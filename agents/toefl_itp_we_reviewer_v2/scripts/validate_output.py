#!/usr/bin/env python3
"""Contract validator for WE Reviewer v2 output.

Public validation API
---------------------
``validate_contract(item)`` is the ONLY supported entry point for external
callers (CLI, internal imports, tests, orchestrator). It runs, in order:

1. Structural validation against the committed
   ``schema/reviewer_output_v2.schema.json`` (source of truth for the output
   shape, including ``additionalProperties: false``). Structural failures
   short-circuit: the semantic stage never sees a malformed record.
2. ``validate_semantics(item)`` - the checks that a JSON Schema cannot
   express (cross-field consistency and safety invariants).

``validate_semantics`` is exposed for introspection and testing only. Calling
it directly bypasses the structural schema gate and is not a supported
validation path.

``validate`` is kept as a backwards-compatible alias of ``validate_contract``
so that existing importers are gated too.

It does not re-decide English grammaticality; that is the reviewer's
independent audit.
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

OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "reviewer_output_v2.schema.json"

LABELS = {"A", "B", "C", "D"}
VALID_ANSWERS = LABELS | {"NONE", "AMBIGUOUS"}
DETECTED_ERROR_POSITIONS = LABELS | {"NONE"}


def load_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("top-level JSON must be an item array or an object with items")


def validate_semantics(item: dict) -> list[str]:
    errors: list[str] = []
    required = {
        "item_id", "section", "agent_version", "verdict", "critical_failure",
        "independent_answer", "generator_answer", "answer_match", "grammar_validity",
        "format_validity", "detected_error_count", "detected_error_position",
        "non_error_parts_valid", "minimal_correction_valid", "marked_part_assessments",
        "checks", "issues", "revision_requirements", "source_similarity_risk", "provenance",
    }
    errors.extend(f"missing required field: {key}" for key in sorted(required - set(item)))
    if item.get("section") != "Written Expression":
        errors.append("section must be Written Expression")
    if item.get("agent_version") != "Written Expression Reviewer v2.0":
        errors.append("agent_version mismatch")
    if item.get("verdict") not in {"PASS", "REVISE", "REJECT"}:
        errors.append("invalid verdict")
    if item.get("independent_answer") not in VALID_ANSWERS:
        errors.append("invalid independent_answer")
    if item.get("generator_answer") not in LABELS:
        errors.append("invalid generator_answer")
    if item.get("grammar_validity") not in {"PASS", "FAIL", "AMBIGUOUS"}:
        errors.append("invalid grammar_validity")
    if item.get("format_validity") not in {"PASS", "WARN", "FAIL"}:
        errors.append("invalid format_validity")
    if item.get("detected_error_position") not in DETECTED_ERROR_POSITIONS:
        errors.append("invalid detected_error_position")
    if item.get("critical_failure") is True and item.get("verdict") == "PASS":
        errors.append("critical_failure=true cannot coexist with PASS")
    if item.get("detected_error_count") == 1 and item.get("independent_answer") not in LABELS:
        errors.append("one detected error requires a letter independent_answer")
    if item.get("detected_error_count") != 1 and item.get("independent_answer") == item.get("generator_answer") and item.get("verdict") == "PASS":
        errors.append("PASS requires exactly one independently detected error")
    assessments = item.get("marked_part_assessments", {})
    if set(assessments) != LABELS:
        errors.append("marked_part_assessments must have exactly A/B/C/D")
    elif sum(value == "ERROR" for value in assessments.values()) != item.get("detected_error_count"):
        errors.append("marked_part_assessments ERROR count disagrees with detected_error_count")
    checks = item.get("checks", {})
    allowed_checks = {
        "grammar_validity": {"PASS", "FAIL", "AMBIGUOUS"},
        "one_error_only": {"PASS", "FAIL", "AMBIGUOUS"},
        "answer_uniqueness": {"PASS", "FAIL", "AMBIGUOUS"},
        "format_validity": {"PASS", "WARN", "FAIL"},
        "target_metadata": {"PASS", "FAIL", "AMBIGUOUS"},
        "naturalness": {"PASS", "WARN", "FAIL"},
        "provenance": {"PASS", "WARN", "FAIL"},
    }
    for key in ("grammar_validity", "one_error_only", "answer_uniqueness", "format_validity", "target_metadata", "naturalness", "provenance"):
        if key not in checks:
            errors.append(f"checks.{key} missing")
        elif checks[key] not in allowed_checks[key]:
            errors.append(f"checks.{key} has invalid value")
    provenance = item.get("provenance", {})
    required_provenance = {"agent_version", "prompt_hash", "spec_version", "format_spec_version", "review_batch_id", "item_review_order", "invocation_id", "runtime_model"}
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    else:
        errors.extend(f"missing provenance field: {key}" for key in sorted(required_provenance - set(provenance)))
    if not isinstance(item.get("issues"), list) or not isinstance(item.get("revision_requirements"), list):
        errors.append("issues and revision_requirements must be arrays")
    if item.get("verdict") == "PASS" and item.get("grammar_validity") != "PASS":
        errors.append("PASS verdict requires grammar_validity=PASS")
    return errors


_SCHEMA_CACHE: dict | None = None


def output_schema() -> dict:
    """Load (and memoize) the committed structural schema."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA_CACHE


def validate_contract(item) -> list[str]:
    """The full public contract: structural schema gate, then semantics.

    Every caller - CLI, internal import, test, orchestrator - goes through
    this one function, so there is no path that reaches the semantic checks
    without first clearing the committed JSON Schema.
    """
    if not isinstance(item, dict):
        return ["<root>: expected type ['object'], got %s" % type(item).__name__]
    structural = schema_errors(item, output_schema())
    if structural:
        return [f"{OUTPUT_SCHEMA_PATH.name}: {error}" for error in structural]
    return validate_semantics(item)


# Backwards-compatible name. Existing importers that call ``validate()`` now
# get the structural schema gate for free.
validate = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python validate_output.py <review.json>")
        return 2
    try:
        items = load_items(Path(sys.argv[1]))

        # The CLI has no validation logic of its own: it calls exactly the same
        # public entry point that internal importers call.
        results = [
            (item.get("item_id", "?") if isinstance(item, dict) else "?", validate_contract(item))
            for item in items
        ]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
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
