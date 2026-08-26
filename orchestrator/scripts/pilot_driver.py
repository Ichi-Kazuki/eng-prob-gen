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

Subcommands (each reads/writes analysis/pilot/candidates_state.json):

  init <structure_gen.json> <we_gen.json>
      Merge + validate the initial Generator output, create Candidates,
      run process_generation_output(). Prints which item_ids are ready for
      Reviewer round 1 and which failed schema validation.

  apply_review <reviewer_output.json> <round_label>
      Feed a Reviewer output file (item_id-keyed) to process_review_output()
      for every candidate currently in REVIEWING. Prints routing summary and
      writes analysis/pilot/round_feedback_<round_label>.json (allowlisted
      Generator feedback for any REVISE_REQUIRED candidates).

  rebuild_feedback <round_label>
      Rebuild the round feedback artifact idempotently from persisted
      Candidate Reviewer history after an earlier artifact write failed.

  apply_revision <generator_output.json>
      Feed a revised Generator output file to process_generation_output()
      for every candidate currently in REVISE_REQUIRED, moving it back to
      REVIEWING (or VALIDATION_FAILED) for the next Reviewer round.

  prepare_solver_batch
      Blind every candidate currently in SOLVING via the shared pure
      projection (through orchestrator.blind_for_solver()) and
      write the combined batch to analysis/pilot/solver_input_batch.json.

  apply_solver <solver_output.json>
      Feed a Solver output file to process_solver_stage() for every
      candidate currently in SOLVING. Prints final state tally.

  finalize
      Build provenance/accepted/manual-review/failure artifacts for ALL
      candidates (terminal and non-terminal) and write them to
      analysis/pilot/pilot_provenance.json, pilot_accepted_items.json,
      pilot_manual_review.json, pilot_failure_items.json. Also appends
      MANUAL_REVIEW entries to analysis/manual_review_queue.json via the
      existing append_manual_review_queue().

Usage: python orchestrator/scripts/pilot_driver.py <subcommand> [args...]
       init ... --force-reset  (explicitly replace an existing state file)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import (  # noqa: E402
    REPO_ROOT,
    BatchIntegrityTracker,
    Candidate,
    State,
    SystemCallError,
    TERMINAL_STATES,
    validate_final_record,
    blind_for_solver,
    build_manual_review_entry,
    build_provenance_record,
    build_review_feedback_from_state,
    canonical_solver_input_errors,
    derive_slot_requirements,
    leakage_guard,
    load_config,
    load_candidate_state,
    load_items_by_id,
    load_versions,
    process_generation_output,
    process_review_output,
    process_solver_stage,
    record_stage_failure,
    retry_failed_stage,
    save_candidate_state,
    strip_internal_test_keys,
)
from shared.json_io import (  # noqa: E402
    atomic_write_json,
    exclusive_file_lock,
    exclusive_state_transaction,
)

PILOT_DIR = REPO_ROOT / "analysis" / "pilot"
STATE_PATH = PILOT_DIR / "candidates_state.json"


def load_state() -> dict[str, Candidate]:
    if not STATE_PATH.exists():
        raise SystemExit(f"No state file at {STATE_PATH}; run 'init' first.")
    return load_candidate_state(STATE_PATH)


def save_state(candidates: dict[str, Candidate]) -> None:
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    save_candidate_state(STATE_PATH, candidates)


def state_transaction():
    """Lock the full Candidate read-modify-write cycle for this driver."""
    return exclusive_state_transaction(STATE_PATH, load_state, save_state)


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
        c.generator_item = gitem
        c.planned_slot = derive_slot_requirements(gitem)
        c = process_generation_output(c, config)
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
        save_state(candidates)

    ready = sorted(i for i, c in candidates.items() if c.state == State.REVIEWING)
    failed = sorted(i for i, c in candidates.items() if c.state != State.REVIEWING)
    print(f"Loaded {len(candidates)} candidates ({len(gen_items)} generator records).")
    print(f"Ready for Reviewer round 1 ({len(ready)}): {ready}")
    if failed:
        print(f"NOT ready (schema validation issue) ({len(failed)}):")
        for i in failed:
            c = candidates[i]
            print(f"  {i}: state={c.state} failure={c.failure}")


