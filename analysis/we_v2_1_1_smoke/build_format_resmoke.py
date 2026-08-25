"""Build the fresh WE v2.1.1 format-only 15-item re-smoke.

The sentences in this file are a new cohort and are not copied from the v2.1
pilot or v2.1 smoke artifacts.  No Reviewer/Solver result is synthesized;
grammar quality remains NOT_EVALUATED.
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
OUT = ROOT / "analysis" / "we_v2_1_1_smoke"
sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))

from format_planner import (  # noqa: E402
    get_official_profile,
    plan_summary,
    pre_emission_checks,
    sample_format_plan,
    select_span_set,
)
from validate_format import format_diagnostics, load_json  # noqa: E402


SMOKE_SEED = 1101
BATCH_ID = "we-v2.1.1-format-resmoke-20260825"
CONFIG_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "config" / "we_v2_format_config.json"
HISTORICAL_SOURCES = (
    ROOT / "analysis" / "we_v2_1_smoke" / "we_v2_1_format_resmoke.json",
    ROOT / "analysis" / "we_v2_1_pilot" / "we_v2_1_25_item_pilot.json",
)


FRESH_ITEMS: list[dict[str, str]] = [
    {
        "id": "we-v2.1.1-resmoke-001",
        "sentence": "The coastal monitoring station records monthly shifts in water temperature and salinity for scientists studying remote northern marshes throughout winter.",
        "correct_span": "records",
    },
    {
        "id": "we-v2.1.1-resmoke-002",
        "sentence": "Several mineral specimens require precise labels before laboratory technicians transport them for comparison with regional geological surveys during the annual fieldwork.",
        "correct_span": "require",
    },
    {
        "id": "we-v2.1.1-resmoke-003",
        "sentence": "Field researchers observed that migratory birds were nesting earlier during an unusually warm spring near protected coastal wetlands during the spring migration period.",
        "correct_span": "were nesting",
    },
    {
        "id": "we-v2.1.1-resmoke-004",
        "sentence": "The municipal assessment identifies districts where aging drainage systems increase flood risk during severe summer storms beside the river throughout the year.",
        "correct_span": "identifies",
    },
    {
        "id": "we-v2.1.1-resmoke-005",
        "sentence": "Historical maps reveal that inland trade routes were altered after railway construction across a northern valley during the subsequent decade.",
        "correct_span": "were altered",
    },
    {
        "id": "we-v2.1.1-resmoke-006",
        "sentence": "Because the instrument measures pressure continuously, engineers can detect subtle changes before mechanical failures interrupt production at a remote facility during extended winter monitoring operations.",
        "correct_span": "measures",
    },
    {
        "id": "we-v2.1.1-resmoke-007",
        "sentence": "The botanical collection includes specimens that were gathered from high elevations and preserved under carefully controlled conditions for later ecological studies.",
        "correct_span": "includes",
    },
    {
        "id": "we-v2.1.1-resmoke-008",
        "sentence": "When the revised protocol reaches every participating clinic, public health officials expect reporting accuracy to improve across isolated rural districts during the following calendar year nationwide.",
        "correct_span": "reporting accuracy",
    },
    {
        "id": "we-v2.1.1-resmoke-009",
        "sentence": "The engineering team tested a lighter alloy that withstands repeated heating without losing structural strength during extended laboratory simulations under carefully controlled conditions.",
        "correct_span": "withstands",
    },
    {
        "id": "we-v2.1.1-resmoke-010",
        "sentence": "Sediment researchers found evidence of ancient floods that may explain unexpected changes in the valley's agricultural history after droughts.",
        "correct_span": "found",
    },
    {
        "id": "we-v2.1.1-resmoke-011",
        "sentence": "The museum archive contains documents that clarify how the settlement developed beside the northern river over several generations of stewardship.",
        "correct_span": "contains",
    },
    {
        "id": "we-v2.1.1-resmoke-012",
        "sentence": "A municipal archive clearly shows how the settlement was altered after improved roads connected the valley with nearby agricultural districts.",
        "correct_span": "was altered",
    },
    {
        "id": "we-v2.1.1-resmoke-013",
        "sentence": "The planning committee reviewed recently updated population projections before recommending a phased expansion of the university campus near the district boundary next autumn.",
        "correct_span": "reviewed",
    },
    {
        "id": "we-v2.1.1-resmoke-014",
        "sentence": "Although the first trial produced inconsistent results, the research group repeated the procedure with controls during three trials.",
        "correct_span": "repeated",
    },
    {
        "id": "we-v2.1.1-resmoke-015",
        "sentence": "The city museum plans to restore several paintings before its traveling exhibition opens in neighboring cities next spring for visiting scholars and local audiences.",
        "correct_span": "several paintings",
    },
]


def _median(values: list[float | int]) -> float | int:
    return statistics.median(values)


def _collect_sentences(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        sentence = value.get("sentence")
        if isinstance(sentence, str):
            found.add(sentence)
        for child in value.values():
            found.update(_collect_sentences(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_sentences(child))
    return found


def historical_exact_matches() -> list[str]:
    historical: set[str] = set()
    for path in HISTORICAL_SOURCES:
        if path.exists():
            historical.update(_collect_sentences(json.loads(path.read_text(encoding="utf-8"))))
    return sorted(item["sentence"] for item in FRESH_ITEMS if item["sentence"] in historical)


def _coherence_audit(span: Any, label: str, correct: bool) -> dict[str, Any]:
    score = float(span.syntactic_coherence)
    verdict = "CLEARLY_INCOHERENT" if score <= 0.0 else "BORDERLINE" if score < 0.35 else "COHERENT"
    return {
        "label": label,
        "text": span.text,
        "word_count": span.word_count,
        "correct_span": correct,
        "syntactic_coherence": round(score, 4),
        "audit": verdict,
    }


def build_items() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    matches = historical_exact_matches()
    if matches:
        raise ValueError(f"fresh smoke sentence reused historical text: {matches}")

    profile = get_official_profile()
    config = load_json(CONFIG_PATH)
    plan_rng = random.Random(SMOKE_SEED)
    items: list[dict[str, Any]] = []
    for order, source in enumerate(FRESH_ITEMS, start=1):
        plan = sample_format_plan(plan_rng, profile)
        selection = select_span_set(
            source["sentence"],
            source["correct_span"],
            plan,
            random.Random(SMOKE_SEED + order),
            profile,
        )
        anchor = selection.spans[selection.correct_index]
        conformance = pre_emission_checks(source["sentence"], selection.spans, plan, anchor)
        if not conformance["valid"]:
            raise ValueError(f"{source['id']} pre-emission check failed: {conformance}")

        labels = ("A", "B", "C", "D")
        marked_parts = {label: selection.spans[index].text for index, label in enumerate(labels)}
        span_types = {label: selection.spans[index].span_type for index, label in enumerate(labels)}
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
            "coherence_audit": [
                _coherence_audit(span, label, index == selection.correct_index)
                for index, (label, span) in enumerate(zip(labels, selection.spans))
            ],
        })

    metrics = build_metrics(items, profile)
    gates = evaluate_gates(metrics)
    if not all(gates.values()):
        raise ValueError(f"v2.1.1 smoke gate failed: {gates}; metrics={metrics}")
    metrics["gates"] = gates
    return items, metrics


def build_metrics(items: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    values = lambda key: [item["format"][key] for item in items]
    audits = [audit for item in items for audit in item["coherence_audit"]]
    correct_types = Counter(item["format"]["correct_span_type"] for item in items)
    band_counts = Counter(item["format"]["format_band_status"] for item in items)
    return {
        "item_count": len(items),
        "marked_span_count": len(audits),
        "grammar_quality": "NOT_EVALUATED",
        "sentence_word_count": {"median": _median(values("sentence_word_count")), "min": min(values("sentence_word_count")), "max": max(values("sentence_word_count"))},
        "coverage": {"median": _median(values("marked_coverage_ratio")), "ge_0_60_count": sum(value >= 0.60 for value in values("marked_coverage_ratio"))},
        "unmarked_context": {"median": _median(values("unmarked_word_count")), "zero_count": sum(value == 0 for value in values("unmarked_word_count"))},
        "zero_gap_rate": sum(any(item["format"][key] == 0 for key in ("gap_A_B", "gap_B_C", "gap_C_D")) for item in items) / len(items),
        "five_plus_span_count": sum(sum(value > 4 for value in item["format"]["span_word_counts"].values()) for item in items),
        "correct_span_type_distribution": dict(correct_types),
        "format_band_counts": dict(band_counts),
        "extreme_item_count": sum(item["format"]["format_band_status"] == "EXTREME" for item in items),
        "single_word_correct_gt_short_phrase": correct_types["SINGLE_WORD"] > correct_types["SHORT_PHRASE"],
        "coherence_audit": {
            "clearly_incoherent_count": sum(audit["audit"] == "CLEARLY_INCOHERENT" for audit in audits),
            "borderline_count": sum(audit["audit"] == "BORDERLINE" for audit in audits),
            "coherent_count": sum(audit["audit"] == "COHERENT" for audit in audits),
            "audited_spans": audits,
        },
        "official_geometry_source_item_count": len(profile["item_geometry"]),
    }


def evaluate_gates(metrics: dict[str, Any]) -> dict[str, bool]:
    sentence_median = metrics["sentence_word_count"]["median"]
    coverage_median = metrics["coverage"]["median"]
    unmarked_median = metrics["unmarked_context"]["median"]
    return {
        "sentence_median_17_23": 17 <= sentence_median <= 23,
        "coverage_median_20_35_percent": 0.20 <= coverage_median <= 0.35,
        "unmarked_median_at_least_12": unmarked_median >= 12,
        "coverage_ge_60_zero": metrics["coverage"]["ge_0_60_count"] == 0,
        "zero_gap_at_most_20_percent": metrics["zero_gap_rate"] <= 0.20,
        "five_plus_spans_zero": metrics["five_plus_span_count"] == 0,
        "single_word_correct_gt_short_phrase": metrics["single_word_correct_gt_short_phrase"],
        "extreme_not_majority": metrics["extreme_item_count"] < metrics["item_count"] / 2,
        "coherence_audit_all_60": metrics["marked_span_count"] == 60,
        "clearly_incoherent_zero": metrics["coherence_audit"]["clearly_incoherent_count"] == 0,
        "borderline_at_most_two": metrics["coherence_audit"]["borderline_count"] <= 2,
    }


def build_output(items: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_version": "WE_V2_1_1_FORMAT_RESMOKE_1.0",
        "run": {
            "agent_version": "Written Expression Generator v2.1.1",
            "batch_id": BATCH_ID,
            "generation_unit": "one fresh item per microbatch",
            "item_count": len(items),
            "fresh_generation": True,
            "historical_cohort_reused": False,
            "historical_exact_match_count": len(historical_exact_matches()),
            "grammar_quality": "NOT_EVALUATED",
            "independent_reviewer_runtime_available": False,
            "independent_solver_runtime_available": False,
            "synthetic_consensus_generated": False,
            "source_of_truth": "analysis/we_format/written_expression_format_official.json",
        },
        "policy": {
            "grammar_generation": "unchanged",
            "changed_surface": "distractor span syntactic-coherence scoring only",
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
        "v2_1_1_resmoke": metrics,
        "items": items,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    items, metrics = build_items()
    output = build_output(items, metrics)
    output_path = OUT / "we_v2_1_1_format_resmoke.json"
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "metrics": metrics}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
