"""Validate TOEFL ITP Generator output.

The committed Draft 2020-12 schemas are the structural source of truth.
Python checks are limited to cross-field semantics that schemas do not make
convenient to express.

Exit codes: 0 valid, 1 candidate/schema/semantic failure, 2 runtime failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)

SPEC_JSON = REPO_ROOT / "specs" / "toefl_itp_grammar_spec.json"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"
SECTION_SCHEMA_PATHS = {
    "Structure": SCHEMA_DIR / "structure_item.schema.json",
    "Written Expression": SCHEMA_DIR / "written_expression_item.schema.json",
}

_SCHEMA_CACHE: dict[str, dict] = {}


def load_taxonomy_values() -> tuple[set[str], set[str]]:
    """Compatibility helper for callers that inspect the specification."""
    spec = json.loads(SPEC_JSON.read_text(encoding="utf-8"))
    return (
        {entry["id"] for entry in spec["primary_targets"]},
        {entry["id"] for entry in spec["tested_error_types"]},
    )


def taxonomy_values() -> tuple[set[str], set[str]]:
    return load_taxonomy_values()


def load_items(path: Path) -> list[object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
        if not isinstance(items, list):
            raise ValueError("$.items must be an array")
        return items
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("$ must be an item object, an array, or an object containing $.items")


def section_schema(section: object) -> tuple[dict | None, Path | None]:
    path = SECTION_SCHEMA_PATHS.get(section) if isinstance(section, str) else None
    if path is None:
        return None, None
    if section not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[section] = load_schema(path)
    return _SCHEMA_CACHE[section], path


def validate_structure_item(item: dict, _primary_targets: object, errors: list[str]) -> None:
    """Cross-field checks only; structural rules belong to JSON Schema."""
    answer = item["correct_answer"]
    if answer not in item["options"]:
        errors.append(f"[{item['item_id']}] $.correct_answer: does not reference $.options")


def validate_written_expression_item(
    item: dict,
    _primary_targets: object,
    _tested_error_types: object,
    errors: list[str],
) -> None:
    """Cross-field checks only; structural rules belong to JSON Schema."""
    answer = item["correct_answer"]
    if answer not in item["marked_parts"]:
        errors.append(f"[{item['item_id']}] $.correct_answer: does not reference $.marked_parts")


def validate_semantics(
    item: dict,
    primary_targets: object = None,
    tested_error_types: object = None,
    errors: list[str] | None = None,
) -> list[str]:
    collected = errors if errors is not None else []
    if item["section"] == "Structure":
        validate_structure_item(item, primary_targets, collected)
    else:
        validate_written_expression_item(item, primary_targets, tested_error_types, collected)
    return collected


def validate_contract(
    item: object,
    primary_targets: object = None,
    tested_error_types: object = None,
    errors: list[str] | None = None,
) -> list[str]:
    collected: list[str] = []
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        collected.append(f"[{item_id}] $: generated item must be an object")
    else:
        schema, schema_path = section_schema(item.get("section"))
        if schema is None:
            collected.append(
                f"[{item_id}] $.section: must be 'Structure' or 'Written Expression', "
                f"got {item.get('section')!r}"
            )
        else:
            structural = schema_errors(item, schema)
            collected.extend(
                f"[{item_id}] {schema_path.name}: {message}" for message in structural
            )
            if not structural:
                validate_semantics(item, primary_targets, tested_error_types, collected)
    if errors is not None:
        errors.extend(collected)
    return collected


validate = validate_contract
validate_item = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        items = load_items(Path(sys.argv[1]))
        errors: list[str] = []
        counts = {"Structure": 0, "Written Expression": 0}
        for item in items:
            if isinstance(item, dict) and item.get("section") in counts:
                counts[item["section"]] += 1
            validate_contract(item, errors=errors)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[?] $: {exc}")
        return 1

    print(f"Checked {len(items)} item(s): {counts}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("All items passed Draft 2020-12 schema and semantic validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
