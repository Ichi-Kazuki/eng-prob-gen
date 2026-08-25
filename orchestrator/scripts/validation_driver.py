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

VALIDATION_DIR = REPO_ROOT / "analysis" / "validation"
STATE_PATH = VALIDATION_DIR / "validation_candidates_state.json"


def load_state() -> dict[str, Candidate]:
    if not STATE_PATH.exists():
        raise SystemExit(f"No state file at {STATE_PATH}; run init first.")
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
    batch_path = VALIDATION_DIR / "validation_solver_input_batch.json"
    if legacy_ids and batch_path.exists():
        batch_items = load_items_by_id(batch_path, "legacy solver input batch")
        for item_id in legacy_ids & set(batch_items):
            candidate = candidates[item_id]
            if candidate.state == State.SOLVING:
                candidate.solver_input = batch_items[item_id]
    return candidates


def save_state(candidates: dict[str, Candidate]) -> None:
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(STATE_PATH, {i: candidate_to_dict(c) for i, c in candidates.items()})


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
        VALIDATION_DIR / "validation_initial_items.json", {"items": list(gen_items.values())}
    )
    candidates: dict[str, Candidate] = {}
    for item_id, item in gen_items.items():
        c = Candidate(item_id=item_id, concept_id=item_id, section=item.get("section", "unknown"))
        c.generator_item = item
        c.generation_history = [{"attempt": 1, "item": item}]
        c = process_generation_output(c, config)
        candidates[item_id] = c
    save_state(candidates)
    print(f"Loaded exactly {len(candidates)} initial candidates: {sections}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_apply_review(reviewer_path: str, round_label: str) -> None:
    config = load_config()
    candidates = load_state()
    reviewer_items = load_stage_items(
        Path(reviewer_path), f"reviewer {round_label}"
    )
    expected = {item_id for item_id, candidate in candidates.items() if candidate.state == State.REVIEWING}
    require_exact_batch_ids(expected, set(reviewer_items), f"Reviewer {round_label}")
    routed: dict[str, list[str]] = {}
    for item_id, c in candidates.items():
        if c.state != State.REVIEWING:
            continue
        reviewer_item = strip_internal_test_keys(reviewer_items[item_id])
        c.review_history.append({"round": round_label, "output": reviewer_item})
        c.reviewer_item = reviewer_item
        c = process_review_output(c, config)
        routed.setdefault(c.state, []).append(item_id)
    save_state(candidates)
    feedback = [build_generator_feedback(c.reviewer_item) for c in candidates.values() if c.state == State.REVISE_REQUIRED]
    if feedback:
        atomic_write_json(
            VALIDATION_DIR / f"validation_round_feedback_{round_label}.json",
            {"items": feedback},
        )
    print(f"Applied Reviewer {round_label}: { {k: len(v) for k, v in routed.items()} }")
    print(f"State tally: {state_tally(candidates)}")


def cmd_apply_revision(generator_path: str) -> None:
    config = load_config()
    candidates = load_state()
    revised_items = load_items_by_id(Path(generator_path), "generator revision")
    expected = {
        item_id for item_id, candidate in candidates.items()
        if candidate.state == State.REVISE_REQUIRED
    }
    require_exact_batch_ids(expected, set(revised_items), "Generator revision")
    updated = []
    for item_id in sorted(expected):
        raw = revised_items[item_id]
        c = candidates[item_id]
        item = strip_internal_test_keys(raw)
        c.generator_item = item
        c.generation_attempt += 1
        c.generation_history.append({"attempt": c.generation_attempt, "item": item})
        c.transition(State.GENERATED, "Reviewer-requested revision regenerated")
        c = process_generation_output(c, config)
        candidates[item_id] = c
        updated.append(item_id)
    save_state(candidates)
    print(f"Applied revisions: {len(updated)}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_apply_generation_retry(generator_path: str) -> None:
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
    print(f"Applied Generator retry output: {len(expected)}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_prepare_solver_batch() -> None:
    config = load_config()
    candidates = load_state()
    batch = []
    for c in candidates.values():
        if c.state != State.SOLVING:
            continue
        try:
            blinded = blind_for_solver(config, c.generator_item)
        except SystemCallError as exc:
            # Cleared so the candidate is not expected in the Solver output
            # applied next; it stays in SOLVING for its retry.
            c.solver_input = None
            record_stage_failure(
                c, config, kind="system", stage="solver", detail=f"blinding: {exc}",
                retry_state=State.SOLVING,
            )
            continue
        c.solver_input = blinded
        batch.append(blinded)
    save_state(candidates)
    atomic_write_json(VALIDATION_DIR / "validation_solver_input_batch.json", {"items": batch})
    print(f"Prepared blinded Solver batch: {len(batch)}")


def cmd_apply_solver(solver_path: str) -> None:
    config = load_config()
    candidates = load_state()
    solver_items = load_stage_items(
        Path(solver_path), "solver output"
    )
    # Only candidates blinded into the last batch can have Solver output; one
    # un-blindable candidate must not make the whole batch un-appliable.
    expected = {
        item_id
        for item_id, candidate in candidates.items()
        if candidate.state == State.SOLVING and candidate.solver_input is not None
    }
    require_exact_batch_ids(expected, set(solver_items), "Solver output")
    for item_id, c in candidates.items():
        if item_id in expected:
            c.solver_item = strip_internal_test_keys(solver_items[item_id])
            c = process_solver_stage(c, config, c.solver_item)
            candidates[item_id] = c
    save_state(candidates)
    print(f"Applied Solver outputs: {len(solver_items)} supplied")
    print(f"State tally: {state_tally(candidates)}")


def cmd_finalize() -> None:
    config = load_config()
    versions = load_versions(config)
    candidates = load_state()
    if len(candidates) != 120:
        raise ValueError(
            f"validation finalize requires exactly 120 initial candidates, got {len(candidates)}"
        )
    nonterminal = sorted(
        (candidate.item_id, candidate.state)
        for candidate in candidates.values()
        if candidate.state not in TERMINAL_STATES
    )
    if nonterminal:
        detail = ", ".join(f"{item_id}={state}" for item_id, state in nonterminal)
        raise ValueError(
            "validation finalize refused; nonterminal initial candidates remain: " + detail
        )
    tracker = BatchIntegrityTracker()
    provenance = []
    accepted = []
    manual = []
    failures = []
    for c in candidates.values():
        if c.generator_item is not None:
            tracker.record_planned(c.generator_item)
        rec = build_provenance_record(c, versions)
        rec["validation_trace"] = {
            "initial_candidate": True,
            "generation_history": getattr(c, "generation_history", []),
            "review_history": getattr(c, "review_history", []),
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
