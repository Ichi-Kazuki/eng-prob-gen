"""Schema-level validation for TOEFL ITP Independent Solver Agent output.

Checks only the *shape* of the Solver's own output (required fields, enum
membership, and the internal-consistency rule that ambiguity_detected must
be true iff solver_answer is AMBIGUOUS or NONE). This does NOT judge
whether solver_answer is the *correct* answer - that is exercised
separately via the smoke/adversarial test process.

Usage:
    python validate_output.py <path-to-solver-output.json>

Exit code 0 if every item passes; 1 if any item fails.
"""

import json
import sys
from pathlib import Path

SECTIONS = {"Structure", "Written Expression"}
SOLVER_ANSWERS = {"A", "B", "C", "D", "AMBIGUOUS", "NONE"}
CONFIDENCE_LEVELS = {"HIGH", "MEDIUM", "LOW"}
AMBIGUOUS_ANSWERS = {"AMBIGUOUS", "NONE"}

REQUIRED_TOP_KEYS = {
    "item_id",
    "section",
    "solver_answer",
    "confidence",
    "reason",
    "ambiguity_detected",
}


def load_items(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("Unrecognized top-level JSON shape")


def validate_item(item, errors):
    prefix = f"[{item.get('item_id', '?')}] "

    missing = REQUIRED_TOP_KEYS - set(item.keys())
    if missing:
        errors.append(prefix + f"missing required field(s): {sorted(missing)}")

    section = item.get("section")
    if section not in SECTIONS:
        errors.append(prefix + f"section must be one of {sorted(SECTIONS)}, got {section!r}")

    answer = item.get("solver_answer")
    if answer not in SOLVER_ANSWERS:
        errors.append(prefix + f"solver_answer must be one of {sorted(SOLVER_ANSWERS)}, got {answer!r}")

    if item.get("confidence") not in CONFIDENCE_LEVELS:
        errors.append(prefix + f"confidence must be one of {sorted(CONFIDENCE_LEVELS)}")

    if not isinstance(item.get("reason"), str) or not item["reason"].strip():
        errors.append(prefix + "reason must be a non-empty string")

    ambiguity = item.get("ambiguity_detected")
    if not isinstance(ambiguity, bool):
        errors.append(prefix + "ambiguity_detected must be a boolean")
    elif answer in AMBIGUOUS_ANSWERS and ambiguity is not True:
        errors.append(prefix + f"solver_answer={answer!r} requires ambiguity_detected=true")
    elif answer in SOLVER_ANSWERS - AMBIGUOUS_ANSWERS and ambiguity is not False:
        errors.append(prefix + f"solver_answer={answer!r} requires ambiguity_detected=false")

    if section == "Written Expression":
        if "suggested_correction" not in item:
            errors.append(prefix + "Written Expression item missing field: suggested_correction")
        elif not isinstance(item["suggested_correction"], str):
            errors.append(prefix + "suggested_correction must be a string")

    # Leakage guard: a Solver output item should never carry answer/metadata
    # fields that only make sense on Generator/Reviewer output.
    leaked_keys = {
        "correct_answer",
        "answer_explanation",
        "distractor_rationales",
        "primary_target",
        "subtype",
        "secondary_features",
        "tested_error_type",
        "difficulty",
        "error_scope",
        "minimal_correction",
        "verdict",
        "independent_answer",
        "checks",
        "issues",
    } & set(item.keys())
    if leaked_keys:
        errors.append(prefix + f"output contains fields that should never appear on Solver output (possible leakage): {sorted(leaked_keys)}")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)

    path = Path(sys.argv[1])
    items = load_items(path)

    errors = []
    section_counts = {"Structure": 0, "Written Expression": 0}
    answer_counts = {k: 0 for k in SOLVER_ANSWERS}

    for item in items:
        section = item.get("section")
        if section in section_counts:
            section_counts[section] += 1
        answer = item.get("solver_answer")
        if answer in answer_counts:
            answer_counts[answer] += 1
        validate_item(item, errors)

    print(f"Checked {len(items)} item(s): sections={section_counts} answers={answer_counts}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("All items passed solver-output schema validation.")
    sys.exit(0)


if __name__ == "__main__":
    main()
