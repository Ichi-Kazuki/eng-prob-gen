#!/usr/bin/env python3
"""Validate WE Reviewer v2 output against schema and safety invariants.

The JSON Schema owns the structural contract. The semantic checks below only
verify consistency between fields the Reviewer already reported; they never
decide English grammaticality themselves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)


OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "reviewer_output_v2.schema.json"
LABELS = {"A", "B", "C", "D"}
CHECK_KEYS = {
    "grammar_validity", "one_error_only", "answer_uniqueness", "format_validity",
    "target_metadata", "naturalness", "provenance",
}
_SCHEMA: dict[str, Any] | None = None


def load_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("top-level JSON must be an item array or an object with items")


def output_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA


def validate_semantics(item: dict) -> list[str]:
    errors: list[str] = []
    prefix = f"[{item['item_id']}]"
    if item["answer_match"] is not (item["independent_answer"] == item["generator_answer"]):
        errors.append(f"{prefix} $.answer_match: must equal independent_answer == generator_answer")

    if item["verdict"] == "PASS":
        if item["critical_failure"] is not False:
            errors.append(f"{prefix} $.critical_failure: PASS requires false")
        if item["detected_error_count"] != 1:
            errors.append(f"{prefix} $.detected_error_count: PASS requires exactly 1")
        if item["detected_error_position"] not in LABELS:
            errors.append(f"{prefix} $.detected_error_position: PASS requires A/B/C/D")
        if item["detected_error_position"] != item["independent_answer"]:
            errors.append(f"{prefix} $.detected_error_position: must equal independent_answer")
        if item["independent_answer"] not in LABELS:
            errors.append(f"{prefix} $.independent_answer: PASS requires A/B/C/D")
        if item["non_error_parts_valid"] is not True:
            errors.append(f"{prefix} $.non_error_parts_valid: PASS requires true")
        if item["minimal_correction_valid"] is not True:
            errors.append(f"{prefix} $.minimal_correction_valid: PASS requires true")
        if item["grammar_validity"] != "PASS":
            errors.append(f"{prefix} $.grammar_validity: PASS requires PASS")
        blocked_checks = sorted(
            key for key in CHECK_KEYS if item["checks"][key] in {"FAIL", "AMBIGUOUS"}
        )
        if blocked_checks:
            errors.append(f"{prefix} $.checks: PASS forbids failed/ambiguous checks={blocked_checks}")
        severities = [issue["severity"] for issue in item["issues"]]
        for severity in ("CRITICAL", "MAJOR"):
            if severity in severities:
                errors.append(f"{prefix} $.issues: PASS forbids {severity} issues")
        if item["revision_requirements"]:
            errors.append(f"{prefix} $.revision_requirements: PASS requires an empty array")

    assessments = item.get("marked_part_assessments", {})
    if sum(value == "ERROR" for value in assessments.values()) != item["detected_error_count"]:
        errors.append(f"{prefix} $.marked_part_assessments: ERROR count disagrees with detected_error_count")
    if item["verdict"] == "REVISE" and not item["revision_requirements"]:
        errors.append(f"{prefix} $.revision_requirements: REVISE requires at least one requirement")
    return errors


def validate_contract(item: object, errors: list[str] | None = None) -> list[str]:
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        collected = [f"[{item_id}] $: reviewer result must be an object"]
    else:
        structural = schema_errors(item, output_schema())
        collected = [
            f"[{item_id}] {OUTPUT_SCHEMA_PATH.name}: {error}"
            for error in structural
        ]
        if not structural:
            collected = validate_semantics(item)
    if errors is not None:
        errors.extend(collected)
    return collected


validate = validate_contract
validate_item = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python validate_output.py <review.json>")
        return 2
    try:
        items = load_items(Path(sys.argv[1]))
        results = [(item.get("item_id", "?") if isinstance(item, dict) else "?", validate_contract(item)) for item in items]
    except ValueError as exc:
        print(f"CONTENT ERROR: {exc}")
        return 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"SYSTEM ERROR: unexpected validator exception: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    failures = [(item_id, errors) for item_id, errors in results if errors]
    print(f"Checked {len(results)} WE Reviewer v2 result(s); {len(failures)} failed.")
    for item_id, errors in failures:
        print(f"[{item_id}]")
        for error in errors:
            print(f"  - {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
