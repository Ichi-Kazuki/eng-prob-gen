"""Structure v0.3 Generator shard/merge contracts.

Implements only:
  * a single shared per-item semantic contract path (copied unweakened from
    the frozen structure/v02/contracts.py::validate_generator_contract
    per-item rules) so shard and merged validation cannot drift apart;
  * validate_generator_shard_contract: validates one five-item Generator
    shard response against the fixed slice of the v0.3 plan it must cover;
  * validate_merged_generator_contract: validates the deterministically
    merged fifteen-item candidate batch against the full v0.3 plan;
  * merge_generator_shards: deterministically concatenates three
    already-shard-contract-passing shard responses (in shard order 1->2->3)
    and re-validates the merged batch, raising ValueError rather than
    repairing on any failure.

No semantic retry, repair, regeneration, item replacement, or partial merge
happens here.
"""

from __future__ import annotations

import copy
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
PLAN_SCHEMA_PATH = ROOT / "schemas" / "plan.schema.json"
GENERATOR_SHARD_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "generator_shard_output.schema.json"

DISTRACTOR_CANDIDATE_IDS: tuple[str, ...] = ("d1", "d2", "d3", "d4", "d5", "d6")
ALL_CANDIDATE_IDS: tuple[str, ...] = ("correct",) + DISTRACTOR_CANDIDATE_IDS

# Frozen fixed partition of the 15-item v0.3 plan across the three Generator
# shards. Not random, not adaptive, not Planner-owned.
SHARD_ORDER_RANGES: dict[int, tuple[int, int]] = {
    1: (1, 5),
    2: (6, 10),
    3: (11, 15),
}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _deduplicate(errors: list[str]) -> list[str]:
    return list(dict.fromkeys(errors))


def _merged_schema() -> dict[str, Any]:
    """Build an in-memory 15-item variant of the shard output schema.

    No separate merged_generator_candidates.schema.json file is created; the
    per-item shape is identical to the shard schema's item, only the batch
    size differs.
    """

    schema = copy.deepcopy(load_schema(GENERATOR_SHARD_OUTPUT_SCHEMA_PATH))
    schema["properties"]["items"]["minItems"] = 15
    schema["properties"]["items"]["maxItems"] = 15
    return schema


def _shared_item_errors(generated_items: list[Any], plan_by_id: dict[str, Any]) -> list[str]:
    """Per-item semantic contract shared by shard and merged validation.

    Copied unweakened from structure/v02/contracts.py::validate_generator_contract.
    """

    errors: list[str] = []
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

    return errors


def validate_generator_shard_contract(output: Any, plan: Any, shard: int) -> list[str]:
    """Validate one v0.3 Generator shard response against its fixed plan slice.

    `shard` must be exactly 1, 2, or 3. The five expected Planner items are
    the fixed slice `plan["items"][SHARD_ORDER_RANGES[shard]]`, never a
    semantically inspected or adaptively chosen subset.
    """

    errors = schema_errors(plan, load_schema(PLAN_SCHEMA_PATH))
    if shard not in SHARD_ORDER_RANGES:
        errors.append(f"generator_shard: shard must be exactly 1, 2, or 3, got {shard!r}")
        return _deduplicate(errors)

    errors.extend(schema_errors(output, load_schema(GENERATOR_SHARD_OUTPUT_SCHEMA_PATH)))
    if not isinstance(output, dict) or not isinstance(plan, dict):
        return _deduplicate(errors)

    generated_items = output.get("items")
    planned_items = plan.get("items")
    if not isinstance(generated_items, list) or not isinstance(planned_items, list) or len(planned_items) != 15:
        errors.append(f"generator_shard[{shard}]: plan must contain exactly 15 items")
        return _deduplicate(errors)

    start, end = SHARD_ORDER_RANGES[shard]
    expected_planned = planned_items[start - 1:end]

    if len(generated_items) != 5:
        errors.append(f"generator_shard[{shard}]: expected exactly 5 items, got {len(generated_items)}")

    generated_ids = [item.get("item_id") if isinstance(item, dict) else None for item in generated_items]
    valid_generated_ids = [value for value in generated_ids if isinstance(value, str)]
    duplicate_generated_ids = sorted(
        {value for value in valid_generated_ids if valid_generated_ids.count(value) > 1}
    )
    if duplicate_generated_ids:
        errors.append(f"generator_shard[{shard}]: duplicate item_id(s): {duplicate_generated_ids}")

    expected_ids = [item.get("item_id") if isinstance(item, dict) else None for item in expected_planned]
    if generated_ids != expected_ids:
        errors.append(
            f"generator_shard[{shard}]: item IDs/order do not match the expected plan sequence: "
            f"expected {expected_ids}, got {generated_ids}"
        )

    plan_by_id = {item.get("item_id"): item for item in expected_planned if isinstance(item, dict)}
    errors.extend(_shared_item_errors(generated_items, plan_by_id))

    return _deduplicate(errors)


