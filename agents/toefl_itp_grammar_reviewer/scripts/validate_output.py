"""Validate TOEFL ITP Reviewer output.

The committed Draft 2020-12 schema owns structural validation. Python owns
only semantic consistency between fields reported by the Reviewer; it does
not judge English or override the Reviewer.

Exit codes: 0 valid, 1 output/schema/semantic failure, 2 runtime failure.
"""

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
ANSWER_POSITIONS = {"A", "B", "C", "D"}
REQUIRED_CHECK_KEYS = {
    "grammar_validity",
    "answer_uniqueness",
    "target_alignment",
    "naturalness",
    "toefl_style",
    "distractor_quality",
    "metadata_consistency",
}

_SCHEMA_CACHE: dict | None = None


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
    raise ValueError("$ must be an item object, an array, or an object containing $.items")


def output_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA_CACHE


def validate_semantics(item: dict, errors: list[str] | None = None) -> list[str]:
    """Validate only consistency among the Reviewer's reported fields."""
    collected = errors if errors is not None else []
    prefix = f"[{item['item_id']}]"
    verdict = item["verdict"]
    checks = item["checks"]
    issues = item["issues"]

    expected_answer_match = item["independent_answer"] == item["generator_answer"]
    if item["answer_match"] is not expected_answer_match:
        collected.append(
            f"{prefix} $.answer_match: must equal "
            "($.independent_answer == $.generator_answer)"
        )

    expected_difficulty_mismatch = (
        item["reviewer_difficulty"] != item["generator_difficulty"]
    )
    if item["difficulty_mismatch"] is not expected_difficulty_mismatch:
        collected.append(
            f"{prefix} $.difficulty_mismatch: must equal "
            "($.reviewer_difficulty != $.generator_difficulty)"
        )

    if item["critical_failure"] and verdict == "PASS":
        collected.append(f"{prefix} $.verdict: PASS requires $.critical_failure=false")

    if verdict == "PASS":
        non_pass_checks = sorted(name for name in REQUIRED_CHECK_KEYS if checks[name] != "PASS")
        if non_pass_checks:
            collected.append(
                f"{prefix} $.checks: verdict=PASS requires every required check to be PASS; "
                f"non-PASS={non_pass_checks}"
            )
        critical_issue_indexes = [
            index for index, issue in enumerate(issues) if issue["severity"] == "CRITICAL"
        ]
        if critical_issue_indexes:
            collected.append(
                f"{prefix} $.issues: verdict=PASS forbids CRITICAL issues; "
                f"indexes={critical_issue_indexes}"
            )
        if item["independent_answer"] not in ANSWER_POSITIONS:
            collected.append(
                f"{prefix} $.independent_answer: verdict=PASS requires A/B/C/D"
            )

    if verdict == "REVISE" and not item["revision_requirements"]:
        collected.append(
            f"{prefix} $.revision_requirements: verdict=REVISE requires at least one requirement"
        )

    if verdict in {"REVISE", "REJECT"}:
        all_checks_pass = all(checks[name] == "PASS" for name in REQUIRED_CHECK_KEYS)
        if all_checks_pass and not issues and not item["revision_requirements"]:
            collected.append(
                f"{prefix} $: verdict={verdict} is inconsistent with all checks PASS, "
                "no issues, and no revision requirements"
            )

    if item["section"] == "Written Expression" and verdict == "PASS":
        if item["detected_error_count"] != 1:
            collected.append(
                f"{prefix} $.detected_error_count: verdict=PASS requires exactly 1"
            )
        if item["detected_error_position"] not in ANSWER_POSITIONS:
            collected.append(
                f"{prefix} $.detected_error_position: verdict=PASS requires A/B/C/D"
            )
        if item["detected_error_position"] != item["independent_answer"]:
            collected.append(
                f"{prefix} $.detected_error_position: verdict=PASS requires equality "
                "with $.independent_answer"
            )
        if item["non_error_parts_valid"] is not True:
            collected.append(
                f"{prefix} $.non_error_parts_valid: verdict=PASS requires true"
            )
        if item["minimal_correction_valid"] is not True:
            collected.append(
                f"{prefix} $.minimal_correction_valid: verdict=PASS requires true"
            )
    return collected


def validate_contract(item: object, errors: list[str] | None = None) -> list[str]:
    collected: list[str] = []
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        collected.append(f"[{item_id}] $: reviewer result must be an object")
    else:
        structural = schema_errors(item, output_schema())
        collected.extend(
            f"[{item_id}] {OUTPUT_SCHEMA_PATH.name}: {message}" for message in structural
        )
        if not structural:
            validate_semantics(item, collected)
    if errors is not None:
        errors.extend(collected)
    return collected


validate_item = validate_contract
validate = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        items = load_items(Path(sys.argv[1]))
        errors: list[str] = []
        section_counts = {"Structure": 0, "Written Expression": 0}
        verdict_counts = {"PASS": 0, "REVISE": 0, "REJECT": 0}
        for item in items:
            if isinstance(item, dict):
                if item.get("section") in section_counts:
                    section_counts[item["section"]] += 1
                if item.get("verdict") in verdict_counts:
                    verdict_counts[item["verdict"]] += 1
            validate_contract(item, errors)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[?] $: {exc}")
        return 1

    print(f"Checked {len(items)} item(s): sections={section_counts} verdicts={verdict_counts}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("All items passed Draft 2020-12 schema and semantic validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
