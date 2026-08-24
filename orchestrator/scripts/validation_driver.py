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
    ConsensusResult,
    FailureInfo,
    REPO_ROOT,
    State,
    blind_for_solver,
    build_generator_feedback,
    build_manual_review_entry,
    build_provenance_record,
    load_config,
    load_items_by_id,
    load_versions,
    process_generation_output,
    process_review_output,
    process_solver_stage,
    strip_internal_test_keys,
)

VALIDATION_DIR = REPO_ROOT / "analysis" / "validation"
STATE_PATH = VALIDATION_DIR / "validation_candidates_state.json"


def candidate_to_dict(c: Candidate) -> dict:
    return {
        "item_id": c.item_id,
        "concept_id": c.concept_id,
        "section": c.section,
        "state": c.state,
        "state_history": c.state_history,
        "generation_attempt": c.generation_attempt,
        "revision_count": c.revision_count,
        "generator_item": c.generator_item,
        "reviewer_item": c.reviewer_item,
        "solver_item": c.solver_item,
        "solver_input": c.solver_input,
        "leakage_check": c.leakage_check,
        "consensus": None if c.consensus is None else {
            "auto_accept": c.consensus.auto_accept,
            "routing": c.consensus.routing,
            "failed_conditions": c.consensus.failed_conditions,
            "disagreement_reasons": c.consensus.disagreement_reasons,
        },
        "failure": None if c.failure is None else {
            "kind": c.failure.kind,
            "stage": c.failure.stage,
            "detail": c.failure.detail,
        },
        "notes": c.notes,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "review_history": getattr(c, "review_history", []),
        "generation_history": getattr(c, "generation_history", []),
    }


def dict_to_candidate(d: dict) -> Candidate:
    c = Candidate(item_id=d["item_id"], concept_id=d["concept_id"], section=d["section"])
    c.state = d["state"]
    c.state_history = d["state_history"]
    c.generation_attempt = d["generation_attempt"]
    c.revision_count = d["revision_count"]
    c.generator_item = d["generator_item"]
    c.reviewer_item = d["reviewer_item"]
    c.solver_item = d["solver_item"]
    c.solver_input = d.get("solver_input")
    c.leakage_check = d.get("leakage_check")
    if d.get("consensus") is not None:
        c.consensus = ConsensusResult(
            auto_accept=d["consensus"]["auto_accept"],
            routing=d["consensus"]["routing"],
            failed_conditions=d["consensus"]["failed_conditions"],
            disagreement_reasons=d["consensus"]["disagreement_reasons"],
        )
    if d.get("failure") is not None:
        c.failure = FailureInfo(
            kind=d["failure"]["kind"],
            stage=d["failure"]["stage"],
            detail=d["failure"]["detail"],
        )
    c.notes = d.get("notes", [])
    c.created_at = d.get("created_at", c.created_at)
    c.updated_at = d.get("updated_at", c.updated_at)
    c.review_history = d.get("review_history", [])
    c.generation_history = d.get("generation_history", [])
    return c


def load_state() -> dict[str, Candidate]:
    if not STATE_PATH.exists():
        raise SystemExit(f"No state file at {STATE_PATH}; run init first.")
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {item_id: dict_to_candidate(d) for item_id, d in data.items()}


def save_state(candidates: dict[str, Candidate]) -> None:
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({i: candidate_to_dict(c) for i, c in candidates.items()}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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

    (VALIDATION_DIR / "validation_initial_items.json").write_text(
        json.dumps({"items": list(gen_items.values())}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
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
    reviewer_items = load_items_by_id(Path(reviewer_path), f"reviewer {round_label}")
    routed: dict[str, list[str]] = {}
    for item_id, c in candidates.items():
        if c.state != State.REVIEWING or item_id not in reviewer_items:
            continue
        reviewer_item = strip_internal_test_keys(reviewer_items[item_id])
        c.review_history.append({"round": round_label, "output": reviewer_item})
        c.reviewer_item = reviewer_item
        c = process_review_output(c, config)
        routed.setdefault(c.state, []).append(item_id)
    save_state(candidates)
    feedback = [build_generator_feedback(c.reviewer_item) for c in candidates.values() if c.state == State.REVISE_REQUIRED]
    if feedback:
        (VALIDATION_DIR / f"validation_round_feedback_{round_label}.json").write_text(
            json.dumps({"items": feedback}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(f"Applied Reviewer {round_label}: { {k: len(v) for k, v in routed.items()} }")
    print(f"State tally: {state_tally(candidates)}")


def cmd_apply_revision(generator_path: str) -> None:
    config = load_config()
    candidates = load_state()
    revised_items = load_items_by_id(Path(generator_path), "generator revision")
    updated = []
    for item_id, raw in revised_items.items():
        c = candidates.get(item_id)
        if c is None or c.state != State.REVISE_REQUIRED:
            continue
        item = strip_internal_test_keys(raw)
        c.generator_item = item
        c.generation_attempt += 1
        c.generation_history.append({"attempt": c.generation_attempt, "item": item})
        c = process_generation_output(c, config)
        candidates[item_id] = c
        updated.append(item_id)
    save_state(candidates)
    print(f"Applied revisions: {len(updated)}")
    print(f"State tally: {state_tally(candidates)}")


def cmd_prepare_solver_batch() -> None:
    config = load_config()
    candidates = load_state()
    batch = []
    for c in candidates.values():
        if c.state != State.SOLVING:
            continue
        blinded = blind_for_solver(config, c.generator_item)
        c.solver_input = blinded
        batch.append(blinded)
    save_state(candidates)
    (VALIDATION_DIR / "validation_solver_input_batch.json").write_text(
        json.dumps({"items": batch}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Prepared blinded Solver batch: {len(batch)}")


def cmd_apply_solver(solver_path: str) -> None:
    config = load_config()
    candidates = load_state()
    solver_items = load_items_by_id(Path(solver_path), "solver output")
    for item_id, c in candidates.items():
        if c.state == State.SOLVING and item_id in solver_items:
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
    (VALIDATION_DIR / "validation_provenance.json").write_text(json.dumps(wrapper, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (VALIDATION_DIR / "validation_accepted_items.json").write_text(json.dumps({"items": accepted}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (VALIDATION_DIR / "validation_manual_review.json").write_text(json.dumps({"items": manual}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (VALIDATION_DIR / "validation_failure_items.json").write_text(json.dumps({"items": failures}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
