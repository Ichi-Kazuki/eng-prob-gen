"""Deterministic planning for the isolated Reading v0.1 contract."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from shared.schema_validation import load_schema, schema_errors


ALLOWED_DOMAINS = (
    "biology",
    "geology",
    "astronomy",
    "anthropology",
    "history",
    "ecology",
    "technology",
    "earth science",
)
QUESTION_TYPES = (
    "DETAIL",
    "VOCABULARY_IN_CONTEXT",
    "INFERENCE",
    "MAIN_IDEA",
    "REFERENCE",
)
PLAN_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reading_plan.schema.json"


def build_plan(seed: int, domain: str | None = None) -> dict[str, Any]:
    """Build a replayable plan without an LLM invocation."""

    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if domain is not None and domain not in ALLOWED_DOMAINS:
        raise ValueError(f"unsupported Reading domain: {domain!r}")
    rng = random.Random(seed)
    selected_domain = domain or rng.choice(ALLOWED_DOMAINS)
    target_words = rng.choice((280, 300, 320))
    plan = {
        "schema_version": "reading-plan-v0.1",
        "plan_id": f"rp-{seed:08x}",
        "seed": seed,
        "domain": selected_domain,
        "target_words": target_words,
        "target_paragraphs": 4,
        "question_plan": list(QUESTION_TYPES),
    }
    errors = schema_errors(plan, load_schema(PLAN_SCHEMA_PATH))
    if errors:
        raise ValueError("internal planner output failed schema validation: " + "; ".join(errors))
    return plan
