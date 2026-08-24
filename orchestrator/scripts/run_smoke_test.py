"""Orchestrator smoke test: replay the existing 6-item Generator/Reviewer/
Solver fixtures through the Orchestrator state machine.

This does NOT call any live agent. It reuses the already-produced fixture
outputs:
    analysis/generator_smoke_test.json
    analysis/reviewer_smoke_test.json
    analysis/solver_smoke_test.json

as if they were the real outputs of a live Generator -> Reviewer -> Solver
run, and exercises the Orchestrator's own logic against them: schema
validation, PASS-gated Solver routing, blinding + leakage guard, and the
mechanical AUTO_ACCEPT consensus rule.

Critical regression case: gen-struct-003 got verdict REVISE from the
Reviewer (marginal distractor C). Solver output exists for it in
solver_smoke_test.json (because that fixture was produced by testing the
Solver Agent standalone against all 6 candidates), but a correct pipeline
must NEVER call Solver on a REVISE item - so this script deliberately does
NOT feed that Solver record to the Orchestrator for gen-struct-003, and
verifies the candidate never reaches SOLVING or ACCEPTED.

Usage:
    python run_smoke_test.py
Writes:
    analysis/orchestrator_smoke_test.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import (  # noqa: E402
    REPO_ROOT,
    BatchIntegrityTracker,
    Candidate,
    State,
    build_provenance_record,
    load_config,
    load_items_by_id,
    load_versions,
    process_generation_output,
    process_review_output,
    process_solver_stage,
)

GENERATOR_FIXTURE = REPO_ROOT / "analysis" / "generator_smoke_test.json"
REVIEWER_FIXTURE = REPO_ROOT / "analysis" / "reviewer_smoke_test.json"
SOLVER_FIXTURE = REPO_ROOT / "analysis" / "solver_smoke_test.json"
OUTPUT_PATH = REPO_ROOT / "analysis" / "orchestrator_smoke_test.json"

# NOTE: this is a regression-comparison label for the console report only.
# It does NOT drive the state machine - the actual verdict fed into
# process_review_output() is read from analysis/reviewer_smoke_test.json
# at runtime (see the item_id-keyed lookup in the loop below).
EXPECTED_LABEL = {
    "gen-struct-001": "ACCEPT-eligible",
    "gen-struct-002": "ACCEPT-eligible",
    "gen-struct-003": "ACCEPT-blocked",
    "gen-we-001": "ACCEPT-eligible",
    "gen-we-002": "ACCEPT-eligible",
    "gen-we-003": "ACCEPT-eligible",
}


def main(output_path: Path | None = None) -> int:
    output_path = output_path or OUTPUT_PATH
    config = load_config()
    versions = load_versions(config)

    # item_id-keyed dicts only - see orchestrator.load_items_by_id(). Every
    # lookup below is by item_id; list position in any of these three files
    # is never used to pair records up.
    generator_items = load_items_by_id(GENERATOR_FIXTURE, "generator_smoke_test.json")
    reviewer_items = load_items_by_id(REVIEWER_FIXTURE, "reviewer_smoke_test.json")
    solver_items = load_items_by_id(SOLVER_FIXTURE, "solver_smoke_test.json")

    missing_reviews = set(generator_items) - set(reviewer_items)
    if missing_reviews:
        raise ValueError(f"reviewer_smoke_test.json has no record for item_id(s): {sorted(missing_reviews)}")

    print("Join key: item_id (dict lookup, not list position).")
    print(f"Generator items: {sorted(generator_items)}")
    print(f"Reviewer items:  {sorted(reviewer_items)}")
    print(f"Solver items:    {sorted(solver_items)}")
    print("Reviewer verdicts (read from analysis/reviewer_smoke_test.json, not hardcoded):")
    for item_id, r in sorted(reviewer_items.items()):
        print(f"  {item_id}: verdict={r['verdict']}")
    print()

    tracker = BatchIntegrityTracker()
    records = []
    solver_skip_log = []

    for item_id, gen_item in generator_items.items():
        tracker.record_planned(gen_item)

        candidate = Candidate(item_id=item_id, concept_id=item_id, section=gen_item["section"])
        candidate.generator_item = gen_item
        candidate = process_generation_output(candidate, config)

        if candidate.state == State.REVIEWING:
            candidate.reviewer_item = reviewer_items[item_id]
            candidate = process_review_output(candidate, config)

        if candidate.state == State.SOLVING:
            solver_item = solver_items.get(item_id)
            candidate = process_solver_stage(candidate, config, solver_item)
        else:
            # Regression guard: prove we deliberately did not consume the
            # fixture's Solver record for a non-PASS item, even though it
            # exists in solver_smoke_test.json.
            if item_id in solver_items and candidate.state != State.SOLVING:
                solver_skip_log.append(
                    f"{item_id}: solver fixture data exists but was NOT sent to Solver "
                    f"(reviewer verdict != PASS; candidate state={candidate.state})"
                )

        if candidate.state == State.ACCEPTED:
            tracker.record_accepted(gen_item)

        records.append((item_id, candidate, build_provenance_record(candidate, versions)))

    output = {
        "_purpose": (
            "Orchestrator state-machine replay over the existing 6-item smoke fixtures. "
            "Not a new content generation run."
        ),
        "pipeline_version": config["pipeline_version"],
        "items": [rec for (_id, _c, rec) in records],
        "batch_summary": tracker.summary(),
        "solver_skip_log": solver_skip_log,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {len(records)} provenance record(s) to {output_path}")
    print()
    print(f"{'item_id':<16} {'reviewer_verdict':<18} {'solver_answer':<15} {'final_state':<16} {'expected':<16} match")
    all_ok = True
    for item_id, candidate, _rec in records:
        expected = EXPECTED_LABEL.get(item_id, "?")
        actually_accepted = candidate.state == State.ACCEPTED
        expected_accept = expected == "ACCEPT-eligible"
        ok = actually_accepted == expected_accept
        all_ok = all_ok and ok
        reviewer_verdict = candidate.reviewer_item["verdict"] if candidate.reviewer_item else "n/a"
        solver_answer = candidate.solver_item["solver_answer"] if candidate.solver_item else "n/a (Solver not called)"
        print(f"{item_id:<16} {reviewer_verdict:<18} {solver_answer:<15} {candidate.state:<16} {expected:<16} {'OK' if ok else 'MISMATCH'}")

    print()
    print("state_history per item:")
    for item_id, candidate, _rec in records:
        print(f"  {item_id}: {candidate.state_history}")

    print()
    for line in solver_skip_log:
        print(f"[regression check] {line}")

    print()
    print("AUTO_ACCEPT 9-condition check (per item that reached SOLVING):")
    for item_id, candidate, _rec in records:
        if candidate.consensus is None:
            continue
        status = "ALL 9 SATISFIED -> ACCEPTED" if candidate.consensus.auto_accept else "NOT satisfied"
        print(f"  {item_id}: {status}")
        if not candidate.consensus.auto_accept:
            for cond in candidate.consensus.failed_conditions:
                print(f"    - failed: {cond}")

    print()
    state_tally: dict[str, int] = {}
    for _id, candidate, _rec in records:
        state_tally[candidate.state] = state_tally.get(candidate.state, 0) + 1
    print(f"Final state tally: {state_tally}")

    if "gen-struct-003" in dict((i, c) for i, c, _ in records):
        struct_003 = next(c for (i, c, _r) in records if i == "gen-struct-003")
        assert struct_003.state != State.ACCEPTED, "REGRESSION: gen-struct-003 must never be ACCEPTED"
        assert State.SOLVING not in struct_003.state_history, (
            "REGRESSION: gen-struct-003 must never reach the Solver (Reviewer verdict was REVISE)"
        )
        print(f"\ngen-struct-003 regression guard OK: final state = {struct_003.state}, "
              f"never entered SOLVING")

    return 0 if all_ok else 1


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python run_smoke_test.py [output-path]")
    raise SystemExit(main(output))
