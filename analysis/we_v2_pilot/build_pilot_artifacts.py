#!/usr/bin/env python3
"""WE v2 Live Pilot driver.

Stages
------
aggregate     merge the nine live generator microbatch files into the 25-item
              initial cohort, run the deterministic format validator, and
              build provenance from the live phase traces.
solver-input  build the blind Solver payload from Reviewer grammar-PASS items.
finalize      apply the unchanged Orchestrator consensus policy, compute pilot
              metrics, context-drift telemetry, failure taxonomy, the blind
              human-review sample, and the final report.

Nothing here decides English grammaticality. Grammar verdicts come from the
live Reviewer agent; answers come from the live blind Solver agent.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "analysis" / "we_v2_pilot"
RAW = PILOT / "raw"
FINAL_ITEMS_PATH = PILOT / "we_v2_pilot_final_items.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))
from validate_format import (  # noqa: E402
    DiagnosticsEmissionError, inject_canonical_diagnostics,
    load_json, load_items, validate_item, CONFIG_PATH, GRAMMAR_SPEC_PATH, TAXONOMY_PATH,
)

sys.path.insert(0, str(PILOT))
from pilot_validation import build_validation_report  # noqa: E402
from shared.schema_validation import schema_errors  # noqa: E402

BATCH_ID = "we-v2-live-pilot-20260824"
MICROBATCHES = [f"{BATCH_ID}-micro-{i:02d}" for i in range(1, 10)]
LABELS = ("A", "B", "C", "D")
ITEM_SCHEMA_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json"
WE_ALLOWLIST = ["item_id", "section", "sentence", "marked_parts"]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve annotations through sys.modules, so register first.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REVIEWER_VALIDATOR = load_module(
    "pilot_reviewer_validator",
    ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "scripts" / "validate_output.py",
)
SOLVER_VALIDATOR = load_module(
    "pilot_solver_validator",
    ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts" / "validate_output.py",
)
ORCHESTRATOR = load_module(
    "pilot_orchestrator",
    ROOT / "orchestrator" / "scripts" / "orchestrator.py",
)


# ---------------------------------------------------------------------------
# Stage: aggregate
# ---------------------------------------------------------------------------

def median(values: list[float]) -> float:
    return statistics.median(values) if values else float("nan")


def candidate_id(item: Any) -> str:
    """Return a safe identifier for diagnostics about malformed candidates."""

    if not isinstance(item, dict):
        return "?"
    value = item.get("item_id", "?")
    return value if isinstance(value, str) else "?"


def candidate_provenance(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    provenance = item.get("provenance")
    return provenance if isinstance(provenance, dict) else {}


def candidate_generation_order(item: Any) -> int:
    value = candidate_provenance(item).get("item_generation_order")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def candidate_microbatch_id(item: Any) -> str | None:
    value = candidate_provenance(item).get("microbatch_id")
    return value if isinstance(value, str) else None


def stage_aggregate() -> int:
    plan = load_json(PILOT / "we_v2_pilot_plan.json")
    slots = {slot["item_id"]: slot for slot in plan["slots"]}
    item_schema = load_json(ITEM_SCHEMA_PATH)
    config = load_json(CONFIG_PATH)

    items: list[Any] = []
    phases: dict[str, dict] = {}
    microbatch_files: list[dict] = []
    problems: list[str] = []

    for micro in MICROBATCHES:
        gen_path = RAW / f"gen_{micro}.json"
        phase_path = RAW / f"phase_{micro}.json"
        if not gen_path.exists():
            problems.append(f"missing live generator output: {gen_path.name}")
            continue
        payload = load_json(gen_path)
        micro_items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(micro_items, list):
            problems.append(f"invalid generator payload in {gen_path.name}: items must be an array")
            micro_items = []
        for raw_item in micro_items:
            try:
                # Deterministic format code owns all mechanically derivable
                # diagnostics. The schema gate runs only after this boundary.
                items.append(inject_canonical_diagnostics(raw_item, config))
            except DiagnosticsEmissionError as exc:
                # Fail closed: retain the raw candidate for an explicit
                # schema/format failure record, never inject placeholders.
                items.append(raw_item)
                problems.append(
                    f"diagnostics emission failed for {candidate_id(raw_item)}: {exc}"
                )
        microbatch_files.append({
            "microbatch_id": micro,
            "items_file": str(gen_path.relative_to(ROOT)).replace("\\", "/"),
            "phase_trace_file": str(phase_path.relative_to(ROOT)).replace("\\", "/") if phase_path.exists() else None,
            "item_count": len(micro_items),
            "file_mtime_utc": datetime.fromtimestamp(gen_path.stat().st_mtime, timezone.utc).isoformat(),
        })
        if phase_path.exists():
            trace = load_json(phase_path)
            trace_items = trace.get("items") if isinstance(trace, dict) else trace
            if not isinstance(trace_items, list):
                problems.append(f"invalid phase trace payload in {phase_path.name}: items must be an array")
                trace_items = []
            for entry in trace_items:
                if isinstance(entry, dict) and isinstance(entry.get("item_id"), str):
                    phases[entry["item_id"]] = entry
                else:
                    problems.append(f"malformed phase trace entry in {phase_path.name}")
        else:
            problems.append(f"missing phase trace: {phase_path.name}")

    items.sort(key=candidate_generation_order)

    ids = [candidate_id(item) for item in items]
    if len(items) != 25:
        problems.append(f"expected exactly 25 initial candidates, found {len(items)}")
    if len(set(ids)) != len(ids):
        problems.append("duplicate item_id in the live cohort")
    if set(ids) - set(slots):
        problems.append(f"item_ids outside the batch plan: {sorted(set(ids) - set(slots))}")
    sentences = [
        item["sentence"].strip().lower()
        if isinstance(item, dict) and isinstance(item.get("sentence"), str)
        else f"<invalid-sentence-{index}>"
        for index, item in enumerate(items)
    ]
    if len(set(sentences)) != len(sentences):
        problems.append("duplicate sentence text in the live cohort")

    grammar = load_json(GRAMMAR_SPEC_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    targets = {x["id"] for x in taxonomy["primary_targets"]}
    error_types = {x["id"] for x in grammar["tested_error_types"] if x["id"] not in {"fragment", "wrong_complementation"}}

    records: list[dict] = []
    for item in items:
        item_id = candidate_id(item)
        slot = slots.get(item_id, {})
        schema_result = schema_errors(item, item_schema)
        format_result = validate_item(item, config, targets, error_types)
        plan_mismatches = []
        for plan_key, item_key in [
            ("primary_target", "primary_target"), ("subtype", "subtype"),
            ("tested_error_type", "tested_error_type"), ("difficulty", "difficulty"),
            ("vocabulary_domain", "vocabulary_domain"),
        ]:
            if slot and (not isinstance(item, dict) or slot[plan_key] != item.get(item_key)):
                plan_mismatches.append(
                    f"{item_key}: plan={slot[plan_key]!r} item={item.get(item_key) if isinstance(item, dict) else None!r}"
                )
        if slot and (not isinstance(item, dict) or slot["planned_correct_position"] != item.get("correct_answer")):
            plan_mismatches.append(
                "correct_answer: "
                f"plan={slot['planned_correct_position']} item={item.get('correct_answer') if isinstance(item, dict) else None}"
            )
        grammar_metadata = item.get("grammar_metadata") if isinstance(item, dict) else None
        for plan_key in ("correction_locality", "decision_granularity"):
            if slot and (not isinstance(grammar_metadata, dict) or slot[plan_key] != grammar_metadata.get(plan_key)):
                plan_mismatches.append(
                    "grammar_metadata."
                    f"{plan_key}: plan={slot[plan_key]!r} item={grammar_metadata.get(plan_key) if isinstance(grammar_metadata, dict) else None!r}"
                )
        records.append({
            "item_id": item_id,
            "item_generation_order": candidate_generation_order(item),
            "microbatch_id": candidate_microbatch_id(item),
            "generator_schema_pass": not schema_result,
            "generator_schema_errors": schema_result,
            "format_validator_pass": format_result["valid"],
            "format_validator_errors": format_result["errors"],
            "plan_conformance_pass": not plan_mismatches,
            "plan_mismatches": plan_mismatches,
            "diagnostics": format_result["diagnostics"],
        })

    for record in records:
        if not (
            record["generator_schema_pass"]
            and record["format_validator_pass"]
            and record["plan_conformance_pass"]
        ):
            problems.append(
                f"candidate validation failed for {record['item_id']}: "
                f"schema={record['generator_schema_errors']} "
                f"format={record['format_validator_errors']} "
                f"plan={record['plan_mismatches']}"
            )

    run = {
        "run_id": BATCH_ID,
        "run_type": "LIVE_PILOT",
        "section": "Written Expression",
        "generator_version": "Written Expression Generator v2.0",
        "reviewer_version": "Written Expression Reviewer v2.0",
        "solver_version": "existing blind Solver (unchanged)",
        "orchestrator_policy": "existing consensus policy (unchanged)",
        "live_generation": True,
        "reused_smoke_artifacts": False,
        "handwritten_items": False,
        "aggregated_at_utc": datetime.now(timezone.utc).isoformat(),
        "microbatches": microbatch_files,
        "aggregation_problems": problems,
    }

    (PILOT / "we_v2_pilot_initial_items.json").write_text(
        json.dumps({"run": run, "items": items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    validation_report = {
        "validator": "TOEFL ITP WE deterministic format validator v2.0",
        "config": config["config_id"],
        "run_id": BATCH_ID,
        "item_count": len(records),
        "generator_schema_pass": sum(r["generator_schema_pass"] for r in records),
        "format_validator_pass": sum(r["format_validator_pass"] for r in records),
        "plan_conformance_pass": sum(r["plan_conformance_pass"] for r in records),
        "items": records,
    }
    (PILOT / "we_v2_pilot_format_validation.json").write_text(
        json.dumps(validation_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    provenance_items = []
    for item in items:
        item_id = candidate_id(item)
        provenance_items.append({
            "item_id": item_id,
            "plan_slot": slots.get(item_id),
            "generator_provenance": candidate_provenance(item),
            "qa_metadata": item.get("qa_metadata") if isinstance(item, dict) else None,
            "sentence_first_phase_trace": phases.get(item_id),
            "deterministic_format_validation": next(
                r for r in records if r["item_id"] == item_id
            ),
        })
    (PILOT / "we_v2_pilot_provenance.json").write_text(
        json.dumps({"run": run, "items": provenance_items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"aggregated {len(items)} live items from {len(microbatch_files)} microbatches")
    print(f"generator_schema_pass  {validation_report['generator_schema_pass']}/{len(records)}")
    print(f"format_validator_pass  {validation_report['format_validator_pass']}/{len(records)}")
    print(f"plan_conformance_pass  {validation_report['plan_conformance_pass']}/{len(records)}")
    for record in records:
        if not (record["generator_schema_pass"] and record["format_validator_pass"] and record["plan_conformance_pass"]):
            print(f"  [{record['item_id']}] schema={record['generator_schema_errors']} "
                  f"format={record['format_validator_errors']} plan={record['plan_mismatches']}")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    return 0 if not problems else 1


# ---------------------------------------------------------------------------
# Stage: solver-input
# ---------------------------------------------------------------------------

def collect_reviews() -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Return (round1, round2, final_by_item_id)."""
    round1: list[dict] = []
    round2: list[dict] = []
    for path in sorted(RAW.glob("review_r1_*.json")):
        round1.extend(load_items(path))
    for path in sorted(RAW.glob("review_r2_*.json")):
        round2.extend(load_items(path))
    final = {review["item_id"]: review for review in round1}
    for review in round2:
        final[review["item_id"]] = review
    return round1, round2, final


