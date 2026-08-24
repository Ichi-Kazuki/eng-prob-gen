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


def _text_units(text: str) -> list[dict[str, Any]]:
    """Split text into lexical tokens and the separators between them.

    The separator units are intentionally retained.  A token-only diff can
    report a valid marked-word replacement while silently ignoring a comma,
    quote, or spacing change elsewhere in the sentence.
    """

    units: list[dict[str, Any]] = []
    cursor = 0
    token_index = 0
    for match in token_matches(text):
        if cursor < match.start():
            units.append({
                "kind": "non_token",
                "text": text[cursor:match.start()],
                "start": cursor,
                "end": match.start(),
            })
        units.append({
            "kind": "token",
            "text": match.group(0),
            "start": match.start(),
            "end": match.end(),
            "token_index": token_index,
        })
        token_index += 1
        cursor = match.end()
    if cursor < len(text):
        units.append({
            "kind": "non_token",
            "text": text[cursor:],
            "start": cursor,
            "end": len(text),
        })
    return units


def _is_benign_separator(unit: dict[str, Any]) -> bool:
    """True for the ordinary single space that merely separates two tokens.

    A diff opcode covering a marked replacement routinely pulls in the spaces
    on either side of it, and those carry no mutation.  Any other whitespace
    run -- doubled spaces, a tab, a newline -- is a real spacing change and
    must be attributed to the marked span like punctuation, otherwise a
    mutation outside the span rides along inside a valid-looking opcode.
    """

    return unit["kind"] == "non_token" and unit["text"] == " "


def _unit_key(unit: dict[str, Any]) -> str:
    return (
        unit["text"].lower()
        if unit["kind"] == "token"
        else unit["text"]
    )


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
    """Map a deleted clean token to an error-side token boundary.

    A deletion leaves no error-side token, so the boundary is attributed from
    the tokens on either side of it.  Either neighbour alone is sufficient: a
    missing determiner or auxiliary immediately before a marked phrase belongs
    to that phrase, and a deletion from the end of a marked span belongs to the
    span it was taken from.  Attribution is refused only when it would be
    ambiguous, that is when the two neighbours are different marked spans and
    neither has a stronger claim.  Sentence start and sentence end are just the
    cases where one neighbour is absent; they need no special rule.
    """

    matches = token_matches(sentence)

    def label_at(index: int) -> str | None:
        if index < 0 or index >= len(matches):
            return None
        return _label_for_error_token(index, sentence, marked_parts, span_indices)

    previous_label = label_at(boundary_index - 1)
    next_label = label_at(boundary_index)

    if previous_label == next_label:
        return previous_label
    if previous_label is None:
        return next_label
    if next_label is None:
        return previous_label
    return None


def _label_for_error_unit(
    unit: dict[str, Any],
    sentence: str,
    marked_parts: dict[str, str],
    span_indices: dict[str, list[int]],
) -> str | None:
    if unit["kind"] == "token":
        return _label_for_error_token(
            unit["token_index"], sentence, marked_parts, span_indices
        )

    for label in LABELS:
        span = marked_parts[label]
        start = sentence.find(span)
        end = start + len(span)
        if start <= unit["start"] and unit["end"] <= end:
            return label
    return None


def mutation_location(
    clean_sentence: str,
    error_sentence: str,
    marked_parts: dict[str, str],
) -> dict[str, Any]:
    """Return the deterministic error-side mutation location.

    A valid one-error Written Expression item must have every non-equal
    token-or-separator opcode wholly attributable to the same marked span.
    Multiple diff opcodes are allowed when one local phrase was reordered, but
    unmarked operations invalidate the location even if another operation has
    a label.
    """

    if not isinstance(clean_sentence, str) or not isinstance(error_sentence, str):
        raise ValueError("clean_sentence and error_sentence must be strings")
    if clean_sentence == error_sentence:
        raise ValueError("clean and error sentences must differ")

    span_indices = marked_token_indices(error_sentence, marked_parts)
    clean_units = _text_units(clean_sentence)
    error_units = _text_units(error_sentence)
    clean_tokens = [
        unit["text"] for unit in clean_units if unit["kind"] == "token"
    ]
    error_tokens = [
        unit["text"] for unit in error_units if unit["kind"] == "token"
    ]
    matcher = difflib.SequenceMatcher(
        a=[_unit_key(unit) for unit in clean_units],
        b=[_unit_key(unit) for unit in error_units],
        autojunk=False,
    )

    operations: list[dict[str, Any]] = []
    operation_validity: list[bool] = []
    labels: set[str] = set()
    for tag, clean_start, clean_end, error_start, error_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_clean_units = clean_units[clean_start:clean_end]
        changed_error_units = error_units[error_start:error_end]
        error_token_indices = [
            unit["token_index"]
            for unit in changed_error_units
            if unit["kind"] == "token"
        ]
        clean_token_indices = [
            unit["token_index"]
            for unit in changed_clean_units
            if unit["kind"] == "token"
        ]

        error_labels = [
            _label_for_error_unit(unit, error_sentence, marked_parts, span_indices)
            for unit in changed_error_units
        ]
        operation_labels = {
            label for label in error_labels
            if label is not None
        }
        unlabeled_non_whitespace_error = any(
            unit["kind"] == "non_token"
            and not _is_benign_separator(unit)
            and label is None
            for unit, label in zip(changed_error_units, error_labels)
        )
        changed_clean_punctuation = any(
            unit["kind"] == "non_token"
            and not _is_benign_separator(unit)
            for unit in changed_clean_units
        )

        if changed_error_units:
            operation_is_single_marked_location = (
                bool(operation_labels)
                and not unlabeled_non_whitespace_error
                and not changed_clean_punctuation
                and len(operation_labels) == 1
                and all(
                    _is_benign_separator(unit) or label in operation_labels
                    for unit, label in zip(changed_error_units, error_labels)
                )
            )
        else:
            boundary_token_index = next(
                (
                    unit["token_index"]
                    for unit in error_units[error_start:]
                    if unit["kind"] == "token"
                ),
                len(error_tokens),
            )
            boundary_label = _label_for_error_boundary(
                boundary_token_index,
                error_sentence,
                marked_parts,
                span_indices,
            ) if clean_token_indices else None
            operation_labels = {boundary_label} if boundary_label else set()
            operation_is_single_marked_location = bool(
                boundary_label and not changed_clean_punctuation
            )
        labels.update(operation_labels)
        operation_validity.append(operation_is_single_marked_location)
        operations.append({
            "tag": tag,
            "clean_token_indices": clean_token_indices,
            "error_token_indices": error_token_indices,
            "clean_tokens": [clean_tokens[index] for index in clean_token_indices],
            "error_tokens": [error_tokens[index] for index in error_token_indices],
            "clean_non_token_units": [
                unit["text"]
                for unit in changed_clean_units
                if unit["kind"] == "non_token"
            ],
            "error_non_token_units": [
                unit["text"]
                for unit in changed_error_units
                if unit["kind"] == "non_token"
            ],
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
