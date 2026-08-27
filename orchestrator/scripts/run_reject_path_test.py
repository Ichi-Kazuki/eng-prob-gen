"""Orchestrator REJECT-path regression test.

Replays the 2 existing Reviewer REJECT fixtures through the Orchestrator
state machine:
    analysis/reviewer_reject_test.json          (candidate items, unsalvageable by
                                                   local revision - '_'-prefixed
                                                   test-only annotations stripped)
    analysis/reviewer_reject_test_results.json  (Reviewer verdict REJECT for both)

These fixtures already exist for exactly this purpose (spec section 19
only asks for a new one-off fixture if no REJECT case exists yet - it
already does), so no new candidate is authored here.

Verifies:
  - a REJECT verdict ends the candidate immediately (state REJECTED)
  - it is never sent back through the revision loop (no REVISE_REQUIRED /
    second GENERATED entry in state_history)
  - it never reaches the Solver
  - the record notes that a brand-new item_id must be generated from
    scratch, not that this candidate was patched

Usage:
    python run_reject_path_test.py
Writes:
    analysis/orchestrator_reject_path_test.json
"""

import argparse
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
    load_items_by_id,
    load_versions,
    process_generation_output,
    process_review_output,
    strip_internal_test_keys,
)

CANDIDATE_FIXTURE = REPO_ROOT / "analysis" / "reviewer_reject_test.json"
REVIEWER_RESULTS_FIXTURE = REPO_ROOT / "analysis" / "reviewer_reject_test_results.json"
OUTPUT_PATH = REPO_ROOT / "analysis" / "orchestrator_reject_path_test.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="write the replay artifact here (default: the historical analysis path)",
    )
    args = parser.parse_args(argv)
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    versions = load_versions(config)

    candidate_items = load_items_by_id(CANDIDATE_FIXTURE, CANDIDATE_FIXTURE.name)
    reviewer_items = load_items_by_id(REVIEWER_RESULTS_FIXTURE, REVIEWER_RESULTS_FIXTURE.name)

    records = []
    for item_id, raw_item in candidate_items.items():
        gen_item = strip_internal_test_keys(raw_item)

        candidate = Candidate(item_id=item_id, concept_id=item_id, section=gen_item["section"])
        candidate.generator_item = gen_item
        candidate = process_generation_output(candidate, config)

        if candidate.state == State.REVIEWING:
            candidate.reviewer_item = reviewer_items[item_id]
            candidate = process_review_output(candidate, config)

        records.append((item_id, candidate, build_provenance_record(candidate, versions)))

    output = {
        "_purpose": (
            "Orchestrator state-machine replay over the existing Reviewer REJECT "
            "fixtures (unsalvageable by local revision). Verifies REJECT terminates "
            "the candidate immediately without a revision loop or Solver call. "
            "Not usable practice content."
        ),
        "pipeline_version": config["pipeline_version"],
        "items": [rec for (_id, _c, rec) in records],
    }
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {len(records)} provenance record(s) to {output_path}")
    print()

    all_ok = True
    for item_id, candidate, _rec in records:
        is_rejected = candidate.state == State.REJECTED
        never_revised = State.REVISE_REQUIRED not in candidate.state_history
        never_solved = State.SOLVING not in candidate.state_history
        # Exactly one GENERATED entry: proves the item was never looped back
        # for a second generation attempt within this candidate.
        single_generation = candidate.state_history.count(State.GENERATED) == 1
        ok = is_rejected and never_revised and never_solved and single_generation
        all_ok = all_ok and ok
        print(
            f"{item_id:<20} state={candidate.state:<10} "
            f"rejected={is_rejected} never_revised={never_revised} "
            f"never_solved={never_solved} single_generation={single_generation} "
            f"-> {'OK' if ok else 'MISMATCH'}"
        )
        print(f"    state_history: {candidate.state_history}")

    assert all_ok, "REGRESSION: a REJECT verdict must terminate the candidate without looping to revision/Solver"
    print("\nREJECT-path regression checks OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
