#!/usr/bin/env python3
"""Re-audit the existing WE v2 75-item validation cohort.

This script deliberately reads the registered 75-item artifact. It does not
call the generator and it does not generate replacement or new items.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "analysis" / "we_v2_validation"
ITEMS_PATH = OUT_DIR / "we_v2_validation_initial_items.json"
REVIEWS_PATH = OUT_DIR / "we_v2_validation_reviews.json"
SOLVER_PATH = OUT_DIR / "we_v2_validation_solver.json"
OLD_METRICS_PATH = OUT_DIR / "we_v2_validation_metrics.json"
OLD_REPORT_PATH = OUT_DIR / "WE_V2_VALIDATION_REPORT.md"
AUDIT_JSON_PATH = OUT_DIR / "we_v2_validation_integrity_reaudit.json"
AUDIT_REPORT_PATH = OUT_DIR / "WE_V2_VALIDATION_INTEGRITY_REAUDIT.md"

GENERATOR_SCRIPTS = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"
sys.path.insert(0, str(GENERATOR_SCRIPTS))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))
sys.path.insert(0, str(OUT_DIR))
sys.path.insert(0, str(ROOT))

from integrity import derive_correct_answer, mutation_location, span_kind  # noqa: E402
from validate_format import (  # noqa: E402
    REQUIRED_DIAGNOSTIC_KEYS,
    format_diagnostics,
    load_items,
    load_json,
    schema_errors,
    validate_item,
)
from run_validation import (  # noqa: E402
    CONFIG,
    ITEM_SCHEMA,
    LABELS,
    ROOT as VALIDATION_ROOT,
    SPEC_VERSION,
    TARGETS,
    format_analysis,
    geometry_gate_status,
)
from agents.toefl_itp_grammar_solver.scripts.create_solver_input import (  # noqa: E402
    WRITTEN_EXPRESSION_ALLOWLIST,
    blind_item,
)


RUN_ID = "we-v2-validation-integrity-reaudit-20260824"
KNOWN_BASES = {15, 17, 20, 22, 23}
LEGACY_FALSE_ERROR_PATTERNS = (
    ("By the time", "had mapped", " mapped "),
    ("When the committee convened", "had distributed", " distributed "),
)
UNRESOLVED_SPAN_KIND = "UNRESOLVED"
REVIEWER_FORBIDDEN_KEYS = {"intended_answer", "position_by_batch"}
SOLVER_FORBIDDEN_KEYS = {
    "correct_answer", "primary_target", "verdict", "independent_answer",
    "format_metadata", "intended_answer",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_number(item: dict[str, Any]) -> int:
    order = item["provenance"]["item_generation_order"]
    return ((order - 1) % 25) + 1


def legacy_false_error(item: dict[str, Any]) -> bool:
    clean = item.get("qa_metadata", {}).get("clean_form", "")
    error = item.get("sentence", "")
    return any(
        marker in clean and clean_marker in clean and error_marker in error
        for marker, clean_marker, error_marker in LEGACY_FALSE_ERROR_PATTERNS
    )


def fixture_source_false_errors() -> list[str]:
    """Check the corrected source fixtures without generating items."""

    source = VALIDATION_ROOT / "analysis" / "we_v2_validation" / "run_validation.py"
    text = source.read_text(encoding="utf-8")
    # This is intentionally a source-level fixture check. The old artifact is
    # audited separately; no new cohort is materialized here.
    legacy_error_fragments = (
        "local guides mapped the safest route",
        "the secretary distributed the revised agenda",
    )
    return [fragment for fragment in legacy_error_fragments if fragment in text]


def corrected_view(item: dict[str, Any], answer: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    view = copy.deepcopy(item)
    view["correct_answer"] = answer
    view["grammar_metadata"]["intended_error_position"] = answer
    view["grammar_metadata"]["correct_span_type"] = span_kind(
        diagnostics["span_word_counts"][answer]
    )
    view["format_metadata"]["diagnostics"] = diagnostics
    return view


def audit_items(items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    required_keys = set(REQUIRED_DIAGNOSTIC_KEYS)
    records: list[dict[str, Any]] = []
    corrected_items: list[dict[str, Any]] = []
    # Gate I measures sentence and span geometry, which does not depend on
    # which marked span holds the error.  An item whose key cannot be derived
    # still has valid geometry, so it must stay in the cohort; dropping it
    # would silently shift the medians and band share onto a subset.
    geometry_items: list[dict[str, Any]] = []
    for item in items:
        item_id = item.get("item_id", "?")
        clean = item.get("qa_metadata", {}).get("clean_form")
        error = item.get("sentence")
        marked = item.get("marked_parts")
        location_errors: list[str] = []
        try:
            location = mutation_location(clean, error, marked)
            actual_labels = location["labels"]
            actual_answer = derive_correct_answer(clean, error, marked)
        except Exception as exc:  # pragma: no cover - defensive audit record
            location = {"labels": [], "operations": [], "valid_single_marked_location": False}
            actual_labels = []
            actual_answer = None
            location_errors.append(f"{type(exc).__name__}: {exc}")

        declared_answer = item.get("correct_answer")
        mutation_valid = bool(
            item.get("qa_metadata", {}).get("clean_sentence_validated") is True
            and item.get("qa_metadata", {}).get("error_form") == error
            and isinstance(clean, str)
            and isinstance(error, str)
            and clean != error
            and location.get("valid_single_marked_location") is True
        )

        recomputed_item = copy.deepcopy(item)
        recomputed_diagnostics: dict[str, Any] = {}
        format_errors: list[str] = []
        if actual_answer in LABELS:
            recomputed_item["correct_answer"] = actual_answer
            recomputed_item["grammar_metadata"]["intended_error_position"] = actual_answer
            recomputed_item["grammar_metadata"]["correct_span_type"] = span_kind(
                len(location["span_token_indices"][actual_answer])
            )
            recomputed_diagnostics, format_errors = format_diagnostics(recomputed_item, CONFIG)
            recomputed_item = corrected_view(recomputed_item, actual_answer, recomputed_diagnostics)
            corrected_items.append(recomputed_item)
            geometry_items.append(recomputed_item)
        else:
            geometry_items.append(copy.deepcopy(item))

        declared_diagnostics = item.get("format_metadata", {}).get("diagnostics")
        calculated_old, calculated_old_errors = format_diagnostics(item, CONFIG)
        declared_keys = set(declared_diagnostics) if isinstance(declared_diagnostics, dict) else set()
        calculated_old_keys = set(calculated_old)
        recomputed_keys = set(recomputed_diagnostics)
        diagnostics_complete = declared_keys == required_keys and calculated_old_keys == required_keys
        diagnostics_key_shape = calculated_old_keys == required_keys
        diagnostics_consistent_as_stored = (
            not calculated_old_errors
            and isinstance(declared_diagnostics, dict)
            and declared_diagnostics == calculated_old
        )
        diagnostics_consistent_after_rekey = (
            not format_errors
            and isinstance(declared_diagnostics, dict)
            and declared_diagnostics == recomputed_diagnostics
        )

        record = {
            "item_id": item_id,
            "base_number": base_number(item),
            "declared_correct_answer": declared_answer,
            "actual_mutation_labels": actual_labels,
            "recomputed_correct_answer": actual_answer,
            "actual_error_span": {
                "label": actual_answer if actual_answer in LABELS else None,
                "text": marked.get(actual_answer) if actual_answer in LABELS else None,
                "token_indices": location.get("span_token_indices", {}).get(actual_answer, []),
            },
            "mutation_operations": location.get("operations", []),
            "answer_key_match": actual_answer == declared_answer,
            "mutation_valid": mutation_valid,
            "location_errors": location_errors,
            "format_errors_after_rekey": format_errors,
            "diagnostics": {
                "required_keys": sorted(required_keys),
                "declared_keys": sorted(declared_keys),
                "calculated_keys": sorted(calculated_old_keys),
                "recomputed_keys": sorted(recomputed_keys),
                "complete": diagnostics_complete,
                "key_shape_valid": diagnostics_key_shape,
                "consistent_as_stored": diagnostics_consistent_as_stored,
                "consistent_after_rekey": diagnostics_consistent_after_rekey,
            },
            "legacy_false_error": legacy_false_error(item),
        }
        records.append(record)

    summary = {
        "item_count": len(items),
        "required_diagnostic_keys_source": "REQUIRED_DIAGNOSTIC_KEYS",
        "required_diagnostic_key_count": len(required_keys),
        "schema": {
            "stored_valid": sum(not schema_errors(item, ITEM_SCHEMA) for item in items),
            "recomputed_valid": sum(not schema_errors(item, ITEM_SCHEMA) for item in corrected_items),
        },
        "answer_key_integrity": {
            "declared_vs_actual_match": sum(record["answer_key_match"] for record in records),
            "declared_vs_actual_mismatch": sum(not record["answer_key_match"] for record in records),
            "recomputed_location_count": sum(record["recomputed_correct_answer"] in LABELS for record in records),
        },
        "mutation_validity": {
            "valid": sum(record["mutation_valid"] for record in records),
            "invalid": sum(not record["mutation_valid"] for record in records),
        },
        "diagnostics_integrity": {
            "required_key_shape": sum(record["diagnostics"]["key_shape_valid"] for record in records),
            "complete": sum(record["diagnostics"]["complete"] for record in records),
            "consistent_as_stored": sum(record["diagnostics"]["consistent_as_stored"] for record in records),
            "consistent_after_deterministic_rekey": sum(record["diagnostics"]["consistent_after_rekey"] for record in records),
        },
        "correct_span_distribution": {
            "declared": dict(Counter(
                item.get("format_metadata", {}).get("diagnostics", {}).get("correct_span_type")
                for item in items
            )),
            "recomputed": dict(Counter(
                span_kind(len(record["actual_error_span"]["token_indices"]))
                if record["actual_error_span"]["label"]
                else UNRESOLVED_SPAN_KIND
                for record in records
            )),
        },
        "legacy_false_error_count": sum(record["legacy_false_error"] for record in records),
        "known_bases": {
            "bases": sorted(KNOWN_BASES),
            "item_count": sum(record["base_number"] in KNOWN_BASES for record in records),
            "actual_equals_declared": sum(
                record["base_number"] in KNOWN_BASES and record["answer_key_match"]
                for record in records
            ),
            "records": [
                {
                    "item_id": record["item_id"],
                    "base_number": record["base_number"],
                    "actual_error_span": record["actual_error_span"]["label"],
                    "declared_correct_answer": record["declared_correct_answer"],
                    "match": record["answer_key_match"],
                }
                for record in records
                if record["base_number"] in KNOWN_BASES
            ],
        },
    }
    return summary, records, corrected_items, geometry_items


def independence_audit(items: list[dict[str, Any]], reviews: dict[str, Any], solvers: list[dict[str, Any]]) -> dict[str, Any]:
    blind_records = []
    blind_errors = []
    for item in items:
        try:
            blinded = blind_item(item)
            blind_records.append(blinded)
            if set(blinded) != set(WRITTEN_EXPRESSION_ALLOWLIST):
                blind_errors.append(item.get("item_id", "?"))
        except Exception:
            blind_errors.append(item.get("item_id", "?"))

    review_records = list(reviews.get("round1", [])) + list(reviews.get("round2", []))
    all_replay_records = review_records + solvers
    runtime_values = [
        record.get("provenance", {}).get("runtime_model")
        for record in review_records
        if isinstance(record, dict)
    ] + [record.get("runtime_model") for record in solvers if isinstance(record, dict)]
    runtime_available = any(value for value in runtime_values)
    source_text = (OUT_DIR / "run_validation.py").read_text(encoding="utf-8")
    source_controls = {
        "position_map_removed": "position_by_batch" not in source_text,
        "intended_answer_path_removed": "intended_answer" not in source_text,
        "deterministic_answer_utility_used": "derive_correct_answer" in source_text,
    }
    return {
        "solver_blind_input": {
            "allowlist": list(WRITTEN_EXPRESSION_ALLOWLIST),
            "items": len(blind_records),
            "exact_allowlist_pass": not blind_errors and len(blind_records) == len(items),
            "failures": blind_errors,
        },
        "replay_outputs": {
            "review_records": len(review_records),
            "solver_records": len(solvers),
            "forbidden_intended_answer_fields": [
                record.get("item_id", "?")
                for record in review_records
                if REVIEWER_FORBIDDEN_KEYS.intersection(record)
            ] + [
                record.get("item_id", "?")
                for record in solvers
                if SOLVER_FORBIDDEN_KEYS.intersection(record)
            ],
            "contract_replay_only_records": sum(
                record.get("judgment_mode") == "contract_only_replay"
                for record in all_replay_records
            ),
        },
        "harness_source_controls": source_controls,
        "runtime_available": runtime_available,
        "independence_status": "NOT_EVALUATED" if not runtime_available else "EVALUATED",
        "grammar_quality_evaluable": runtime_available,
        "reason": "No callable live Agent runtime is present; Reviewer/Solver contract replay cannot establish independent grammar quality, consensus quality, or AUTO_ACCEPT quality.",
    }


def run_command(command: list[str], cwd: Path = ROOT, timeout: int = 180) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {
            "command": command,
            "returncode": result.returncode,
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "stdout": result.stdout[-3000:],
            "stderr": result.stderr[-3000:],
        }
    except Exception as exc:  # pragma: no cover
        return {"command": command, "returncode": None, "status": "ERROR", "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}


def run_regression_replay() -> dict[str, Any]:
    tracked_paths = [
        ROOT / "analysis" / "we_v2" / "we_v2_regression.json",
        ROOT / "analysis" / "pilot" / "pilot_p0_hardening_regression.json",
        ROOT / "analysis" / "pilot" / "pilot_provenance.json",
        ROOT / "analysis" / "validation" / "validation_provenance.json",
        ROOT / "analysis" / "manual_review_queue.json",
    ]
    before = {str(path): sha256(path) for path in tracked_paths if path.exists()}
    with tempfile.TemporaryDirectory(prefix=".integrity-replay-", dir=OUT_DIR) as temp_name:
        temp = Path(temp_name)
        paths = {
            "we_v2_regression_artifact": temp / "we_v2_regression_results.json",
            "p0_regression_artifact": temp / "pilot_p0_hardening_regression_results.json",
            "we_v2_smoke_acceptance_artifact": temp / "we_v2_smoke_acceptance.json",
        }
        commands = {
            "we_v2_regression": [sys.executable, "analysis/we_v2/run_regression_contract.py", str(paths["we_v2_regression_artifact"])],
            "p0_regression": [sys.executable, "agents/toefl_itp_grammar_reviewer/scripts/run_p0_hardening_regression.py", str(paths["p0_regression_artifact"])],
            # Discover every test module, not just the contract-boundary one.
            # The integrity and report tests guard this script's own output, so
            # a narrower pattern lets the harness pass while they regress.
            "diagnostics_contract_unittest": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            "we_v2_smoke_acceptance": [sys.executable, "analysis/we_v2/run_smoke_acceptance.py", str(paths["we_v2_smoke_acceptance_artifact"])],
            "orchestrator_acceptance": [sys.executable, "orchestrator/scripts/run_acceptance_tests.py", str(temp)],
            "orchestrator_smoke": [sys.executable, "orchestrator/scripts/run_smoke_test.py", str(temp / "orchestrator_smoke_test.json")],
            "orchestrator_adversarial": [sys.executable, "orchestrator/scripts/run_adversarial_test.py", str(temp / "orchestrator_adversarial_test.json")],
            "orchestrator_reject_path": [sys.executable, "orchestrator/scripts/run_reject_path_test.py", str(temp / "orchestrator_reject_path_test.json")],
        }
        results = {name: run_command(command) for name, command in commands.items()}
        required_artifacts = {
            name: {
                "path": str(path.relative_to(ROOT)),
                "temporary": True,
                "exists": path.exists(),
                "status": "PASS" if path.exists() else "FAIL",
            }
            for name, path in paths.items()
        }
        results.update(required_artifacts)
        required_names = [
            "we_v2_regression", "p0_regression", "diagnostics_contract_unittest",
            "we_v2_smoke_acceptance", "orchestrator_acceptance", "orchestrator_smoke",
            "orchestrator_adversarial", "orchestrator_reject_path",
            "we_v2_regression_artifact", "p0_regression_artifact",
        ]
        results["all_required_pass"] = all(results[name]["status"] == "PASS" for name in required_names)
        results["artifact_presence_gate"] = all(
            results[name]["exists"] for name in ("we_v2_regression_artifact", "p0_regression_artifact")
        )
        results["temporary_output_directory"] = str(temp.relative_to(ROOT))
    after = {str(path): sha256(path) for path in tracked_paths if path.exists()}
    results["tracked_fixture_unchanged"] = before == after
    results["tracked_fixture_hashes_before"] = before
    results["tracked_fixture_hashes_after"] = after
    results["all_required_pass"] = bool(results["all_required_pass"] and results["artifact_presence_gate"] and results["tracked_fixture_unchanged"])
    return results


def _ordered_count_text(
    counts: dict[str, int],
    labels: tuple[str, ...],
    *,
    include_labels: bool = False,
    omit_zero: bool = False,
) -> str:
    values = []
    for label in labels:
        count = counts.get(label, 0)
        if omit_zero and count == 0:
            continue
        values.append(f"{count} {label}" if include_labels else str(count))
    # Any bucket outside `labels` is still reported.  Dropping it silently
    # would make the rendered counts sum to less than the cohort size with no
    # indication that items went unclassified.
    for label in sorted(set(counts) - set(labels)):
        count = counts[label]
        if omit_zero and count == 0:
            continue
        values.append(f"{count} {label}")
    return " / ".join(values) or "0"


def classify_old_metrics(
    summary: dict[str, Any],
    independence: dict[str, Any],
    regression: dict[str, Any],
    geometry: dict[str, Any],
    old_metrics: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Compare the previously published claims with the re-audited results.

    `old_conclusion` must carry what the previous run actually reported, read
    from the stored metrics artifact.  Rendering current values there makes a
    row contradict its own `basis` and destroys the point of the table.  Only
    `status` and `basis` describe the current cohort.
    """

    item_count = summary["item_count"]
    old = old_metrics or {}
    old_core = old.get("core_metrics", {})
    old_defects = old.get("defect_monitoring", {})
    old_geometry = old.get("geometry_gate", {})
    old_total = old_core.get("initial_generated")

    def old_ratio(key: str) -> str:
        value = old_core.get(key)
        if value is None or old_total is None:
            return "not recorded"
        return f"{value}/{old_total}"

    def old_count(key: str) -> str:
        value = old_core.get(key)
        return "not recorded" if value is None else str(value)

    old_band_distribution = _ordered_count_text(
        old_geometry.get("actual", {}).get("worst_band_classification", {}),
        ("EXTREME", "WARNING", "PREFERRED"),
        include_labels=True,
        omit_zero=True,
    ) if old_geometry else "not recorded"
    old_gate_status = (
        "not recorded" if "pass" not in old_geometry
        else ("PASS" if old_geometry["pass"] else "FAIL")
    )
    old_wrong_keys = old_defects.get("wrong_answer_key", {}).get("initial")
    old_wrong_keys_text = (
        "not recorded" if old_wrong_keys is None else f"{old_wrong_keys} wrong keys"
    )
    denominator = str(item_count)
    diagnostics = summary["diagnostics_integrity"]
    answer = summary["answer_key_integrity"]
    mutation = summary["mutation_validity"]
    declared_span_distribution = _ordered_count_text(
        summary["correct_span_distribution"]["declared"],
        ("SINGLE_WORD", "SHORT_PHRASE", "CLAUSE_OR_CLAUSE_LIKE"),
    )
    recomputed_span_distribution = _ordered_count_text(
        summary["correct_span_distribution"]["recomputed"],
        ("SINGLE_WORD", "SHORT_PHRASE", "CLAUSE_OR_CLAUSE_LIKE"),
    )
    band_distribution = _ordered_count_text(
        geometry.get("actual", {}).get("worst_band_classification", {}),
        ("EXTREME", "WARNING", "PREFERRED"),
        include_labels=True,
        omit_zero=True,
    )
    gate_status = "PASS" if geometry["pass"] else "FAIL"
    return [
        {"metric": "generator schema", "old_conclusion": old_ratio("generator_schema_pass"), "status": "VALID", "basis": f"Stored items and deterministic schema recheck both pass for the current {denominator}-item cohort."},
        {"metric": "diagnostics completeness", "old_conclusion": old_ratio("diagnostics_complete"), "status": "RECOMPUTED", "basis": "Required key set is sourced dynamically from REQUIRED_DIAGNOSTIC_KEYS and compared with calculated keys."},
        {"metric": "diagnostics consistency", "old_conclusion": old_ratio("diagnostics_consistent"), "status": "RECOMPUTED", "basis": f"Stored-key consistency is {diagnostics['consistent_as_stored']}/{denominator}; after deterministic re-key it is {diagnostics['consistent_after_deterministic_rekey']}/{denominator}."},
        {"metric": "format geometry", "old_conclusion": f"Gate I {old_gate_status}", "status": "RECOMPUTED", "basis": f"Recomputed from actual spans; Gate I is {gate_status} with the distance axis included."},
        {"metric": "format bands", "old_conclusion": old_band_distribution, "status": "RECOMPUTED", "basis": f"Current corrected-cohort worst-band distribution is {band_distribution}."},
        {"metric": "correct-span distribution", "old_conclusion": declared_span_distribution, "status": "RECOMPUTED", "basis": f"Correct span is selected from actual mutation location; current recomputed distribution is {recomputed_span_distribution}."},
        {"metric": "answer-key integrity", "old_conclusion": old_wrong_keys_text, "status": "INVALID", "basis": f"Deterministic audit finds {answer['declared_vs_actual_mismatch']} stored-key mismatches in the current cohort; the previous zero count is invalidated."},
        {"metric": "mutation validity", "old_conclusion": f'{old_ratio("initial_generated")} implied', "status": "RECOMPUTED", "basis": f"Structural clean/error mutation and single marked location pass {mutation['valid']}/{denominator}."},
        {"metric": "Reviewer grammar quality", "old_conclusion": f'{old_count("reviewer_round1_grammar_PASS")} PASS', "status": "NOT_EVALUATED", "basis": independence["reason"]},
        {"metric": "Solver consensus / AUTO_ACCEPT quality", "old_conclusion": f'{old_count("solver_consensus")} agreement / {old_count("AUTO_ACCEPT")} AUTO_ACCEPT', "status": "NOT_EVALUATED", "basis": independence["reason"]},
        {"metric": "regression integrity", "old_conclusion": "PASS", "status": "VALID" if regression["all_required_pass"] else "INVALID", "basis": "WE/P0 artifacts are required temporary gate outputs; tracked fixtures are hash-unchanged."},
        {"metric": "format drift conclusion", "old_conclusion": "Recalibration required", "status": "VALID" if not geometry["pass"] else "INVALID", "basis": f"Current Gate I result is {gate_status}; sentence length, coverage, unmarked context, gaps, worst-band share, and distance are evaluated from the current cohort."},
        {"metric": "human blind-review quality conclusion", "old_conclusion": "pending", "status": "NOT_EVALUATED", "basis": "No human labels or live Agent grammar judgments were added by this re-audit."},
    ]


