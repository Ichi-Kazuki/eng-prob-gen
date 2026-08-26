"""Pilot Batch live-run driver.

This is the "live call sites" wiring documented in
orchestrator/TOEFL_ITP_GRAMMAR_PIPELINE.md section 6. It contains NO
grammar/quality judgement of its own - it only:

  - loads live Generator/Reviewer/Solver agent output files (produced by
    real Agent-tool calls made by the conductor, outside this script)
  - feeds them through the existing orchestrator.py engine functions
    (process_generation_output / process_review_output / process_solver_stage
    / build_generator_feedback / evaluate_consensus / build_provenance_record
    / build_manual_review_entry) exactly as run_smoke_test.py does for
    fixture replay
  - persists Candidate state as JSON between pipeline stages, since each
    invocation of this script is a fresh process and the actual agent calls
    happen between invocations (via the Agent tool, not from Python)

Subcommands (each reads/writes runs/pilot/candidates_state.json):

  init <structure_gen.json> <we_gen.json>
      Merge + validate the initial Generator output, create Candidates,
      run process_generation_output(). Prints which item_ids are ready for
      Reviewer round 1 and which failed schema validation.

  apply_review <reviewer_output.json> <round_label> [--allow-partial]
      Feed a Reviewer output file (item_id-keyed) to process_review_output()
      for every expected candidate. The Reviewer must have been given the
      canonical reviewer_input_batch.json produced by init or
      prepare_reviewer_batch. Output IDs must match the pending batch by
      default; ``--allow-partial`` is an explicit compatibility opt-in. Prints
      routing summary and writes runs/pilot/round_feedback_<round_label>.json
      (allowlisted Generator feedback for any REVISE_REQUIRED candidates).

  rebuild_feedback <round_label>
      Rebuild the round feedback artifact idempotently from persisted
      Candidate Reviewer history after an earlier artifact write failed.

  apply_revision <generator_output.json> [--allow-partial]
      Feed a revised Generator output file to process_generation_output()
      for every expected candidate, moving it back to REVIEWING (or
      VALIDATION_FAILED) for the next Reviewer round. Partial application
      requires the explicit ``--allow-partial`` opt-in.

  prepare_solver_batch
      Blind every candidate currently in SOLVING via the shared pure
      projection (through orchestrator.blind_for_solver()), commit Candidate
      state first, and then rebuild the state-bound batch artifact at
      runs/pilot/solver_input_batch.json.

  prepare_reviewer_batch
      Rebuild the canonical, state-bound phase-1 Reviewer payload at
      runs/pilot/reviewer_input_batch.json.

  apply_solver <solver_output.json> [--allow-partial]
      Feed a Solver output file to process_solver_stage() for every
      candidate currently in SOLVING. Output IDs must match the pending batch
      by default; partial application requires ``--allow-partial``. Prints
      final state tally.

  finalize
      Build provenance/accepted/manual-review/failure artifacts for the
      completed current-format terminal candidate set and write them to
      runs/pilot/pilot_provenance.json, pilot_accepted_items.json,
      pilot_manual_review.json, pilot_failure_items.json through a staged
      run bundle. Also appends MANUAL_REVIEW entries to
      runs/manual_review_queue.json via the existing
      append_manual_review_queue(), before committing the completion marker.
      Unversioned legacy state must be migrated before finalization.

Usage: python orchestrator/scripts/pilot_driver.py <subcommand> [args...]
       init ... --force-reset  (explicitly replace an existing state file)
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import (  # noqa: E402
    BatchIntegrityTracker,
    build_run_manifest,
    Candidate,
    config_from_run_manifest,
    configured_runtime_root,
    ensure_pipeline_snapshot_current,
    State,
    SystemCallError,
    TERMINAL_STATES,
    state_snapshot_digest,
    validate_final_record,
    blind_for_solver,
    build_manual_review_entry,
    build_provenance_record,
    build_review_feedback_from_state,
    build_reviewer_batch_artifact,
    build_solver_batch_artifact,
    canonical_solver_input_errors,
    derive_slot_requirements,
    finalization_id,
    leakage_guard,
    load_config,
    load_candidate_state,
    load_state_manifest,
    load_items_by_id,
    load_versions,
    manifest_versions,
    process_generation_output,
    process_review_output,
    process_solver_stage,
    record_stage_failure,
    retry_failed_stage,
    save_candidate_state,
    strip_internal_test_keys,
    validate_solver_batch_artifact,
    validate_reviewer_batch_artifact,
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

PILOT_DIR = configured_runtime_root() / "pilot"
STATE_PATH = PILOT_DIR / "candidates_state.json"
REVIEWER_BATCH_FILENAME = "reviewer_input_batch.json"


def load_state() -> dict[str, Candidate]:
    if not STATE_PATH.exists():
        raise SystemExit(f"No state file at {STATE_PATH}; run 'init' first.")
    return load_candidate_state(STATE_PATH)


def load_state_config() -> dict:
    if not STATE_PATH.exists():
        return load_config()
    manifest = load_state_manifest(STATE_PATH)
    current_config = load_config()
    if manifest is None:
        return current_config
    ensure_pipeline_snapshot_current(manifest, current_config)
    return config_from_run_manifest(manifest)


def save_state(candidates: dict[str, Candidate], run_manifest: dict | None = None) -> None:
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    if run_manifest is None and STATE_PATH.exists():
        run_manifest = load_state_manifest(STATE_PATH)
    if run_manifest is None:
        run_manifest = build_run_manifest(load_config())
    for candidate in candidates.values():
        if candidate.planned_slot is None and candidate.generator_item is not None:
            candidate.planned_slot = derive_slot_requirements(candidate.generator_item)
    save_candidate_state(STATE_PATH, candidates, run_manifest=run_manifest)
    atomic_write_json(reviewer_batch_path(), build_reviewer_batch_artifact(candidates))


def state_transaction():
    """Lock the full Candidate read-modify-write cycle for this driver."""
    return exclusive_state_transaction(STATE_PATH, load_state, save_state)


def reviewer_batch_path() -> Path:
    return PILOT_DIR / REVIEWER_BATCH_FILENAME


def write_reviewer_batch() -> None:
    """Publish the current canonical Reviewer batch from a locked snapshot."""
    with exclusive_file_lock(STATE_PATH):
        candidates = load_state()
        artifact = build_reviewer_batch_artifact(candidates)
        atomic_write_json(reviewer_batch_path(), artifact)


def validate_reviewer_batch_if_present(candidates: dict[str, Candidate]) -> None:
    """Reject a present stale/tampered precomputed Reviewer input artifact."""
    path = reviewer_batch_path()
    if not path.exists():
        # A current run is initialized with this artifact.  Only unmanifested
        # legacy/direct-call state may omit it; silently falling back to raw
        # Generator state would reopen the prompt-only blinding boundary.
        if load_state_manifest(STATE_PATH) is not None:
            raise ValueError(
                "refusing Reviewer output: canonical Reviewer batch is missing"
            )
        return
    try:
        artifact = read_json(path)
    except JsonPersistenceError as exc:
        raise ValueError(f"refusing Reviewer output: current Reviewer batch is unreadable: {exc}") from exc
    errors = validate_reviewer_batch_artifact(artifact, candidates)
    if errors:
        raise ValueError(
            "refusing Reviewer output: Reviewer batch is missing, stale, or tampered: "
            + "; ".join(errors)
        )


def state_tally(candidates: dict[str, Candidate]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for c in candidates.values():
        tally[c.state] = tally.get(c.state, 0) + 1
    return tally


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_init(structure_path: str, we_path: str, *, force_reset: bool = False) -> None:
    config = load_config()
    run_manifest = build_run_manifest(config)
    gen_items: dict[str, dict] = {}
    structure_items = load_items_by_id(Path(structure_path), "structure generator round1")
    written_expression_items = load_items_by_id(Path(we_path), "we generator round1")
    duplicates = sorted(set(structure_items) & set(written_expression_items))
    if duplicates:
        raise ValueError(f"duplicate initial item_id across pilot batches: {duplicates}")
    gen_items.update(structure_items)
    gen_items.update(written_expression_items)
    if STATE_PATH.exists() and not force_reset:
        raise SystemExit(
            f"Refusing to initialize: existing state file at {STATE_PATH}. "
            "Use init ... --force-reset only when an intentional reset is required."
        )

    candidates: dict[str, Candidate] = {}
    for item_id, gitem in gen_items.items():
        gitem = strip_internal_test_keys(gitem)
        c = Candidate(item_id=item_id, concept_id=item_id, section=gitem.get("section", "unknown"))
        c.planned_slot = derive_slot_requirements(gitem)
        c = apply_generation_result(c, gitem, config, process_generation_output)
        candidates[item_id] = c

    with exclusive_file_lock(STATE_PATH):
        if STATE_PATH.exists() and not force_reset:
            raise SystemExit(
                f"Refusing to initialize: existing state file at {STATE_PATH}. "
                "Use init ... --force-reset only when an intentional reset is required."
            )
        atomic_write_json(
            PILOT_DIR / "pilot_initial_items.json",
            {"items": list(gen_items.values())},
        )
        save_state(candidates, run_manifest=run_manifest)

    ready = sorted(i for i, c in candidates.items() if c.state == State.REVIEWING)
    failed = sorted(i for i, c in candidates.items() if c.state != State.REVIEWING)
    print(f"Loaded {len(candidates)} candidates ({len(gen_items)} generator records).")
    print(f"Ready for Reviewer round 1 ({len(ready)}): {ready}")
    if failed:
        print(f"NOT ready (schema validation issue) ({len(failed)}):")
        for i in failed:
            c = candidates[i]
            print(f"  {i}: state={c.state} failure={c.failure}")


def cmd_apply_review(
    reviewer_path: str, round_label: str, *, allow_partial: bool = False
) -> None:
    config = load_state_config()
    reviewer_items = load_items_by_id(Path(reviewer_path), f"reviewer round {round_label}")

    routed: dict[str, list[str]] = {}
    with state_transaction() as candidates:
        validate_reviewer_batch_if_present(candidates)
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
        # Build from the same locked in-memory snapshot that is about to be
        # persisted. If the following artifact write fails, this exact
        # document remains reproducible from state.
        feedback_document = build_review_feedback_from_state(candidates, round_label)
    feedback_path = PILOT_DIR / f"round_feedback_{round_label}.json"
    atomic_write_json(feedback_path, feedback_document)
    write_reviewer_batch()

    applied_count = sum(len(ids) for ids in routed.values())
    print(f"Reviewer round '{round_label}' applied: {applied_count} (supplied: {len(reviewer_items)}).")
    for state, ids in routed.items():
        if ids:
            print(f"  {state} ({len(ids)}): {sorted(ids)}")
    print(f"Wrote {len(feedback_document['items'])} REVISE feedback record(s) (issues+revision_requirements only) to {feedback_path}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_rebuild_feedback(round_label: str) -> None:
    """Idempotently rebuild one round's feedback from persisted Candidate state."""
    load_state_config()
    with exclusive_file_lock(STATE_PATH):
        candidates = load_state()
        feedback_document = build_review_feedback_from_state(candidates, round_label)
    feedback_path = PILOT_DIR / f"round_feedback_{round_label}.json"
    atomic_write_json(feedback_path, feedback_document)
    print(
        f"Rebuilt {len(feedback_document['items'])} REVISE feedback record(s) "
        f"for round '{round_label}' at {feedback_path}"
    )


