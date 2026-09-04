"""Structure v0.2 Generator/Reviewer output contracts and canonicalization.

Enforces the fail-closed rules for:
  * the v0.2 Generator candidate batch, checked against its Planner plan
    (batch identity, Planner-owned metadata, authorship metadata, the
    single-blank stem, the seven raw candidate surfaces, and the
    sentence-length hard gate);
  * the blind candidate Reviewer contract: exact item identity, exact-text
    option_judgments completeness, and the VALID/MARGINAL-must-have-
    exactly-one-diagnostic / INVALID-must-have-none rule.

No candidate selection, no intended-correct reconciliation, and no
deterministic grammar/clause-count/difficulty realization checking happen
here.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from shared.schema_validation import load_schema, schema_errors

from structure.contracts import (
    BLANK_MARKER,
    build_completed_sentence,
    count_words,
    normalized_option_surface,
)


ROOT = Path(__file__).resolve().parent
REVIEWER_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "reviewer_output.schema.json"
GENERATOR_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "generator_output.schema.json"
PLAN_SCHEMA_PATH = ROOT / "schemas" / "plan.schema.json"

VALID_JUDGMENTS_REQUIRING_DIAGNOSTIC = frozenset({"VALID", "MARGINAL"})

DISTRACTOR_CANDIDATE_IDS: tuple[str, ...] = ("d1", "d2", "d3", "d4", "d5", "d6")
ALL_CANDIDATE_IDS: tuple[str, ...] = ("correct",) + DISTRACTOR_CANDIDATE_IDS


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def validate_generator_contract(output: Any, plan: Any) -> list[str]:
    """Validate one v0.2 Generator batch response against its Planner plan.

    Enforces: batch identity (15/15, ID order match, no duplicates, plan
    order 1..15); Planner-owned metadata (section, primary_target,
    difficulty); authorship metadata (non-whitespace subtype,
    vocabulary_domain, answer_explanation, and all six distractor
    rationales); a single blank marker in the stem; exact-string and
    normalized-surface uniqueness across all seven raw candidate texts;
    and the sentence-length hard gate using the Generator-intended
    correct_option.text. No semantic grammar/difficulty/clause_count
    checking is performed.
    """

    errors = schema_errors(output, load_schema(GENERATOR_OUTPUT_SCHEMA_PATH))
    errors.extend(schema_errors(plan, load_schema(PLAN_SCHEMA_PATH)))
    if not isinstance(output, dict) or not isinstance(plan, dict):
        return _deduplicate(errors)

    generated_items = output.get("items")
    planned_items = plan.get("items")
    if not isinstance(generated_items, list) or not isinstance(planned_items, list):
        return _deduplicate(errors)

    if len(generated_items) != 15:
        errors.append(f"generator: expected exactly 15 items, got {len(generated_items)}")
    if len(planned_items) != 15:
        errors.append(f"generator: plan must contain exactly 15 items, got {len(planned_items)}")

    valid_planned = [item for item in planned_items if isinstance(item, dict)]
    plan_orders = [item.get("order") for item in valid_planned]
    if plan_orders != list(range(1, len(valid_planned) + 1)):
        errors.append("generator: plan item order must be 1..15")

    generated_ids = [item.get("item_id") if isinstance(item, dict) else None for item in generated_items]
    valid_generated_ids = [value for value in generated_ids if isinstance(value, str)]
    duplicate_generated_ids = sorted(
        {value for value in valid_generated_ids if valid_generated_ids.count(value) > 1}
    )
    if duplicate_generated_ids:
        errors.append(f"generator: duplicate item_id(s): {duplicate_generated_ids}")

    planned_ids = [item.get("item_id") for item in valid_planned]
    if generated_ids != planned_ids:
        errors.append(
            f"generator: item IDs/order do not match the plan sequence: expected {planned_ids}, got {generated_ids}"
        )

    plan_by_id = {item.get("item_id"): item for item in valid_planned}

    for index, item in enumerate(generated_items):
        if not isinstance(item, dict):
            errors.append(f"generator[index-{index}]: item must be an object")
            continue
        item_id = item.get("item_id")
        label = item_id if isinstance(item_id, str) and item_id else f"index-{index}"
        prefix = f"generator[{label}]"
        planned = plan_by_id.get(item_id)

        if item.get("section") != "Structure":
            errors.append(f"{prefix}: section must be Structure")

        if planned is None:
            errors.append(f"{prefix}: no matching planned item_id in the plan sequence")
        else:
            if item.get("primary_target") != planned.get("primary_target"):
                errors.append(f"{prefix}: primary_target does not match Planner metadata")
            if item.get("difficulty") != planned.get("difficulty"):
                errors.append(f"{prefix}: difficulty does not match Planner metadata")

        if not _nonempty_string(item.get("subtype")):
            errors.append(f"{prefix}: subtype must be non-whitespace")
        if not _nonempty_string(item.get("vocabulary_domain")):
            errors.append(f"{prefix}: vocabulary_domain must be non-whitespace")
        if not _nonempty_string(item.get("answer_explanation")):
            errors.append(f"{prefix}: answer_explanation must be non-whitespace")

        distractor_candidates = item.get("distractor_candidates")
        if not isinstance(distractor_candidates, dict):
            errors.append(f"{prefix}: distractor_candidates must be an object")
            distractor_candidates = {}
        for candidate_id in DISTRACTOR_CANDIDATE_IDS:
            candidate = distractor_candidates.get(candidate_id)
            if not isinstance(candidate, dict) or not _nonempty_string(candidate.get("rationale")):
                errors.append(f"{prefix}: distractor_candidates.{candidate_id}.rationale must be non-whitespace")

        stem = item.get("stem")
        stem_has_single_blank = isinstance(stem, str) and stem.count(BLANK_MARKER) == 1
        if not stem_has_single_blank:
            errors.append(f"{prefix}: stem must contain exactly one {BLANK_MARKER!r} blank marker")

        correct_option = item.get("correct_option")
        correct_text = correct_option.get("text") if isinstance(correct_option, dict) else None

        candidate_texts: dict[str, Any] = {"correct": correct_text}
        for candidate_id in DISTRACTOR_CANDIDATE_IDS:
            candidate = distractor_candidates.get(candidate_id)
            candidate_texts[candidate_id] = candidate.get("text") if isinstance(candidate, dict) else None

        exact_texts: dict[str, str] = {}
        surfaces: dict[str, str] = {}
        for candidate_id in ALL_CANDIDATE_IDS:
            text = candidate_texts.get(candidate_id)
            if not isinstance(text, str) or not text.strip():
                errors.append(f"{prefix}: candidate {candidate_id} text must be non-whitespace")
                continue
            if text in exact_texts:
                errors.append(
                    f"{prefix}: candidate {candidate_id} duplicates exact text of candidate {exact_texts[text]}"
                )
            else:
                exact_texts[text] = candidate_id
            normalized = normalized_option_surface(text)
            if normalized in surfaces:
                errors.append(
                    f"{prefix}: candidate {candidate_id} duplicates candidate {surfaces[normalized]} "
                    "after normalization"
                )
            else:
                surfaces[normalized] = candidate_id

        if stem_has_single_blank and _nonempty_string(correct_text) and planned is not None:
            bin_info = planned.get("sentence_length_bin")
            if isinstance(bin_info, dict):
                minimum = bin_info.get("minimum")
                maximum = bin_info.get("maximum")
                if isinstance(minimum, int) and isinstance(maximum, int):
                    completed_sentence = build_completed_sentence(stem, correct_text)
                    actual_word_count = count_words(completed_sentence)
                    if not (minimum <= actual_word_count <= maximum):
                        bin_label = bin_info.get("label")
                        target_word_count = planned.get("target_word_count")
                        errors.append(
                            f"{prefix}: completed sentence word count {actual_word_count} is outside planned "
                            f"{bin_label} bin ({minimum}..{maximum}); target_word_count={target_word_count}"
                        )

    return _deduplicate(errors)


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
    "validate_generator_contract",
    "validate_reviewer_contract",
    "canonicalize_reviewer_output",
]
