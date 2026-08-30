"""Canonical contracts and fail-closed checks for Reading v0.1/v0.2.

The Reading contract family is intentionally independent of the existing WE
schemas and validators.  This module owns only shape/integrity checks; it
never repairs a model response or changes an agent judgment.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import string
import textwrap
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from shared.schema_validation import load_schema, schema_errors

from .planner import (
    QUESTION_SUBTYPES,
    QUESTION_SUBTYPE_COMPATIBILITY,
    QUESTION_TYPES,
    passage_id_for_seed,
)


SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
GENERATOR_MODEL_SCHEMA_V02_2_PATH = SCHEMA_DIR / "reading_generator_model_v0_2_2.schema.json"
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
    "inference_verifier_input": SCHEMA_DIR / "reading_inference_verifier_input_v0_2.schema.json",
    "inference_verifier": SCHEMA_DIR / "reading_inference_verifier_output_v0_2.schema.json",
    "candidate_verifier_input": SCHEMA_DIR / "reading_inference_candidate_verifier_input_v0_2.schema.json",
    "candidate_verifier": SCHEMA_DIR / "reading_inference_candidate_verifier_output_v0_2.schema.json",
    "inference_repair_input": SCHEMA_DIR / "reading_inference_repair_input_v0_2.schema.json",
    "inference_repair": SCHEMA_DIR / "reading_inference_repair_output_v0_2.schema.json",
    "result": SCHEMA_DIR / "reading_result_v0_2.schema.json",
    "draft_result": SCHEMA_DIR / "reading_draft_result_v0_2.schema.json",
    "batch_result": SCHEMA_DIR / "reading_batch_result_v0_2.schema.json",
}
ANSWER_LABELS = {"A", "B", "C", "D"}
ANSWER_LABEL_ORDER = ("A", "B", "C", "D")
SOLVER_LABELS = ANSWER_LABELS | {"AMBIGUOUS", "NONE"}
GENERATOR_QUESTION_GROUP_FIELDS = {
    "DETAIL": "detail_questions",
    "VOCABULARY_IN_CONTEXT": "vocabulary_in_context_questions",
    "INFERENCE": "inference_questions",
    "MAIN_IDEA": "main_idea_questions",
    "REFERENCE": "reference_questions",
}
INFERENCE_SUBTYPES = frozenset({"LOCAL_INFERENCE", "CROSS_IDEA_INFERENCE", "RHETORICAL_PURPOSE"})
INFERENCE_VERIFIER_VALID_STATUSES = frozenset({
    "VALID_SHALLOW_INFERENCE",
    "VALID_GENUINE_INFERENCE",
    "VALID_CROSS_IDEA_INFERENCE",
})
_OPTIONAL_TARGET_FIELDS = ("target_text", "target_line")
CANONICAL_QUESTION_ORDER_VERSION = "reading-v0.2.5-evidence-position-aware-v1"
CHOICE_PERMUTATION_VERSION = "reading-v0.2.5-seeded-choice-permutation-v1"
DISPLAY_LINE_WIDTH = 72
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
    "target_text",
    "target_line",
    "subtype",
    "distractor_metadata",
    "distractor_taxonomy",
    "distractor_category",
    "why_wrong",
    "provenance",
}
DISTRACTOR_CATEGORIES = (
    "TEXT_TRUE_BUT_NOT_ANSWER",
    "WRONG_REFERENT",
    "SCOPE_SHIFT",
    "CAUSE_EFFECT_REVERSAL",
    "OVERGENERALIZATION",
    "UNDERGENERALIZATION",
    "LEXICAL_SENSE_TRAP",
    "UNSUPPORTED_INFERENCE",
    "NEARBY_DETAIL_CONFUSION",
    "CONTRADICTED_BY_PASSAGE",
)
DISTRACTOR_METADATA_CORRECT = "CORRECT_OPTION"


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
    if not errors and isinstance(plan, dict) and "passage_id" in plan:
        try:
            expected_id = passage_id_for_seed(plan["seed"])
        except (TypeError, ValueError):
            expected_id = None
        if expected_id is None or plan.get("passage_id") != expected_id:
            errors.append("plan: passage_id must equal the deterministic Planner id")
    if not errors and isinstance(plan, dict) and plan.get("schema_version") == "reading-plan-v0.2":
        if plan.get("question_count") != len(plan.get("question_plan", [])):
            errors.append("plan: question_count must equal the length of question_plan")
        planned_types = plan.get("question_plan", [])
        planned_counts: Counter[Any] = Counter(planned_types)
        if plan.get("question_type_counts") != {
            question_type: planned_counts[question_type]
            for question_type in QUESTION_TYPES
        }:
            errors.append("plan: question_type_counts must equal the question_plan multiset")
        if sum(plan.get("question_type_counts", {}).values()) != plan.get("question_count"):
            errors.append("plan: question_type_counts must sum to question_count")
    return errors


def generator_model_schema_for_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Build the v0.2.2 model-facing schema with exact type quotas.

    This schema is a transport contract only.  The canonical Generator
    schema remains the flat ``questions`` contract and is still validated
    after the grouped response is flattened.
    """

    if not isinstance(plan, dict) or plan.get("schema_version") != "reading-plan-v0.2":
        raise ValueError("a Reading v0.2 plan is required for the v0.2.2 Generator schema")
    plan_errors = validate_plan_contract(plan, SCHEMA_PATHS_V02)
    if plan_errors:
        raise ValueError("cannot build Generator model schema from an invalid plan: " + "; ".join(plan_errors))
    schema = load_schema(GENERATOR_MODEL_SCHEMA_V02_2_PATH)
    properties = schema.get("properties")
    counts = plan["question_type_counts"]
    if not isinstance(properties, dict) or not isinstance(counts, dict):
        raise ValueError("Generator model schema template or plan quotas are malformed")
    for question_type, field_name in GENERATOR_QUESTION_GROUP_FIELDS.items():
        group_schema = properties.get(field_name)
        if not isinstance(group_schema, dict):
            raise ValueError(f"Generator model schema is missing {field_name}")
        quota = counts.get(question_type)
        if not isinstance(quota, int) or isinstance(quota, bool) or quota < 0:
            raise ValueError(f"invalid quota for {question_type}: {quota!r}")
        group_schema["minItems"] = quota
        group_schema["maxItems"] = quota
    return schema


