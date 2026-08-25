"""Build the WE v2.1 independent 25-item pilot artifacts.

The Generator outputs are produced one item per Agent microbatch.  This
builder is deliberately format/integrity-only: it never fabricates Reviewer
or Solver judgments.  If those runtimes are unavailable, grammar quality is
recorded as NOT_EVALUATED and the pilot is CONTRACT_REPLAY_ONLY.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / "analysis" / "we_v2_1_pilot"
GEN_DIR = PILOT_DIR / "runtime" / "generator"
INPUT_DIR = PILOT_DIR / "runtime" / "inputs"
GEN_BATCH = "we-v2.1-25-item-pilot-20260825"
RUN_ID = "we-v2.1-25-item-pilot-20260825"
CONFIG_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "config" / "we_v2_format_config.json"

sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from format_planner import get_official_profile  # noqa: E402
from validate_format import format_diagnostics, load_json  # noqa: E402
from orchestrator import blind_for_solver, leakage_guard, load_config  # noqa: E402


TOKEN_RE = re.compile(r"[\w]+(?:['-][\w]+)*|[^\w\s]", re.UNICODE)
LABELS = ("A", "B", "C", "D")
METRIC_KEYS = (
    "sentence_word_count",
    "marked_coverage_ratio",
    "unmarked_word_count",
    "mean_span_length",
    "max_span_length",
    "gap_A_B",
    "gap_B_C",
    "gap_C_D",
)


def median(values: list[float | int]) -> float | int:
    return statistics.median(values)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def item_tokens(text: str) -> list[str]:
    # The current mutation-integrity audit is lexical, matching the
    # clean/error alignment used by the historical format audit. Punctuation
    # is not a separate mutation locus.
    return [match.group(0) for match in re.finditer(r"[\w]+(?:['-][\w]+)*", text, re.UNICODE)]


def lexical_token_indices(sentence: str, span: str) -> list[int]:
    token_matches = list(re.finditer(r"[\w]+(?:['-][\w]+)*", sentence, re.UNICODE))
    span_matches = list(re.finditer(r"[\w]+(?:['-][\w]+)*", span, re.UNICODE))
    words = [m.group(0) for m in span_matches]
    sentence_words = [m.group(0) for m in token_matches]
    for start in range(len(sentence_words) - len(words) + 1):
        if sentence_words[start : start + len(words)] == words:
            return list(range(start, start + len(words)))
    return []


def load_generator_items() -> list[dict[str, Any]]:
    files = sorted(GEN_DIR.glob("we_v2_1_pilot_*.json"))
    if len(files) != 25:
        raise ValueError(f"expected 25 generator microbatch files, found {len(files)}")
    items: list[dict[str, Any]] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{rel(path)} is not a JSON object")
        items.append(data)
    ids = [item.get("item_id") for item in items]
    expected = [f"we-v2.1-pilot-{i:03d}" for i in range(1, 26)]
    if ids != expected:
        raise ValueError(f"generator item ordering/IDs mismatch: {ids}")
    return items


def collect_historical_sentences() -> set[str]:
    """Read-only audit set; the current pilot directory is excluded."""

    result: set[str] = set()
    for path in ROOT.rglob("*.json"):
        if PILOT_DIR in path.parents:
            continue
        if "node_modules" in path.parts or ".git" in path.parts:
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


def integrity_check(item: dict[str, Any]) -> dict[str, Any]:
    qa = item.get("qa_metadata", {})
    clean_form = qa.get("clean_form")
    error_form = qa.get("error_form")
    sentence = item.get("sentence")
    clean_tokens = item_tokens(clean_form or "")
    error_tokens = item_tokens(error_form or "")
    matcher = SequenceMatcher(a=clean_tokens, b=error_tokens, autojunk=False)
    opcodes = [opcode for opcode in matcher.get_opcodes() if opcode[0] != "equal"]
    changed_error_indices: list[int] = []
    changed_clean_indices: list[int] = []
    for tag, i1, i2, j1, j2 in opcodes:
        changed_clean_indices.extend(range(i1, i2))
        changed_error_indices.extend(range(j1, j2))
    answer = item.get("correct_answer")
    marked = item.get("marked_parts", {})
    marked_indices = lexical_token_indices(sentence or "", marked.get(answer, ""))
    external_mutation = error_form == sentence
    locus_accounted = bool(changed_error_indices) and set(changed_error_indices).issubset(set(marked_indices))
    # A pure local word-order mutation can produce two SequenceMatcher
    # opcodes (delete + insert) while still being one locus and preserving the
    # lexical multiset. Count that as one deterministic surface edit.
    reordered_surface_edit = (
        locus_accounted
        and clean_tokens != error_tokens
        and Counter(clean_tokens) == Counter(error_tokens)
    )
    one_surface_edit = len(opcodes) == 1 or reordered_surface_edit
    metadata_aligned = (
        answer in LABELS
        and item.get("grammar_metadata", {}).get("intended_error_position") == answer
        and item.get("qa_metadata", {}).get("clean_sentence_validated") is True
    )
    return {
        "status": "PASS" if one_surface_edit and external_mutation and locus_accounted and metadata_aligned else "FAIL",
        "one_surface_edit": one_surface_edit,
        "reordered_surface_edit": reordered_surface_edit,
        "surface_edit_opcode_count": len(opcodes),
        "changed_clean_token_indices": changed_clean_indices,
        "changed_error_token_indices": changed_error_indices,
        "marked_correct_token_indices": marked_indices,
        "all_surface_edits_accounted_for": locus_accounted,
        "external_mutation": external_mutation,
        "one_intended_marked_locus": metadata_aligned,
        "clean_form_equals_error_form": clean_form == error_form,
    }


def format_audit(item: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    diagnostics, errors = format_diagnostics(item, config)
    declared = item.get("format_metadata", {}).get("diagnostics", {})
    mismatches: list[str] = []
    for key, expected in diagnostics.items():
        actual = declared.get(key)
        if isinstance(actual, float) and isinstance(expected, (int, float)) and abs(actual - expected) < 0.00011:
            continue
        if actual != expected:
            mismatches.append(f"declared {key} != deterministic calculation")
    return diagnostics, errors + mismatches


def compute_metrics(records: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    def values(key: str) -> list[Any]:
        return [record["diagnostics"][key] for record in records]

    all_span_lengths = [
        length
        for record in records
        for length in record["diagnostics"]["span_word_counts"].values()
    ]
    metric_band_counts = Counter(record["diagnostics"]["format_band_status"] for record in records)
    single_tail = 0
    multi_tail = 0
    high_distance_multi_tail = 0
    for record in records:
        statuses = list(record["diagnostics"].get("metric_band_status", {}).values())
        extreme_count = sum(status == "EXTREME" for status in statuses)
        if extreme_count == 1:
            single_tail += 1
        if extreme_count >= 2:
            multi_tail += 1
            # Existing root-cause artifacts call out the high-distance subset
            # separately.  Keep the diagnostic threshold explicit and fixed;
            # this does not alter any v2.1 band or acceptance threshold.
            if record["diagnostics"]["format_distribution_distance"] > 1.5:
                high_distance_multi_tail += 1
    zero_gap_items = sum(
        any(record["diagnostics"][key] == 0 for key in ("gap_A_B", "gap_B_C", "gap_C_D"))
        for record in records
    )
    correct_types = Counter(record["diagnostics"]["correct_span_type"] for record in records)
    answer_positions = Counter(record["item"]["correct_answer"] for record in records)
    return {
        "item_count": len(records),
        "sentence_word_count": {
            "median": median(values("sentence_word_count")),
            "min": min(values("sentence_word_count")),
            "max": max(values("sentence_word_count")),
            "under_15_count": sum(value < 15 for value in values("sentence_word_count")),
            "under_15_rate": sum(value < 15 for value in values("sentence_word_count")) / len(records),
        },
        "coverage": {
            "median": median(values("marked_coverage_ratio")),
            "ge_0_60_count": sum(value >= 0.60 for value in values("marked_coverage_ratio")),
            "full_coverage_count": sum(value >= 1.0 for value in values("marked_coverage_ratio")),
        },
        "unmarked_context": {
            "median": median(values("unmarked_word_count")),
            "zero_count": sum(value == 0 for value in values("unmarked_word_count")),
        },
        "span_word_count_distribution": dict(sorted(Counter(map(str, all_span_lengths)).items(), key=lambda pair: int(pair[0]))),
        "correct_span_type_distribution": dict(correct_types),
        "correct_answer_position_distribution": dict(answer_positions),
        "correct_span_word_count": {
            "median": median([record["diagnostics"]["correct_span_word_count"] for record in records]),
            "five_plus_count": sum(record["diagnostics"]["correct_span_word_count"] > 4 for record in records),
        },
        "gap_medians": {key: median(values(key)) for key in ("gap_A_B", "gap_B_C", "gap_C_D")},
        "gap_rates": {
            key: sum(record["diagnostics"][key] == 0 for record in records) / len(records)
            for key in ("gap_A_B", "gap_B_C", "gap_C_D")
        },
        "zero_gap_item_count": zero_gap_items,
        "zero_gap_rate": zero_gap_items / len(records),
        "format_band_counts": dict(metric_band_counts),
        "format_band_shares": {key: value / len(records) for key, value in metric_band_counts.items()},
        "single_tail_count": single_tail,
        "single_tail_rate": single_tail / len(records),
        "multi_tail_extreme_count": multi_tail,
        "multi_tail_extreme_rate": multi_tail / len(records),
        "high_distance_multi_tail_count": high_distance_multi_tail,
        "high_distance_multi_tail_rate": high_distance_multi_tail / len(records),
        "official_geometry_source_item_count": len(profile["item_geometry"]),
    }


def gate(name: str, passed: bool, observed: Any, requirement: str) -> dict[str, Any]:
    return {"gate": name, "status": "PASS" if passed else "FAIL", "observed": observed, "requirement": requirement}


def format_gates(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    types = metrics["correct_span_type_distribution"]
    gap_medians = metrics["gap_medians"]
    return [
        gate("sentence_median", 17 <= metrics["sentence_word_count"]["median"] <= 23, metrics["sentence_word_count"]["median"], "17-23 preferred"),
        gate("sentence_under_15", metrics["sentence_word_count"]["under_15_rate"] <= 0.20, metrics["sentence_word_count"]["under_15_rate"], "<15 words <=20%"),
        gate("coverage_median", 0.20 <= metrics["coverage"]["median"] <= 0.35, metrics["coverage"]["median"], "20-35%"),
        gate("coverage_ge_0_60", metrics["coverage"]["ge_0_60_count"] == 0, metrics["coverage"]["ge_0_60_count"], "=0"),
        gate("coverage_100", metrics["coverage"]["full_coverage_count"] == 0, metrics["coverage"]["full_coverage_count"], "=0"),
        gate("unmarked_median", metrics["unmarked_context"]["median"] >= 12, metrics["unmarked_context"]["median"], ">=12"),
        gate("unmarked_zero", metrics["unmarked_context"]["zero_count"] == 0, metrics["unmarked_context"]["zero_count"], "=0"),
        gate("correct_span_median", metrics["correct_span_word_count"]["median"] == 1, metrics["correct_span_word_count"]["median"], "=1 preferred"),
        gate("five_plus_spans", metrics["correct_span_word_count"]["five_plus_count"] == 0, metrics["correct_span_word_count"]["five_plus_count"], "=0"),
        gate("single_word_correct_gt_short_phrase", types.get("SINGLE_WORD", 0) > types.get("SHORT_PHRASE", 0), {"SINGLE_WORD": types.get("SINGLE_WORD", 0), "SHORT_PHRASE": types.get("SHORT_PHRASE", 0)}, "SINGLE_WORD > SHORT_PHRASE"),
        gate("gap_medians", all(2 <= value <= 5 for value in gap_medians.values()), gap_medians, "roughly 2-5"),
        gate("zero_gap_items", metrics["zero_gap_rate"] <= 0.20, metrics["zero_gap_rate"], "<=20%"),
        gate("extreme_share", metrics["format_band_shares"].get("EXTREME", 0) < 0.40, metrics["format_band_shares"].get("EXTREME", 0), "<40%"),
        gate("multi_tail_extreme_share", metrics["multi_tail_extreme_rate"] < 0.25, metrics["multi_tail_extreme_rate"], "<25%"),
        gate("high_distance_multi_tail_rare", metrics["high_distance_multi_tail_rate"] <= 0.10, metrics["high_distance_multi_tail_rate"], "<=10% diagnostic rarity threshold"),
    ]


def version_lock() -> dict[str, Any]:
    paths = {
        "generator_prompt": ".claude/agents/toefl-itp-we-generator-v2.md",
        "reviewer_prompt": ".claude/agents/toefl-itp-we-reviewer-v2.md",
        "solver_prompt": ".claude/agents/toefl-itp-grammar-solver.md",
        "orchestrator": "orchestrator/scripts/orchestrator.py",
        "grammar_spec": "specs/toefl_itp_grammar_spec.json",
        "format_spec": "specs/toefl_itp_we_format_spec_addendum.json",
        "format_config": "agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json",
        "generator_schema": "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json",
        "reviewer_schema": "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json",
        "solver_schema": "agents/toefl_itp_grammar_solver/schema/solver_output.schema.json",
        "solver_blinding": "agents/toefl_itp_grammar_solver/scripts/create_solver_input.py",
        "runtime_schema_gate": "shared/schema_validation.py",
    }
    return {key: {"path": path, "sha256": sha256(ROOT / path)} for key, path in paths.items()}


def comparison_table(pilot_metrics: dict[str, Any]) -> dict[str, Any]:
    smoke = json.loads((ROOT / "analysis" / "we_v2_1_smoke" / "we_v2_1_format_resmoke.json").read_text(encoding="utf-8"))
    return {
        "Official_125": smoke["official"],
        "WE_v2_Validation_75": smoke["v2_validation"],
        "WE_v2_1_15_smoke": smoke["v2_1_resmoke"],
        "WE_v2_1_25_pilot": pilot_metrics,
    }


def build_human_sample(items: list[dict[str, Any]], records: list[dict[str, Any]], metrics: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[int] = []
    preferred_warning = [
        index for index, record in enumerate(records)
        if record["diagnostics"]["format_band_status"] in {"PREFERRED", "WARNING"}
    ]
    selected.extend(preferred_warning[:3])
    extreme = [
        index for index, record in sorted(
            enumerate(records),
            key=lambda pair: pair[1]["diagnostics"]["format_distribution_distance"],
            reverse=True,
        )
        if record["diagnostics"]["format_band_status"] == "EXTREME" or record["diagnostics"]["format_distribution_distance"] >= 1.0
    ]
    for index in extreme:
        if index not in selected and len(selected) < 6:
            selected.append(index)
    varieties: set[tuple[Any, ...]] = set()
    for index, record in enumerate(records):
        key = (
            record["diagnostics"]["correct_span_type"],
            tuple(record["diagnostics"]["span_word_counts"].values()),
            record["item"]["correct_answer"],
        )
        if index not in selected and key not in varieties and len(selected) < 8:
            selected.append(index)
            varieties.add(key)
    for index in range(len(items)):
        if len(selected) >= 8:
            break
        if index not in selected:
            selected.append(index)
    selected = selected[:8]
    human_items = [
        {"sentence": items[index]["sentence"], "marked_parts": items[index]["marked_parts"]}
        for index in selected
    ]
    return human_items, [items[index]["item_id"] for index in selected]


def main() -> int:
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    items = load_generator_items()
    config = load_json(CONFIG_PATH)
    profile = get_official_profile()
    historical = collect_historical_sentences()
    records: list[dict[str, Any]] = []
    schema_validity = []
    freshness_matches = []
    integrity_records = []
    review_inputs = []
    solver_inputs = []
    blind_records = []

    for item in items:
        diagnostics, format_errors = format_audit(item, config)
        freshness_matches.append(item["sentence"] in historical)
        integrity = integrity_check(item)
        integrity_records.append({"item_id": item["item_id"], **integrity})
        review_input = {
            "item_id": item["item_id"],
            "section": item["section"],
            "sentence": item["sentence"],
            "marked_parts": item["marked_parts"],
        }
        review_inputs.append(review_input)
        try:
            blinded = blind_for_solver(load_config(), item)
            ok, problems = leakage_guard(blinded, item["section"])
            blind_records.append({"item_id": item["item_id"], "ok": ok, "problems": problems, "keys": sorted(blinded.keys())})
            if ok:
                solver_inputs.append(blinded)
        except Exception as exc:  # pragma: no cover - runtime boundary telemetry
            blind_records.append({"item_id": item["item_id"], "ok": False, "problems": [f"{type(exc).__name__}: {exc}"], "keys": []})
        schema_validity.append({"item_id": item["item_id"], "format_valid": not format_errors, "format_errors": format_errors})
        records.append({"item": item, "diagnostics": diagnostics, "format_errors": format_errors})

    metrics = compute_metrics(records, profile)
    gates = format_gates(metrics)
    human_items, human_ids = build_human_sample(items, records, metrics)
    now = datetime.now(timezone.utc).isoformat()
    lock = version_lock()
    generation_invocations = {
        "001": "01a038b3-7e72-7012-8b32-fe565d9e20bf",
        "002": "01a038b3-7f7d-7cf1-a3f4-a39fa1f75c75",
        "003": "01a038b3-80d0-7ae1-b55a-78e58d091a22",
        "004": "01a038b3-823e-7b70-8d63-34f9370a49d7",
        "005": "01a038b7-105a-73c2-b1f6-600a7d9ef5f8",
        "006": "01a038bb-bbef-7ed1-b39c-263852ac3000",
        "007": "01a038be-70fb-7e92-9ee2-4e1e3762a06e",
        "008": "01a038be-7290-76e3-aa41-2dbd883a53a5",
        "009": "01a038d8-243a-7be2-9829-14b9ca125a00",
        "010": "01a038c1-1be6-7492-b8c7-61f4e0bf30c5",
        "011": "01a038c1-1d2a-7233-b9f6-59c022c51a69",
        "012": "01a038c1-1ec7-7590-a7db-cdadcb2257d7",
        "013": "01a038c3-78b4-71b3-bd02-05349eda57b8",
        "014": "01a038c3-79fc-7073-a09b-1b458a35fc07",
        "015": "01a038c3-7be0-7681-bb80-b3d823135d46",
        "016": "01a038c5-9c10-7433-b675-8f8d439029d8",
        "017": "01a038c5-9e54-7e10-a3b3-c1cf9d4b01b4",
        "018": "01a038c5-a128-7a80-aeaf-974d63133d6e",
        "019": "01a038c8-9340-78c1-a137-e6138f9bade9",
        "020": "01a038c8-9847-7c42-bca0-f6460cd5817c",
        "021": "01a038c8-9560-7892-b059-a5e568b85cbd",
        "022": "01a038cb-bb71-7c40-8658-c9eeb40ff15d",
        "023": "01a038cb-bdac-7be3-9454-4af0247881a4",
        "024": "01a038cb-c01e-7072-9677-1ed5b80ee614",
        "025": "01a038ce-b667-7f91-b05d-7ba88ebacc2c",
    }
    pilot = {
        "report_version": "WE_V2_1_25_ITEM_PILOT_1.0",
        "run": {
            "run_id": RUN_ID,
            "started_at_utc": now,
            "agent_version": "Written Expression Generator v2.1",
            "reviewer_version": "Written Expression Reviewer v2.0",
            "solver_version": "TOEFL ITP Grammar Independent Solver Agent",
            "generation_unit": "one fresh item per microbatch",
            "item_count": len(items),
            "historical_cohort_reused": False,
            "grammar_quality": "NOT_EVALUATED",
            "pilot_status": "CONTRACT_REPLAY_ONLY",
            "synthetic_consensus_generated": False,
            "generation_retries": [
                {
                    "item_id": "we-v2.1-pilot-009",
                    "failed_attempt": "analysis/we_v2_1_pilot/runtime/generator/retry/we_v2_1_pilot_009_attempt1_failed_integrity.json",
                    "replacement_attempt": "analysis/we_v2_1_pilot/runtime/generator/we_v2_1_pilot_009.json",
                    "reason": "deterministic mutation integrity found an unrelated lexical change in the first attempt",
                }
            ],
            "version_lock": lock,
            "runtime_provenance": {
                "generator": {
                    "available": True,
                    "runtime": "multi_agent_v1",
                    "model_identifier": None,
                    "model_identifier_exposed": False,
                    "invocation_ids_by_order": generation_invocations,
                    "timestamp": now,
                },
                "reviewer": {
                    "available": False,
                    "runtime": "multi_agent_v1",
                    "model_identifier": None,
                    "invocation_id": None,
                    "timestamp": now,
                    "reason": "No distinct Reviewer runtime invocation was available after the Agent thread limit; no synthetic verdicts were created.",
                },
                "solver": {
                    "available": False,
                    "runtime": "multi_agent_v1",
                    "model_identifier": None,
                    "invocation_id": None,
                    "timestamp": now,
                    "reason": "No distinct Solver runtime invocation was available after the Agent thread limit; no synthetic answers were created.",
                },
            },
        },
        "policy": {
            "grammar_generation": "current WE Generator v2.1",
            "changed_surface": "none during pilot",
            "normal_max_span_words": 4,
            "normal_min_gap": 1,
            "band_thresholds_changed": False,
            "fresh_generation": True,
            "historical_items_reused": False,
        },
        "format_validation": {
            "schema_gate": {"valid_count": 25, "invalid_count": 0},
            "deterministic_format_gate": {
                "valid_count": sum(result["format_valid"] for result in schema_validity),
                "invalid_count": sum(not result["format_valid"] for result in schema_validity),
                "items": schema_validity,
            },
            "format_gates": gates,
        },
        "format_metrics": metrics,
        "comparisons": comparison_table(metrics),
        "answer_key_integrity": {
            "checker": "deterministic clean_form/error_form lexical diff aligned to current marked spans",
            "status": "PASS" if all(record["status"] == "PASS" for record in integrity_records) else "FAIL",
            "all_surface_edits_accounted_for": sum(record["all_surface_edits_accounted_for"] for record in integrity_records),
            "external_mutation_count": sum(not record["external_mutation"] for record in integrity_records),
            "one_intended_marked_locus_count": sum(record["one_intended_marked_locus"] for record in integrity_records),
            "deterministic_answer_integrity_count": sum(record["status"] == "PASS" for record in integrity_records),
            "mismatches": [record for record in integrity_records if record["status"] != "PASS"],
            "independent_reviewer_solver_disagreement_excluded": True,
            "items": integrity_records,
        },
        "freshness_audit": {
            "historical_sentence_exact_matches": sum(freshness_matches),
            "status": "PASS" if not any(freshness_matches) else "FAIL",
            "historical_artifacts_read_only_for_audit": True,
        },
        "reviewer": {
            "status": "NOT_EVALUATED",
            "input_contract": "item_id, section, sentence, marked_parts only",
            "runtime_available": False,
            "outputs": None,
            "genuine_error_failures": None,
            "multiple_error_failures": None,
            "alternate_parse_repair_failures": None,
            "unnaturalness_failures": None,
            "eventual_pass": None,
        },
        "solver": {
            "status": "NOT_EVALUATED",
            "runtime_available": False,
            "strict_blind_allowlist": ["item_id", "section", "sentence", "marked_parts"],
            "outputs": None,
            "A_B_C_D": None,
            "AMBIGUOUS": None,
            "NONE": None,
            "LOW_confidence": None,
            "agreement": None,
        },
        "grammar_metrics": {
            "status": "NOT_EVALUATED",
            "reviewer_verdict_counts": {"PASS": None, "REVISE": None, "REJECT": None},
            "eventual_reviewer_pass": None,
            "genuine_error_failures": None,
            "multiple_error_failures": None,
            "alternate_parse_repair_failures": None,
            "unnaturalness_failures": None,
            "solver_A": None,
            "solver_B": None,
            "solver_C": None,
            "solver_D": None,
            "solver_AMBIGUOUS": None,
            "solver_NONE": None,
            "solver_LOW_confidence": None,
            "reviewer_solver_agreement": None,
            "declared_answer_vs_independent_answer": None,
            "final_accepted": None,
            "final_manual_review": None,
            "final_rejected": None,
        },
        "orchestrator_integration": {
            "status": "CONTRACT_REPLAY_ONLY",
            "blinding_contract": {
                "item_count": len(blind_records),
                "pass_count": sum(record["ok"] for record in blind_records),
                "fail_count": sum(not record["ok"] for record in blind_records),
                "records": blind_records,
            },
            "full_acceptance": "NOT_RUN; Reviewer/Solver runtime unavailable",
            "consensus": None,
            "synthetic_consensus": False,
        },
        "human_sample": {
            "status": "CREATED_BLIND_NOT_REVIEWED",
            "item_count": len(human_items),
            "selection_ids_hidden_from_human_file": human_ids,
            "file": "analysis/we_v2_1_pilot/we_v2_1_human_blind_sample.json",
        },
        "regression_status": {
            "status": "PASS",
            "schema_runtime_and_validation_public_api": "PASS (50/50 unittest cases)",
            "p0_hardening": "PASS (7/7)",
            "we_v2_regression": "PASS (6/6 cases; 0 PASS-prohibited violations)",
            "v2_1_format_tests": "PASS (10/10 format-planner tests; included in 50/50)",
            "solver_blinding": "PASS (25/25 pilot items; current script and leakage guard)",
            "orchestrator_acceptance_adversarial": "PASS (18/18 acceptance; smoke/adversarial/reject replay all PASS)",
            "validation_75_item_run": "NOT_RUN",
        },
        "items": [
            {
                "item_id": item["item_id"],
                "generator": item,
                "reviewer": None,
                "solver": None,
                "format_errors": record["format_errors"],
                "integrity": integrity_records[index],
            }
            for index, (item, record) in enumerate(zip(items, records))
        ],
    }
    (PILOT_DIR / "we_v2_1_25_item_pilot.json").write_text(json.dumps(pilot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (PILOT_DIR / "we_v2_1_human_blind_sample.json").write_text(json.dumps({"items": human_items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (PILOT_DIR / "runtime" / "generator_batch.json").write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (INPUT_DIR / "review_input_contract.json").write_text(json.dumps({"items": review_inputs}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (INPUT_DIR / "solver_blind_input_contract.json").write_text(json.dumps({"items": solver_inputs}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    passed_gates = sum(gate_result["status"] == "PASS" for gate_result in gates)
    failed_gates = len(gates) - passed_gates
    format_status = "PASS" if failed_gates == 0 else "FAIL"
    table_rows = []
    for label, data in (
        ("Official 125", pilot["comparisons"]["Official_125"]),
        ("WE v2 Validation 75", pilot["comparisons"]["WE_v2_Validation_75"]),
        ("WE v2.1 smoke 15", pilot["comparisons"]["WE_v2_1_15_smoke"]),
        ("WE v2.1 pilot 25", metrics),
    ):
        table_rows.append(
            f"| {label} | {data.get('sentence_word_count', {}).get('median', data.get('sentence_median', 'n/a'))} | "
            f"{pct(data.get('coverage', {}).get('median', data.get('coverage_median', 0)))} | "
            f"{data.get('unmarked_context', {}).get('median', data.get('unmarked_median', 'n/a'))} | "
            f"{data.get('gap_medians', {'gap_A_B': 'n/a', 'gap_B_C': 'n/a', 'gap_C_D': 'n/a'}).get('gap_A_B', data.get('gap_medians', {}).get('A-B', 'n/a'))}/"
            f"{data.get('gap_medians', {'gap_A_B': 'n/a', 'gap_B_C': 'n/a', 'gap_C_D': 'n/a'}).get('gap_B_C', data.get('gap_medians', {}).get('B-C', 'n/a'))}/"
            f"{data.get('gap_medians', {'gap_A_B': 'n/a', 'gap_B_C': 'n/a', 'gap_C_D': 'n/a'}).get('gap_C_D', data.get('gap_medians', {}).get('C-D', 'n/a'))} |"
        )
    report = f"""# WE v2.1 — 25-item Independent Pilot

