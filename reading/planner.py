"""Deterministic planning for the isolated Reading contracts.

The v0.1 planner is retained for the historical five-question smoke path.
The current planner (``build_plan``) uses only the derived profile committed
in ``analysis/reading_v0_2_empirical_profile.json``.  It never calls a model.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from shared.schema_validation import load_schema, schema_errors

from .difficulty import plan_difficulty_profile


ALLOWED_DOMAINS = (
    "biology",
    "geology",
    "astronomy",
    "anthropology",
    "history",
    "ecology",
    "technology",
    "earth science",
    "archaeology",
    "psychology",
    "sociology",
    "linguistics",
    "economics",
    "geography",
    "architecture",
    "art history",
    "visual arts",
    "music",
    "communication",
    "education",
    "environmental science",
)
QUESTION_TYPES = (
    "DETAIL",
    "VOCABULARY_IN_CONTEXT",
    "INFERENCE",
    "MAIN_IDEA",
    "REFERENCE",
)
QUESTION_SUBTYPES = (
    "DIRECT_FACTUAL_DETAIL",
    "PARAPHRASED_FACTUAL_DETAIL",
    "NEGATIVE_EXCEPT_DETAIL",
    "LOCAL_INFERENCE",
    "CROSS_IDEA_INFERENCE",
    "RHETORICAL_PURPOSE",
    "VOCABULARY_CONTEXT_MEANING",
    "PASSAGE_MAIN_IDEA",
    "ANTECEDENT_REFERENCE",
)
QUESTION_SUBTYPE_COMPATIBILITY = {
    "DETAIL": frozenset({
        "DIRECT_FACTUAL_DETAIL",
        "PARAPHRASED_FACTUAL_DETAIL",
        "NEGATIVE_EXCEPT_DETAIL",
    }),
    "VOCABULARY_IN_CONTEXT": frozenset({"VOCABULARY_CONTEXT_MEANING"}),
    "INFERENCE": frozenset({"LOCAL_INFERENCE", "CROSS_IDEA_INFERENCE", "RHETORICAL_PURPOSE"}),
    "MAIN_IDEA": frozenset({"PASSAGE_MAIN_IDEA"}),
    "REFERENCE": frozenset({"ANTECEDENT_REFERENCE"}),
}
PLAN_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reading_plan.schema.json"
PLAN_V02_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reading_plan_v0_2.schema.json"
EMPIRICAL_PROFILE_PATH = Path(__file__).resolve().parents[1] / "analysis" / "reading_v0_2_empirical_profile.json"
PLAN_SCHEMA = load_schema(PLAN_SCHEMA_PATH)
PLAN_V02_SCHEMA = load_schema(PLAN_V02_SCHEMA_PATH)


@dataclass(frozen=True)
class EmpiricalPassageComposition:
    """One observed passage-level composition from the v0.2 profile."""

    target_words: int
    question_count: int
    question_type_counts: tuple[tuple[str, int], ...]

    def counts(self) -> dict[str, int]:
        return dict(self.question_type_counts)


def _load_empirical_observations(profile_path: Path) -> tuple[EmpiricalPassageComposition, ...]:
    """Load the persisted official-derived passage observations.

    The Planner samples the observations themselves rather than fitting a
    parametric distribution. Failing closed here prevents a missing or
    malformed profile from silently restoring an unsupported fallback policy.
    """

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not load Reading empirical profile: {profile_path}") from exc

    measurements = profile.get("passage_measurements") if isinstance(profile, dict) else None
    if not isinstance(measurements, list) or not measurements:
        raise RuntimeError("Reading empirical profile must contain passage_measurements")

    observations: list[EmpiricalPassageComposition] = []
    for index, measurement in enumerate(measurements, 1):
        if not isinstance(measurement, dict):
            raise RuntimeError(f"Reading empirical profile measurement {index} must be an object")
        target_words = measurement.get("passage_word_count_approx")
        question_count = measurement.get("question_count")
        raw_counts = measurement.get("question_type_counts")
        if isinstance(target_words, bool) or not isinstance(target_words, int) or target_words < 0:
            raise RuntimeError(
                "Reading empirical profile contains an invalid passage length "
                f"at passage_measurements[{index - 1}]"
            )
        if isinstance(question_count, bool) or not isinstance(question_count, int) or question_count < 1:
            raise RuntimeError(f"Reading empirical profile contains an invalid question count at measurement {index}")
        if not isinstance(raw_counts, dict) or set(raw_counts) != set(QUESTION_TYPES):
            raise RuntimeError(f"Reading empirical profile has invalid question_type_counts at measurement {index}")
        counts: dict[str, int] = {}
        for question_type in QUESTION_TYPES:
            count = raw_counts[question_type]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise RuntimeError(f"Reading empirical profile has invalid {question_type} count at measurement {index}")
            counts[question_type] = count
        if sum(counts.values()) == 0:
            raise RuntimeError(f"Reading empirical profile has no classified questions at measurement {index}")
        # One source row has an abstract classification residual of one
        # question. Keep the observed row and let the deterministic adapter
        # reconcile it to the row's declared total instead of inventing a
        # subtype or rejecting the whole profile.
        observations.append(EmpiricalPassageComposition(
            target_words=target_words,
            question_count=question_count,
            question_type_counts=tuple((question_type, counts[question_type]) for question_type in QUESTION_TYPES),
        ))
    return tuple(observations)


EMPIRICAL_PASSAGE_COMPOSITIONS = _load_empirical_observations(EMPIRICAL_PROFILE_PATH)
EMPIRICAL_PASSAGE_LENGTHS = tuple(observation.target_words for observation in EMPIRICAL_PASSAGE_COMPOSITIONS)

# These are derived from the small 20-passage B-E measurement, not copied
# official content. Keeping them profile-derived makes replay behavior easy to
# audit and prevents a second aggregate calibration from drifting separately.
QUESTION_COUNT_WEIGHTS = tuple(
    sorted(Counter(observation.question_count for observation in EMPIRICAL_PASSAGE_COMPOSITIONS).items())
)


def _load_empirical_passage_lengths(profile_path: Path) -> tuple[int, ...]:
    """Compatibility wrapper for callers that only need length observations."""

    return tuple(observation.target_words for observation in _load_empirical_observations(profile_path))


def _load_empirical_aggregate_counts(profile_path: Path) -> tuple[tuple[str, int], ...]:
    """Load the profile's published aggregate type totals."""

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not load Reading empirical profile: {profile_path}") from exc
    derived = profile.get("derived_profile", {}).get("question_type_counts") if isinstance(profile, dict) else None
    if not isinstance(derived, dict) or set(derived) != set(QUESTION_TYPES):
        raise RuntimeError("Reading empirical profile must contain derived question_type_counts")
    counts: list[tuple[str, int]] = []
    for question_type in QUESTION_TYPES:
        value = derived[question_type]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"Reading empirical profile has invalid aggregate count for {question_type}")
        counts.append((question_type, value))
    return tuple(counts)


