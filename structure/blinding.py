"""Allowlist-only blind projections for the Structure Reviewer and Solver."""

from __future__ import annotations

from typing import Any, Mapping

from shared.reviewer_blinding import reviewer_input_sha256
from shared.solver_blinding import canonical_solver_input

from .contracts import FORBIDDEN_PRIVATE_FIELDS, find_leakage, validate_blind_input


BLIND_ALLOWLIST = ("item_id", "section", "stem", "options")


def _project_item(item: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TypeError("Structure Generator item must be an object")
    if item.get("section") != "Structure":
        raise ValueError("Structure blind projection requires section=Structure")
    # Use the shared canonical Structure projection for the same immutable,
    # deep-copying behavior used by the existing grammar runtime.
    projected = canonical_solver_input(dict(item))
    if tuple(projected) != BLIND_ALLOWLIST:
        raise AssertionError("shared Structure projection changed its allowlist")
    return projected


def build_blind_input(generator: Mapping[str, Any]) -> dict[str, Any]:
    items = generator.get("items")
    if not isinstance(items, list):
        raise ValueError("Generator output must contain an items array")
    payload = {"items": [_project_item(item) for item in items]}
    leakage = find_leakage(payload)
    if leakage:
        raise ValueError("Structure blind projection contains forbidden field(s): " + ", ".join(leakage))
    return payload


build_reviewer_input = build_blind_input
build_solver_input = build_blind_input


def blind_input_sha256(payload: Mapping[str, Any]) -> str:
    return reviewer_input_sha256(dict(payload))


def reviewer_input_hash(payload: Mapping[str, Any]) -> str:
    return blind_input_sha256(payload)


def solver_input_hash(payload: Mapping[str, Any]) -> str:
    return blind_input_sha256(payload)


validate_reviewer_input = validate_blind_input
validate_solver_input = validate_blind_input


def blind_input_errors(generator: Any, payload: Any, plan: Mapping[str, Any] | None = None) -> list[str]:
    if not isinstance(generator, dict) or not isinstance(payload, dict):
        return ["Structure blind input and Generator output must be objects"]
    try:
        expected = build_blind_input(generator)
    except (TypeError, ValueError, KeyError) as exc:
        return [f"Structure blind input could not be derived: {exc}"]
    errors = []
    if payload != expected:
        errors.append("Structure blind input does not match the canonical allowlisted projection")
    errors.extend(validate_blind_input(payload, plan))
    return list(dict.fromkeys(errors))


def leakage_errors(payload: Any) -> list[str]:
    return [f"forbidden field {path}" for path in find_leakage(payload)]


__all__ = [
    "BLIND_ALLOWLIST",
    "FORBIDDEN_PRIVATE_FIELDS",
    "blind_input_errors",
    "blind_input_sha256",
    "build_blind_input",
    "build_reviewer_input",
    "build_solver_input",
    "leakage_errors",
    "reviewer_input_hash",
    "validate_reviewer_input",
    "validate_solver_input",
    "solver_input_hash",
]
