"""Validation-batch driver using the production Orchestrator state machine.

This is intentionally a thin validation-only wrapper around the same
``orchestrator.py`` functions used by ``pilot_driver.py``.  It keeps the
validation state and artifacts under ``analysis/validation`` and records all
Reviewer rounds so the initial 120 candidates can be evaluated without
replacement-candidate dilution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import (  # noqa: E402
    BatchIntegrityTracker,
    Candidate,
    REPO_ROOT,
    State,
    SystemCallError,
    TERMINAL_STATES,
    blind_for_solver,
    build_generator_feedback,
    build_manual_review_entry,
    build_provenance_record,
    derive_slot_requirements,
    load_config,
    load_candidate_state,
    load_items_by_id,
    load_versions,
    leakage_guard,
    process_generation_output,
    process_review_output,
    process_solver_stage,
    record_stage_failure,
    retry_failed_stage,
    save_candidate_state,
    strip_internal_test_keys,
    validate_final_record,
)
from shared.json_io import (  # noqa: E402
    atomic_write_json,
    exclusive_file_lock,
    exclusive_state_transaction,
)

VALIDATION_DIR = REPO_ROOT / "analysis" / "validation"
STATE_PATH = VALIDATION_DIR / "validation_candidates_state.json"


def load_state() -> dict[str, Candidate]:
    if not STATE_PATH.exists():
        raise SystemExit(f"No state file at {STATE_PATH}; run init first.")
    return load_candidate_state(STATE_PATH)


def save_state(candidates: dict[str, Candidate]) -> None:
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    save_candidate_state(STATE_PATH, candidates)


def state_transaction():
    """Lock the full Candidate read-modify-write cycle for this driver."""
    return exclusive_state_transaction(STATE_PATH, load_state, save_state)


def state_tally(candidates: dict[str, Candidate]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for c in candidates.values():
        tally[c.state] = tally.get(c.state, 0) + 1
    return tally


def cmd_init(*batch_paths: str) -> None:
    if len(batch_paths) != 3:
        raise SystemExit("init requires exactly three batch JSON paths")
    config = load_config()
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

    atomic_write_json(
        VALIDATION_DIR / "validation_initial_items.json",
        {"items": list(gen_items.values())},
    )
    candidates: dict[str, Candidate] = {}
    for item_id, item in gen_items.items():
        c = Candidate(item_id=item_id, concept_id=item_id, section=item.get("section", "unknown"))
        c.generator_item = item
        c.planned_slot = derive_slot_requirements(item)
        c.generation_history = [{"attempt": 1, "item": item}]
        c = process_generation_output(c, config)
        candidates[item_id] = c
    with exclusive_file_lock(STATE_PATH):
        save_state(candidates)
    print(f"Loaded exactly {len(candidates)} initial candidates: {sections}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_apply_review(reviewer_path: str, round_label: str) -> None:
    config = load_config()
    reviewer_items = load_items_by_id(Path(reviewer_path), f"reviewer {round_label}")
    routed: dict[str, list[str]] = {}
    with state_transaction() as candidates:
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
            reviewer_item = strip_internal_test_keys(reviewer_items[item_id])
            c.review_history.append({"round": round_label, "output": reviewer_item})
            c.reviewer_item = reviewer_item
            c = process_review_output(c, config)
            routed.setdefault(c.state, []).append(item_id)
        feedback = [
            build_generator_feedback(candidates[item_id].reviewer_item)
            for item_id in routed.get(State.REVISE_REQUIRED, [])
        ]
    atomic_write_json(
        VALIDATION_DIR / f"validation_round_feedback_{round_label}.json",
        {"items": feedback},
    )
    print(f"Applied Reviewer {round_label}: { {k: len(v) for k, v in routed.items()} }")
    print(f"State tally: {state_tally(candidates)}")


def cmd_apply_revision(generator_path: str) -> None:
    config = load_config()
    revised_items = load_items_by_id(Path(generator_path), "generator revision")
    updated = []
    with state_transaction() as candidates:
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
                continue
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
            item = strip_internal_test_keys(raw)
            c.generator_item = item
            if is_revision:
                c.generation_attempt += 1
            c.generation_history.append({"attempt": c.generation_attempt, "item": item})
            c = process_generation_output(c, config)
            candidates[item_id] = c
            updated.append(item_id)
    print(f"Applied revisions: {len(updated)}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_prepare_solver_batch() -> None:
    config = load_config()
    batch = []
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
            c.solver_input = blinded
            batch.append(blinded)
        atomic_write_json(VALIDATION_DIR / "validation_solver_input_batch.json", {"items": batch})
    print(f"Prepared blinded Solver batch: {len(batch)}")


def cmd_apply_solver(solver_path: str) -> None:
    config = load_config()
    solver_items = load_items_by_id(Path(solver_path), "solver output")
    with state_transaction() as candidates:
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
    print(f"Applied Solver outputs: {len(solver_items)} supplied")
    print(f"State tally: {state_tally(candidates)}")


def cmd_finalize() -> None:
    config = load_config()
    versions = load_versions(config)
    candidates = load_state()
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
        rec = build_provenance_record(c, versions)
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
    atomic_write_json(VALIDATION_DIR / "validation_provenance.json", wrapper)
    atomic_write_json(VALIDATION_DIR / "validation_accepted_items.json", {"items": accepted})
    atomic_write_json(VALIDATION_DIR / "validation_manual_review.json", {"items": manual})
    atomic_write_json(VALIDATION_DIR / "validation_failure_items.json", {"items": failures})
    print(f"Finalized {len(candidates)} initial candidates")
    print(f"State tally: {state_tally(candidates)}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "init":
        cmd_init(*args)
    elif cmd == "apply_review":
        cmd_apply_review(*args)
    elif cmd == "apply_revision":
        cmd_apply_revision(*args)
    elif cmd == "prepare_solver_batch":
        cmd_prepare_solver_batch()
    elif cmd == "apply_solver":
        cmd_apply_solver(*args)
    elif cmd == "finalize":
        cmd_finalize()
    else:
        print(f"Unknown subcommand: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
