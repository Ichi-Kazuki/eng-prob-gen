"""Validate final provenance artifacts with canonical schemas and semantics."""

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

SCHEMA_DIR = REPO_ROOT / "orchestrator" / "schemas"
VALID_STATES = {
    "GENERATED", "GENERATION_FAILED", "VALIDATION_FAILED", "REVIEWING",
    "REVISE_REQUIRED", "REJECTED", "SOLVING", "ACCEPTED", "MANUAL_REVIEW", "DISCARDED",
}
TERMINAL_STATES = {"REJECTED", "ACCEPTED", "MANUAL_REVIEW", "DISCARDED"}
_SCHEMAS: dict[str, dict] = {}


def load_records(path: Path) -> list[object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        if not isinstance(data["items"], list):
            raise ValueError("$.items must be an array")
        return data["items"]
    if isinstance(data, list):
        return data
    raise ValueError("top-level JSON must be an array or an object containing items")


def _schema(name: str) -> dict:
    if name not in _SCHEMAS:
        _SCHEMAS[name] = load_schema(SCHEMA_DIR / name)
    return _SCHEMAS[name]


def validate_contract(record: object, errors: list[str] | None = None) -> list[str]:
    collected: list[str] = []
    item_id = record.get("item_id", "?") if isinstance(record, dict) else "?"
    prefix = f"[{item_id}]"
    if not isinstance(record, dict):
        collected.append(f"{prefix} $: provenance record must be an object")
    else:
        structural = schema_errors(record, _schema("provenance.schema.json"))
        collected.extend(f"{prefix} provenance.schema.json: {error}" for error in structural)
        if isinstance(record.get("qa_audit"), dict):
            collected.extend(
                f"{prefix} qa_audit.schema.json: {error}"
                for error in schema_errors(record["qa_audit"], _schema("qa_audit.schema.json"))
            )
        if record.get("accepted_item") is not None:
            collected.extend(
                f"{prefix} accepted_item.schema.json: {error}"
                for error in schema_errors(record["accepted_item"], _schema("accepted_item.schema.json"))
            )

        state = record.get("state")
        if state not in VALID_STATES:
            collected.append(f"{prefix} $.state: unrecognized state {state!r}")
        # Replay artifacts may intentionally capture a candidate parked at
        # REVISE_REQUIRED. Finalization drivers enforce that only terminal
        # states are emitted; this validator additionally rejects SOLVING,
        # which must never be persisted as a final provenance record.
        if state == "SOLVING":
            collected.append(f"{prefix} $.state: SOLVING is a transient in-flight state")
        accepted = record.get("accepted_item")
        if (state == "ACCEPTED") != (accepted is not None):
            collected.append(f"{prefix} $.accepted_item: non-null iff state is ACCEPTED")
        if record.get("consensus") is not (state == "ACCEPTED"):
            collected.append(f"{prefix} $.consensus: must equal state == ACCEPTED")
        if "planned_slot" in record and record.get("batch_slot") != record.get("planned_slot"):
            collected.append(f"{prefix} $.batch_slot: must equal planned_slot when both are present")
        history = record.get("state_history")
        if not isinstance(history, list) or not history or history[-1] != state:
            collected.append(f"{prefix} $.state_history: last entry must equal state")
        qa = record.get("qa_audit")
        if isinstance(qa, dict):
            if qa.get("state") != state or qa.get("state_history") != history:
                collected.append(f"{prefix} $.qa_audit: state and state_history must mirror provenance")
        solver_states = {"ACCEPTED", "MANUAL_REVIEW", "DISCARDED"}
        if state not in solver_states and record.get("solver") is not None:
            collected.append(f"{prefix} $.solver: Solver output is not valid before terminal Solver routing")
    if errors is not None:
        errors.extend(collected)
    return collected


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
