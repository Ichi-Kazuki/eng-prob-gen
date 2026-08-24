"""Schema-level validation for the Orchestrator's own provenance output.

Checks only the *shape* of a provenance record (required fields, internal
consistency such as accepted_item being non-null iff state == ACCEPTED),
mirroring the pattern of agents/*/scripts/validate_output.py. Does not
re-judge whether the underlying ACCEPTED/DISCARDED/etc. decision was
correct - that is exercised by run_smoke_test.py / run_adversarial_test.py
/ run_reject_path_test.py / run_acceptance_tests.py.

Usage:
    python validate_provenance.py <path-to-orchestrator-output.json>

Exit code 0 if every record passes; 1 if any record fails.
"""

import json
import sys
from pathlib import Path

REQUIRED_TOP_KEYS = {
    "item_id", "concept_id", "section", "state", "state_history",
    "generation_attempt", "revision_count", "generator", "reviewer", "solver",
    "consensus", "batch_slot", "versions", "accepted_item", "qa_audit",
}

VALID_STATES = {
    "GENERATED", "GENERATION_FAILED", "VALIDATION_FAILED", "REVIEWING",
    "REVISE_REQUIRED", "REJECTED", "SOLVING", "ACCEPTED", "MANUAL_REVIEW",
    "DISCARDED",
}


def load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    raise ValueError("Unrecognized top-level JSON shape")


def validate_record(rec: dict, errors: list[str]) -> None:
    prefix = f"[{rec.get('item_id', '?')}] "

    missing = REQUIRED_TOP_KEYS - set(rec.keys())
    if missing:
        errors.append(prefix + f"missing required field(s): {sorted(missing)}")

    state = rec.get("state")
    if state not in VALID_STATES:
        errors.append(prefix + f"state {state!r} is not a recognized Orchestrator state")

    accepted_item = rec.get("accepted_item")
    if state == "ACCEPTED" and accepted_item is None:
        errors.append(prefix + "state=ACCEPTED but accepted_item is null")
    if state != "ACCEPTED" and accepted_item is not None:
        errors.append(prefix + f"state={state!r} but accepted_item is non-null (should only be set for ACCEPTED)")

    consensus = rec.get("consensus")
    if not isinstance(consensus, bool):
        errors.append(prefix + "consensus must be a boolean")
    elif consensus and state != "ACCEPTED":
        errors.append(prefix + "consensus=true but state != ACCEPTED")
    elif not consensus and state == "ACCEPTED":
        errors.append(prefix + "state=ACCEPTED but consensus=false")

    if not isinstance(rec.get("state_history"), list) or not rec["state_history"]:
        errors.append(prefix + "state_history must be a non-empty array")
    elif rec["state_history"][-1] != state:
        errors.append(prefix + "state_history's last entry does not match the record's current state")

    qa_audit = rec.get("qa_audit")
    if not isinstance(qa_audit, dict):
        errors.append(prefix + "qa_audit must be present (it is the only place Reviewer/Solver detail lives)")

    if state == "SOLVING":
        errors.append(prefix + "state=SOLVING is a transient in-flight state and must not appear as a final record")

    # Solver is only ever called once a candidate has passed through SOLVING,
    # which only happens after a Reviewer PASS - so a non-null solver record
    # should only appear on a final state reachable from SOLVING.
    states_where_solver_may_be_set = {"ACCEPTED", "MANUAL_REVIEW", "DISCARDED"}
    if state not in states_where_solver_may_be_set and rec.get("solver") is not None:
        errors.append(
            prefix + f"state={state!r} but solver is non-null - Solver must only be "
            "reachable via a prior Reviewer PASS (state history should include SOLVING)"
        )


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    path = Path(sys.argv[1])
    records = load_records(path)

    errors: list[str] = []
    for rec in records:
        validate_record(rec, errors)

    print(f"Checked {len(records)} provenance record(s).")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("All provenance records passed shape validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
