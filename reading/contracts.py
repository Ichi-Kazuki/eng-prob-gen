"""Canonical contracts and fail-closed checks for Reading v0.1/v0.2.

The Reading contract family is intentionally independent of the existing WE
schemas and validators.  This module owns only shape/integrity checks; it
never repairs a model response or changes an agent judgment.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from shared.schema_validation import load_schema, schema_errors

from .planner import QUESTION_TYPES


SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_PATHS = {
    "plan": SCHEMA_DIR / "reading_plan.schema.json",
    "generator": SCHEMA_DIR / "reading_generator_output.schema.json",
    "reviewer_input": SCHEMA_DIR / "reading_reviewer_input.schema.json",
    "reviewer": SCHEMA_DIR / "reading_reviewer_output.schema.json",
    "solver_input": SCHEMA_DIR / "reading_solver_input.schema.json",
    "solver": SCHEMA_DIR / "reading_solver_output.schema.json",
    "result": SCHEMA_DIR / "reading_result.schema.json",
}
SCHEMA_PATHS_V02 = {
    "plan": SCHEMA_DIR / "reading_plan_v0_2.schema.json",
    "generator": SCHEMA_DIR / "reading_generator_output_v0_2.schema.json",
    "reviewer_input": SCHEMA_DIR / "reading_reviewer_input_v0_2.schema.json",
    "reviewer": SCHEMA_DIR / "reading_reviewer_output_v0_2.schema.json",
    "solver_input": SCHEMA_DIR / "reading_solver_input_v0_2.schema.json",
    "solver": SCHEMA_DIR / "reading_solver_output_v0_2.schema.json",
    "result": SCHEMA_DIR / "reading_result_v0_2.schema.json",
    "draft_result": SCHEMA_DIR / "reading_draft_result_v0_2.schema.json",
    "batch_result": SCHEMA_DIR / "reading_batch_result_v0_2.schema.json",
}
ANSWER_LABELS = {"A", "B", "C", "D"}
SOLVER_LABELS = ANSWER_LABELS | {"AMBIGUOUS", "NONE"}
HARD_VALIDITY = "HARD_VALIDITY"
EMPIRICAL_FORMAT_WARNING = "EMPIRICAL_FORMAT_WARNING"
FORMAT_ADHERENCE_FAILURE = "FORMAT_ADHERENCE_FAILURE"
VALID = "VALID"
BLIND_FORBIDDEN_KEYS = {
    "correct_answer",
    "intended_answer",
    "generator_answer",
    "answer_key",
    "answer_match",
    "rationale",
    "explanation",
    "evidence",
    "generation_plan",
    "plan",
    "plan_id",
    "target_words",
    "target_paragraphs",
    "question_plan",
    "question_type",
    "generator_metadata",
    "target_metadata",
    "provenance",
}


def _schema_errors(
    value: Any,
    key: str,
    schema_paths: dict[str, Path] = SCHEMA_PATHS,
) -> list[str]:
    return [f"{key}: {error}" for error in schema_errors(value, load_schema(schema_paths[key]))]


def validate_plan_contract(
    plan: Any,
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if isinstance(plan, dict) and plan.get("schema_version") == "reading-plan-v0.2" else SCHEMA_PATHS
    errors = _schema_errors(plan, "plan", schema_paths)
    if not errors and isinstance(plan, dict) and plan.get("schema_version") == "reading-plan-v0.2":
        if plan.get("question_count") != len(plan.get("question_plan", [])):
            errors.append("plan: question_count must equal the length of question_plan")
        planned_types = plan.get("question_plan", [])
        planned_counts = Counter(planned_types)
        if plan.get("question_type_counts") != {
            question_type: planned_counts[question_type]
            for question_type in QUESTION_TYPES
        }:
            errors.append("plan: question_type_counts must equal the question_plan multiset")
        if sum(plan.get("question_type_counts", {}).values()) != plan.get("question_count"):
            errors.append("plan: question_type_counts must sum to question_count")
    return errors


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w]+(?:['-][\w]+)*\b", text, flags=re.UNICODE))


def split_paragraphs(passage: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", passage.strip()) if paragraph.strip()]


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _contains_anchor(paragraph: str, anchor: str) -> bool:
    return _normalized_text(anchor) in _normalized_text(paragraph)


def _duplicate_text(values: list[str]) -> bool:
    normalized = [_normalized_text(value).strip(" .,:;!?\"'()[]") for value in values]
    return len(set(normalized)) != len(normalized)


def _nested_keys(value: Any, forbidden: set[str], path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in forbidden:
                found.append(f"{path}.{key}")
            found.extend(_nested_keys(nested, forbidden, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_nested_keys(nested, forbidden, f"{path}[{index}]"))
    return found


def validate_generator_contract(
    output: Any,
    plan: dict[str, Any] | None = None,
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if (
            (isinstance(plan, dict) and plan.get("schema_version") == "reading-plan-v0.2")
            or (isinstance(output, dict) and output.get("schema_version") == "reading-generator-v0.2")
        ) else SCHEMA_PATHS
    errors = _schema_errors(output, "generator", schema_paths)
    if errors or not isinstance(output, dict):
        return errors
    questions = output["questions"]
    passage_id = output["passage_id"]
    seen_ids: set[str] = set()
    seen_types: list[str] = []
    for index, question in enumerate(questions, 1):
        item_id = question["item_id"]
        if item_id in seen_ids:
            errors.append(f"generator: duplicate question id {item_id!r}")
        seen_ids.add(item_id)
        if item_id != f"{passage_id}-q{index}":
            errors.append(f"generator: question {index} has unexpected item_id {item_id!r}")
        seen_types.append(question["question_type"])
        choices = question["choices"]
        if _duplicate_text(list(choices.values())):
            errors.append(f"generator: question {item_id} has duplicate answer choices")
        evidence = question["evidence"]
        paragraphs = split_paragraphs(output["passage"])
        paragraph_number = evidence["paragraph"]
        if paragraph_number > len(paragraphs):
            errors.append(f"generator: {item_id} evidence paragraph {paragraph_number} is out of range")
        elif not _contains_anchor(paragraphs[paragraph_number - 1], evidence["anchor"]):
            errors.append(f"generator: {item_id} evidence anchor is not present in its paragraph")
    is_v02 = plan is not None and plan.get("schema_version") == "reading-plan-v0.2"
    if not is_v02 and sorted(seen_types) != sorted(QUESTION_TYPES):
        errors.append(f"generator: question types must contain exactly {list(QUESTION_TYPES)}")
    if plan is not None:
        if validate_plan_contract(plan, schema_paths):
            errors.append("generator: supplied plan is not a valid Reading plan")
        else:
            expected_id = f"rc-{plan['seed']:08x}"
            if passage_id != expected_id:
                errors.append(f"generator: passage_id must equal planned id {expected_id!r}")
            if is_v02 and len(questions) != plan["question_count"]:
                errors.append(
                    f"generator: expected {plan['question_count']} questions; got {len(questions)}"
                )
            if is_v02 and Counter(seen_types) != Counter(plan["question_type_counts"]):
                errors.append(
                    "generator: question type counts do not match the planned multiset; "
                    f"expected {dict(sorted(plan['question_type_counts'].items()))}, "
                    f"got {dict(sorted(Counter(seen_types).items()))}"
                )
            elif not is_v02 and seen_types != list(plan["question_plan"]):
                errors.append("generator: question order does not follow the deterministic plan")
    return errors


def passage_word_count_profile(count: int, *, is_v02: bool) -> dict[str, Any]:
    """Classify passage length without treating the preferred band as a cap."""

    if not is_v02:
        return {
            "classification": VALID,
            "band": "HISTORICAL_V01",
            "hard_failure": False,
            "empirical_warning": False,
        }
    if count < 160:
        return {
            "classification": HARD_VALIDITY,
            "band": "BELOW_EMPIRICAL_MINIMUM",
            "hard_failure": True,
            "empirical_warning": False,
        }
    if count > 300:
        return {
            "classification": EMPIRICAL_FORMAT_WARNING,
            "band": "ABOVE_EMPIRICAL_PREFERRED_BAND",
            "hard_failure": False,
            "empirical_warning": True,
        }
    return {
        "classification": VALID,
        "band": "EMPIRICAL_PREFERRED_BAND",
        "hard_failure": False,
        "empirical_warning": False,
    }


def deterministic_diagnostics(
    output: Any,
    plan: dict[str, Any],
    schema_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Return hard deterministic failures and non-blocking empirical warnings."""

    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if plan.get("schema_version") == "reading-plan-v0.2" else SCHEMA_PATHS
    errors = validate_generator_contract(output, plan, schema_paths)
    warnings: list[str] = []
    is_v02 = plan.get("schema_version") == "reading-plan-v0.2"
    count: int | None = None
    paragraph_count: int | None = None
    profile: dict[str, Any] | None = None
    if isinstance(output, dict) and isinstance(output.get("passage"), str):
        passage = output["passage"]
        paragraphs = split_paragraphs(passage)
        count = word_count(passage)
        paragraph_count = len(paragraphs)
        profile = passage_word_count_profile(count, is_v02=is_v02)
        if profile["hard_failure"]:
            if is_v02:
                errors.append(f"deterministic: passage word count {count} is below 160")
        elif profile["empirical_warning"]:
            if is_v02:
                warnings.append(
                    f"deterministic: passage word count {count} is above the empirical preferred band of 160-300"
                )
        elif not is_v02 and (count < 240 or count > 380):
            errors.append(f"deterministic: passage word count {count} is outside 240-380")

        if not errors:
            if not is_v02 and len(paragraphs) != plan["target_paragraphs"]:
                errors.append(
                    f"deterministic: passage must contain exactly {plan['target_paragraphs']} non-empty paragraphs; got {len(paragraphs)}"
                )
            if "\r" in passage or "\t" in passage or "\n\n\n" in passage:
                errors.append("deterministic: passage contains malformed whitespace formatting")
            if re.search(r"(^|\n)\s*(?:[-*]|\d+[.)])\s+", passage):
                errors.append("deterministic: passage contains list-like formatting")
            if re.search(r"lorem ipsum|\[insert|\{placeholder|question\s+[1-5]", passage, flags=re.IGNORECASE):
                errors.append("deterministic: passage contains placeholder or question formatting")
            if any(word_count(paragraph) < 35 for paragraph in paragraphs):
                errors.append("deterministic: every paragraph must contain at least 35 words")
            if len({_normalized_text(paragraph) for paragraph in paragraphs}) != len(paragraphs):
                errors.append("deterministic: passage contains duplicate paragraphs")

    adherence_errors = [
        error for error in errors
        if "question type counts" in error
        or "expected" in error and "questions; got" in error
        or "supplied plan" in error
    ]
    if errors and len(adherence_errors) == len(errors):
        classification = FORMAT_ADHERENCE_FAILURE
    else:
        classification = HARD_VALIDITY if errors else (EMPIRICAL_FORMAT_WARNING if warnings else VALID)
    return {
        "classification": classification,
        "hard_failures": errors,
        "adherence_failures": adherence_errors,
        "empirical_warnings": warnings,
        "passage_word_count": count,
        "paragraph_count": paragraph_count,
        "word_count_profile": profile,
    }


