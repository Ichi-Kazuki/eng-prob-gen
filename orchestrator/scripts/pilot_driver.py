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

  apply_revision <generator_output.json>
      Feed a revised Generator output file to process_generation_output()
      for every candidate currently in REVISE_REQUIRED, moving it back to
      REVIEWING (or VALIDATION_FAILED) for the next Reviewer round.

  prepare_solver_batch
      Blind every candidate currently in SOLVING via the existing
      create_solver_input.py (through orchestrator.blind_for_solver()) and
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
"""

from __future__ import annotations

import json
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
    blind_for_solver,
    build_generator_feedback,
    build_manual_review_entry,
    build_provenance_record,
    candidate_from_dict,
    candidate_to_dict,
    load_config,
    load_items_by_id,
    load_versions,
    process_generation_output,
    process_review_output,
    process_solver_stage,
    record_stage_failure,
    require_exact_batch_ids,
    strip_internal_test_keys,
)
from shared.json_io import atomic_write_json, read_json  # noqa: E402

PILOT_DIR = REPO_ROOT / "analysis" / "pilot"
STATE_PATH = PILOT_DIR / "candidates_state.json"


def load_state() -> dict[str, Candidate]:
    if not STATE_PATH.exists():
        raise SystemExit(f"No state file at {STATE_PATH}; run 'init' first.")
    data = read_json(STATE_PATH)
    if not isinstance(data, dict):
        raise ValueError(f"state file {STATE_PATH} must contain an object")
    candidates = {item_id: candidate_from_dict(d) for item_id, d in data.items()}

    # State written before solver_input was added can still have an in-flight
    # Solver batch. Recover only those legacy records from the batch artifact;
    # an explicit null in a current state file continues to mean "not batched".
    legacy_ids = {
        item_id for item_id, record in data.items()
        if "solver_input" not in record
    }
    batch_path = PILOT_DIR / "solver_input_batch.json"
    if legacy_ids and batch_path.exists():
        batch_items = load_items_by_id(batch_path, "legacy solver input batch")
        for item_id in legacy_ids & set(batch_items):
            candidate = candidates[item_id]
            if candidate.state == State.SOLVING:
                candidate.solver_input = batch_items[item_id]
    return candidates


def save_state(candidates: dict[str, Candidate]) -> None:
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    data = {item_id: candidate_to_dict(c) for item_id, c in candidates.items()}
    atomic_write_json(STATE_PATH, data)


def state_tally(candidates: dict[str, Candidate]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for c in candidates.values():
        tally[c.state] = tally.get(c.state, 0) + 1
    return tally


def load_stage_items(path: Path, label: str) -> dict[str, dict]:
    """Load agent JSON, reporting an unreadable file as an operator error.

    A file that cannot be read or parsed is a batch-level problem (wrong path,
    truncated download, invalid encoding) and says nothing about any single
    candidate, so it must not consume per-candidate retry budget. State is left
    untouched so the operator can simply re-run the command with a good file.
    """
    try:
        return load_items_by_id(path, label)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"{label} could not be read from {path}: {exc}. "
            "No candidate state was changed; re-run with a readable file."
        ) from exc


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_init(structure_path: str, we_path: str) -> None:
    config = load_config()
    structure_items = load_items_by_id(Path(structure_path), "structure generator round1")
    written_expression_items = load_items_by_id(Path(we_path), "we generator round1")
    duplicates = sorted(set(structure_items) & set(written_expression_items))
    if duplicates:
        raise ValueError(f"duplicate initial item_id across pilot batches: {duplicates}")
    gen_items = {**structure_items, **written_expression_items}

    candidates: dict[str, Candidate] = {}
    for item_id, gitem in gen_items.items():
        gitem = strip_internal_test_keys(gitem)
        c = Candidate(item_id=item_id, concept_id=item_id, section=gitem.get("section", "unknown"))
        c.generator_item = gitem
        c = process_generation_output(c, config)
        candidates[item_id] = c

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
    candidates = load_state()
    reviewer_items = load_stage_items(
        Path(reviewer_path), f"reviewer round {round_label}"
    )

    expected = {item_id for item_id, candidate in candidates.items() if candidate.state == State.REVIEWING}
    require_exact_batch_ids(expected, set(reviewer_items), f"Reviewer {round_label}")

    routed: dict[str, list[str]] = {"SOLVING": [], "REVISE_REQUIRED": [], "REJECTED": [], "DISCARDED": [], "VALIDATION_FAILED": [], "GENERATION_FAILED": [], "skipped_not_reviewing": []}
    for item_id, c in candidates.items():
        if c.state != State.REVIEWING:
            continue
        c.reviewer_item = strip_internal_test_keys(reviewer_items[item_id])
        c = process_review_output(c, config)
        routed.setdefault(c.state, []).append(item_id)

    save_state(candidates)

    feedback_items = []
    for item_id in routed.get("REVISE_REQUIRED", []):
        c = candidates[item_id]
        feedback_items.append(build_generator_feedback(c.reviewer_item))
    feedback_path = PILOT_DIR / f"round_feedback_{round_label}.json"
    if feedback_items:
        atomic_write_json(feedback_path, {"items": feedback_items})

    print(f"Reviewer round '{round_label}' applied to {sum(len(v) for v in routed.values())} candidates.")
    for state, ids in routed.items():
        if ids:
            print(f"  {state} ({len(ids)}): {sorted(ids)}")
    if feedback_items:
        print(f"Wrote {len(feedback_items)} REVISE feedback record(s) (issues+revision_requirements only) to {feedback_path}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_apply_revision(generator_path: str) -> None:
    config = load_config()
    candidates = load_state()
    revised_items = load_items_by_id(Path(generator_path), "generator revision round")
    expected = {
        item_id for item_id, candidate in candidates.items()
        if candidate.state == State.REVISE_REQUIRED
    }
    require_exact_batch_ids(expected, set(revised_items), "Generator revision round")

    updated = []
    for item_id in sorted(expected):
        gitem = revised_items[item_id]
        c = candidates[item_id]
        c.generator_item = strip_internal_test_keys(gitem)
        c.generation_attempt += 1
        c.generation_history.append({"attempt": c.generation_attempt, "item": c.generator_item})
        c.transition(State.GENERATED, "Reviewer-requested revision regenerated")
        c = process_generation_output(c, config)
        updated.append(item_id)

    save_state(candidates)
    print(f"Applied revision to {len(updated)} candidate(s): {sorted(updated)}")
    ready = sorted(i for i in updated if candidates[i].state == State.REVIEWING)
    print(f"Ready for next Reviewer round ({len(ready)}): {ready}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_apply_generation_retry(generator_path: str) -> None:
    """Apply regenerated output after generator validation/system failure."""
    config = load_config()
    candidates = load_state()
    retry_items = load_stage_items(
        Path(generator_path), "generator retry"
    )
    expected = {item_id for item_id, candidate in candidates.items() if candidate.state == State.GENERATED}
    require_exact_batch_ids(expected, set(retry_items), "Generator retry")
    for item_id in sorted(expected):
        candidate = candidates[item_id]
        candidate.generator_item = strip_internal_test_keys(retry_items[item_id])
        candidate.generation_attempt += 1
        candidate.generation_history.append(
            {"attempt": candidate.generation_attempt, "item": candidate.generator_item}
        )
        process_generation_output(candidate, config)
    save_state(candidates)
    print(f"Applied Generator retry output to {len(expected)} candidate(s): {sorted(expected)}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_prepare_solver_batch() -> None:
    config = load_config()
    candidates = load_state()
    solving = {i: c for i, c in candidates.items() if c.state == State.SOLVING}

    batch = []
    errors = []
    for item_id, c in solving.items():
        try:
            blinded = blind_for_solver(config, c.generator_item)
        except SystemCallError as e:
            # The candidate stays in SOLVING for its retry, but it is not in
            # this batch, so ``solver_input`` is cleared: that is what marks it
            # as not-expected in the Solver output applied next.
            c.solver_input = None
            record_stage_failure(
                c, config, kind="system", stage="solver", detail=f"blinding: {e}",
                retry_state=State.SOLVING,
            )
            errors.append(f"{item_id}: {e}")
            continue
        c.solver_input = blinded
        batch.append(blinded)

    out_path = PILOT_DIR / "solver_input_batch.json"
    atomic_write_json(out_path, {"items": batch})
    save_state(candidates)
    print(f"Blinded {len(batch)} candidate(s) currently in SOLVING -> {out_path}")
    if errors:
        print("Blinding errors:")
        for e in errors:
            print(f"  {e}")
    print(f"item_ids: {sorted(solving.keys())}")


def cmd_apply_solver(solver_path: str) -> None:
    config = load_config()
    candidates = load_state()
    solver_items = load_stage_items(
        Path(solver_path), "solver output"
    )

    # Only candidates that were actually blinded into the last batch can have
    # Solver output; one un-blindable candidate must not make the whole batch
    # un-appliable.
    expected = {
        item_id
        for item_id, candidate in candidates.items()
        if candidate.state == State.SOLVING and candidate.solver_input is not None
    }
    not_batched = sorted(
        item_id
        for item_id, candidate in candidates.items()
        if candidate.state == State.SOLVING and candidate.solver_input is None
    )
    require_exact_batch_ids(expected, set(solver_items), "Solver output")

    routed: dict[str, list[str]] = {}
    for item_id, c in candidates.items():
        if c.state != State.SOLVING or item_id not in expected:
            continue
        s_item = solver_items.get(item_id)
        c = process_solver_stage(c, config, strip_internal_test_keys(s_item))
        routed.setdefault(c.state, []).append(item_id)

    save_state(candidates)
    if not_batched:
        print(
            "Awaiting solver retry (not in this batch): "
            f"{len(not_batched)} -> {not_batched}"
        )
    print(f"Solver output applied. Routing:")
    for state, ids in routed.items():
        print(f"  {state} ({len(ids)}): {sorted(ids)}")
    print(f"Current tally: {state_tally(candidates)}")


def cmd_finalize() -> None:
    config = load_config()
    versions = load_versions(config)
    candidates = load_state()

    # A retryable failure now parks the candidate back in its working state, so
    # finalizing mid-retry would write a provenance record that appears in none
    # of accepted/manual/failure and that validate_provenance.py then rejects.
    nonterminal = sorted(
        (candidate.item_id, candidate.state)
        for candidate in candidates.values()
        if candidate.state not in TERMINAL_STATES
    )
    if nonterminal:
        detail = ", ".join(f"{item_id}={state}" for item_id, state in nonterminal)
        raise ValueError(
            "pilot finalize refused; nonterminal candidates remain: " + detail
        )

    tracker = BatchIntegrityTracker()
    provenance_records = []
    accepted_items = []
    manual_review_entries = []
    failure_items = []

    for item_id, c in candidates.items():
        if c.generator_item is not None:
            tracker.record_planned(c.generator_item)
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
        cmd_init(*args)
    elif cmd == "apply_review":
        cmd_apply_review(*args)
    elif cmd == "apply_revision":
        cmd_apply_revision(*args)
    elif cmd == "apply_generation_retry":
        cmd_apply_generation_retry(*args)
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
