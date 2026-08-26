"""Validation-batch driver using the production Orchestrator state machine.

This is intentionally a thin validation-only wrapper around the same
``orchestrator.py`` functions used by ``pilot_driver.py``.  It keeps the
validation state and artifacts under ``runs/validation`` and records all
Reviewer rounds so the initial 120 candidates can be evaluated without
replacement-candidate dilution.

``rebuild_feedback <round_label>`` regenerates a round artifact from the
persisted Candidate Reviewer history if the original artifact write failed.
``init ... --force-reset`` is required to replace an existing state file.
Solver batches are rebuilt from committed state and are rejected when their
state fingerprint is stale. Final artifacts use a staging directory and a
completion manifest so an incomplete publish is not treated as a run. Stage
outputs must match the pending item set; ``--allow-partial`` is an explicit
opt-in for legacy partial workflows, and unversioned legacy state must be
migrated before finalization.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import (  # noqa: E402
    BatchIntegrityTracker,
    build_run_manifest,
    Candidate,
    config_from_run_manifest,
    configured_runtime_root,
    current_version_mismatches,
    State,
    SystemCallError,
    TERMINAL_STATES,
    state_snapshot_digest,
    blind_for_solver,
    build_manual_review_entry,
    build_provenance_record,
    build_review_feedback_from_state,
    build_solver_batch_artifact,
    canonical_solver_input_errors,
    derive_slot_requirements,
    finalization_id,
    load_config,
    load_candidate_state,
    load_state_manifest,
    load_items_by_id,
    load_versions,
    manifest_versions,
    leakage_guard,
    process_generation_output,
    process_review_output,
    process_solver_stage,
    record_stage_failure,
    retry_failed_stage,
    save_candidate_state,
    strip_internal_test_keys,
    validate_final_record,
    validate_solver_batch_artifact,
    validate_stage_item_ids,
)
from shared.json_io import (  # noqa: E402
    JsonPersistenceError,
    atomic_write_json,
    complete_json_bundle,
    exclusive_file_lock,
    exclusive_state_transaction,
    publish_json_bundle,
    read_json,
)
from driver_helpers import apply_generation_result, apply_review_result  # noqa: E402

VALIDATION_DIR = configured_runtime_root() / "validation"
STATE_PATH = VALIDATION_DIR / "validation_candidates_state.json"


def load_state() -> dict[str, Candidate]:
    if not STATE_PATH.exists():
        raise SystemExit(f"No state file at {STATE_PATH}; run init first.")
    return load_candidate_state(STATE_PATH)


def load_state_config() -> dict:
    if not STATE_PATH.exists():
        return load_config()
    manifest = load_state_manifest(STATE_PATH)
    return config_from_run_manifest(manifest) if manifest is not None else load_config()


def save_state(candidates: dict[str, Candidate], run_manifest: dict | None = None) -> None:
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    if run_manifest is None and STATE_PATH.exists():
        run_manifest = load_state_manifest(STATE_PATH)
    if run_manifest is None:
        run_manifest = build_run_manifest(load_config())
    save_candidate_state(STATE_PATH, candidates, run_manifest=run_manifest)


def state_transaction():
    """Lock the full Candidate read-modify-write cycle for this driver."""
    return exclusive_state_transaction(STATE_PATH, load_state, save_state)


def state_tally(candidates: dict[str, Candidate]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for c in candidates.values():
        tally[c.state] = tally.get(c.state, 0) + 1
    return tally


def cmd_init(*batch_paths: str, force_reset: bool = False) -> None:
    if len(batch_paths) != 3:
        raise SystemExit("init requires exactly three batch JSON paths")
    config = load_config()
    run_manifest = build_run_manifest(config)
    gen_items: dict[str, dict] = {}
    for path in batch_paths:
        for item_id, item in load_items_by_id(Path(path), Path(path).name).items():
            if item_id in gen_items:
                raise ValueError(f"duplicate initial item_id across batches: {item_id}")
            gen_items[item_id] = strip_internal_test_keys(item)
    if len(gen_items) != 120:
        raise ValueError(f"initial candidate count must be exactly 120, got {len(gen_items)}")
    sections = {s: sum(1 for x in gen_items.values() if x.get("section") == s) for s in ("Structure", "Written Expression")}
    if sections != {"Structure": 45, "Written Expression": 75}:
        raise ValueError(f"initial section counts mismatch: {sections}")
    if STATE_PATH.exists() and not force_reset:
        raise SystemExit(
            f"Refusing to initialize: existing state file at {STATE_PATH}. "
            "Use init ... --force-reset only when an intentional reset is required."
        )

    candidates: dict[str, Candidate] = {}
    for item_id, item in gen_items.items():
        c = Candidate(item_id=item_id, concept_id=item_id, section=item.get("section", "unknown"))
        c.planned_slot = derive_slot_requirements(item)
        c = apply_generation_result(c, item, config, process_generation_output)
        candidates[item_id] = c
    with exclusive_file_lock(STATE_PATH):
        if STATE_PATH.exists() and not force_reset:
            raise SystemExit(
                f"Refusing to initialize: existing state file at {STATE_PATH}. "
                "Use init ... --force-reset only when an intentional reset is required."
            )
        atomic_write_json(
            VALIDATION_DIR / "validation_initial_items.json",
            {"items": list(gen_items.values())},
        )
        save_state(candidates, run_manifest=run_manifest)
    print(f"Loaded exactly {len(candidates)} initial candidates: {sections}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_apply_review(
    reviewer_path: str, round_label: str, *, allow_partial: bool = False
) -> None:
    config = load_state_config()
    reviewer_items = load_items_by_id(Path(reviewer_path), f"reviewer {round_label}")
    routed: dict[str, list[str]] = {}
    with state_transaction() as candidates:
        batch_errors = validate_stage_item_ids(
            candidates, reviewer_items, "reviewer", allow_partial=allow_partial
        )
        if batch_errors:
            raise ValueError("refusing Reviewer output: " + "; ".join(batch_errors))
        for item_id, c in candidates.items():
            if (
                c.state in {State.GENERATION_FAILED, State.VALIDATION_FAILED}
                and c.failure is not None
                and c.failure.stage == "reviewer"
                and item_id in reviewer_items
            ):
                c = retry_failed_stage(c, config)
            if c.state != State.REVIEWING or item_id not in reviewer_items:
                continue
            c = apply_review_result(c, reviewer_items[item_id], round_label, config, process_review_output)
            routed.setdefault(c.state, []).append(item_id)
        # Compute from the same locked snapshot that is being persisted so a
        # failed artifact write can reproduce this exact feedback later.
        feedback_document = build_review_feedback_from_state(candidates, round_label)
    atomic_write_json(
        VALIDATION_DIR / f"validation_round_feedback_{round_label}.json",
        feedback_document,
    )
    print(f"Applied Reviewer {round_label}: { {k: len(v) for k, v in routed.items()} }")
    print(f"State tally: {state_tally(candidates)}")


def cmd_rebuild_feedback(round_label: str) -> None:
    """Idempotently rebuild one Reviewer round's feedback from Candidate state."""
    with exclusive_file_lock(STATE_PATH):
        candidates = load_state()
        feedback_document = build_review_feedback_from_state(candidates, round_label)
    feedback_path = VALIDATION_DIR / f"validation_round_feedback_{round_label}.json"
    atomic_write_json(feedback_path, feedback_document)
    print(
        f"Rebuilt {len(feedback_document['items'])} REVISE feedback record(s) "
        f"for round '{round_label}' at {feedback_path}"
    )


