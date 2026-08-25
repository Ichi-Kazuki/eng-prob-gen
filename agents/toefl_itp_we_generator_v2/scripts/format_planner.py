"""WE v2.1 format planning and span-selection policy.

This module owns only the format layer.  It does not generate prose, mutate
grammar, or decide whether an error is valid.  The official 125-item artifact
is read as the empirical source on every planning call; probabilities are
therefore derived from observed counts rather than copied from hand-tuned
constants.
"""

from __future__ import annotations

import itertools
import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[3]
OFFICIAL_SOURCE = ROOT / "analysis" / "we_format" / "written_expression_format_official.json"
TOKEN_RE = re.compile(r"[\w]+(?:['-][\w]+)*", re.UNICODE)
LABELS = ("A", "B", "C", "D")
SPAN_TYPES = {"SINGLE_WORD", "SHORT_PHRASE", "CLAUSE_OR_CLAUSE_LIKE"}
NORMAL_MAX_SPAN_WORDS = 4
CLAUSE_MARKERS = {
    "although", "because", "if", "since", "that", "though", "unless",
    "until", "when", "where", "while", "which", "who", "whom", "whose",
}
BOUNDARY_WORDS = {"and", "or", "but", "nor", "of", "to", "for", "in", "on", "at", "by", "with"}


@dataclass(frozen=True)
class SentenceLengthPlan:
    target: int
    lower: int
    upper: int
    source: str = "official.items[].sentence_word_count"

    @property
    def region(self) -> str:
        if self.target <= 10:
            return "<=10"
        if self.target <= 15:
            return "11-15"
        if self.target <= 20:
            return "16-20"
        if self.target <= 25:
            return "21-25"
        if self.target <= 30:
            return "26-30"
        return "31+"

    def contains(self, realized_word_count: int) -> bool:
        return self.lower <= realized_word_count <= self.upper


@dataclass(frozen=True)
class CorrectSpanPlan:
    span_type: str
    target_word_count: int
    source: str = "official.items[].correct_span_type / correct_span_word_count"


@dataclass(frozen=True)
class FormatPlan:
    sentence: SentenceLengthPlan
    correct_span: CorrectSpanPlan
    gap_targets: dict[str, int]
    distractor_word_counts: tuple[int, int, int]
    answer_position: str


@dataclass(frozen=True)
class SpanCandidate:
    start: int
    end: int
    text: str
    word_count: int
    span_type: str
    lexical_quality: float = 0.0

    @property
    def is_single_word(self) -> bool:
        return self.word_count == 1


@dataclass(frozen=True)
class SpanSelection:
    spans: tuple[SpanCandidate, ...]
    correct_index: int
    correct_answer: str
    score: float
    candidate_scope: str = "whole_sentence"

    @property
    def gaps(self) -> tuple[int, int, int]:
        return tuple(
            self.spans[index + 1].start - self.spans[index].end
            for index in range(3)
        )


class SpanSelectionError(ValueError):
    """Raised when a safe four-span set cannot be selected."""


