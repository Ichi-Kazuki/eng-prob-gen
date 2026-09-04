"""Structure v0.2 Reviewer output exact-text contract and canonicalization.

Enforces the fail-closed rules for the blind candidate Reviewer contract:
exact item identity, exact-text option_judgments completeness, and the
VALID/MARGINAL-must-have-exactly-one-diagnostic / INVALID-must-have-none
rule. No candidate selection, no intended-correct reconciliation, and no
Planner/difficulty/clause-count comparison happen here.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parent
REVIEWER_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "reviewer_output.schema.json"

VALID_JUDGMENTS_REQUIRING_DIAGNOSTIC = frozenset({"VALID", "MARGINAL"})


def _deduplicate(errors: list[str]) -> list[str]:
    return list(dict.fromkeys(errors))


def _reviewer_input_items(reviewer_input: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = reviewer_input.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _item_errors(output_item: Mapping[str, Any], input_item: Mapping[str, Any], item_label: str) -> list[str]:
    errors: list[str] = []
    candidate_options = input_item.get("candidate_options")
    if not isinstance(candidate_options, list) or len(candidate_options) != 7:
        return [f"reviewer[{item_label}]: blind candidate_options must contain exactly seven strings"]
    if len(set(candidate_options)) != len(candidate_options):
        return [f"reviewer[{item_label}]: blind candidate_options are not unique"]
    expected_texts = set(candidate_options)

    option_judgments = output_item.get("option_judgments")
    if not isinstance(option_judgments, list):
        return [f"reviewer[{item_label}]: option_judgments must be an array"]

    observed_texts = [
        entry.get("option_text") for entry in option_judgments if isinstance(entry, dict)
    ]
    if len(option_judgments) != 7 or len(observed_texts) != 7:
        errors.append(f"reviewer[{item_label}]: option_judgments must contain exactly seven option objects")
        return errors

    observed_counts = Counter(observed_texts)
    expected_counts = Counter(candidate_options)
    if observed_counts != expected_counts:
        missing = sorted((expected_counts - observed_counts).elements())
        duplicated = sorted(
            text for text, count in observed_counts.items() if count > 1 and text in expected_texts
        )
        invented = sorted((observed_counts - expected_counts).elements())
        if missing:
            errors.append(f"reviewer[{item_label}]: option_judgments missing exact visible text(s) {missing}")
        if duplicated:
            errors.append(f"reviewer[{item_label}]: option_judgments duplicate exact visible text(s) {duplicated}")
        if invented:
            errors.append(
                f"reviewer[{item_label}]: option_judgments contain invented or modified text(s) {invented}"
            )
        return errors

    judgment_by_text: dict[str, str] = {
        entry["option_text"]: entry["judgment"] for entry in option_judgments if isinstance(entry, dict)
    }

    diagnostics = output_item.get("candidate_diagnostics")
    if not isinstance(diagnostics, list):
        errors.append(f"reviewer[{item_label}]: candidate_diagnostics must be an array")
        return errors

    diagnostic_texts = [
        entry.get("option_text") for entry in diagnostics if isinstance(entry, dict)
    ]
    if len(diagnostics) != len(diagnostic_texts):
        errors.append(f"reviewer[{item_label}]: candidate_diagnostics entries must be objects")
        return errors

    diagnostic_counts = Counter(diagnostic_texts)
    for text, count in diagnostic_counts.items():
        if count > 1:
            errors.append(f"reviewer[{item_label}]: duplicate candidate_diagnostics entry for {text!r}")

    invented_diagnostics = sorted(set(diagnostic_texts) - expected_texts)
    if invented_diagnostics:
        errors.append(
            f"reviewer[{item_label}]: candidate_diagnostics reference invented or modified text(s) {invented_diagnostics}"
        )

    required_diagnostic_texts = {
        text for text, judgment in judgment_by_text.items() if judgment in VALID_JUDGMENTS_REQUIRING_DIAGNOSTIC
    }
    prohibited_diagnostic_texts = {
        text for text, judgment in judgment_by_text.items() if judgment not in VALID_JUDGMENTS_REQUIRING_DIAGNOSTIC
    }

    present_diagnostic_texts = set(diagnostic_texts) & expected_texts
    missing_diagnostics = sorted(required_diagnostic_texts - present_diagnostic_texts)
    if missing_diagnostics:
        errors.append(
            f"reviewer[{item_label}]: VALID/MARGINAL option(s) missing a diagnostic: {missing_diagnostics}"
        )

    disallowed_diagnostics = sorted(present_diagnostic_texts & prohibited_diagnostic_texts)
    if disallowed_diagnostics:
        errors.append(
            f"reviewer[{item_label}]: INVALID option(s) must not have a diagnostic: {disallowed_diagnostics}"
        )

    return errors


def validate_reviewer_contract(raw_reviewer: Any, reviewer_input: Mapping[str, Any]) -> list[str]:
    """Validate one raw Reviewer response against the blind candidate contract."""

    errors = schema_errors(raw_reviewer, load_schema(REVIEWER_OUTPUT_SCHEMA_PATH))
    if not isinstance(raw_reviewer, dict) or not isinstance(reviewer_input, dict):
        return errors

    output_items = raw_reviewer.get("items")
    input_items = _reviewer_input_items(reviewer_input)
    if not isinstance(output_items, list):
        return errors

    expected_ids = [item.get("item_id") for item in input_items]
    actual_ids = [item.get("item_id") for item in output_items if isinstance(item, dict)]
    valid_actual_ids = [value for value in actual_ids if isinstance(value, str)]
    duplicates = sorted({value for value in valid_actual_ids if valid_actual_ids.count(value) > 1})
    if duplicates:
        errors.append(f"reviewer: duplicate item_id(s): {duplicates}")
    if actual_ids != expected_ids:
        errors.append("reviewer: item IDs/order do not match the blind candidate input")

    input_by_id = {item.get("item_id"): item for item in input_items}
    for output_item in output_items:
        if not isinstance(output_item, dict):
            continue
        item_id = output_item.get("item_id")
        input_item = input_by_id.get(item_id)
        if input_item is None:
            continue
        item_label = str(item_id)
        errors.extend(_item_errors(output_item, input_item, item_label))

    return _deduplicate(errors)


def canonicalize_reviewer_output(raw_reviewer: Any, reviewer_input: Mapping[str, Any]) -> dict[str, Any]:
    """Map a validated raw Reviewer response to the exact-text-keyed internal form."""

    errors = validate_reviewer_contract(raw_reviewer, reviewer_input)
    if errors:
        raise ValueError("reviewer raw output cannot be canonicalized: " + "; ".join(errors))
    if not isinstance(raw_reviewer, dict):  # pragma: no cover - guarded above
        raise ValueError("reviewer raw output must be an object")

    canonical_items: list[dict[str, Any]] = []
    for output_item in raw_reviewer["items"]:
        option_judgments = {
            entry["option_text"]: entry["judgment"] for entry in output_item["option_judgments"]
        }
        candidate_diagnostics = {
            entry["option_text"]: {
                "natural_wording": entry["natural_wording"],
                "serious_defect": entry["serious_defect"],
                "observed_clause_count": entry["observed_clause_count"],
                "candidate_pool_observed_difficulty": entry["candidate_pool_observed_difficulty"],
                "difficulty_confidence": entry["difficulty_confidence"],
            }
            for entry in output_item["candidate_diagnostics"]
        }
        canonical_items.append({
            "item_id": output_item["item_id"],
            "option_judgments": option_judgments,
            "candidate_diagnostics": candidate_diagnostics,
            "comment": output_item["comment"],
        })
    return {"items": canonical_items}


__all__ = [
    "validate_reviewer_contract",
    "canonicalize_reviewer_output",
]
