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
PROFILE_PATH = Path(__file__).resolve().parent / "profile.json"
PLAN_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "plan.schema.json"


@lru_cache(maxsize=1)
def load_profile() -> dict[str, Any]:
    with PROFILE_PATH.open(encoding="utf-8") as handle:
        profile = json.load(handle)
    if not isinstance(profile, dict):
        raise ValueError("Structure profile must be a JSON object")
    return profile


def _mapping(name: str) -> dict[str, int]:
    value = load_profile().get(name)
    if not isinstance(value, dict) or not value:
        raise ValueError(f"Structure profile field {name!r} must be a non-empty object")
    result: dict[str, int] = {}
    for key, weight in value.items():
        if not isinstance(key, str) or not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
            raise ValueError(f"Structure profile field {name!r} contains an invalid weight")
        if weight:
            result[key] = weight
    if not result:
        raise ValueError(f"Structure profile field {name!r} has no positive weights")
    return result


PRIMARY_TARGET_WEIGHTS = _mapping("primary_target_weights")
DIFFICULTY_WEIGHTS = _mapping("difficulty_weights")
CLAUSE_COUNT_WEIGHTS = {int(key): value for key, value in _mapping("clause_count_weights").items()}
VOCABULARY_DOMAINS = tuple(load_profile().get("vocabulary_domains", ()))
TARGET_SUBTYPES = load_profile().get("target_subtypes", {})
LENGTH_BINS = tuple(load_profile().get("sentence_length_bins", ()))


def _validate_profile() -> None:
    if sum(PRIMARY_TARGET_WEIGHTS.values()) != 75:
        raise ValueError("Structure primary_target weights must sum to 75")
    if sum(DIFFICULTY_WEIGHTS.values()) != 75:
        raise ValueError("Structure difficulty weights must sum to 75")
    if sum(CLAUSE_COUNT_WEIGHTS.values()) != 75:
        raise ValueError("Structure clause-count weights must sum to 75")
    if not VOCABULARY_DOMAINS or any(not isinstance(domain, str) or not domain.strip() for domain in VOCABULARY_DOMAINS):
        raise ValueError("Structure profile must contain a usable vocabulary-domain pool")
    if len(LENGTH_BINS) != 4:
        raise ValueError("Structure profile must contain four sentence-length bins")
    for length_bin in LENGTH_BINS:
        if not isinstance(length_bin, dict):
            raise ValueError("Structure sentence-length bins must be objects")
        required = {"label", "minimum", "maximum", "weight"}
        if not required.issubset(length_bin):
            raise ValueError("Structure sentence-length bin is missing a required field")
        if length_bin["minimum"] > length_bin["maximum"] or length_bin["weight"] <= 0:
            raise ValueError("Structure sentence-length bin has invalid bounds or weight")
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


def _sample_length(rng: random.Random) -> tuple[dict[str, Any], int]:
    length_bin = weighted_choice(rng, {entry["label"]: entry["weight"] for entry in LENGTH_BINS})
    selected = next(entry for entry in LENGTH_BINS if entry["label"] == length_bin)
    word_count = rng.randint(selected["minimum"], selected["maximum"])
    return dict(selected), word_count


def _plan_item(rng: random.Random, seed: int, order: int) -> dict[str, Any]:
    primary_target = weighted_choice(rng, PRIMARY_TARGET_WEIGHTS)
    difficulty = weighted_choice(rng, DIFFICULTY_WEIGHTS)
    clause_count = weighted_choice(rng, CLAUSE_COUNT_WEIGHTS)
    length_bin, target_word_count = _sample_length(rng)
    subtype_pool = TARGET_SUBTYPES[primary_target]
    domain = rng.choice(VOCABULARY_DOMAINS)
    return {
        "item_id": f"structure-v01-{seed:016x}-{order:02d}",
        "order": order,
        "section": "Structure",
        "primary_target": primary_target,
        "subtype": rng.choice(subtype_pool),
        "difficulty": difficulty,
        "vocabulary_domain": domain,
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