def _read_official(source: Path) -> dict[str, Any]:
    return json.loads(source.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def official_profile(source_text: str = str(OFFICIAL_SOURCE)) -> dict[str, Any]:
    """Derive all sampling observations from the official artifact."""

    source = Path(source_text)
    data = _read_official(source)
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("official format source must contain a non-empty items array")

    sentence_values = [int(item["sentence_word_count"]) for item in items]
    correct_types = [str(item["correct_span_type"]) for item in items]
    correct_lengths = [int(item["correct_span_word_count"]) for item in items]
    correct_positions = [str(item["correct_answer"]) for item in items]
    gap_values = {
        key: [int(item[key]) for item in items]
        for key in ("gap_A_B", "gap_B_C", "gap_C_D")
    }
    span_values = [
        int(span["word_count"])
        for item in items
        for span in item.get("marked_spans", [])
    ]
    type_to_lengths: dict[str, list[int]] = {name: [] for name in SPAN_TYPES}
    for span_type, length in zip(correct_types, correct_lengths):
        if span_type not in SPAN_TYPES:
            raise ValueError(f"unexpected official correct span type: {span_type}")
        type_to_lengths[span_type].append(length)

    return {
        "source": str(source),
        "sentence_values": sentence_values,
        "correct_types": correct_types,
        "correct_lengths": correct_lengths,
        "correct_positions": correct_positions,
        "gap_values": gap_values,
        "span_values": span_values,
        "counts": {
            "sentence_word_count": dict(Counter(sentence_values)),
            "correct_span_type": dict(Counter(correct_types)),
            "correct_span_word_count": dict(Counter(correct_lengths)),
            "correct_answer": dict(Counter(correct_positions)),
            "span_word_count": dict(Counter(span_values)),
            "gap_A_B": dict(Counter(gap_values["gap_A_B"])),
            "gap_B_C": dict(Counter(gap_values["gap_B_C"])),
            "gap_C_D": dict(Counter(gap_values["gap_C_D"])),
        },
        "correct_lengths_by_type": type_to_lengths,
        "item_geometry": [
            {
                "sentence_word_count": int(item["sentence_word_count"]),
                "total_marked_words": int(item["marked_token_total"]),
                "coverage": float(item["marked_coverage_ratio"]),
                "unmarked_context": int(item["unmarked_word_count"]),
                "mean_span_length": float(item["mean_marked_span_length"]),
                "max_span_length": int(item["max_marked_span_length"]),
            }
            for item in items
        ],
    }


def get_official_profile(source: Path = OFFICIAL_SOURCE) -> dict[str, Any]:
    """Return a defensive, cached view of the official empirical profile."""

    return official_profile(str(source.resolve()))


def empirical_probabilities(counts: dict[Any, int]) -> dict[Any, float]:
    total = sum(counts.values())
    if total <= 0:
        raise ValueError("cannot derive probabilities from empty counts")
    return {key: value / total for key, value in counts.items()}


def _sample_observation(values: Sequence[Any], rng: random.Random) -> Any:
    if not values:
        raise ValueError("cannot sample an empty empirical observation list")
    return values[rng.randrange(len(values))]


def sample_sentence_length_plan(
    rng: random.Random,
    profile: dict[str, Any] | None = None,
    tolerance: int = 2,
) -> SentenceLengthPlan:
    """Sample one observed official sentence length and make a conformance range.

    The target is an empirical draw from the 125 official observations.  The
    range is deliberately a small tolerance around that draw, so realization
    is checked against the plan instead of being padded after the fact.
    """

    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    profile = profile or get_official_profile()
    target = int(_sample_observation(profile["sentence_values"], rng))
    return SentenceLengthPlan(
        target=target,
        lower=max(1, target - tolerance),
        upper=target + tolerance,
    )


def sample_correct_span_plan(
    rng: random.Random,
    profile: dict[str, Any] | None = None,
) -> CorrectSpanPlan:
    """Sample correct-span type and length from official observations."""

    profile = profile or get_official_profile()
    span_type = str(_sample_observation(profile["correct_types"], rng))
    word_count = int(_sample_observation(profile["correct_lengths_by_type"][span_type], rng))
    return CorrectSpanPlan(span_type=span_type, target_word_count=word_count)


def sample_format_plan(rng: random.Random, profile: dict[str, Any] | None = None) -> FormatPlan:
    """Sample the complete format plan from empirical observations."""

    profile = profile or get_official_profile()
    sentence = sample_sentence_length_plan(rng, profile)
    correct_span = sample_correct_span_plan(rng, profile)
    gap_targets = {
        key: int(_sample_observation(values, rng))
        for key, values in profile["gap_values"].items()
    }
    distractors = tuple(
        int(_sample_observation([value for value in profile["span_values"] if value <= 4], rng))
        for _ in range(3)
    )
    # The official marked-span sample contains no 5+ word spans.  A normal
    # v2.1 plan therefore never asks for one, even when grammar could justify
    # a longer syntactic unit; it is excluded at sampling time, not shortened.
    answer_position = str(_sample_observation(profile["correct_positions"], rng))
    return FormatPlan(sentence, correct_span, gap_targets, distractors, answer_position)


def plan_summary(plan: FormatPlan, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expose derived counts/probabilities for telemetry and unit tests."""

    profile = profile or get_official_profile()
    return {
        "sentence": {
            "target": plan.sentence.target,
            "lower": plan.sentence.lower,
            "upper": plan.sentence.upper,
            "region": plan.sentence.region,
            "source": plan.sentence.source,
        },
        "correct_span": {
            "type": plan.correct_span.span_type,
            "target_word_count": plan.correct_span.target_word_count,
            "source": plan.correct_span.source,
        },
        "gap_targets": dict(plan.gap_targets),
        "distractor_word_counts": list(plan.distractor_word_counts),
        "answer_position": plan.answer_position,
        "derived_empirical_counts": {
            "correct_span_type": profile["counts"]["correct_span_type"],
            "correct_answer": profile["counts"]["correct_answer"],
            "span_word_count": profile["counts"]["span_word_count"],
            "gap_A_B": profile["counts"]["gap_A_B"],
            "gap_B_C": profile["counts"]["gap_B_C"],
            "gap_C_D": profile["counts"]["gap_C_D"],
        },
    }


def lexical_tokens(sentence: str) -> list[re.Match[str]]:
    return list(TOKEN_RE.finditer(sentence))


def _span_text(sentence: str, token_matches: Sequence[re.Match[str]], start: int, end: int) -> str:
    return sentence[token_matches[start].start(): token_matches[end - 1].end()]


def _looks_clause_like(text: str, words: Sequence[str]) -> bool:
    lower = [word.lower() for word in words]
    return len(words) >= 2 and (
        lower[0] in CLAUSE_MARKERS
        or any(word in {"is", "are", "was", "were", "be", "been", "has", "have", "had", "does", "do", "did"} for word in lower)
    )


def _lexical_quality(sentence: str, matches: Sequence[re.Match[str]], start: int, end: int) -> float:
    words = [match.group(0).lower() for match in matches[start:end]]
    quality = 1.0
    if len(words) == 1:
        quality += 0.35
    elif len(words) == 2:
        quality += 0.50
    if words[0] in {"and", "or", "but", "nor"}:
        quality -= 0.35
    if words[-1] in BOUNDARY_WORDS:
        quality -= 0.40
    # Do not make proximity to the correct span part of candidate quality.
    # Whole-sentence enumeration and geometry scoring decide placement.
    return quality


def enumerate_candidate_spans(sentence: str, max_words: int = 4) -> list[SpanCandidate]:
    """Enumerate local lexical candidates across the entire sentence.

    The normal candidate set intentionally stops at four words.  It is a
    format policy, not a grammar prohibition; a grammar-required larger locus
    must be handled as an explicit exception outside normal planning.
    """

    if max_words < 1:
        raise ValueError("max_words must be positive")
    matches = lexical_tokens(sentence)
    candidates: list[SpanCandidate] = []
    for start in range(len(matches)):
        for end in range(start + 1, min(len(matches), start + max_words) + 1):
            between = sentence[matches[start].end():matches[end - 1].start()]
            if re.search(r"[,;:!?]", between):
                continue
            words = [match.group(0) for match in matches[start:end]]
            count = len(words)
            span_type = "SINGLE_WORD" if count == 1 else (
                "CLAUSE_OR_CLAUSE_LIKE" if _looks_clause_like(" ".join(words), words) else "SHORT_PHRASE"
            )
            candidates.append(SpanCandidate(
                start=start,
                end=end,
                text=_span_text(sentence, matches, start, end),
                word_count=count,
                span_type=span_type,
                lexical_quality=_lexical_quality(sentence, matches, start, end),
            ))
    return candidates


def _resolve_correct_span(
    sentence: str,
    correct_span: str | tuple[int, int] | SpanCandidate,
    desired_type: str | None,
    *,
    long_span_rationale: str | None = None,
) -> SpanCandidate:
    rationale = long_span_rationale.strip() if isinstance(long_span_rationale, str) else ""
    max_words = len(lexical_tokens(sentence)) if rationale else NORMAL_MAX_SPAN_WORDS
    candidates = enumerate_candidate_spans(sentence, max_words=max_words)
    if isinstance(correct_span, SpanCandidate):
        selected = correct_span
    elif isinstance(correct_span, tuple):
        selected = next((item for item in candidates if (item.start, item.end) == correct_span), None)
        if selected is None:
            raise SpanSelectionError("correct span token range is not a normal candidate")
    else:
        matches = [item for item in candidates if item.text == correct_span]
        if len(matches) != 1:
            raise SpanSelectionError("correct span text must align uniquely to one lexical candidate")
        selected = matches[0]
    if selected.word_count > NORMAL_MAX_SPAN_WORDS and not rationale:
        raise SpanSelectionError(
            "5+ word correct spans require a non-empty long_span_rationale"
        )
    if desired_type in SPAN_TYPES and desired_type != selected.span_type:
        # Preserve the grammar-provided locus.  Never expand or shrink it just
        # to satisfy a sampled type; the caller records this as an override.
        return SpanCandidate(
            start=selected.start,
            end=selected.end,
            text=selected.text,
            word_count=selected.word_count,
            span_type=selected.span_type,
            lexical_quality=selected.lexical_quality,
        )
    return selected


def _non_overlapping(spans: Sequence[SpanCandidate]) -> bool:
    ordered = sorted(spans, key=lambda span: span.start)
    return all(left.end <= right.start for left, right in zip(ordered, ordered[1:]))


def _unique_substring(sentence: str, text: str) -> bool:
    first = sentence.find(text)
    return first >= 0 and sentence.find(text, first + 1) < 0


def _gaps(spans: Sequence[SpanCandidate]) -> tuple[int, int, int]:
    ordered = sorted(spans, key=lambda span: span.start)
    return tuple(ordered[index + 1].start - ordered[index].end for index in range(3))


def _mean_stdev(values: Iterable[float]) -> tuple[float, float]:
    values = list(values)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, math.sqrt(variance) or 1.0


def score_span_set(
    sentence_word_count: int,
    spans: Sequence[SpanCandidate],
    correct_span: SpanCandidate,
    plan: FormatPlan,
    profile: dict[str, Any] | None = None,
) -> float:
    """Score geometry as a soft official-distance preference.

    The score includes all requested geometry terms.  It is not a band-pass
    optimizer: grammar-selected loci remain fixed, and bands are still
    calculated later by the existing deterministic validator.
    """

    if len(spans) != 4 or not _non_overlapping(spans):
        return float("inf")
    ordered = tuple(sorted(spans, key=lambda span: span.start))
    gaps = _gaps(ordered)
    if any(gap < 1 for gap in gaps):
        return float("inf")
    profile = profile or get_official_profile()
    total_marked = sum(span.word_count for span in ordered)
    coverage = total_marked / sentence_word_count
    unmarked = sentence_word_count - total_marked
    mean_span = total_marked / 4
    max_span = max(span.word_count for span in ordered)
    correct_index = ordered.index(correct_span)
    geometry_fields = (
        "sentence_word_count", "total_marked_words", "coverage",
        "unmarked_context", "mean_span_length", "max_span_length",
    )
    target_geometry: dict[str, float] = {}
    scales: dict[str, float] = {}
    for field in geometry_fields:
        mean, stdev = _mean_stdev(item[field] for item in profile["item_geometry"])
        target_geometry[field] = mean
        scales[field] = stdev
    actual = {
        "sentence_word_count": sentence_word_count,
        "total_marked_words": total_marked,
        "coverage": coverage,
        "unmarked_context": unmarked,
        "mean_span_length": mean_span,
        "max_span_length": max_span,
    }
    score = sum(abs(actual[key] - target_geometry[key]) / scales[key] for key in actual)
    # Keep the sampled plan as a soft preference while retaining the full
    # Official item-level geometry as the primary reference.
    plan_total = plan.correct_span.target_word_count + sum(plan.distractor_word_counts)
    score += 0.25 * abs(total_marked - plan_total)
    for key, gap in zip(("gap_A_B", "gap_B_C", "gap_C_D"), gaps):
        gap_mean, gap_stdev = _mean_stdev(profile["gap_values"][key])
        score += 0.45 * abs(gap - plan.gap_targets[key]) / gap_stdev
        score += 0.15 * abs(gap - gap_mean) / gap_stdev
    if correct_span.span_type != plan.correct_span.span_type:
        score += 0.80
    if correct_index != LABELS.index(plan.answer_position):
        score += 0.25
    score -= 0.05 * sum(span.lexical_quality for span in ordered if span != correct_span)
    return score


def select_span_set(
    sentence: str,
    correct_span: str | tuple[int, int] | SpanCandidate,
    plan: FormatPlan,
    rng: random.Random | None = None,
    profile: dict[str, Any] | None = None,
    max_distractor_candidates: int = 56,
    *,
    long_span_rationale: str | None = None,
) -> SpanSelection:
    """Select A/B/C/D from whole-sentence candidates with normal spacing.

    The grammar-provided correct locus is authoritative even when its type
    differs from the independently sampled format type.  A 5+ word correct
    locus is accepted only when ``long_span_rationale`` documents the grammar
    exception; distractors remain capped at the normal four words.
    """

    rng = rng or random.Random(0)
    profile = profile or get_official_profile()
    anchor = _resolve_correct_span(
        sentence,
        correct_span,
        plan.correct_span.span_type,
        long_span_rationale=long_span_rationale,
    )
    all_candidates = enumerate_candidate_spans(sentence, max_words=NORMAL_MAX_SPAN_WORDS)
    distractors = [
        candidate for candidate in all_candidates
        if (candidate.start, candidate.end) != (anchor.start, anchor.end)
        and candidate.word_count <= NORMAL_MAX_SPAN_WORDS
        and candidate.end <= len(lexical_tokens(sentence))
        and _unique_substring(sentence, candidate.text)
    ]
    # Keep the pool sentence-wide and favour one/two-word local units.  The
    # pool is shuffled before ranking so equal-quality positions do not lock
    # the correct answer to a fixed A/B/C/D slot.
    rng.shuffle(distractors)
    distractors.sort(key=lambda span: (
        0 if span.word_count == 1 else 1 if span.word_count == 2 else 2,
        -span.lexical_quality,
    ))
    distractors = distractors[:max_distractor_candidates]

    best: tuple[float, tuple[SpanCandidate, ...]] | None = None
    for combo in itertools.combinations(distractors, 3):
        spans = tuple(sorted((anchor, *combo), key=lambda span: span.start))
        if not _non_overlapping(spans):
            continue
        gaps = _gaps(spans)
        # Official observed gaps start at one.  A zero-gap set is not a normal
        # v2.1 candidate and is rejected before scoring.
        if any(gap < 1 for gap in gaps):
            continue
        score = score_span_set(len(lexical_tokens(sentence)), spans, anchor, plan, profile)
        if best is None or score < best[0]:
            best = (score, spans)
    if best is None:
        raise SpanSelectionError("no whole-sentence four-span set satisfies normal nonzero-gap policy")
    selected = best[1]
    correct_index = selected.index(anchor)
    return SpanSelection(
        spans=selected,
        correct_index=correct_index,
        correct_answer=LABELS[correct_index],
        score=best[0],
    )


def pre_emission_checks(
    sentence: str,
    spans: Sequence[SpanCandidate],
    plan: FormatPlan,
    correct_span: SpanCandidate,
    *,
    grammar_type_override: bool = True,
    long_span_rationale: str | None = None,
) -> dict[str, Any]:
    """Deterministically check plan/realization conformance before emission.

    Grammar span type is authoritative by default because the sampled format
    type is independent of the grammar-required locus.  The strict
    ``grammar_type_override=False`` mode remains available for diagnostics.
    A long-span exception is valid only for the selected correct span and only
    with a non-empty rationale.
    """

    word_count = len(lexical_tokens(sentence))
    ordered = tuple(sorted(spans, key=lambda span: span.start))
    lengths = [span.word_count for span in ordered]
    gaps = _gaps(ordered) if len(ordered) == 4 else ()
    total_marked = sum(lengths)
    coverage = total_marked / word_count if word_count else 1.0
    errors: list[str] = []
    warnings: list[str] = []
    if not plan.sentence.contains(word_count):
        errors.append(
            f"realized clean sentence length {word_count} is outside planned range "
            f"{plan.sentence.lower}-{plan.sentence.upper}"
        )
    if len(ordered) != 4:
        errors.append("exactly four spans are required")
    if len(set((span.start, span.end) for span in ordered)) != len(ordered):
        errors.append("span ranges must be unique")
    if not _non_overlapping(ordered):
        errors.append("spans overlap or are out of order")
    if any(length < 1 for length in lengths):
        errors.append("all spans must contain lexical tokens")
    rationale = long_span_rationale.strip() if isinstance(long_span_rationale, str) else ""
    long_spans = [span for span in ordered if span.word_count > NORMAL_MAX_SPAN_WORDS]
    if long_spans:
        if (
            len(long_spans) == 1
            and long_spans[0] == correct_span
            and rationale
        ):
            warnings.append(
                "grammar-required long correct span accepted under explicit rationale"
            )
        else:
            errors.append(
                "5+ word spans require a non-empty long_span_rationale for the correct span"
            )
    if gaps and any(gap < 1 for gap in gaps):
        errors.append("zero-gap adjacency is disallowed in normal v2.1 planning")
    if coverage >= 1.0:
        errors.append("100% marked coverage is disallowed in normal v2.1 planning")
    if word_count - total_marked <= 0:
        errors.append("unmarked context must remain positive")
    actual_type = ordered[ordered.index(correct_span)].span_type if correct_span in ordered else None
    if actual_type is None:
        errors.append("correct span must be one of the selected spans")
    elif actual_type != plan.correct_span.span_type:
        if grammar_type_override:
            warnings.append(
                f"grammar locus retained as {actual_type}; sampled type {plan.correct_span.span_type} was not forced"
            )
        else:
            errors.append(
                f"correct span type {actual_type} does not match sampled plan {plan.correct_span.span_type}"
            )
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "exceptions": {
            "long_span_rationale": rationale or None,
        },
        "metrics": {
            "sentence_word_count": word_count,
            "span_word_counts": lengths,
            "total_marked_words": total_marked,
            "coverage": round(coverage, 4),
            "unmarked_context": word_count - total_marked,
            "gaps": list(gaps),
            "correct_span_type": actual_type,
        },
    }
