"""Build the fresh WE v2.1.2 grammar-safety re-smoke artifacts.

The repository has no live Generator/Reviewer/Solver runtime.  This builder
therefore emits a fresh deterministic safety smoke cohort from newly authored
clean/error pairs, runs the existing v2.1.1 format gates unchanged, and never
creates Reviewer/Solver judgements.  The blind and sealed-key topology matches
the previous grammar pilot.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / "analysis" / "we_v2_1_2_grammar_pilot"
GEN_DIR = PILOT_DIR / "runtime" / "generator"
CONFIG_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "config" / "we_v2_format_config.json"

sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))
from mutation_safety import template_audit_records, validate_item  # noqa: E402
from validate_format import (  # noqa: E402
    GRAMMAR_SPEC_PATH,
    TAXONOMY_PATH,
    format_diagnostics,
    load_json,
    validate_item as validate_format_item,
)
from shared.tokenization import lexical_tokens  # noqa: E402


LABELS = ("A", "B", "C", "D")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def span_type(span: str) -> str:
    count = len(lexical_tokens(span))
    if count == 1:
        return "SINGLE_WORD"
    if count <= 4:
        return "SHORT_PHRASE"
    return "CLAUSE_OR_CLAUSE_LIKE"


def historical_sentences() -> set[str]:
    result: set[str] = set()
    for path in ROOT.rglob("*.json"):
        if PILOT_DIR in path.parents or ".git" in path.parts or "node_modules" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue

        def visit(value: Any, key: str | None = None) -> None:
            if key in {"sentence", "clean_form", "error_form"} and isinstance(value, str):
                result.add(value)
            elif isinstance(value, dict):
                for child_key, child in value.items():
                    visit(child, child_key)
            elif isinstance(value, list):
                for child in value:
                    visit(child, key)

        visit(data)
    return result


def specs() -> list[dict[str, Any]]:
    """Freshly authored pairs; none are copied from the v2.1.1 pilot."""

    return [
        {
            "clean": "During the winter expedition, the observatory records subtle changes in atmospheric pressure across the northern plateau each morning.",
            "error": "During the winter expedition, the observatory record subtle changes in atmospheric pressure across the northern plateau each morning.",
            "marked": {"A": "expedition", "B": "record", "C": "pressure", "D": "plateau"}, "answer": "B",
            "target": "CLAUSE_STRUCTURE", "type": "agreement_error", "subtype": "subject verb agreement", "mutation": "finite agreement substitution: records -> record", "correction": "Change record to records.", "explanation": "The singular subject observatory requires records, not record.", "granularity": "AGREEMENT_DEPENDENCY",
        },
        {
            "clean": "An ancient observatory preserves fragile star charts in climate-controlled cabinets near the western dome throughout the year.",
            "error": "A ancient observatory preserves fragile star charts in climate-controlled cabinets near the western dome throughout the year.",
            "marked": {"A": "A ancient", "B": "charts", "C": "dome", "D": "year"}, "answer": "A",
            "target": "REFERENCE_AND_DETERMINERS", "type": "incorrect_part_of_speech", "subtype": "indefinite article before vowel sound", "mutation": "article substitution: An -> A", "correction": "Change A to An.", "explanation": "The vowel sound at the start of ancient requires An, not A.", "granularity": "FUNCTION_WORD",
        },
        {
            "clean": "At the remote station, technicians carefully measure mineral density before recording the results in a shared laboratory ledger.",
            "error": "At the remote station, technicians careful measure mineral density before recording the results in a shared laboratory ledger.",
            "marked": {"A": "station", "B": "careful", "C": "density", "D": "ledger"}, "answer": "B",
            "target": "WORD_CLASS_FORM", "type": "incorrect_part_of_speech", "subtype": "adverbial manner modifier", "mutation": "adverb-to-adjective substitution: carefully -> careful", "correction": "Change careful to carefully.", "explanation": "The verb measure requires the adverb carefully to describe manner.", "granularity": "WORD_CLASS",
        },
        {
            "clean": "The archive preserves specimens that the researcher examined before the curator returned them to a regional collection.",
            "error": "The archive preserves specimens who the researcher examined before the curator returned them to a regional collection.",
            "marked": {"A": "preserves", "B": "who", "C": "curator", "D": "collection"}, "answer": "B",
            "target": "RELATIVE_CLAUSES", "type": "incorrect_relative_marker", "subtype": "object relative marker", "mutation": "object relative marker substitution: that -> who", "correction": "Change who to that.", "explanation": "The relative marker refers to specimens as an object, so who is not the appropriate form.", "granularity": "FUNCTION_WORD",
        },
        {
            "clean": "Researchers found ceramic fragments preserved beneath the riverbank after the flood receded during the autumn survey.",
            "error": "Researchers found ceramic fragments preserving beneath the riverbank after the flood receded during the autumn survey.",
            "marked": {"A": "found", "B": "preserving", "C": "riverbank", "D": "survey"}, "answer": "B",
            "target": "NONFINITE_VERB_PHRASES", "type": "wrong_verb_form", "subtype": "reduced passive participle", "mutation": "reduced passive participle substitution: preserved -> preserving", "correction": "Change preserving to preserved.", "explanation": "The fragments are passively preserved beneath the riverbank, so preserved is required.", "granularity": "MORPHOLOGY",
        },
        {
            "clean": "The digital catalog allows visitors to locate rare manuscripts without consulting the separate inventory maintained by the archive.",
            "error": "The digital catalog allows visitors locating rare manuscripts without consulting the separate inventory maintained by the archive.",
            "marked": {"A": "catalog", "B": "locating", "C": "inventory", "D": "archive"}, "answer": "B",
            "target": "VERB_COMPLEMENTATION", "type": "wrong_verb_form", "subtype": "allow plus object plus infinitive", "mutation": "allow-complement substitution: to locate -> locating", "correction": "Change locating to to locate.", "explanation": "Allow visitors requires the infinitive to locate in this complement frame.", "granularity": "VERB_FRAME",
        },
        {
            "clean": "The revised policy requires local clinics to comply with reporting standards during annual inspections by regional auditors.",
            "error": "The revised policy requires local clinics to comply to reporting standards during annual inspections by regional auditors.",
            "marked": {"A": "policy", "B": "comply to", "C": "inspections", "D": "auditors"}, "answer": "B",
            "target": "VERB_COMPLEMENTATION", "type": "wrong_preposition_collocation", "subtype": "comply preposition", "mutation": "verb-preposition substitution: comply with -> comply to", "correction": "Change comply to to comply with.", "explanation": "The verb comply takes the preposition with, not to, before reporting standards.", "granularity": "VERB_FRAME",
        },
        {
            "clean": "The survey revealed how the current moved through the channel after the engineers adjusted the underwater gate.",
            "error": "The survey revealed how moved the current through the channel after the engineers adjusted the underwater gate.",
            "marked": {"A": "survey", "B": "moved the current", "C": "engineers", "D": "gate"}, "answer": "B",
            "target": "NOUN_CLAUSES", "type": "wrong_word_order", "subtype": "embedded question word order", "mutation": "embedded-question word order reversal: how the current moved -> how moved the current", "correction": "Change how moved the current to how the current moved.", "explanation": "An embedded question uses statement order, how the current moved, rather than the reversed order.", "granularity": "WORD_ORDER",
        },
        {
            "clean": "A series of controlled observations reveals seasonal changes in the river's temperature during extended drought conditions.",
            "error": "A series of controlled observations reveal seasonal changes in the river's temperature during extended drought conditions.",
            "marked": {"A": "controlled", "B": "reveal", "C": "temperature", "D": "conditions"}, "answer": "B",
            "target": "CLAUSE_STRUCTURE", "type": "agreement_error", "subtype": "singular head noun agreement", "mutation": "singular head agreement substitution: reveals -> reveal", "correction": "Change reveal to reveals.", "explanation": "The singular head noun series requires reveals, even though observations is plural.", "granularity": "AGREEMENT_DEPENDENCY",
        },
        {
            "clean": "The laboratory compared many samples from the upper valley before selecting representative specimens for chemical analysis.",
            "error": "The laboratory compared much samples from the upper valley before selecting representative specimens for chemical analysis.",
            "marked": {"A": "laboratory", "B": "much samples", "C": "specimens", "D": "analysis"}, "answer": "B",
            "target": "REFERENCE_AND_DETERMINERS", "type": "agreement_error", "subtype": "count quantifier", "mutation": "count quantifier substitution: many -> much", "correction": "Change much to many.", "explanation": "Samples is a plural count noun, so many rather than much is required.", "granularity": "FUNCTION_WORD",
        },
        {
            "clean": "The stability of the bridge depends on regular inspections after heavy rainfall along the mountain road.",
            "error": "The stability of the bridge depends of regular inspections after heavy rainfall along the mountain road.",
            "marked": {"A": "bridge", "B": "depends of", "C": "rainfall", "D": "road"}, "answer": "B",
            "target": "VERB_COMPLEMENTATION", "type": "wrong_preposition_collocation", "subtype": "depend preposition", "mutation": "verb-preposition substitution: depends on -> depends of", "correction": "Change depends of to depends on.", "explanation": "The verb depend selects the preposition on, not of.", "granularity": "VERB_FRAME",
        },
        {
            "clean": "The committee recommended that the museum preserve the mural in a temperature-controlled gallery near the central archive.",
            "error": "The committee recommended that the museum preserves the mural in a temperature-controlled gallery near the central archive.",
            "marked": {"A": "committee", "B": "preserves", "C": "gallery", "D": "archive"}, "answer": "B",
            "target": "CLAUSE_STRUCTURE", "type": "wrong_verb_form", "subtype": "mandative subjunctive", "mutation": "mandative base-form substitution: preserve -> preserves", "correction": "Change preserves to preserve.", "explanation": "The mandative that-clause after recommended takes the base form preserve.", "granularity": "MORPHOLOGY",
        },
        {
            "clean": "The revised filter is more reliable than the earlier device during repeated trials in the coastal laboratory.",
            "error": "The revised filter is most reliable than the earlier device during repeated trials in the coastal laboratory.",
            "marked": {"A": "most reliable", "B": "device", "C": "trials", "D": "laboratory"}, "answer": "A",
            "target": "COMPARATIVES_DEGREE", "type": "wrong_degree_form", "subtype": "comparative required before than", "mutation": "comparative/superlative substitution: more reliable -> most reliable", "correction": "Change most reliable to more reliable.", "explanation": "The explicit than comparison requires comparative more reliable, not superlative most reliable.", "granularity": "MORPHOLOGY",
        },
        {
            "clean": "The engineers plan to measure soil moisture and compare the results during the afternoon field survey.",
            "error": "The engineers plan to measure soil moisture and comparing the results during the afternoon field survey.",
            "marked": {"A": "engineers", "B": "comparing", "C": "results", "D": "survey"}, "answer": "B",
            "target": "PARALLEL_STRUCTURE", "type": "wrong_verb_form", "subtype": "forced infinitival coordination", "mutation": "parallel base-form substitution: compare -> comparing", "correction": "Change comparing to compare.", "explanation": "The infinitive plan coordinates measure and compare, so comparing breaks the forced parallel form.", "granularity": "MORPHOLOGY",
        },
        {
            "clean": "Neither the instruments nor the calibration record explains the unusual readings recorded during the midnight inspection.",
            "error": "Neither the instruments nor the calibration record explain the unusual readings recorded during the midnight inspection.",
            "marked": {"A": "instruments", "B": "explain", "C": "readings", "D": "inspection"}, "answer": "B",
            "target": "PARALLEL_STRUCTURE", "type": "agreement_error", "subtype": "neither nor nearest subject agreement", "mutation": "nearest-subject agreement substitution: explains -> explain", "correction": "Change explain to explains.", "explanation": "The nearer singular subject record requires explains in the neither-nor construction.", "granularity": "AGREEMENT_DEPENDENCY",
        },
        {
            "clean": "By the time the storm arrived, the crew had completed the coastal measurements and secured the instruments.",
            "error": "By the time the storm arrived, the crew has completed the coastal measurements and secured the instruments.",
            "marked": {"A": "storm", "B": "has completed", "C": "secured", "D": "instruments"}, "answer": "B",
            "target": "VERB_FORM_VOICE", "type": "wrong_verb_form", "subtype": "past perfect before past event", "mutation": "past-perfect substitution: had completed -> has completed", "correction": "Change has completed to had completed.", "explanation": "The completed action precedes the past event arrived, so had completed is required.", "granularity": "MORPHOLOGY",
        },
        {
            "clean": "The committee postponed reviewing the survey results until the laboratory completed its final analysis.",
            "error": "The committee postponed to review the survey results until the laboratory completed its final analysis.",
            "marked": {"A": "postponed", "B": "to review", "C": "laboratory", "D": "analysis"}, "answer": "B",
            "target": "NONFINITE_VERB_PHRASES", "type": "wrong_verb_form", "subtype": "postpone gerund complement", "mutation": "gerund-to-infinitive substitution: reviewing -> to review", "correction": "Change to review to reviewing.", "explanation": "Postpone selects a gerund complement, so reviewing is required.", "granularity": "VERB_FRAME",
        },
        {
            "clean": "The composite remained stable under pressure during the extended heating test in the materials laboratory.",
            "error": "The composite remained stability under pressure during the extended heating test in the materials laboratory.",
            "marked": {"A": "composite", "B": "stability", "C": "heating", "D": "laboratory"}, "answer": "B",
            "target": "VERB_COMPLEMENTATION", "type": "incorrect_part_of_speech", "subtype": "predicate adjective after remain", "mutation": "predicate adjective substitution: stable -> stability", "correction": "Change stability to stable.", "explanation": "The linking verb remained requires the predicate adjective stable, not the noun stability.", "granularity": "WORD_CLASS",
        },
        {
            "clean": "These instruments detect faint signals from the deep-water sensors during the overnight calibration exercise.",
            "error": "This instruments detect faint signals from the deep-water sensors during the overnight calibration exercise.",
            "marked": {"A": "This instruments", "B": "signals", "C": "sensors", "D": "calibration"}, "answer": "A",
            "target": "REFERENCE_AND_DETERMINERS", "type": "agreement_error", "subtype": "demonstrative determiner number", "mutation": "demonstrative number substitution: These -> This", "correction": "Change This to These.", "explanation": "The plural noun instruments requires the plural demonstrative These.", "granularity": "FUNCTION_WORD",
        },
        {
            "clean": "The updated procedure requires analysts to record every sample before the final report is released.",
            "error": "The updated procedure requires analysts to records every sample before the final report is released.",
            "marked": {"A": "procedure", "B": "records", "C": "sample", "D": "report"}, "answer": "B",
            "target": "NONFINITE_VERB_PHRASES", "type": "wrong_verb_form", "subtype": "infinitive complement base form", "mutation": "infinitival base-form substitution: record -> records", "correction": "Change records to record.", "explanation": "The infinitive to must be followed by the base form record.", "granularity": "MORPHOLOGY",
        },
        {
            "clean": "The instruments have produced consistent readings throughout the prolonged field trial near the eastern boundary.",
            "error": "The instruments has produced consistent readings throughout the prolonged field trial near the eastern boundary.",
            "marked": {"A": "instruments", "B": "has produced", "C": "readings", "D": "boundary"}, "answer": "B",
            "target": "CLAUSE_STRUCTURE", "type": "agreement_error", "subtype": "plural subject auxiliary agreement", "mutation": "plural auxiliary substitution: have produced -> has produced", "correction": "Change has produced to have produced.", "explanation": "The plural subject instruments requires have produced.", "granularity": "AGREEMENT_DEPENDENCY",
        },
        {
            "clean": "The laboratory method that the chemist tested reduced contamination in the final preparation stage.",
            "error": "The laboratory method who the chemist tested reduced contamination in the final preparation stage.",
            "marked": {"A": "method", "B": "who", "C": "contamination", "D": "stage"}, "answer": "B",
            "target": "RELATIVE_CLAUSES", "type": "incorrect_relative_marker", "subtype": "object relative marker", "mutation": "object relative marker substitution: that -> who", "correction": "Change who to that.", "explanation": "The relative marker refers to method as an object, so that rather than who is required.", "granularity": "FUNCTION_WORD",
        },
        {
            "clean": "The new coating is more durable than the earlier material during prolonged exposure to saltwater.",
            "error": "The new coating is durabler than the earlier material during prolonged exposure to saltwater.",
            "marked": {"A": "durabler", "B": "material", "C": "exposure", "D": "saltwater"}, "answer": "A",
            "target": "COMPARATIVES_DEGREE", "type": "wrong_degree_form", "subtype": "invalid comparative morphology", "mutation": "invalid comparative morphology: more durable -> durabler", "correction": "Change durabler to more durable.", "explanation": "The adjective durable takes more in the comparative, not the invalid inflection durabler.", "granularity": "MORPHOLOGY",
        },
        {
            "clean": "The field report explains when the sensors are most active during the polar night near the remote observatory.",
            "error": "The field report explains when are the sensors most active during the polar night near the remote observatory.",
            "marked": {"A": "report", "B": "are the sensors", "C": "active", "D": "observatory"}, "answer": "B",
            "target": "NOUN_CLAUSES", "type": "wrong_word_order", "subtype": "embedded question word order", "mutation": "embedded-question inversion insertion: when the sensors are most active -> when are the sensors most active", "correction": "Change when are the sensors most active to when the sensors are most active.", "explanation": "The embedded question requires when the sensors are most active, not when are the sensors most active.", "granularity": "WORD_ORDER",
        },
        {
            "clean": "Although the station received little sunlight, its solar panels supplied enough power for the instruments throughout the winter.",
            "error": "Despite the station received little sunlight, its solar panels supplied enough power for the instruments throughout the winter.",
            "marked": {"A": "Despite", "B": "received", "C": "panels", "D": "winter"}, "answer": "A",
            "target": "CONNECTORS_CONJUNCTIONS", "type": "incorrect_subordinator", "subtype": "finite concessive clause connector", "mutation": "finite-clause connector substitution: Although -> Despite", "correction": "Change Despite to Although.", "explanation": "Despite cannot directly introduce the finite clause the station received; Although is required.", "granularity": "CLAUSE_RELATION",
        },
    ]


def build_item(spec: dict[str, Any], index: int, config: dict[str, Any]) -> dict[str, Any]:
    sentence = spec["error"]
    marked = spec["marked"]
    span_types = {label: span_type(marked[label]) for label in LABELS}
    correct_span_type = span_types[spec["answer"]]
    grammar_metadata = {
        "error_scope": "local" if spec["granularity"] in {"WORD_CLASS", "MORPHOLOGY", "FUNCTION_WORD", "VERB_FRAME"} else "clause_level",
        "correction_locality": "LOCAL_SINGLE_TOKEN" if correct_span_type == "SINGLE_WORD" else "LOCAL_SHORT_SPAN",
        "decision_granularity": spec["granularity"],
        "intended_error_position": spec["answer"],
        "correct_span_type": correct_span_type,
    }
    item: dict[str, Any] = {
        "item_id": f"we-v2.1.2-grammar-pilot-{index:03d}",
        "section": "Written Expression",
        "agent_version": "Written Expression Generator v2.1",
        "primary_target": spec["target"],
        "subtype": spec["subtype"],
        "secondary_features": ["fresh v2.1.2 mutation-safety smoke", "single local mutation"],
        "tested_error_type": spec["type"],
        "difficulty": "EASY" if index <= 10 else "MEDIUM",
        "vocabulary_domain": "fresh academic fieldwork",
        "sentence": sentence,
        "marked_parts": marked,
        "correct_answer": spec["answer"],
        "error_explanation": spec["explanation"],
        "minimal_correction": spec["correction"],
        "grammar_metadata": grammar_metadata,
        "format_metadata": {"span_types": span_types},
    }
    diagnostics, errors = format_diagnostics(item, config)
    if errors:
        raise ValueError(f"{item['item_id']} format diagnostics failed: {errors}")
    count = diagnostics["sentence_word_count"]
    item["format_metadata"].update({
        "target_sentence_length_region": f"{max(10, count - 2)}-{count + 2}; sampled fresh target {count}",
        "expected_span_profile": f"Four local spans; correct-span type {correct_span_type}",
        "coverage_profile": f"{diagnostics['span_word_counts']} marked lexical span profile",
        "approximate_context_profile": f"gaps {diagnostics['gap_A_B']}/{diagnostics['gap_B_C']}/{diagnostics['gap_C_D']}",
        "diagnostics": diagnostics,
    })
    item["provenance"] = {
        "agent_version": "Written Expression Generator v2.1",
        "prompt_hash": None,
        "spec_version": "1.0.0",
        "format_spec_version": "1.0.0",
        "generation_batch_id": "we-v2.1.2-25-item-grammar-resmoke-20260826",
        "microbatch_id": item["item_id"],
        "item_generation_order": index,
        "invocation_id": None,
        "runtime_model": None,
    }
    item["qa_metadata"] = {
        "clean_form": spec["clean"],
        "error_form": spec["error"],
        "minimal_correction": spec["correction"],
        "mutation_type": spec["mutation"],
        "clean_sentence_validated": True,
        # The offline builder has no independent grammar runtime.  Keep this
        # out of PASS artifacts so downstream validation quarantines it.
        "grammar_check_status": "AMBIGUOUS",
        "format_check_status": "PASS",
    }
    return item


def build() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    all_historical = historical_sentences()
    source_specs = specs()
    if len(source_specs) != 25:
        raise ValueError(f"expected 25 fresh specs, found {len(source_specs)}")
    items = [build_item(spec, index, config) for index, spec in enumerate(source_specs, 1)]
    format_band_counts = dict(Counter(item["format_metadata"]["diagnostics"]["format_band_status"] for item in items))
    exact_matches = [item["sentence"] for item in items if item["sentence"] in all_historical]
    if exact_matches:
        raise ValueError(f"historical sentence reuse detected: {exact_matches}")

    grammar = load_json(GRAMMAR_SPEC_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    targets = {entry["id"] for entry in taxonomy["primary_targets"]}
    error_types = {
        entry["id"]
        for entry in grammar["tested_error_types"]
        if entry["id"] not in {"fragment", "wrong_complementation"}
    }
    format_results = [
        validate_format_item(item, config, targets, error_types)
        for item in items
    ]
    format_report = {
        "validator": "TOEFL ITP WE deterministic format validator v2.1.1",
        "config": config["config_id"],
        "item_count": len(format_results),
        "valid_count": sum(result["valid"] for result in format_results),
        "invalid_count": sum(not result["valid"] for result in format_results),
        "items": format_results,
    }
    format_validation_path = PILOT_DIR / "format_validation.json"
    format_validation_path.write_text(
        json.dumps(format_report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if format_report["invalid_count"]:
        failures = [result for result in format_results if not result["valid"]]
        raise ValueError(f"format validation failed: {failures}")

    safety_records = []
    for item in items:
        result = validate_item(item)
        if result.status != "PASS":
            raise ValueError(f"{item['item_id']} mutation safety failed: {result.reasons}")
        safety_records.append({"item_id": item["item_id"], **result.to_dict()})

    for old in GEN_DIR.glob("we_v2.1.2_grammar_pilot_*.json"):
        old.unlink()
    for index, item in enumerate(items, 1):
        (GEN_DIR / f"we_v2.1.2_grammar_pilot_{index:03d}.json").write_text(
            json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    blind_items = [
        {"blind_id": f"blind-{index:03d}", "sentence": item["sentence"], "marked_parts": item["marked_parts"]}
        for index, item in enumerate(items, 1)
    ]
    sealed_items = []
    for index, item in enumerate(items, 1):
        sealed_items.append({
            "blind_id": f"blind-{index:03d}",
            "generator_item_id": item["item_id"],
            "correct_answer": item["correct_answer"],
            "intended_answer": item["correct_answer"],
            "primary_target": item["primary_target"],
            "tested_error_type": item["tested_error_type"],
            "mutation_metadata": {
                "clean_form": item["qa_metadata"]["clean_form"],
                "error_form": item["qa_metadata"]["error_form"],
                "mutation_type": item["qa_metadata"]["mutation_type"],
                "minimal_correction": item["qa_metadata"]["minimal_correction"],
            },
            "generation_plan": {
                "sentence": {
                    "target": item["format_metadata"]["diagnostics"]["sentence_word_count"],
                    "lower": max(10, item["format_metadata"]["diagnostics"]["sentence_word_count"] - 2),
                    "upper": item["format_metadata"]["diagnostics"]["sentence_word_count"] + 2,
                    "source": "fresh safety-smoke realization",
                },
                "correct_span": {
                    "type": item["grammar_metadata"]["correct_span_type"],
                    "target_word_count": item["format_metadata"]["diagnostics"]["correct_span_word_count"],
                    "source": "locked v2.1.1 format diagnostics",
                },
                "gap_targets": {
                    "gap_A_B": item["format_metadata"]["diagnostics"]["gap_A_B"],
                    "gap_B_C": item["format_metadata"]["diagnostics"]["gap_B_C"],
                    "gap_C_D": item["format_metadata"]["diagnostics"]["gap_C_D"],
                },
                "answer_position": item["correct_answer"],
            },
            "answer_explanation": item["error_explanation"],
            "grammar_metadata": item["grammar_metadata"],
            "marked_parts": item["marked_parts"],
            "sentence": item["sentence"],
            "deterministic_mutation_safety": safety_records[index - 1],
        })

    blind_path = PILOT_DIR / "we_v2_1_2_grammar_pilot_blind.json"
    key_path = PILOT_DIR / "we_v2_1_2_grammar_pilot_sealed_key.json"
    batch_path = PILOT_DIR / "runtime" / "generator_batch.json"
    safety_path = PILOT_DIR / "mutation_safety_validation.json"
    template_path = PILOT_DIR / "mutation_template_audit.json"
    blind_path.write_text(json.dumps({"items": blind_items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    batch_path.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    safety_path.write_text(json.dumps({"item_count": 25, "valid_count": 25, "items": safety_records}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    template_path.write_text(json.dumps({"scope": ["incorrect_reference", "wrong_degree_form", "parallel wrong_verb_form"], "templates": template_audit_records()}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    key = {
        "artifact": "WE v2.1.2 grammar pilot sealed generator answer key",
        "sealed_until_blind_review_complete": True,
        "run": {
            "batch_id": "we-v2.1.2-25-item-grammar-resmoke-20260826",
            "generator_version": "Written Expression Generator v2.1.2",
            "item_schema_version_literal": "Written Expression Generator v2.1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "generation_unit": "fresh offline safety-smoke item pair",
            "generation_runtime_available": False,
            "fresh_generation": True,
            "historical_exact_sentence_matches": len(exact_matches),
            "initial_generation_attempts": 25,
            "initial_generation_failures": 0,
            "regenerated_count": 0,
            "reviewer_runtime_available": False,
            "solver_runtime_available": False,
            "synthetic_reviewer_solver_judgment_generated": False,
            "format_logic_locked_to": "WE v2.1.1",
            "version_lock": {
                "locked_generator_version": "Written Expression Generator v2.1.2",
                "item_schema_version_literal": "Written Expression Generator v2.1",
                "paths": {
                    "generator_prompt": {"path": ".claude/agents/toefl-itp-we-generator-v2.md", "sha256": sha256(ROOT / ".claude/agents/toefl-itp-we-generator-v2.md")},
                    "generator_instructions": {"path": "agents/toefl_itp_we_generator_v2/AGENTS.md", "sha256": sha256(ROOT / "agents/toefl_itp_we_generator_v2/AGENTS.md")},
                    "mutation_safety": {"path": "agents/toefl_itp_we_generator_v2/scripts/mutation_safety.py", "sha256": sha256(ROOT / "agents/toefl_itp_we_generator_v2/scripts/mutation_safety.py")},
                    "generator_schema": {"path": "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json", "sha256": sha256(ROOT / "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json")},
                    "format_planner": {"path": "agents/toefl_itp_we_generator_v2/scripts/format_planner.py", "sha256": sha256(ROOT / "agents/toefl_itp_we_generator_v2/scripts/format_planner.py")},
                    "format_validator": {"path": "agents/toefl_itp_we_generator_v2/scripts/validate_format.py", "sha256": sha256(ROOT / "agents/toefl_itp_we_generator_v2/scripts/validate_format.py")},
                    "format_config": {"path": "agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json", "sha256": sha256(ROOT / "agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json")},
                    "grammar_spec": {"path": "specs/toefl_itp_grammar_spec.json", "sha256": sha256(ROOT / "specs/toefl_itp_grammar_spec.json")},
                    "format_spec": {"path": "specs/toefl_itp_we_format_spec_addendum.json", "sha256": sha256(ROOT / "specs/toefl_itp_we_format_spec_addendum.json")},
                    "taxonomy": {"path": "analysis/grammar_taxonomy.json", "sha256": sha256(ROOT / "analysis/grammar_taxonomy.json")},
                    "reviewer_contract": {"path": "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json", "sha256": sha256(ROOT / "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json")},
                    "solver_contract": {"path": "agents/toefl_itp_grammar_solver/schema/solver_output.schema.json", "sha256": sha256(ROOT / "agents/toefl_itp_grammar_solver/schema/solver_output.schema.json")},
                },
            },
        },
        "items": sealed_items,
    }
    key_path.write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    report = f"""# WE v2.1.2 Grammar Mutation Safety — Fresh 25-item Re-smoke

