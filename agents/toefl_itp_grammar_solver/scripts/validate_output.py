"""Validate TOEFL ITP Independent Solver output.

The committed Draft 2020-12 schema is the structural source of truth. Its
``additionalProperties: false`` rule is the Solver-output allowlist and its
conditionals enforce answer/ambiguity consistency.

Exit codes: 0 valid, 1 output/schema/semantic failure, 2 runtime failure.
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

OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "solver_output.schema.json"
REQUIRED_TOP_KEYS = {
    "item_id", "section", "solver_answer", "confidence", "reason", "ambiguity_detected"
}
ALLOWED_TOP_KEYS = REQUIRED_TOP_KEYS | {"suggested_correction"}
SOLVER_ANSWERS = {"A", "B", "C", "D", "AMBIGUOUS", "NONE"}

_SCHEMA_CACHE: dict | None = None


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
    raise ValueError("$ must be an item object, an array, or an object containing $.items")


def output_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA_CACHE


def validate_semantics(item: dict, errors: list[str] | None = None) -> list[str]:
    """Reserved for cross-field rules not expressible in the schema.

    The current Solver contract expresses every structural and conditional
    rule in Draft 2020-12 JSON Schema, so there is no duplicate Python rule.
    """
    return errors if errors is not None else []


def validate_contract(item: object, errors: list[str] | None = None) -> list[str]:
    collected: list[str] = []
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        collected.append(f"[{item_id}] $: solver result must be an object")
    else:
        structural = schema_errors(item, output_schema())
        collected.extend(
            f"[{item_id}] {OUTPUT_SCHEMA_PATH.name}: {message}" for message in structural
        )
        if not structural:
            validate_semantics(item, collected)
    if errors is not None:
        errors.extend(collected)
    return collected


validate_item = validate_contract
validate = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        items = load_items(Path(sys.argv[1]))
        errors: list[str] = []
        section_counts = {"Structure": 0, "Written Expression": 0}
        answer_counts = {answer: 0 for answer in SOLVER_ANSWERS}
        for item in items:
            if isinstance(item, dict):
                if item.get("section") in section_counts:
                    section_counts[item["section"]] += 1
                if item.get("solver_answer") in answer_counts:
                    answer_counts[item["solver_answer"]] += 1
            validate_contract(item, errors)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[?] $: {exc}")
        return 1

    print(f"Checked {len(items)} item(s): sections={section_counts} answers={answer_counts}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("All items passed Draft 2020-12 schema and semantic validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
