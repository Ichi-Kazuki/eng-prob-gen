"""Validate Generator output against the canonical Draft 2020-12 schemas."""

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
SECTION_SCHEMAS = {
    "Structure": SCHEMA_DIR / "structure_item.schema.json",
    "Written Expression": SCHEMA_DIR / "written_expression_item.schema.json",
}
ERROR_SCOPES = {"local", "clause_level", "sentence_level", "cross_clause"}
DIFFICULTY_TIERS = {"EASY", "MEDIUM", "HARD"}
_SCHEMAS: dict[str, dict] = {}


def load_taxonomy_values() -> tuple[set[str], set[str]]:
    spec = json.loads(SPEC_JSON.read_text(encoding="utf-8"))
    return (
        {entry["id"] for entry in spec["primary_targets"]},
        {entry["id"] for entry in spec["tested_error_types"]},
    )


taxonomy_values = load_taxonomy_values


def load_items(path: Path) -> list[object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        if not isinstance(data["items"], list):
            raise ValueError("$.items must be an array")
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("top-level JSON must be an item, an array, or an object containing items")


def _schema(section: str) -> dict:
    if section not in _SCHEMAS:
        _SCHEMAS[section] = load_schema(SECTION_SCHEMAS[section])
    return _SCHEMAS[section]


def validate_semantics(item: dict, primary_targets: set[str], tested_error_types: set[str]) -> list[str]:
    errors: list[str] = []
    prefix = f"[{item.get('item_id', '?')}]"
    if item.get("primary_target") not in primary_targets:
        errors.append(f"{prefix} $.primary_target: not in taxonomy")
    if item.get("section") == "Written Expression":
        tested_error_type = item.get("tested_error_type")
        if tested_error_type not in tested_error_types:
            errors.append(f"{prefix} $.tested_error_type: not in taxonomy")
        if tested_error_type == "fragment":
            errors.append(f"{prefix} $.tested_error_type: fragment is not valid for Written Expression")
        if tested_error_type == "wrong_complementation":
            errors.append(
                f"{prefix} $.tested_error_type: wrong_complementation was superseded by "
                "wrong_preposition_collocation"
            )
        if item.get("error_scope") not in ERROR_SCOPES:
            errors.append(f"{prefix} $.error_scope: invalid error scope")
    if item.get("section") == "Structure" and item.get("correct_answer") not in item.get("options", {}):
        errors.append(f"{prefix} $.correct_answer: does not reference $.options")
    if item.get("section") == "Written Expression" and item.get("correct_answer") not in item.get("marked_parts", {}):
        errors.append(f"{prefix} $.correct_answer: does not reference $.marked_parts")
    return errors


def validate_contract(
    item: object,
    primary_targets: set[str] | None = None,
    tested_error_types: set[str] | None = None,
    errors: list[str] | None = None,
) -> list[str]:
    if isinstance(primary_targets, list) and errors is None and tested_error_types is None:
        errors = primary_targets
        primary_targets = None
    collected: list[str] = []
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        collected.append(f"[{item_id}] $: generated item must be an object")
    else:
        section = item.get("section")
        if section not in SECTION_SCHEMAS:
            collected.append(f"[{item_id}] $.section: must be 'Structure' or 'Written Expression'")
        else:
            structural = schema_errors(item, _schema(section))
            collected.extend(f"[{item_id}] {SECTION_SCHEMAS[section].name}: {error}" for error in structural)
            if not structural:
                targets, error_types = primary_targets or load_taxonomy_values()
                collected.extend(validate_semantics(item, targets, error_types))
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