def _normalized_display_paragraphs(passage: str) -> list[str]:
    """Normalize passage paragraphs for the platform-independent display model."""

    normalized = unicodedata.normalize("NFC", passage).replace("\r\n", "\n").replace("\r", "\n")
    return [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", normalized.strip())
        if re.sub(r"\s+", " ", paragraph).strip()
    ]


def display_lines(passage: str, *, width: int = DISPLAY_LINE_WIDTH) -> list[str]:
    """Return deterministic 1-based-display-compatible lines for a passage.

    The line model is intentionally independent of terminal or browser width.
    Paragraph boundaries are preserved as wrapping boundaries, but blank lines
    are not counted as display lines because the test-taker sees paragraph text,
    not source-format separators.
    """

    if not isinstance(passage, str):
        raise TypeError("passage must be a string")
    if isinstance(width, bool) or not isinstance(width, int) or width < 20:
        raise ValueError("display line width must be an integer of at least 20")
    lines: list[str] = []
    for paragraph in _normalized_display_paragraphs(passage):
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
                replace_whitespace=True,
                drop_whitespace=True,
            )
        )
    return lines


def target_line_for_text(passage: str, target_text: str, *, width: int = DISPLAY_LINE_WIDTH) -> int | None:
    """Return the first 1-based display line containing an exact target expression."""

    lines = display_lines(passage, width=width)
    matching_lines = _surface_match_line_numbers(lines, target_text)
    return matching_lines[0] if matching_lines else None


def _display_position_for_question(question: dict[str, Any], passage: str) -> tuple[int, int, int]:
    """Return a stable global display position for evidence-aware ordering."""

    evidence = question.get("evidence")
    paragraphs = _normalized_display_paragraphs(passage) if isinstance(passage, str) else []
    paragraph_number = evidence.get("paragraph") if isinstance(evidence, dict) else None
    anchor = evidence.get("anchor") if isinstance(evidence, dict) else None
    if isinstance(paragraph_number, int) and 1 <= paragraph_number <= len(paragraphs):
        preceding_lines = sum(len(display_lines(paragraph)) for paragraph in paragraphs[:paragraph_number - 1])
        paragraph_lines = display_lines(paragraphs[paragraph_number - 1])
        local_line = 0
        anchor_offset = len(paragraphs[paragraph_number - 1])
        if isinstance(anchor, str):
            normalized_paragraph = _normalized_text(paragraphs[paragraph_number - 1])
            normalized_anchor = _normalized_text(anchor)
            offset = normalized_paragraph.find(normalized_anchor)
            if offset >= 0:
                anchor_offset = offset
            for index, line in enumerate(paragraph_lines):
                if _contains_surface_expression(line, anchor):
                    local_line = index
                    break
        return preceding_lines + local_line + 1, paragraph_number, anchor_offset
    return (10**9, 10**9, 10**9)


def _question_order_key(
    question: dict[str, Any],
    passage: str,
    original_index: int,
) -> tuple[int, int, int, int, str, int]:
    question_type = question.get("question_type")
    subtype = question.get("subtype")
    # Main-idea items are passage-global and conventionally appear before
    # location-specific items. Cross-idea inference is synthesis and is placed
    # after local evidence when the taxonomy identifies it as such.
    global_rank = 0 if question_type == "MAIN_IDEA" else (
        2 if question_type == "INFERENCE" and subtype == "CROSS_IDEA_INFERENCE" else 1
    )
    target_line = question.get("target_line")
    if isinstance(target_line, int) and target_line >= 1:
        line_number, paragraph_number, anchor_offset = target_line, target_line, 0
    else:
        line_number, paragraph_number, anchor_offset = _display_position_for_question(question, passage)
    stem_value = question.get("stem")
    stem = stem_value if isinstance(stem_value, str) else ""
    return (global_rank, line_number, paragraph_number, anchor_offset, stem.casefold(), original_index)


def _evidence_position_aware_order(
    questions: list[dict[str, Any]],
    passage: str,
) -> list[dict[str, Any]]:
    """Order questions by globality and deterministic passage evidence position."""

    return [
        question
        for _index, question in sorted(
            enumerate(questions),
            key=lambda pair: _question_order_key(pair[1], passage, pair[0]),
        )
    ]


def _omit_transport_null_target_fields(question: dict[str, Any]) -> None:
    """Restore omission semantics for transport-encoded optional targets.

    Codex Structured Outputs requires every declared property in its transport
    schema, so an optional canonical target property can arrive as ``None``.
    Reading's canonical contract is non-nullable and historically represented
    an inapplicable target by omission. Only remove those two transport nulls;
    existing values and every other question field remain untouched.
    """

    for field_name in _OPTIONAL_TARGET_FIELDS:
        if field_name in question and question[field_name] is None:
            del question[field_name]