def cmd_apply_revision(generator_path: str, *, allow_partial: bool = False) -> None:
    config = load_state_config()
    revised_items = load_items_by_id(Path(generator_path), "generator revision round")

    updated = []
    with state_transaction() as candidates:
        batch_errors = validate_stage_item_ids(
            candidates, revised_items, "revision", allow_partial=allow_partial
        )
        if batch_errors:
            raise ValueError("refusing Generator revision output: " + "; ".join(batch_errors))
        for item_id, gitem in revised_items.items():
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
                # A revision is a quality-driven new Generator attempt. It is
                # intentionally distinct from transient failure retry counters.
                c.reviewer_item = None
                c.reviewer_input = None
                c.reviewer_input_sha256 = None
                c.solver_item = None
                c.solver_input = None
                c.leakage_check = None
                c.consensus = None
                c.failure = None
                c.transition(State.GENERATED, "Reviewer-requested revision regenerated")
            if is_revision:
                c.generation_attempt += 1
            c = apply_generation_result(c, gitem, config, process_generation_output)
            updated.append(item_id)

    write_reviewer_batch()

    print(f"Applied revision to {len(updated)} candidate(s): {sorted(updated)}")
    ready = sorted(i for i in updated if candidates[i].state == State.REVIEWING)
    print(f"Ready for next Reviewer round ({len(ready)}): {ready}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_prepare_solver_batch() -> None:
    config = load_state_config()
    batch = []
    errors = []
    out_path = PILOT_DIR / "solver_input_batch.json"
    with state_transaction() as candidates:
        solving = {}
        for item_id, c in candidates.items():
            if (
                c.state in {State.GENERATION_FAILED, State.VALIDATION_FAILED}
                and c.failure is not None
                and c.failure.stage == "solver"
            ):
                c = retry_failed_stage(c, config)
            if c.state == State.SOLVING:
                solving[item_id] = c

        for item_id, c in solving.items():
            try:
                blinded = c.solver_input if c.solver_input is not None else blind_for_solver(config, c.generator_item)
            except SystemCallError as exc:
                c.solver_input = None
                record_stage_failure(
                    c,
                    config,
                    kind="system",
                    stage="solver",
                    detail=f"during blinding: {exc}",
                )
                errors.append(f"{item_id}: {exc}")
                continue
            ok, problems = leakage_guard(blinded, c.section)
            c.leakage_check = {
                "ok": ok, "problems": problems, "blinded_keys": sorted(blinded.keys())
            }
            if not ok:
                c.solver_input = None
                c.transition(State.MANUAL_REVIEW, f"leakage guard failed before Solver: {problems}")
                errors.append(f"{item_id}: leakage guard failed: {problems}")
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
                errors.append(f"{item_id}: {'; '.join(canonical_errors)}")
                continue
            c.solver_input = blinded
            batch.append(blinded)
        # The transaction commits the state first. The derived batch is
        # rebuilt from that committed state below, so a failed artifact write
        # cannot make an uncommitted payload look authoritative.
    committed = load_state()
    artifact = build_solver_batch_artifact(committed, config)
    atomic_write_json(out_path, artifact)
    print(f"Blinded {len(batch)} candidate(s) currently in SOLVING -> {out_path}")
    if errors:
        print("Blinding errors:")
        for error in errors:
            print(f"  {error}")
    print(f"item_ids: {sorted(solving.keys())}")


def cmd_prepare_reviewer_batch() -> None:
    """Rebuild the canonical phase-1 Reviewer input artifact."""
    load_state_config()
    write_reviewer_batch()
    print(f"Prepared canonical Reviewer batch -> {reviewer_batch_path()}")


def cmd_apply_solver(solver_path: str, *, allow_partial: bool = False) -> None:
    config = load_state_config()
    solver_items = load_items_by_id(Path(solver_path), "solver output")

    routed: dict[str, list[str]] = {}
    with state_transaction() as candidates:
        batch_errors = validate_stage_item_ids(
            candidates, solver_items, "solver", allow_partial=allow_partial
        )
        if batch_errors:
            raise ValueError("refusing Solver output: " + "; ".join(batch_errors))
        try:
            batch_artifact = read_json(PILOT_DIR / "solver_input_batch.json")
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
            if c.state != State.SOLVING or c.solver_input is None:
                continue
            s_item = solver_items.get(item_id)
            if s_item is None:
                if allow_partial:
                    continue
                raise ValueError(f"solver output is missing expected item_id {item_id!r}")
            c = process_solver_stage(
                c,
                config,
                strip_internal_test_keys(s_item),
                precomputed_solver_input=c.solver_input,
            )
            routed.setdefault(c.state, []).append(item_id)
    applied_count = sum(len(ids) for ids in routed.values())
    print(f"Solver output applied: {applied_count} (supplied: {len(solver_items)}). Routing:")
    for state, ids in routed.items():
        print(f"  {state} ({len(ids)}): {sorted(ids)}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_finalize() -> None:
    config = load_state_config()
    # Acquire the first state snapshot under the same exclusive lock used by
    # stage transactions. Artifact construction happens after unlock, then
    # the commit phase below rechecks this exact snapshot digest.
    with exclusive_file_lock(STATE_PATH):
        candidates = load_state()
        run_manifest = load_state_manifest(STATE_PATH) if STATE_PATH.exists() else None
        if run_manifest is not None:
            ensure_pipeline_snapshot_current(run_manifest, config)
        candidates = copy.deepcopy(candidates)
        state_digest = state_snapshot_digest(candidates, run_manifest=run_manifest)
    versions = load_versions(config) if run_manifest is None else manifest_versions(run_manifest)

    legacy_candidates = sorted(
        candidate.item_id for candidate in candidates.values() if candidate.legacy_compatibility
    )
    if legacy_candidates:
        raise ValueError(
            "pilot finalize refused; legacy compatibility state requires migration to the "
            f"current state format: {legacy_candidates}"
        )

    nonterminal = sorted(
        (candidate.item_id, candidate.state)
        for candidate in candidates.values()
        if candidate.state not in TERMINAL_STATES
    )
    if nonterminal:
        detail = ", ".join(f"{item_id}={state}" for item_id, state in nonterminal)
        raise ValueError(f"pilot finalize refused; nonterminal candidates remain: {detail}")

    tracker = BatchIntegrityTracker()
    provenance_records = []
    accepted_items = []
    manual_review_entries = []
    failure_items = []

    for item_id, c in candidates.items():
        if c.generator_item is not None:
            tracker.record_planned(c.generator_item, c.planned_slot)
        rec = build_provenance_record(c, versions, run_manifest=run_manifest)
        provenance_records.append(rec)
        if c.state == State.ACCEPTED:
            if c.generator_item is None:
                raise ValueError(f"accepted candidate {c.item_id} is missing generator_item")
            accepted_items.append(rec["accepted_item"])
            tracker.record_accepted(c.generator_item)
        elif c.state == State.MANUAL_REVIEW:
            manual_review_entries.append(build_manual_review_entry(c))
            failure_items.append(rec)
        elif c.state in (State.REJECTED, State.DISCARDED, State.VALIDATION_FAILED, State.GENERATION_FAILED):
            failure_items.append(rec)

    for record in provenance_records:
        final_errors = validate_final_record(record)
        if final_errors:
            raise ValueError(
                f"final artifact schema validation failed for {record['item_id']}: "
                + "; ".join(final_errors)
            )
    run_id = finalization_id(candidates, versions)
    artifacts = {
        "provenance": ("pilot_provenance.json", {
            "pipeline_version": config["pipeline_version"],
            "finalize_id": run_id,
            "state_digest": state_digest,
            "run_manifest": run_manifest,
            "items": provenance_records,
            "batch_summary": tracker.summary(),
        }),
        "accepted": ("pilot_accepted_items.json", {"finalize_id": run_id, "state_digest": state_digest, "items": accepted_items}),
        "manual_review": ("pilot_manual_review.json", {"finalize_id": run_id, "state_digest": state_digest, "items": manual_review_entries}),
        "failures": ("pilot_failure_items.json", {"finalize_id": run_id, "state_digest": state_digest, "items": failure_items}),
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
            raise ValueError("pilot finalize snapshot is stale; rerun finalize")
        if run_manifest is not None and current_manifest != run_manifest:
            raise ValueError("pilot run manifest changed; refusing mixed finalization")
        if current_manifest is not None:
            ensure_pipeline_snapshot_current(current_manifest, config)
        manifest = publish_json_bundle(
            PILOT_DIR,
            artifacts,
            finalize_id=run_id,
            manifest_name="pilot_finalize_manifest.json",
            metadata={
                "state_digest": state_digest,
                "manual_review_item_ids": sorted(entry["item_id"] for entry in manual_review_entries),
            },
        )

        if manual_review_entries:
            from orchestrator import append_manual_review_queue
            append_manual_review_queue(config, manual_review_entries)
        complete_json_bundle(PILOT_DIR, manifest, manifest_name="pilot_finalize_manifest.json")

    print(f"Finalized {len(candidates)} candidates.")
    print(f"State tally: {state_tally(candidates)}")
    print(f"ACCEPTED: {len(accepted_items)}  MANUAL_REVIEW: {len(manual_review_entries)}  failure_items: {len(failure_items)}")
    print(f"Finalize id: {run_id}")
    print("Wrote: pilot_provenance.json, pilot_accepted_items.json, pilot_manual_review.json, pilot_failure_items.json")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    args = sys.argv[2:]
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
    elif cmd == "prepare_reviewer_batch":
        cmd_prepare_reviewer_batch()
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
