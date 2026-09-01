"""Deterministic Structure v0.1 planning from the checked-in aggregate profile."""

from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from shared.schema_validation import load_schema, schema_errors


STRUCTURE_VERSION = "v0.1"
QUESTION_COUNT = 15
PROFILE_TOTAL = 75
DIFFICULTIES = ("EASY", "MEDIUM", "HARD")
PROFILE_PATH = Path(__file__).resolve().parent / "profile.json"
PLAN_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "plan.schema.json"


@lru_cache(maxsize=1)
def load_profile() -> dict[str, Any]:
    with PROFILE_PATH.open(encoding="utf-8") as handle:
        profile = json.load(handle)
    if not isinstance(profile, dict):
        raise ValueError("Structure profile must be a JSON object")
    return profile


def _raw_mapping(name: str) -> dict[str, int]:
    value = load_profile().get(name)
    if not isinstance(value, dict) or not value:
        raise ValueError(f"Structure profile field {name!r} must be a non-empty object")
    result: dict[str, int] = {}
    for key, weight in value.items():
        if not isinstance(key, str) or not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
            raise ValueError(f"Structure profile field {name!r} contains an invalid weight")
        result[key] = weight
    return result


def _mapping(name: str) -> dict[str, int]:
    result = {key: weight for key, weight in _raw_mapping(name).items() if weight}
    if not result:
        raise ValueError(f"Structure profile field {name!r} has no positive weights")
    return result


def _joint_mapping() -> dict[tuple[str, str, int], int]:
    value = load_profile().get("joint_structural_weights")
    if not isinstance(value, dict) or not value:
        raise ValueError("Structure profile field 'joint_structural_weights' must be a non-empty object")
    result: dict[tuple[str, str, int], int] = {}
    for target, by_clause in value.items():
        if not isinstance(target, str) or not isinstance(by_clause, dict) or not by_clause:
            raise ValueError("Structure joint structural weights contain an invalid target entry")
        for raw_clause_count, by_difficulty in by_clause.items():
            if not isinstance(raw_clause_count, str):
                raise ValueError("Structure joint structural weights contain an invalid clause count")
            try:
                clause_count = int(raw_clause_count)
            except ValueError as exc:
                raise ValueError("Structure joint structural weights contain an invalid clause count") from exc
            if str(clause_count) != raw_clause_count or clause_count not in {1, 2, 3, 4}:
                raise ValueError("Structure joint structural weights contain an invalid clause count")
            if not isinstance(by_difficulty, dict) or set(by_difficulty) != set(DIFFICULTIES):
                raise ValueError("Structure joint structural weights must contain EASY/MEDIUM/HARD counts")
            for difficulty in DIFFICULTIES:
                weight = by_difficulty[difficulty]
                if not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
                    raise ValueError("Structure joint structural weights contain an invalid weight")
                result[(target, difficulty, clause_count)] = weight
    return result


def _conditional_length_mapping() -> dict[str, dict[str, int]]:
    value = load_profile().get("sentence_length_weights_by_difficulty")
    if not isinstance(value, dict) or not value:
        raise ValueError(
            "Structure profile field 'sentence_length_weights_by_difficulty' must be a non-empty object"
        )
    result: dict[str, dict[str, int]] = {}
    for difficulty, by_length in value.items():
        if not isinstance(difficulty, str) or not isinstance(by_length, dict) or not by_length:
            raise ValueError("Structure conditional sentence-length weights contain an invalid difficulty entry")
        weights: dict[str, int] = {}
        for label, weight in by_length.items():
            if not isinstance(label, str) or not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
                raise ValueError("Structure conditional sentence-length weights contain an invalid weight")
            weights[label] = weight
        result[difficulty] = weights
    return result


PRIMARY_TARGET_WEIGHTS = _mapping("primary_target_weights")
DIFFICULTY_WEIGHTS = _mapping("difficulty_weights")
CLAUSE_COUNT_WEIGHTS = {int(key): value for key, value in _mapping("clause_count_weights").items()}
TARGET_SUBTYPES = load_profile().get("target_subtypes", {})
LENGTH_BINS = tuple(load_profile().get("sentence_length_bins", ()))
JOINT_STRUCTURAL_WEIGHTS = _joint_mapping()
SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY = _conditional_length_mapping()


