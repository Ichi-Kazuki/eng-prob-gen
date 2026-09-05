"""Deterministic Structure v0.3 planning built on top of the frozen v0.1 Planner.

The v0.3 Planner performs NO independent sampling. It calls the frozen
structure.planner.build_plan(seed) for its empirical distributions and RNG
sequence, then deep-transforms only version/identity metadata into the v0.3
shape. Every Planner-owned per-item sampled value (order, section,
primary_target, difficulty, clause_count, sentence_length_bin,
target_word_count) is copied unchanged from the v0.1 plan. No shard_id,
domain_pool, or other Generator-sharding metadata is added to the plan: shard
partitioning is a fixed pipeline-owned slice of the completed plan, not a
Planner-owned field.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import structure.planner as v01_planner
from shared.schema_validation import load_schema, schema_errors


STRUCTURE_VERSION = "v0.3"
SCHEMA_VERSION = "structure-plan-v0.3"
QUESTION_COUNT = 15
PLAN_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "plan.schema.json"


def _validate_seed(seed: int) -> None:
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("Structure v0.3 seed must be a non-negative integer")


def _transform_item(v01_item: dict[str, Any], seed: int) -> dict[str, Any]:
    order = v01_item["order"]
    transformed = copy.deepcopy(v01_item)
    transformed["item_id"] = f"structure-v03-{seed:016x}-{order:02d}"
    return transformed


def build_plan(seed: int) -> dict[str, Any]:
    """Build the complete replayable 15-item Structure v0.3 plan.

    Reuses the frozen v0.1 Planner's sampling behavior exactly: every
    Planner-owned sampled field is copied unchanged from
    structure.planner.build_plan(seed). Only version/identity metadata is
    transformed. No new RNG call, weighted draw, or profile table is used.
    """

    _validate_seed(seed)
    v01_plan = v01_planner.build_plan(seed)

    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": f"structure-plan-v0.3-{seed:016x}",
        "version": STRUCTURE_VERSION,
        "seed": v01_plan["seed"],
        "question_count": QUESTION_COUNT,
        "items": [_transform_item(item, seed) for item in v01_plan["items"]],
    }

    errors = schema_errors(plan, load_schema(PLAN_SCHEMA_PATH))
    if errors:
        raise ValueError(
            "internal Structure v0.3 planner output failed schema validation: " + "; ".join(errors)
        )

    expected_ids = [f"structure-v03-{seed:016x}-{order:02d}" for order in range(1, QUESTION_COUNT + 1)]
    actual_ids = [item["item_id"] for item in plan["items"]]
    if actual_ids != expected_ids:
        raise ValueError("internal Structure v0.3 planner produced an unexpected item_id sequence")

    orders = [item["order"] for item in plan["items"]]
    if orders != list(range(1, QUESTION_COUNT + 1)):
        raise ValueError("internal Structure v0.3 planner produced an unexpected order sequence")

    if plan["plan_id"] != f"structure-plan-v0.3-{seed:016x}":
        raise ValueError("internal Structure v0.3 planner produced an unexpected plan_id")
    if plan["schema_version"] != SCHEMA_VERSION:
        raise ValueError("internal Structure v0.3 planner produced an unexpected schema_version")
    if plan["version"] != STRUCTURE_VERSION:
        raise ValueError("internal Structure v0.3 planner produced an unexpected version")

    return plan


def plan_for_seed(seed: int) -> dict[str, Any]:
    """Compatibility alias for callers that name the operation explicitly."""

    return build_plan(seed)


__all__ = ["build_plan", "plan_for_seed", "STRUCTURE_VERSION", "SCHEMA_VERSION", "QUESTION_COUNT"]
