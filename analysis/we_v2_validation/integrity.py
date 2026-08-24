"""Deterministic Written Expression answer-key integrity helpers.

The answer key is derived from the clean/error mutation and the marked spans.
This module intentionally has no grammar model: it verifies location and
alignment only.  A live Reviewer/Solver remains necessary for grammar-quality
judgments.
"""

from __future__ import annotations

import difflib
import re
from typing import Any


LABELS = ("A", "B", "C", "D")
TOKEN_RE = re.compile(r"[\w]+(?:['-][\w]+)*", re.UNICODE)


def token_matches(text: str) -> list[re.Match[str]]:
    return list(TOKEN_RE.finditer(text))


def token_texts(text: str) -> list[str]:
    return [match.group(0) for match in token_matches(text)]


def marked_token_indices(sentence: str, marked_parts: dict[str, str]) -> dict[str, list[int]]:
    matches = token_matches(sentence)
    indices: dict[str, list[int]] = {}
    for label in LABELS:
        span = marked_parts.get(label)
        if not isinstance(span, str):
            raise ValueError(f"marked_parts.{label} must be a string")
        start = sentence.find(span)
        if start < 0 or sentence.find(span, start + 1) >= 0:
            raise ValueError(f"marked span {label} is missing or not uniquely aligned")
        end = start + len(span)
        selected = [
            index
            for index, match in enumerate(matches)
            if match.start() >= start and match.end() <= end
        ]
        if not selected:
            raise ValueError(f"marked span {label} contains no token")
        indices[label] = selected
    return indices


def _label_for_error_token(
    token_index: int,
    sentence: str,
    marked_parts: dict[str, str],
    span_indices: dict[str, list[int]],
) -> str | None:
    for label in LABELS:
        if token_index in span_indices[label]:
            return label
    return None


def _label_for_error_boundary(
    boundary_index: int,
    sentence: str,
    marked_parts: dict[str, str],
    span_indices: dict[str, list[int]],
) -> str | None:
    """Map a deleted clean token to the error-side insertion boundary.

    A missing word has no error-side token.  The boundary before the next
    error token is therefore used, with half-open span membership so a missing
    determiner immediately before a marked phrase maps to that phrase.
    """

    matches = token_matches(sentence)
    boundary_char = matches[boundary_index].start() if boundary_index < len(matches) else len(sentence)
    for label in LABELS:
        span = marked_parts[label]
        start = sentence.find(span)
        end = start + len(span)
        if start <= boundary_char < end:
            return label
    return None


def mutation_location(
    clean_sentence: str,
    error_sentence: str,
    marked_parts: dict[str, str],
) -> dict[str, Any]:
    """Return the deterministic error-side mutation location.

    A valid one-error Written Expression item must have every non-equal
    opcode wholly attributable to the same marked span.  Multiple diff
    opcodes are allowed when one local phrase was reordered, but unmarked
    operations invalidate the location even if another operation has a label.
    """

    if not isinstance(clean_sentence, str) or not isinstance(error_sentence, str):
        raise ValueError("clean_sentence and error_sentence must be strings")
    if clean_sentence == error_sentence:
        raise ValueError("clean and error sentences must differ")

    span_indices = marked_token_indices(error_sentence, marked_parts)
    clean_tokens = token_texts(clean_sentence)
    error_tokens = token_texts(error_sentence)
    matcher = difflib.SequenceMatcher(
        a=[token.lower() for token in clean_tokens],
        b=[token.lower() for token in error_tokens],
        autojunk=False,
    )

    operations: list[dict[str, Any]] = []
    operation_validity: list[bool] = []
    labels: set[str] = set()
    for tag, clean_start, clean_end, error_start, error_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        error_indices = list(range(error_start, error_end))
        if error_indices:
            error_labels = [
                _label_for_error_token(index, error_sentence, marked_parts, span_indices)
                for index in error_indices
            ]
            operation_labels = {
                label for label in error_labels
                if label is not None
            }
            operation_is_single_marked_location = (
                len(operation_labels) == 1
                and all(label in operation_labels for label in error_labels)
            )
        else:
            boundary_label = _label_for_error_boundary(
                error_start, error_sentence, marked_parts, span_indices
            )
            operation_labels = {boundary_label} if boundary_label else set()
            operation_is_single_marked_location = bool(boundary_label)
        labels.update(operation_labels)
        operation_validity.append(operation_is_single_marked_location)
        operations.append({
            "tag": tag,
            "clean_token_indices": list(range(clean_start, clean_end)),
            "error_token_indices": error_indices,
            "clean_tokens": clean_tokens[clean_start:clean_end],
            "error_tokens": error_tokens[error_start:error_end],
            "affected_labels": sorted(operation_labels),
        })

    valid_single_marked_location = bool(operations) and len(labels) == 1
    if valid_single_marked_location:
        expected_label = next(iter(labels))
        valid_single_marked_location = all(
            operation_is_valid and operation["affected_labels"] == [expected_label]
            for operation_is_valid, operation in zip(operation_validity, operations)
        )

    return {
        "clean_token_count": len(clean_tokens),
        "error_token_count": len(error_tokens),
        "operations": operations,
        "labels": sorted(labels),
        "span_token_indices": span_indices,
        "valid_single_marked_location": valid_single_marked_location,
    }


def derive_correct_answer(
    clean_sentence: str,
    error_sentence: str,
    marked_parts: dict[str, str],
) -> str:
    """Derive the answer label from the actual mutation location."""

    location = mutation_location(clean_sentence, error_sentence, marked_parts)
    labels = location["labels"]
    if not location["valid_single_marked_location"]:
        raise ValueError(
            "every mutation operation must resolve to the same marked label; "
            f"got labels={labels}, operations={location['operations']}"
        )
    return labels[0]


def span_kind(word_count: int) -> str:
    if word_count == 1:
        return "SINGLE_WORD"
    if 2 <= word_count <= 4:
        return "SHORT_PHRASE"
    return "CLAUSE_OR_CLAUSE_LIKE"