def _validate_profile() -> None:
    raw_primary_target_weights = _raw_mapping("primary_target_weights")
    raw_difficulty_weights = _raw_mapping("difficulty_weights")
    raw_clause_count_weights = _raw_mapping("clause_count_weights")
    if sum(PRIMARY_TARGET_WEIGHTS.values()) != PROFILE_TOTAL:
        raise ValueError("Structure primary_target weights must sum to 75")
    if sum(DIFFICULTY_WEIGHTS.values()) != PROFILE_TOTAL:
        raise ValueError("Structure difficulty weights must sum to 75")
    if sum(CLAUSE_COUNT_WEIGHTS.values()) != PROFILE_TOTAL:
        raise ValueError("Structure clause-count weights must sum to 75")
    if sum(JOINT_STRUCTURAL_WEIGHTS.values()) != PROFILE_TOTAL:
        raise ValueError("Structure joint structural weights must sum to 75")

    actual_primary_target_weights = {
        target: sum(weight for (item_target, _difficulty, _clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                    if item_target == target)
        for target in set(raw_primary_target_weights) | {key[0] for key in JOINT_STRUCTURAL_WEIGHTS}
    }
    if actual_primary_target_weights != raw_primary_target_weights:
        raise ValueError("Structure joint structural weights do not reproduce primary_target weights")

    actual_difficulty_weights = {
        difficulty: sum(weight for (_target, item_difficulty, _clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                        if item_difficulty == difficulty)
        for difficulty in set(raw_difficulty_weights) | {key[1] for key in JOINT_STRUCTURAL_WEIGHTS}
    }
    if actual_difficulty_weights != raw_difficulty_weights:
        raise ValueError("Structure joint structural weights do not reproduce difficulty weights")

    expected_clause_count_weights = {int(key): weight for key, weight in raw_clause_count_weights.items()}
    actual_clause_count_weights = {
        clause_count: sum(weight for (_target, _difficulty, item_clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                          if item_clause_count == clause_count)
        for clause_count in set(expected_clause_count_weights) | {key[2] for key in JOINT_STRUCTURAL_WEIGHTS}
    }
    if actual_clause_count_weights != expected_clause_count_weights:
        raise ValueError("Structure joint structural weights do not reproduce clause-count weights")

    if len(LENGTH_BINS) != 4:
        raise ValueError("Structure profile must contain four sentence-length bins")
    length_labels: list[str] = []
    for length_bin in LENGTH_BINS:
        if not isinstance(length_bin, dict):
            raise ValueError("Structure sentence-length bins must be objects")
        required = {"label", "minimum", "maximum", "weight"}
        if not required.issubset(length_bin):
            raise ValueError("Structure sentence-length bin is missing a required field")
        if not isinstance(length_bin["label"], str) or not length_bin["label"]:
            raise ValueError("Structure sentence-length bin has an invalid label")
        if length_bin["label"] in length_labels:
            raise ValueError("Structure sentence-length bin labels must be unique")
        length_labels.append(length_bin["label"])
        if (
            any(isinstance(length_bin[field], bool) or not isinstance(length_bin[field], int)
                for field in ("minimum", "maximum", "weight"))
            or length_bin["minimum"] > length_bin["maximum"]
            or length_bin["weight"] <= 0
        ):
            raise ValueError("Structure sentence-length bin has invalid bounds or weight")
    overall_length_weights = {entry["label"]: entry["weight"] for entry in LENGTH_BINS}
    if sum(overall_length_weights.values()) != PROFILE_TOTAL:
        raise ValueError("Structure sentence-length weights must sum to 75")
    if set(SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY) != set(raw_difficulty_weights):
        raise ValueError("Structure conditional sentence-length weights have an invalid difficulty set")
    for difficulty, weights in SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY.items():
        if set(weights) != set(length_labels):
            raise ValueError("Structure conditional sentence-length weights have an invalid bin set")
        if sum(weights.values()) != raw_difficulty_weights[difficulty]:
            raise ValueError(f"Structure conditional sentence-length weights do not sum to {difficulty} marginal")
    actual_length_weights = {
        label: sum(weights[label] for weights in SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY.values())
        for label in length_labels
    }
    if actual_length_weights != overall_length_weights:
        raise ValueError("Structure conditional sentence-length weights do not reproduce overall length weights")
    if any(target not in TARGET_SUBTYPES or not TARGET_SUBTYPES[target] for target in PRIMARY_TARGET_WEIGHTS):
        raise ValueError("Structure profile is missing a subtype pool for a sampled primary target")


_validate_profile()


def _validate_seed(seed: int) -> None:
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("Structure seed must be a non-negative integer")


def weighted_choice(rng: random.Random, weighted_values: Mapping[Any, int]) -> Any:
    """Choose one key using integer weights and the supplied deterministic RNG."""

    positive = [(key, weight) for key, weight in weighted_values.items() if weight > 0]
    total = sum(weight for _, weight in positive)
    if total <= 0:
        raise ValueError("weighted choice requires at least one positive weight")
    draw = rng.randrange(total)
    for key, weight in positive:
        if draw < weight:
            return key
        draw -= weight
    raise AssertionError("weighted choice did not select a key")


def _sample_length(rng: random.Random, difficulty: str) -> tuple[dict[str, Any], int]:
    length_bin = weighted_choice(rng, SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY[difficulty])
    selected = next(entry for entry in LENGTH_BINS if entry["label"] == length_bin)
    word_count = rng.randint(selected["minimum"], selected["maximum"])
    return dict(selected), word_count


def _plan_item(rng: random.Random, seed: int, order: int) -> dict[str, Any]:
    primary_target, difficulty, clause_count = weighted_choice(rng, JOINT_STRUCTURAL_WEIGHTS)
    length_bin, target_word_count = _sample_length(rng, difficulty)
    subtype_pool = TARGET_SUBTYPES[primary_target]
    return {
        "item_id": f"structure-v01-{seed:016x}-{order:02d}",
        "order": order,
        "section": "Structure",
        "primary_target": primary_target,
        "subtype": rng.choice(subtype_pool),
        "difficulty": difficulty,
        "clause_count": clause_count,
        "sentence_length_bin": length_bin,
        "target_word_count": target_word_count,
    }


def build_plan(seed: int) -> dict[str, Any]:
    """Build the complete replayable 15-item Structure plan without a model."""

    _validate_seed(seed)
    rng = random.Random(seed)
    plan = {
        "schema_version": "structure-plan-v0.1",
        "plan_id": f"structure-plan-v0.1-{seed:016x}",
        "version": STRUCTURE_VERSION,
        "seed": seed,
        "question_count": QUESTION_COUNT,
        "items": [_plan_item(rng, seed, order) for order in range(1, QUESTION_COUNT + 1)],
    }
    errors = schema_errors(plan, load_schema(PLAN_SCHEMA_PATH))
    if errors:
        raise ValueError("internal Structure planner output failed schema validation: " + "; ".join(errors))
    return plan


def plan_for_seed(seed: int) -> dict[str, Any]:
    """Compatibility alias for callers that name the operation explicitly."""

    return build_plan(seed)