def cmd_apply_review(reviewer_path: str, round_label: str) -> None:
    config = load_config()
    reviewer_items = load_items_by_id(Path(reviewer_path), f"reviewer round {round_label}")

    routed: dict[str, list[str]] = {"SOLVING": [], "REVISE_REQUIRED": [], "REJECTED": [], "DISCARDED": [], "VALIDATION_FAILED": [], "GENERATION_FAILED": [], "skipped_not_reviewing": []}
    with state_transaction() as candidates:
        for item_id, c in candidates.items():
            if (
                c.state in {State.GENERATION_FAILED, State.VALIDATION_FAILED}
                and c.failure is not None
                and c.failure.stage == "reviewer"
                and item_id in reviewer_items
            ):
                c = retry_failed_stage(c, config)
            if c.state != State.REVIEWING:
                continue
            if item_id not in reviewer_items:
                routed["skipped_not_reviewing"].append(item_id)
                continue
            reviewer_item = strip_internal_test_keys(reviewer_items[item_id])
            c.reviewer_item = reviewer_item
            c = process_review_output(c, config)
            c.review_history.append({
                "round": round_label,
                "output": reviewer_item,
                "routed_state": c.state,
            })
            routed.setdefault(c.state, []).append(item_id)
        # Build from the same locked in-memory snapshot that is about to be
        # persisted. If the following artifact write fails, this exact
        # document remains reproducible from state.
        feedback_document = build_review_feedback_from_state(candidates, round_label)
    feedback_path = PILOT_DIR / f"round_feedback_{round_label}.json"
    atomic_write_json(feedback_path, feedback_document)

    print(f"Reviewer round '{round_label}' applied to {sum(len(v) for v in routed.values())} candidates.")
    for state, ids in routed.items():
        if ids:
            print(f"  {state} ({len(ids)}): {sorted(ids)}")
    print(f"Wrote {len(feedback_document['items'])} REVISE feedback record(s) (issues+revision_requirements only) to {feedback_path}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_rebuild_feedback(round_label: str) -> None:
    """Idempotently rebuild one round's feedback from persisted Candidate state."""
    with exclusive_file_lock(STATE_PATH):
        candidates = load_state()
        feedback_document = build_review_feedback_from_state(candidates, round_label)
    feedback_path = PILOT_DIR / f"round_feedback_{round_label}.json"
    atomic_write_json(feedback_path, feedback_document)
    print(
        f"Rebuilt {len(feedback_document['items'])} REVISE feedback record(s) "
        f"for round '{round_label}' at {feedback_path}"
    )


def cmd_apply_revision(generator_path: str) -> None:
    config = load_config()
    revised_items = load_items_by_id(Path(generator_path), "generator revision round")

    updated = []
    skipped = []
    with state_transaction() as candidates:
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
                skipped.append(item_id)
                continue
            if is_generator_retry:
                c = retry_failed_stage(c, config)
            else:
                # A revision is a quality-driven new Generator attempt. It is
                # intentionally distinct from transient failure retry counters.
                c.reviewer_item = None
                c.solver_item = None
                c.solver_input = None
                c.leakage_check = None
                c.consensus = None
                c.failure = None
                c.transition(State.GENERATED, "Reviewer-requested revision regenerated")
            c.generator_item = strip_internal_test_keys(gitem)
            if is_revision:
                c.generation_attempt += 1
            c = process_generation_output(c, config)
            updated.append(item_id)

    print(f"Applied revision to {len(updated)} candidate(s): {sorted(updated)}")
    if skipped:
        print(f"Skipped (not in REVISE_REQUIRED, or no matching candidate): {sorted(skipped)}")
    ready = sorted(i for i in updated if candidates[i].state == State.REVIEWING)
    print(f"Ready for next Reviewer round ({len(ready)}): {ready}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_prepare_solver_batch() -> None:
    config = load_config()
    batch = []
    errors = []
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
            except SystemCallError as e:
                c.solver_input = None
                record_stage_failure(
                    c,
                    config,
                    kind="system",
                    stage="solver",
                    detail=f"during blinding: {e}",
                )
                errors.append(f"{item_id}: {e}")
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

        out_path = PILOT_DIR / "solver_input_batch.json"
        atomic_write_json(out_path, {"items": batch})
        # The blinded input and leakage result are part of the cross-process
        # contract. Persist them before the command exits so apply_solver can
        # consume the exact input handed to the Solver.
    print(f"Blinded {len(batch)} candidate(s) currently in SOLVING -> {out_path}")
    if errors:
        print("Blinding errors:")
        for e in errors:
            print(f"  {e}")
    print(f"item_ids: {sorted(solving.keys())}")


def cmd_apply_solver(solver_path: str) -> None:
    config = load_config()
    solver_items = load_items_by_id(Path(solver_path), "solver output")

    routed: dict[str, list[str]] = {}
    missing = []
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
            if c.state != State.SOLVING or c.solver_input is None:
                continue
            s_item = solver_items.get(item_id)
            if s_item is None:
                missing.append(item_id)
                continue
            c = process_solver_stage(
                c,
                config,
                strip_internal_test_keys(s_item),
                precomputed_solver_input=c.solver_input,
            )
            routed.setdefault(c.state, []).append(item_id)
    print(f"Solver output applied. Routing:")
    for state, ids in routed.items():
        print(f"  {state} ({len(ids)}): {sorted(ids)}")
    if missing:
        print(f"MISSING solver record for SOLVING candidates: {sorted(missing)}")
    print(f"Current tally: {state_tally(candidates)}")


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
        raise ValueError(f"pilot finalize refused; nonterminal candidates remain: {detail}")

    tracker = BatchIntegrityTracker()
    provenance_records = []
    accepted_items = []
    manual_review_entries = []
    failure_items = []

    for item_id, c in candidates.items():
        if c.generator_item is not None:
            tracker.record_planned(c.generator_item, c.planned_slot)
        rec = build_provenance_record(c, versions)
        provenance_records.append(rec)
        if c.state == State.ACCEPTED:
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
    atomic_write_json(PILOT_DIR / "pilot_provenance.json", {
        "pipeline_version": config["pipeline_version"],
        "items": provenance_records,
        "batch_summary": tracker.summary(),
    })
    atomic_write_json(PILOT_DIR / "pilot_accepted_items.json", {"items": accepted_items})
    atomic_write_json(PILOT_DIR / "pilot_manual_review.json", {"items": manual_review_entries})
    atomic_write_json(PILOT_DIR / "pilot_failure_items.json", {"items": failure_items})

    if manual_review_entries:
        from orchestrator import append_manual_review_queue
        append_manual_review_queue(config, manual_review_entries)

    print(f"Finalized {len(candidates)} candidates.")
    print(f"State tally: {state_tally(candidates)}")
    print(f"ACCEPTED: {len(accepted_items)}  MANUAL_REVIEW: {len(manual_review_entries)}  failure_items: {len(failure_items)}")
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
        cmd_apply_review(*args)
    elif cmd == "rebuild_feedback":
        cmd_rebuild_feedback(*args)
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
