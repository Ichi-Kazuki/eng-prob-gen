"""Orchestrator adversarial regression test.

Replays the 5 deliberately-broken Reviewer-test fixtures through the
Orchestrator state machine:
    analysis/reviewer_adversarial_test.json          (candidate items, '_'-prefixed
                                                        test-only annotations stripped
                                                        before use, as if they were
                                                        Generator output)
    analysis/reviewer_adversarial_test_results.json  (Reviewer verdicts - all REVISE,
                                                        all critical_failure=true)

Every one of these 5 items must be blocked from ACCEPTED, and - because
Reviewer verdict is REVISE for all of them - none may ever reach the
Solver, even though analysis/solver_adversarial_test.json contains Solver
answers for the same 5 item_ids (produced when the Solver Agent was tested
standalone). This script asserts that fixture is never consumed here.

Usage:
    python run_adversarial_test.py
Writes:
    analysis/orchestrator_adversarial_test.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import (  # noqa: E402
    REPO_ROOT,
    Candidate,
    State,
    build_provenance_record,
    load_config,
    load_versions,
    process_generation_output,
    process_review_output,
    strip_internal_test_keys,
)

CANDIDATE_FIXTURE = REPO_ROOT / "analysis" / "reviewer_adversarial_test.json"
REVIEWER_RESULTS_FIXTURE = REPO_ROOT / "analysis" / "reviewer_adversarial_test_results.json"
SOLVER_FIXTURE = REPO_ROOT / "analysis" / "solver_adversarial_test.json"
OUTPUT_PATH = REPO_ROOT / "analysis" / "orchestrator_adversarial_test.json"


def load_items(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["item_id"]: item for item in data["items"]}


def main(output_path: Path | None = None) -> int:
    output_path = output_path or OUTPUT_PATH
    config = load_config()
    versions = load_versions(config)

    candidate_items = load_items(CANDIDATE_FIXTURE)
    reviewer_items = load_items(REVIEWER_RESULTS_FIXTURE)
    solver_items = load_items(SOLVER_FIXTURE)  # deliberately never fed to process_solver_stage below

    records = []
    solver_skip_log = []

    for item_id, raw_item in candidate_items.items():
        gen_item = strip_internal_test_keys(raw_item)

        candidate = Candidate(item_id=item_id, concept_id=item_id, section=gen_item["section"])
        candidate.generator_item = gen_item
        candidate = process_generation_output(candidate, config)

        if candidate.state == State.REVIEWING:
            candidate.reviewer_item = reviewer_items[item_id]
            candidate = process_review_output(candidate, config)

        if candidate.state != State.SOLVING and item_id in solver_items:
            solver_skip_log.append(
                f"{item_id}: solver fixture data exists but was NOT sent to Solver "
                f"(reviewer verdict={reviewer_items[item_id]['verdict']}; candidate state={candidate.state})"
            )

        records.append((item_id, candidate, build_provenance_record(candidate, versions)))

    accepted = [i for (i, c, _r) in records if c.state == State.ACCEPTED]
    solved = [i for (i, c, _r) in records if State.SOLVING in c.state_history]

    output = {
        "_purpose": (
            "Orchestrator state-machine replay over deliberately broken Reviewer-test "
            "fixtures (multiple-answer, zero-answer, WE double-error, WE zero-error, "
            "metadata mismatch). Verifies ACCEPT rate = 0% and Solver is never called "
            "on a REVISE item. Not usable practice content."
        ),
        "pipeline_version": config["pipeline_version"],
        "items": [rec for (_id, _c, rec) in records],
        "accept_count": len(accepted),
        "total_count": len(records),
        "accept_rate": len(accepted) / len(records) if records else None,
        "solver_skip_log": solver_skip_log,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {len(records)} provenance record(s) to {output_path}")
    print()
    for item_id, candidate, _rec in records:
        print(f"{item_id:<28} final_state={candidate.state:<16} entered_SOLVING={'yes' if item_id in solved else 'no'}")
    print()
    for line in solver_skip_log:
        print(f"[regression check] {line}")

    print(f"\nACCEPT rate: {len(accepted)}/{len(records)}")
    assert not accepted, f"REGRESSION: adversarial items must never be ACCEPTED, but got: {accepted}"
    assert not solved, f"REGRESSION: adversarial items must never reach the Solver, but got: {solved}"
    print("Adversarial regression checks OK: 0% ACCEPT rate, 0 items reached Solver.")

    return 0


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python run_adversarial_test.py [output-path]")
    raise SystemExit(main(output))