def validate_merged_generator_contract(output: Any, plan: Any) -> list[str]:
    """Validate the merged fifteen-item candidate batch against the full v0.3 plan."""

    errors = schema_errors(plan, load_schema(PLAN_SCHEMA_PATH))
    errors.extend(schema_errors(output, _merged_schema()))
    if not isinstance(output, dict) or not isinstance(plan, dict):
        return _deduplicate(errors)

    generated_items = output.get("items")
    planned_items = plan.get("items")
    if not isinstance(generated_items, list) or not isinstance(planned_items, list) or len(planned_items) != 15:
        errors.append("merged_generator: plan must contain exactly 15 items")
        return _deduplicate(errors)

    if len(generated_items) != 15:
        errors.append(f"merged_generator: expected exactly 15 items, got {len(generated_items)}")

    generated_ids = [item.get("item_id") if isinstance(item, dict) else None for item in generated_items]
    valid_generated_ids = [value for value in generated_ids if isinstance(value, str)]
    duplicate_generated_ids = sorted(
        {value for value in valid_generated_ids if valid_generated_ids.count(value) > 1}
    )
    if duplicate_generated_ids:
        errors.append(f"merged_generator: duplicate item_id(s): {duplicate_generated_ids}")

    expected_ids = [item.get("item_id") if isinstance(item, dict) else None for item in planned_items]
    if generated_ids != expected_ids:
        errors.append(
            f"merged_generator: item IDs/order do not match the plan sequence: "
            f"expected {expected_ids}, got {generated_ids}"
        )

    plan_by_id = {item.get("item_id"): item for item in planned_items if isinstance(item, dict)}
    errors.extend(_shared_item_errors(generated_items, plan_by_id))

    return _deduplicate(errors)


def merge_generator_shards(shard_outputs: Mapping[int, Any], plan: Any) -> dict[str, Any]:
    """Deterministically merge three already-validated Generator shard responses.

    Requires exactly the three keys 1, 2, 3. Each shard must independently
    pass validate_generator_shard_contract before any concatenation happens.
    Items are concatenated as deep copies strictly in shard order 1->2->3 (no
    sorting based on model output, no fuzzy reconciliation, no partial
    merge). The merged batch is then re-validated with
    validate_merged_generator_contract; any failure raises ValueError rather
    than repairing or returning a partial result.
    """

    if not isinstance(shard_outputs, dict) or set(shard_outputs) != {1, 2, 3}:
        raise ValueError("merge_generator_shards requires exactly three shard outputs keyed 1, 2, and 3")

    for shard in (1, 2, 3):
        shard_errors = validate_generator_shard_contract(shard_outputs[shard], plan, shard)
        if shard_errors:
            raise ValueError(
                f"generator shard {shard} failed its contract and cannot be merged: " + "; ".join(shard_errors)
            )

    merged_items: list[dict[str, Any]] = []
    for shard in (1, 2, 3):
        merged_items.extend(copy.deepcopy(item) for item in shard_outputs[shard]["items"])

    merged = {"items": merged_items}
    merged_errors = validate_merged_generator_contract(merged, plan)
    if merged_errors:
        raise ValueError(
            "merged Generator candidate batch failed contract validation: " + "; ".join(merged_errors)
        )
    return merged


__all__ = [
    "SHARD_ORDER_RANGES",
    "validate_generator_shard_contract",
    "validate_merged_generator_contract",
    "merge_generator_shards",
]
