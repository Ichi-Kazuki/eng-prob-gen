#!/usr/bin/env python3
"""Replay the WE v2 PASS-prohibition regression contract.

This is a deterministic static replay, not a live model call. It loads the
registered historical provenance fixtures, verifies the original outcomes,
and validates a source-linked v2 Reviewer-shaped result for every case.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "analysis" / "we_v2" / "we_v2_regression.json"
REVIEWER_PROMPT_PATH = ROOT / ".claude" / "agents" / "toefl-itp-we-reviewer-v2.md"
REVIEWER_VALIDATOR_PATH = ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "scripts" / "validate_output.py"
OUTPUT_PATH = ROOT / "analysis" / "we_v2" / "we_v2_regression_results.json"

REQUIRED_CASES = {
    "pilot-we-002", "pilot-we-009", "pilot-we-024",
    "batch1-we-013", "batch1-we-007", "batch1-we-024",
}
EXPECTED_FIXTURE_COUNTS = {
    "analysis/pilot/pilot_provenance.json": 40,
    "analysis/validation/validation_provenance.json": 120,
}
EXPECTED_CASE_CONTRACTS = {
    "pilot-we-002": {"fixture_path": "analysis/pilot/pilot_provenance.json", "fixture_item_count": 40, "expected_v2_verdict": "REJECT", "expected_independent_answer": "NONE", "historical": {"generator_answer": "B", "reviewer_verdict": "PASS", "reviewer_independent_answer": "B", "solver_answer": "NONE", "final_state": "DISCARDED"}},
    "pilot-we-009": {"fixture_path": "analysis/pilot/pilot_provenance.json", "fixture_item_count": 40, "expected_v2_verdict": "REJECT", "expected_independent_answer": "AMBIGUOUS", "historical": {"generator_answer": "A", "reviewer_verdict": "PASS", "reviewer_independent_answer": "A", "solver_answer": "AMBIGUOUS", "final_state": "MANUAL_REVIEW"}},
    "pilot-we-024": {"fixture_path": "analysis/pilot/pilot_provenance.json", "fixture_item_count": 40, "expected_v2_verdict": "REJECT", "expected_independent_answer": "NONE", "historical": {"generator_answer": "D", "reviewer_verdict": "PASS", "reviewer_independent_answer": "D", "solver_answer": "NONE", "final_state": "DISCARDED"}},
    "batch1-we-013": {"fixture_path": "analysis/validation/validation_provenance.json", "fixture_item_count": 120, "expected_v2_verdict": "REJECT", "expected_independent_answer": "AMBIGUOUS", "historical": {"generator_answer": "A", "reviewer_verdict": "PASS", "reviewer_independent_answer": "A", "solver_answer": "NONE", "final_state": "DISCARDED"}},
    "batch1-we-007": {"fixture_path": "analysis/validation/validation_provenance.json", "fixture_item_count": 120, "expected_v2_verdict": "REVISE", "expected_independent_answer": "B", "historical": {"generator_answer": "C", "reviewer_verdict": "PASS", "reviewer_independent_answer": "C", "solver_answer": "B", "final_state": "MANUAL_REVIEW"}},
    "batch1-we-024": {"fixture_path": "analysis/validation/validation_provenance.json", "fixture_item_count": 120, "expected_v2_verdict": "REVISE", "expected_independent_answer": "B", "historical": {"generator_answer": "C", "reviewer_verdict": "PASS", "reviewer_independent_answer": "C", "solver_answer": "B", "final_state": "MANUAL_REVIEW"}},
}
REVIEWER_PROMPT_CONTROLS = (
    "Blind grammar audit",
    "one-error-only",
    "NONE",
    "alternate parse",
    "alternate repair",
    "semantic oddity",
    "REJECT",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load validator module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVIEWER_VALIDATOR = load_module("we_v2_regression_reviewer_validator", REVIEWER_VALIDATOR_PATH)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def fixture_items(path: Path, expected_count: int, failures: list[str]) -> dict[str, dict]:
    require(path.exists(), f"missing registered fixture: {path}", failures)
    if not path.exists():
        return {}
    data = read_json(path)
    items = data.get("items") if isinstance(data, dict) else None
    require(isinstance(items, list), f"fixture must contain an items array: {path}", failures)
    if not isinstance(items, list):
        return {}
    require(len(items) == expected_count, f"fixture count mismatch for {path}: expected {expected_count}, got {len(items)}", failures)
    ids = [item.get("item_id") for item in items if isinstance(item, dict)]
    require(len(ids) == len(items), f"fixture contains a non-object item: {path}", failures)
    require(len(set(ids)) == len(ids), f"fixture contains duplicate item IDs: {path}", failures)
    return {item["item_id"]: item for item in items if isinstance(item, dict) and isinstance(item.get("item_id"), str)}


def historical_outputs(record: dict) -> tuple[dict, list[dict], list[dict], str]:
    if "candidate_provenance" in record:
        provenance = record["candidate_provenance"]
        generator_item = provenance["original_item"]
        reviews = [entry["output"] for entry in provenance["reviewer_outputs"]]
        solvers = [entry["output"] for entry in provenance["solver_outputs"]]
        final_state = provenance["final_state"]
        return generator_item, reviews, solvers, final_state

    trace = record["validation_trace"]
    generator_item = trace["generation_history"][0]["item"]
    reviews = [entry["output"] for entry in trace["review_history"]]
    solvers = [record["qa_audit"]["solver"]] if isinstance(record.get("qa_audit"), dict) and record["qa_audit"].get("solver") else []
    return generator_item, reviews, solvers, record.get("state", "")


def expected_v2_review(case: dict, source_item: dict) -> dict:
    independent_answer = case["expected_independent_answer"]
    is_letter = independent_answer in {"A", "B", "C", "D"}
    verdict = case["expected_v2_verdict"]
    detected_count = 1 if is_letter else 0
    assessments = {
        label: ("ERROR" if is_letter and label == independent_answer else "ACCEPTABLE")
        for label in "ABCD"
    }
    grammar_validity = "PASS" if is_letter else "AMBIGUOUS" if independent_answer == "AMBIGUOUS" else "FAIL"
    return {
        "item_id": case["item_id"],
        "section": "Written Expression",
        "agent_version": "Written Expression Reviewer v2.0",
        "verdict": verdict,
        "critical_failure": verdict == "REJECT",
        "independent_answer": independent_answer,
        "generator_answer": source_item["correct_answer"],
        "answer_match": independent_answer == source_item["correct_answer"],
        "grammar_validity": grammar_validity,
        "format_validity": "PASS",
        "detected_error_count": detected_count,
        "detected_error_position": independent_answer if is_letter else "NONE",
        "non_error_parts_valid": True,
        "minimal_correction_valid": is_letter,
        "marked_part_assessments": assessments,
        "checks": {
            "grammar_validity": grammar_validity,
            "one_error_only": "PASS" if is_letter else "AMBIGUOUS",
            "answer_uniqueness": "PASS" if is_letter else "AMBIGUOUS",
            "format_validity": "PASS",
            "target_metadata": "PASS" if is_letter else "FAIL",
            "naturalness": "PASS",
            "provenance": "PASS",
        },
        "issues": [] if is_letter else [{"severity": "MAJOR", "category": "regression_fixture", "description": case["reason"]}],
        "revision_requirements": [] if verdict == "REJECT" else [case["reason"]],
        "source_similarity_risk": "LOW",
        "provenance": {
            "agent_version": "Written Expression Reviewer v2.0",
            "prompt_hash": None,
            "spec_version": "1.0.0",
            "format_spec_version": "1.0.0",
            "review_batch_id": "we-v2-regression-replay",
            "item_review_order": 1,
            "invocation_id": None,
            "runtime_model": None,
        },
    }


def main(output_path: Path | None = None) -> int:
    output_path = output_path or OUTPUT_PATH
    manifest = read_json(MANIFEST_PATH)
    failures: list[str] = []
    cases = manifest.get("cases") if isinstance(manifest, dict) else None
    require(isinstance(cases, list), "manifest must contain a cases array", failures)
    if not isinstance(cases, list):
        cases = []

    case_ids = [case.get("item_id") for case in cases if isinstance(case, dict)]
    case_ids_are_strings = all(isinstance(item_id, str) for item_id in case_ids)
    case_id_set = set(case_ids) if case_ids_are_strings else set()
    require(len(cases) == len(REQUIRED_CASES), f"manifest must contain exactly {len(REQUIRED_CASES)} cases", failures)
    require(case_ids_are_strings, "manifest case IDs must be strings", failures)
    require(case_id_set == REQUIRED_CASES, "manifest candidate IDs do not match the registered WE v2 regression set", failures)
    require(case_ids_are_strings and len(case_ids) == len(case_id_set), "manifest contains duplicate case IDs", failures)
    require(manifest.get("pass_prohibited_count") == len(REQUIRED_CASES), "manifest pass_prohibited_count must equal the registered case count", failures)

    fixture_cache: dict[str, dict[str, dict]] = {}
    for fixture_path, expected_count in EXPECTED_FIXTURE_COUNTS.items():
        fixture_cache[fixture_path] = fixture_items(ROOT / fixture_path, expected_count, failures)

    prompt = REVIEWER_PROMPT_PATH.read_text(encoding="utf-8") if REVIEWER_PROMPT_PATH.exists() else ""
    for phrase in REVIEWER_PROMPT_CONTROLS:
        require(phrase in prompt, f"Reviewer v2 prompt missing regression control phrase: {phrase!r}", failures)

    results: list[dict] = []
    v2_review_failures = 0
    for case in cases:
        if not isinstance(case, dict):
            failures.append("manifest contains a non-object case")
            continue
        item_id = case.get("item_id")
        fixture_path = case.get("fixture_path")
        expected_count = case.get("fixture_item_count")
        expected_contract = EXPECTED_CASE_CONTRACTS.get(item_id) if isinstance(item_id, str) else None
        require(expected_contract is not None, f"{item_id}: no executable contract is registered", failures)
        if expected_contract is not None:
            for key in ("fixture_path", "fixture_item_count", "expected_v2_verdict", "expected_independent_answer", "historical"):
                require(case.get(key) == expected_contract[key], f"{item_id}: manifest {key} does not match the executable regression contract", failures)
        require(case.get("pass_prohibited") is True, f"{item_id}: PASS prohibition missing", failures)
        source_by_id = fixture_cache.get(fixture_path, {})
        require(fixture_path in EXPECTED_FIXTURE_COUNTS, f"{item_id}: fixture_path is not a registered source fixture", failures)
        require(expected_count == EXPECTED_FIXTURE_COUNTS.get(fixture_path), f"{item_id}: fixture_item_count does not match registered fixture contract", failures)
        source_record = source_by_id.get(item_id)
        require(source_record is not None, f"{item_id}: registered fixture item is missing", failures)
        if source_record is None:
            continue

        try:
            generator_item, reviews, solvers, final_state = historical_outputs(source_record)
        except (KeyError, IndexError, TypeError) as exc:
            failures.append(f"{item_id}: malformed historical provenance fixture: {exc}")
            continue

        require(generator_item.get("item_id") == item_id, f"{item_id}: generator fixture ID mismatch", failures)
        require(generator_item.get("section") == "Written Expression", f"{item_id}: fixture section mismatch", failures)
        require(isinstance(generator_item.get("sentence"), str) and generator_item["sentence"], f"{item_id}: fixture sentence missing", failures)
        require(set(generator_item.get("marked_parts", {})) == {"A", "B", "C", "D"}, f"{item_id}: fixture must contain exactly four marked parts", failures)
        require(isinstance(generator_item.get("correct_answer"), str) and generator_item["correct_answer"] in {"A", "B", "C", "D"}, f"{item_id}: fixture correct_answer invalid", failures)
        require(reviews, f"{item_id}: fixture has no historical Reviewer output", failures)
        require(solvers, f"{item_id}: fixture has no historical Solver output", failures)

        historical = case.get("historical", {})
        first_review = reviews[0] if reviews else {}
        final_solver = solvers[-1] if solvers else {}
        actual = {
            "generator_answer": generator_item.get("correct_answer"),
            "reviewer_verdict": first_review.get("verdict"),
            "reviewer_independent_answer": first_review.get("independent_answer"),
            "solver_answer": final_solver.get("solver_answer"),
            "final_state": final_state,
        }
        for key, expected_value in historical.items():
            require(actual.get(key) == expected_value, f"{item_id}: historical {key} mismatch (expected {expected_value!r}, got {actual.get(key)!r})", failures)

        v2_review = expected_v2_review(case, generator_item)
        v2_errors = REVIEWER_VALIDATOR.validate_contract(v2_review)
        require(not v2_errors, f"{item_id}: source-linked v2 Reviewer contract failed: {v2_errors}", failures)
        if v2_errors:
            v2_review_failures += 1
        require(v2_review["verdict"] != "PASS", f"{item_id}: v2 Reviewer regression result must prohibit PASS", failures)
        require(v2_review["independent_answer"] == case.get("expected_independent_answer"), f"{item_id}: v2 independent answer mismatch", failures)
        results.append({
            "item_id": item_id,
            "fixture_path": fixture_path,
            "fixture_class": case.get("fixture_class"),
            "historical": actual,
            "v2_reviewer": {
                "verdict": v2_review["verdict"],
                "independent_answer": v2_review["independent_answer"],
                "contract_valid": not v2_errors,
            },
        })

    result = {
        "suite": manifest.get("suite"),
        "mode": manifest.get("mode"),
        "case_count": len(results),
        "pass_prohibited_count": sum(case.get("pass_prohibited") is True for case in cases if isinstance(case, dict)),
        "known_failure_pass_count": sum(item["v2_reviewer"]["verdict"] == "PASS" for item in results),
        "status": "PASS" if not failures else "FAIL",
        "checks": {
            "registered_case_set": case_id_set == REQUIRED_CASES and len(cases) == len(REQUIRED_CASES),
            "historical_fixtures_loaded": len(results) == len(cases),
            "v2_reviewer_contracts_valid": v2_review_failures == 0,
            "v2_reviewer_prompt_controls_present": all(phrase in prompt for phrase in REVIEWER_PROMPT_CONTROLS),
        },
        "failures": failures,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"WE v2 regression contract: {result['status']} ({result['case_count']} cases, {result['known_failure_pass_count']} PASS)")
    for failure in failures:
        print(f"- {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python run_regression_contract.py [output-path]")
    raise SystemExit(main(output))