QUESTION_TYPE_WEIGHTS = _load_empirical_aggregate_counts(EMPIRICAL_PROFILE_PATH)
EMPIRICAL_MAX_QUESTION_TYPE_COUNTS = {
    question_type: max(observation.counts()[question_type] for observation in EMPIRICAL_PASSAGE_COMPOSITIONS)
    for question_type in QUESTION_TYPES
}


def _weighted_choice(rng: random.Random, weighted_values: tuple[tuple[Any, int], ...]) -> Any:
    values = [value for value, _weight in weighted_values]
    weights = [weight for _value, weight in weighted_values]
    return rng.choices(values, weights=weights, k=1)[0]


def adapt_question_type_counts(
    source_counts: Mapping[str, int],
    question_count: int,
    rng: random.Random,
) -> dict[str, int]:
    """Adapt one observed composition to a requested total.

    Exact observed rows are returned unchanged. When a caller requests a
    different total (for example after a future profile update), additions use
    empirical marginal weights and removals are sampled from the observed
    counts. ``MAIN_IDEA`` is capped at the observed maximum of one; this is a
    structural guard, not a one-of-each rule.
    """

    if isinstance(question_count, bool) or not isinstance(question_count, int) or question_count < 1:
        raise ValueError("question_count must be a positive integer")
    if set(source_counts) != set(QUESTION_TYPES):
        raise ValueError("source_counts must contain exactly the empirical primary question types")
    counts = {}
    for question_type in QUESTION_TYPES:
        count = source_counts[question_type]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"invalid source count for {question_type}: {count!r}")
        counts[question_type] = min(count, EMPIRICAL_MAX_QUESTION_TYPE_COUNTS[question_type])
    if sum(counts.values()) == 0:
        raise ValueError("source_counts must contain at least one question")

    while sum(counts.values()) > question_count:
        candidates = [question_type for question_type in QUESTION_TYPES if counts[question_type] > 0]
        removed = _weighted_choice(rng, tuple((question_type, counts[question_type]) for question_type in candidates))
        counts[removed] -= 1

    while sum(counts.values()) < question_count:
        candidates = [
            question_type
            for question_type in QUESTION_TYPES
            if question_type != "MAIN_IDEA" or counts[question_type] < 1
        ]
        added_weights = tuple(
            (question_type, weight)
            for question_type, weight in QUESTION_TYPE_WEIGHTS
            if question_type in candidates
        )
        added = _weighted_choice(rng, added_weights)
        counts[added] += 1
    return counts


def sample_question_type_counts(rng: random.Random, question_count: int) -> dict[str, int]:
    """Bootstrap an observed row and adapt it to ``question_count``."""

    observation = rng.choice(EMPIRICAL_PASSAGE_COMPOSITIONS)
    return adapt_question_type_counts(observation.counts(), question_count, rng)


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
    errors = schema_errors(plan, PLAN_SCHEMA)
    if errors:
        raise ValueError("internal planner output failed schema validation: " + "; ".join(errors))
    return plan


def build_plan_v02(seed: int, domain: str | None = None) -> dict[str, Any]:
    """Build a replayable variable-length v0.2 passage plan.

    Question count and type mix are sampled from the derived B-E profile. The
    type mix bootstraps a complete observed passage row before adapting it to
    the sampled total. ``question_plan`` remains an ordered compatibility
    representation, while ``question_type_counts`` is the canonical
    adherence contract for the v0.2.2 Generator.
    """

    _validate_seed_and_domain(seed, domain)
    rng = random.Random(seed)
    selected_domain = domain or rng.choice(ALLOWED_DOMAINS)
    target_words = rng.choice(EMPIRICAL_PASSAGE_LENGTHS)
    question_count = _weighted_choice(rng, QUESTION_COUNT_WEIGHTS)
    question_type_counts = sample_question_type_counts(rng, question_count)
    question_plan = [
        question_type
        for question_type in QUESTION_TYPES
        for _ in range(question_type_counts[question_type])
    ]
    rng.shuffle(question_plan)
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
        "difficulty_profile": plan_difficulty_profile(),
    }
    errors = schema_errors(plan, PLAN_V02_SCHEMA)
    if errors:
        raise ValueError("internal planner output failed schema validation: " + "; ".join(errors))
    return plan



def build_plan(seed: int, domain: str | None = None) -> dict[str, Any]:
    """Build the current v0.2 plan without an LLM invocation."""

    return build_plan_v02(seed, domain)
