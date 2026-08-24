#!/usr/bin/env python3
"""Render the completed WE v2 Live Pilot metrics as the required report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "analysis" / "we_v2_pilot"
BATCH = "we-v2-live-pilot-20260824"


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def md_row(values: list[object]) -> str:
    return "| " + " | ".join(str(v) for v in values) + " |\n"


def load_regression_result(path: Path, suite: str) -> dict[str, object]:
    """Summarize a recorded regression result and fail closed on bad shape."""

    try:
        display_path = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        display_path = str(path)
    unavailable = {
        "available": False,
        "status": "UNAVAILABLE",
        "case_count": None,
        "failure_count": None,
        "detail": f"missing or unreadable artifact: {display_path}",
    }
    if not path.exists():
        return unavailable
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        unavailable["detail"] = f"could not load artifact: {type(exc).__name__}: {exc}"
        return unavailable
    if not isinstance(data, dict):
        unavailable["detail"] = "artifact is not a JSON object"
        return unavailable

    cases = data.get("results")
    failures = data.get("failures")
    checks = data.get("checks")
    case_count = data.get("case_count")
    if not isinstance(cases, list) or not isinstance(failures, list) or not isinstance(checks, dict):
        unavailable["detail"] = "artifact is missing results, failures, or checks"
        return unavailable
    if not isinstance(case_count, int):
        case_count = len(cases)
    expected_case_count = 7 if suite == "p0" else 6
    if case_count != expected_case_count or len(cases) != expected_case_count:
        return {
            "available": True,
            "status": "FAIL",
            "case_count": case_count,
            "failure_count": len(failures),
            "detail": f"stale or incomplete artifact: expected {expected_case_count} cases; got {case_count}",
        }

    if suite == "p0":
        recorded_failure_count = data.get("failure_count")
        if not isinstance(recorded_failure_count, int):
            recorded_failure_count = len(failures)
        checks_pass = all(value is True for value in checks.values())
        status = "PASS" if recorded_failure_count == 0 and not failures and checks_pass else "FAIL"
        return {
            "available": True,
            "status": status,
            "case_count": case_count,
            "failure_count": recorded_failure_count,
            "detail": display_path,
        }

    recorded_status = data.get("status")
    known_failure_pass_count = data.get("known_failure_pass_count")
    if not isinstance(recorded_status, str) or not isinstance(known_failure_pass_count, int):
        unavailable["detail"] = "WE regression artifact is missing status or known_failure_pass_count"
        return unavailable
    checks_pass = all(value is True for value in checks.values())
    status = (
        "PASS"
        if recorded_status == "PASS"
        and known_failure_pass_count == 0
        and not failures
        and checks_pass
        else "FAIL"
    )
    return {
        "available": True,
        "status": status,
        "case_count": case_count,
        "failure_count": len(failures),
        "detail": display_path,
    }


def main() -> int:
    metrics = json.loads((PILOT / "we_v2_pilot_metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((PILOT / "we_v2_pilot_provenance.json").read_text(encoding="utf-8"))
    p0_path = ROOT / "analysis" / "pilot" / "pilot_p0_hardening_regression_results.json"
    we_regression_path = ROOT / "analysis" / "we_v2" / "we_v2_regression_results.json"
    p0_result = load_regression_result(p0_path, "p0")
    we_regression_result = load_regression_result(we_regression_path, "we_v2")
    regression_gate_pass = (
        p0_result["available"]
        and we_regression_result["available"]
        and p0_result["status"] == "PASS"
        and we_regression_result["status"] == "PASS"
    )
    config = json.loads((ROOT / "orchestrator" / "config.json").read_text(encoding="utf-8"))
    gen_hash = hashlib.sha256((ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md").read_bytes()).hexdigest()
    reviewer_hash = hashlib.sha256((ROOT / ".claude" / "agents" / "toefl-itp-we-reviewer-v2.md").read_bytes()).hexdigest()
    solver_hash = hashlib.sha256((ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md").read_bytes()).hexdigest()

    geometry = metrics["geometry_comparison"]
    pilot = geometry["v2_live_pilot_25"]
    official = geometry["official_125"]
    v11 = geometry["v1_1_validation_75"]
    smoke = geometry["v2_smoke_10"]
    drift = metrics["context_drift_telemetry"]["five_item_windows"]
    guard = metrics["format_guardrails"]
    r1 = metrics["reviewer_round1"]
    rev = metrics["reviewer_eventual"]
    solver = metrics["solver"]
    orch = metrics["orchestrator"]
    revision = metrics["revision"]

    lines: list[str] = []
    lines += [
        "# TOEFL ITP Written Expression v2.0 — 25-item LIVE Pilot Report",
        "",
        f"- Run ID: `{BATCH}`",
        "- Scope: Written Expression only; exactly 25 initial candidates; Structure 0; replacement generation false.",
        "- Generation unit: nine independent microbatches (3/3/3/3/3/3/3/3/1), no 25-item monolithic realization.",
        "- Existing Smoke JSON and handwritten items were not used as the pilot cohort.",
        "",
        "## 1. Live invocation and version lock",
        "",
        "All 25 candidates, 25 Reviewer results, and 25 Solver results were processed through fresh live Agent invocations. Invocation IDs are stored in the raw microbatch artifacts and provenance. The three pre-existing generator microbatches retain `invocation_id: null` because that ID was unavailable when this continuation began; the six newly completed generator microbatches have IDs. Reviewer and Solver have nine recorded invocation IDs each.",
        "",
        md_row(["Component", "Fixed version", "Prompt hash (sha256)"]),
        md_row(["Generator", "Written Expression Generator v2.0", f"`sha256:{gen_hash}`"]),
        md_row(["Reviewer", "Written Expression Reviewer v2.0", f"`sha256:{reviewer_hash}`"]),
        md_row(["Solver", "existing blind Solver (unchanged)", f"`sha256:{solver_hash}`"]),
        md_row(["Orchestrator", "existing consensus policy", "unchanged; no relaxation"]),
        "",
        "## 2. Core pilot metrics",
        "",
        md_row(["Metric", "Result"]),
        md_row(["Initial generated", metrics["scope"]["initial_generated"]]),
        md_row(["Generator schema pass", f"{metrics['generator']['generator_schema_pass']}/25"]),
        md_row(["Format validator pass", f"{metrics['generator']['format_validator_pass']}/25"]),
        md_row(["Plan conformance (final cohort)", f"{metrics['generator']['plan_conformance_pass']}/25"]),
        md_row(["Final AUTO_ACCEPT", f"{orch['AUTO_ACCEPT']}/25 ({orch['auto_accept_rate'] * 100:.2f}%)"]),
        md_row(["MANUAL_REVIEW / DISCARDED / REJECTED", f"{orch['MANUAL_REVIEW']} / {orch['DISCARDED']} / {orch['REJECTED']}"]),
        "",
        "Generator schema was 22/25 because items 013–015 from the pre-existing micro-05 artifact lacked the required `format_metadata.diagnostics` fields. The deterministic validator still passed all 25, and these three were explicitly blocked from AUTO_ACCEPT and routed to MANUAL_REVIEW.",
        "",
        "## 3. Reviewer and revision",
        "",
        md_row(["Round", "PASS", "REVISE", "REJECT"]),
        md_row(["Round 1", r1["PASS"], r1["REVISE"], r1["REJECT"]]),
        md_row(["Eventual", rev["PASS"], rev["REVISE"], rev["REJECT"]]),
        "",
        md_row(["Validity split", "Count"]),
        md_row(["grammar PASS / FAIL / AMBIGUOUS", f"{metrics['reviewer_validity_split']['grammar_PASS']} / {metrics['reviewer_validity_split']['grammar_FAIL']} / {metrics['reviewer_validity_split']['grammar_AMBIGUOUS']}"]),
        md_row(["format PASS / WARN / FAIL", f"{metrics['reviewer_validity_split']['format_PASS']} / {metrics['reviewer_validity_split']['format_WARN']} / {metrics['reviewer_validity_split']['format_FAIL']}"]),
        md_row(["grammar PASS + format WARN", metrics["reviewer_validity_split"]["grammar_PASS_with_format_WARN"]]),
        "",
        f"Revision success: {revision['revision_success']}/{revision['revision_attempted']} "
        f"(derived from the recorded Round-2 Reviewer results).",
        "",
        "## 4. Solver and Orchestrator",
        "",
        md_row(["Solver metric", "Result"]),
        md_row(["Reached", f"{solver['reached']}/25"]),
        md_row(["A–D consensus with Generator answer", f"{solver['consensus']}/25"]),
        md_row(["A–D disagreement", solver["letter_disagreement"]]),
        md_row(["AMBIGUOUS / NONE", f"{solver['AMBIGUOUS']} / {solver['NONE']}"]),
        md_row(["LOW confidence", solver["LOW_confidence"]]),
        md_row(["Confidence", str(solver["confidence_counts"])]),
        "",
        "Solver consensus was 25/25, but AUTO_ACCEPT was 22/25 because the three Generator schema-invalid items were blocked independently of downstream agreement.",
        "",
        "## 5. Format guardrails",
        "",
        md_row(["Guardrail / band", "Count"]),
        md_row(["PREFERRED", guard["PREFERRED"]]),
        md_row(["WARNING band", guard["WARNING"]]),
        md_row(["EXTREME band", guard["EXTREME"]]),
        md_row(["Coverage = 100%", guard["coverage_100_percent"]]),
        md_row(["Unmarked context = 0", guard["unmarked_context_zero"]]),
        md_row(["Coverage ≥ 60%", guard["coverage_ge_60_percent"]]),
        "",
        "The four Reviewer `format WARN` results include format-band warnings/extremes; they were not treated as grammar failures. Coverage 100% and zero unmarked context did not recur.",
        "",
        "## 6. Geometry comparison",
        "",
        md_row(["Cohort", "n", "Sentence median", "Span median", "Coverage median", "Unmarked median", "Gaps A–B / B–C / C–D"]),
        md_row(["Official", official["item_count"], official["sentence_median"], official["span_median"], pct(official["coverage_median"]), official["unmarked_context_median"], " / ".join(str(official["gap_medians"][k]) for k in ("gap_A_B", "gap_B_C", "gap_C_D"))]),
        md_row(["v1.1 Validation", v11["item_count"], v11["sentence_median"], v11["span_median"], pct(v11["coverage_median"]), v11["unmarked_context_median"], " / ".join(str(v11["gap_medians"][k]) for k in ("gap_A_B", "gap_B_C", "gap_C_D"))]),
        md_row(["v2 Smoke", smoke["item_count"], smoke["sentence_median"], smoke["span_median"], pct(smoke["coverage_median"]), smoke["unmarked_context_median"], " / ".join(str(smoke["gap_medians"][k]) for k in ("gap_A_B", "gap_B_C", "gap_C_D"))]),
        md_row(["v2 Live Pilot", pilot["item_count"], pilot["sentence_median"], pilot["span_median"], pct(pilot["coverage_median"]), pilot["unmarked_context_median"], " / ".join(str(pilot["gap_medians"][k]) for k in ("gap_A_B", "gap_B_C", "gap_C_D"))]),
        "",
        "Live Pilot is close to the Official reference on sentence length, span size, coverage, and unmarked context. Its gap medians are 3/2/3 versus the Official 4/4/4; this is a small geometry difference, not the v1.1 full-sentence partition pattern.",
        "",
        "## 7. Failure taxonomy",
        "",
        md_row(["Primary reason", "Count", "Detail"]),
        md_row(["other", 3, "Generator schema failure: missing diagnostics in items 013–015; blocked from AUTO_ACCEPT"]),
        "",
        "No live candidate was classified as no_genuine_error, multiple_genuine_errors, wrong_answer_key, marked_span_mismatch, alternate_parse, semantic_only_error, solver_disagreement, solver_ambiguous, solver_none, or revision_failure.",
        "",
        "## 8. Context-drift telemetry",
        "",
        md_row(["Window", "Grammar PASS", "Reviewer PASS", "AUTO_ACCEPT", "Bands P/W/E", "Sentence median", "Coverage median", "Unmarked median"]),
    ]
    for row in drift:
        bands = row["format_band_counts"]
        lines.append(md_row([
            row["window"], f"{row['grammar_pass']}/{row['n']}", f"{row['reviewer_pass']}/{row['n']}",
            f"{row['auto_accept']}/{row['n']}", f"{bands['PREFERRED']}/{bands['WARNING']}/{bands['EXTREME']}",
            row["sentence_median"], pct(row["coverage_median"]), row["unmarked_context_median"],
        ]))
    lines += [
        "",
        "There is no clear monotonic generation-order drift: grammar PASS stayed 5/5 in every window, and sentence/coverage/context medians oscillate rather than degrade. EXTREME format results are localized to the 6–15 region (1 + 2), so they remain a follow-up risk rather than a broad context collapse.",
        "",
        "## 9. P0 regression",
        "",
        f"- WE v2 regression contract: {we_regression_result['status']} ({we_regression_result['case_count']} cases, {we_regression_result['failure_count']} recorded failures).",
        f"- Reviewer P0 hardening regression: {p0_result['status']} ({p0_result['case_count']} cases, {p0_result['failure_count']} recorded failures).",
        f"- Internal gate result: {'PASS' if regression_gate_pass else 'FAIL — do not proceed'}; statuses are derived from the recorded regression artifacts.",
        "",
        "## 10. Blind human-review sample",
        "",
        "A blind payload of 12 AUTO_ACCEPT candidates was extracted. It contains only `item_id`, `section`, `sentence`, and `marked_parts`, plus the rubric; it excludes Generator answer, clean sentence, mutation record, Reviewer result, Solver result, and format diagnostics. Human responses have not been filled in yet.",
        "",
        "File: `analysis/we_v2_pilot/we_v2_pilot_human_sample.json`",
        "",
        "## 11. Remaining risks and recommendation",
        "",
        "- Fix the Generator v2 emission bug that omitted required deterministic diagnostics for items 013–015 before any larger run; keep the schema gate hard.",
        "- Review the three EXTREME-format items and the one WARNING-band item during human calibration; format warnings alone are not grammar failures.",
        "- Complete the 12-item blind human review before production use; the current human sample is a payload, not a human quality verdict.",
        "",
        (
            "Recommendation for 75-item WE Validation: **proceed conditionally, not immediately**. "
            + (
                "The recorded P0 and WE v2 regression artifacts pass. "
                if regression_gate_pass
                else "At least one required regression artifact is unavailable or failing; the regression gate is closed. "
            )
            + "The live pilot still requires the Generator schema pass rate to be corrected and re-smoked before larger generation. No 75-item generation, DB insert, or website integration was performed in this run."
        ),
        "",
        "## 12. Required output artifacts",
        "",
        "- `we_v2_pilot_plan.json`",
        "- `we_v2_pilot_initial_items.json`",
        "- `we_v2_pilot_final_format_validation.json`",
        "- `we_v2_pilot_provenance.json`",
        "- `we_v2_pilot_review.json`",
        "- `we_v2_pilot_solver.json`",
        "- `we_v2_pilot_accepted.json`",
        "- `we_v2_pilot_failures.json`",
        "- `we_v2_pilot_metrics.json`",
        "- `we_v2_pilot_human_sample.json`",
        "- `WE_V2_PILOT_REPORT.md`",
        "",
        f"Generated from `{PILOT.relative_to(ROOT).as_posix()}/we_v2_pilot_metrics.json`.",
    ]
    (PILOT / "WE_V2_PILOT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {PILOT / 'WE_V2_PILOT_REPORT.md'}")
    return 0 if regression_gate_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
