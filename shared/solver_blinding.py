"""Canonical, allowlist-only construction of Solver input.

This module is deliberately small and has no subprocess, filesystem, or
quality-judgement dependency.  Every caller that prepares Solver input uses
this one deterministic projection so persisted state, live orchestration, and
the compatibility CLI cannot drift apart.
"""

from __future__ import annotations

import copy

STRUCTURE_ALLOWLIST = ("item_id", "section", "stem", "options")
WRITTEN_EXPRESSION_ALLOWLIST = ("item_id", "section", "sentence", "marked_parts")


def canonical_solver_input(generator_item: dict) -> dict:
    """Return the exact allowlisted payload derived from one Generator item.

    The source item is never mutated.  Unknown sections and missing
    allowlisted fields fail closed instead of producing a partial Solver
    payload.
    """
    if not isinstance(generator_item, dict):
        raise TypeError("generator item must be an object")

    section = generator_item.get("section")
    if section == "Structure":
        allowlist = STRUCTURE_ALLOWLIST
    elif section == "Written Expression":
        allowlist = WRITTEN_EXPRESSION_ALLOWLIST
    else:
        raise ValueError(
            f"Unknown section {section!r} for item {generator_item.get('item_id', '?')}"
        )

    missing = [key for key in allowlist if key not in generator_item]
    if missing:
        raise ValueError(
            f"item {generator_item.get('item_id', '?')} is missing required field(s) "
            f"for blinding: {missing}"
        )

    # Deep-copy values because Structure.options and WE.marked_parts are
    # nested objects.  Callers may persist or test the returned payload; it
    # must never be able to mutate the canonical Generator source through a
    # shared reference.
    return {key: copy.deepcopy(generator_item[key]) for key in allowlist}
