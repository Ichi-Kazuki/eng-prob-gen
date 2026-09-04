"""Structure v0.2 Solver compatibility layer over the frozen v0.1 blind Solver.

The Structure v0.2 Solver semantics are intentionally unchanged from the
frozen Structure v0.1 blind Solver: the Solver receives only the FINAL
four-option item (item_id, section, stem, options) after Generator candidate
generation, blind Reviewer, deterministic candidate selection, four-option
assembly, and the frozen deterministic A-D permutation. It never sees the
seven-candidate pool.

This module is a thin wrapper. It does not reimplement blind projection,
exact-text answer matching, or the AMBIGUOUS/NONE contract: it delegates to
the frozen `structure.blinding` and `structure.contracts` implementations
and additionally enforces that the internally constructed Solver input
validates against the frozen `structure/schemas/solver_input.schema.json`.

No Generator/Reviewer reconciliation, ACCEPT/QUARANTINE decision, or
candidate-selection inspection happens here; that belongs to a future v0.2
pipeline/post-Solver decision layer.
"""

from __future__ import annotations

from typing import Any, Mapping

from shared.schema_validation import load_schema, schema_errors

from structure.blinding import build_solver_input as _build_v01_solver_input
from structure.contracts import SCHEMA_PATHS as _V01_SCHEMA_PATHS
from structure.contracts import canonicalize_solver_output as _canonicalize_solver_output
from structure.contracts import validate_solver_contract as _validate_solver_contract


SOLVER_INPUT_SCHEMA_PATH = _V01_SCHEMA_PATHS["solver_input"]


def build_solver_input(final_permuted: Mapping[str, Any]) -> dict[str, Any]:
    """Project a final-permuted v0.2 four-option batch to the frozen blind Solver input.

    `final_permuted` is the output of the frozen
    `structure.permutation.permute_generator_output(...)` applied to the
    v0.2 pre-permutation four-option batch (see
    `structure.v02.selection.assemble_final_generator_output`). Delegates to
    the frozen `structure.blinding.build_solver_input` allowlist projection,
    then fails closed unless the result also validates against the frozen
    `solver_input.schema.json`.
    """

    payload = _build_v01_solver_input(final_permuted)
    errors = schema_errors(payload, load_schema(SOLVER_INPUT_SCHEMA_PATH))
    if errors:
        raise ValueError(
            "Structure v0.2 Solver input failed the frozen solver_input schema: " + "; ".join(errors)
        )
    return payload


def solver_input_errors(final_permuted: Any, payload: Any) -> list[str]:
    """Return errors comparing `payload` against the deterministic replay projection.

    Rebuilds the expected Solver input from `final_permuted`, schema-validates
    `payload` against the frozen solver_input schema, and requires exact
    equality. No fuzzy correction: any changed item order, item_id, stem,
    option letter, option text, added field, or removed field fails.
    """

    if not isinstance(final_permuted, dict) or not isinstance(payload, dict):
        return ["Structure v0.2 Solver input and final permuted batch must be objects"]
    try:
        expected = build_solver_input(final_permuted)
    except (TypeError, ValueError, KeyError) as exc:
        return [f"Structure v0.2 Solver input could not be derived: {exc}"]

    errors = schema_errors(payload, load_schema(SOLVER_INPUT_SCHEMA_PATH))
    if payload != expected:
        errors.append("Structure v0.2 Solver input does not match the canonical allowlisted projection")
    return list(dict.fromkeys(errors))


def validate_solver_contract(raw_solver: Any, solver_input: Mapping[str, Any]) -> list[str]:
    """Delegate to the frozen v0.1 exact-text Solver output contract unchanged."""

    return _validate_solver_contract(raw_solver, solver_input)


def canonicalize_solver_output(raw_solver: Any, solver_input: Mapping[str, Any]) -> dict[str, Any]:
    """Delegate to the frozen v0.1 exact-text Solver output canonicalization unchanged."""

    return _canonicalize_solver_output(raw_solver, solver_input)


__all__ = [
    "SOLVER_INPUT_SCHEMA_PATH",
    "build_solver_input",
    "solver_input_errors",
    "validate_solver_contract",
    "canonicalize_solver_output",
]
