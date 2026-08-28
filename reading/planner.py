"""Deterministic planning for the isolated Reading contracts.

The v0.1 planner is retained for the historical five-question smoke path.
The current planner (``build_plan``) uses only the derived profile committed
in ``analysis/reading_v0_2_empirical_profile.json``.  It never calls a model.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from shared.schema_validation import load_schema, schema_errors


ALLOWED_DOMAINS = (
    "biology",
    "geology",
    "astronomy",
    "anthropology",
    "history",
    "ecology",
    "technology",
    "earth science",
)
QUESTION_TYPES = (
    "DETAIL",
    "VOCABULARY_IN_CONTEXT",
    "INFERENCE",
    "MAIN_IDEA",
    "REFERENCE",
)
PLAN_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reading_plan.schema.json"
PLAN_V02_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reading_plan_v0_2.schema.json"
EMPIRICAL_PROFILE_PATH = Path(__file__).resolve().parents[1] / "analysis" / "reading_v0_2_empirical_profile.json"


def _load_empirical_passage_lengths(profile_path: Path) -> tuple[int, ...]:
    """Load the persisted official-derived passage length observations.

    The Planner samples the observations themselves rather than fitting a
    parametric distribution.  Failing closed here prevents a missing or
    malformed calibration profile from silently restoring an unsupported
    fallback target policy.
    """

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not load Reading empirical profile: {profile_path}") from exc

    measurements = profile.get("passage_measurements") if isinstance(profile, dict) else None
    if not isinstance(measurements, list) or not measurements:
        raise RuntimeError("Reading empirical profile must contain passage_measurements")

    lengths: list[int] = []
    for index, measurement in enumerate(measurements, 1):
        value = measurement.get("passage_word_count_approx") if isinstance(measurement, dict) else None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(
                "Reading empirical profile contains an invalid passage length "
                f"at passage_measurements[{index - 1}]"
            )
        lengths.append(value)
    return tuple(lengths)


EMPIRICAL_PASSAGE_LENGTHS = _load_empirical_passage_lengths(EMPIRICAL_PROFILE_PATH)

# These are derived from the small 20-passage B-E measurement, not copied
# official content.  Keeping the weights explicit makes replay behavior easy
# to audit and keeps the planner independent of runtime/model availability.
QUESTION_COUNT_WEIGHTS = (
    (7, 2),
    (8, 2),
    (9, 3),
    (10, 6),
    (11, 3),
    (12, 3),
    (14, 1),
)
QUESTION_TYPE_WEIGHTS = (
    ("DETAIL", 74),
    ("VOCABULARY_IN_CONTEXT", 63),
    ("INFERENCE", 27),
    ("MAIN_IDEA", 15),
    ("REFERENCE", 21),
)


def _weighted_choice(rng: random.Random, weighted_values: tuple[tuple[Any, int], ...]) -> Any:
    values = [value for value, _weight in weighted_values]
    weights = [weight for _value, weight in weighted_values]
    return rng.choices(values, weights=weights, k=1)[0]


def _validate_seed_and_domain(seed: int, domain: str | None) -> None:
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if domain is not None and domain not in ALLOWED_DOMAINS:
        raise ValueError(f"unsupported Reading domain: {domain!r}")


def passage_id_for_seed(seed: int) -> str:
    """Return the deterministic, Planner-owned Reading passage identity."""

    _validate_seed_and_domain(seed, None)
    return f"rc-{seed:08x}"


def build_plan_v01(seed: int, domain: str | None = None) -> dict[str, Any]:
    """Build the historical, fixed five-question v0.1 plan."""

    _validate_seed_and_domain(seed, domain)
    rng = random.Random(seed)
    selected_domain = domain or rng.choice(ALLOWED_DOMAINS)
    target_words = rng.choice((280, 300, 320))
    plan = {
        "schema_version": "reading-plan-v0.1",
        "plan_id": f"rp-{seed:08x}",
        "passage_id": passage_id_for_seed(seed),
        "seed": seed,
        "domain": selected_domain,
        "target_words": target_words,
        "target_paragraphs": 4,
        "question_plan": list(QUESTION_TYPES),
    }
    errors = schema_errors(plan, load_schema(PLAN_SCHEMA_PATH))
    if errors:
        raise ValueError("internal planner output failed schema validation: " + "; ".join(errors))
    return plan


def build_plan_v02(seed: int, domain: str | None = None) -> dict[str, Any]:
    """Build a replayable variable-length v0.2 passage plan.

    Question count and type mix are sampled from the derived B-E profile.  A
    type may repeat.  ``question_plan`` remains as an ordered compatibility
    representation, while ``question_type_counts`` is the canonical
    adherence contract for the v0.2.2 Generator.
    """

    _validate_seed_and_domain(seed, domain)
    rng = random.Random(seed)
    selected_domain = domain or rng.choice(ALLOWED_DOMAINS)
    target_words = rng.choice(EMPIRICAL_PASSAGE_LENGTHS)
    question_count = _weighted_choice(rng, QUESTION_COUNT_WEIGHTS)
    question_plan = [
        _weighted_choice(rng, QUESTION_TYPE_WEIGHTS)
        for _ in range(question_count)
    ]
    question_type_counts = {
        question_type: Counter(question_plan)[question_type]
        for question_type in QUESTION_TYPES
    }
    plan = {
        "schema_version": "reading-plan-v0.2",
        "plan_id": f"rp-v02-{seed:08x}",
        "passage_id": passage_id_for_seed(seed),
        "seed": seed,
        "domain": selected_domain,
        "target_words": target_words,
        "target_paragraphs": 4,
        "question_count": question_count,
        "question_plan": question_plan,
        "question_type_counts": question_type_counts,
    }
    errors = schema_errors(plan, load_schema(PLAN_V02_SCHEMA_PATH))
    if errors:
        raise ValueError("internal planner output failed schema validation: " + "; ".join(errors))
    return plan



def build_plan(seed: int, domain: str | None = None) -> dict[str, Any]:
    """Build the current v0.2 plan without an LLM invocation."""

    return build_plan_v02(seed, domain)
