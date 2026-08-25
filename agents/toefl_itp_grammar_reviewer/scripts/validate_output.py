"""Validate Reviewer output using its canonical schema and invariants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)

OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "reviewer_output.schema.json"
CHECK_KEYS = {
    "grammar_validity", "answer_uniqueness", "target_alignment", "naturalness",
    "toefl_style", "distractor_quality", "metadata_consistency",
}
REQUIRED_CHECK_KEYS = CHECK_KEYS
REQUIRED_TOP_KEYS = {
    "item_id", "section", "verdict", "critical_failure", "independent_answer",
    "generator_answer", "answer_match", "reviewer_difficulty", "generator_difficulty",
    "difficulty_mismatch", "checks", "issues", "revision_requirements",
    "source_similarity_risk",
}
ANSWER_POSITIONS = {"A", "B", "C", "D"}
_SCHEMA: dict | None = None


def load_items(path: Path) -> list[object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        if not isinstance(data["items"], list):
            raise ValueError("$.items must be an array")
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("top-level JSON must be an item, an array, or an object containing items")


def output_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA


def validate_semantics(item: dict) -> list[str]:
    errors: list[str] = []
    prefix = f"[{item['item_id']}]"
    if item["answer_match"] is not (item["independent_answer"] == item["generator_answer"]):
        errors.append(f"{prefix} $.answer_match: must equal independent_answer == generator_answer")
    if item["difficulty_mismatch"] is not (
        item["reviewer_difficulty"] != item["generator_difficulty"]
    ):
        errors.append(f"{prefix} $.difficulty_mismatch: must equal reviewer_difficulty != generator_difficulty")

    verdict = item["verdict"]
    checks = item["checks"]
    issues = item["issues"]
    if verdict == "PASS":
        if item["critical_failure"] is not False:
            errors.append(f"{prefix} $.verdict: PASS requires critical_failure=false")
        non_pass = sorted(key for key in CHECK_KEYS if checks[key] != "PASS")
        if non_pass:
            errors.append(f"{prefix} $.checks: PASS requires all checks PASS; non-PASS={non_pass}")
        severities = [issue["severity"] for issue in issues]
        for severity in ("CRITICAL", "MAJOR"):
            if severity in severities:
                errors.append(f"{prefix} $.issues: PASS forbids {severity} issues")
        if item["revision_requirements"]:
            errors.append(f"{prefix} $.revision_requirements: PASS requires an empty array")
    if item["section"] == "Written Expression" and verdict == "PASS":
        if item["detected_error_count"] != 1:
            errors.append(f"{prefix} $.detected_error_count: PASS requires exactly 1")
        if item["detected_error_position"] not in ANSWER_POSITIONS:
            errors.append(f"{prefix} $.detected_error_position: PASS requires A/B/C/D")
        if item["detected_error_position"] != item["independent_answer"]:
            errors.append(f"{prefix} $.detected_error_position: must equal independent_answer")
        if item["non_error_parts_valid"] is not True:
            errors.append(f"{prefix} $.non_error_parts_valid: PASS requires true")
        if item["minimal_correction_valid"] is not True:
            errors.append(f"{prefix} $.minimal_correction_valid: PASS requires true")
    if verdict == "REVISE" and not item["revision_requirements"]:
        errors.append(f"{prefix} $.revision_requirements: REVISE requires at least one requirement")
    return errors


def validate_contract(item: object, errors: list[str] | None = None) -> list[str]:
    collected: list[str] = []
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        collected.append(f"[{item_id}] $: reviewer result must be an object")
    else:
        structural = schema_errors(item, output_schema())
        collected.extend(f"[{item_id}] {OUTPUT_SCHEMA_PATH.name}: {error}" for error in structural)
        if not structural:
            collected.extend(validate_semantics(item))
    if errors is not None:
        errors.extend(collected)
    return collected


validate = validate_contract
validate_item = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        items = load_items(Path(sys.argv[1]))
        errors: list[str] = []
        sections = {"Structure": 0, "Written Expression": 0}
        verdicts = {"PASS": 0, "REVISE": 0, "REJECT": 0}
        for item in items:
            if isinstance(item, dict):
                if item.get("section") in sections:
                    sections[item["section"]] += 1
                if item.get("verdict") in verdicts:
                    verdicts[item["verdict"]] += 1
            validate_contract(item, errors)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[?] $: {exc}")
        return 1
    print(f"Checked {len(items)} item(s): sections={sections} verdicts={verdicts}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("All items passed Draft 2020-12 schema and semantic validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