def validate_deterministic(
    output: Any,
    plan: dict[str, Any],
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    """Run inexpensive content/structure gates before any blind calls."""

    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if plan.get("schema_version") == "reading-plan-v0.2" else SCHEMA_PATHS
    return deterministic_diagnostics(output, plan, schema_paths)["hard_failures"]


def blind_input(
    output: dict[str, Any],
    *,
    schema_version: str = "reading-blind-input-v0.1",
) -> dict[str, Any]:
    """Project only test-taker-visible fields, for both blind agents."""

    payload = {
        "schema_version": schema_version,
        "passage_id": output["passage_id"],
        "section": output["section"],
        "title": output["title"],
        "passage": output["passage"],
        "questions": [
            {
                "item_id": question["item_id"],
                "number": index,
                "stem": question["stem"],
                "choices": copy.deepcopy(question["choices"]),
            }
            for index, question in enumerate(output["questions"], 1)
        ],
    }
    leakage = _nested_keys(payload, BLIND_FORBIDDEN_KEYS)
    if leakage:
        raise ValueError("blind projection contains forbidden field(s): " + ", ".join(leakage))
    return payload


def _blind_input_errors(
    output: Any,
    payload: Any,
    schema_key: str,
    schema_paths: dict[str, Path] | None = None,
    schema_version: str = "reading-blind-input-v0.1",
) -> list[str]:
    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if isinstance(output, dict) and output.get("schema_version") == "reading-generator-v0.2" else SCHEMA_PATHS
    errors: list[str] = []
    if not isinstance(output, dict):
        return ["blind input source must be an object"]
    try:
        expected = blind_input(output, schema_version=schema_version)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"blind input could not be derived: {exc}"]
    if payload != expected:
        errors.append("blind input does not match the canonical allowlisted projection")
    errors.extend(f"blind input: forbidden field {path}" for path in _nested_keys(payload, BLIND_FORBIDDEN_KEYS))
    errors.extend(_schema_errors(payload, schema_key, schema_paths))
    return errors