def current_generator_validation(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the cohort currently being finalized, including revisions."""

    plan = load_json(PILOT / "we_v2_pilot_plan.json")
    item_schema = load_json(ITEM_SCHEMA_PATH)
    config = load_json(CONFIG_PATH)
    grammar = load_json(GRAMMAR_SPEC_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    targets = {entry["id"] for entry in taxonomy["primary_targets"]}
    error_types = {
        entry["id"] for entry in grammar["tested_error_types"]
        if entry["id"] not in {"fragment", "wrong_complementation"}
    }
    return build_validation_report(
        items,
        plan,
        item_schema,
        config,
        targets,
        error_types,
        run_id=BATCH_ID,
        stage="final_cohort",
        source_items=(
            "analysis/we_v2_pilot/we_v2_pilot_final_items.json"
            if FINAL_ITEMS_PATH.exists()
            else "analysis/we_v2_pilot/we_v2_pilot_initial_items.json"
        ),
    )


def reviewer_contract_errors(review: Any) -> list[str]:
    """Validate a Reviewer record without allowing malformed JSON to abort a gate."""

    if not isinstance(review, dict):
        return ["reviewer result must be an object"]
    try:
        return REVIEWER_VALIDATOR.validate_contract(review)
    except Exception as exc:
        return [f"reviewer validator exception: {type(exc).__name__}: {exc}"]


def solver_contract_errors(entry: Any) -> list[str]:
    """Validate a Solver record without allowing malformed JSON to abort a gate."""

    if not isinstance(entry, dict):
        return ["solver result must be an object"]
    errors: list[str] = []
    try:
        SOLVER_VALIDATOR.validate_contract(entry, errors)
    except Exception as exc:
        errors.append(f"solver validator exception: {type(exc).__name__}: {exc}")
    return errors


def stage_solver_input() -> int:
    cohort = load_json(FINAL_ITEMS_PATH if FINAL_ITEMS_PATH.exists() else PILOT / "we_v2_pilot_initial_items.json")
    items = {item["item_id"]: item for item in cohort["items"]}
    round1, round2, final = collect_reviews()
    generator_validation = current_generator_validation(list(items.values()))
    generator_validation_by_id = {
        record["item_id"]: record for record in generator_validation["items"]
    }

    contract_errors = {
        review["item_id"]: reviewer_contract_errors(review)
        for review in list(final.values())
        if isinstance(review, dict) and "item_id" in review
    }
    generator_contract_errors = {}
    for item_id, record in generator_validation_by_id.items():
        if not record["generator_schema_pass"] or not record["format_validator_pass"]:
            generator_contract_errors[item_id] = [
                *record["generator_schema_errors"],
                *record["format_validator_errors"],
            ]
    final_reviews = [final[item_id] for item_id in items if item_id in final]
    review_payload = {
        "run": {
            "run_id": BATCH_ID,
            "reviewer_version": "Written Expression Reviewer v2.0",
            "live_review": True,
            "blind_grammar_audit_first": True,
            "grammar_and_format_validity_separated": True,
            "rounds": sorted({1 if round1 else 0, 2 if round2 else 0} - {0}),
            "contract_validation": {
                "checked": len(contract_errors),
                "valid": sum(not errors for errors in contract_errors.values()),
                "errors": {k: v for k, v in contract_errors.items() if v},
            },
        },
        "round1": round1,
        "round2": round2,
        "final": final_reviews,
        # Reviewer validator consumers expect the final aggregate to expose
        # the contract-shaped records at the top level as well.
        "items": final_reviews,
    }
    (PILOT / "we_v2_pilot_review.json").write_text(
        json.dumps(review_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    eligible = [
        item_id for item_id in items
        if (
            item_id in final
            and not contract_errors.get(item_id)
            and not generator_contract_errors.get(item_id)
            and final[item_id].get("grammar_validity") == "PASS"
        )
    ]
    blind = []
    for item_id in eligible:
        item = items[item_id]
        missing = [key for key in WE_ALLOWLIST if key not in item]
        if missing:
            raise ValueError(f"{item_id} cannot be blinded, missing {missing}")
        blind.append({key: item[key] for key in WE_ALLOWLIST})

    leaked = set()
    for payload in blind:
        leaked |= set(payload) - set(WE_ALLOWLIST)
    if leaked:
        raise ValueError(f"blind payload leak: {sorted(leaked)}")

    (PILOT / "we_v2_pilot_solver_input.json").write_text(
        json.dumps({
            "run": {
            "run_id": BATCH_ID,
            "blinding": "allowlist: item_id, section, sentence, marked_parts",
                "source": "contract-valid Reviewer grammar_validity == PASS plus final Generator schema/format gates",
                "cohort_source": str((FINAL_ITEMS_PATH if FINAL_ITEMS_PATH.exists() else PILOT / "we_v2_pilot_initial_items.json").relative_to(ROOT)).replace("\\", "/"),
                "eligible_count": len(blind),
                "generator_validation": {
                    "schema_pass": generator_validation["generator_schema_pass"],
                    "format_pass": sum(
                        record["generator_schema_pass"] and record["format_validator_pass"]
                        for record in generator_validation["items"]
                    ),
                    "invalid_items": generator_contract_errors,
                },
            },
            "items": blind,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"reviews: round1={len(round1)} round2={len(round2)} final={len(final)}")
    bad = {k: v for k, v in contract_errors.items() if v}
    print(f"reviewer contract valid: {len(contract_errors) - len(bad)}/{len(contract_errors)}")
    for item_id, errors in bad.items():
        print(f"  [{item_id}] {errors}")
    if generator_contract_errors:
        print(f"generator contract valid: {len(items) - len(generator_contract_errors)}/{len(items)}")
        for item_id, errors in generator_contract_errors.items():
            print(f"  [Generator {item_id}] {errors}")
    print(f"solver input (validated grammar PASS): {len(blind)} items -> we_v2_pilot_solver_input.json")
    return 0


# ---------------------------------------------------------------------------
# Stage: finalize
# ---------------------------------------------------------------------------

FAILURE_REASONS = [
    "no_genuine_error", "multiple_genuine_errors", "wrong_answer_key",
    "marked_span_mismatch", "alternate_parse", "semantic_only_error",
    "reference_dependency", "tense_optionality", "connector_ambiguity",
    "unnatural_sentence", "format_extreme", "format_warning_only",
    "solver_disagreement", "solver_ambiguous", "solver_none",
    "revision_failure", "other",
]


def classify_failure(item: dict, review: dict | None, solver: dict | None, consensus) -> tuple[str, list[str]]:
    """Primary reason first, then contributing reasons. Reviewer/Solver evidence
    only; this function never re-decides grammaticality itself."""
    reasons: list[str] = []
    if review is not None:
        independent_answer = review.get("independent_answer")
        detected_error_count = review.get("detected_error_count")
        answer_match = review.get("answer_match")
        issues = review.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        categories = " ".join(
            f"{issue.get('category', '')} {issue.get('description', '')}".lower()
            for issue in issues
            if isinstance(issue, dict)
        )
        if independent_answer == "NONE" or detected_error_count == 0:
            reasons.append("no_genuine_error")
        if isinstance(detected_error_count, int) and detected_error_count > 1:
            reasons.append("multiple_genuine_errors")
        if independent_answer in LABELS and not answer_match:
            reasons.append("wrong_answer_key")
        if "alternate_parse" in categories or "alternate parse" in categories:
            reasons.append("alternate_parse")
        if "semantic" in categories and "semantic_only_error" not in reasons:
            reasons.append("semantic_only_error")
        if "span" in categories or "marked_part" in categories:
            reasons.append("marked_span_mismatch")
        if "reference" in categories:
            reasons.append("reference_dependency")
        if "tense" in categories:
            reasons.append("tense_optionality")
        if "connector" in categories:
            reasons.append("connector_ambiguity")
        if "natural" in categories:
            reasons.append("unnatural_sentence")
        if independent_answer == "AMBIGUOUS" and "alternate_parse" not in reasons:
            reasons.append("alternate_parse")
    metadata = item.get("format_metadata", {})
    diagnostics = metadata.get("diagnostics", {}) if isinstance(metadata, dict) else {}
    band = diagnostics.get("format_band_status") if isinstance(diagnostics, dict) else None
    if band == "EXTREME":
        reasons.append("format_extreme")
    if solver is not None:
        solver_answer = solver.get("solver_answer")
        if solver_answer == "AMBIGUOUS":
            reasons.append("solver_ambiguous")
        elif solver_answer == "NONE":
            reasons.append("solver_none")
        elif solver_answer != item.get("correct_answer"):
            reasons.append("solver_disagreement")
        elif consensus is not None and not consensus.auto_accept:
            reasons.append("solver_disagreement")
    if not reasons and review is not None and review.get("verdict") == "REVISE":
        reasons.append("revision_failure")
    if not reasons:
        reasons.append("other")
    ordered = list(OrderedDict.fromkeys(reasons))
    return ordered[0], ordered


def band_counts(items: list[dict]) -> dict[str, int]:
    counter = Counter(item["format_metadata"]["diagnostics"]["format_band_status"] for item in items)
    return {band: counter.get(band, 0) for band in ("PREFERRED", "WARNING", "EXTREME")}


def geometry_summary(items: list[dict]) -> dict:
    diagnostics = [item["format_metadata"]["diagnostics"] for item in items]
    span_lengths = [count for d in diagnostics for count in d["span_word_counts"].values()]
    return {
        "item_count": len(items),
        "sentence_median": median([d["sentence_word_count"] for d in diagnostics]),
        "span_median": median(span_lengths),
        "mean_span_length_median": median([d["mean_span_length"] for d in diagnostics]),
        "coverage_median": round(median([d["marked_coverage_ratio"] for d in diagnostics]), 4),
        "unmarked_context_median": median([d["unmarked_word_count"] for d in diagnostics]),
        "gap_medians": {
            "gap_A_B": median([d["gap_A_B"] for d in diagnostics]),
            "gap_B_C": median([d["gap_B_C"] for d in diagnostics]),
            "gap_C_D": median([d["gap_C_D"] for d in diagnostics]),
        },
        "coverage_100_percent_count": sum(d["marked_coverage_ratio"] >= 1.0 for d in diagnostics),
        "unmarked_context_zero_count": sum(d["unmarked_word_count"] == 0 for d in diagnostics),
        "coverage_ge_60_percent_count": sum(d["marked_coverage_ratio"] >= 0.60 for d in diagnostics),
        "format_band_counts": band_counts(items),
        "distance_median": round(median([d["format_distribution_distance"] for d in diagnostics]), 4),
    }


def official_geometry() -> dict:
    data = load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")
    summary = data["summary"]["all"]
    return {
        "source": "analysis/we_format/written_expression_format_official.json",
        "item_count": summary["item_count"],
        "sentence_median": summary["sentence_word_count"]["median"],
        "span_median": summary["marked_span_word_count_all_4_spans"]["median"],
        "coverage_median": summary["coverage_ratio"]["median"],
        "unmarked_context_median": summary["unmarked_word_count"]["median"],
        "gap_medians": {
            "gap_A_B": summary["gap_A_B"]["median"],
            "gap_B_C": summary["gap_B_C"]["median"],
            "gap_C_D": summary["gap_C_D"]["median"],
        },
        "coverage_100_percent_count": sum(x["marked_coverage_ratio"] >= 1.0 for x in data["items"]),
        "unmarked_context_zero_count": sum(x["unmarked_word_count"] == 0 for x in data["items"]),
        "coverage_ge_60_percent_count": sum(x["marked_coverage_ratio"] >= 0.60 for x in data["items"]),
    }


def v11_geometry() -> dict:
    data = load_json(ROOT / "analysis" / "we_format" / "written_expression_format_validation.json")
    summary = data["summary"]["all"]
    return {
        "source": "analysis/we_format/written_expression_format_validation.json",
        "item_count": summary["item_count"],
        "sentence_median": summary["sentence_word_count"]["median"],
        "span_median": summary["marked_span_word_count_all_4_spans"]["median"],
        "coverage_median": summary["coverage_ratio"]["median"],
        "unmarked_context_median": summary["unmarked_word_count"]["median"],
        "gap_medians": {
            "gap_A_B": summary["gap_A_B"]["median"],
            "gap_B_C": summary["gap_B_C"]["median"],
            "gap_C_D": summary["gap_C_D"]["median"],
        },
        "coverage_100_percent_count": sum(x["marked_coverage_ratio"] >= 1.0 for x in data["items"]),
        "unmarked_context_zero_count": sum(x["unmarked_word_count"] == 0 for x in data["items"]),
        "coverage_ge_60_percent_count": sum(x["marked_coverage_ratio"] >= 0.60 for x in data["items"]),
    }


def smoke_geometry() -> dict:
    smoke = load_items(ROOT / "analysis" / "we_v2" / "we_v2_smoke_items.json")
    summary = geometry_summary(smoke)
    summary["source"] = "analysis/we_v2/we_v2_smoke_items.json"
    return summary


def stage_finalize() -> int:
    cohort = load_json(FINAL_ITEMS_PATH if FINAL_ITEMS_PATH.exists() else PILOT / "we_v2_pilot_initial_items.json")
    items = cohort["items"]
    by_id = {item["item_id"]: item for item in items}
    # Always validate the cohort that is actually being finalized.  In
    # particular, a revision must not inherit the initial Generator gate.
    validation = current_generator_validation(items)
    if FINAL_ITEMS_PATH.exists():
        (PILOT / "we_v2_pilot_final_format_validation.json").write_text(
            json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    validation_by_id = {r["item_id"]: r for r in validation["items"]}
    review_payload = load_json(PILOT / "we_v2_pilot_review.json")
    round1 = {r["item_id"]: r for r in review_payload["round1"]}
    round2 = {r["item_id"]: r for r in review_payload["round2"]}
    final_review = {r["item_id"]: r for r in review_payload["final"]}

    solver_path = PILOT / "we_v2_pilot_solver.json"
    solver_by_id: dict[str, dict] = {}
    solver_run: dict = {}
    if solver_path.exists():
        solver_payload = load_json(solver_path)
        solver_run = solver_payload.get("run", {})
        for entry in solver_payload.get("items", []):
            if isinstance(entry, dict) and "item_id" in entry:
                solver_by_id[entry["item_id"]] = entry

    solver_contract_errors_by_id = {
        item_id: errors
        for item_id, entry in solver_by_id.items()
        for errors in [solver_contract_errors(entry)]
        if errors
    }
    reviewer_contract_errors_by_id = {
        item_id: errors
        for item_id, review in final_review.items()
        for errors in [reviewer_contract_errors(review)]
        if errors
    }

    config = load_json(ROOT / "orchestrator" / "config.json")

    accepted: list[dict] = []
    failures: list[dict] = []
    records: list[dict] = []

    for item in items:
        item_id = item["item_id"]
        item_validation = validation_by_id[item_id]
        item_metadata = item.get("format_metadata", {})
        item_diagnostics = item_metadata.get("diagnostics", {}) if isinstance(item_metadata, dict) else {}
        validation_diagnostics = item_validation.get("diagnostics", {})
        if validation_diagnostics:
            # Preserve the raw initial Generator output (and its schema
            # failure), but always use diagnostics calculated from the final
            # sentence/spans for downstream geometry/consensus telemetry.
            evaluation_item = json.loads(json.dumps(item))
            evaluation_item.setdefault("format_metadata", {})["diagnostics"] = validation_diagnostics
            item_diagnostics = validation_diagnostics
        else:
            evaluation_item = item
        review = final_review.get(item_id)
        solver = solver_by_id.get(item_id)
        reviewer_contract_errors_for_item = reviewer_contract_errors_by_id.get(item_id, [])
        solver_contract_errors_for_item = solver_contract_errors_by_id.get(item_id, [])
        consensus = None
        state = None
        if not item_validation["generator_schema_pass"] or not item_validation["format_validator_pass"]:
            # A schema-invalid Generator artifact cannot enter AUTO_ACCEPT,
            # even if later live review/solve signals happen to agree.
            # Keep it in the 25-item evaluation and route it to manual QA.
            state = "MANUAL_REVIEW"
        elif review is None:
            state = "MANUAL_REVIEW"
        elif reviewer_contract_errors_for_item:
            # The fields used by evaluate_consensus are not sufficient to
            # establish a valid Reviewer record; the full contract is the gate.
            state = "MANUAL_REVIEW"
        elif review.get("grammar_validity") != "PASS" or review.get("verdict") != "PASS":
            state = "REJECTED" if review.get("verdict") == "REJECT" else "MANUAL_REVIEW"
        elif solver is None:
            state = "MANUAL_REVIEW"
        elif solver_contract_errors_for_item:
            # Never let a partially-shaped Solver answer flow into consensus.
            state = "MANUAL_REVIEW"
        else:
            consensus = ORCHESTRATOR.evaluate_consensus(evaluation_item, review, solver, config)
            state = consensus.routing

        record = {
            "item_id": item_id,
            "item_generation_order": (
                item.get("provenance", {}).get("item_generation_order")
                if isinstance(item.get("provenance"), dict)
                else None
            ),
            "microbatch_id": (
                item.get("provenance", {}).get("microbatch_id")
                if isinstance(item.get("provenance"), dict)
                else None
            ),
            "generator_answer": item.get("correct_answer"),
            "generator_schema_pass": item_validation["generator_schema_pass"],
            "generator_schema_errors": item_validation["generator_schema_errors"],
            "format_validator_pass": item_validation["format_validator_pass"],
            "format_validator_errors": item_validation["format_validator_errors"],
            "plan_conformance_pass": item_validation["plan_conformance_pass"],
            "plan_mismatches": item_validation["plan_mismatches"],
            "reviewer_contract_valid": review is not None and not reviewer_contract_errors_for_item,
            "reviewer_contract_errors": reviewer_contract_errors_for_item,
            "reviewer_round1_verdict": round1[item_id]["verdict"] if item_id in round1 else None,
            "reviewer_final_verdict": review.get("verdict") if review else None,
            "revised": item_id in round2,
            "grammar_validity": review.get("grammar_validity") if review else None,
            "format_validity": review.get("format_validity") if review else None,
            "reviewer_independent_answer": review.get("independent_answer") if review else None,
            "reviewer_answer_match": review.get("answer_match") if review else None,
            "solver_reached": solver is not None,
            "solver_contract_valid": solver is not None and not solver_contract_errors_for_item,
            "solver_contract_errors": solver_contract_errors_for_item,
            "solver_answer": solver.get("solver_answer") if solver else None,
            "solver_confidence": solver.get("confidence") if solver else None,
            "solver_ambiguity_detected": solver.get("ambiguity_detected") if solver else None,
            "consensus": None if consensus is None else {
                "auto_accept": consensus.auto_accept,
                "routing": consensus.routing,
                "failed_conditions": consensus.failed_conditions,
                "disagreement_reasons": consensus.disagreement_reasons,
            },
            "final_state": state,
            "format_band_status": item_diagnostics.get("format_band_status", "EXTREME"),
            "sentence_word_count": item_diagnostics.get("sentence_word_count", 0),
            "marked_coverage_ratio": item_diagnostics.get("marked_coverage_ratio", 1.0),
            "unmarked_word_count": item_diagnostics.get("unmarked_word_count", 0),
        }

        if state == "ACCEPTED":
            record["primary_failure_reason"] = None
            record["failure_reasons"] = []
            accepted.append({
                "item": item,
                "reviewer_result": review,
                "solver_result": solver,
                "consensus": record["consensus"],
                "final_state": state,
            })
        else:
            primary, all_reasons = classify_failure(evaluation_item, review, solver, consensus)
            record["primary_failure_reason"] = primary
            record["failure_reasons"] = all_reasons
            failures.append({
                "item_id": item_id,
                "final_state": state,
                "primary_failure_reason": primary,
                "failure_reasons": all_reasons,
                 "reviewer_verdict": review.get("verdict") if review else None,
                 "reviewer_independent_answer": review.get("independent_answer") if review else None,
                 "grammar_validity": review.get("grammar_validity") if review else None,
                 "format_validity": review.get("format_validity") if review else None,
                 "reviewer_issues": review.get("issues", []) if review else [],
                 "revision_requirements": review.get("revision_requirements", []) if review else [],
                "solver_result": solver,
                "consensus": record["consensus"],
                "item": item,
            })
        records.append(record)

    # ---- metrics ----
    reviewer_r1 = Counter(r["reviewer_round1_verdict"] for r in records)
    reviewer_final = Counter(r["reviewer_final_verdict"] for r in records)
    state_counts = Counter(r["final_state"] for r in records)
    solver_answers = [
        r for r in records if r["solver_reached"] and r["solver_contract_valid"]
    ]

    windows = []
    for start in range(1, 26, 5):
        window = [r for r in records if start <= r["item_generation_order"] <= start + 4]
        diagnostics = [validation_by_id[r["item_id"]]["diagnostics"] for r in window]
        windows.append({
            "window": f"items {start}-{start + 4}",
            "n": len(window),
            "grammar_pass": sum(r["grammar_validity"] == "PASS" for r in window),
            "grammar_failure": sum(r["grammar_validity"] not in (None, "PASS") for r in window),
            "reviewer_pass": sum(r["reviewer_final_verdict"] == "PASS" for r in window),
            "auto_accept": sum(r["final_state"] == "ACCEPTED" for r in window),
            "format_band_counts": {
                band: sum(r["format_band_status"] == band for r in window)
                for band in ("PREFERRED", "WARNING", "EXTREME")
            },
            "sentence_median": median([d["sentence_word_count"] for d in diagnostics]),
            "coverage_median": round(median([d["marked_coverage_ratio"] for d in diagnostics]), 4),
            "unmarked_context_median": median([d["unmarked_word_count"] for d in diagnostics]),
            "reviewer_verdicts": dict(Counter(r["reviewer_final_verdict"] for r in window)),
        })

    first_half = [r for r in records if r["item_generation_order"] <= 13]
    second_half = [r for r in records if r["item_generation_order"] > 13]

    def half_summary(rows: list[dict]) -> dict:
        return {
            "n": len(rows),
            "grammar_pass_rate": round(sum(r["grammar_validity"] == "PASS" for r in rows) / len(rows), 4) if rows else None,
            "auto_accept_rate": round(sum(r["final_state"] == "ACCEPTED" for r in rows) / len(rows), 4) if rows else None,
            "extreme_count": sum(r["format_band_status"] == "EXTREME" for r in rows),
            "sentence_median": median([r["sentence_word_count"] for r in rows]),
            "coverage_median": round(median([r["marked_coverage_ratio"] for r in rows]), 4),
        }

    geometry_items = []
    for item in items:
        geometry_item = json.loads(json.dumps(item))
        current_diagnostics = validation_by_id[item["item_id"]].get("diagnostics", {})
        if current_diagnostics:
            geometry_item.setdefault("format_metadata", {})["diagnostics"] = current_diagnostics
        geometry_items.append(geometry_item)
    pilot_geometry = geometry_summary(geometry_items)
    pilot_geometry["source"] = "analysis/we_v2_pilot/we_v2_pilot_final_items.json" if FINAL_ITEMS_PATH.exists() else "analysis/we_v2_pilot/we_v2_pilot_initial_items.json"

    metrics = {
        "report_version": "WE_V2_LIVE_PILOT_METRICS_1.0",
        "run_id": BATCH_ID,
        "live_generation": True,
        "scope": {
            "initial_generated": len(items),
            "evaluation_unit": "exactly 25 initial candidates",
            "replacement_generation": False,
        },
        "generator": {
            "generator_schema_pass": sum(r["generator_schema_pass"] for r in records),
            "format_validator_pass": sum(r["format_validator_pass"] for r in records),
            "plan_conformance_pass": validation["plan_conformance_pass"],
            "plan_conformance_stage": validation["validation_stage"],
        },
        "reviewer_round1": {
            "PASS": reviewer_r1.get("PASS", 0),
            "REVISE": reviewer_r1.get("REVISE", 0),
            "REJECT": reviewer_r1.get("REJECT", 0),
        },
        "reviewer_eventual": {
            "PASS": reviewer_final.get("PASS", 0),
            "REVISE": reviewer_final.get("REVISE", 0),
            "REJECT": reviewer_final.get("REJECT", 0),
        },
        "reviewer_validity_split": {
            "grammar_PASS": sum(r["grammar_validity"] == "PASS" for r in records),
            "grammar_FAIL": sum(r["grammar_validity"] == "FAIL" for r in records),
            "grammar_AMBIGUOUS": sum(r["grammar_validity"] == "AMBIGUOUS" for r in records),
            "format_PASS": sum(r["format_validity"] == "PASS" for r in records),
            "format_WARN": sum(r["format_validity"] == "WARN" for r in records),
            "format_FAIL": sum(r["format_validity"] == "FAIL" for r in records),
            "grammar_PASS_with_format_WARN": sum(
                r["grammar_validity"] == "PASS" and r["format_validity"] == "WARN" for r in records
            ),
        },
        "solver": {
            "reached": len(solver_answers),
            "consensus": sum(
                r["solver_answer"] == r["generator_answer"] and r["solver_answer"] in LABELS
                for r in solver_answers
            ),
            "letter_disagreement": sum(
                r["solver_answer"] in LABELS and r["solver_answer"] != r["generator_answer"]
                for r in solver_answers
            ),
            "AMBIGUOUS": sum(r["solver_answer"] == "AMBIGUOUS" for r in solver_answers),
            "NONE": sum(r["solver_answer"] == "NONE" for r in solver_answers),
            "LOW_confidence": sum(r["solver_confidence"] == "LOW" for r in solver_answers),
            "confidence_counts": dict(Counter(r["solver_confidence"] for r in solver_answers)),
            "contract_errors": solver_contract_errors_by_id,
            "contract_valid": sum(not r["solver_contract_errors"] for r in records if r["solver_reached"]),
            "run": solver_run,
        },
        "orchestrator": {
            "AUTO_ACCEPT": state_counts.get("ACCEPTED", 0),
            "MANUAL_REVIEW": state_counts.get("MANUAL_REVIEW", 0),
            "DISCARDED": state_counts.get("DISCARDED", 0),
            "REJECTED": state_counts.get("REJECTED", 0),
            "auto_accept_rate": round(state_counts.get("ACCEPTED", 0) / len(items), 4) if items else None,
            "policy": "unchanged; auto_accept conditions not relaxed",
        },
        "revision": {
            "revise_requested_round1": reviewer_r1.get("REVISE", 0),
            "revision_attempted": len(round2),
            "revision_success": sum(
                1 for item_id in round2 if final_review.get(item_id, {}).get("verdict") == "PASS"
            ),
            "revision_failed": sum(
                1 for item_id in round2 if final_review.get(item_id, {}).get("verdict") != "PASS"
            ),
        },
        "format_guardrails": {
            "coverage_100_percent": pilot_geometry["coverage_100_percent_count"],
            "unmarked_context_zero": pilot_geometry["unmarked_context_zero_count"],
            "coverage_ge_60_percent": pilot_geometry["coverage_ge_60_percent_count"],
            "EXTREME": pilot_geometry["format_band_counts"]["EXTREME"],
            "WARNING": pilot_geometry["format_band_counts"]["WARNING"],
            "PREFERRED": pilot_geometry["format_band_counts"]["PREFERRED"],
            "note": "WARNING is a format diagnostic and is never treated as a grammatical failure.",
        },
        "geometry_comparison": {
            "official_125": official_geometry(),
            "v1_1_validation_75": v11_geometry(),
            "v2_smoke_10": smoke_geometry(),
            "v2_live_pilot_25": pilot_geometry,
        },
        "failure_taxonomy": {
            "reason_vocabulary": FAILURE_REASONS,
            "primary_reason_counts": dict(Counter(
                r["primary_failure_reason"] for r in records if r["primary_failure_reason"]
            )),
            "all_reason_counts": dict(Counter(
                reason for r in records for reason in r["failure_reasons"]
            )),
        },
        "context_drift_telemetry": {
            "note": "Each microbatch was realized in an independent live generation context; order is plan generation order.",
            "five_item_windows": windows,
            "first_half_items_1_13": half_summary(first_half),
            "second_half_items_14_25": half_summary(second_half),
            "per_item": [
                {
                    "item_generation_order": r["item_generation_order"],
                    "item_id": r["item_id"],
                    "microbatch_id": r["microbatch_id"],
                    "grammar_validity": r["grammar_validity"],
                    "reviewer_verdict": r["reviewer_final_verdict"],
                    "format_band_status": r["format_band_status"],
                    "sentence_word_count": r["sentence_word_count"],
                    "marked_coverage_ratio": r["marked_coverage_ratio"],
                    "final_state": r["final_state"],
                }
                for r in sorted(records, key=lambda x: x["item_generation_order"])
            ],
        },
        "distributions": {
            "primary_target": dict(Counter(item["primary_target"] for item in items)),
            "tested_error_type": dict(Counter(item["tested_error_type"] for item in items)),
            "difficulty": dict(Counter(item["difficulty"] for item in items)),
            "correct_answer": dict(Counter(item["correct_answer"] for item in items)),
            "correct_span_type": dict(Counter(
                item["grammar_metadata"]["correct_span_type"] for item in items
            )),
        },
        "per_item": records,
    }

    (PILOT / "we_v2_pilot_metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (PILOT / "we_v2_pilot_accepted.json").write_text(
        json.dumps({
            "run": {"run_id": BATCH_ID, "state": "AUTO_ACCEPT", "count": len(accepted)},
            "items": accepted,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (PILOT / "we_v2_pilot_failures.json").write_text(
        json.dumps({
            "run": {"run_id": BATCH_ID, "count": len(failures), "reason_vocabulary": FAILURE_REASONS},
            "items": failures,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- blind human sample ----
    sample_ids = [entry["item"]["item_id"] for entry in accepted][:max(10, min(len(accepted), 12))]
    human_sample = {
        "run": {
            "run_id": BATCH_ID,
            "purpose": "blind human review of AUTO_ACCEPT candidates",
            "blinding": "no pipeline answer, no Reviewer verdict, no Solver result, no grammar or format metadata",
            "count": len(sample_ids),
        },
        "rubric": [
            "Is exactly one of A/B/C/D genuinely wrong in standard written English (answer uniqueness)?",
            "Is the English natural for academic prose?",
            "Does this read like a real TOEFL ITP Written Expression item?",
            "Are the four marked spans natural inspection targets?",
            "Does anything feel like a question TOEFL ITP would never ask?",
        ],
        "response_fields": {
            "human_answer": "A|B|C|D|NONE|AMBIGUOUS",
            "answer_uniqueness": "OK|WEAK|BROKEN",
            "naturalness": "OK|WEAK|BROKEN",
            "itp_likeness": "OK|WEAK|BROKEN",
            "marked_span_naturalness": "OK|WEAK|BROKEN",
            "would_never_be_asked": "true|false",
            "comment": "free text",
        },
        "items": [
            {
                "item_id": item_id,
                "section": "Written Expression",
                "sentence": by_id[item_id]["sentence"],
                "marked_parts": by_id[item_id]["marked_parts"],
            }
            for item_id in sample_ids
        ],
    }
    (PILOT / "we_v2_pilot_human_sample.json").write_text(
        json.dumps(human_sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "initial_generated": len(items),
        "generator_schema_pass": metrics["generator"]["generator_schema_pass"],
        "format_validator_pass": metrics["generator"]["format_validator_pass"],
        "reviewer_round1": metrics["reviewer_round1"],
        "reviewer_eventual": metrics["reviewer_eventual"],
        "solver": {k: v for k, v in metrics["solver"].items() if k not in ("contract_errors", "run")},
        "orchestrator": metrics["orchestrator"],
        "format_guardrails": metrics["format_guardrails"],
        "human_sample": len(sample_ids),
    }, indent=2, ensure_ascii=False))
    return 0


STAGES = {"aggregate": stage_aggregate, "solver-input": stage_solver_input, "finalize": stage_finalize}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=sorted(STAGES))
    args = parser.parse_args()
    raise SystemExit(STAGES[args.stage]())
