#!/usr/bin/env python3
"""Contract validator for WE Generator v2 output.

Public validation API
---------------------
``validate_contract(item, ...)`` is the ONLY supported entry point for
external callers (CLI, internal imports, tests, orchestrator). It runs, in
order:

1. Structural validation against the committed
   ``schema/written_expression_item_v2.schema.json`` (source of truth for the
   output shape). Structural failures short-circuit: the semantic stage never
   sees a malformed item.
2. ``validate_semantics(...)`` - the deterministic geometry/semantic
   validation in ``validate_format.validate_item``.

``validate_semantics`` (and ``validate_format.validate_item`` behind it) is
the geometry engine, not a public gate: calling it directly bypasses the
structural schema gate and is not a supported validation path.

``validate`` and ``validate_item_contract`` are aliases of
``validate_contract``. It returns the same ``{"item_id", "valid", "errors",
...}`` result shape that ``validate_format.validate_item`` returns, so the
existing consumers of that shape keep working.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_format import (  # noqa: E402
    CONFIG_PATH,
    GRAMMAR_SPEC_PATH,
    TAXONOMY_PATH,
    load_items,
    load_json,
    schema_errors,
    validate_item as validate_semantics,
)
from shared.schema_validation import SchemaValidationRuntimeError  # noqa: E402

ITEM_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "written_expression_item_v2.schema.json"

_CONTEXT_CACHE: dict | None = None


def validation_context() -> dict:
    """Load (and memoize) the schema, config and taxonomy the gate needs."""
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is None:
        grammar = load_json(GRAMMAR_SPEC_PATH)
        taxonomy = load_json(TAXONOMY_PATH)
        _CONTEXT_CACHE = {
            "schema": load_json(ITEM_SCHEMA_PATH),
            "config": load_json(CONFIG_PATH),
            "targets": {x["id"] for x in taxonomy["primary_targets"]},
            "error_types": {
                x["id"] for x in grammar["tested_error_types"]
                if x["id"] not in {"fragment", "wrong_complementation"}
            },
        }
    return _CONTEXT_CACHE


def validate_contract(item, config=None, targets=None, error_types=None) -> dict:
    """The full public contract: structural schema gate, then semantics.

    Every caller - CLI, internal import, test, orchestrator - goes through
    this one function, so there is no path that reaches the geometry checks
    without first clearing the committed JSON Schema.
    """
    context = validation_context()
    config = context["config"] if config is None else config
    targets = context["targets"] if targets is None else targets
    error_types = context["error_types"] if error_types is None else error_types

    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        return {
            "item_id": item_id,
            "valid": False,
            "errors": ["generated item must be an object"],
            "diagnostics": {},
        }
    structural = schema_errors(item, context["schema"])
    if structural:
        return {
            "item_id": item_id,
            "valid": False,
            "errors": [f"{ITEM_SCHEMA_PATH.name}: {error}" for error in structural],
            "diagnostics": {},
        }
    return validate_semantics(item, config, targets, error_types)


# Aliases: both are the gated contract, never the bare geometry stage.
validate = validate_contract
validate_item_contract = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python validate_output.py <items.json>")
        return 2
    try:
        items = load_items(Path(sys.argv[1]))

        # The CLI has no validation logic of its own: it calls exactly the same
        # public entry point that internal importers call.
        results = [validate_contract(item) for item in items]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    failures = [result for result in results if not result["valid"]]
    print(f"Checked {len(results)} WE v2 item(s); {len(failures)} failed.")
    for result in failures:
        print(f"[{result['item_id']}] ")
        for error in result["errors"]:
            print(f"  - {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
