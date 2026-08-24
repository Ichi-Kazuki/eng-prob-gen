#!/usr/bin/env python3
"""Canonical WE Generator v2 output emission boundary.

This adapter runs deterministic format diagnostics before the Generator
contract validator. It never invents diagnostics. A candidate that cannot be
measured is returned as a failure record and is not emitted as a schema-valid
item.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from validate_format import (
    CONFIG_PATH,
    DiagnosticsEmissionError,
    GRAMMAR_SPEC_PATH,
    TAXONOMY_PATH,
    inject_canonical_diagnostics,
    load_items,
    load_json,
    schema_errors,
    validate_item,
)


ITEM_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "written_expression_item_v2.schema.json"


def emit_items(
    items: list[Any],
    config: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonicalize and strictly validate candidates before emission.

    The schema gate intentionally runs on the copied, canonicalized item. A
    candidate with valid geometry but a missing top-level contract field must
    still be rejected at this boundary.
    """

    schema = schema or load_json(ITEM_SCHEMA_PATH)
    grammar = load_json(GRAMMAR_SPEC_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    targets = {entry["id"] for entry in taxonomy["primary_targets"]}
    error_types = {
        entry["id"]
        for entry in grammar["tested_error_types"]
        if entry["id"] not in {"fragment", "wrong_complementation"}
    }
    emitted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in items:
        item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
        try:
            canonical = inject_canonical_diagnostics(item, config)
        except DiagnosticsEmissionError as exc:
            failures.append({
                "item_id": item_id,
                "state": "VALIDATION_FAILED",
                "failure_kind": "content",
                "stage": "generator_diagnostics_emission",
                "error": str(exc),
            })
            continue

        contract_errors = [f"schema: {error}" for error in schema_errors(canonical, schema)]
        format_result = validate_item(canonical, config, targets, error_types)
        contract_errors.extend(f"contract: {error}" for error in format_result["errors"])
        if contract_errors:
            failures.append({
                "item_id": item_id,
                "state": "VALIDATION_FAILED",
                "failure_kind": "schema" if any(error.startswith("schema:") for error in contract_errors) else "contract",
                "stage": "generator_schema_validation",
                "errors": contract_errors,
            })
            continue
        emitted.append(canonical)
    return emitted, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("items", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failures", type=Path, required=True)
    args = parser.parse_args()

    config = load_json(CONFIG_PATH)
    emitted, failures = emit_items(load_items(args.items), config)
    args.output.write_text(json.dumps({"items": emitted}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.failures.write_text(json.dumps({"failures": failures}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Emitted {len(emitted)} item(s); {len(failures)} failed validation.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
