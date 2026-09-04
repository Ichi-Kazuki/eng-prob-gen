"""Fail-closed Structure v0.1 contract and deterministic validation rules."""

from __future__ import annotations

import copy
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.schema_validation import load_schema, schema_errors

from .planner import PLAN_SCHEMA_PATH, load_profile


ROOT = Path(__file__).resolve().parent
BLANK_MARKER = "____"
LETTERS = ("A", "B", "C", "D")
REVIEWER_DIFFICULTY_CONFIDENCES = frozenset({"HIGH", "MEDIUM", "LOW"})
REVIEWER_ANSWER_SENTINELS = frozenset({"AMBIGUOUS", "NONE"})
SCHEMA_PATHS = {
    "plan": PLAN_SCHEMA_PATH,
    "generator_item": ROOT / "schemas" / "generator_item.schema.json",
    "generator": ROOT / "schemas" / "generator_output.schema.json",
    "reviewer_input": ROOT / "schemas" / "reviewer_input.schema.json",
    "reviewer": ROOT / "schemas" / "reviewer_output.schema.json",
    "solver_input": ROOT / "schemas" / "solver_input.schema.json",
    "solver": ROOT / "schemas" / "solver_output.schema.json",
}


def _expected_items(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = plan.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _schema(value: Any, name: str) -> list[str]:
    return schema_errors(value, load_schema(SCHEMA_PATHS[name]))


def _ids(items: Iterable[Any]) -> tuple[list[str], list[str]]:
    values = [item.get("item_id") for item in items if isinstance(item, dict)]
    valid = [value for value in values if isinstance(value, str)]
    duplicates = sorted({value for value in valid if valid.count(value) > 1})
    return valid, duplicates


def count_words(text: str) -> int:
    """Count words using the deterministic Unicode-whitespace splitting convention."""

    return len(text.split())


def build_completed_sentence(stem: str, option_text: str) -> str:
    """Replace the single blank marker in `stem` with the canonical option text."""

    return stem.replace(BLANK_MARKER, option_text, 1)


def normalized_option_surface(value: str) -> str:
    """Normalize option text for deterministic duplicate-surface detection."""

    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_plan(plan: Any) -> list[str]:
    errors = _schema(plan, "plan")
    if errors or not isinstance(plan, dict):
        return errors
    expected_targets = set(load_profile()["primary_target_weights"])
    if any(item["primary_target"] not in expected_targets for item in plan["items"]):
        errors.append("plan: primary_target is outside the Structure profile")
    expected_ids = [f"structure-v01-{plan['seed']:016x}-{order:02d}" for order in range(1, 16)]
    actual_ids = [item["item_id"] for item in plan["items"]]
    if actual_ids != expected_ids:
        errors.append("plan: item IDs are not the deterministic Planner-owned sequence")
    if [item["order"] for item in plan["items"]] != list(range(1, 16)):
        errors.append("plan: item order is not 1 through 15")
    return errors


def validate_generator_contract(output: Any, plan: Mapping[str, Any]) -> list[str]:
    """Validate one complete Generator response, including hard deterministic gates."""

    errors = _schema(output, "generator")
    if not isinstance(output, dict):
        return errors
    generated_items = output.get("items")
    planned_items = _expected_items(plan)
    if not isinstance(generated_items, list):
        return errors
    if len(generated_items) != 15:
        errors.append(f"generator: expected exactly 15 items, got {len(generated_items)}")

    planned_ids = [item.get("item_id") for item in planned_items]
    actual_ids, duplicates = _ids(generated_items)
    if duplicates:
        errors.append(f"generator: duplicate item_id(s): {duplicates}")
    if actual_ids != planned_ids:
        errors.append(f"generator: item IDs/order do not match the Planner sequence: expected {planned_ids}, got {actual_ids}")

    for index, item in enumerate(generated_items):
        item_id = item.get("item_id", f"index-{index}") if isinstance(item, dict) else f"index-{index}"
        prefix = f"generator[{item_id}]"
        errors.extend(f"{prefix}: {message}" for message in _schema(item, "generator_item"))
        if not isinstance(item, dict):
            continue
        if item.get("section") != "Structure":
            errors.append(f"{prefix}: section must be Structure")
        planned = planned_items[index] if index < len(planned_items) else None
        if planned is not None:
            if item.get("primary_target") != planned.get("primary_target"):
                errors.append(f"{prefix}: primary_target does not match Planner metadata")
            if item.get("difficulty") != planned.get("difficulty"):
                errors.append(f"{prefix}: difficulty does not match Planner metadata")
            if item.get("item_id") != planned.get("item_id"):
                errors.append(f"{prefix}: item_id does not match its planned order")
        options = item.get("options")
        if not isinstance(options, dict) or set(options) != set(LETTERS):
            errors.append(f"{prefix}: options must contain exactly A/B/C/D")
        else:
            surfaces: dict[str, str] = {}
            for letter in LETTERS:
                option = options.get(letter)
                if not _nonempty_string(option):
                    errors.append(f"{prefix}: option {letter} is empty")
                    continue
                surface = normalized_option_surface(option) if isinstance(option, str) else ""
                if surface in surfaces:
                    errors.append(f"{prefix}: option {letter} duplicates option {surfaces[surface]} after normalization")
                else:
                    surfaces[surface] = letter
        correct = item.get("correct_answer")
        if correct not in LETTERS:
            errors.append(f"{prefix}: correct_answer must be A/B/C/D")
        elif isinstance(options, dict) and correct not in options:
            errors.append(f"{prefix}: correct_answer option is missing")
        rationales = item.get("distractor_rationales")
        if not isinstance(rationales, dict) or set(rationales) != set(LETTERS):
            errors.append(f"{prefix}: distractor_rationales must contain exactly A/B/C/D")
        if not _nonempty_string(item.get("answer_explanation")):
            errors.append(f"{prefix}: answer_explanation must be non-empty")
        stem = item.get("stem")
        stem_has_single_blank = isinstance(stem, str) and stem.count(BLANK_MARKER) == 1
        if not stem_has_single_blank:
            errors.append(f"{prefix}: stem must contain exactly one {BLANK_MARKER!r} blank marker")
        elif (
            isinstance(stem, str)
            and planned is not None
            and isinstance(options, dict)
            and isinstance(correct, str)
            and correct in options
        ):
            option_text = options[correct]
            bin_info = planned.get("sentence_length_bin")
            if isinstance(option_text, str) and option_text.strip() and isinstance(bin_info, dict):
                minimum = bin_info.get("minimum")
                maximum = bin_info.get("maximum")
                if isinstance(minimum, int) and isinstance(maximum, int):
                    completed_sentence = build_completed_sentence(stem, option_text)
                    actual_word_count = count_words(completed_sentence)
                    if not (minimum <= actual_word_count <= maximum):
                        label = bin_info.get("label")
                        target_word_count = planned.get("target_word_count")
                        errors.append(
                            f"{prefix}: completed sentence word count {actual_word_count} is outside planned "
                            f"{label} bin ({minimum}..{maximum}); target_word_count={target_word_count}"
                        )
    return _deduplicate(errors)


def _deduplicate(errors: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(errors))


def validate_blind_input(payload: Any, plan: Mapping[str, Any] | None = None) -> list[str]:
    errors = _schema(payload, "reviewer_input")
    if not isinstance(payload, dict):
        return errors
    items = payload.get("items")
    if not isinstance(items, list):
        return errors
    ids, duplicates = _ids(items)
    if duplicates:
        errors.append(f"blind input: duplicate item_id(s): {duplicates}")
    if plan is not None:
        expected = [item.get("item_id") for item in _expected_items(plan)]
        if ids != expected:
            errors.append("blind input: item IDs/order do not match the Planner sequence")
    leakage = find_leakage(payload)
    errors.extend(f"blind input: forbidden field {path}" for path in leakage)
    return _deduplicate(errors)


def validate_generator_blind_input(payload: Any, plan: Mapping[str, Any] | None = None) -> list[str]:
    return validate_blind_input(payload, plan)


def _reviewer_option_text_errors(
    output_item: Mapping[str, Any], blind_item: Mapping[str, Any], item_label: str
) -> list[str]:
    """Validate raw Reviewer option text identity without normalizing strings."""

    errors: list[str] = []
    options = blind_item.get("options")
    judgments = output_item.get("option_judgments")
    if not isinstance(options, dict) or set(options) != set(LETTERS):
        return [f"reviewer[{item_label}]: blind options must contain exactly A/B/C/D"]
    expected_texts = [options[letter] for letter in LETTERS]
    if not all(isinstance(text, str) for text in expected_texts):
        return [f"reviewer[{item_label}]: blind option texts must be strings"]
    if len(set(expected_texts)) != len(expected_texts):
        return [f"reviewer[{item_label}]: blind option texts are not one-to-one"]
    if not isinstance(judgments, list):
        return errors

    observed_texts = [entry.get("option_text") for entry in judgments if isinstance(entry, dict)]
    if len(judgments) != 4 or len(observed_texts) != 4:
        errors.append(f"reviewer[{item_label}]: option_judgments must contain exactly four option objects")
        return errors
    if not all(isinstance(text, str) and bool(text.strip()) for text in observed_texts):
        errors.append(f"reviewer[{item_label}]: option_text must be non-empty strings")
        return errors

    expected_counts = Counter(expected_texts)
    observed_counts = Counter(observed_texts)
    if observed_counts != expected_counts:
        missing = sorted(text for text, count in (expected_counts - observed_counts).items() for _ in range(count))
        duplicates = sorted(text for text, count in (observed_counts - expected_counts).items() for _ in range(count) if text in expected_counts)
        extras = sorted(text for text, count in (observed_counts - expected_counts).items() for _ in range(count) if text not in expected_counts)
        errors.append(
            f"reviewer[{item_label}]: option_text values must match the four blind options exactly once "
            f"(missing={missing}, duplicates={duplicates}, extras={extras})"
        )

    best_answer_text = output_item.get("best_answer_text")
    if not isinstance(best_answer_text, str) or (
        best_answer_text not in expected_texts and best_answer_text not in REVIEWER_ANSWER_SENTINELS
    ):
        errors.append(f"reviewer[{item_label}]: best_answer_text is not an exact visible option or allowed sentinel")
    return errors


def validate_reviewer_contract(output: Any, blind: Mapping[str, Any], plan: Mapping[str, Any] | None = None) -> list[str]:
    errors = _schema(output, "reviewer")
    if not isinstance(output, dict):
        return errors
    items = output.get("items")
    if not isinstance(items, list):
        return errors
    expected = [item.get("item_id") for item in blind.get("items", []) if isinstance(item, dict)]
    actual, duplicates = _ids(items)
    if duplicates:
        errors.append(f"reviewer: duplicate item_id(s): {duplicates}")
    if actual != expected:
        errors.append("reviewer: item IDs/order do not match blind input")
    blind_items = blind.get("items", []) if isinstance(blind, dict) else []
    if isinstance(blind_items, list):
        for output_item, blind_item in zip(items, blind_items):
            if isinstance(output_item, dict) and isinstance(blind_item, dict):
                item_label = str(output_item.get("item_id", "unknown"))
                errors.extend(_reviewer_option_text_errors(output_item, blind_item, item_label))
    errors.extend(f"reviewer: forbidden field {path}" for path in find_leakage(output))
    return _deduplicate(errors)


def canonicalize_reviewer_output(output: Any, blind: Mapping[str, Any]) -> dict[str, Any]:
    """Map a validated raw text-based Reviewer response to the legacy internal shape."""

    errors = validate_reviewer_contract(output, blind)
    if errors:
        raise ValueError("reviewer raw output cannot be canonicalized: " + "; ".join(errors))
    if not isinstance(output, dict):  # pragma: no cover - guarded by validate_reviewer_contract
        raise ValueError("reviewer raw output must be an object")
    blind_items = blind.get("items")
    output_items = output.get("items")
    if not isinstance(blind_items, list) or not isinstance(output_items, list):  # pragma: no cover
        raise ValueError("reviewer raw output and blind input must contain items arrays")

    canonical_items: list[dict[str, Any]] = []
    for output_item, blind_item in zip(output_items, blind_items):
        if not isinstance(output_item, dict) or not isinstance(blind_item, dict):  # pragma: no cover
            raise ValueError("reviewer raw output and blind input items must be objects")
        options = blind_item["options"]
        text_to_judgment = {
            entry["option_text"]: entry["judgment"] for entry in output_item["option_judgments"]
        }
        option_to_letter = {options[letter]: letter for letter in LETTERS}
        best_answer_text = output_item["best_answer_text"]
        best_answer = option_to_letter.get(best_answer_text, best_answer_text)
        canonical_items.append({
            "item_id": output_item["item_id"],
            "option_judgments": {
                letter: text_to_judgment[options[letter]] for letter in LETTERS
            },
            "best_answer": best_answer,
            "natural_wording": output_item["natural_wording"],
            "serious_defect": output_item["serious_defect"],
            "comment": output_item["comment"],
            "observed_difficulty": output_item["observed_difficulty"],
            "difficulty_confidence": output_item["difficulty_confidence"],
        })
    return {"items": canonical_items}


def reviewer_difficulty_diagnostic_reasons(
    planned_difficulty: Any, reviewer_item: Mapping[str, Any]
) -> list[str]:
    """Return difficulty diagnostics that are never used as acceptance reasons."""

    observed_difficulty = reviewer_item.get("observed_difficulty")
    confidence = reviewer_item.get("difficulty_confidence")
    reasons: list[str] = []
    if observed_difficulty != planned_difficulty:
        reasons.append(
            f"reviewer_difficulty_mismatch: planned={planned_difficulty}, observed={observed_difficulty}"
        )
    if confidence == "LOW":
        reasons.append("reviewer_difficulty_confidence_low")
    elif confidence not in REVIEWER_DIFFICULTY_CONFIDENCES - {"LOW"}:
        reasons.append(f"reviewer_difficulty_confidence_not_accepted: {confidence}")
    return reasons


def reviewer_difficulty_diagnostics(
    plan: Mapping[str, Any], reviewer: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Return auditable per-item difficulty diagnostics for a completed review."""

    reviewer_by_id = {
        item.get("item_id"): item
        for item in (reviewer or {}).get("items", [])
        if isinstance(item, dict)
    }
    diagnostics: list[dict[str, Any]] = []
    for planned_item in _expected_items(plan):
        item_id = planned_item.get("item_id")
        reviewer_item = reviewer_by_id.get(item_id)
        if not isinstance(reviewer_item, dict):
            continue
        diagnostics.append({
            "item_id": item_id,
            "planned_difficulty": planned_item.get("difficulty"),
            "observed_difficulty": reviewer_item.get("observed_difficulty"),
            "difficulty_confidence": reviewer_item.get("difficulty_confidence"),
            "reasons": reviewer_difficulty_diagnostic_reasons(planned_item.get("difficulty"), reviewer_item),
        })
    return diagnostics


def reviewer_difficulty_summary(
    plan: Mapping[str, Any], reviewer: Mapping[str, Any] | None
) -> tuple[int, int]:
    """Return observed/planned agreement and low-confidence counts."""

    reviewer_by_id = {
        item.get("item_id"): item
        for item in (reviewer or {}).get("items", [])
        if isinstance(item, dict)
    }
    agreement_count = 0
    low_confidence_count = 0
    for planned_item in _expected_items(plan):
        reviewer_item = reviewer_by_id.get(planned_item.get("item_id"))
        if not isinstance(reviewer_item, dict):
            continue
        if reviewer_item.get("observed_difficulty") == planned_item.get("difficulty"):
            agreement_count += 1
        if reviewer_item.get("difficulty_confidence") == "LOW":
            low_confidence_count += 1
    return agreement_count, low_confidence_count


SOLVER_ANSWER_SENTINELS = frozenset({"AMBIGUOUS", "NONE"})


def _solver_answer_text_errors(
    output_item: Mapping[str, Any], blind_item: Mapping[str, Any], item_label: str
) -> list[str]:
    """Validate raw Solver answer_text against the visible options by exact identity."""

    options = blind_item.get("options")
    if not isinstance(options, dict) or set(options) != set(LETTERS):
        return [f"solver[{item_label}]: blind options must contain exactly A/B/C/D"]
    expected_texts = [options[letter] for letter in LETTERS]
    if not all(isinstance(text, str) for text in expected_texts):
        return [f"solver[{item_label}]: blind option texts must be strings"]
    if len(set(expected_texts)) != len(expected_texts):
        return [f"solver[{item_label}]: blind option texts are not one-to-one"]

    answer_text = output_item.get("answer_text")
    if not isinstance(answer_text, str) or (
        answer_text not in expected_texts and answer_text not in SOLVER_ANSWER_SENTINELS
    ):
        return [f"solver[{item_label}]: answer_text is not an exact visible option or allowed sentinel"]
    return []


def validate_solver_contract(output: Any, blind: Mapping[str, Any], plan: Mapping[str, Any] | None = None) -> list[str]:
    errors = _schema(output, "solver")
    if not isinstance(output, dict):
        return errors
    items = output.get("items")
    if not isinstance(items, list):
        return errors
    expected = [item.get("item_id") for item in blind.get("items", []) if isinstance(item, dict)]
    actual, duplicates = _ids(items)
    if duplicates:
        errors.append(f"solver: duplicate item_id(s): {duplicates}")
    if actual != expected:
        errors.append("solver: item IDs/order do not match blind input")
    blind_items = blind.get("items", []) if isinstance(blind, dict) else []
    if isinstance(blind_items, list):
        for output_item, blind_item in zip(items, blind_items):
            if isinstance(output_item, dict) and isinstance(blind_item, dict):
                item_label = str(output_item.get("item_id", "unknown"))
                errors.extend(_solver_answer_text_errors(output_item, blind_item, item_label))
    errors.extend(f"solver: forbidden field {path}" for path in find_leakage(output))
    return _deduplicate(errors)


def canonicalize_solver_output(output: Any, blind: Mapping[str, Any]) -> dict[str, Any]:
    """Map a validated raw text-based Solver response to the legacy internal shape."""

    errors = validate_solver_contract(output, blind)
    if errors:
        raise ValueError("solver raw output cannot be canonicalized: " + "; ".join(errors))
    if not isinstance(output, dict):  # pragma: no cover - guarded by validate_solver_contract
        raise ValueError("solver raw output must be an object")
    blind_items = blind.get("items")
    output_items = output.get("items")
    if not isinstance(blind_items, list) or not isinstance(output_items, list):  # pragma: no cover
        raise ValueError("solver raw output and blind input must contain items arrays")

    canonical_items: list[dict[str, Any]] = []
    for output_item, blind_item in zip(output_items, blind_items):
        if not isinstance(output_item, dict) or not isinstance(blind_item, dict):  # pragma: no cover
            raise ValueError("solver raw output and blind input items must be objects")
        options = blind_item["options"]
        answer_text = output_item["answer_text"]
        option_to_letter = {options[letter]: letter for letter in LETTERS}
        answer = option_to_letter.get(answer_text, answer_text)
        canonical_items.append({
            "item_id": output_item["item_id"],
            "answer": answer,
            "confidence": output_item["confidence"],
            "reason": output_item["reason"],
        })
    return {"items": canonical_items}


validate_generator = validate_generator_contract
validate_reviewer = validate_reviewer_contract
validate_solver = validate_solver_contract


FORBIDDEN_PRIVATE_FIELDS = frozenset({
    "correct_answer",
    "primary_target",
    "subtype",
    "secondary_features",
    "difficulty",
    "vocabulary_domain",
    "answer_explanation",
    "distractor_rationales",
    "permutation",
    "permutation_version",
    "original_to_canonical",
    "canonical_to_original",
    "plan",
    "planner",
    "generator",
    "reviewer",
    "solver",
})


def find_leakage(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_PRIVATE_FIELDS:
                found.append(child_path)
            found.extend(find_leakage(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_leakage(child, f"{path}[{index}]"))
    return found


def post_blind_comparison(
    generator: Mapping[str, Any], reviewer: Mapping[str, Any], solver: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    reviewer_by_id = {
        item["item_id"]: item for item in reviewer.get("items", []) if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }
    solver_by_id = {
        item["item_id"]: item for item in solver.get("items", []) if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }
    agreements: list[dict[str, Any]] = []
    count = 0
    for item in generator.get("items", []):
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id")
        reviewer_answer = reviewer_by_id.get(item_id, {}).get("best_answer")
        solver_answer = solver_by_id.get(item_id, {}).get("answer")
        agree = reviewer_answer == solver_answer
        count += int(agree)
        agreements.append({
            "item_id": item_id,
            "reviewer": reviewer_answer,
            "solver": solver_answer,
            "agree": agree,
        })
    return agreements, count


def clean_copy(value: Any) -> Any:
    """Return a defensive copy for stage artifacts."""

    return copy.deepcopy(value)