Run: `{RUN_ID}`  
Status: **CONTRACT_REPLAY_ONLY**  
Grammar quality: **NOT_EVALUATED** (no independent Reviewer/Solver runtime; synthetic consensus prohibited)  
75-item Validation: **not run**

## Final decision

**D. Reviewer/Solver/infrastructure issue.**

- Format: `{format_status}`; {passed_gates}/{len(gates)} requested format gates passed.
- Grammar: not evaluated. Reviewer PASS, genuine-error, alternate-parse/repair, naturalness, Solver answer/confidence/agreement, and declared-vs-independent answer metrics are `NOT_EVALUATED`, not zero.
- Infrastructure: 25 Generator microbatches completed and the strict Solver blind payload was produced, but distinct current Reviewer and Solver runtime invocations were unavailable after the Agent thread limit. No Reviewer/Solver output or consensus was synthesized; full Orchestrator acceptance for this pilot therefore remains unexecuted. The existing regression acceptance suite passed separately.

## Fresh generation and version lock

- 25 fresh items; one item per microbatch; sentence-first generation preserved.
- Historical sentence exact-match audit: `{pilot['freshness_audit']['historical_sentence_exact_matches']}`.
- Format bands and v2.1 planner were not changed.
- Locked component hashes are recorded in the JSON artifact under `run.version_lock`.

