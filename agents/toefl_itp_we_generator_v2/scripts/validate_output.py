#!/usr/bin/env python3
"""Schema-level contract validation for WE Generator v2 output."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from validate_format import load_items, load_json, validate_item, CONFIG_PATH, GRAMMAR_SPEC_PATH, TAXONOMY_PATH


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python validate_output.py <items.json>")
        return 2
    path = Path(sys.argv[1])
    config = load_json(CONFIG_PATH)
    grammar = load_json(GRAMMAR_SPEC_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    targets = {x["id"] for x in taxonomy["primary_targets"]}
    error_types = {x["id"] for x in grammar["tested_error_types"] if x["id"] not in {"fragment", "wrong_complementation"}}
    results = [validate_item(item, config, targets, error_types) for item in load_items(path)]
    failures = [result for result in results if not result["valid"]]
    print(f"Checked {len(results)} WE v2 item(s); {len(failures)} failed.")
    for result in failures:
        print(f"[{result['item_id']}] ")
        for error in result["errors"]:
            print(f"  - {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
