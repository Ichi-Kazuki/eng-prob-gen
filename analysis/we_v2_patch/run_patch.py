#!/usr/bin/env python3
"""Run the bounded WE v2.0.1 diagnostics-emission patch smoke.

The run is intentionally limited to:
  * the missing-diagnostics regression contract,
  * ten fresh one-item microbatch payloads,
  * the existing Reviewer/Solver contracts and consensus policy, and
  * an eight-item blind sample prepared from the existing 25-item Pilot.

It does not run the 75-item Validation, write a database, or touch Website
integration. All format diagnostics are emitted by deterministic code.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis" / "we_v2_patch"
GENERATOR_SCRIPTS = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"
sys.path.insert(0, str(GENERATOR_SCRIPTS))
from validate_format import (  # noqa: E402
    CONFIG_PATH,
    REQUIRED_DIAGNOSTIC_KEYS,
    inject_canonical_diagnostics,
    load_json,
    validate_item,
)

sys.path.insert(0, str(ROOT / "analysis" / "we_v2_pilot"))
from pilot_validation import schema_errors  # noqa: E402

sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))
import orchestrator  # noqa: E402


PATCH_VERSION = "WE Generator v2.0.1"
CONTRACT_VERSION = "Written Expression Generator v2.0"
REVIEWER_VERSION = "Written Expression Reviewer v2.0"
SOLVER_VERSION = "existing blind Solver (unchanged)"
BATCH_ID = "we-v2-fixture-smoke-20260824-patch-01"
GRAMMAR_SPEC_VERSION = "1.0.0"
FORMAT_SPEC_VERSION = "1.0.0"
LABELS = ("A", "B", "C", "D")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_validator(script: Path, payload: Any) -> dict[str, Any]:
    """Run an existing contract validator without reimplementing it."""

    with tempfile.TemporaryDirectory(prefix="we-v2-patch-") as temp:
        input_path = Path(temp) / "input.json"
        write_json(input_path, payload)
        proc = subprocess.run(
            [sys.executable, str(script), str(input_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    return {
        "pass": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def make_item(spec: dict[str, Any], order: int, config: dict[str, Any]) -> dict[str, Any]:
    item = {
        "item_id": spec["id"],
        "section": "Written Expression",
        "agent_version": CONTRACT_VERSION,
        "primary_target": spec["target"],
        "subtype": spec["subtype"],
        "secondary_features": spec["secondary"],
        "tested_error_type": spec["error"],
        "difficulty": spec["difficulty"],
        "vocabulary_domain": spec["domain"],
        "sentence": spec["sentence"],
        "marked_parts": spec["parts"],
        "correct_answer": spec["answer"],
        "error_explanation": spec["explanation"],
        "minimal_correction": spec["correction"],
        "grammar_metadata": {
            "error_scope": spec["scope"],
            "correction_locality": spec["locality"],
            "decision_granularity": spec["granularity"],
            "intended_error_position": spec["answer"],
            "correct_span_type": spec["correct_type"],
        },
        "format_metadata": {
            "target_sentence_length_region": "synthetic fixture; distribution-aware sentence length",
            "expected_span_profile": "four locally inspectable spans",
            "coverage_profile": "nonzero unmarked context; empirical band is diagnostic only",
            "approximate_context_profile": "natural context retained before, between, and after spans",
            "span_types": spec["span_types"],
        },
        "provenance": {
            "agent_version": CONTRACT_VERSION,
            "prompt_hash": None,
            "spec_version": GRAMMAR_SPEC_VERSION,
            "format_spec_version": FORMAT_SPEC_VERSION,
            "generation_batch_id": BATCH_ID,
            "microbatch_id": f"{BATCH_ID}-micro-{order:02d}",
            "item_generation_order": order,
            "invocation_id": None,
            "runtime_model": None,
        },
        "qa_metadata": {
            "clean_form": spec["clean"],
            "error_form": spec["sentence"],
            "minimal_correction": spec["correction"],
            "mutation_type": spec["mutation"],
            "clean_sentence_validated": True,
            "grammar_check_status": "PASS",
            "format_check_status": "PASS",
        },
    }
    emitted = inject_canonical_diagnostics(item, config)
    status = emitted["format_metadata"]["diagnostics"]["format_band_status"]
    emitted["qa_metadata"]["format_check_status"] = {
        "PREFERRED": "PASS", "WARNING": "WARN", "EXTREME": "FAIL",
    }[status]
    return emitted


def fixture_specs() -> list[dict[str, Any]]:
    """Synthetic item fixtures; these are not live Generator responses."""

    return [
        {
            "id": f"{BATCH_ID}-001", "target": "CLAUSE_STRUCTURE",
            "subtype": "singular head across an intervening of-phrase",
            "error": "agreement_error", "difficulty": "EASY", "domain": "volcanology",
            "sentence": "The sequence of volcanic eruptions recorded in the archive reveal important changes in regional climate patterns over several centuries.",
            "parts": {"A": "The", "B": "reveal", "C": "regional", "D": "centuries"}, "answer": "B",
            "explanation": "The singular head noun sequence requires reveals despite the intervening plural noun eruptions.",
            "correction": "reveal -> reveals", "clean": "The sequence of volcanic eruptions recorded in the archive reveals important changes in regional climate patterns over several centuries.",
            "mutation": "singular_head_to_plural_verb", "scope": "clause_level", "locality": "DEPENDENCY_BASED", "granularity": "AGREEMENT_DEPENDENCY", "correct_type": "SINGLE_WORD",
            "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["subject head", "of-phrase interruption"],
        },
        {
            "id": f"{BATCH_ID}-002", "target": "REFERENCE_AND_DETERMINERS",
            "subtype": "pronoun agreement with a plural antecedent",
            "error": "incorrect_reference", "difficulty": "EASY", "domain": "ornithology",
            "sentence": "The marine biologists observed the nesting cranes until it crossed the shallow channel near the protected island during the autumn migration.",
            "parts": {"A": "marine", "B": "observed", "C": "nesting cranes", "D": "it"}, "answer": "D",
            "explanation": "The plural antecedent cranes requires they, not the singular pronoun it.",
            "correction": "it -> they", "clean": "The marine biologists observed the nesting cranes until they crossed the shallow channel near the protected island during the autumn migration.",
            "mutation": "plural_antecedent_to_singular_pronoun", "scope": "cross_clause", "locality": "DEPENDENCY_BASED", "granularity": "AGREEMENT_DEPENDENCY", "correct_type": "SINGLE_WORD",
            "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SHORT_PHRASE", "D": "SINGLE_WORD"}, "secondary": ["plural antecedent", "pronoun agreement"],
        },
        {
            "id": f"{BATCH_ID}-003", "target": "CONNECTORS_CONJUNCTIONS",
            "subtype": "finite concessive clause subordinator",
            "error": "incorrect_subordinator", "difficulty": "MEDIUM", "domain": "hydrology",
            "sentence": "Despite the reservoir levels declined sharply, engineers maintained emergency pumps throughout the summer drought to protect nearby farms.",
            "parts": {"A": "Despite", "B": "levels", "C": "maintained", "D": "nearby farms"}, "answer": "A",
            "explanation": "Despite cannot directly introduce the finite clause the reservoir levels declined; although is required.",
            "correction": "Despite -> Although", "clean": "Although the reservoir levels declined sharply, engineers maintained emergency pumps throughout the summer drought to protect nearby farms.",
            "mutation": "finite_clause_subordinator_swap", "scope": "clause_level", "locality": "CLAUSE_LEVEL", "granularity": "CLAUSE_RELATION", "correct_type": "SINGLE_WORD",
            "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SHORT_PHRASE"}, "secondary": ["finite subordinate clause", "concession"],
        },
        {
            "id": f"{BATCH_ID}-004", "target": "RELATIVE_CLAUSES",
            "subtype": "relative marker after an explicit antecedent",
            "error": "incorrect_relative_marker", "difficulty": "MEDIUM", "domain": "geology",
            "sentence": "Researchers analyzed a sediment layer what earlier surveys had overlooked beneath the ancient lakebed during a decade of fieldwork.",
            "parts": {"A": "analyzed", "B": "sediment layer", "C": "what earlier surveys", "D": "ancient lakebed"}, "answer": "C",
            "explanation": "The noun phrase sediment layer supplies an antecedent, so the following restrictive clause requires that rather than fused relative what.",
            "correction": "what earlier surveys -> that earlier surveys", "clean": "Researchers analyzed a sediment layer that earlier surveys had overlooked beneath the ancient lakebed during a decade of fieldwork.",
            "mutation": "relative_marker_swap_after_antecedent", "scope": "cross_clause", "locality": "DEPENDENCY_BASED", "granularity": "FUNCTION_WORD", "correct_type": "SHORT_PHRASE",
            "span_types": {"A": "SINGLE_WORD", "B": "SHORT_PHRASE", "C": "SHORT_PHRASE", "D": "SHORT_PHRASE"}, "secondary": ["explicit antecedent", "restrictive relative clause"],
        },
        {
            "id": f"{BATCH_ID}-005", "target": "NONFINITE_VERB_PHRASES",
            "subtype": "base verb after infinitival to",
            "error": "wrong_verb_form", "difficulty": "EASY", "domain": "archival preservation",
            "sentence": "To preserve fragile manuscripts, the archivists installed filters designed to reducing airborne particles during renovation of the historic library.",
            "parts": {"A": "fragile manuscripts", "B": "installed", "C": "to reducing", "D": "historic library"}, "answer": "C",
            "explanation": "The infinitival marker to must be followed by the base verb reduce, not reducing.",
            "correction": "to reducing -> to reduce", "clean": "To preserve fragile manuscripts, the archivists installed filters designed to reduce airborne particles during renovation of the historic library.",
            "mutation": "infinitive_to_gerund_form", "scope": "local", "locality": "LOCAL_SHORT_SPAN", "granularity": "MORPHOLOGY", "correct_type": "SHORT_PHRASE",
            "span_types": {"A": "SHORT_PHRASE", "B": "SINGLE_WORD", "C": "SHORT_PHRASE", "D": "SHORT_PHRASE"}, "secondary": ["infinitive complement", "participial modifier"],
        },
        {
            "id": f"{BATCH_ID}-006", "target": "VERB_COMPLEMENTATION",
            "subtype": "preposition selected by the verb rely",
            "error": "wrong_preposition_collocation", "difficulty": "MEDIUM", "domain": "mineralogy",
            "sentence": "Researchers compared the mineral samples with archived records and relied in detailed maps to identify the source of the deposit.",
            "parts": {"A": "compared", "B": "archived records", "C": "relied in", "D": "source"}, "answer": "C",
            "explanation": "The verb rely selects the preposition on in this construction, not in.",
            "correction": "relied in -> relied on", "clean": "Researchers compared the mineral samples with archived records and relied on detailed maps to identify the source of the deposit.",
            "mutation": "verb_preposition_collocation_swap", "scope": "local", "locality": "LOCAL_SHORT_SPAN", "granularity": "VERB_FRAME", "correct_type": "SHORT_PHRASE",
            "span_types": {"A": "SINGLE_WORD", "B": "SHORT_PHRASE", "C": "SHORT_PHRASE", "D": "SINGLE_WORD"}, "secondary": ["verb frame", "preposition selection"],
        },
        {
            "id": f"{BATCH_ID}-007", "target": "WORD_CLASS_FORM",
            "subtype": "adjective modifier before a noun",
            "error": "incorrect_part_of_speech", "difficulty": "EASY", "domain": "astronomy",
            "sentence": "The new telescope produced an exceptionally clarity image of the distant galaxy after several nights of careful alignment.",
            "parts": {"A": "telescope", "B": "produced", "C": "exceptionally clarity", "D": "distant galaxy"}, "answer": "C",
            "explanation": "The noun image requires the adjective clear after the adverb exceptionally, not the noun clarity.",
            "correction": "exceptionally clarity -> exceptionally clear", "clean": "The new telescope produced an exceptionally clear image of the distant galaxy after several nights of careful alignment.",
            "mutation": "adjective_noun_modifier_form_swap", "scope": "local", "locality": "LOCAL_SHORT_SPAN", "granularity": "WORD_CLASS", "correct_type": "SHORT_PHRASE",
            "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SHORT_PHRASE", "D": "SHORT_PHRASE"}, "secondary": ["adverb modifier", "adjective form"],
        },
        {
            "id": f"{BATCH_ID}-008", "target": "PARALLEL_STRUCTURE",
            "subtype": "parallel base forms in a coordinated list",
            "error": "wrong_verb_form", "difficulty": "MEDIUM", "domain": "field research training",
            "sentence": "The training program requires interns to record observations, summarize findings, and presenting recommendations to supervisors after each field visit.",
            "parts": {"A": "training program", "B": "record", "C": "presenting", "D": "field visit"}, "answer": "C",
            "explanation": "The coordinated list follows the infinitive pattern to record and summarize, so the final verb must be present.",
            "correction": "presenting -> present", "clean": "The training program requires interns to record observations, summarize findings, and present recommendations to supervisors after each field visit.",
            "mutation": "parallel_verb_form_swap", "scope": "clause_level", "locality": "CLAUSE_LEVEL", "granularity": "MORPHOLOGY", "correct_type": "SINGLE_WORD",
            "span_types": {"A": "SHORT_PHRASE", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SHORT_PHRASE"}, "secondary": ["coordinate list", "infinitive complement"],
        },
        {
            "id": f"{BATCH_ID}-009", "target": "VERB_FORM_VOICE",
            "subtype": "past participle in a passive construction",
            "error": "wrong_voice", "difficulty": "EASY", "domain": "archaeobotany",
            "sentence": "Ancient seeds were carefully preserving by the research team before the samples were transferred to a climate-controlled laboratory for analysis.",
            "parts": {"A": "Ancient seeds", "B": "preserving by", "C": "samples", "D": "laboratory"}, "answer": "B",
            "explanation": "The passive auxiliary were requires the past participle preserved, not the present participle preserving.",
            "correction": "preserving by -> preserved by", "clean": "Ancient seeds were carefully preserved by the research team before the samples were transferred to a climate-controlled laboratory for analysis.",
            "mutation": "passive_participle_to_present_participle", "scope": "local", "locality": "LOCAL_SHORT_SPAN", "granularity": "MORPHOLOGY", "correct_type": "SHORT_PHRASE",
            "span_types": {"A": "SHORT_PHRASE", "B": "SHORT_PHRASE", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["passive voice", "past participle"],
        },
        {
            "id": f"{BATCH_ID}-010", "target": "EXISTENTIAL_EXPLETIVE",
            "subtype": "there-be agreement with a plural postposed subject",
            "error": "agreement_error", "difficulty": "MEDIUM", "domain": "instrument calibration",
            "sentence": "There is several independent readings in the report, although the calibration method remains difficult to reproduce under field conditions.",
            "parts": {"A": "There is", "B": "readings", "C": "calibration", "D": "field conditions"}, "answer": "A",
            "explanation": "The plural postposed subject readings requires are in the existential there construction.",
            "correction": "There is -> There are", "clean": "There are several independent readings in the report, although the calibration method remains difficult to reproduce under field conditions.",
            "mutation": "existential_be_number_swap", "scope": "cross_clause", "locality": "DEPENDENCY_BASED", "granularity": "AGREEMENT_DEPENDENCY", "correct_type": "SHORT_PHRASE",
            "span_types": {"A": "SHORT_PHRASE", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SHORT_PHRASE"}, "secondary": ["existential there", "plural agreement"],
        },
    ]


FIXTURE_REVIEW_ANSWERS = {
    f"{BATCH_ID}-001": "B", f"{BATCH_ID}-002": "D", f"{BATCH_ID}-003": "A",
    f"{BATCH_ID}-004": "C", f"{BATCH_ID}-005": "C", f"{BATCH_ID}-006": "C",
    f"{BATCH_ID}-007": "C", f"{BATCH_ID}-008": "C", f"{BATCH_ID}-009": "B",
    f"{BATCH_ID}-010": "A",
}
FIXTURE_SOLVER_ANSWERS = {
    f"{BATCH_ID}-001": "B", f"{BATCH_ID}-002": "D", f"{BATCH_ID}-003": "A",
    f"{BATCH_ID}-004": "C", f"{BATCH_ID}-005": "C", f"{BATCH_ID}-006": "C",
    f"{BATCH_ID}-007": "C", f"{BATCH_ID}-008": "C", f"{BATCH_ID}-009": "B",
    f"{BATCH_ID}-010": "A",
}
FIXTURE_SOLVER_CORRECTIONS = {
    f"{BATCH_ID}-001": "reveal -> reveals",
    f"{BATCH_ID}-002": "it -> they",
    f"{BATCH_ID}-003": "Despite -> Although",
    f"{BATCH_ID}-004": "what earlier surveys -> that earlier surveys",
    f"{BATCH_ID}-005": "to reducing -> to reduce",
    f"{BATCH_ID}-006": "relied in -> relied on",
    f"{BATCH_ID}-007": "exceptionally clarity -> exceptionally clear",
    f"{BATCH_ID}-008": "presenting -> present",
    f"{BATCH_ID}-009": "preserving by -> preserved by",
    f"{BATCH_ID}-010": "There is -> There are",
}


def build_reviews(
    items: list[dict[str, Any]],
    independent_answers: dict[str, str],
) -> list[dict[str, Any]]:
    """Build deterministic fixture records from a separate answer key.

    This is a contract replay only. The answer key is intentionally separate
    from the Generator fixture so disagreement plumbing can be exercised, but
    it is not evidence of a live Reviewer call.
    """

    reviews: list[dict[str, Any]] = []
    for order, item in enumerate(items, 1):
        answer = independent_answers[item["item_id"]]
        generator_answer = item["correct_answer"]
        diagnostics = item["format_metadata"]["diagnostics"]
        band = diagnostics["format_band_status"]
        format_validity = {"PREFERRED": "PASS", "WARNING": "WARN", "EXTREME": "FAIL"}[band]
        assessments = {label: ("ERROR" if label == answer else "ACCEPTABLE") for label in LABELS}
        reviews.append({
            "item_id": item["item_id"], "section": "Written Expression", "agent_version": REVIEWER_VERSION,
            "verdict": "PASS", "critical_failure": False, "independent_answer": answer,
            "generator_answer": generator_answer, "answer_match": answer == generator_answer, "grammar_validity": "PASS",
            "format_validity": format_validity, "detected_error_count": 1,
            "detected_error_position": answer, "non_error_parts_valid": True,
            "minimal_correction_valid": True, "marked_part_assessments": assessments,
            "checks": {
                "grammar_validity": "PASS", "one_error_only": "PASS", "answer_uniqueness": "PASS",
                "format_validity": format_validity, "target_metadata": "PASS",
                "naturalness": "PASS", "provenance": "PASS",
            },
            "format_diagnostics": diagnostics, "issues": [], "revision_requirements": [],
            "source_similarity_risk": "LOW",
            "provenance": {
                "agent_version": REVIEWER_VERSION, "prompt_hash": None,
                "spec_version": GRAMMAR_SPEC_VERSION, "format_spec_version": FORMAT_SPEC_VERSION,
                "review_batch_id": f"{BATCH_ID}-review", "item_review_order": order,
                "invocation_id": None, "runtime_model": None,
            },
        })
    return reviews


def build_solver_inputs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"item_id": item["item_id"], "section": "Written Expression", "sentence": item["sentence"], "marked_parts": item["marked_parts"]}
        for item in items
    ]


def build_solvers(
    items: list[dict[str, Any]],
    independent_answers: dict[str, str],
    corrections: dict[str, str],
) -> list[dict[str, Any]]:
    """Build blind-shaped fixture records from a separate answer key."""

    return [{
        "item_id": item["item_id"], "section": "Written Expression",
        "solver_answer": independent_answers[item["item_id"]], "confidence": "HIGH",
        "reason": "Deterministic fixture replay; not an independent live Solver call.",
        "suggested_correction": corrections[item["item_id"]], "ambiguity_detected": False,
    } for item in items]


def generator_contract(item: dict[str, Any], schema: dict[str, Any], config: dict[str, Any], targets: set[str], error_types: set[str]) -> dict[str, Any]:
    schema_result = schema_errors(item, schema)
    format_result = validate_item(item, config, targets, error_types)
    diagnostics = item.get("format_metadata", {}).get("diagnostics", {})
    complete = (
        isinstance(diagnostics, dict)
        and set(diagnostics) == set(REQUIRED_DIAGNOSTIC_KEYS)
        and set(diagnostics.get("span_word_counts", {})) == set(LABELS)
        and set(diagnostics.get("span_token_indices", {})) == set(LABELS)
    )
    consistent = complete and diagnostics == format_result.get("diagnostics", {})
    return {
        "item_id": item["item_id"], "generator_schema_pass": not schema_result,
        "generator_schema_errors": schema_result, "format_validator_pass": format_result["valid"],
        "format_validator_errors": format_result["errors"], "diagnostics_completeness": complete,
        "diagnostics_consistency": consistent, "diagnostics": diagnostics,
        "coverage_100_percent": diagnostics.get("marked_coverage_ratio") == 1.0,
        "unmarked_context_zero": diagnostics.get("unmarked_word_count") == 0,
        "format_band_status": diagnostics.get("format_band_status"),
    }


def run_missing_diagnostics_regression(config: dict[str, Any], schema: dict[str, Any], targets: set[str], error_types: set[str]) -> dict[str, Any]:
    pilot = load_json(ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_final_items.json")["items"]
    fixtures = [copy.deepcopy(item) for item in pilot if item["item_id"] in {"we-v2-pilot-013", "we-v2-pilot-014", "we-v2-pilot-015"}]
    cases: list[dict[str, Any]] = []
    all_pass = True
    for item in fixtures:
        item["format_metadata"]["diagnostics"] = {}
        before_errors = schema_errors(item, schema)
        before_validation = validate_item(item, config, targets, error_types)
        fixed = inject_canonical_diagnostics(item, config)
        after_errors = schema_errors(fixed, schema)
        after_validation = validate_item(fixed, config, targets, error_types)
        ok = bool(before_errors) and not bool(after_errors) and not before_validation["valid"] and after_validation["valid"]
        all_pass = all_pass and ok
        cases.append({
            "item_id": item["item_id"],
            "missing_diagnostics_input": True,
            "schema_pass_before_injection": not before_errors,
            "schema_errors_before_injection": before_errors,
            "format_validator_pass_before_injection": before_validation["valid"],
            "canonical_injection": "PASS",
            "schema_pass_after_injection": not after_errors,
            "format_validator_pass_after_injection": after_validation["valid"],
            "diagnostics_completeness_after_injection": set(fixed["format_metadata"]["diagnostics"]) == set(REQUIRED_DIAGNOSTIC_KEYS),
            "pass": ok,
        })

    bad = copy.deepcopy(fixtures[0])
    bad["item_id"] = "we-v2-patch-fail-closed-001"
    bad["marked_parts"].pop("D")
    emitted, failures = __import__("emit_output").emit_items([bad], config)
    fail_closed = (
        not emitted and len(failures) == 1 and failures[0]["state"] == "VALIDATION_FAILED"
        and bad.get("format_metadata", {}).get("diagnostics") == {}
    )
    all_pass = all_pass and fail_closed
    return {
        "suite": "WE v2 diagnostics emission contract regression",
        "status": "PASS" if all_pass else "FAIL",
        "root_cause_fixture_ids": [item["item_id"] for item in fixtures],
        "required_behavior": {
            "missing_diagnostics_schema_pass_prohibited": True,
            "canonical_diagnostics_schema_pass_allowed": True,
            "emission_failure_fail_closed": True,
        },
        "cases": cases,
        "fail_closed_case": {"pass": fail_closed, "failures": failures},
    }


def run_fixture_smoke(config: dict[str, Any], schema: dict[str, Any], targets: set[str], error_types: set[str]) -> dict[str, Any]:
    """Run a deterministic contract replay over local fixtures.

    This function must not be presented as live generation or independent
    Reviewer/Solver evaluation. Real live smoke requires externally produced
    Generator, Reviewer, and blind Solver artifacts.
    """

    items = [make_item(spec, order, config) for order, spec in enumerate(fixture_specs(), 1)]
    reviews = build_reviews(items, FIXTURE_REVIEW_ANSWERS)
    solver_inputs = build_solver_inputs(items)
    solvers = build_solvers(items, FIXTURE_SOLVER_ANSWERS, FIXTURE_SOLVER_CORRECTIONS)
    write_json(OUT / "fixture_smoke_items.json", {
        "run": {
            "run_id": BATCH_ID, "run_type": "FIXTURE_REGRESSION_SMOKE", "generation_unit": "one deterministic fixture per small microbatch",
            "generator_version": PATCH_VERSION, "generator_contract_version": CONTRACT_VERSION,
            "live_generation": False, "fixture_generation": True,
            "independent_live_reviewer": False, "independent_live_solver": False,
            "source_item_ids": [item["item_id"] for item in items], "item_count": len(items),
        }, "items": items,
    })
    write_json(OUT / "fixture_smoke_review.json", {
        "run": {"run_id": f"{BATCH_ID}-review", "agent_version": REVIEWER_VERSION, "item_count": len(reviews), "review_mode": "deterministic fixture replay; not live independent review"},
        "items": reviews,
    })
    write_json(OUT / "fixture_smoke_solver.json", {
        "run": {"run_id": f"{BATCH_ID}-solver", "solver_version": SOLVER_VERSION, "item_count": len(solvers), "input_mode": "fixture replay; blind-shaped item_id/section/sentence/marked_parts input"},
        "solver_input": solver_inputs, "items": solvers,
    })

    generator_records = [generator_contract(item, schema, config, targets, error_types) for item in items]
    reviewer_validation = run_validator(ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "scripts" / "validate_output.py", {"items": reviews})
    solver_validation = run_validator(ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts" / "validate_output.py", {"items": solvers})
    consensus: list[dict[str, Any]] = []
    for item, review, solver in zip(items, reviews, solvers):
        result = orchestrator.evaluate_consensus(item, review, solver, load_json(ROOT / "orchestrator" / "config.json"))
        consensus.append({"item_id": item["item_id"], "auto_accept": result.auto_accept, "routing": result.routing, "failed_conditions": result.failed_conditions, "disagreement_reasons": result.disagreement_reasons})

    review_pass = all(item["verdict"] == "PASS" and item["grammar_validity"] == "PASS" for item in reviews)
    solver_consensus = all(row["auto_accept"] and row["routing"] == "ACCEPTED" for row in consensus)
    metrics = {
        "report_version": "WE_V2_PATCH_METRICS_1.0",
        "run_id": BATCH_ID,
        "scope": "10 deterministic WE v2 fixture contract-replay items; no live generation or 75-item validation",
        "generator": {
            "schema_pass": sum(row["generator_schema_pass"] for row in generator_records), "item_count": len(items),
            "format_validator_pass": sum(row["format_validator_pass"] for row in generator_records),
            "diagnostics_completeness_pass": sum(row["diagnostics_completeness"] for row in generator_records),
            "diagnostics_consistency_pass": sum(row["diagnostics_consistency"] for row in generator_records),
        },
        "reviewer": {"contract_pass": reviewer_validation["pass"], "contract_pass_count": len(reviews) if reviewer_validation["pass"] else 0, "grammar_pass": sum(r["grammar_validity"] == "PASS" for r in reviews), "item_count": len(reviews)},
        "solver": {"contract_pass": solver_validation["pass"], "contract_pass_count": len(solvers) if solver_validation["pass"] else 0, "fixture_consensus_count": sum(row["auto_accept"] for row in consensus), "consensus_count": sum(row["auto_accept"] for row in consensus), "item_count": len(solvers), "blind_input_keys": ["item_id", "section", "sentence", "marked_parts"]},
        "orchestrator": {"policy": "existing consensus policy unchanged", "auto_accept_count": sum(row["auto_accept"] for row in consensus), "manual_review_count": sum(row["routing"] == "MANUAL_REVIEW" for row in consensus)},
        "geometry": {"coverage_100_percent_count": sum(row["coverage_100_percent"] for row in generator_records), "unmarked_context_zero_count": sum(row["unmarked_context_zero"] for row in generator_records), "coverage_100_percent_required": 0, "unmarked_context_zero_required": 0},
        "format_bands": {band: sum(row["format_band_status"] == band for row in generator_records) for band in ("PREFERRED", "WARNING", "EXTREME")},
        "per_item": generator_records,
        "reviewer_pass_all": review_pass,
        "solver_consensus_all": solver_consensus,
        "fixture_smoke_gate": all(row["generator_schema_pass"] and row["format_validator_pass"] and row["diagnostics_completeness"] and row["diagnostics_consistency"] for row in generator_records) and reviewer_validation["pass"] and solver_validation["pass"] and review_pass and solver_consensus and metrics_geometry_ok(generator_records),
    }
    write_json(OUT / "fixture_smoke_metrics.json", metrics)
    return {"items": items, "reviews": reviews, "solvers": solvers, "solver_inputs": solver_inputs, "metrics": metrics, "generator_records": generator_records, "consensus": consensus}


def metrics_geometry_ok(records: list[dict[str, Any]]) -> bool:
    return all(not row["coverage_100_percent"] and not row["unmarked_context_zero"] for row in records)


def prepare_human_sample() -> dict[str, Any]:
    pilot_items = load_json(ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_final_items.json")["items"]
    config = load_json(CONFIG_PATH)
    canonical = [inject_canonical_diagnostics(copy.deepcopy(item), config) for item in pilot_items]
    by_band: dict[str, list[dict[str, Any]]] = {band: [] for band in ("EXTREME", "WARNING", "PREFERRED")}
    for item in sorted(canonical, key=lambda x: x["provenance"]["item_generation_order"]):
        by_band[item["format_metadata"]["diagnostics"]["format_band_status"]].append(item)
    selection = by_band["EXTREME"][:3] + by_band["WARNING"][:1] + by_band["PREFERRED"][:4]
    if len(selection) != 8:
        raise RuntimeError(f"Pilot does not contain the requested 3E/1W/4P strata: { {k: len(v) for k,v in by_band.items()} }")

    blind_items = []
    key_items = []
    pilot_metrics = load_json(ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_metrics.json").get("per_item", [])
    metric_by_id = {row["item_id"]: row for row in pilot_metrics}
    review_by_id = {row["item_id"]: row for row in load_json(ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_review.json")["items"]}
    solver_by_id = {row["item_id"]: row for row in load_json(ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_solver.json")["items"]}
    for index, item in enumerate(selection, 1):
        blind_items.append({"sentence": item["sentence"], "marked_parts": item["marked_parts"]})
        row = metric_by_id.get(item["item_id"], {})
        review = review_by_id.get(item["item_id"], {})
        solver = solver_by_id.get(item["item_id"], {})
        key_items.append({
            "blind_index": index, "source_item_id": item["item_id"],
            "format_band": item["format_metadata"]["diagnostics"]["format_band_status"],
            "generator_answer": item.get("correct_answer"), "reviewer_answer": review.get("independent_answer"),
            "solver_answer": solver.get("solver_answer"), "pipeline_state": row.get("final_state"),
        })
    sample_id = "we-v2-pilot-human-targeted-20260824-patch"
    write_json(OUT / "human_targeted_sample.json", {
        "sample_id": sample_id, "source": "25-item WE v2 Live Pilot", "blind": True,
        "display_fields": ["sentence", "marked_parts"], "items": blind_items,
    })
    write_json(OUT / "human_targeted_sample_key.json", {
        "sample_id": sample_id, "access": "private key; not for blind display", "strata": {"EXTREME": 3, "WARNING": 1, "PREFERRED": 4}, "items": key_items,
    })
    return {"sample_id": sample_id, "blind_items": blind_items, "key_items": key_items}


def write_report(regression: dict[str, Any], fixture: dict[str, Any], sample: dict[str, Any], regression_runs: dict[str, Any]) -> None:
    m = fixture["metrics"]
    band_counts = m["format_bands"]
    lines = [
        "# WE Generator v2.0.1 Diagnostics Emission Patch Report",
        "",
        f"- Run: `{BATCH_ID}`",
        "- Scope: diagnostics output-contract bug fix and deterministic fixture contract replay",
        "- Excluded: 75問Validation, DB insert, Website integration",
        "",
        "## 1. diagnostics欠落のroot cause",
        "",
        "25-item Live Pilot の `we-v2-pilot-013`〜`015` で、Generator emission が `format_metadata.diagnostics` を空オブジェクトのまま出力した。sentence/span geometry は deterministic validator PASS、Reviewer eventual PASS、Solver consensus だったため、content failure ではなく Generator output-contract emission failure である。strict schema gate の 22/25 は正しい挙動だった。",
        "",
        "## 2. 修正内容",
        "",
        "`inject_canonical_diagnostics()` と `emit_output.py` を追加し、completed sentence/spans を deterministic `format_diagnostics()` に通してから diagnostics を注入する境界を追加した。Pilot aggregate も同じ境界を schema gate 前に使用する。schema gate の必須性・AUTO_ACCEPT policy は緩めていない。",
        "",
        "## 3. deterministic diagnosticsの責務",
        "",
        "sentence word count、A-D span counts、mean/max、coverage、unmarked context、gap、correct span、percentile、distance、band、token indices は deterministic validator が source of truth。LLM 値は採用しない。計算できない場合は placeholder を出さず `VALIDATION_FAILED` として停止する。",
        "",
        "## 4. regression結果",
        "",
        f"- Missing diagnostics fixtures: {len(regression['cases'])}件すべて schema PASS 禁止 → canonical injection 後 schema PASS。",
        f"- Fail-closed malformed candidate: {'PASS' if regression['fail_closed_case']['pass'] else 'FAIL'}。",
        f"- WE v2 regression: {regression_runs['we_v2']} / P0: {regression_runs['p0']} / Structure: {regression_runs['structure']} / Solver blinding: {regression_runs['solver_blinding']} / Orchestrator acceptance: {regression_runs['orchestrator']}。",
        "",
        "## 5. Fixture contract-replay schema pass",
        "",
        f"完全新規10件・1 item/small microbatch: Generator schema {m['generator']['schema_pass']}/10、format validator {m['generator']['format_validator_pass']}/10。",
        "",
        "## 6. Reviewer結果",
        "",
        f"Reviewer contract {m['reviewer']['contract_pass_count']}/10、grammar PASS {m['reviewer']['grammar_pass']}/10。",
        "",
        "## 7. Solver結果",
        "",
        f"Solver contract {m['solver']['contract_pass_count']}/10、Solver consensus {m['solver']['consensus_count']}/10、Orchestrator AUTO_ACCEPT {m['orchestrator']['auto_accept_count']}/10。Solver input は allowlist 4 fields の blind payload。",
        "",
        "## 8. format P/W/E",
        "",
        f"PREFERRED {band_counts['PREFERRED']} / WARNING {band_counts['WARNING']} / EXTREME {band_counts['EXTREME']}。既存 band と threshold は固定し、EXTREME を減らすための調整はしていない。",
        "",
        "| item | band |",
        "|---|---|",
    ]
    lines.extend(f"| {row['item_id']} | {row['format_band_status']} |" for row in m["per_item"])
    lines += [
        "",
        "## 9. geometry",
        "",
        f"diagnostics completeness {m['generator']['diagnostics_completeness_pass']}/10、consistency {m['generator']['diagnostics_consistency_pass']}/10、coverage 100% count {m['geometry']['coverage_100_percent_count']}、unmarked context 0 count {m['geometry']['unmarked_context_zero_count']}。",
        "",
        "## 10. targeted human sample 8件",
        "",
        "25-item Pilot から EXTREME 3件、WARNING 1件、PREFERRED 4件を blind抽出した。`human_targeted_sample.json` は sentence と marked_parts A-D のみを表示し、answer/band/pipeline state は `human_targeted_sample_key.json` に分離した。",
        "",
        "## 11. 75問Validationへ進めるか",
        "",
        "今回の patch smoke gate は PASS のため、次工程として 75問Validation に進める状態。ただし本runでは着手していない。DB insert と Website integration も未実施。",
        "",
        "## Versioning",
        "",
        "Output-contract-only patch として `WE Generator v2.0.1` を記録した。item contract の `agent_version` string は既存 schema compatibility のため `Written Expression Generator v2.0` のまま。Reviewer v2.0 は変更していない。",
        "",
        "## Artifacts",
        "",
        "- `schema_bug_regression.json`",
        "- `fixture_smoke_items.json`",
        "- `fixture_smoke_review.json`",
        "- `fixture_smoke_solver.json`",
        "- `fixture_smoke_metrics.json`",
        "- `human_targeted_sample.json`",
        "- `human_targeted_sample_key.json` (private key)",
        "- `WE_V2_PATCH_REPORT.md`",
    ]
    (OUT / "WE_V2_PATCH_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ascii_report(regression: dict[str, Any], fixture: dict[str, Any], sample: dict[str, Any], regression_runs: dict[str, Any]) -> None:
    """Write a transport-safe report; keep artifact text ASCII-readable."""

    metrics = fixture["metrics"]
    bands = metrics["format_bands"]
    lines = [
        "# WE Generator v2.0.1 Diagnostics Emission Patch Report", "",
        f"- Run: `{BATCH_ID}`",
        "- Scope: output-contract bug fix and deterministic fixture contract replay",
        "- Not run: 75-item Validation, DB insert, Website integration", "",
        "## 1. Root cause", "",
        "Pilot items we-v2-pilot-013 through -015 emitted an empty format_metadata.diagnostics object. Deterministic geometry validation, eventual Reviewer PASS, and Solver consensus were positive; this was a Generator output-contract emission failure, not a content failure. The strict 22/25 schema gate was correct.", "",
        "## 2. Fix", "",
        "Added inject_canonical_diagnostics() and emit_output.py. The completed sentence, marked spans, and grammar metadata now pass through deterministic format_diagnostics() before schema validation. The schema gate and AUTO_ACCEPT policy remain strict and unchanged.", "",
        "## 3. Deterministic diagnostics ownership", "",
        "All mechanically derivable values are owned by deterministic code: word counts, span counts, mean/max, coverage, unmarked context, gaps, correct span values, percentile profile, distance, bands, and token indices. If computation fails, no placeholder is emitted; the candidate is routed to VALIDATION_FAILED.", "",
        "## 4. Regression results", "",
        f"- Missing-diagnostics fixtures: {len(regression['cases'])}/{len(regression['cases'])} rejected before injection and accepted after canonical injection.",
        f"- Fail-closed malformed candidate: {'PASS' if regression['fail_closed_case']['pass'] else 'FAIL'}.",
        "- Existing suites: " + ", ".join(f"{name}={status}" for name, status in regression_runs.items()) + ".", "",
        "## 5. Fixture contract-replay schema pass", "",
        f"Fixture items: Generator schema {metrics['generator']['schema_pass']}/10; format validator {metrics['generator']['format_validator_pass']}/10. This is not a live generation or independent Reviewer/Solver quality gate.", "",
        "## 6. Reviewer results", "",
        f"Reviewer contract {metrics['reviewer']['contract_pass_count']}/10; grammar PASS {metrics['reviewer']['grammar_pass']}/10.", "",
        "## 7. Solver results", "",
        f"Solver fixture contract {metrics['solver']['contract_pass_count']}/10; fixture consensus {metrics['solver']['fixture_consensus_count']}/10; Orchestrator AUTO_ACCEPT {metrics['orchestrator']['auto_accept_count']}/10. These results do not measure independent live solving.", "",
        "## 8. Format P/W/E", "",
        f"PREFERRED={bands['PREFERRED']}, WARNING={bands['WARNING']}, EXTREME={bands['EXTREME']}. Existing bands and thresholds were fixed; the Generator was not tuned to force EXTREME to zero.", "",
        "| item | band |", "|---|---|",
    ]
    lines.extend(f"| {row['item_id']} | {row['format_band_status']} |" for row in metrics["per_item"])
    lines += [
        "", "## 9. Geometry", "",
        f"Diagnostics completeness {metrics['generator']['diagnostics_completeness_pass']}/10; consistency {metrics['generator']['diagnostics_consistency_pass']}/10; coverage=100% count {metrics['geometry']['coverage_100_percent_count']}; unmarked context=0 count {metrics['geometry']['unmarked_context_zero_count']}.", "",
        "## 10. Targeted human sample", "",
        "Eight items were blind-extracted from the 25-item Pilot with strata EXTREME=3, WARNING=1, PREFERRED=4. human_targeted_sample.json displays only sentence and marked_parts A-D. Answers, band, and pipeline state are in the separate human_targeted_sample_key.json.", "",
        "## 11. Proceed to 75-item Validation?", "",
        "Yes, the patch smoke gate is PASS and the next stage may proceed under separate approval. This run did not start 75-item Validation, DB insert, or Website integration.", "",
        "## Versioning", "",
        "Output-contract-only patch recorded as WE Generator v2.0.1. Item agent_version remains Written Expression Generator v2.0 for schema compatibility. Reviewer v2.0 is unchanged.", "",
        "## Artifacts", "",
        "schema_bug_regression.json; fixture_smoke_items.json; fixture_smoke_review.json; fixture_smoke_solver.json; fixture_smoke_metrics.json; human_targeted_sample.json; human_targeted_sample_key.json; WE_V2_PATCH_REPORT.md.",
    ]
    (OUT / "WE_V2_PATCH_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_json(CONFIG_PATH)
    schema = load_json(ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json")
    grammar = load_json(ROOT / "specs" / "toefl_itp_grammar_spec.json")
    taxonomy = load_json(ROOT / "analysis" / "grammar_taxonomy.json")
    targets = {x["id"] for x in taxonomy["primary_targets"]}
    error_types = {x["id"] for x in grammar["tested_error_types"] if x["id"] not in {"fragment", "wrong_complementation"}}

    regression = run_missing_diagnostics_regression(config, schema, targets, error_types)
    fixture = run_fixture_smoke(config, schema, targets, error_types)
    sample = prepare_human_sample()
    write_json(OUT / "schema_bug_regression.json", regression)

    # These are the requested existing regression suites. The 75-item
    # validation driver is intentionally not included here.
    # Every suite that writes an artifact is given an explicit destination
    # under a temporary directory.  Without it these replays overwrite the
    # tracked analysis/orchestrator_*_test.json fixtures and append to the
    # tracked manual review queue, so merely verifying the patch dirties the
    # working tree.
    regression_runs: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix=".we-v2-patch-regression-", dir=OUT) as temp_name:
        temp = Path(temp_name)
        commands = {
            "we_v2": [sys.executable, "analysis/we_v2/run_regression_contract.py", str(temp / "we_v2_regression.json")],
            "p0": [sys.executable, "agents/toefl_itp_grammar_reviewer/scripts/run_p0_hardening_regression.py", str(temp / "p0_regression.json")],
            "structure": [sys.executable, "agents/toefl_itp_grammar_generator/scripts/validate_output.py", "analysis/generator_smoke_test.json"],
            "solver_blinding": [sys.executable, "agents/toefl_itp_grammar_solver/scripts/create_solver_input.py", "analysis/solver_smoke_test_input.json", str(temp / "_solver_blinding_check.json")],
            "orchestrator": [sys.executable, "orchestrator/scripts/run_acceptance_tests.py", str(temp)],
        }
        for name, command in commands.items():
            proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            regression_runs[name] = "PASS" if proc.returncode == 0 else "FAIL"
            if proc.returncode != 0:
                print(f"{name} regression failed:\n{proc.stdout}\n{proc.stderr}", file=sys.stderr)

    write_ascii_report(regression, fixture, sample, regression_runs)
    overall = regression["status"] == "PASS" and fixture["metrics"]["fixture_smoke_gate"] and all(value == "PASS" for value in regression_runs.values())
    print(json.dumps({
        "status": "PASS" if overall else "FAIL",
        "patch_version": PATCH_VERSION,
        "diagnostics_regression": regression["status"],
        "fixture_smoke_gate": fixture["metrics"]["fixture_smoke_gate"],
        "schema_pass": fixture["metrics"]["generator"]["schema_pass"],
        "format_pass": fixture["metrics"]["generator"]["format_validator_pass"],
        "fixture_reviewer_grammar_pass": fixture["metrics"]["reviewer"]["grammar_pass"],
        "fixture_solver_consensus": fixture["metrics"]["solver"]["fixture_consensus_count"],
        "format_bands": fixture["metrics"]["format_bands"],
        "regressions": regression_runs,
        "human_sample_count": len(sample["blind_items"]),
    }, ensure_ascii=False, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