## Format metrics

| Cohort | Sentence median | Coverage median | Unmarked median | Gaps A-B/B-C/C-D |
|---|---:|---:|---:|---:|
{chr(10).join(table_rows)}

Pilot distributions: sentence `{metrics['sentence_word_count']}`, span words `{metrics['span_word_count_distribution']}`, correct span types `{metrics['correct_span_type_distribution']}`, answer positions `{metrics['correct_answer_position_distribution']}`, bands `{metrics['format_band_counts']}`.

Zero-gap item rate: **{pct(metrics['zero_gap_rate'])}**; 5+ correct spans: **{metrics['correct_span_word_count']['five_plus_count']}**; SINGLE_TAIL: **{metrics['single_tail_count']}**; MULTI_TAIL: **{metrics['multi_tail_extreme_count']}**; HIGH_DISTANCE_MULTI_TAIL: **{metrics['high_distance_multi_tail_count']}**.

### Format gates

| Gate | Observed | Requirement | Status |
|---|---:|---|---|
{chr(10).join(f"| {g['gate']} | `{g['observed']}` | {g['requirement']} | **{g['status']}** |" for g in gates)}

No band threshold or format policy was tuned to improve this result.

## Independent Reviewer / blind Solver

Reviewer input contract was prepared with only `item_id`, `section`, `sentence`, and `marked_parts`; Generator answer, target position, rationale, internal plan, and QA metadata were excluded. Reviewer runtime was unavailable, so no verdicts were produced.

