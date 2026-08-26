"""Canonical, allowlist-only construction of Reviewer input.

The Reviewer must make its independent judgment from the question surface,
not from Generator intent or QA metadata.  This module is deliberately pure:
it has no filesystem, subprocess, or model dependency and never mutates the
Generator source object.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

STRUCTURE_REVIEWER_ALLOWLIST = ("item_id", "section", "stem", "options")
WRITTEN_EXPRESSION_REVIEWER_ALLOWLIST = (
    "item_id",
    "section",
    "sentence",
    "marked_parts",
)


def reviewer_allowlist(section: object) -> tuple[str, ...]:
    """Return the canonical input fields for a supported section."""

    if section == "Structure":
        return STRUCTURE_REVIEWER_ALLOWLIST
    if section == "Written Expression":
        return WRITTEN_EXPRESSION_REVIEWER_ALLOWLIST
    raise ValueError(f"unsupported Reviewer section: {section!r}")


def canonical_reviewer_input(generator_item: dict[str, Any]) -> dict[str, Any]:
    """Project one Generator item to the exact Reviewer phase-1 payload.

    The allowlist is intentionally identical in shape to the Solver surface,
    while remaining a separate named boundary.  Unknown Generator fields are
    never copied, including fields added to the schema in the future.
    """

    if not isinstance(generator_item, dict):
        raise TypeError("generator item must be an object")
    allowlist = reviewer_allowlist(generator_item.get("section"))
    missing = [key for key in allowlist if key not in generator_item]
    if missing:
        raise ValueError(
            f"item {generator_item.get('item_id', '?')} is missing required field(s) "
            f"for Reviewer blinding: {missing}"
        )
    return {key: copy.deepcopy(generator_item[key]) for key in allowlist}


def reviewer_input_sha256(payload: dict[str, Any]) -> str:
    """Return a stable digest for a canonical Reviewer payload."""

    if not isinstance(payload, dict):
        raise TypeError("Reviewer payload must be an object")
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Reviewer payload is not JSON-compatible: {exc}") from exc
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def canonical_reviewer_input_sha256(generator_item: dict[str, Any]) -> str:
    """Hash the canonical projection derived from a Generator item."""

    return reviewer_input_sha256(canonical_reviewer_input(generator_item))


def reviewer_input_errors(
    generator_item: object,
    reviewer_input: object,
    expected_sha256: object | None = None,
) -> list[str]:
    """Return errors when a precomputed Reviewer payload is stale or forged.

    Equality is checked against a fresh projection from the source item.  The
    optional digest is an additional artifact-integrity check; it is not used
    as an authenticity boundary by itself.
    """

    errors: list[str] = []
    if not isinstance(generator_item, dict):
        return ["Generator item must be an object"]
    if not isinstance(reviewer_input, dict):
        return ["Reviewer input must be an object"]
    try:
        expected = canonical_reviewer_input(generator_item)
    except (TypeError, ValueError, KeyError) as exc:
        return [f"canonical Reviewer input could not be derived: {exc}"]
    if reviewer_input != expected:
        errors.append("Reviewer input does not match the canonical allowlisted payload")
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or expected_sha256 != reviewer_input_sha256(reviewer_input):
            errors.append("Reviewer input digest does not match the supplied payload")
    return errors


# Descriptive aliases keep the API easy to discover without creating a second
# implementation or a second policy.
canonical_reviewer_payload = canonical_reviewer_input
reviewer_payload_sha256 = reviewer_input_sha256
canonical_reviewer_payload_sha256 = canonical_reviewer_input_sha256
validate_reviewer_input = reviewer_input_errors

