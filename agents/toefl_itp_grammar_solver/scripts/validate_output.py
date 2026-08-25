"""Validate Solver output against the canonical Draft 2020-12 schema."""

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

OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "solver_output.schema.json"
REQUIRED_TOP_KEYS = {
    "item_id", "section", "solver_answer", "confidence", "reason", "ambiguity_detected"
}
ALLOWED_TOP_KEYS = REQUIRED_TOP_KEYS | {"suggested_correction"}
_SCHEMA: dict | None = None


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


def output_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA


def validate_contract(item: object, errors: list[str] | None = None) -> list[str]:
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        collected = [f"[{item_id}] $: solver result must be an object"]
    else:
        collected = [
            f"[{item_id}] {OUTPUT_SCHEMA_PATH.name}: {error}"
            for error in schema_errors(item, output_schema())
        ]
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
        sections = {"Structure": 0, "Written Expression": 0}
        answers = {answer: 0 for answer in ("A", "B", "C", "D", "AMBIGUOUS", "NONE")}
        for item in items:
            if isinstance(item, dict):
                if item.get("section") in sections:
                    sections[item["section"]] += 1
                if item.get("solver_answer") in answers:
                    answers[item["solver_answer"]] += 1
            validate_contract(item, errors)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[?] $: {exc}")
        return 1
    print(f"Checked {len(items)} item(s): sections={sections} answers={answers}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("All items passed Draft 2020-12 schema validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
