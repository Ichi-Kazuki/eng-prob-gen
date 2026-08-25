"""Shared Generator validation helpers for the WE v2 pilot stages."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GENERATOR_SCRIPTS = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"
if str(GENERATOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(GENERATOR_SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validate_format import load_json, validate_item  # noqa: E402
from shared.schema_validation import schema_errors  # noqa: E402


def plan_mismatches(item: dict[str, Any], slot: dict[str, Any] | None) -> list[str]:
    """Compare an item with its plan slot, including revised metadata."""

    if not slot:
        return []
    mismatches: list[str] = []
    for plan_key, item_key in (
        ("primary_target", "primary_target"),
        ("subtype", "subtype"),
        ("tested_error_type", "tested_error_type"),
        ("difficulty", "difficulty"),
        ("vocabulary_domain", "vocabulary_domain"),
    ):
        if slot.get(plan_key) != item.get(item_key):
            mismatches.append(f"{item_key}: plan={slot.get(plan_key)!r} item={item.get(item_key)!r}")

    if slot.get("planned_correct_position") != item.get("correct_answer"):
        mismatches.append(
            "correct_answer: "
            f"plan={slot.get('planned_correct_position')} item={item.get('correct_answer')}"
        )

    grammar_metadata = item.get("grammar_metadata")
    if not isinstance(grammar_metadata, dict):
        return mismatches + ["grammar_metadata must be an object"]
    for plan_key in ("correction_locality", "decision_granularity"):
        if slot.get(plan_key) != grammar_metadata.get(plan_key):
            mismatches.append(
                f"grammar_metadata.{plan_key}: "
                f"plan={slot.get(plan_key)!r} item={grammar_metadata.get(plan_key)!r}"
            )
    return mismatches


def validate_generator_item(
    item: Any,
    slot: dict[str, Any] | None,
    item_schema: dict[str, Any],
    config: dict[str, Any],
    targets: set[str],
    error_types: set[str],
) -> dict[str, Any]:
    """Return a non-throwing validation record for one final-cohort item."""

    item_dict = item if isinstance(item, dict) else {}
    schema_result = schema_errors(item, item_schema)
    try:
        format_result = validate_item(item, config, targets, error_types)
    except Exception as exc:  # malformed input must fail closed, not abort finalization
        format_result = {
            "valid": False,
            "errors": [f"format validator exception: {type(exc).__name__}: {exc}"],
            "diagnostics": {},
        }
    provenance = item_dict.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return {
        "item_id": item_dict.get("item_id", "?"),
        "item_generation_order": provenance.get("item_generation_order"),
        "microbatch_id": provenance.get("microbatch_id"),
        "generator_schema_pass": not schema_result,
        "generator_schema_errors": schema_result,
        "format_validator_pass": format_result.get("valid", False),
        "format_validator_errors": format_result.get("errors", []),
        "plan_conformance_pass": not plan_mismatches(item_dict, slot),
        "plan_mismatches": plan_mismatches(item_dict, slot),
        "diagnostics": format_result.get("diagnostics", {}),
    }


def build_validation_report(
    items: list[dict[str, Any]],
    plan: dict[str, Any],
    item_schema: dict[str, Any],
    config: dict[str, Any],
    targets: set[str],
    error_types: set[str],
    *,
    run_id: str,
    stage: str,
    source_items: str,
) -> dict[str, Any]:
    """Validate the complete cohort and return the recorded aggregate shape."""

    slots = {slot["item_id"]: slot for slot in plan.get("slots", [])}
    records = [
        validate_generator_item(
            item,
            slots.get(item.get("item_id") if isinstance(item, dict) else None),
            item_schema,
            config,
            targets,
            error_types,
        )
        for item in items
    ]
    return {
        "validator": "TOEFL ITP WE deterministic format validator v2.0",
        "config": config.get("config_id"),
        "run_id": run_id,
        "validation_stage": stage,
        "source_items": source_items,
        "item_count": len(records),
        "generator_schema_pass": sum(r["generator_schema_pass"] for r in records),
        "format_validator_pass": sum(r["format_validator_pass"] for r in records),
        "plan_conformance_pass": sum(r["plan_conformance_pass"] for r in records),
        "items": records,
    }
