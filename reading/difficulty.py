"""Deterministic structural-difficulty proxies for Reading v0.2.

This module deliberately does not claim psychometric equivalence with TOEFL
ITP. It exposes a stable calibration interface now, while official-item
feature measurements and human response data can replace the provisional
guardrails later without changing Planner/diagnostics call sites.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DIFFICULTY_PROFILE_PATH = ROOT / "analysis" / "reading_v0_2_difficulty_profile.json"

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])(?:[\"')\]]*)\s+")

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "hers", "him", "his", "how", "if", "in", "into", "is", "it",
    "its", "may", "might", "more", "most", "not", "of", "on", "or", "our",
    "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "to", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "would", "you", "your",
})

_EVIDENCE_SCOPE_BY_SUBTYPE = {
    "DIRECT_FACTUAL_DETAIL": "LOCAL",
    "PARAPHRASED_FACTUAL_DETAIL": "LOCAL_TO_MULTI_SENTENCE",
    "NEGATIVE_EXCEPT_DETAIL": "LOCAL_TO_MULTI_SENTENCE",
    "LOCAL_INFERENCE": "LOCAL_TO_MULTI_SENTENCE",
    "CROSS_IDEA_INFERENCE": "DISTRIBUTED",
    "RHETORICAL_PURPOSE": "LOCAL_TO_MULTI_SENTENCE",
    "VOCABULARY_CONTEXT_MEANING": "LOCAL",
    "PASSAGE_MAIN_IDEA": "WHOLE_PASSAGE",
    "ANTECEDENT_REFERENCE": "LOCAL",
}

_INFERENCE_DEPTH_BY_SUBTYPE = {
    "LOCAL_INFERENCE": "LOCAL",
    "CROSS_IDEA_INFERENCE": "CROSS_IDEA",
    "RHETORICAL_PURPOSE": "RHETORICAL_PURPOSE",
}


def _load_profile(path: Path = DIFFICULTY_PROFILE_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not load Reading difficulty profile: {path}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("Reading difficulty profile must be an object")
    required = {
        "schema_version",
        "status",
        "target_band",
        "psychometric_equivalence",
        "dimensions",
        "guardrails",
    }
    if not required.issubset(raw):
        missing = ", ".join(sorted(required - set(raw)))
        raise RuntimeError(f"Reading difficulty profile is missing: {missing}")
    if raw["psychometric_equivalence"] is not False:
        raise RuntimeError("provisional Reading difficulty profile must not claim psychometric equivalence")
    if not isinstance(raw["dimensions"], dict) or not isinstance(raw["guardrails"], dict):
        raise RuntimeError("Reading difficulty dimensions and guardrails must be objects")
    return raw


DIFFICULTY_PROFILE = _load_profile()


def plan_difficulty_profile() -> dict[str, Any]:
    """Return the Planner-facing, prompt-safe structural target."""

    return {
        "profile_id": DIFFICULTY_PROFILE["schema_version"],
        "target_band": DIFFICULTY_PROFILE["target_band"],
        "calibration_status": "PROVISIONAL_STRUCTURAL_PROXY",
        "psychometric_equivalence": False,
        "dimensions": dict(DIFFICULTY_PROFILE["dimensions"]),
    }


def _word_tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _WORD_RE.finditer(text)]


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in _word_tokens(text)
        if len(token) > 2 and token not in _STOPWORDS
    }


def _sentence_word_counts(text: str) -> list[int]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_SPLIT_RE.split(normalized)
        if sentence.strip()
    ]
    return [len(_word_tokens(sentence)) for sentence in sentences if _word_tokens(sentence)]


def _lexical_overlap(left: str, right: str) -> float | None:
    left_tokens = _content_tokens(left)
    right_tokens = _content_tokens(right)
    if not left_tokens or not right_tokens:
        return None
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _question_answer_evidence_overlap(question: dict[str, Any]) -> float | None:
    if question.get("question_type") in {"VOCABULARY_IN_CONTEXT", "REFERENCE"}:
        return None
    choices = question.get("choices")
    correct = question.get("correct_answer")
    evidence = question.get("evidence")
    if not isinstance(choices, dict) or not isinstance(correct, str) or not isinstance(evidence, dict):
        return None
    answer = choices.get(correct)
    anchor = evidence.get("anchor")
    if not isinstance(answer, str) or not isinstance(anchor, str):
        return None
    return _lexical_overlap(answer, anchor)


def _distractor_categories(question: dict[str, Any]) -> list[str]:
    metadata = question.get("distractor_metadata")
    correct = question.get("correct_answer")
    if not isinstance(metadata, dict) or not isinstance(correct, str):
        return []
    categories: list[str] = []
    for label, entry in metadata.items():
        if label == correct or not isinstance(entry, dict):
            continue
        category = entry.get("category")
        if isinstance(category, str):
            categories.append(category)
    return categories


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def estimate_difficulty_alignment(
    plan: dict[str, Any] | None,
    generator: dict[str, Any] | None,
) -> dict[str, Any]:
    """Estimate observable structural difficulty and compare it with guardrails.

    PASS means only that no anti-pattern guardrail fired. It does not mean
    empirical or score equivalence with an official TOEFL ITP item.
    """

    target = plan.get("difficulty_profile") if isinstance(plan, dict) else None
    if not isinstance(target, dict):
        target = plan_difficulty_profile()

    base = {
        "schema_version": "reading-difficulty-estimate-v0.1",
        "target_band": target.get("target_band", DIFFICULTY_PROFILE["target_band"]),
        "calibration_status": "PROVISIONAL_STRUCTURAL_PROXY",
        "psychometric_equivalence": False,
    }
    if not isinstance(generator, dict):
        return {
            **base,
            "status": "UNAVAILABLE",
            "dimension_status": {},
            "observed": {},
            "warnings": [],
        }

    passage = generator.get("passage")
    questions = generator.get("questions")
    if not isinstance(passage, str) or not isinstance(questions, list):
        return {
            **base,
            "status": "UNAVAILABLE",
            "dimension_status": {},
            "observed": {},
            "warnings": ["DIFFICULTY_INPUT_UNAVAILABLE"],
        }

    question_objects = [q for q in questions if isinstance(q, dict)]
    words = _word_tokens(passage)
    sentence_words = _sentence_word_counts(passage)

    long_word_rate = (
        sum(len(token.replace("'", "")) >= 8 for token in words) / len(words)
        if words else 0.0
    )
    mean_sentence_words = mean(sentence_words) if sentence_words else 0.0

    overlaps = [
        overlap
        for question in question_objects
        if (overlap := _question_answer_evidence_overlap(question)) is not None
    ]
    guardrails = DIFFICULTY_PROFILE["guardrails"]
    copy_threshold = float(guardrails["surface_copy_overlap_warning_at_or_above"])
    copied = [overlap for overlap in overlaps if overlap >= copy_threshold]
    surface_copy_share = len(copied) / len(overlaps) if overlaps else None

    subtype_counts = Counter(
        question.get("subtype", "UNKNOWN")
        for question in question_objects
        if isinstance(question.get("subtype"), str)
    )
    evidence_scope_counts = Counter(
        _EVIDENCE_SCOPE_BY_SUBTYPE.get(question.get("subtype"), "UNKNOWN")
        for question in question_objects
    )
    inference_depth_counts = Counter(
        _INFERENCE_DEPTH_BY_SUBTYPE.get(question.get("subtype"), "UNKNOWN")
        for question in question_objects
        if question.get("question_type") == "INFERENCE"
    )

    distractor_categories = [
        category
        for question in question_objects
        for category in _distractor_categories(question)
    ]
    distractor_counts = Counter(distractor_categories)
    contradicted_share = (
        distractor_counts["CONTRADICTED_BY_PASSAGE"] / len(distractor_categories)
        if distractor_categories else None
    )

    warnings: list[str] = []
    if long_word_rate > float(guardrails["long_word_rate_warning_above"]):
        warnings.append("LEXICAL_LOAD_RISK")
    if mean_sentence_words > float(guardrails["mean_sentence_words_warning_above"]):
        warnings.append("SYNTACTIC_LOAD_RISK")
    if (
        surface_copy_share is not None
        and surface_copy_share > float(guardrails["surface_copy_question_share_warning_above"])
    ):
        warnings.append("CORRECT_OPTION_SURFACE_COPY_RISK")
    if (
        contradicted_share is not None
        and contradicted_share > float(guardrails["contradicted_distractor_share_warning_above"])
    ):
        warnings.append("DIRECTLY_CONTRADICTED_DISTRACTOR_DOMINANCE")

    dimension_status = {
        "lexical": "WARN" if "LEXICAL_LOAD_RISK" in warnings else "PASS",
        "syntactic": "WARN" if "SYNTACTIC_LOAD_RISK" in warnings else "PASS",
        "paraphrase": "WARN" if "CORRECT_OPTION_SURFACE_COPY_RISK" in warnings else "PASS",
        "evidence_distance": "OBSERVED_ONLY",
        "inference_depth": "OBSERVED_ONLY",
        "distractor_competitiveness": (
            "WARN" if "DIRECTLY_CONTRADICTED_DISTRACTOR_DOMINANCE" in warnings else "PASS"
        ),
    }

    return {
        **base,
        "status": "WARN" if warnings else "PASS",
        "dimension_status": dimension_status,
        "observed": {
            "passage_word_count": len(words),
            "sentence_count": len(sentence_words),
            "mean_sentence_words": _round(mean_sentence_words, 2),
            "long_word_rate": _round(long_word_rate),
            "answer_evidence_lexical_overlap_mean": _round(mean(overlaps) if overlaps else None),
            "surface_copy_question_share": _round(surface_copy_share),
            "subtype_distribution": dict(sorted(subtype_counts.items())),
            "evidence_scope_proxy_distribution": dict(sorted(evidence_scope_counts.items())),
            "inference_depth_proxy_distribution": dict(sorted(inference_depth_counts.items())),
            "distractor_category_distribution": dict(sorted(distractor_counts.items())),
            "directly_contradicted_distractor_share": _round(contradicted_share),
        },
        "warnings": warnings,
    }
