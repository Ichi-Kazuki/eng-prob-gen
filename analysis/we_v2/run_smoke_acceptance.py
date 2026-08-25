#!/usr/bin/env python3
"""Run the bounded WE v2 Smoke acceptance checks A-H."""

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))
from validate_format import load_json, load_items, validate_item  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load validator module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVIEWER_VALIDATOR = load_module(
    "we_v2_reviewer_validator",
    ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "scripts" / "validate_output.py",
)
SOLVER_VALIDATOR = load_module(
    "we_v2_solver_validator",
    ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts" / "validate_output.py",
)


def main(output_path: Path | None = None) -> int:
    output_path = output_path or ROOT / "analysis" / "we_v2" / "we_v2_smoke_acceptance.json"
    items_path = ROOT / "analysis" / "we_v2" / "we_v2_smoke_items.json"
    review_path = ROOT / "analysis" / "we_v2" / "we_v2_smoke_review.json"
    solver_path = ROOT / "analysis" / "we_v2" / "we_v2_smoke_solver.json"
    config = load_json(ROOT / "agents" / "toefl_itp_we_generator_v2" / "config" / "we_v2_format_config.json")
    grammar = load_json(ROOT / "specs" / "toefl_itp_grammar_spec.json")
    taxonomy = load_json(ROOT / "analysis" / "grammar_taxonomy.json")
    targets = {x["id"] for x in taxonomy["primary_targets"]}
    error_types = {x["id"] for x in grammar["tested_error_types"] if x["id"] not in {"fragment", "wrong_complementation"}}
    items = load_items(items_path)
    reviews = load_items(review_path)
    solvers = load_items(solver_path)
    by_id = {item["item_id"]: item for item in items if isinstance(item, dict) and "item_id" in item}
    review_by_id = {item["item_id"]: item for item in reviews if isinstance(item, dict) and "item_id" in item}
    solver_by_id = {item["item_id"]: item for item in solvers if isinstance(item, dict) and "item_id" in item}
    item_ids = [item.get("item_id") if isinstance(item, dict) else None for item in items]
    review_ids = [item.get("item_id") if isinstance(item, dict) else None for item in reviews]
    solver_ids = [item.get("item_id") if isinstance(item, dict) else None for item in solvers]
    item_id_set = set(item_ids)

    def exact_dependent_ids(ids: list[object]) -> bool:
        return (
            len(items) > 0
            and len(ids) == len(items)
            and all(isinstance(item_id, str) for item_id in ids)
            and len(set(ids)) == len(ids)
            and len(set(item_ids)) == len(item_ids)
            and set(ids) == item_id_set
        )

    review_contract_errors = [
        REVIEWER_VALIDATOR.validate_contract(item)
        for item in reviews
    ]
    solver_contract_errors: list[list[str]] = []
    for item in solvers:
        errors: list[str] = []
        if not isinstance(item, dict):
            errors.append("item must be an object")
        else:
            SOLVER_VALIDATOR.validate_contract(item, errors)
        solver_contract_errors.append(errors)
    dependencies_complete = exact_dependent_ids(review_ids) and exact_dependent_ids(solver_ids)
    reviews_valid = dependencies_complete and all(not errors for errors in review_contract_errors)
    solvers_valid = dependencies_complete and all(not errors for errors in solver_contract_errors)

    checks: list[dict] = []
    def check(code: str, description: str, passed: bool, detail: str) -> None:
        checks.append({"id": code, "description": description, "passed": passed, "detail": detail})

    validation = [validate_item(item, config, targets, error_types) for item in items]
    check("A", "schema/contract and deterministic geometry valid", all(result["valid"] for result in validation), f"{sum(result['valid'] for result in validation)}/{len(validation)}")
    check("B", "exactly four aligned spans", all(set(item["marked_parts"]) == {"A", "B", "C", "D"} and item["format_metadata"]["diagnostics"]["format_band_status"] in {"PREFERRED", "WARNING"} for item in items), "all items have A/B/C/D and no EXTREME band")
    review_one_error_count = sum(
        isinstance(review, dict) and review.get("detected_error_count") == 1
        for review in reviews
    )
    check(
        "C",
        "exactly one genuine error recorded by independent review",
        reviews_valid and all(
            review["detected_error_count"] == 1 and review["grammar_validity"] == "PASS"
            for review in reviews
        ),
        f"{review_one_error_count}/{len(reviews)}; complete IDs and reviewer contract required",
    )
    review_matches = sum(
        isinstance(review, dict)
        and review.get("item_id") in by_id
        and review.get("answer_match") is True
        and review.get("independent_answer") == by_id[review["item_id"]].get("correct_answer")
        and review.get("answer_match") == (
            review.get("independent_answer") == review.get("generator_answer")
        )
        for review in reviews
    )
    check(
        "D",
        "Reviewer independent answer matches Generator",
        reviews_valid and review_matches == len(items),
        f"{review_matches}/{len(items)}; exact reviewer ID set and contract required",
    )
    solver_matches = sum(
        isinstance(solver, dict)
        and solver.get("item_id") in by_id
        and solver.get("solver_answer") == by_id[solver["item_id"]].get("correct_answer")
        for solver in solvers
    )
    check(
        "E",
        "existing blind Solver consensus",
        solvers_valid and solver_matches == len(items),
        f"{solver_matches}/{len(items)}; exact solver ID set and contract required",
    )

    official = load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")["summary"]["all"]
    diagnostics = [item["format_metadata"]["diagnostics"] for item in items]
    checks_in_official_range = all([
        min(x["sentence_word_count"] for x in load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")["items"]) <= statistics_median([d["sentence_word_count"] for d in diagnostics]) <= max(x["sentence_word_count"] for x in load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")["items"]),
        min(x["marked_coverage_ratio"] for x in load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")["items"]) <= statistics_median([d["marked_coverage_ratio"] for d in diagnostics]) <= max(x["marked_coverage_ratio"] for x in load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")["items"]),
        all(d["format_band_status"] != "EXTREME" for d in diagnostics),
    ])
    check("F", "geometry remains within official observed item-level ranges", checks_in_official_range, "no EXTREME band; sentence and coverage medians within official min/max")
    check("G", "100% marked coverage is absent", all(d["marked_coverage_ratio"] < 1.0 for d in diagnostics), f"count={sum(d['marked_coverage_ratio'] == 1.0 for d in diagnostics)}")
    check("H", "zero unmarked context is absent", all(d["unmarked_word_count"] > 0 for d in diagnostics), f"count={sum(d['unmarked_word_count'] == 0 for d in diagnostics)}")

    report = {"suite": "WE v2 smoke acceptance A-H", "item_count": len(items), "passed": all(c["passed"] for c in checks), "checks": checks}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for result in checks:
        print(f"[{ 'PASS' if result['passed'] else 'FAIL' }] {result['id']} {result['description']} -- {result['detail']}")
    print(f"Smoke acceptance: {sum(c['passed'] for c in checks)}/{len(checks)}")
    return 0 if report["passed"] else 1


def statistics_median(values: list[float]) -> float:
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python run_smoke_acceptance.py [output-path]")
    raise SystemExit(main(output))
