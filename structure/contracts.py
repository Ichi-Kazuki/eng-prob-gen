"""Fail-closed Structure v0.1 contract and deterministic validation rules."""

from __future__ import annotations

import copy
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.schema_validation import load_schema, schema_errors

from .planner import PLAN_SCHEMA_PATH, load_profile


ROOT = Path(__file__).resolve().parent
BLANK_MARKER = "____"
LETTERS = ("A", "B", "C", "D")
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
        if not isinstance(stem, str) or stem.count(BLANK_MARKER) != 1:
            errors.append(f"{prefix}: stem must contain exactly one {BLANK_MARKER!r} blank marker")
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
    errors.extend(f"reviewer: forbidden field {path}" for path in find_leakage(output))
    return _deduplicate(errors)


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
    errors.extend(f"solver: forbidden field {path}" for path in find_leakage(output))
    return _deduplicate(errors)


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
