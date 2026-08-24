"""P0 Generator/Reviewer hardening regression contract.

This test does not call a live model and does not alter Solver or Orchestrator
behavior. It verifies that:

* the seven Pilot candidates remain registered as regression fixtures;
* the historical provenance still contains the expected original/revised
  Reviewer and Solver outcomes;
* the three final failures have a post-hardening PASS prohibition; and
* the v1.1 construction-safety and review-phase controls are present in the
  runtime agent definitions.

The original Pilot item text is resolved from pilot_provenance.json rather than
copied into a new generation template.
"""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "analysis" / "pilot" / "pilot_p0_hardening_regression.json"
PROVENANCE_PATH = REPO_ROOT / "analysis" / "pilot" / "pilot_provenance.json"
GENERATOR_PROMPT = REPO_ROOT / ".claude" / "agents" / "toefl-itp-grammar-generator.md"
REVIEWER_PROMPT = REPO_ROOT / ".claude" / "agents" / "toefl-itp-grammar-reviewer.md"
OUTPUT_PATH = REPO_ROOT / "analysis" / "pilot" / "pilot_p0_hardening_regression_results.json"


def reviewer_outputs(record: dict) -> dict[int, dict]:
    return {
        int(entry["round"]): entry["output"]
        for entry in record["candidate_provenance"]["reviewer_outputs"]
    }


def solver_outputs(record: dict) -> list[dict]:
    return [entry["output"] for entry in record["candidate_provenance"]["solver_outputs"]]


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def content_version(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    by_id = {item["item_id"]: item for item in provenance["items"]}
    generator_prompt = GENERATOR_PROMPT.read_text(encoding="utf-8")
    reviewer_prompt = REVIEWER_PROMPT.read_text(encoding="utf-8")

    failures: list[str] = []
    results: list[dict] = []
    cases = manifest["items"]
    required_ids = {
        "pilot-we-002", "pilot-we-009", "pilot-we-024",
        "pilot-struct-012", "pilot-we-006", "pilot-we-014", "pilot-we-021",
    }

    require(len(cases) == 7, f"manifest must contain 7 cases, got {len(cases)}", failures)
    require({case["item_id"] for case in cases} == required_ids,
            "manifest candidate IDs do not match the required Pilot set", failures)
    require(MANIFEST_PATH.exists() and PROVENANCE_PATH.exists(),
            "manifest/provenance source files must exist", failures)

    for case in cases:
        item_id = case["item_id"]
        record = by_id.get(item_id)
        require(record is not None, f"missing provenance record: {item_id}", failures)
        if record is None:
            continue

        rounds = reviewer_outputs(record)
        solvers = solver_outputs(record)
        case_result = {
            "item_id": item_id,
            "fixture_class": case["fixture_class"],
            "generator_guard": case["generator_guard"],
            "historical_round1_verdict": rounds.get(1, {}).get("verdict"),
            "historical_round2_verdict": rounds.get(2, {}).get("verdict"),
            "historical_solver_answers": [s.get("solver_answer") for s in solvers],
        }

        if "expected_hardened_reviewer" in case:
            expected = case["expected_hardened_reviewer"]
            historical = rounds.get(1, {})
            require(historical.get("verdict") == "PASS",
                    f"{item_id}: source provenance should document the original PASS false-negative",
                    failures)
            require(expected["verdict_not"] == ["PASS"],
                    f"{item_id}: hardened reviewer contract must prohibit PASS", failures)
            require(case["historical_solver_answer"] in {"NONE", "AMBIGUOUS"},
                    f"{item_id}: required historical solver answer must be NONE/AMBIGUOUS", failures)
            require(solvers and solvers[-1].get("solver_answer") == case["historical_solver_answer"],
                    f"{item_id}: provenance Solver outcome mismatch", failures)
            case_result["post_hardening_contract"] = "PASS prohibited"
        else:
            original = case["original_expected"]
            revised = case["revised_expected"]
            require(rounds.get(1, {}).get("verdict") == original["reviewer_verdict"],
                    f"{item_id}: original Reviewer verdict mismatch", failures)
            require(rounds.get(2, {}).get("verdict") == revised["reviewer_verdict"],
                    f"{item_id}: revised Reviewer verdict mismatch", failures)
            if "independent_answer" in original:
                require(rounds[1].get("independent_answer") == original["independent_answer"],
                        f"{item_id}: original independent answer mismatch", failures)
            require(solvers and solvers[-1].get("solver_answer") == revised["solver_answer"],
                    f"{item_id}: revised Solver outcome mismatch", failures)
            case_result["revision_contract"] = "original detected; revised remains accepted"

        results.append(case_result)

    generator_controls = manifest["required_prompt_controls"]["generator"]
    reviewer_controls = manifest["required_prompt_controls"]["reviewer"]
    for phrase in generator_controls:
        require(phrase in generator_prompt,
                f"Generator prompt missing P0 control phrase: {phrase!r}", failures)
    for phrase in reviewer_controls:
        require(phrase in reviewer_prompt,
                f"Reviewer prompt missing P0 control phrase: {phrase!r}", failures)

    output = {
        "_purpose": "Static P0 hardening regression contract; no live model call.",
        "fixture_version": manifest["fixture_version"],
        "case_count": len(results),
        "failure_count": len(failures),
        "results": results,
        "checks": {
            "three_failure_classes_registered": required_ids.issuperset(
                {"pilot-we-002", "pilot-we-009", "pilot-we-024"}
            ),
            "four_revise_cases_registered": required_ids.issuperset(
                {"pilot-struct-012", "pilot-we-006", "pilot-we-014", "pilot-we-021"}
            ),
            "generator_p0_prompt_controls_present": all(p in generator_prompt for p in generator_controls),
            "reviewer_p0_prompt_controls_present": all(p in reviewer_prompt for p in reviewer_controls),
        },
        "prompt_versions": {
            "generator_version": content_version(GENERATOR_PROMPT),
            "reviewer_version": content_version(REVIEWER_PROMPT),
            "solver_version": content_version(REPO_ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md"),
        },
        "failures": failures,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if failures:
        print(f"P0 hardening regression: FAIL ({len(failures)} failure(s))")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"P0 hardening regression: PASS ({len(results)} fixture contracts, 0 failures)")
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
