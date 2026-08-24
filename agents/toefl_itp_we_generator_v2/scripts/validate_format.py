#!/usr/bin/env python3
"""Deterministic geometry and contract validator for TOEFL ITP WE v2.

This tool deliberately does not pretend to decide whether an English sentence
has a genuine grammatical error. That is the independent Reviewer phase. It
does mechanically validate tokenization, span alignment, non-overlap, four
spans, coverage, context, gaps, and empirical format diagnostics.

Usage:
    python validate_format.py path/to/items.json
    python validate_format.py path/to/items.json --report path/to/report.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "config" / "we_v2_format_config.json"
GRAMMAR_SPEC_PATH = ROOT / "specs" / "toefl_itp_grammar_spec.json"
TAXONOMY_PATH = ROOT / "analysis" / "grammar_taxonomy.json"
TOKEN_RE = re.compile(r"[\w]+(?:['-][\w]+)*", re.UNICODE)
LABELS = ("A", "B", "C", "D")
SPAN_TYPES = {"SINGLE_WORD", "SHORT_PHRASE", "CLAUSE_OR_CLAUSE_LIKE"}
ERROR_SCOPES = {"local", "clause_level", "sentence_level", "cross_clause"}
CORRECTION_LOCALITIES = {"DEPENDENCY_BASED", "LOCAL_SHORT_SPAN", "SEMANTIC_OR_CONTEXT_DEPENDENT", "LOCAL_SINGLE_TOKEN", "CLAUSE_LEVEL"}
DECISION_GRANULARITIES = {"FUNCTION_WORD", "WORD_ORDER", "CLAUSE_RELATION", "VERB_FRAME", "OTHER", "MORPHOLOGY", "WORD_CLASS", "AGREEMENT_DEPENDENCY", "LOCAL_PHRASE"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_items(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("top-level JSON must be an item array or an object with items")


def tokens(text: str) -> list[dict[str, Any]]:
    return [
        {"text": m.group(0), "start": m.start(), "end": m.end(), "index": i}
        for i, m in enumerate(TOKEN_RE.finditer(text))
    ]


def span_token_indices(sentence: str, span: str) -> tuple[list[int], list[str]]:
    first = sentence.find(span)
    if first < 0:
        return [], ["span is not an exact substring of sentence"]
    if sentence.find(span, first + 1) >= 0:
        return [], ["span occurs more than once; alignment is not unique"]

    sentence_tokens = tokens(sentence)
    start_char = first
    end_char = first + len(span)
    selected = [
        t for t in sentence_tokens
        if t["start"] >= start_char and t["end"] <= end_char
    ]
    errors: list[str] = []
    if not selected:
        errors.append("span contains no lexical token")
        return [], errors
    if selected[0]["start"] != start_char or selected[-1]["end"] != end_char:
        errors.append("span cuts through a lexical token or has unaligned boundary")
    expected = list(range(selected[0]["index"], selected[-1]["index"] + 1))
    actual = [t["index"] for t in selected]
    if actual != expected:
        errors.append("span token indices are not contiguous")
    return actual, errors


def nearest_rank_percentile(value: float, sample: list[float]) -> float:
    if not sample:
        return 0.0
    # Empirical CDF percentile, with a deterministic mid-rank for ties.
    lower = sum(x < value for x in sample)
    equal = sum(x == value for x in sample)
    return (lower + 0.5 * equal) / len(sample)


def band(value: float, threshold: dict[str, float]) -> str:
    if value < threshold["q05"] or value > threshold["q95"]:
        return "EXTREME"
    if value < threshold["q10"] or value > threshold["q90"]:
        return "WARNING"
    return "PREFERRED"


def worst_band(bands: list[str]) -> str:
    rank = {"PREFERRED": 0, "WARNING": 1, "EXTREME": 2}
    return max(bands, key=lambda item: rank[item]) if bands else "EXTREME"


def official_item_samples() -> dict[str, list[float]]:
    official_path = ROOT / "analysis" / "we_format" / "written_expression_format_official.json"
    data = load_json(official_path)
    items = data["items"]
    return {
        "sentence_word_count": [x["sentence_word_count"] for x in items],
        "marked_coverage_ratio": [x["marked_coverage_ratio"] for x in items],
        "unmarked_word_count": [x["unmarked_word_count"] for x in items],
        "mean_span_length": [x["mean_marked_span_length"] for x in items],
        "max_span_length": [x["max_marked_span_length"] for x in items],
    }


def format_diagnostics(item: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    sentence = item.get("sentence", "")
    sentence_tokens = tokens(sentence)
    parts = item.get("marked_parts")
    if not isinstance(parts, dict) or set(parts) != set(LABELS):
        return {}, ["marked_parts must have exactly A/B/C/D"]

    indices: dict[str, list[int]] = {}
    span_errors: dict[str, list[str]] = {}
    for label in LABELS:
        idx, idx_errors = span_token_indices(sentence, parts[label])
        indices[label] = idx
        span_errors[label] = idx_errors
        errors.extend(f"{label}: {message}" for message in idx_errors)

    starts = [indices[label][0] for label in LABELS if indices[label]]
    ends = [indices[label][-1] for label in LABELS if indices[label]]
    if len(starts) == 4 and starts != sorted(starts):
        errors.append("marked spans are not in sentence order A-B-C-D")
    for before, after in zip(LABELS, LABELS[1:]):
        if indices[before] and indices[after] and indices[before][-1] >= indices[after][0]:
            errors.append(f"span overlap or reversed order: {before}/{after}")

    counts = {label: len(indices[label]) for label in LABELS}
    if any(count < 1 for count in counts.values()):
        errors.append("all four spans must contain at least one lexical token")
    marked_count = sum(counts.values())
    sentence_count = len(sentence_tokens)
    coverage = (marked_count / sentence_count) if sentence_count else 1.0
    unmarked = sentence_count - marked_count
    gaps = {
        "gap_A_B": indices["B"][0] - indices["A"][-1] - 1 if indices["A"] and indices["B"] else -1,
        "gap_B_C": indices["C"][0] - indices["B"][-1] - 1 if indices["B"] and indices["C"] else -1,
        "gap_C_D": indices["D"][0] - indices["C"][-1] - 1 if indices["C"] and indices["D"] else -1,
    }
    if any(value < 0 for value in gaps.values()):
        errors.append("gap cannot be computed because a span is not aligned")

    mean_length = marked_count / 4 if marked_count else 0.0
    max_length = max(counts.values()) if counts else 0
    grammar = item.get("grammar_metadata", {})
    correct = item.get("correct_answer")
    correct_count = counts.get(correct, 0)
    declared_types = item.get("format_metadata", {}).get("span_types", {})
    for label in LABELS:
        declared = declared_types.get(label)
        count = counts[label]
        if declared not in SPAN_TYPES:
            errors.append(f"span_types.{label} is missing or invalid")
        elif declared == "SINGLE_WORD" and count != 1:
            errors.append(f"span_types.{label}=SINGLE_WORD but word count is {count}")
        elif declared == "SHORT_PHRASE" and not 2 <= count <= 4:
            errors.append(f"span_types.{label}=SHORT_PHRASE but word count is {count}")
        elif declared == "CLAUSE_OR_CLAUSE_LIKE" and count < 2:
            errors.append(f"span_types.{label}=CLAUSE_OR_CLAUSE_LIKE needs at least 2 tokens")

    if correct in LABELS:
        declared_correct_type = declared_types.get(correct)
        grammar_correct_type = grammar.get("correct_span_type")
        if declared_correct_type in SPAN_TYPES and grammar_correct_type != declared_correct_type:
            errors.append(
                "grammar_metadata.correct_span_type must match "
                f"format_metadata.span_types.{correct}"
            )

    samples = official_item_samples()
    metric_values = {
        "sentence_word_count": sentence_count,
        "marked_coverage_ratio": coverage,
        "unmarked_word_count": unmarked,
        "mean_span_length": mean_length,
        "max_span_length": max_length,
    }
    thresholds = config["item_level_thresholds"]
    profile: dict[str, float] = {}
    metric_bands: dict[str, str] = {}
    for name, value in metric_values.items():
        profile[name] = nearest_rank_percentile(value, samples[name])
        metric_bands[name] = band(value, thresholds[name])
    for name, value in gaps.items():
        profile[name] = nearest_rank_percentile(value, [x[name] for x in load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")["items"]])
        metric_bands[name] = band(value, thresholds[name])

    distance_terms: list[float] = []
    for name in config["distance"]["metrics"]:
        stats = config["distance"]["official_item_level_statistics"][name]
        if stats["stdev"] == 0:
            continue
        distance_terms.append(((metric_values[name] - stats["mean"]) / stats["stdev"]) ** 2)
    distance = math.sqrt(sum(distance_terms) / len(distance_terms)) if distance_terms else 0.0
    status = worst_band(list(metric_bands.values()))
    if coverage >= 1.0:
        errors.append("100% marked coverage is prohibited as the normal v2 pattern")
    if unmarked == 0:
        errors.append("zero unmarked context is prohibited as the normal v2 pattern")
    if correct_count < 1:
        errors.append("correct_answer does not point to an aligned span")

    diagnostics = {
        "sentence_word_count": sentence_count,
        "span_word_counts": counts,
        "mean_span_length": round(mean_length, 4),
        "max_span_length": max_length,
        "marked_coverage_ratio": round(coverage, 4),
        "unmarked_word_count": unmarked,
        **gaps,
        "correct_span_word_count": correct_count,
        "correct_span_type": grammar.get("correct_span_type"),
        "correction_locality": grammar.get("correction_locality"),
        "decision_granularity": grammar.get("decision_granularity"),
        "format_distribution_distance": round(distance, 4),
        "format_percentile_profile": {key: round(value, 4) for key, value in profile.items()},
        "format_band_status": status,
        "metric_band_status": metric_bands,
        "span_token_indices": indices,
    }
    return diagnostics, errors


def validate_item(item: dict[str, Any], config: dict[str, Any], targets: set[str], error_types: set[str]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(item, dict):
        return {"item_id": "?", "valid": False, "errors": ["item must be an object"]}
    item_id = item.get("item_id", "?")
    required = {
        "item_id", "section", "agent_version", "primary_target", "subtype", "secondary_features",
        "tested_error_type", "difficulty", "vocabulary_domain", "sentence", "marked_parts",
        "correct_answer", "error_explanation", "minimal_correction", "grammar_metadata",
        "format_metadata", "provenance", "qa_metadata",
    }
    missing = sorted(required - set(item))
    errors.extend(f"missing required field: {name}" for name in missing)
    if item.get("section") != "Written Expression":
        errors.append("section must be Written Expression")
    if item.get("agent_version") != "Written Expression Generator v2.0":
        errors.append("agent_version must be Written Expression Generator v2.0")
    if item.get("primary_target") not in targets:
        errors.append("primary_target is not in the grammar taxonomy")
    if item.get("tested_error_type") not in error_types:
        errors.append("tested_error_type is not in the grammar taxonomy")
    if item.get("correct_answer") not in LABELS:
        errors.append("correct_answer must be A/B/C/D")
    if item.get("qa_metadata", {}).get("clean_sentence_validated") is not True:
        errors.append("qa_metadata.clean_sentence_validated must be true")
    grammar_metadata = item.get("grammar_metadata")
    if not isinstance(grammar_metadata, dict):
        errors.append("grammar_metadata must be an object")
    else:
        if grammar_metadata.get("error_scope") not in ERROR_SCOPES:
            errors.append("grammar_metadata.error_scope is invalid")
        if grammar_metadata.get("correction_locality") not in CORRECTION_LOCALITIES:
            errors.append("grammar_metadata.correction_locality is invalid")
        if grammar_metadata.get("decision_granularity") not in DECISION_GRANULARITIES:
            errors.append("grammar_metadata.decision_granularity is invalid")
        if grammar_metadata.get("intended_error_position") != item.get("correct_answer"):
            errors.append("grammar_metadata.intended_error_position must equal correct_answer")
        if grammar_metadata.get("correct_span_type") not in SPAN_TYPES:
            errors.append("grammar_metadata.correct_span_type is invalid")
    format_metadata = item.get("format_metadata")
    if not isinstance(format_metadata, dict):
        errors.append("format_metadata must be an object")
    else:
        required_format_keys = {"target_sentence_length_region", "expected_span_profile", "coverage_profile", "approximate_context_profile", "span_types", "diagnostics"}
        errors.extend(f"missing format_metadata field: {key}" for key in sorted(required_format_keys - set(format_metadata)))
        if not isinstance(format_metadata.get("diagnostics"), dict):
            errors.append("format_metadata.diagnostics must be an object")
    provenance = item.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    else:
        required_provenance_keys = {"agent_version", "prompt_hash", "spec_version", "format_spec_version", "generation_batch_id", "microbatch_id", "item_generation_order", "invocation_id", "runtime_model"}
        errors.extend(f"missing provenance field: {key}" for key in sorted(required_provenance_keys - set(provenance)))
    qa = item.get("qa_metadata")
    if not isinstance(qa, dict):
        errors.append("qa_metadata must be an object")
    else:
        for key in ("clean_form", "error_form", "minimal_correction", "mutation_type", "grammar_check_status", "format_check_status"):
            if not isinstance(qa.get(key), str) or not qa[key]:
                errors.append(f"qa_metadata.{key} must be a nonempty string")
        if qa.get("grammar_check_status") not in {"PASS", "FAIL", "AMBIGUOUS"}:
            errors.append("qa_metadata.grammar_check_status is invalid")
        if qa.get("format_check_status") not in {"PASS", "WARN", "FAIL"}:
            errors.append("qa_metadata.format_check_status is invalid")

    diagnostics, diagnostic_errors = format_diagnostics(item, config)
    errors.extend(diagnostic_errors)
    declared = item.get("format_metadata", {}).get("diagnostics", {})
    if diagnostics and declared:
        for key in (
            "sentence_word_count", "span_word_counts", "mean_span_length", "max_span_length",
            "marked_coverage_ratio", "unmarked_word_count", "gap_A_B", "gap_B_C", "gap_C_D",
            "correct_span_word_count", "correct_span_type", "correction_locality",
            "decision_granularity", "format_distribution_distance", "format_percentile_profile",
            "format_band_status", "metric_band_status", "span_token_indices",
        ):
            if key in declared and key in diagnostics and declared[key] != diagnostics[key]:
                if isinstance(declared[key], float) and abs(declared[key] - diagnostics[key]) < 0.00011:
                    continue
                errors.append(f"format_metadata.diagnostics.{key} does not match deterministic calculation")

    return {"item_id": item_id, "valid": not errors, "errors": errors, "diagnostics": diagnostics}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("items", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    config = load_json(CONFIG_PATH)
    grammar = load_json(GRAMMAR_SPEC_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    targets = {x["id"] for x in taxonomy["primary_targets"]}
    error_types = {x["id"] for x in grammar["tested_error_types"] if x["id"] not in {"fragment", "wrong_complementation"}}
    results = [validate_item(item, config, targets, error_types) for item in load_items(args.items)]
    report = {
        "validator": "TOEFL ITP WE deterministic format validator v2.0",
        "config": config["config_id"],
        "item_count": len(results),
        "valid_count": sum(result["valid"] for result in results),
        "invalid_count": sum(not result["valid"] for result in results),
        "items": results,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["invalid_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