def cmd_apply_revision(generator_path: str, *, allow_partial: bool = False) -> None:
    config = load_state_config()
    revised_items = load_items_by_id(Path(generator_path), "generator revision")
    updated = []
    with state_transaction() as candidates:
        batch_errors = validate_stage_item_ids(
            candidates, revised_items, "revision", allow_partial=allow_partial
        )
        if batch_errors:
            raise ValueError("refusing Generator revision output: " + "; ".join(batch_errors))
        for item_id, raw in revised_items.items():
            c = candidates.get(item_id)
            is_revision = c is not None and c.state == State.REVISE_REQUIRED
            is_generator_retry = (
                c is not None
                and c.state in {State.GENERATION_FAILED, State.VALIDATION_FAILED}
                and c.failure is not None
                and c.failure.stage == "generator"
            )
            if c is None or not (is_revision or is_generator_retry):
                if allow_partial:
                    continue
                raise ValueError(f"revision item_id {item_id!r} is not currently eligible")
            if is_generator_retry:
                c = retry_failed_stage(c, config)
            else:
                c.reviewer_item = None
                c.solver_item = None
                c.solver_input = None
                c.leakage_check = None
                c.consensus = None
                c.failure = None
                c.transition(State.GENERATED, "Reviewer-requested revision regenerated")
            if is_revision:
                c.generation_attempt += 1
            c = apply_generation_result(c, raw, config, process_generation_output)
            candidates[item_id] = c
            updated.append(item_id)
    print(f"Applied revisions: {len(updated)}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_prepare_solver_batch() -> None:
    config = load_state_config()
    batch = []
    out_path = VALIDATION_DIR / "validation_solver_input_batch.json"
    with state_transaction() as candidates:
        for c in candidates.values():
            if (
                c.state in {State.GENERATION_FAILED, State.VALIDATION_FAILED}
                and c.failure is not None
                and c.failure.stage == "solver"
            ):
                c = retry_failed_stage(c, config)
            if c.state != State.SOLVING:
                continue
            try:
                blinded = (
                    c.solver_input
                    if c.solver_input is not None
                    else blind_for_solver(config, c.generator_item)
                )
            except SystemCallError as exc:
                c.solver_input = None
                record_stage_failure(
                    c,
                    config,
                    kind="system",
                    stage="solver",
                    detail=f"during blinding: {exc}",
                )
                continue
            ok, problems = leakage_guard(blinded, c.section)
            c.leakage_check = {
                "ok": ok, "problems": problems, "blinded_keys": sorted(blinded.keys())
            }
            if not ok:
                c.solver_input = None
                c.transition(State.MANUAL_REVIEW, f"leakage guard failed before Solver: {problems}")
                continue
            canonical_errors = canonical_solver_input_errors(config, c.generator_item, blinded)
            if canonical_errors:
                c.solver_input = None
                record_stage_failure(
                    c,
                    config,
                    kind="content",
                    stage="solver",
                    detail="; ".join(canonical_errors),
                )
                continue
            c.solver_input = blinded
            batch.append(blinded)
        # Commit the state before publishing the derived artifact. A later
        # artifact-write failure is recoverable by rebuilding from this state.
    committed = load_state()
    artifact = build_solver_batch_artifact(committed, config)
    atomic_write_json(out_path, artifact)
    print(f"Prepared blinded Solver batch: {len(batch)}")


def cmd_apply_solver(solver_path: str, *, allow_partial: bool = False) -> None:
    config = load_state_config()
    solver_items = load_items_by_id(Path(solver_path), "solver output")
    applied_count = 0
    with state_transaction() as candidates:
        batch_errors = validate_stage_item_ids(
            candidates, solver_items, "solver", allow_partial=allow_partial
        )
        if batch_errors:
            raise ValueError("refusing Solver output: " + "; ".join(batch_errors))
        try:
            batch_artifact = read_json(VALIDATION_DIR / "validation_solver_input_batch.json")
        except JsonPersistenceError as exc:
            raise ValueError(f"refusing Solver output: current Solver batch is unreadable: {exc}") from exc
        batch_errors = validate_solver_batch_artifact(batch_artifact, candidates, config)
        if batch_errors:
            raise ValueError(
                "refusing Solver output: Solver batch is missing, stale, or tampered: "
                + "; ".join(batch_errors)
            )
        for item_id, c in candidates.items():
            if (
                c.state in {State.GENERATION_FAILED, State.VALIDATION_FAILED}
                and c.failure is not None
                and c.failure.stage == "solver"
                and c.solver_input is not None
                and item_id in solver_items
            ):
                c = retry_failed_stage(c, config)
            if c.state == State.SOLVING and c.solver_input is not None and item_id in solver_items:
                c.solver_item = strip_internal_test_keys(solver_items[item_id])
                c = process_solver_stage(
                    c,
                    config,
                    c.solver_item,
                    precomputed_solver_input=c.solver_input,
                )
                candidates[item_id] = c
                applied_count += 1
    print(f"Applied Solver outputs: {applied_count} (supplied: {len(solver_items)})")
    print(f"State tally: {state_tally(candidates)}")


def cmd_finalize() -> None:
    config = load_state_config()
    run_manifest = load_state_manifest(STATE_PATH) if STATE_PATH.exists() else None
    versions = (
        load_versions(config)
        if run_manifest is None
        else manifest_versions(run_manifest)
    )
    candidates = load_state()
    legacy_candidates = sorted(
        candidate.item_id for candidate in candidates.values() if candidate.legacy_compatibility
    )
    if legacy_candidates:
        raise ValueError(
            "validation finalize refused; legacy compatibility state requires migration to the "
            f"current state format: {legacy_candidates}"
        )
    nonterminal = sorted(
        (candidate.item_id, candidate.state)
        for candidate in candidates.values()
        if candidate.state not in TERMINAL_STATES
    )
    if nonterminal:
        detail = ", ".join(f"{item_id}={state}" for item_id, state in nonterminal)
        raise ValueError(f"validation finalize refused; nonterminal candidates remain: {detail}")
    tracker = BatchIntegrityTracker()
    provenance = []
    accepted = []
    manual = []
    failures = []
    for c in candidates.values():
        if c.generator_item is not None:
            tracker.record_planned(c.generator_item, c.planned_slot)
        rec = build_provenance_record(c, versions, run_manifest=run_manifest)
        rec["validation_trace"] = {
            "initial_candidate": True,
            "generation_history": c.generation_history,
            "review_history": c.review_history,
        }
        provenance.append(rec)
        if c.state == State.ACCEPTED:
            accepted.append(rec["accepted_item"])
            tracker.record_accepted(c.generator_item)
        elif c.state == State.MANUAL_REVIEW:
            manual.append(build_manual_review_entry(c))
            failures.append(rec)
        elif c.state in {State.REJECTED, State.DISCARDED, State.VALIDATION_FAILED, State.GENERATION_FAILED}:
            failures.append(rec)
    wrapper = {
        "pipeline_version": config["pipeline_version"],
        "initial_candidate_count": len(candidates),
        "replacement_candidates_included": 0,
        "versions": versions,
        "run_manifest": run_manifest,
        "items": provenance,
        "batch_summary": tracker.summary(),
    }
    for record in provenance:
        final_errors = validate_final_record(record)
        if final_errors:
            raise ValueError(
                f"final artifact schema validation failed for {record['item_id']}: "
                + "; ".join(final_errors)
            )
    run_id = finalization_id(candidates, versions)
    state_digest = state_snapshot_digest(candidates, run_manifest=run_manifest)
    wrapper["finalize_id"] = run_id
    wrapper["state_digest"] = state_digest
    artifacts = {
        "provenance": ("validation_provenance.json", wrapper),
        "accepted": ("validation_accepted_items.json", {"finalize_id": run_id, "state_digest": state_digest, "items": accepted}),
        "manual_review": ("validation_manual_review.json", {"finalize_id": run_id, "state_digest": state_digest, "items": manual}),
        "failures": ("validation_failure_items.json", {"finalize_id": run_id, "state_digest": state_digest, "items": failures}),
    }
    # Re-check and hold the state lock while publishing. A concurrent stage
    # update must make this snapshot stale rather than producing a mixed run.
    with exclusive_file_lock(STATE_PATH):
        current_candidates = load_state()
        current_manifest = load_state_manifest(STATE_PATH) if run_manifest is not None else None
        if (
            finalization_id(current_candidates, versions) != run_id
            or state_snapshot_digest(current_candidates, run_manifest=current_manifest) != state_digest
        ):
            raise ValueError("validation finalize snapshot is stale; rerun finalize")
        if run_manifest is not None and current_manifest != run_manifest:
            raise ValueError("validation run manifest changed; refusing mixed finalization")
        manifest = publish_json_bundle(
            VALIDATION_DIR,
            artifacts,
            finalize_id=run_id,
            manifest_name="validation_finalize_manifest.json",
            metadata={
                "state_digest": state_digest,
                "manual_review_item_ids": sorted(entry["item_id"] for entry in manual),
            },
        )
        complete_json_bundle(VALIDATION_DIR, manifest, manifest_name="validation_finalize_manifest.json")
    print(f"Finalized {len(candidates)} initial candidates")
    print(f"State tally: {state_tally(candidates)}")
    print(f"Finalize id: {run_id}")
    if run_manifest is not None:
        mismatches = current_version_mismatches(run_manifest)
        if mismatches:
            print(f"WARNING: current files differ from the run snapshot: {', '.join(mismatches)}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "init":
        force_reset = args.count("--force-reset")
        if force_reset > 1:
            raise SystemExit("init accepts --force-reset at most once")
        args = [arg for arg in args if arg != "--force-reset"]
        cmd_init(*args, force_reset=bool(force_reset))
    elif cmd == "apply_review":
        allow_partial = args.count("--allow-partial")
        if allow_partial > 1:
            raise SystemExit("apply_review accepts --allow-partial at most once")
        args = [arg for arg in args if arg != "--allow-partial"]
        cmd_apply_review(*args, allow_partial=bool(allow_partial))
    elif cmd == "rebuild_feedback":
        cmd_rebuild_feedback(*args)
    elif cmd == "apply_revision":
        allow_partial = args.count("--allow-partial")
        if allow_partial > 1:
            raise SystemExit("apply_revision accepts --allow-partial at most once")
        args = [arg for arg in args if arg != "--allow-partial"]
        cmd_apply_revision(*args, allow_partial=bool(allow_partial))
    elif cmd == "prepare_solver_batch":
        cmd_prepare_solver_batch()
    elif cmd == "apply_solver":
        allow_partial = args.count("--allow-partial")
        if allow_partial > 1:
            raise SystemExit("apply_solver accepts --allow-partial at most once")
        args = [arg for arg in args if arg != "--allow-partial"]
        cmd_apply_solver(*args, allow_partial=bool(allow_partial))
    elif cmd == "finalize":
        cmd_finalize()
    else:
        print(f"Unknown subcommand: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