def render_report(audit: dict[str, Any]) -> str:
    summary = audit["items"]
    item_count = summary["item_count"]
    known = summary["known_bases"]
    diag = summary["diagnostics_integrity"]
    answer = summary["answer_key_integrity"]
    mutation = summary["mutation_validity"]
    geometry = audit["format"]["gate_i"]
    independence = audit["independence"]
    regression = audit["regression"]
    known_base_text = ", ".join(str(base) for base in known["bases"])
    lines = [
        "# WE v2 Validation Integrity Re-audit",
        "",
        f"- Status: **SUPERSEDES** `WE_V2_VALIDATION_REPORT.md`; the old report is retained.",
        f"- Run ID: `{RUN_ID}`; source cohort: existing `we_v2_validation_initial_items.json` only.",
        f"- New {item_count}-item generation: **NOT RUN**. No replacement candidates were generated.",
        "- Runtime mode: **CONTRACT_REPLAY_ONLY**; grammar-quality metrics are excluded.",
        "",
        "## Executive result",
        "",
        f"- Wrong-key count: old stored declaration **{answer['declared_vs_actual_mismatch']}/{item_count}** mismatched actual mutation; corrected deterministic derivation resolves **{answer['recomputed_location_count']}/{item_count}** locations.",
        f"- False-error fixture count: old artifact **{summary['legacy_false_error_count']}**; corrected source fixture scan **{audit['fixture_fix']['source_false_error_count']}**.",
        f"- Known bases {known_base_text}: actual error span equals stored `correct_answer` **{known['actual_equals_declared']}/{known['item_count']}**.",
        f"- Answer-key integrity of the stored old artifact: **{answer['declared_vs_actual_match']}/{item_count}**; recomputed answer-key integrity: **{answer['recomputed_location_count']}/{item_count}**.",
        f"- Diagnostics key integrity: required/calc key shape **{diag['required_key_shape']}/{item_count}**; complete **{diag['complete']}/{item_count}**; consistent after deterministic re-key **{diag['consistent_after_deterministic_rekey']}/{item_count}**.",
        f"- Regression integrity: **{'PASS' if regression['all_required_pass'] else 'FAIL'}**; WE/P0 artifact-presence gate **{'PASS' if regression['artifact_presence_gate'] else 'FAIL'}**.",
        f"- Gate I integrity: **{'PASS' if geometry['pass'] else 'FAIL'}**. "
        + ("Format drift conclusion is maintained." if not geometry["pass"] else "The previous format drift conclusion is superseded by this result."),
        "",
        "## Integrity checks",
        "",
        "### Mutation and answer-key integrity",
        "",
        "`correct_answer` is now derived from a clean/error token-and-separator diff plus error-side marked-span alignment. The hand-written position map was removed from the validation generator path.",
        "",
        "| Check | Result |",
        "|---|---:|",
        f"| Stored key equals actual mutation | {answer['declared_vs_actual_match']}/{item_count} |",
        f"| Actual mutation resolves to one marked span | {answer['recomputed_location_count']}/{item_count} |",
        f"| Structural mutation validity | {mutation['valid']}/{item_count} |",
        f"| Known bases {known_base_text} | {known['actual_equals_declared']}/{known['item_count']} |",
        "",
        "Known-base records were checked individually in `we_v2_validation_integrity_reaudit.json`.",
        "",
        "### Diagnostics and format geometry",
        "",
        f"Required diagnostic keys are read from `REQUIRED_DIAGNOSTIC_KEYS` at runtime ({summary['required_diagnostic_key_count']} keys); actual calculated keys are compared as sets. No diagnostic-key list is hard-coded in the re-audit completeness calculation.",
        "",
        f"- Key shape: {diag['required_key_shape']}/{item_count}.",
        f"- Complete: {diag['complete']}/{item_count}.",
        f"- Stored diagnostics consistent with old declared key: {diag['consistent_as_stored']}/{item_count}.",
        f"- Recomputed diagnostics consistent after actual-key re-derivation: {diag['consistent_after_deterministic_rekey']}/{item_count}.",
        "",
        "Gate I required axes:",
        "",
        "| Axis | Result |",
        "|---|---|",
    ]
    for axis, passed in geometry["axes"].items():
        lines.append(f"| {axis} | {'PASS' if passed else 'FAIL'} |")
    lines += [
        "",
        f"- Recomputed worst-band distribution: `{audit['format']['bands']}`.",
        f"- Recomputed correct-span distribution: `{summary['correct_span_distribution']['recomputed']}`; old declared distribution: `{summary['correct_span_distribution']['declared']}`.",
        "- Sentence length, coverage, unmarked context, A-B/B-C/C-D gaps, holistic format distance, and worst-band share are all Gate I inputs.",
        "",
        "### Reviewer/Solver independence",
        "",
        f"- Solver blind allowlist boundary: **{'PASS' if independence['solver_blind_input']['exact_allowlist_pass'] else 'FAIL'}** ({independence['solver_blind_input']['items']} items).",
        f"- Harness source controls: `{independence['harness_source_controls']}`.",
        f"- Runtime available: **{independence['runtime_available']}**.",
        "- The existing Reviewer/Solver files are contract-shaped replay outputs. Their answer agreement is not treated as independent judgment evidence.",
        "",
        "### False-error fixture correction",
        "",
        f"The old artifact contains {summary['legacy_false_error_count']} `before/by the time/when + simple past` false-error cases. The source fixture was changed to unambiguous non-finite/tense errors; corrected source scan reports {audit['fixture_fix']['source_false_error_count']}. The old JSON artifact remains historical evidence and was not silently regenerated.",
        "",
        "### Regression replay integrity",
        "",
        f"- Replay output directory: temporary (`{regression['temporary_output_directory']}`).",
        f"- WE regression artifact present: **{regression['we_v2_regression_artifact']['exists']}**.",
        f"- P0 regression artifact present: **{regression['p0_regression_artifact']['exists']}**.",
        f"- Tracked fixture hashes unchanged: **{regression['tracked_fixture_unchanged']}**.",
        "- Missing WE/P0 artifact would make Gate B FAIL.",
        "",
        "## Old-report metric disposition",
        "",
        "| Old metric/conclusion | Status | Re-audit disposition |",
        "|---|---|---|",
    ]
    for metric in audit["metric_disposition"]:
        lines.append(f"| {metric['metric']} ({metric['old_conclusion']}) | **{metric['status']}** | {metric['basis']} |")
    lines += [
        "",
        "Status meanings: `VALID` = still supported; `INVALID` = contradicted; `RECOMPUTED` = numerical conclusion must be replaced by this audit; `NOT_EVALUATED` = no defensible conclusion under CONTRACT_REPLAY_ONLY.",
        "",
        "## Final decisions",
        "",
        f"- Grammar-quality metrics evaluable: **{independence['grammar_quality_evaluable']}**. Reviewer grammar quality, Solver consensus quality, and AUTO_ACCEPT quality are excluded.",
        f"- Format drift conclusion maintained: **{'YES' if not geometry['pass'] else 'NO'}** — Gate I is {'FAIL' if not geometry['pass'] else 'PASS'}, with the recalibrated geometry check explicitly including holistic format distance.",
        # The trailing clause must follow the computed gate.  Stating an
        # unresolved gate while the bullets above report PASS makes the
        # rendered report contradict its own JSON result.
        f"- New {item_count}-item Validation should be re-run now: **NO**. First correct/re-key the historical cohort or regenerate only after the fixture fix, and provide an actual Agent runtime for grammar-quality evidence"
        + ("; the current format drift gate also remains unresolved." if not geometry["pass"] else "; the current format drift gate now passes."),
        "",
        "## Retained artifacts",
        "",
        "- Historical report retained with superseded/invalidated status: `WE_V2_VALIDATION_REPORT.md`.",
        "- Re-audit data: `we_v2_validation_integrity_reaudit.json`.",
        "- This report: `WE_V2_VALIDATION_INTEGRITY_REAUDIT.md`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    data = read_json(ITEMS_PATH)
    items = data["items"] if isinstance(data, dict) else data
    if not isinstance(items, list) or len(items) != 75:
        raise RuntimeError(f"expected existing 75-item cohort, got {len(items) if isinstance(items, list) else 'invalid'}")

    summary, records, corrected_items, geometry_items = audit_items(items)
    reviews = read_json(REVIEWS_PATH)
    solvers_data = read_json(SOLVER_PATH)
    solvers = solvers_data["items"] if isinstance(solvers_data, dict) else solvers_data
    independence = independence_audit(items, reviews, solvers)

    plan_path = OUT_DIR / "we_v2_validation_plans.json"
    plan_data = read_json(plan_path)
    format_report = format_analysis(geometry_items, plan_data)
    gate_i = geometry_gate_status(format_report)
    regression = run_regression_replay()
    source_false_errors = fixture_source_false_errors()
    fixture_fix = {
        "old_artifact_false_error_count": summary["legacy_false_error_count"],
        "source_false_error_patterns_remaining": source_false_errors,
        "source_false_error_count": len(source_false_errors),
        "existing_artifact_rewritten": False,
    }

    audit = {
        "run_id": RUN_ID,
        "status": "SUPERSEDES_OLD_REPORT",
        "scope": {
            "source_items": str(ITEMS_PATH.relative_to(ROOT)),
            "item_count": len(items),
            "new_75_generated": False,
            "replacement_generation": False,
            "runtime_mode": "CONTRACT_REPLAY_ONLY",
        },
        "items": summary,
        "item_records": records,
        "format": {
            "bands": format_report["format_axes"]["worst_band_classification"],
            "corrected_cohort": format_report["cohort"],
            "gate_i": gate_i,
            "required_gate_i_axes": [
                "sentence_word_count", "marked_coverage_ratio", "unmarked_word_count",
                "gap_A_B", "gap_B_C", "gap_C_D", "format_distance_median", "worst_band_status",
            ],
        },
        "fixture_fix": fixture_fix,
        "independence": independence,
        "regression": regression,
    }
    audit["metric_disposition"] = classify_old_metrics(
        summary, independence, regression, gate_i, read_json(OLD_METRICS_PATH)
    )
    write_json(AUDIT_JSON_PATH, audit)
    AUDIT_REPORT_PATH.write_text(render_report(audit), encoding="utf-8")
    print(json.dumps({
        "run_id": RUN_ID,
        "items": len(items),
        "wrong_key_before": summary["answer_key_integrity"]["declared_vs_actual_mismatch"],
        "wrong_key_after": 0 if summary["answer_key_integrity"]["recomputed_location_count"] == len(items) else len(items) - summary["answer_key_integrity"]["recomputed_location_count"],
        "false_error_before": summary["legacy_false_error_count"],
        "false_error_after_source_fix": fixture_fix["source_false_error_count"],
        "grammar_quality_evaluable": independence["grammar_quality_evaluable"],
        "regression": regression["all_required_pass"],
        "gate_i": gate_i["pass"],
    }, ensure_ascii=False))
    return 0 if regression["all_required_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
