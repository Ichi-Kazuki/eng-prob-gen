"""Schema-level validation for TOEFL ITP Reviewer Agent output.

Checks only the *shape* of the Reviewer's own output (required fields,
enum membership, internal consistency such as critical_failure implying
a non-PASS verdict). This does NOT judge whether a verdict is the
*correct* verdict for the underlying item - that is a matter of review
quality, exercised separately via the adversarial test process.

Usage:
    python validate_output.py <path-to-reviewer-output.json>

Exit code 0 if every item passes; 1 if any item fails.
"""

import json
import sys
from pathlib import Path

VERDICTS = {"PASS", "REVISE", "REJECT"}
CHECK_VALUES = {"PASS", "REVISE", "REJECT"}
DIFFICULTY_TIERS = {"EASY", "MEDIUM", "HARD"}
SECTIONS = {"Structure", "Written Expression"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
INDEPENDENT_ANSWERS = {"A", "B", "C", "D", "NONE", "AMBIGUOUS"}
GENERATOR_ANSWERS = {"A", "B", "C", "D"}
ERROR_POSITIONS = {"A", "B", "C", "D", "NONE"}

REQUIRED_CHECK_KEYS = {
    "grammar_validity",
    "answer_uniqueness",
    "target_alignment",
    "naturalness",
    "toefl_style",
    "distractor_quality",
    "metadata_consistency",
}

REQUIRED_TOP_KEYS = {
    "item_id",
    "section",
    "verdict",
    "critical_failure",
    "independent_answer",
    "generator_answer",
    "answer_match",
    "reviewer_difficulty",
    "generator_difficulty",
    "difficulty_mismatch",
    "checks",
    "issues",
    "revision_requirements",
    "source_similarity_risk",
}

WE_ONLY_KEYS = {
    "detected_error_count",
    "detected_error_position",
    "non_error_parts_valid",
    "minimal_correction_valid",
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

    verdict = item.get("verdict")
    if verdict not in VERDICTS:
        errors.append(prefix + f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")

    if not isinstance(item.get("critical_failure"), bool):
        errors.append(prefix + "critical_failure must be a boolean")
    elif item["critical_failure"] is True and verdict == "PASS":
        errors.append(prefix + "critical_failure=true is inconsistent with verdict=PASS")

    if item.get("independent_answer") not in INDEPENDENT_ANSWERS:
        errors.append(prefix + f"independent_answer must be one of {sorted(INDEPENDENT_ANSWERS)}")

    if item.get("generator_answer") not in GENERATOR_ANSWERS:
        errors.append(prefix + "generator_answer must be one of A/B/C/D")

    if not isinstance(item.get("answer_match"), bool):
        errors.append(prefix + "answer_match must be a boolean")

    if item.get("reviewer_difficulty") not in DIFFICULTY_TIERS:
        errors.append(prefix + "reviewer_difficulty must be EASY/MEDIUM/HARD")

    if item.get("generator_difficulty") not in DIFFICULTY_TIERS:
        errors.append(prefix + "generator_difficulty must be EASY/MEDIUM/HARD")

    if not isinstance(item.get("difficulty_mismatch"), bool):
        errors.append(prefix + "difficulty_mismatch must be a boolean")

    checks = item.get("checks")
    if not isinstance(checks, dict):
        errors.append(prefix + "checks must be an object")
    else:
        missing_checks = REQUIRED_CHECK_KEYS - set(checks.keys())
        if missing_checks:
            errors.append(prefix + f"checks missing key(s): {sorted(missing_checks)}")
        for k, v in checks.items():
            if k in REQUIRED_CHECK_KEYS and v not in CHECK_VALUES:
                errors.append(prefix + f"checks.{k} must be one of {sorted(CHECK_VALUES)}, got {v!r}")

    issues = item.get("issues")
    if not isinstance(issues, list):
        errors.append(prefix + "issues must be an array")
    else:
        for i, issue in enumerate(issues):
            if not isinstance(issue, dict):
                errors.append(prefix + f"issues[{i}] must be an object")
                continue
            if issue.get("severity") not in SEVERITIES:
                errors.append(prefix + f"issues[{i}].severity must be one of {sorted(SEVERITIES)}")
            if not isinstance(issue.get("category"), str) or not issue["category"].strip():
                errors.append(prefix + f"issues[{i}].category must be a non-empty string")
            if not isinstance(issue.get("description"), str) or not issue["description"].strip():
                errors.append(prefix + f"issues[{i}].description must be a non-empty string")

    if not isinstance(item.get("revision_requirements"), list):
        errors.append(prefix + "revision_requirements must be an array")

    if item.get("source_similarity_risk") not in RISK_LEVELS:
        errors.append(prefix + f"source_similarity_risk must be one of {sorted(RISK_LEVELS)}")

    if section == "Written Expression":
        missing_we = WE_ONLY_KEYS - set(item.keys())
        if missing_we:
            errors.append(prefix + f"Written Expression item missing field(s): {sorted(missing_we)}")
        if "detected_error_count" in item and not isinstance(item["detected_error_count"], int):
            errors.append(prefix + "detected_error_count must be an integer")
        if "detected_error_position" in item and item["detected_error_position"] not in ERROR_POSITIONS:
            errors.append(prefix + f"detected_error_position must be one of {sorted(ERROR_POSITIONS)}")
        if "non_error_parts_valid" in item and not isinstance(item["non_error_parts_valid"], bool):
            errors.append(prefix + "non_error_parts_valid must be a boolean")
        if "minimal_correction_valid" in item and not isinstance(item["minimal_correction_valid"], bool):
            errors.append(prefix + "minimal_correction_valid must be a boolean")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)

    path = Path(sys.argv[1])
    items = load_items(path)

    errors = []
    section_counts = {"Structure": 0, "Written Expression": 0}
    verdict_counts = {"PASS": 0, "REVISE": 0, "REJECT": 0}

    for item in items:
        section = item.get("section")
        if section in section_counts:
            section_counts[section] += 1
        verdict = item.get("verdict")
        if verdict in verdict_counts:
            verdict_counts[verdict] += 1
        validate_item(item, errors)

    print(f"Checked {len(items)} item(s): sections={section_counts} verdicts={verdict_counts}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("All items passed reviewer-output schema validation.")
    sys.exit(0)


if __name__ == "__main__":
    main()