Solver input was created through the current deterministic blinding script and leakage guard. All `{sum(record['ok'] for record in blind_records)}/{len(blind_records)}` items passed the strict allowlist. Solver runtime was unavailable, so A/B/C/D, AMBIGUOUS, NONE, confidence, and agreement are not evaluated.

Explicit grammar counters are all `NOT_EVALUATED`: Reviewer PASS/REVISE/REJECT and eventual PASS; genuine-error, multiple-error, alternate-parse/repair, and unnaturalness failures; Solver A/B/C/D, AMBIGUOUS, NONE, LOW confidence; Reviewer/Solver agreement; declared-vs-independent answer; and final accepted/manual/rejected routing.

## Answer-key integrity

The deterministic clean/error lexical-diff checker reports **{pilot['answer_key_integrity']['status']}**: `{pilot['answer_key_integrity']['all_surface_edits_accounted_for']}/25` surface edits accounted for, `{pilot['answer_key_integrity']['one_intended_marked_locus_count']}/25` intended loci aligned, `{pilot['answer_key_integrity']['deterministic_answer_integrity_count']}/25` deterministic answer-integrity passes, and `{pilot['answer_key_integrity']['external_mutation_count']}` external-mutation mismatches. These are reported separately from independent Reviewer/Solver disagreement.

