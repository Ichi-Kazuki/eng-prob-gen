"""Validate Orchestrator provenance records.

Draft 2020-12 schemas own structural validation; Python checks only
cross-record state consistency.

Exit codes: 0 valid, 1 record/schema/semantic failure, 2 runtime failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
_SCHEMAS: dict[str, dict] = {}
VALID_STATES = {
    "GENERATED", "GENERATION_FAILED", "VALIDATION_FAILED", "REVIEWING",
    "REVISE_REQUIRED", "REJECTED", "SOLVING", "ACCEPTED", "MANUAL_REVIEW",
    "DISCARDED",
}
STATES_WHERE_SOLVER_MAY_BE_SET = {"ACCEPTED", "MANUAL_REVIEW", "DISCARDED"}


def schema(name: str) -> dict:
    if name not in _SCHEMAS:
        _SCHEMAS[name] = load_schema(SCHEMA_DIR / name)
    return _SCHEMAS[name]


def load_records(path: Path) -> list[object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        if not isinstance(data["items"], list):
            raise ValueError("$.items must be an array")
        return data["items"]
    if isinstance(data, list):
        return data
    raise ValueError("$ must be an array or an object containing $.items")


def validate_semantics(record: dict, errors: list[str] | None = None) -> list[str]:
    collected = errors if errors is not None else []
    prefix = f"[{record['item_id']}]"
    state = record["state"]
    accepted_item = record["accepted_item"]
    if state not in VALID_STATES:
        collected.append(f"{prefix} $.state: unrecognized Orchestrator state {state!r}")
    if (state == "ACCEPTED") != (accepted_item is not None):
        collected.append(
            f"{prefix} $.accepted_item: must be non-null iff $.state is ACCEPTED"
        )
    if record["consensus"] is not (state == "ACCEPTED"):
        collected.append(f"{prefix} $.consensus: must be true iff $.state is ACCEPTED")
    if not record["state_history"] or record["state_history"][-1] != state:
        collected.append(f"{prefix} $.state_history: final entry must equal $.state")
    if state == "SOLVING":
        collected.append(f"{prefix} $.state: SOLVING is not a final state")
    if record["solver"] is not None and state not in STATES_WHERE_SOLVER_MAY_BE_SET:
        collected.append(
            f"{prefix} $.solver: non-null Solver output is not valid when $.state={state!r}"
        )
    if record["solver"] is not None and "SOLVING" not in record["state_history"]:
        collected.append(
            f"{prefix} $.solver: non-null Solver output requires SOLVING in $.state_history"
        )

    qa = record["qa_audit"]
    for field in ("item_id", "state", "state_history", "revision_count"):
        if qa[field] != record[field]:
            collected.append(f"{prefix} $.qa_audit.{field}: must equal $.{field}")
    for field in ("validation_retry_counts", "system_failure_retry_counts"):
        if qa[field] != record[field]:
            collected.append(f"{prefix} $.qa_audit.{field}: must equal $.{field}")
    return collected


def validate_contract(record: object, errors: list[str] | None = None) -> list[str]:
    collected: list[str] = []
    item_id = record.get("item_id", "?") if isinstance(record, dict) else "?"
    if not isinstance(record, dict):
        collected.append(f"[{item_id}] $: provenance record must be an object")
    else:
        structural = schema_errors(record, schema("provenance.schema.json"))
        collected.extend(f"[{item_id}] provenance.schema.json: {e}" for e in structural)
        if not structural:
            qa_errors = schema_errors(
                record["qa_audit"], schema("qa_audit.schema.json"), "$.qa_audit"
            )
            collected.extend(f"[{item_id}] qa_audit.schema.json: {e}" for e in qa_errors)
            accepted_errors: list[str] = []
            if record["accepted_item"] is not None:
                accepted_errors = schema_errors(
                    record["accepted_item"], schema("accepted_item.schema.json"), "$.accepted_item"
                )
                collected.extend(
                    f"[{item_id}] accepted_item.schema.json: {e}" for e in accepted_errors
                )
            if not qa_errors and not accepted_errors:
                validate_semantics(record, collected)
    if errors is not None:
        errors.extend(collected)
    return collected


validate_record = validate_contract
validate = validate_contract


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        records = load_records(Path(sys.argv[1]))
        errors: list[str] = []
        for record in records:
            validate_contract(record, errors)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[?] $: {exc}")
        return 1

    print(f"Checked {len(records)} provenance record(s).")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("All provenance records passed Draft 2020-12 schema and semantic validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