def blind_input_errors(
    output: Any,
    payload: Any,
    schema_paths: dict[str, Path] | None = None,
    schema_version: str = "reading-blind-input-v0.1",
) -> list[str]:
    return _blind_input_errors(output, payload, "reviewer_input", schema_paths, schema_version)


def solver_input_errors(
    output: Any,
    payload: Any,
    schema_paths: dict[str, Path] | None = None,
    schema_version: str = "reading-blind-input-v0.1",
) -> list[str]:
    return _blind_input_errors(output, payload, "solver_input", schema_paths, schema_version)


def payload_sha256(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def _ids(values: list[dict[str, Any]], field: str) -> tuple[list[str], list[str]]:
    ids = [value.get(field) for value in values]
    valid = [value for value in ids if isinstance(value, str)]
    duplicates = sorted({value for value in valid if valid.count(value) > 1})
    return valid, duplicates


def validate_reviewer_contract(
    output: Any,
    blind: dict[str, Any],
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if (
            isinstance(output, dict) and output.get("schema_version") == "reading-reviewer-v0.2"
        ) or blind.get("schema_version") == "reading-blind-input-v0.2" else SCHEMA_PATHS
    errors = _schema_errors(output, "reviewer", schema_paths)
    if errors or not isinstance(output, dict):
        return errors
    if output["passage_id"] != blind["passage_id"] or output["section"] != blind["section"]:
        errors.append("reviewer: passage identity does not match blind input")
    expected_ids = [question["item_id"] for question in blind["questions"]]
    actual_ids, duplicates = _ids(output["questions"], "item_id")
    if duplicates:
        errors.append(f"reviewer: duplicate item_id(s) {duplicates}")
    if actual_ids != expected_ids:
        errors.append("reviewer: question ids/order do not match blind input")
    for question in output["questions"]:
        if question["best_answer"] in {"AMBIGUOUS", "NONE"} and question["unique_answer"]:
            errors.append(f"reviewer: {question['item_id']} cannot mark AMBIGUOUS/NONE as unique")
        if question["best_answer"] == "NONE" and question["answerable"]:
            errors.append(f"reviewer: {question['item_id']} cannot mark NONE as answerable")
    errors.extend(f"reviewer: forbidden field {path}" for path in _nested_keys(output, BLIND_FORBIDDEN_KEYS))
    return errors


def validate_solver_contract(
    output: Any,
    blind: dict[str, Any],
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if (
            isinstance(output, dict) and output.get("schema_version") == "reading-solver-v0.2"
        ) or blind.get("schema_version") == "reading-blind-input-v0.2" else SCHEMA_PATHS
    errors = _schema_errors(output, "solver", schema_paths)
    if errors or not isinstance(output, dict):
        return errors
    if output["passage_id"] != blind["passage_id"] or output["section"] != blind["section"]:
        errors.append("solver: passage identity does not match blind input")
    expected_ids = [question["item_id"] for question in blind["questions"]]
    actual_ids, duplicates = _ids(output["answers"], "item_id")
    if duplicates:
        errors.append(f"solver: duplicate item_id(s) {duplicates}")
    if actual_ids != expected_ids:
        errors.append("solver: answer ids/order do not match blind input")
    errors.extend(f"solver: forbidden field {path}" for path in _nested_keys(output, BLIND_FORBIDDEN_KEYS))
    return errors


def post_blind_comparison(
    generator: dict[str, Any], reviewer: dict[str, Any], solver: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compare sealed judgments without altering any of them."""

    reviewer_by_id = {item["item_id"]: item["best_answer"] for item in reviewer["questions"]}
    solver_by_id = {item["item_id"]: item["answer"] for item in solver["answers"]}
    agreements: list[dict[str, Any]] = []
    errors: list[str] = []
    for question in generator["questions"]:
        item_id = question["item_id"]
        answers = {
            "generator": question["correct_answer"],
            "reviewer": reviewer_by_id.get(item_id),
            "solver": solver_by_id.get(item_id),
        }
        agree = len(set(answers.values())) == 1
        agreements.append({"item_id": item_id, **answers, "agree": agree})
        if not agree:
            errors.append(f"answer disagreement for {item_id}: {answers}")
    return agreements, errors


def validate_result_contract(
    result: Any,
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02 if isinstance(result, dict) and result.get("schema_version") == "reading-result-v0.2" else SCHEMA_PATHS
    errors = _schema_errors(result, "result", schema_paths)
    if errors or not isinstance(result, dict):
        return errors
    if result["decision"] == "ACCEPT":
        checks = result["checks"]
        required_true = {
            "generator_canonical",
            "deterministic",
            "reviewer_contract",
            "reviewer_set_pass",
            "reviewer_no_ambiguous_none",
            "solver_contract",
            "solver_no_ambiguous_none",
            "all_answers_agree",
            "no_leakage",
            "no_synthetic_fallback",
        }
        missing_or_false = sorted(key for key in required_true if checks.get(key) is not True)
        if missing_or_false:
            errors.append(f"result: ACCEPT requires true gates {missing_or_false}")
        if result["infrastructure"].get("runtime_failures"):
            errors.append("result: ACCEPT forbids runtime failures")
    return errors


def validate_draft_result_contract(result: Any) -> list[str]:
    """Validate the explicit non-production marker used by draft mode."""

    return _schema_errors(result, "draft_result", SCHEMA_PATHS_V02)


def validate_batch_result_contract(result: Any) -> list[str]:
    """Validate the persisted v0.2 batch summary shape."""

    return _schema_errors(result, "batch_result", SCHEMA_PATHS_V02)