def _flatten_grouped_generator_questions(
    raw_output: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    expected_fields = set(GENERATOR_QUESTION_GROUP_FIELDS.values())
    present_fields = {field for field in expected_fields if field in raw_output}
    if present_fields != expected_fields:
        missing = sorted(expected_fields - present_fields)
        extra = sorted(present_fields - expected_fields)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise ValueError("grouped Generator response must contain all type collections (" + "; ".join(detail) + ")")
    for question_type, field_name in GENERATOR_QUESTION_GROUP_FIELDS.items():
        questions = raw_output[field_name]
        expected_count = plan["question_type_counts"][question_type]
        if not isinstance(questions, list):
            raise ValueError(f"{field_name} must be an array")
        if len(questions) != expected_count:
            raise ValueError(
                f"{field_name} quota mismatch: expected {expected_count}; got {len(questions)}"
            )
        normalized: list[dict[str, Any]] = []
        for index, question in enumerate(questions, 1):
            if not isinstance(question, dict):
                raise ValueError(f"{field_name}[{index}] must be an object")
            copied = copy.deepcopy(question)
            declared_type = copied.get("question_type")
            if declared_type is None:
                copied["question_type"] = question_type
            elif declared_type != question_type:
                raise ValueError(
                    f"{field_name}[{index}].question_type must be {question_type!r}; got {declared_type!r}"
                )
            normalized.append(copied)
        grouped[question_type] = normalized
    return _evidence_position_aware_order(
        [question for question_type in QUESTION_TYPES for question in grouped[question_type]],
        raw_output.get("passage", ""),
    )


def canonicalize_generator_output(
    raw_output: Any,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Bind Planner-owned identity fields without changing semantic content.

    The raw model response is copied before the envelope is applied.  A
    legacy response may contain ``passage_id`` or question ``item_id`` fields;
    neither is authoritative.  Those deterministic identity fields are
    replaced from the validated Planner state, while passage text, question
    text, choices, answers, types, and evidence are left untouched.
    """

    if not isinstance(raw_output, dict):
        raise ValueError("Generator response must be an object")
    plan_errors = validate_plan_contract(plan)
    if plan_errors:
        raise ValueError("cannot build canonical Generator envelope: " + "; ".join(plan_errors))

    canonical = copy.deepcopy(raw_output)
    is_v02 = plan.get("schema_version") == "reading-plan-v0.2"
    if is_v02 and any(field in raw_output for field in GENERATOR_QUESTION_GROUP_FIELDS.values()):
        if "questions" in raw_output:
            raise ValueError("grouped Generator response must not also contain flat questions")
        canonical["questions"] = _flatten_grouped_generator_questions(raw_output, plan)
        for field_name in GENERATOR_QUESTION_GROUP_FIELDS.values():
            canonical.pop(field_name, None)
    passage_id = plan.get("passage_id") or passage_id_for_seed(plan["seed"])
    canonical["passage_id"] = passage_id
    questions = canonical.get("questions")
    if isinstance(questions, list):
        if is_v02:
            questions = _evidence_position_aware_order(questions, canonical.get("passage", ""))
            canonical["questions"] = questions
        for index, question in enumerate(questions, 1):
            if isinstance(question, dict):
                _omit_transport_null_target_fields(question)
                question["item_id"] = f"{passage_id}-q{index}"
    return canonical


_INTERNAL_ANSWER_LABEL_KEYS = {
    "answer_label",
    "correct_answer",
    "correct_answer_label",
    "intended_answer",
    "intended_answer_label",
    "answer_key",
    "generator_answer",
    "generator_answer_label",
}


def _remap_internal_answer_labels(value: Any, original_to_canonical: dict[str, str]) -> None:
    """Remap explicit nested label metadata without rewriting prose.

    The current Reading evidence schema contains a natural-language rationale
    only, so this is normally a no-op.  Keeping the traversal here makes the
    permutation safe for any explicitly keyed label metadata that may be
    carried by a compatible internal evidence representation; ordinary
    rationale text is intentionally never parsed or rewritten.
    """

    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _INTERNAL_ANSWER_LABEL_KEYS and isinstance(nested, str):
                value[key] = original_to_canonical.get(nested, nested)
            else:
                _remap_internal_answer_labels(nested, original_to_canonical)
    elif isinstance(value, list):
        for nested in value:
            _remap_internal_answer_labels(nested, original_to_canonical)


def _choice_permutation_for_question(
    *,
    passage_seed: int,
    passage_id: str,
    item_id: str,
    question_index: int,
) -> tuple[dict[str, str], dict[str, str], str, str]:
    """Build one replayable label permutation from only system-owned seed data."""

    seed_material = (
        f"{CHOICE_PERMUTATION_VERSION}|passage_seed={passage_seed}"
        f"|passage_id={passage_id}|item_id={item_id}|question_index={question_index}"
    )
    seed_digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    rng = random.Random(int(seed_digest, 16))
    original_labels = list(ANSWER_LABEL_ORDER)
    rng.shuffle(original_labels)
    canonical_to_original = dict(zip(ANSWER_LABEL_ORDER, original_labels))
    original_to_canonical = {
        original: canonical
        for canonical, original in canonical_to_original.items()
    }
    return original_to_canonical, canonical_to_original, seed_material, seed_digest


def _permutation_question_references(
    output: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return raw question objects in the final canonical order."""

    if "questions" in output:
        if any(field in output for field in GENERATOR_QUESTION_GROUP_FIELDS.values()):
            raise ValueError("Generator response must use either flat or grouped questions, not both")
        questions = output["questions"]
        if not isinstance(questions, list):
            raise ValueError("Generator questions must be an array")
        if not all(isinstance(question, dict) for question in questions):
            raise ValueError("Generator questions must contain only question objects")
        return _evidence_position_aware_order(questions, output.get("passage", ""))

    expected_fields = set(GENERATOR_QUESTION_GROUP_FIELDS.values())
    present_fields = {field for field in expected_fields if field in output}
    if present_fields != expected_fields:
        missing = sorted(expected_fields - present_fields)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        raise ValueError("grouped Generator response must contain all type collections (" + "; ".join(detail) + ")")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for question_type, field_name in GENERATOR_QUESTION_GROUP_FIELDS.items():
        questions = output[field_name]
        if not isinstance(questions, list):
            raise ValueError(f"{field_name} must be an array")
        if not all(isinstance(question, dict) for question in questions):
            raise ValueError(f"{field_name} must contain only question objects")
        grouped[question_type] = questions
    return _evidence_position_aware_order(
        [question for question_type in QUESTION_TYPES for question in grouped[question_type]],
        output.get("passage", ""),
    )


def apply_choice_permutation_to_question(
    question: dict[str, Any],
    *,
    original_to_canonical: dict[str, str],
    canonical_to_original: dict[str, str],
) -> dict[str, Any]:
    """Apply an already-recorded A/B/C/D mapping to one semantic question.

    The helper is intentionally pure: it returns a deep copy and never derives
    a new mapping.  This is used both by the original whole-set permutation and
    by the bounded v0.2.11 inference repair merge.
    """

    if not isinstance(question, dict):
        raise ValueError("choice permutation requires a question object")
    if set(original_to_canonical) != ANSWER_LABELS or set(original_to_canonical.values()) != ANSWER_LABELS:
        raise ValueError("original_to_canonical must be a complete A/B/C/D mapping")
    if set(canonical_to_original) != ANSWER_LABELS or set(canonical_to_original.values()) != ANSWER_LABELS:
        raise ValueError("canonical_to_original must be a complete A/B/C/D mapping")
    if any(canonical_to_original[canonical] != original for original, canonical in original_to_canonical.items()):
        raise ValueError("choice permutation mappings must be inverses")

    copied = copy.deepcopy(question)
    choices = copied.get("choices")
    original_answer = copied.get("correct_answer")
    if not isinstance(choices, dict) or set(choices) != ANSWER_LABELS:
        raise ValueError("question must contain exactly A/B/C/D choices")
    if original_answer not in ANSWER_LABELS:
        raise ValueError("question has an invalid correct_answer")
    copied["choices"] = {
        canonical_label: copy.deepcopy(choices[original_label])
        for canonical_label, original_label in canonical_to_original.items()
    }
    copied["correct_answer"] = original_to_canonical[original_answer]
    distractor_metadata = copied.get("distractor_metadata")
    if isinstance(distractor_metadata, dict) and set(distractor_metadata) == ANSWER_LABELS:
        copied["distractor_metadata"] = {
            canonical_label: copy.deepcopy(distractor_metadata[original_label])
            for canonical_label, original_label in canonical_to_original.items()
        }
    for key, value in copied.items():
        if key not in {"choices", "correct_answer"}:
            _remap_internal_answer_labels(value, original_to_canonical)
    return copied


def permute_generator_choices(
    output: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply an independent deterministic A/B/C/D permutation per v0.2 item.

    ``output`` may be the model-facing flat or grouped response, or the
    trusted canonical flat response.  The returned output is always a deep
    copy, and no identity fields are assigned here.  Planned question
    identity/index values are used only as stable seed material; the existing
    canonicalizer still owns persisted identity fields.  The returned
    provenance records both mapping directions and enough seed material to
    reconstruct each mapping.
    """

    if plan.get("schema_version") != "reading-plan-v0.2":
        raise ValueError("choice permutation requires a Reading v0.2 plan")
    passage_seed = plan.get("seed")
    if not isinstance(passage_seed, int) or isinstance(passage_seed, bool):
        raise ValueError("choice permutation requires an integer passage seed")
    passage_id = plan.get("passage_id") or passage_id_for_seed(passage_seed)
    if not isinstance(passage_id, str):
        raise ValueError("choice permutation requires a Planner-owned passage_id")
    if not isinstance(output, dict):
        raise ValueError("choice permutation requires a Generator response object")

    permuted = copy.deepcopy(output)
    questions = _permutation_question_references(permuted, plan)
    question_provenance: list[dict[str, Any]] = []
    for question_index, question in enumerate(questions, 1):
        if not isinstance(question, dict):
            raise ValueError(f"question {question_index} must be an object")
        _omit_transport_null_target_fields(question)
        item_id = f"{passage_id}-q{question_index}"
        choices = question.get("choices")
        original_answer = question.get("correct_answer")
        if not isinstance(choices, dict) or set(choices) != set(ANSWER_LABEL_ORDER):
            raise ValueError(f"question {item_id} must contain exactly A/B/C/D choices")
        if original_answer not in ANSWER_LABELS:
            raise ValueError(f"question {item_id} has an invalid correct_answer")

        original_to_canonical, canonical_to_original, seed_material, seed_digest = (
            _choice_permutation_for_question(
                passage_seed=passage_seed,
                passage_id=passage_id,
                item_id=item_id,
                question_index=question_index,
            )
        )
        permuted_question = apply_choice_permutation_to_question(
            question,
            original_to_canonical=original_to_canonical,
            canonical_to_original=canonical_to_original,
        )
        question.clear()
        question.update(permuted_question)
        question_provenance.append({
            "item_id": item_id,
            "question_index": question_index,
            "seed_material": seed_material,
            "seed_sha256": "sha256:" + seed_digest,
            "original_to_canonical": original_to_canonical,
            "canonical_to_original": canonical_to_original,
        })

    provenance = {
        "version": CHOICE_PERMUTATION_VERSION,
        "algorithm": "sha256-seeded Fisher-Yates shuffle of A/B/C/D per question",
        "passage_seed": passage_seed,
        "passage_id": passage_id,
        "questions": question_provenance,
    }
    return permuted, provenance


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w]+(?:['-][\w]+)*\b", text, flags=re.UNICODE))


def split_paragraphs(passage: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", passage.strip()) if paragraph.strip()]


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _contains_anchor(paragraph: str, anchor: str) -> bool:
    return _normalized_text(anchor) in _normalized_text(paragraph)


_TARGET_STEM_PREFIX = re.compile(r"^\s*The\s+(?:word|phrase)\b", flags=re.IGNORECASE)
_TARGET_STEM_PATTERN = re.compile(
    r"^\s*The\s+(?:word|phrase)\s+(?P<target>.+?)\s+in\s+"
    r"(?P<location>(?:line\s+\d+)|(?:paragraph\s+\d+)|(?:(?:the\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth)\s+paragraph))\s+"
    r"(?:refers\s+to(?:\s+.+)?|is\s+closest\s+in\s+meaning\s+to)\s*$",
    flags=re.IGNORECASE,
)
_PARAGRAPH_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
}
_TARGET_QUESTION_TYPES = {"REFERENCE", "VOCABULARY_IN_CONTEXT"}
TARGET_LINE_NORMALIZATION_VERSION = "reading-v0.2.5-target-line-normalization-v1"


def _target_metadata_from_stem(stem: str) -> tuple[str, int] | None:
    """Extract the target and claimed location number from a target stem.

    This compatibility helper retains the historical two-tuple API.  New v0.2
    line-based validation uses ``_target_reference_from_stem`` so it can also
    distinguish a line from a paragraph.
    """

    reference = _target_reference_from_stem(stem)
    if reference is None:
        return None
    target, _location_kind, location_number = reference
    return target, location_number


def _target_reference_from_stem(stem: str) -> tuple[str, str, int] | None:
    """Extract target text and its explicit line/paragraph location from a stem."""

    match = _TARGET_STEM_PATTERN.fullmatch(stem)
    if match is None:
        return None
    location = match.group("location").casefold()
    line_location = re.fullmatch(r"line\s+(\d+)", location)
    if line_location is not None:
        location_kind = "line"
        location_number = int(line_location.group(1))
    else:
        numeric_location = re.fullmatch(r"paragraph\s+(\d+)", location)
        if numeric_location is not None:
            location_kind = "paragraph"
            location_number = int(numeric_location.group(1))
        else:
            ordinal = re.fullmatch(
                r"(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth)\s+paragraph",
                location,
            )
            if ordinal is None:
                return None
            location_kind = "paragraph"
            location_number = _PARAGRAPH_ORDINALS[ordinal.group(1)]
    target = match.group("target").strip()
    if len(target) >= 2 and target[0] in {"'", '"'} and target[-1] == target[0]:
        target = target[1:-1].strip()
    return target, location_kind, location_number


_SURFACE_TRANSLATION = str.maketrans({
    "’": "'",
    "‘": "'",
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
})
_SURFACE_STRIP_CHARS = string.punctuation + "“”‘’‐‑‒–—"


def _surface_text(value: str) -> str:
    """Normalize only case, whitespace, quotes, and edge punctuation."""

    normalized = unicodedata.normalize("NFC", value).translate(_SURFACE_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.strip(_SURFACE_STRIP_CHARS).strip().casefold()


def _contains_surface_expression(paragraph: str, target: str) -> bool:
    """Check for an exact token sequence, never a fuzzy substring match."""

    target_text = _surface_text(target)
    paragraph_text = _surface_text(paragraph)
    if not target_text:
        return False
    escaped_target = re.escape(target_text)
    return re.search(
        rf"(?<![\w'-]){escaped_target}(?![\w'-])",
        paragraph_text,
        flags=re.UNICODE,
    ) is not None


def _surface_match_line_numbers(lines: list[str], target_text: str) -> list[int]:
    """Return display lines matching a target under target-presence semantics."""

    return [
        line_number
        for line_number, line in enumerate(lines, 1)
        if _contains_surface_expression(line, target_text)
    ]


def _target_line_contains_expression(
    lines: list[str],
    target_line: Any,
    target_text: str,
) -> bool:
    """Return whether a supplied 1-based display line contains the target."""

    if (
        isinstance(target_line, bool)
        or not isinstance(target_line, int)
        or not 1 <= target_line <= len(lines)
    ):
        return False
    return _contains_surface_expression(lines[target_line - 1], target_text)


def normalize_target_line_metadata(
    output: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize display-line metadata on a copied output.

    This is deliberately separate from schema and target-presence validation.
    It runs only on the post-permutation canonical copy, and it never mutates
    the Generator response that is persisted as ``generator_raw.json``.

    A supplied target line is authoritative when it contains the target under
    the exact surface matcher, even when other display lines also match.  If
    the supplied line does not match, the structured target line is derived
    only when the target expression matches exactly one canonical display line.
    A stem's numeric reference is rewritten only when the existing full
    target-stem grammar parses, the stem target agrees with ``target_text``
    under the same surface matcher, and the embedded number equals the
    original Generator ``target_line``.  That last equality is the explicit
    safe pattern for a mechanical stem rewrite.
    """

    normalized = copy.deepcopy(output)
    audit: dict[str, Any] = {
        "version": TARGET_LINE_NORMALIZATION_VERSION,
        "algorithm": (
            "fixed-width display-line scan using _contains_surface_expression; "
            "preserve a supplied matching target line, otherwise derive only a unique global match; "
            "stem rewrite only when parsed stem line equals generator_target_line"
        ),
        "questions": [],
    }
    passage = normalized.get("passage")
    questions = normalized.get("questions")
    if (
        normalized.get("schema_version") != "reading-generator-v0.2"
        or not isinstance(passage, str)
        or not isinstance(questions, list)
    ):
        return normalized, audit

    lines = display_lines(passage)
    records = audit["questions"]
    for question_index, question in enumerate(questions, 1):
        if not isinstance(question, dict) or question.get("question_type") not in _TARGET_QUESTION_TYPES:
            continue
        target_text = question.get("target_text")
        if not isinstance(target_text, str) or not target_text.strip():
            continue

        generator_target_line = question.get("target_line")
        matching_lines = _surface_match_line_numbers(lines, target_text)
        supplied_line_matches = _target_line_contains_expression(
            lines,
            generator_target_line,
            target_text,
        )
        if supplied_line_matches:
            resolution = "UNIQUE_SURFACE_MATCH" if len(matching_lines) == 1 else "SUPPLIED_LINE_MATCH"
            canonical_target_line = generator_target_line
        else:
            resolution = (
                "ZERO_SURFACE_MATCH"
                if not matching_lines
                else "UNIQUE_SURFACE_MATCH"
                if len(matching_lines) == 1
                else "MULTIPLE_SURFACE_MATCH"
            )
            canonical_target_line = matching_lines[0] if len(matching_lines) == 1 else None
        record: dict[str, Any] = {
            "item_id": question.get("item_id"),
            "question_index": question_index,
            "generator_target_line": copy.deepcopy(generator_target_line),
            "canonical_target_line": canonical_target_line,
            "target_line_resolution": resolution,
            "stem_line_normalized": False,
            "matched_display_lines": matching_lines,
        }
        records.append(record)
        if supplied_line_matches:
            continue
        if len(matching_lines) != 1:
            continue

        canonical_target_line = matching_lines[0]
        # A unique surface match is sufficient to derive canonical structured
        # metadata.  Invalid model values still fail the normal schema/contract
        # gates; this function is not an input repair for malformed types.
        question["target_line"] = canonical_target_line

        stem = question.get("stem")
        if not isinstance(stem, str):
            continue
        stem_match = _TARGET_STEM_PATTERN.fullmatch(stem)
        if stem_match is None:
            continue
        stem_reference = _target_reference_from_stem(stem)
        if stem_reference is None:
            continue
        stem_target, location_kind, stem_line = stem_reference
        if (
            location_kind != "line"
            or _surface_text(stem_target) != _surface_text(target_text)
            or not isinstance(generator_target_line, int)
            or isinstance(generator_target_line, bool)
            or generator_target_line < 1
            or stem_line != generator_target_line
            or stem_line == canonical_target_line
        ):
            continue

        location_text = stem_match.group("location")
        digits_match = re.search(r"\d+", location_text)
        if digits_match is None:
            continue
        absolute_start = stem_match.start("location") + digits_match.start()
        absolute_end = stem_match.start("location") + digits_match.end()
        question["stem"] = stem[:absolute_start] + str(canonical_target_line) + stem[absolute_end:]
        record["stem_line_normalized"] = True

    return normalized, audit


def _target_presence_errors(
    question: dict[str, Any],
    paragraphs: list[str],
    passage: str,
) -> list[str]:
    question_type = question["question_type"]
    if question_type not in _TARGET_QUESTION_TYPES:
        return []
    stem = question["stem"]
    if not _TARGET_STEM_PREFIX.match(stem):
        if "target_text" in question or "target_line" in question:
            item_id = question["item_id"]
            diagnostic_prefix = f"generator: {item_id} {question_type}_TARGET"
            return [f"{diagnostic_prefix}_METADATA_UNPARSEABLE"]
        return []
    metadata = _target_reference_from_stem(stem)
    item_id = question["item_id"]
    diagnostic_prefix = f"generator: {item_id} {question_type}_TARGET"
    if metadata is None:
        return [f"{diagnostic_prefix}_METADATA_UNPARSEABLE"]
    target, location_kind, location_number = metadata
    target_text = question.get("target_text")
    target_line = question.get("target_line")
    has_explicit_target_metadata = "target_text" in question or "target_line" in question
    if location_kind == "line":
        if not isinstance(target_text, str) or not target_text.strip() or not isinstance(target_line, int):
            return [f"{diagnostic_prefix}_METADATA_MISSING: line targets require target_text and target_line"]
        if _surface_text(target_text) != _surface_text(target):
            return [f"{diagnostic_prefix}_TEXT_MISMATCH: target_text does not match the stem target"]
        lines = display_lines(passage)
        matching_lines = _surface_match_line_numbers(lines, target_text)
        if _target_line_contains_expression(lines, target_line, target_text):
            if target_line != location_number:
                return [f"{diagnostic_prefix}_LINE_MISMATCH: target_line does not match line {location_number}"]
            return []
        if not matching_lines:
            return [
                f"{diagnostic_prefix}_NOT_FOUND: targeted expression {target_text!r} is not present "
                f"in line {target_line}"
            ]
        if len(matching_lines) > 1:
            return [
                f"{diagnostic_prefix}_MULTIPLE_MATCHES: targeted expression {target_text!r} "
                f"appears on canonical display lines {matching_lines}"
            ]
        if target_line != location_number:
            return [f"{diagnostic_prefix}_LINE_MISMATCH: target_line does not match line {location_number}"]
        if not 1 <= target_line <= len(lines):
            return [f"{diagnostic_prefix}_LOCATION_INVALID: line {target_line} is out of range"]
        if not _contains_surface_expression(lines[target_line - 1], target_text):
            return [
                f"{diagnostic_prefix}_NOT_FOUND: targeted expression {target_text!r} is not present "
                f"in line {target_line}"
            ]
        return []
    if has_explicit_target_metadata:
        return [f"{diagnostic_prefix}_METADATA_MISMATCH: paragraph targets cannot carry line metadata"]
    paragraph_number = location_number
    if not 1 <= paragraph_number <= len(paragraphs):
        return [f"{diagnostic_prefix}_LOCATION_INVALID: paragraph {paragraph_number} is out of range"]
    if not _contains_surface_expression(paragraphs[paragraph_number - 1], target):
        return [
            f"{diagnostic_prefix}_NOT_FOUND: targeted expression {target!r} is not present "
            f"in paragraph {paragraph_number}"
        ]
    return []


def _duplicate_text(values: list[str]) -> bool:
    normalized = [_normalized_text(value).strip(" .,:;!?\"'()[]") for value in values]
    return len(set(normalized)) != len(normalized)


def _question_metadata_errors(question: dict[str, Any]) -> list[str]:
    """Validate optional secondary taxonomy and private distractor metadata."""

    errors: list[str] = []
    item_id = question.get("item_id", "<unknown>")
    question_type = question.get("question_type")
    subtype = question.get("subtype")
    if subtype is not None:
        allowed = (
            QUESTION_SUBTYPE_COMPATIBILITY.get(question_type, frozenset())
            if isinstance(question_type, str)
            else frozenset()
        )
        if subtype not in QUESTION_SUBTYPES:
            errors.append(f"generator: {item_id} has invalid question subtype {subtype!r}")
        elif subtype not in allowed:
            errors.append(
                f"generator: {item_id} subtype {subtype!r} is not compatible with {question_type!r}"
            )

    metadata = question.get("distractor_metadata")
    if metadata is None:
        return errors
    if not isinstance(metadata, dict) or set(metadata) != ANSWER_LABELS:
        errors.append(f"generator: {item_id} distractor_metadata must contain exactly A/B/C/D")
        return errors
    correct_answer = question.get("correct_answer")
    for label in ANSWER_LABEL_ORDER:
        entry = metadata[label]
        if not isinstance(entry, dict):
            errors.append(f"generator: {item_id} distractor_metadata[{label}] must be an object")
            continue
        category = entry.get("category")
        rationale = entry.get("rationale")
        if category == DISTRACTOR_METADATA_CORRECT:
            if label != correct_answer:
                errors.append(
                    f"generator: {item_id} marks non-key choice {label} as CORRECT_OPTION"
                )
        elif category not in DISTRACTOR_CATEGORIES:
            errors.append(f"generator: {item_id} has invalid distractor category {category!r} for {label}")
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(f"generator: {item_id} distractor rationale for {label} is missing")
    if correct_answer in ANSWER_LABELS:
        correct_entry = metadata.get(correct_answer, {})
        if isinstance(correct_entry, dict) and correct_entry.get("category") != DISTRACTOR_METADATA_CORRECT:
            errors.append(f"generator: {item_id} correct choice must be marked CORRECT_OPTION")
    return errors


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
    is_v02 = (
        (plan is not None and plan.get("schema_version") == "reading-plan-v0.2")
        or output.get("schema_version") == "reading-generator-v0.2"
    )
    paragraphs = split_paragraphs(output["passage"])
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
        errors.extend(_question_metadata_errors(question))
        choices = question["choices"]
        if _duplicate_text(list(choices.values())):
            errors.append(f"generator: question {item_id} has duplicate answer choices")
        evidence = question["evidence"]
        paragraph_number = evidence["paragraph"]
        if paragraph_number > len(paragraphs):
            errors.append(f"generator: {item_id} evidence paragraph {paragraph_number} is out of range")
        elif not _contains_anchor(paragraphs[paragraph_number - 1], evidence["anchor"]):
            errors.append(f"generator: {item_id} evidence anchor is not present in its paragraph")
        if is_v02:
            errors.extend(_target_presence_errors(question, paragraphs, output["passage"]))
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

    # Keep semantic choice checks conservative and non-blocking. Importing
    # lazily avoids a module cycle because diagnostics uses contract helpers.
    from .diagnostics import choice_quality_warnings

    quality_warnings = choice_quality_warnings(output if isinstance(output, dict) else None)

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
        "choice_quality_warnings": quality_warnings,
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
    if schema_version == "reading-blind-input-v0.1":
        payload["title"] = output["title"]
        # Preserve the historical v0.1 field order in persisted JSON objects.
        payload = {
            "schema_version": payload["schema_version"],
            "passage_id": payload["passage_id"],
            "section": payload["section"],
            "title": payload["title"],
            "passage": payload["passage"],
            "questions": payload["questions"],
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


def inference_verifier_input(
    output: dict[str, Any],
    *,
    item_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Project the visible surface of only the requested INFERENCE items."""

    if not isinstance(output, dict):
        raise ValueError("inference verifier input source must be an object")
    questions = []
    for question in output["questions"]:
        if question.get("question_type") != "INFERENCE":
            continue
        if item_ids is not None and question.get("item_id") not in item_ids:
            continue
        questions.append({
            "item_id": question["item_id"],
            "stem": question["stem"],
            "choices": copy.deepcopy(question["choices"]),
        })
    payload = {
        "passage_id": output["passage_id"],
        "section": output["section"],
        "passage": output["passage"],
        "questions": questions,
    }
    leakage = _nested_keys(payload, BLIND_FORBIDDEN_KEYS)
    if leakage:
        raise ValueError("inference verifier projection contains forbidden field(s): " + ", ".join(leakage))
    return payload


def inference_verifier_input_errors(
    output: Any,
    payload: Any,
    schema_paths: dict[str, Path] | None = None,
    *,
    expected_item_ids: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Validate that verifier input is a strict visible inference projection."""

    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02
    errors: list[str] = []
    if not isinstance(output, dict):
        return ["inference verifier input source must be an object"]
    try:
        expected = inference_verifier_input(output, item_ids=expected_item_ids)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"inference verifier input could not be derived: {exc}"]
    if payload != expected:
        errors.append("inference verifier input does not match the canonical visible projection")
    errors.extend(
        f"inference verifier input: forbidden field {path}"
        for path in _nested_keys(payload, BLIND_FORBIDDEN_KEYS)
    )
    errors.extend(_schema_errors(payload, "inference_verifier_input", schema_paths))
    return errors


def validate_inference_verifier_contract(
    output: Any,
    verifier_input: dict[str, Any],
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    """Validate one blind Verifier response against its supplied item IDs."""

    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02
    errors = _schema_errors(output, "inference_verifier", schema_paths)
    if errors or not isinstance(output, dict):
        return errors
    if output["passage_id"] != verifier_input["passage_id"] or output["section"] != verifier_input["section"]:
        errors.append("inference_verifier: passage identity does not match input")
    expected_ids = [question["item_id"] for question in verifier_input["questions"]]
    actual_ids, duplicates = _ids(output["questions"], "item_id")
    if duplicates:
        errors.append(f"inference_verifier: duplicate item_id(s) {duplicates}")
    if actual_ids != expected_ids:
        errors.append("inference_verifier: question ids/order do not match input")
    return errors


def inference_repair_input_errors(
    payload: Any,
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02
    return _schema_errors(payload, "inference_repair_input", schema_paths)


def inference_repair_model_schema_for_item_ids(item_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Build a repair transport schema with the exact requested item IDs."""

    if not item_ids or len(set(item_ids)) != len(item_ids) or not all(isinstance(item_id, str) for item_id in item_ids):
        raise ValueError("repair schema requires a non-empty unique item-id sequence")
    schema = load_schema(SCHEMA_PATHS_V02["inference_repair"])
    replacements = schema.get("properties", {}).get("replacements")
    if not isinstance(replacements, dict) or not isinstance(replacements.get("items"), dict):
        raise ValueError("repair schema is missing its replacement item definition")
    replacements["minItems"] = len(item_ids)
    replacements["maxItems"] = len(item_ids)
    item_properties = replacements["items"].get("properties")
    if not isinstance(item_properties, dict):
        raise ValueError("repair schema is missing replacement item properties")
    item_properties["item_id"] = {"enum": list(item_ids)}
    return schema


def validate_inference_repair_contract(
    output: Any,
    requested_item_ids: list[str] | tuple[str, ...],
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    """Validate exactly two indexed candidates per flagged inference item."""

    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02
    errors = _schema_errors(output, "inference_repair", schema_paths)
    if errors or not isinstance(output, dict):
        return errors
    actual_ids, duplicates = _ids(output["replacements"], "item_id")
    requested = list(requested_item_ids)
    if duplicates:
        errors.append(f"inference_repair: duplicate item_id(s) {duplicates}")
    if len(actual_ids) != len(requested) or set(actual_ids) != set(requested):
        errors.append(
            "inference_repair: replacement item IDs must exactly match requested IDs; "
            f"requested {requested}, got {actual_ids}"
        )
    for replacement in output["replacements"]:
        item_id = replacement.get("item_id")
        candidates = replacement.get("candidates")
        if not isinstance(candidates, list):
            continue
        candidate_indices = [candidate.get("candidate_index") for candidate in candidates if isinstance(candidate, dict)]
        if (
            len(candidate_indices) != 2
            or any(isinstance(index, bool) or not isinstance(index, int) for index in candidate_indices)
            or sorted(candidate_indices) != [1, 2]
        ):
            errors.append(
                f"inference_repair: {item_id} candidate indices must be exactly [1, 2]; got {candidate_indices}"
            )
        if len(candidate_indices) != len(set(candidate_indices)):
            errors.append(f"inference_repair: {item_id} contains duplicate candidate_index values")
    return errors


def candidate_verifier_input(
    output: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the temporary blind input for surviving remapped candidates."""

    if not isinstance(output, dict):
        raise ValueError("candidate verifier input source must be an object")
    visible_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("candidate verifier input candidates must be objects")
        question = candidate.get("canonical_remapped_question", candidate.get("question"))
        if not isinstance(question, dict):
            raise ValueError("candidate verifier input candidate is missing its canonical question")
        visible_candidates.append({
            "parent_item_id": candidate["parent_item_id"],
            "candidate_index": candidate["candidate_index"],
            "stem": question["stem"],
            "choices": copy.deepcopy(question["choices"]),
        })
    payload = {
        "passage_id": output["passage_id"],
        "section": output["section"],
        "passage": output["passage"],
        "candidates": visible_candidates,
    }
    leakage = _nested_keys(payload, BLIND_FORBIDDEN_KEYS)
    if leakage:
        raise ValueError("candidate verifier projection contains forbidden field(s): " + ", ".join(leakage))
    return payload


def candidate_verifier_input_errors(
    output: Any,
    payload: Any,
    candidates: list[dict[str, Any]],
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    """Validate the exact visible allowlist used for candidate verification."""

    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02
    errors: list[str] = []
    if not isinstance(output, dict):
        return ["candidate verifier input source must be an object"]
    try:
        expected = candidate_verifier_input(output, candidates)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"candidate verifier input could not be derived: {exc}"]
    if payload != expected:
        errors.append("candidate verifier input does not match the canonical visible projection")
    errors.extend(
        f"candidate verifier input: forbidden field {path}"
        for path in _nested_keys(payload, BLIND_FORBIDDEN_KEYS)
    )
    errors.extend(_schema_errors(payload, "candidate_verifier_input", schema_paths))
    return errors


def validate_candidate_verifier_contract(
    output: Any,
    verifier_input: dict[str, Any],
    schema_paths: dict[str, Path] | None = None,
) -> list[str]:
    """Validate every blind candidate judgment against the supplied candidate pairs."""

    if schema_paths is None:
        schema_paths = SCHEMA_PATHS_V02
    errors = _schema_errors(output, "candidate_verifier", schema_paths)
    if errors or not isinstance(output, dict):
        return errors
    if output["passage_id"] != verifier_input["passage_id"] or output["section"] != verifier_input["section"]:
        errors.append("candidate_verifier: passage identity does not match input")
    expected_pairs = [
        (candidate.get("parent_item_id"), candidate.get("candidate_index"))
        for candidate in verifier_input["candidates"]
    ]
    actual_pairs = [
        (candidate.get("parent_item_id"), candidate.get("candidate_index"))
        for candidate in output["candidates"]
    ]
    duplicates = sorted({pair for pair in actual_pairs if actual_pairs.count(pair) > 1})
    if duplicates:
        errors.append(f"candidate_verifier: duplicate candidate identity {duplicates}")
    if actual_pairs != expected_pairs:
        errors.append(
            "candidate_verifier: candidate identities/order do not match input; "
            f"expected {expected_pairs}, got {actual_pairs}"
        )
    return errors


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
        if result.get("schema_version") == "reading-result-v0.2":
            required_true.add("inference_gate_pass")
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
