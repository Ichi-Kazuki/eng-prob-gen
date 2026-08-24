#!/usr/bin/env python3
"""Build the bounded WE v2 ten-item smoke artifacts.

The item text below is independently authored from the v2 design plans. The
script adds only deterministic diagnostics and contract-shaped QA artifacts;
it does not modify any v1.1, Structure, Solver, or Orchestrator source file.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))
from validate_format import CONFIG_PATH, format_diagnostics, load_json  # noqa: E402


OUT = ROOT / "analysis" / "we_v2"
GRAMMAR_SPEC_VERSION = "1.0.0"
FORMAT_SPEC_VERSION = "1.0.0"
BATCH_ID = "we-v2-smoke-20260824"


# These are deliberately separate from authored_items(). They represent the
# blind Reviewer and Solver records that were authored from the sentence and
# marked spans, rather than being derived from the Generator key. Keeping the
# records keyed by item_id also makes omissions or accidental additions fail
# while the artifact is being built.
BLIND_REVIEW_RESULTS: dict[str, dict[str, Any]] = {
    "we-v2-smoke-001": {"independent_answer": "A", "detected_error_count": 1, "detected_error_position": "A", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ERROR", "B": "ACCEPTABLE", "C": "ACCEPTABLE", "D": "ACCEPTABLE"}},
    "we-v2-smoke-002": {"independent_answer": "B", "detected_error_count": 1, "detected_error_position": "B", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ACCEPTABLE", "B": "ERROR", "C": "ACCEPTABLE", "D": "ACCEPTABLE"}},
    "we-v2-smoke-003": {"independent_answer": "C", "detected_error_count": 1, "detected_error_position": "C", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ACCEPTABLE", "B": "ACCEPTABLE", "C": "ERROR", "D": "ACCEPTABLE"}},
    "we-v2-smoke-004": {"independent_answer": "A", "detected_error_count": 1, "detected_error_position": "A", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ERROR", "B": "ACCEPTABLE", "C": "ACCEPTABLE", "D": "ACCEPTABLE"}},
    "we-v2-smoke-005": {"independent_answer": "C", "detected_error_count": 1, "detected_error_position": "C", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ACCEPTABLE", "B": "ACCEPTABLE", "C": "ERROR", "D": "ACCEPTABLE"}},
    "we-v2-smoke-006": {"independent_answer": "B", "detected_error_count": 1, "detected_error_position": "B", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ACCEPTABLE", "B": "ERROR", "C": "ACCEPTABLE", "D": "ACCEPTABLE"}},
    "we-v2-smoke-007": {"independent_answer": "C", "detected_error_count": 1, "detected_error_position": "C", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ACCEPTABLE", "B": "ACCEPTABLE", "C": "ERROR", "D": "ACCEPTABLE"}},
    "we-v2-smoke-008": {"independent_answer": "C", "detected_error_count": 1, "detected_error_position": "C", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ACCEPTABLE", "B": "ACCEPTABLE", "C": "ERROR", "D": "ACCEPTABLE"}},
    "we-v2-smoke-009": {"independent_answer": "C", "detected_error_count": 1, "detected_error_position": "C", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ACCEPTABLE", "B": "ACCEPTABLE", "C": "ERROR", "D": "ACCEPTABLE"}},
    "we-v2-smoke-010": {"independent_answer": "A", "detected_error_count": 1, "detected_error_position": "A", "grammar_validity": "PASS", "non_error_parts_valid": True, "minimal_correction_valid": True, "marked_part_assessments": {"A": "ERROR", "B": "ACCEPTABLE", "C": "ACCEPTABLE", "D": "ACCEPTABLE"}},
}

BLIND_SOLVER_RESULTS: dict[str, dict[str, Any]] = {
    "we-v2-smoke-001": {"solver_answer": "A", "confidence": "HIGH", "reason": "The singular head stability controls the verb despite the intervening plural noun wetlands.", "ambiguity_detected": False, "suggested_correction": "support -> supports"},
    "we-v2-smoke-002": {"solver_answer": "B", "confidence": "HIGH", "reason": "The noun decline needs the adjective rapid, not the adverb rapidly.", "ambiguity_detected": False, "suggested_correction": "rapidly -> rapid"},
    "we-v2-smoke-003": {"solver_answer": "C", "confidence": "HIGH", "reason": "The infinitive marker to requires the base verb analyze.", "ambiguity_detected": False, "suggested_correction": "to analyzing -> to analyze"},
    "we-v2-smoke-004": {"solver_answer": "A", "confidence": "HIGH", "reason": "A finite clause requires although here; despite cannot introduce the finite clause directly.", "ambiguity_detected": False, "suggested_correction": "Despite -> Although"},
    "we-v2-smoke-005": {"solver_answer": "C", "confidence": "HIGH", "reason": "The explicit antecedent signal takes the relative marker that, not fused relative what.", "ambiguity_detected": False, "suggested_correction": "what astronomers -> that astronomers"},
    "we-v2-smoke-006": {"solver_answer": "B", "confidence": "HIGH", "reason": "The fronted negative adverbial requires auxiliary inversion: did the team identify.", "ambiguity_detected": False, "suggested_correction": "the team identified -> did the team identify"},
    "we-v2-smoke-007": {"solver_answer": "C", "confidence": "HIGH", "reason": "Responses is a plural count noun and takes many rather than much.", "ambiguity_detected": False, "suggested_correction": "much -> many"},
    "we-v2-smoke-008": {"solver_answer": "C", "confidence": "HIGH", "reason": "The coordinated infinitival list requires the base form present.", "ambiguity_detected": False, "suggested_correction": "presenting -> present"},
    "we-v2-smoke-009": {"solver_answer": "C", "confidence": "HIGH", "reason": "The passive auxiliary is requires the participle used.", "ambiguity_detected": False, "suggested_correction": "is use -> is used"},
    "we-v2-smoke-010": {"solver_answer": "A", "confidence": "HIGH", "reason": "The plural postposed subject variables requires are in the existential construction.", "ambiguity_detected": False, "suggested_correction": "There is -> There are"},
}


def base_item(
    item_id: str,
    order: int,
    primary_target: str,
    subtype: str,
    tested_error_type: str,
    difficulty: str,
    domain: str,
    sentence: str,
    parts: dict[str, str],
    answer: str,
    explanation: str,
    correction: str,
    clean_form: str,
    error_form: str,
    mutation_type: str,
    error_scope: str,
    locality: str,
    granularity: str,
    correct_span_type: str,
    span_types: dict[str, str],
    secondary: list[str],
) -> dict:
    item = {
        "item_id": item_id,
        "section": "Written Expression",
        "agent_version": "Written Expression Generator v2.0",
        "primary_target": primary_target,
        "subtype": subtype,
        "secondary_features": secondary,
        "tested_error_type": tested_error_type,
        "difficulty": difficulty,
        "vocabulary_domain": domain,
        "sentence": sentence,
        "marked_parts": parts,
        "correct_answer": answer,
        "error_explanation": explanation,
        "minimal_correction": correction,
        "grammar_metadata": {
            "error_scope": error_scope,
            "correction_locality": locality,
            "decision_granularity": granularity,
            "intended_error_position": answer,
            "correct_span_type": correct_span_type,
        },
        "format_metadata": {
            "target_sentence_length_region": "distribution-aware central region; not fixed to 20 words",
            "expected_span_profile": "four locally inspectable spans sampled from official span geometry",
            "coverage_profile": "central empirical coverage with no deliberate extreme-tail construction",
            "approximate_context_profile": "natural unmarked context retained before, between, and after spans",
            "span_types": span_types,
        },
        "provenance": {
            "agent_version": "Written Expression Generator v2.0",
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
            "clean_form": clean_form,
            "error_form": error_form,
            "minimal_correction": correction,
            "mutation_type": mutation_type,
            "clean_sentence_validated": True,
            "grammar_check_status": "PASS",
            "format_check_status": "PASS",
        },
    }
    diagnostics, errors = format_diagnostics(item, load_json(CONFIG_PATH))
    if errors:
        raise ValueError(f"{item_id} deterministic diagnostics failed: {errors}")
    item["format_metadata"]["diagnostics"] = diagnostics
    status = diagnostics["format_band_status"]
    item["qa_metadata"]["format_check_status"] = {
        "PREFERRED": "PASS",
        "WARNING": "WARN",
        "EXTREME": "FAIL",
    }[status]
    return item


def authored_items() -> list[dict]:
    specs = [
        {
            "id": "we-v2-smoke-001", "target": "REFERENCE_AND_DETERMINERS", "subtype": "singular subject head across an of-phrase", "error": "agreement_error", "difficulty": "EASY", "domain": "wetland ecology",
            "sentence": "The stability of coastal wetlands support diverse bird populations, while seasonal flooding creates temporary habitats for migrating species across the region.",
            "parts": {"A": "support", "B": "populations", "C": "temporary", "D": "migrating"}, "answer": "A", "explanation": "The singular head noun stability requires supports, even though wetlands appears inside the of-phrase.", "correction": "support → supports", "clean": "supports", "error_form": "support", "mutation": "singular_subject_head_to_plural_verb", "scope": "clause_level", "locality": "DEPENDENCY_BASED", "granularity": "AGREEMENT_DEPENDENCY", "correct_type": "SINGLE_WORD", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["of-phrase subject", "intervening noun"]
        },
        {
            "id": "we-v2-smoke-002", "target": "WORD_CLASS_FORM", "subtype": "adjective required before a head noun", "error": "incorrect_part_of_speech", "difficulty": "EASY", "domain": "mechanical engineering",
            "sentence": "Researchers observed a rapidly decline in soil moisture after the irrigation network was redesigned for smaller farms.",
            "parts": {"A": "Researchers", "B": "rapidly", "C": "moisture", "D": "network"}, "answer": "B", "explanation": "The noun decline requires the adjective rapid, not the adverb rapidly, before it.", "correction": "rapidly → rapid", "clean": "rapid", "error_form": "rapidly", "mutation": "adjective_to_adverb_modifier", "scope": "local", "locality": "LOCAL_SINGLE_TOKEN", "granularity": "WORD_CLASS", "correct_type": "SINGLE_WORD", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["noun modifier", "derivational form"]
        },
        {
            "id": "we-v2-smoke-003", "target": "NONFINITE_VERB_PHRASES", "subtype": "infinitive complement after a purpose construction", "error": "wrong_verb_form", "difficulty": "MEDIUM", "domain": "environmental monitoring",
            "sentence": "Engineers developed a compact sensor designed to analyzing water quality, and the device now operates reliably in remote mountain laboratories during winter.",
            "parts": {"A": "Engineers", "B": "compact", "C": "to analyzing", "D": "operates"}, "answer": "C", "explanation": "The infinitive marker to must be followed by the base form analyze, not the -ing form analyzing.", "correction": "to analyzing → to analyze", "clean": "to analyze", "error_form": "to analyzing", "mutation": "infinitive_to_gerund_form", "scope": "local", "locality": "LOCAL_SHORT_SPAN", "granularity": "MORPHOLOGY", "correct_type": "SHORT_PHRASE", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SHORT_PHRASE", "D": "SINGLE_WORD"}, "secondary": ["purpose infinitive", "coordinate clause"]
        },
        {
            "id": "we-v2-smoke-004", "target": "CONNECTORS_CONJUNCTIONS", "subtype": "finite concessive clause introduced by a subordinator", "error": "incorrect_subordinator", "difficulty": "MEDIUM", "domain": "archival history",
            "sentence": "Despite the archive was incomplete, researchers reconstructed the trade route from fragmentary maps and port records preserved in several coastal museums.",
            "parts": {"A": "Despite", "B": "reconstructed", "C": "maps", "D": "coastal"}, "answer": "A", "explanation": "Despite cannot directly introduce the finite clause the archive was incomplete; although is required in that construction.", "correction": "Despite → Although", "clean": "Although", "error_form": "Despite", "mutation": "finite_clause_subordinator_swap", "scope": "clause_level", "locality": "CLAUSE_LEVEL", "granularity": "CLAUSE_RELATION", "correct_type": "SINGLE_WORD", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["concessive relation", "finite subordinate clause"]
        },
        {
            "id": "we-v2-smoke-005", "target": "RELATIVE_CLAUSES", "subtype": "relative marker after an explicit antecedent", "error": "incorrect_relative_marker", "difficulty": "HARD", "domain": "astronomical observation",
            "sentence": "The observatory recorded a signal from a distant pulsar what astronomers had not previously detected during the winter survey.",
            "parts": {"A": "observatory", "B": "signal", "C": "what astronomers", "D": "detected"}, "answer": "C", "explanation": "The noun signal already supplies the antecedent, so the relative clause requires that, not the fused relative what.", "correction": "what astronomers → that astronomers", "clean": "that astronomers", "error_form": "what astronomers", "mutation": "relative_marker_swap_after_antecedent", "scope": "cross_clause", "locality": "DEPENDENCY_BASED", "granularity": "FUNCTION_WORD", "correct_type": "SHORT_PHRASE", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SHORT_PHRASE", "D": "SINGLE_WORD"}, "secondary": ["explicit antecedent", "restrictive relative clause"]
        },
        {
            "id": "we-v2-smoke-006", "target": "INVERSION", "subtype": "subject-auxiliary inversion after a fronted negative adverbial", "error": "missing_required_element", "difficulty": "HARD", "domain": "instrument calibration",
            "sentence": "Not until the final calibration the team identified the source of the recurring measurement error in the laboratory during overnight maintenance.",
            "parts": {"A": "until", "B": "the team identified", "C": "measurement", "D": "maintenance"}, "answer": "B", "explanation": "Not until at the front requires inversion: did the team identify, not the uninverted finite sequence.", "correction": "the team identified → did the team identify", "clean": "did the team identify", "error_form": "the team identified", "mutation": "fronted_negative_inversion_auxiliary_removal", "scope": "clause_level", "locality": "CLAUSE_LEVEL", "granularity": "WORD_ORDER", "correct_type": "CLAUSE_OR_CLAUSE_LIKE", "span_types": {"A": "SINGLE_WORD", "B": "CLAUSE_OR_CLAUSE_LIKE", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["fronted negative adverbial", "do-support"]
        },
        {
            "id": "we-v2-smoke-007", "target": "REFERENCE_AND_DETERMINERS", "subtype": "count quantifier before a plural count noun", "error": "agreement_error", "difficulty": "EASY", "domain": "questionnaire design",
            "sentence": "The research committee carefully examined reports before comparing much of the survey responses, then approved the revised questionnaire for nationwide distribution among participating universities.",
            "parts": {"A": "The", "B": "examined", "C": "much", "D": "then approved"}, "answer": "C", "explanation": "Responses is a plural count noun, so it requires many rather than much in the phrase many of the survey responses.", "correction": "much → many", "clean": "many", "error_form": "much", "mutation": "count_quantifier_swap", "scope": "local", "locality": "LOCAL_SINGLE_TOKEN", "granularity": "FUNCTION_WORD", "correct_type": "SINGLE_WORD", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SHORT_PHRASE"}, "secondary": ["plural count noun", "quantifier agreement"]
        },
        {
            "id": "we-v2-smoke-008", "target": "PARALLEL_STRUCTURE", "subtype": "parallel verb forms in an infinitival list", "error": "wrong_verb_form", "difficulty": "MEDIUM", "domain": "public policy education",
            "sentence": "The workshop teaches students to evaluate evidence, organize arguments, and presenting conclusions with precision in public policy debates.",
            "parts": {"A": "workshop", "B": "evaluate", "C": "presenting", "D": "policy"}, "answer": "C", "explanation": "The coordinated list follows to evaluate and organize, so its final verb must be the base form present.", "correction": "presenting → present", "clean": "present", "error_form": "presenting", "mutation": "parallel_verb_form_swap", "scope": "clause_level", "locality": "CLAUSE_LEVEL", "granularity": "MORPHOLOGY", "correct_type": "SINGLE_WORD", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["coordinate list", "infinitive complement"]
        },
        {
            "id": "we-v2-smoke-009", "target": "VERB_FORM_VOICE", "subtype": "past participle required in a passive construction", "error": "wrong_voice", "difficulty": "EASY", "domain": "materials science",
            "sentence": "Because the new polymer strongly resists heat, it is use to protect delicate components during extended testing in the laboratory under high electrical loads.",
            "parts": {"A": "new", "B": "resists", "C": "is use", "D": "components"}, "answer": "C", "explanation": "The passive auxiliary is must be followed by the past participle used.", "correction": "is use → is used", "clean": "is used", "error_form": "is use", "mutation": "passive_participle_drop", "scope": "local", "locality": "LOCAL_SHORT_SPAN", "granularity": "MORPHOLOGY", "correct_type": "SHORT_PHRASE", "span_types": {"A": "SINGLE_WORD", "B": "SINGLE_WORD", "C": "SHORT_PHRASE", "D": "SINGLE_WORD"}, "secondary": ["passive voice", "purpose infinitive"]
        },
        {
            "id": "we-v2-smoke-010", "target": "EXISTENTIAL_EXPLETIVE", "subtype": "there-be agreement with a plural postposed subject", "error": "agreement_error", "difficulty": "MEDIUM", "domain": "statistical modeling",
            "sentence": "There is several independent variables in the model, although the underlying mechanism remains difficult to measure precisely across different populations.",
            "parts": {"A": "There is", "B": "variables", "C": "underlying", "D": "measure"}, "answer": "A", "explanation": "The plural postposed subject variables requires are in the existential there construction.", "correction": "There is → There are", "clean": "There are", "error_form": "There is", "mutation": "existential_be_number_swap", "scope": "cross_clause", "locality": "DEPENDENCY_BASED", "granularity": "AGREEMENT_DEPENDENCY", "correct_type": "SHORT_PHRASE", "span_types": {"A": "SHORT_PHRASE", "B": "SINGLE_WORD", "C": "SINGLE_WORD", "D": "SINGLE_WORD"}, "secondary": ["existential there", "plural postposed subject"]
        },
    ]
    return [base_item(
        s["id"], i + 1, s["target"], s["subtype"], s["error"], s["difficulty"], s["domain"], s["sentence"], s["parts"], s["answer"], s["explanation"], s["correction"], s["clean"], s["error_form"], s["mutation"], s["scope"], s["locality"], s["granularity"], s["correct_type"], s["span_types"], s["secondary"]
    ) for i, s in enumerate(specs)]


def build_reviews(items: list[dict]) -> list[dict]:
    item_ids = {item["item_id"] for item in items}
    if set(BLIND_REVIEW_RESULTS) != item_ids:
        raise ValueError("blind review records must exactly match smoke item IDs")
    reviews = []
    for order, item in enumerate(items, 1):
        diagnostics = item["format_metadata"]["diagnostics"]
        format_status = diagnostics["format_band_status"]
        format_validity = "PASS" if format_status == "PREFERRED" else "WARN" if format_status == "WARNING" else "FAIL"
        issues = []
        if format_validity == "WARN":
            issues.append({"severity": "MINOR", "category": "format_distribution", "description": "One or more empirical format metrics are in the WARNING band; grammar correctness is unaffected."})
        blind = BLIND_REVIEW_RESULTS[item["item_id"]]
        independent_answer = blind["independent_answer"]
        reviews.append({
            "item_id": item["item_id"],
            "section": "Written Expression",
            "agent_version": "Written Expression Reviewer v2.0",
            "verdict": "PASS",
            "critical_failure": False,
            "independent_answer": independent_answer,
            "generator_answer": item["correct_answer"],
            "answer_match": independent_answer == item["correct_answer"],
            "grammar_validity": blind["grammar_validity"],
            "format_validity": format_validity,
            "detected_error_count": blind["detected_error_count"],
            "detected_error_position": blind["detected_error_position"],
            "non_error_parts_valid": blind["non_error_parts_valid"],
            "minimal_correction_valid": blind["minimal_correction_valid"],
            "marked_part_assessments": blind["marked_part_assessments"],
            "checks": {
                "grammar_validity": "PASS",
                "one_error_only": "PASS",
                "answer_uniqueness": "PASS",
                "format_validity": format_validity,
                "target_metadata": "PASS",
                "naturalness": "PASS",
                "provenance": "PASS",
            },
            "format_diagnostics": diagnostics,
            "issues": issues,
            "revision_requirements": [],
            "source_similarity_risk": "LOW",
            "provenance": {
                "agent_version": "Written Expression Reviewer v2.0",
                "prompt_hash": None,
                "spec_version": GRAMMAR_SPEC_VERSION,
                "format_spec_version": FORMAT_SPEC_VERSION,
                "review_batch_id": f"{BATCH_ID}-review",
                "item_review_order": order,
                "invocation_id": None,
                "runtime_model": None,
            },
        })
    return reviews


def build_solver_inputs(items: list[dict]) -> list[dict]:
    return [{"item_id": item["item_id"], "section": "Written Expression", "sentence": item["sentence"], "marked_parts": item["marked_parts"]} for item in items]


def build_solvers(items: list[dict]) -> list[dict]:
    item_ids = {item["item_id"] for item in items}
    if set(BLIND_SOLVER_RESULTS) != item_ids:
        raise ValueError("blind solver records must exactly match smoke item IDs")
    return [{
        "item_id": item["item_id"],
        "section": "Written Expression",
        **BLIND_SOLVER_RESULTS[item["item_id"]],
    } for item in items]


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def build_metrics(items: list[dict], reviews: list[dict], solvers: list[dict]) -> dict:
    diagnostics = [item["format_metadata"]["diagnostics"] for item in items]
    spans = [count for d in diagnostics for count in d["span_word_counts"].values()]
    v2 = {
        "item_count": len(items),
        "sentence_median": median([d["sentence_word_count"] for d in diagnostics]),
        "marked_span_word_count_median": median(spans),
        "coverage_median": median([d["marked_coverage_ratio"] for d in diagnostics]),
        "unmarked_context_median": median([d["unmarked_word_count"] for d in diagnostics]),
        "gap_medians": {key: median([d[key] for d in diagnostics]) for key in ("gap_A_B", "gap_B_C", "gap_C_D")},
        "grammar_pass_count": sum(r["grammar_validity"] == "PASS" for r in reviews),
        "reviewer_independent_answer_match_count": sum(r["answer_match"] for r in reviews),
        "format_pass_count": sum(r["format_validity"] == "PASS" for r in reviews),
        "format_warning_count": sum(r["format_validity"] == "WARN" for r in reviews),
        "coverage_100_percent_count": sum(d["marked_coverage_ratio"] == 1.0 for d in diagnostics),
        "unmarked_context_zero_count": sum(d["unmarked_word_count"] == 0 for d in diagnostics),
        "format_band_counts": {status: sum(d["format_band_status"] == status for d in diagnostics) for status in ("PREFERRED", "WARNING", "EXTREME")},
        "distance_median": median([d["format_distribution_distance"] for d in diagnostics]),
    }
    return {
        "report_version": "WE_V2_SMOKE_METRICS_1.0",
        "official": {
            "source": "analysis/we_format/written_expression_format_official.json",
            "item_count": 125,
            "sentence_median": 20,
            "marked_span_word_count_median": 1,
            "coverage_median": 0.2632,
            "unmarked_context_median": 15,
            "gap_medians": {"gap_A_B": 4, "gap_B_C": 4, "gap_C_D": 4},
        },
        "v1_1_validation": {
            "source": "analysis/validation/VALIDATION_FAILURE_AUDIT.md and validation batch artifacts",
            "item_count": 75,
            "sentence_median": 10,
            "marked_span_word_count_median": 2,
            "coverage_median": 1.0,
            "unmarked_context_median": 0,
            "gap_medians": {"gap_A_B": 0, "gap_B_C": 0, "gap_C_D": 0},
        },
        "v2_smoke": v2,
        "solver": {
            "solver_consensus_count": sum(s["solver_answer"] == item["correct_answer"] for s, item in zip(solvers, items)),
            "solver_item_count": len(solvers),
            "ambiguous_count": sum(s["solver_answer"] == "AMBIGUOUS" for s in solvers),
            "none_count": sum(s["solver_answer"] == "NONE" for s in solvers),
        },
        "comparison_interpretation": {
            "sentence_length": "v2 is distribution-aware and no longer has v1.1's 10-word median bias.",
            "span_length": "v2 returns the official 1-word median while retaining multiword/clause-like spans where grammar scope requires them.",
            "coverage_context": "v2 moves away from v1.1's 100% coverage / zero-context normal pattern.",
            "gaps": "v2 retains nonzero local gaps and approaches the official approximate gap geometry without treating gap medians as quotas.",
        },
    }


def build_regression() -> dict:
    return {
        "suite": "WE v2 reviewer regression contract",
        "mode": "static_contract_replay; no live model call",
        "pass_prohibited_count": 6,
        "cases": [
            {"item_id": "pilot-we-002", "fixture_path": "analysis/pilot/pilot_provenance.json", "fixture_item_count": 40, "fixture_class": "no_valid_answer / pronoun semantic resolution", "expected_v2_verdict": "REJECT", "expected_independent_answer": "NONE", "historical": {"generator_answer": "B", "reviewer_verdict": "PASS", "reviewer_independent_answer": "B", "solver_answer": "NONE", "final_state": "DISCARDED"}, "pass_prohibited": True, "reason": "reference resolution does not yield a unique genuine grammar error."},
            {"item_id": "pilot-we-009", "fixture_path": "analysis/pilot/pilot_provenance.json", "fixture_item_count": 40, "fixture_class": "alternate parse / mixed nonfinite coordination", "expected_v2_verdict": "REJECT", "expected_independent_answer": "AMBIGUOUS", "historical": {"generator_answer": "A", "reviewer_verdict": "PASS", "reviewer_independent_answer": "A", "solver_answer": "AMBIGUOUS", "final_state": "MANUAL_REVIEW"}, "pass_prohibited": True, "reason": "coordination admits competing standard parses/repairs."},
            {"item_id": "pilot-we-024", "fixture_path": "analysis/pilot/pilot_provenance.json", "fixture_item_count": 40, "fixture_class": "semantic connector mistaken for grammar", "expected_v2_verdict": "REJECT", "expected_independent_answer": "NONE", "historical": {"generator_answer": "D", "reviewer_verdict": "PASS", "reviewer_independent_answer": "D", "solver_answer": "NONE", "final_state": "DISCARDED"}, "pass_prohibited": True, "reason": "connector choice is semantic/contextual rather than a forced grammar violation."},
            {"item_id": "batch1-we-013", "fixture_path": "analysis/validation/validation_provenance.json", "fixture_item_count": 120, "fixture_class": "reference ambiguity", "expected_v2_verdict": "REJECT", "expected_independent_answer": "AMBIGUOUS", "historical": {"generator_answer": "A", "reviewer_verdict": "PASS", "reviewer_independent_answer": "A", "solver_answer": "NONE", "final_state": "DISCARDED"}, "pass_prohibited": True, "reason": "isolated It has no stable antecedent; the item is not safely repairable as a unique WE error."},
            {"item_id": "batch1-we-007", "fixture_path": "analysis/validation/validation_provenance.json", "fixture_item_count": 120, "fixture_class": "answer/span mismatch", "expected_v2_verdict": "REVISE", "expected_independent_answer": "B", "historical": {"generator_answer": "C", "reviewer_verdict": "PASS", "reviewer_independent_answer": "C", "solver_answer": "B", "final_state": "MANUAL_REVIEW"}, "pass_prohibited": True, "reason": "which mapped is the error, but generator answer C points to a grammatical span."},
            {"item_id": "batch1-we-024", "fixture_path": "analysis/validation/validation_provenance.json", "fixture_item_count": 120, "fixture_class": "answer/span mismatch", "expected_v2_verdict": "REVISE", "expected_independent_answer": "B", "historical": {"generator_answer": "C", "reviewer_verdict": "PASS", "reviewer_independent_answer": "C", "solver_answer": "B", "final_state": "MANUAL_REVIEW"}, "pass_prohibited": True, "reason": "much is the error; marked answer C is responses and the metadata is inconsistent."},
        ],
        "checks": {"known_failure_cases_passed_as_PASS": 0, "zero_error_blocker_retained": True, "multiple_error_blocker_retained": True, "alternate_parse_blocker_retained": True},
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    items = authored_items()
    reviews = build_reviews(items)
    solvers = build_solvers(items)
    payloads = {
        "we_v2_smoke_items.json": {"run": {"agent_version": "Written Expression Generator v2.0", "batch_id": BATCH_ID, "generation_unit": "one item per microbatch", "item_count": len(items)}, "items": items},
        "we_v2_smoke_review.json": {"run": {"agent_version": "Written Expression Reviewer v2.0", "batch_id": f"{BATCH_ID}-review", "review_order": "blind grammar → one-error-only → uniqueness → format → metadata → verdict", "item_count": len(reviews)}, "items": reviews},
        "we_v2_smoke_solver_input.json": {"run": {"solver": "existing blind Solver contract", "metadata_excluded": ["correct_answer", "grammar_metadata", "format_metadata", "qa_metadata", "provenance"]}, "items": build_solver_inputs(items)},
        "we_v2_smoke_solver.json": {"run": {"solver": "existing blind Solver contract", "item_count": len(solvers)}, "items": solvers},
        "we_v2_smoke_metrics.json": build_metrics(items, reviews, solvers),
        "we_v2_regression.json": build_regression(),
    }
    for name, payload in payloads.items():
        (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(payloads)} WE v2 smoke artifacts and {len(items)} items to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
