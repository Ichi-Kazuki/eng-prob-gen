"""Cheap diagnostics for generated Reading passage sets and batches."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from statistics import mean
from typing import Any, Iterable

from .difficulty import estimate_difficulty_alignment

from .contracts import (
    HARD_VALIDITY,
    passage_word_count_profile,
    split_paragraphs,
    word_count,
)


def sentence_count(text: str) -> int:
    """Count ordinary sentence-final punctuation without an NLP dependency."""

    return len(re.findall(r"[.!?](?=(?:[\"'\)\]]?)(?:\s|$))", text))


def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _option_length_distribution(questions: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = [
        len(choice)
        for question in questions
        for choice in (question.get("choices", {}) or {}).values()
        if isinstance(choice, str)
    ]
    if not lengths:
        return {"count": 0, "minimum": 0, "maximum": 0, "mean": 0.0, "buckets": {}}
    buckets = Counter(
        "0-24" if length < 25 else
        "25-49" if length < 50 else
        "50-74" if length < 75 else
        "75+"
        for length in lengths
    )
    return {
        "count": len(lengths),
        "minimum": min(lengths),
        "maximum": max(lengths),
        "mean": round(mean(lengths), 2),
        "buckets": dict(sorted(buckets.items())),
    }


def choice_quality_warnings(output: dict[str, Any] | None) -> list[str]:
    """Return conservative, non-blocking warnings for suspicious choices.

    These checks are intentionally surface-level. They flag patterns worth
    review without attempting to decide semantic correctness automatically.
    """

    if not isinstance(output, dict) or not isinstance(output.get("passage"), str):
        return []
    passage = re.sub(r"\s+", " ", output["passage"]).strip().casefold()
    warnings: list[str] = []
    for question in output.get("questions", []):
        if not isinstance(question, dict) or not isinstance(question.get("choices"), dict):
            continue
        item_id = question.get("item_id", "<unknown>")
        choices = question["choices"]
        if set(choices) != {"A", "B", "C", "D"} or not all(isinstance(value, str) for value in choices.values()):
            continue
        lengths = {label: len(choices[label]) for label in ("A", "B", "C", "D")}
        for label, length in lengths.items():
            other_lengths = [value for other, value in lengths.items() if other != label]
            if length >= 40 and length >= 1.8 * max(other_lengths) and length - max(other_lengths) >= 20:
                warnings.append(f"{item_id}: CHOICE_LENGTH_OUTLIER on {label}")
        normalized = {
            label: re.sub(r"\s+", " ", choices[label]).strip(" .,:;!?\"'()[]").casefold()
            for label in ("A", "B", "C", "D")
        }
        for index, left in enumerate(("A", "B", "C", "D")):
            for right in ("A", "B", "C", "D")[index + 1:]:
                if normalized[left] != normalized[right] and len(normalized[left].split()) >= 4:
                    if SequenceMatcher(None, normalized[left], normalized[right]).ratio() >= 0.92:
                        warnings.append(f"{item_id}: CHOICE_NEAR_DUPLICATE {left}/{right}")
        correct_answer = question.get("correct_answer")
        correct = normalized.get(correct_answer) if isinstance(correct_answer, str) else None
        if isinstance(correct, str) and len(correct.split()) >= 5 and correct in passage:
            wrong_choices_copied = any(
                normalized[label] and normalized[label] in passage
                for label in ("A", "B", "C", "D")
                if label != correct_answer
            )
            if not wrong_choices_copied:
                warnings.append(f"{item_id}: CORRECT_OPTION_COPIED_FROM_PASSAGE")
    return warnings


def diagnostics_for_result(result: dict[str, Any]) -> dict[str, Any]:
    generator = result.get("generator")
    if not isinstance(generator, dict):
        return {
            "passage_word_count": 0,
            "paragraph_count": 0,
            "word_count_classification": None,
            "empirical_format_warnings": [],
            "sentence_count": 0,
            "question_count": 0,
            "question_type_distribution": {},
            "correct_answer_distribution": {},
            "option_length_distribution": _option_length_distribution([]),
            "choice_quality_warnings": [],
            "difficulty": estimate_difficulty_alignment(result.get("plan"), None),
            "reviewer_solver_agreement": {"agree": 0, "total": 0, "rate": None},
            "reviewer_ambiguous_none_count": 0,
            "solver_ambiguous_none_count": 0,
            "acceptance_rate": None,
        }
    passage = generator.get("passage", "")
    questions = generator.get("questions", [])
    if not isinstance(passage, str) or not isinstance(questions, list):
        return diagnostics_for_result({**result, "generator": None})
    is_v02 = (result.get("plan") or {}).get("schema_version") == "reading-plan-v0.2"
    count = word_count(passage)
    word_profile = passage_word_count_profile(count, is_v02=is_v02)
    checks = result.get("checks", {})
    hard_failures = checks.get("generator_errors", []) + checks.get("deterministic_errors", [])
    classification = checks.get("deterministic_classification")
    if not isinstance(classification, str):
        classification = HARD_VALIDITY if hard_failures else word_profile["classification"]
    empirical_warnings = list(checks.get("empirical_warnings", []))
    if word_profile["empirical_warning"] and not empirical_warnings:
        empirical_warnings.append(
            f"deterministic: passage word count {count} is above the empirical preferred band of 160-300"
        )
    agreements = result.get("checks", {}).get("answer_agreement", [])
    reviewer = result.get("reviewer") or {}
    solver = result.get("solver") or {}
    reviewer_questions = reviewer.get("questions", []) if isinstance(reviewer, dict) else []
    solver_answers = solver.get("answers", []) if isinstance(solver, dict) else []
    agree_count = sum(item.get("agree") is True for item in agreements if isinstance(item, dict))
    return {
        "passage_word_count": count,
        "paragraph_count": len(split_paragraphs(passage)),
        "word_count_classification": classification,
        "empirical_format_warnings": empirical_warnings,
        "sentence_count": sentence_count(passage),
        "question_count": len(questions),
        "question_type_distribution": _counts(
            question.get("question_type", "UNKNOWN")
            for question in questions
            if isinstance(question, dict)
        ),
        "correct_answer_distribution": _counts(
            question.get("correct_answer", "UNKNOWN")
            for question in questions
            if isinstance(question, dict)
        ),
        "option_length_distribution": _option_length_distribution(
            [question for question in questions if isinstance(question, dict)]
        ),
        "choice_quality_warnings": choice_quality_warnings(generator),
        "difficulty": estimate_difficulty_alignment(result.get("plan"), generator),
        "reviewer_solver_agreement": {
            "agree": agree_count,
            "total": len(agreements),
            "rate": round(agree_count / len(agreements), 4) if agreements else None,
        },
        "reviewer_ambiguous_none_count": sum(
            item.get("best_answer") in {"AMBIGUOUS", "NONE"}
            for item in reviewer_questions
            if isinstance(item, dict)
        ),
        "solver_ambiguous_none_count": sum(
            item.get("answer") in {"AMBIGUOUS", "NONE"}
            for item in solver_answers
            if isinstance(item, dict)
        ),
        "acceptance_rate": 1.0 if result.get("decision") == "ACCEPT" else 0.0,
    }


def aggregate_diagnostics(results: list[dict[str, Any]]) -> dict[str, Any]:
    per_passage = [diagnostics_for_result(result) for result in results]
    populated = [item for item in per_passage if item["question_count"]]
    type_counts: Counter[Any] = Counter()
    answer_counts: Counter[Any] = Counter()
    option_counts: Counter[Any] = Counter()
    agreement_total = 0
    agreement_agree = 0
    reviewer_none = 0
    solver_none = 0
    choice_quality_warning_count = 0
    for item in populated:
        type_counts.update(item["question_type_distribution"])
        answer_counts.update(item["correct_answer_distribution"])
        option_counts.update(item["option_length_distribution"]["buckets"])
        agreement_agree += item["reviewer_solver_agreement"]["agree"]
        agreement_total += item["reviewer_solver_agreement"]["total"]
        reviewer_none += item["reviewer_ambiguous_none_count"]
        solver_none += item["solver_ambiguous_none_count"]
        choice_quality_warning_count += len(item["choice_quality_warnings"])
    completed = len(results)
    accepted = sum(result.get("decision") == "ACCEPT" for result in results)
    return {
        "passage_count_with_generator": len(populated),
        "passage_word_count": {
            "minimum": min((item["passage_word_count"] for item in populated), default=0),
            "maximum": max((item["passage_word_count"] for item in populated), default=0),
            "mean": round(mean(item["passage_word_count"] for item in populated), 2) if populated else 0.0,
        },
        "question_count_total": sum(item["question_count"] for item in populated),
        "question_type_distribution": dict(sorted(type_counts.items())),
        "correct_answer_distribution": dict(sorted(answer_counts.items())),
        "option_length_buckets": dict(sorted(option_counts.items())),
        "reviewer_solver_agreement": {
            "agree": agreement_agree,
            "total": agreement_total,
            "rate": round(agreement_agree / agreement_total, 4) if agreement_total else None,
        },
        "reviewer_ambiguous_none_count": reviewer_none,
        "solver_ambiguous_none_count": solver_none,
        "choice_quality_warning_count": choice_quality_warning_count,
        "acceptance_rate": round(accepted / completed, 4) if completed else None,
        "per_passage": per_passage,
    }