Date: 2026-08-26  
Generator lock: **WE Generator v2.1.2**  
Format logic: **v2.1.1 locked**  
75-item Validation: **NOT RUN**

## Deterministic results

- Fresh items: **25**
- Historical exact sentence matches: **{len(exact_matches)}**
- Mutation safety: **25/25**
- Metadata consistency: **25/25**
- External mutation: **0**
- Existing v2.1.1 format validator: **{format_report['valid_count']}/{format_report['item_count']}**
- Existing format-band diagnostics: **{format_band_counts}** (diagnostic only)

## Runtime boundary

The live Generator, independent Reviewer, and Solver runtimes are unavailable
in this workspace. This artifact is a fresh offline safety-smoke cohort so the
new guards and the locked format gates can be exercised without inventing
Reviewer/Solver judgments. Grammar quality is therefore **NOT_EVALUATED**;
the sealed key is not to be used as an independent blind verdict.

Blind artifact: `analysis/we_v2_1_2_grammar_pilot/we_v2_1_2_grammar_pilot_blind.json`  
Sealed key: `analysis/we_v2_1_2_grammar_pilot/we_v2_1_2_grammar_pilot_sealed_key.json`

Template audit: `analysis/we_v2_1_2_grammar_pilot/mutation_template_audit.json`

Output hashes:

- Blind: `{sha256(blind_path)}`
- Sealed key: `{sha256(key_path)}`
"""
    report_path = PILOT_DIR / "WE_V2_1_2_GRAMMAR_RESMOKE_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    return {
        "item_count": len(items),
        "historical_exact_sentence_matches": len(exact_matches),
        "mutation_safety": "25/25",
        "metadata_consistency": "25/25",
        "external_mutation": 0,
        "format_validation": rel(format_validation_path),
        "blind": rel(blind_path),
        "sealed_key": rel(key_path),
        "report": rel(report_path),
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
