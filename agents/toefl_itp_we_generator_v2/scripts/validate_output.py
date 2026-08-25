#!/usr/bin/env python3
"""Validate WE Generator v2 output at the pipeline boundary.

The JSON Schema is the canonical structural contract. Only after an item
passes that contract do we run taxonomy, semantic, and deterministic format
checks supplied by ``validate_format.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)
from validate_format import (  # noqa: E402
    CONFIG_PATH,
    GRAMMAR_SPEC_PATH,
    TAXONOMY_PATH,
    load_items,
    load_json,
    validate_item,
)


OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "written_expression_item_v2.schema.json"
_SCHEMA: dict[str, Any] | None = None


def output_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA


def validate_contract(
    item: object,
    config: dict[str, Any],
    targets: set[str],
    error_types: set[str],
) -> dict[str, Any]:
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        return {"item_id": item_id, "valid": False, "errors": ["$: item must be an object"], "diagnostics": {}}

    structural = schema_errors(item, output_schema())
    if structural:
        return {
            "item_id": item_id,
            "valid": False,
            "errors": [f"{OUTPUT_SCHEMA_PATH.name}: {error}" for error in structural],
            "diagnostics": {},
        }

    # This function owns semantic and deterministic checks only. Structural
    # required/type/enum/additional-property checks remain in the schema.
    return validate_item(item, config, targets, error_types)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python validate_output.py <items.json>")
        return 2
    try:
        path = Path(sys.argv[1])
        config = load_json(CONFIG_PATH)
        grammar = load_json(GRAMMAR_SPEC_PATH)
        taxonomy = load_json(TAXONOMY_PATH)
        targets = {x["id"] for x in taxonomy["primary_targets"]}
        error_types = {
            x["id"]
            for x in grammar["tested_error_types"]
            if x["id"] not in {"fragment", "wrong_complementation"}
        }
        results = [validate_contract(item, config, targets, error_types) for item in load_items(path)]
    except ValueError as exc:
        print(f"CONTENT ERROR: {exc}")
        return 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # validator crash => explicit system failure
        print(f"SYSTEM ERROR: unexpected validator exception: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    failures = [result for result in results if not result["valid"]]
    print(f"Checked {len(results)} WE v2 item(s); {len(failures)} failed.")
    for result in failures:
        print(f"[{result['item_id']}]")
        for error in result["errors"]:
            print(f"  - {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