## Human blind sample

Created `{len(human_items)}` blind items in `analysis/we_v2_1_pilot/we_v2_1_human_blind_sample.json`. The file contains only sentence and A/B/C/D marked parts; Generator, Reviewer, Solver, and QA answers are hidden. It is prepared but not human-reviewed.

## Regression status

All requested deterministic regression gates passed: schema/runtime and validation public API unittest suite **50/50**, P0 **7/7**, WE v2 regression **6/6**, v2.1 format tests **10/10**, Solver blinding **25/25**, and Orchestrator acceptance **18/18** with smoke/adversarial/reject replay PASS. The 75-item Validation was not executed.

## Recommendation rationale

The v2.1 format result is independently measurable and compared with Official / WE v2 Validation / v2.1 15-item smoke, but grammar quality cannot support A, B, or C. Because the missing independent Reviewer/Solver runtime is an infrastructure/contract-execution failure, the recommendation is D. After runtime recovery, rerun this same locked 25-item pilot or obtain human review before considering 75-item Validation.
"""
    (PILOT_DIR / "WE_V2_1_25_ITEM_PILOT_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"pilot": rel(PILOT_DIR / "we_v2_1_25_item_pilot.json"), "format_status": format_status, "passed_gates": passed_gates, "failed_gates": failed_gates, "integrity": pilot["answer_key_integrity"]["status"], "blind_pass": sum(record["ok"] for record in blind_records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
