"""Build the fresh WE v2.1 format-only 15-item re-smoke.

This artifact deliberately has no Reviewer or Solver records.  It is a fresh
format-planning sample authored for this re-smoke, not a replay of the v2.0 or
v2.0.1 cohorts.  Grammar quality remains NOT_EVALUATED because no independent
Agent runtime is available in this workspace.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis" / "we_v2_1_smoke"
sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))

from format_planner import (  # noqa: E402
    get_official_profile,
    plan_summary,
    pre_emission_checks,
    sample_format_plan,
    select_span_set,
)
from validate_format import format_diagnostics, load_json  # noqa: E402


SMOKE_SEED = 1002
BATCH_ID = "we-v2.1-format-resmoke-20260825"
CONFIG_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "config" / "we_v2_format_config.json"


# Freshly authored format fixtures.  The grammar locus is retained only as a
# location anchor for span selection; no grammar verdict is asserted here.
FRESH_ITEMS: list[dict[str, str]] = [
    {
        "id": "we-v2.1-resmoke-001",
        "sentence": "The coastal observatory records seasonal changes in ocean temperature and salinity for researchers studying long-term climate patterns across remote northern waters each winter.",
        "correct_span": "records",
    },
    {
        "id": "we-v2.1-resmoke-002",
        "sentence": "Several mineral samples require careful labeling before technicians transport them to the laboratory, where specialists compare their composition with regional geological surveys annually.",
        "correct_span": "require",
    },
    {
        "id": "we-v2.1-resmoke-003",
        "sentence": "Researchers observed that island birds were nesting earlier during the unusually warm spring season near coastal wetlands.",
        "correct_span": "were nesting",
    },
    {
        "id": "we-v2.1-resmoke-004",
        "sentence": "The municipal survey identifies several neighborhoods where aging drainage systems increase flood risk during intense summer storms near the river and threaten nearby schools, markets, and public transit routes after heavy rainfall.",
        "correct_span": "increase",
    },
    {
        "id": "we-v2.1-resmoke-005",
        "sentence": "Historical maps reveal that inland trade routes were altered after railway construction.",
        "correct_span": "were altered",
    },
    {
        "id": "we-v2.1-resmoke-006",
        "sentence": "Because the instrument measures pressure continuously, engineers can detect small changes before mechanical failures interrupt production at the remote facility during winter operations.",
        "correct_span": "measures",
    },
    {
        "id": "we-v2.1-resmoke-007",
        "sentence": "The botanical collection includes specimens that were gathered from high elevations and preserved under carefully controlled conditions for future genetic studies and ecological comparisons.",
        "correct_span": "genetic studies",
    },
    {
        "id": "we-v2.1-resmoke-008",
        "sentence": "When the revised protocol reaches every participating clinic, public health officials expect reporting accuracy to improve across rural districts during the following year.",
        "correct_span": "reporting accuracy",
    },
    {
        "id": "we-v2.1-resmoke-009",
        "sentence": "The engineering team tested a lighter alloy that withstands repeated heating without losing structural strength during extended laboratory simulations under controlled conditions.",
        "correct_span": "that withstands",
    },
    {
        "id": "we-v2.1-resmoke-010",
        "sentence": "Researchers analyzing sediment layers found evidence of ancient floods that may explain unexpected changes in the valley's agricultural history.",
        "correct_span": "found",
    },
    {
        "id": "we-v2.1-resmoke-011",
        "sentence": "The museum archive contains records that clarify how the settlement developed along the northern river.",
        "correct_span": "contains",
    },
    {
        "id": "we-v2.1-resmoke-012",
        "sentence": "The archive clearly shows how the settlement was altered.",
        "correct_span": "was altered",
    },
    {
        "id": "we-v2.1-resmoke-013",
        "sentence": "The committee reviewed population projections before recommending a phased expansion of the university campus near the district boundary.",
        "correct_span": "reviewed",
    },
    {
        "id": "we-v2.1-resmoke-014",
        "sentence": "Although the first experiment produced inconsistent results, the research group repeated the procedure with controls and recorded each observation for comparison across three trials.",
        "correct_span": "repeated",
    },
    {
        "id": "we-v2.1-resmoke-015",
        "sentence": "The museum plans to restore several paintings before the traveling exhibition opens in neighboring cities next spring for visiting scholars and local audiences.",
        "correct_span": "restore several",
    },
]


def _median(values: list[float | int]) -> float | int:
    return statistics.median(values)


def _format_status(diagnostics: dict[str, Any]) -> str:
    return diagnostics["format_band_status"]


def build_items() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    profile = get_official_profile()
    config = load_json(CONFIG_PATH)
    plan_rng = random.Random(SMOKE_SEED)
    items: list[dict[str, Any]] = []
    for order, source in enumerate(FRESH_ITEMS, start=1):
        plan = sample_format_plan(plan_rng, profile)
        selection_rng = random.Random(SMOKE_SEED + order)
        selection = select_span_set(source["sentence"], source["correct_span"], plan, selection_rng, profile)
        anchor = selection.spans[selection.correct_index]
        conformance = pre_emission_checks(source["sentence"], selection.spans, plan, anchor)
        if not conformance["valid"]:
            raise ValueError(f"{source['id']} pre-emission check failed: {conformance}")

        marked_parts = {
            label: selection.spans[index].text
            for index, label in enumerate(("A", "B", "C", "D"))
        }
        span_types = {
            label: selection.spans[index].span_type
            for index, label in enumerate(("A", "B", "C", "D"))
        }
        format_input = {
            "sentence": source["sentence"],
            "marked_parts": marked_parts,
            "correct_answer": selection.correct_answer,
            "grammar_metadata": {
                "correct_span_type": anchor.span_type,
                "correction_locality": "NOT_EVALUATED",
                "decision_granularity": "NOT_EVALUATED",
            },
            "format_metadata": {"span_types": span_types},
        }
        diagnostics, errors = format_diagnostics(format_input, config)
        if errors:
            raise ValueError(f"{source['id']} validator errors: {errors}")
        items.append({
            "item_id": source["id"],
            "generation_order": order,
            "sentence": source["sentence"],
            "marked_parts": marked_parts,
            "correct_answer": selection.correct_answer,
            "span_types": span_types,
            "grammar_quality": "NOT_EVALUATED",
            "plan": plan_summary(plan, profile),
            "pre_emission": conformance,
            "format": diagnostics,
            "selection": {
                "candidate_scope": selection.candidate_scope,
                "score": round(selection.score, 4),
                "correct_index": selection.correct_index,
            },
        })

    metrics = build_metrics(items, profile)
    return items, metrics


def build_metrics(items: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    def values(key: str) -> list[Any]:
        return [item["format"][key] for item in items]

    span_counts = Counter(
        str(length)
        for item in items
        for length in item["format"]["span_word_counts"].values()
    )
    correct_types = Counter(item["format"]["correct_span_type"] for item in items)
    answer_positions = Counter(item["correct_answer"] for item in items)
    gap_medians = {
        key: _median([item["format"][key] for item in items])
        for key in ("gap_A_B", "gap_B_C", "gap_C_D")
    }
    metric_statuses = Counter(_format_status(item["format"]) for item in items)
    multi_tail = sum(
        sum(status == "EXTREME" for status in item["format"]["metric_band_status"].values()) >= 2
        for item in items
    )
    zero_gap_items = sum(
        any(item["format"][key] == 0 for key in ("gap_A_B", "gap_B_C", "gap_C_D"))
        for item in items
    )
    official_items = profile["item_geometry"]
    return {
        "item_count": len(items),
        "grammar_quality": "NOT_EVALUATED",
        "sentence_word_count": {
            "median": _median(values("sentence_word_count")),
            "min": min(values("sentence_word_count")),
            "max": max(values("sentence_word_count")),
            "under_15_count": sum(value < 15 for value in values("sentence_word_count")),
        },
        "coverage": {"median": _median(values("marked_coverage_ratio")), "ge_0_60_count": sum(value >= 0.60 for value in values("marked_coverage_ratio")), "full_coverage_count": sum(value >= 1.0 for value in values("marked_coverage_ratio"))},
        "unmarked_context": {"median": _median(values("unmarked_word_count")), "zero_count": sum(value == 0 for value in values("unmarked_word_count"))},
        "span_word_count_distribution": dict(sorted(span_counts.items(), key=lambda pair: int(pair[0]))),
        "correct_span_type_distribution": dict(correct_types),
        "correct_answer_position_distribution": dict(answer_positions),
        "correct_span_word_count": {"median": _median([item["format"]["correct_span_word_count"] for item in items]), "five_plus_count": sum(item["format"]["correct_span_word_count"] > 4 for item in items)},
        "gap_medians": gap_medians,
        "zero_gap_item_count": zero_gap_items,
        "zero_gap_rate": zero_gap_items / len(items),
        "format_band_counts": dict(metric_statuses),
        "multi_tail_extreme_count": multi_tail,
        "official_geometry_source_item_count": len(official_items),
    }


def build_output(items: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_version": "WE_V2_1_FORMAT_RESMOKE_1.0",
        "run": {
            "agent_version": "Written Expression Generator v2.1",
            "batch_id": BATCH_ID,
            "generation_unit": "one fresh item per microbatch",
            "item_count": len(items),
            "historical_cohort_reused": False,
            "grammar_quality": "NOT_EVALUATED",
            "independent_agent_runtime_available": False,
            "source_of_truth": "analysis/we_format/written_expression_format_official.json",
        },
        "policy": {
            "grammar_generation": "unchanged",
            "changed_surface": "format planner + span-selection policy only",
            "normal_max_span_words": 4,
            "normal_min_gap": 1,
            "band_thresholds_changed": False,
        },
        "format_validation": {
            "validator": "format_diagnostics direct pre-emission validation",
            "valid_count": len(items),
            "invalid_count": 0,
            "grammar_contract_validation": "NOT_RUN; grammar quality is NOT_EVALUATED",
        },
        "official": {
            "item_count": 125,
            "sentence_median": 20,
            "coverage_median": 0.2632,
            "unmarked_median": 15,
            "correct_span_type_distribution": {"SINGLE_WORD": 98, "SHORT_PHRASE": 12, "CLAUSE_OR_CLAUSE_LIKE": 15},
            "correct_answer_position_distribution": {"A": 24, "B": 37, "C": 31, "D": 33},
            "gap_medians": {"gap_A_B": 4, "gap_B_C": 4, "gap_C_D": 4},
            "zero_gap_item_rate": 0.0,
            "five_plus_span_count": 0,
        },
        "v2_validation": {
            "source": "analysis/we_v2_validation/we_v2_format_drift_root_cause.json",
            "item_count": 75,
            "sentence_median": 14,
            "coverage_median": 0.4,
            "unmarked_median": 8,
            "span_word_count_distribution": {"1": 205, "2": 79, "3": 7, "5": 8, "6": 1},
            "correct_span_type_distribution": {"SINGLE_WORD": 22, "SHORT_PHRASE": 44, "CLAUSE_OR_CLAUSE_LIKE": 9},
            "correct_answer_position_distribution": {"A": 14, "B": 26, "C": 30, "D": 5},
            "gap_medians": {"gap_A_B": 1, "gap_B_C": 2, "gap_C_D": 3},
            "zero_gap_item_rate": 0.5333,
            "five_plus_span_count": 9,
            "multi_tail_count": 6,
        },
        "v2_1_resmoke": metrics,
        "items": items,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    items, metrics = build_items()
    output = build_output(items, metrics)
    output_path = OUT / "we_v2_1_format_resmoke.json"
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "metrics": metrics}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
