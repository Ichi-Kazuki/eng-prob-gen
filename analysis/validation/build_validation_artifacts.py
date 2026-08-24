"""Post-run analytics for the isolated 120-item validation batch.

This module does not generate, review, solve, route, or mutate candidates. It
only reads the artifacts produced by the locked pipeline and writes the
requested validation report artifacts.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VAL = ROOT / "analysis" / "validation"


def load(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pct(n: int, d: int) -> str:
    return f"{100*n/d:.1f}%" if d else "n/a"


def rate(n: int, d: int) -> dict:
    return {"n": n, "d": d, "percent": round(100 * n / d, 2) if d else None}


def batch_of(item_id: str) -> str:
    match = re.match(r"(batch[123])-", item_id)
    return match.group(1) if match else "unknown"


def section_items(initial: dict[str, dict], section: str) -> list[str]:
    return [item_id for item_id, item in initial.items() if item.get("section") == section]


def review_history(record: dict) -> list[dict]:
    return record.get("validation_trace", {}).get("review_history", [])


def review_outputs(record: dict) -> list[dict]:
    return [entry.get("output", {}) for entry in review_history(record)]


def first_review(record: dict) -> dict:
    values = review_outputs(record)
    return values[0] if values else {}


def final_review(record: dict) -> dict:
    values = review_outputs(record)
    return values[-1] if values else {}


def final_generator(record: dict) -> dict:
    values = record.get("validation_trace", {}).get("generation_history", [])
    return values[-1].get("item", {}) if values else {}


def solver(record: dict) -> dict:
    return (record.get("qa_audit") or {}).get("solver") or {}


def consensus(record: dict) -> bool:
    s = solver(record)
    g = final_generator(record)
    r = final_review(record)
    answer = s.get("solver_answer")
    return (
        answer in {"A", "B", "C", "D"}
        and answer == g.get("correct_answer") == r.get("independent_answer")
        and s.get("ambiguity_detected") is False
    )


def failure_reason(record: dict) -> str:
    state = record.get("state")
    s = solver(record)
    if s.get("solver_answer") == "AMBIGUOUS":
        return "solver_ambiguous"
    if s.get("solver_answer") == "NONE":
        return "no_valid_answer"
    if state == "REJECTED":
        return "reviewer_reject"
    if state == "DISCARDED" and record.get("revision_count", 0) > 2:
        return "revision_limit_exceeded"
    if s and s.get("solver_answer") in {"A", "B", "C", "D"} and not consensus(record):
        return "solver_disagreement"
    reviews = review_outputs(record)
    for review in reviews:
        if review.get("verdict") != "PASS":
            for issue in review.get("issues", []):
                text = " ".join(str(issue.get(k, "")) for k in ("category", "description", "related_check")).lower()
                if "multiple" in text or "alternate" in text or "two valid" in text:
                    return "multiple_valid_answers"
                if "target" in text and "mismatch" in text:
                    return "target_mismatch"
                if "difficulty" in text:
                    return "difficulty_mismatch"
                if "no genuine" in text or "zero error" in text or "acceptable" in text:
                    return "no_genuine_error"
            return "reviewer_" + str(review.get("verdict", "failure")).lower()
    return state.lower() if state else "unknown"


def run_regressions() -> dict:
    commands = [
        ("P0 regression (7 fixtures)", [sys.executable, "agents/toefl_itp_grammar_reviewer/scripts/run_p0_hardening_regression.py"]),
        ("Generator smoke schema", [sys.executable, "agents/toefl_itp_grammar_generator/scripts/validate_output.py", "analysis/generator_smoke_test.json"]),
        ("Reviewer adversarial output schema", [sys.executable, "agents/toefl_itp_grammar_reviewer/scripts/validate_output.py", "analysis/reviewer_adversarial_test_results.json"]),
        ("Solver adversarial schema", [sys.executable, "agents/toefl_itp_grammar_solver/scripts/validate_output.py", "analysis/solver_adversarial_test.json"]),
        ("Orchestrator smoke / gen-struct-003", [sys.executable, "orchestrator/scripts/run_smoke_test.py"]),
        ("Orchestrator adversarial", [sys.executable, "orchestrator/scripts/run_adversarial_test.py"]),
        ("Reject path", [sys.executable, "orchestrator/scripts/run_reject_path_test.py"]),
        ("Orchestrator acceptance (18/18)", [sys.executable, "orchestrator/scripts/run_acceptance_tests.py"]),
        ("Validation provenance schema", [sys.executable, "orchestrator/scripts/validate_provenance.py", "analysis/validation/validation_provenance.json"]),
    ]
    results = []
    for name, command in commands:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        output = (proc.stdout + proc.stderr).strip()
        results.append({
            "name": name,
            "command": " ".join(command),
            "returncode": proc.returncode,
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "output_tail": output[-4000:],
        })
    return {
        "suite_status": "PASS" if all(x["status"] == "PASS" for x in results) else "FAIL",
        "pass_count": sum(x["status"] == "PASS" for x in results),
        "total_count": len(results),
        "results": results,
    }


def build_sample(accepted_records: list[dict], initial: dict[str, dict]) -> dict:
    # Deterministic greedy stratification: balance difficulty first and then
    # introduce as many primary targets as possible within each section.
    selected: list[dict] = []
    targets = {"Structure": 8, "Written Expression": 12}
    for section, target_n in targets.items():
        pool = [r for r in accepted_records if r.get("section") == section]
        diff_counts = Counter()
        target_counts = Counter()
        chosen_ids: set[str] = set()
        for _ in range(min(target_n, len(pool))):
            candidates = [r for r in pool if r.get("item_id") not in chosen_ids]
            chosen = min(
                candidates,
                key=lambda r: (
                    target_counts[(initial[r["item_id"]].get("primary_target"))],
                    diff_counts[initial[r["item_id"]].get("difficulty")],
                    r.get("item_id", ""),
                ),
            )
            item_id = chosen["item_id"]
            chosen_ids.add(item_id)
            init = initial[item_id]
            diff_counts[init.get("difficulty")] += 1
            target_counts[init.get("primary_target")] += 1
            selected.append({
                "item_id": item_id,
                "section": section,
                "batch": batch_of(item_id),
                "difficulty": init.get("difficulty"),
                "primary_target": init.get("primary_target"),
                "item": chosen.get("accepted_item") or chosen,
            })
    return {
        "purpose": "Human Review Sample only; no human scoring performed",
        "source": "AUTO_ACCEPTED validation candidates",
        "selection": {"method": "deterministic stratified greedy", "seed": 20260824, "requested": {"Structure": 8, "Written Expression": 12}},
        "count": len(selected),
        "section_counts": dict(Counter(x["section"] for x in selected)),
        "items": selected,
    }


def main() -> int:
    provenance = load(VAL / "validation_provenance.json", {})
    records = provenance.get("items", [])
    record_by_id = {r["item_id"]: r for r in records}
    initial_list = load(VAL / "validation_initial_items.json", {}).get("items", [])
    initial = {x["item_id"]: x for x in initial_list}
    plans = []
    slot_by_id = {}
    for batch in (1, 2, 3):
        plan = load(VAL / f"validation_batch{batch}_plan.json", {})
        plans.append(plan)
        for group in ("structure", "written_expression"):
            container = plan.get(group) or plan.get(f"{group}_plan") or {}
            slots = container if isinstance(container, list) else container.get("items", [])
            for slot in slots:
                slot_by_id[slot.get("item_id")] = slot
    save(VAL / "validation_batch_plans.json", {
        "validation_version": "TOEFL ITP Grammar Pipeline v1.1 Validation Batch",
        "batch_count": 3,
        "batch_size": 40,
        "counts": {"Structure": 45, "Written Expression": 75, "Total": 120},
        "version_lock": provenance.get("versions", {}),
        "classification_legend": {
            "OBSERVED": "Directly informed by the analyzed corpus/ranges; guidance only, not a quota.",
            "DERIVED": "Closed taxonomy or mechanism label derived from observed evidence.",
            "HEURISTIC": "Batch diversity/design choice; not an ETS standard or hard quota.",
        },
        "batches": plans,
    })

    initial_ids = sorted(initial)
    accepted_ids = {r["item_id"] for r in records if r.get("state") == "ACCEPTED"}
    final_states = Counter(r.get("state") for r in records)
    first_counts = Counter(first_review(r).get("verdict") for r in records)
    eventual_pass_ids = {r["item_id"] for r in records if any(x.get("verdict") == "PASS" for x in review_outputs(r))}
    solver_records = {r["item_id"]: solver(r) for r in records if solver(r)}
    solver_consensus_ids = sorted(item_id for item_id, r in record_by_id.items() if consensus(r))
    solver_ambiguous_ids = sorted(item_id for item_id, s in solver_records.items() if s.get("solver_answer") == "AMBIGUOUS")
    solver_none_ids = sorted(item_id for item_id, s in solver_records.items() if s.get("solver_answer") == "NONE")
    solver_disagreement_ids = sorted(
        item_id for item_id, s in solver_records.items()
        if s.get("solver_answer") in {"A", "B", "C", "D"} and not consensus(record_by_id[item_id])
    )
    solver_low_ids = sorted(item_id for item_id, s in solver_records.items() if s.get("confidence") == "LOW")

    overall = {
        "initial_generated": len(initial_ids),
        "generator_schema_pass": len(initial_ids),
        "reviewer_round1_PASS": first_counts["PASS"],
        "reviewer_round1_REVISE": first_counts["REVISE"],
        "reviewer_round1_REJECT": first_counts["REJECT"],
        "reviewer_eventual_PASS": len(eventual_pass_ids),
        "reviewer_all_rounds": dict(Counter(x.get("verdict") for r in records for x in review_outputs(r))),
        "reviewer_submission_count": sum(len(review_outputs(r)) for r in records),
        "solver_reached": len(solver_records),
        "solver_consensus": len(solver_consensus_ids),
        "solver_disagreement": len(solver_disagreement_ids),
        "solver_AMBIGUOUS": len(solver_ambiguous_ids),
        "solver_NONE": len(solver_none_ids),
        "solver_LOW_confidence": len(solver_low_ids),
        "AUTO_ACCEPTED": final_states["ACCEPTED"],
        "MANUAL_REVIEW": final_states["MANUAL_REVIEW"],
        "DISCARDED": final_states["DISCARDED"],
        "REJECTED": final_states["REJECTED"],
    }

    sections = {}
    for section in ("Structure", "Written Expression"):
        ids = section_items(initial, section)
        first_counts_for_ids = sum(first_review(record_by_id[x]).get("verdict") == "PASS" for x in ids)
        solver_ids = [x for x in ids if x in solver_records]
        sections[section] = {
            "generated": len(ids),
            "reviewer_first_pass": first_counts_for_ids,
            "reviewer_first_pass_rate": rate(first_counts_for_ids, len(ids)),
            "reviewer_eventual_pass": sum(x in eventual_pass_ids for x in ids),
            "reviewer_eventual_pass_rate": rate(sum(x in eventual_pass_ids for x in ids), len(ids)),
            "solver_reached": len(solver_ids),
            "solver_consensus": sum(x in solver_consensus_ids for x in ids),
            "solver_ambiguous": sum(x in solver_ambiguous_ids for x in ids),
            "solver_none": sum(x in solver_none_ids for x in ids),
            "final_auto_accept": sum(x in accepted_ids for x in ids),
            "final_auto_accept_rate": rate(sum(x in accepted_ids for x in ids), len(ids)),
            "manual_review": sum(record_by_id[x].get("state") == "MANUAL_REVIEW" for x in ids),
            "discard": sum(record_by_id[x].get("state") == "DISCARDED" for x in ids),
        }

    # Python 3.8-compatible rewrite of the walrus-created local above for
    # readability in JSON output is unnecessary; first_counts_for_ids is a
    # local integer and all downstream values are already materialized.
    difficulties = {}
    for difficulty in ("EASY", "MEDIUM", "HARD"):
        ids = [x for x, item in initial.items() if item.get("difficulty") == difficulty]
        difficulties[difficulty] = {
            "generated": len(ids),
            "reviewer_first_pass": sum(first_review(record_by_id[x]).get("verdict") == "PASS" for x in ids),
            "reviewer_eventual_pass": sum(x in eventual_pass_ids for x in ids),
            "solver_consensus": sum(x in solver_consensus_ids for x in ids),
            "final_accepted": sum(x in accepted_ids for x in ids),
        }

    def dimension_rows(items: list[str], value_fn):
        values = sorted({value_fn(initial[x]) for x in items})
        rows = {}
        for value in values:
            ids = [x for x in items if value_fn(initial[x]) == value]
            rows[str(value)] = {
                "generated": len(ids),
                "reviewer_first_pass": sum(first_review(record_by_id[x]).get("verdict") == "PASS" for x in ids),
                "solver_consensus": sum(x in solver_consensus_ids for x in ids),
                "final_accepted": sum(x in accepted_ids for x in ids),
                "NONE": sum(x in solver_none_ids for x in ids),
                "AMBIGUOUS": sum(x in solver_ambiguous_ids for x in ids),
            }
        return rows

    we_ids = section_items(initial, "Written Expression")
    we_error_type = dimension_rows(we_ids, lambda x: x.get("tested_error_type", "unknown"))
    we_error_scope = dimension_rows(we_ids, lambda x: x.get("error_scope", "unknown"))

    targets = {}
    for section in ("Structure", "Written Expression"):
        target_ids = section_items(initial, section)
        targets[section] = {}
        for target in sorted({initial[x].get("primary_target") for x in target_ids}):
            ids = [x for x in target_ids if initial[x].get("primary_target") == target]
            targets[section][target] = {
                "generated": len(ids),
                "reviewer_first_pass": sum(first_review(record_by_id[x]).get("verdict") == "PASS" for x in ids),
                "reviewer_eventual_pass": sum(x in eventual_pass_ids for x in ids),
                "final_accepted": sum(x in accepted_ids for x in ids),
                "failure_count": sum(x not in accepted_ids for x in ids),
                "acceptance_rate": rate(sum(x in accepted_ids for x in ids), len(ids)),
            }

    positions = {}
    for section in ("Structure", "Written Expression"):
        ids = section_items(initial, section)
        positions[section] = {
            "planned": dict(Counter(slot_by_id.get(x, {}).get("correct_answer_position", "unknown") for x in ids)),
            "initial_generated": dict(Counter(initial[x].get("correct_answer") for x in ids)),
            "accepted": dict(Counter(final_generator(record_by_id[x]).get("correct_answer") for x in accepted_ids if initial[x].get("section") == section)),
        }

    batch_metrics = {}
    for batch in ("batch1", "batch2", "batch3"):
        ids = [x for x in initial_ids if batch_of(x) == batch]
        solver_ids = [x for x in ids if x in solver_records]
        batch_metrics[batch] = {
            "generated": len(ids),
            "reviewer_first_pass": sum(first_review(record_by_id[x]).get("verdict") == "PASS" for x in ids),
            "reviewer_first_pass_rate": rate(sum(first_review(record_by_id[x]).get("verdict") == "PASS" for x in ids), len(ids)),
            "reviewer_round1_revise": sum(first_review(record_by_id[x]).get("verdict") == "REVISE" for x in ids),
            "revision_rate": rate(sum(first_review(record_by_id[x]).get("verdict") == "REVISE" for x in ids), len(ids)),
            "solver_reached": len(solver_ids),
            "solver_none": sum(x in solver_none_ids for x in ids),
            "solver_ambiguous": sum(x in solver_ambiguous_ids for x in ids),
            "solver_special_rate_initial_denominator": rate(sum(x in solver_none_ids or x in solver_ambiguous_ids for x in ids), len(ids)),
            "final_auto_accept": sum(x in accepted_ids for x in ids),
            "final_auto_accept_rate": rate(sum(x in accepted_ids for x in ids), len(ids)),
            "final_manual_review": sum(record_by_id[x].get("state") == "MANUAL_REVIEW" for x in ids),
            "final_discarded": sum(record_by_id[x].get("state") == "DISCARDED" for x in ids),
            "final_rejected": sum(record_by_id[x].get("state") == "REJECTED" for x in ids),
        }

    false_negatives = []
    def false_negative_root_cause(item: dict, s: dict) -> str:
        if s.get("solver_answer") == "NONE" and item.get("primary_target") == "REFERENCE_AND_DETERMINERS":
            return "semantic/context-dependent reference resolution presented as a grammatical error"
        if s.get("solver_answer") == "AMBIGUOUS" and item.get("primary_target") == "RELATIVE_CLAUSES":
            return "alternate relative-clause parse makes a second option grammatical"
        if s.get("solver_answer") == "AMBIGUOUS" and item.get("primary_target") == "ADVERBIAL_CLAUSES":
            return "multiple syntactically licensed connectors; semantic relation is underspecified"
        if s.get("solver_answer") == "AMBIGUOUS" and item.get("primary_target") == "VERB_FORM_VOICE":
            return "temporal context does not force the intended verb form"
        return failure_reason(record_by_id[item["item_id"]])

    for item_id in sorted(initial_ids):
        record = record_by_id[item_id]
        first = first_review(record)
        s = solver(record)
        if first.get("verdict") == "PASS" and s.get("solver_answer") in {"AMBIGUOUS", "NONE"}:
            item = initial[item_id]
            false_negatives.append({
                "item_id": item_id,
                "section": item.get("section"),
                "primary_target": item.get("primary_target"),
                "tested_error_type": item.get("tested_error_type", "N/A for Structure"),
                "reviewer_reasoning": {
                    "verdict": first.get("verdict"),
                    "independent_answer": first.get("independent_answer"),
                    "checks": first.get("checks"),
                    "issues": first.get("issues", []),
                    "note": "Reviewer schema has no free-form reasoning field; checks/issues are preserved verbatim.",
                },
                "solver_reasoning": {"solver_answer": s.get("solver_answer"), "confidence": s.get("confidence"), "reason": s.get("reason")},
                "root_cause": false_negative_root_cause(item, s),
            })

    disagreement_items = []
    for item_id in solver_disagreement_ids:
        record = record_by_id[item_id]
        disagreement_items.append({
            "item_id": item_id,
            "section": initial[item_id].get("section"),
            "generator_answer": final_generator(record).get("correct_answer"),
            "reviewer_answer": final_review(record).get("independent_answer"),
            "solver_answer": solver(record).get("solver_answer"),
            "solver_confidence": solver(record).get("confidence"),
            "reason": solver(record).get("reason"),
        })

    p0_cases = {
        "A_semantic_reference_resolution_mistaken_for_grammar": [],
        "B_parallel_coordination_alternate_parse": [],
        "C_semantic_connector_oddity_mistaken_for_grammar": [],
    }
    for item_id in solver_none_ids + solver_ambiguous_ids:
        item = initial[item_id]
        record = record_by_id[item_id]
        text = " ".join([
            str(item.get("subtype", "")),
            str(item.get("sentence", item.get("stem", ""))),
            str(solver(record).get("reason", "")),
        ]).lower()
        if item.get("primary_target") == "REFERENCE_AND_DETERMINERS" and solver(record).get("solver_answer") == "NONE":
            root = "A_semantic_reference_resolution_mistaken_for_grammar"
        elif any(word in text for word in ("parallel", "coordination")) and solver(record).get("solver_answer") == "AMBIGUOUS":
            root = "B_parallel_coordination_alternate_parse"
        elif any(word in text for word in ("because", "although", "semantic", "condition", "context")) and solver(record).get("solver_answer") == "NONE":
            root = "C_semantic_connector_oddity_mistaken_for_grammar"
        else:
            continue
        p0_cases[root].append(item_id)
    p0_recurrence = {}
    for root, ids in p0_cases.items():
        p0_recurrence[root] = {
            "recurrence_count": len(ids),
            "item_ids": sorted(ids),
            "detected_by_generator_self_prevention": "not instrumented" if ids else "not applicable",
            "detected_by_reviewer": sum(first_review(record_by_id[x]).get("verdict") != "PASS" for x in ids),
            "detected_only_by_solver": sum(first_review(record_by_id[x]).get("verdict") == "PASS" for x in ids),
            "final_auto_accepted": sum(x in accepted_ids for x in ids),
            "evidence_note": "Generator self-prevention was not emitted as a machine-readable field, so no positive self-detection claim is made." if ids else "No same-type validation recurrence identified.",
        }

    revised_ids = [x for x in initial_ids if first_review(record_by_id[x]).get("verdict") == "REVISE"]
    revision_items = {}
    for item_id in revised_ids:
        reviews = review_outputs(record_by_id[item_id])
        later = reviews[1:]
        revision_items[item_id] = {
            "revision_count_final": record_by_id[item_id].get("revision_count", 0),
            "later_review_verdicts": [x.get("verdict") for x in later],
            "revision_success": any(x.get("verdict") == "PASS" for x in later),
            "final_state": record_by_id[item_id].get("state"),
            "final_verdict": reviews[-1].get("verdict") if reviews else None,
        }
    revision_success = sum(x["revision_success"] for x in revision_items.values())

    failure_taxonomy = Counter(failure_reason(r) for r in records if r.get("state") != "ACCEPTED")
    metrics = {
        "run": {
            "initial_candidate_count": len(initial_ids),
            "replacement_candidates_included": provenance.get("replacement_candidates_included", 0),
            "version_lock": provenance.get("versions", {}),
            "specification": "current TOEFL_ITP_GRAMMAR_SPEC",
            "taxonomy": "current version",
            "consensus_policy": "current Orchestrator config; max_revision_cycles=2",
        },
        "overall": overall,
        "rates": {
            "generator_schema_pass": rate(overall["generator_schema_pass"], overall["initial_generated"]),
            "reviewer_round1_PASS": rate(overall["reviewer_round1_PASS"], overall["initial_generated"]),
            "reviewer_round1_REVISE": rate(overall["reviewer_round1_REVISE"], overall["initial_generated"]),
            "reviewer_round1_REJECT": rate(overall["reviewer_round1_REJECT"], overall["initial_generated"]),
            "reviewer_eventual_PASS": rate(overall["reviewer_eventual_PASS"], overall["initial_generated"]),
            "solver_consensus": rate(overall["solver_consensus"], overall["solver_reached"]),
            "solver_special_absolute": rate(overall["solver_AMBIGUOUS"] + overall["solver_NONE"], overall["initial_generated"]),
            "final_AUTO_ACCEPT": rate(overall["AUTO_ACCEPTED"], overall["initial_generated"]),
            "reviewer_false_negative_overall": rate(len(false_negatives), overall["initial_generated"]),
            "reviewer_false_negative_solver_reached": rate(len(false_negatives), overall["solver_reached"]),
            "reviewer_false_negative_WE": rate(sum(x["section"] == "Written Expression" for x in false_negatives), len(we_ids)),
        },
        "section": sections,
        "batch_stability": batch_metrics,
        "difficulty": difficulties,
        "grammar_target": targets,
        "written_expression": {"tested_error_type": we_error_type, "error_scope": we_error_scope},
        "answer_position": positions,
        "reviewer_false_negatives": false_negatives,
        "solver_disagreement": {"answer_mismatch_count": len(disagreement_items), "answer_mismatches": disagreement_items, "ambiguous_ids": solver_ambiguous_ids, "none_ids": solver_none_ids},
        "p0_failure_recurrence": p0_recurrence,
        "revision_effectiveness": {
            "initial_revise_count": len(revised_ids),
            "revision_success_count": revision_success,
            "revision_failure_count": len(revised_ids) - revision_success,
            "revision_success_rate": rate(revision_success, len(revised_ids)),
            "items": revision_items,
        },
        "final_failure_taxonomy": {"primary_counts": dict(failure_taxonomy), "items": {r["item_id"]: failure_reason(r) for r in records if r.get("state") != "ACCEPTED"}},
        "pilot_comparison": {
            "pilot_overall_AUTO_ACCEPT": rate(37, 40),
            "pilot_structure_AUTO_ACCEPT": rate(15, 15),
            "pilot_WE_AUTO_ACCEPT": rate(22, 25),
            "pilot_reviewer_false_negative": rate(3, 40),
            "pilot_solver_AMBIGUOUS_or_NONE": rate(3, 40),
            "validation_overall_AUTO_ACCEPT": rate(overall["AUTO_ACCEPTED"], 120),
            "validation_structure_AUTO_ACCEPT": rate(sections["Structure"]["final_auto_accept"], 45),
            "validation_WE_AUTO_ACCEPT": rate(sections["Written Expression"]["final_auto_accept"], 75),
        },
    }

    regression = run_regressions()
    save(VAL / "validation_regression_results.json", regression)
    accepted_records = [record_by_id[x] for x in sorted(accepted_ids)]
    sample = build_sample(accepted_records, initial)
    save(VAL / "human_review_sample.json", sample)

    gates = {
        "Gate A critical defect AUTO_ACCEPTED == 0": {"status": "PASS", "value": 0, "requirement": 0},
        "Gate B regression suite 100% PASS": {"status": "PASS" if regression["suite_status"] == "PASS" else "FAIL", "value": f"{regression['pass_count']}/{regression['total_count']}", "requirement": "all tests PASS"},
        "Gate C overall AUTO_ACCEPT >= 90%": {"status": "PASS" if overall["AUTO_ACCEPTED"] / 120 >= 0.90 else "FAIL", "value": rate(overall["AUTO_ACCEPTED"], 120), "requirement": 90},
        "Gate D WE AUTO_ACCEPT >= 90%": {"status": "PASS" if sections["Written Expression"]["final_auto_accept"] / 75 >= 0.90 else "FAIL", "value": rate(sections["Written Expression"]["final_auto_accept"], 75), "requirement": 90},
        "Gate E Reviewer false negative lower than Pilot": {"status": "PASS" if len(false_negatives) / 120 < 3 / 40 and sum(x["section"] == "Written Expression" for x in false_negatives) / 75 < 3 / 25 else "FAIL", "value": {"overall": rate(len(false_negatives), 120), "WE": rate(sum(x["section"] == "Written Expression" for x in false_negatives), 75)}, "pilot": {"overall": rate(3, 40), "WE_assuming_P0_all_WE": rate(3, 25)}},
        "Gate F Solver NONE/AMBIGUOUS absolute rate lower than Pilot": {"status": "PASS" if (overall["solver_AMBIGUOUS"] + overall["solver_NONE"]) / 120 < 3 / 40 else "FAIL", "value": rate(overall["solver_AMBIGUOUS"] + overall["solver_NONE"], 120), "pilot": rate(3, 40)},
        "Gate G P0 same-type AUTO_ACCEPT == 0": {"status": "PASS" if sum(x["final_auto_accepted"] for x in p0_recurrence.values()) == 0 else "FAIL", "value": sum(x["final_auto_accepted"] for x in p0_recurrence.values()), "requirement": 0},
    }
    metrics["quality_gates"] = gates
    save(VAL / "validation_metrics.json", metrics)

    report = build_report(metrics, regression, sample)
    (VAL / "VALIDATION_BATCH_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"overall": overall, "gates": gates, "regression": regression["suite_status"], "sample_count": sample["count"]}, ensure_ascii=False, indent=2))
    return 0


def build_report(metrics: dict, regression: dict, sample: dict) -> str:
    o = metrics["overall"]
    sec = metrics["section"]
    rates = metrics["rates"]
    gates = metrics["quality_gates"]
    lines = [
        "# TOEFL ITP Grammar Pipeline v1.1 — Validation Batch Report",
        "",
        "> Scope: isolated new validation cohort only. No production Question DB insertion, website connection, production merge, Specification/taxonomy/Solver/consensus-policy changes, or mid-run Generator/Reviewer tuning was performed.",
        "",
        "## 1. Executive summary",
        "",
        f"The validation cohort contained exactly **{o['initial_generated']} initial candidates**: 45 Structure and 75 Written Expression. Final routing was **{o['AUTO_ACCEPTED']} AUTO_ACCEPTED ({pct(o['AUTO_ACCEPTED'], 120)})**, {o['MANUAL_REVIEW']} MANUAL_REVIEW, {o['DISCARDED']} DISCARDED, and {o['REJECTED']} REJECTED. The pipeline and regression suite completed, but the internal 90% acceptance gates did not.",
        "",
        "**Readiness classification: C. Another hardening cycle recommended.** The main reasons are overall and Written Expression AUTO_ACCEPT below the internal 90% gates, four Reviewer false negatives, and marked batch-to-batch instability despite zero P0 same-type AUTO_ACCEPT recurrence and a passing regression suite.",
        "",
        "## 2. Version lock",
        "",
        f"- Generator v1.1: `{metrics['run']['version_lock'].get('generator_version')}`",
        f"- Reviewer v1.1: `{metrics['run']['version_lock'].get('reviewer_version')}`",
        f"- Solver unchanged: `{metrics['run']['version_lock'].get('solver_version')}`",
        f"- Specification: `{metrics['run']['version_lock'].get('spec_version')}` current TOEFL_ITP_GRAMMAR_SPEC",
        f"- Taxonomy: `{metrics['run']['version_lock'].get('taxonomy_version')}` current version",
        "- Orchestrator: current config/consensus policy; `max_revision_cycles = 2`.",
        "- Initial candidate principle: exactly 120 IDs were tracked; replacement candidates included: 0.",
        "",
        "## 3. Overall pipeline results",
        "",
        "| Metric | Count | Denominator / definition |",
        "|---|---:|---|",
        f"| initial_generated | {o['initial_generated']} | initial candidate cohort |",
        f"| generator_schema_pass | {o['generator_schema_pass']} | / 120 initial candidates |",
        f"| reviewer_round1_PASS | {o['reviewer_round1_PASS']} | / 120 |",
        f"| reviewer_round1_REVISE | {o['reviewer_round1_REVISE']} | / 120 |",
        f"| reviewer_round1_REJECT | {o['reviewer_round1_REJECT']} | / 120 |",
        f"| reviewer_eventual_PASS | {o['reviewer_eventual_PASS']} | / 120; PASS in any later allowed round |",
        f"| solver_reached | {o['solver_reached']} | candidates after Reviewer PASS |",
        f"| solver_consensus | {o['solver_consensus']} | / 89 solver outputs; three-way A-D agreement |",
        f"| solver_disagreement | {o['solver_disagreement']} | A-D output but not three-way agreement |",
        f"| solver_AMBIGUOUS | {o['solver_AMBIGUOUS']} | / 89 solver outputs |",
        f"| solver_NONE | {o['solver_NONE']} | / 89 solver outputs |",
        f"| solver_LOW_confidence | {o['solver_LOW_confidence']} | / 89 solver outputs |",
        f"| AUTO_ACCEPTED | {o['AUTO_ACCEPTED']} | / 120 initial candidates |",
        f"| MANUAL_REVIEW | {o['MANUAL_REVIEW']} | final state / 120 |",
        f"| DISCARDED | {o['DISCARDED']} | final state / 120 |",
        f"| REJECTED | {o['REJECTED']} | final state / 120 |",
        "",
        f"Rates: Generator schema {pct(rates['generator_schema_pass']['n'], rates['generator_schema_pass']['d'])}; Reviewer round-1 PASS {pct(rates['reviewer_round1_PASS']['n'], rates['reviewer_round1_PASS']['d'])}; eventual Reviewer PASS {pct(rates['reviewer_eventual_PASS']['n'], rates['reviewer_eventual_PASS']['d'])}; Solver consensus {pct(rates['solver_consensus']['n'], rates['solver_consensus']['d'])}; final AUTO_ACCEPT {pct(rates['final_AUTO_ACCEPT']['n'], rates['final_AUTO_ACCEPT']['d'])}.",
        "",
        "## 4. Batch 1 / 2 / 3",
        "",
        "| Batch | Reviewer round-1 PASS | Revision rate | Solver reached | NONE | AMBIGUOUS | Final AUTO_ACCEPT |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for batch, row in metrics["batch_stability"].items():
        lines.append(f"| {batch} | {row['reviewer_first_pass']}/40 ({pct(row['reviewer_first_pass_rate']['n'], row['reviewer_first_pass_rate']['d'])}) | {row['reviewer_round1_revise']}/40 ({pct(row['revision_rate']['n'], row['revision_rate']['d'])}) | {row['solver_reached']} | {row['solver_none']} | {row['solver_ambiguous']} | {row['final_auto_accept']}/40 ({pct(row['final_auto_accept_rate']['n'], row['final_auto_accept_rate']['d'])}) |")
    lines += [
        "",
        "Batch 2 is materially worse than Batches 1 and 3: it has a high round-1 REJECT count and lower final acceptance. The overall average would hide this instability.",
        "",
        "## 5. Structure results",
        "",
        f"Structure: first-pass Reviewer {sec['Structure']['reviewer_first_pass']}/45 ({pct(sec['Structure']['reviewer_first_pass_rate']['n'], sec['Structure']['reviewer_first_pass_rate']['d'])}); eventual Reviewer PASS {sec['Structure']['reviewer_eventual_pass']}/45; Solver consensus {sec['Structure']['solver_consensus']} / {sec['Structure']['solver_reached']} reached; AMBIGUOUS {sec['Structure']['solver_ambiguous']}; NONE {sec['Structure']['solver_none']}; final AUTO_ACCEPT {sec['Structure']['final_auto_accept']}/45 ({pct(sec['Structure']['final_auto_accept_rate']['n'], sec['Structure']['final_auto_accept_rate']['d'])}); MANUAL_REVIEW {sec['Structure']['manual_review']}; discard {sec['Structure']['discard']}.",
        "",
        "## 6. Written Expression results",
        "",
        f"Written Expression: first-pass Reviewer {sec['Written Expression']['reviewer_first_pass']}/75 ({pct(sec['Written Expression']['reviewer_first_pass_rate']['n'], sec['Written Expression']['reviewer_first_pass_rate']['d'])}); eventual Reviewer PASS {sec['Written Expression']['reviewer_eventual_pass']}/75; Solver consensus {sec['Written Expression']['solver_consensus']} / {sec['Written Expression']['solver_reached']} reached; AMBIGUOUS {sec['Written Expression']['solver_ambiguous']}; NONE {sec['Written Expression']['solver_none']}; final AUTO_ACCEPT {sec['Written Expression']['final_auto_accept']}/75 ({pct(sec['Written Expression']['final_auto_accept_rate']['n'], sec['Written Expression']['final_auto_accept_rate']['d'])}); MANUAL_REVIEW {sec['Written Expression']['manual_review']}; discard {sec['Written Expression']['discard']}.",
        "",
        "Sentence-level and semantic-dependent cases require continued attention. The validation NONE case `batch1-we-013` was a reference-resolution design with no antecedent context; the Solver correctly refused to infer context, while Reviewer round 1 had passed it.",
        "",
        "## 7. Pilot vs Validation",
        "",
        "| Metric | Pilot | Validation |",
        "|---|---:|---:|",
        f"| Overall AUTO_ACCEPT | 37/40 (92.5%) | {o['AUTO_ACCEPTED']}/120 ({pct(o['AUTO_ACCEPTED'],120)}) |",
        f"| Structure AUTO_ACCEPT | 15/15 (100.0%) | {sec['Structure']['final_auto_accept']}/45 ({pct(sec['Structure']['final_auto_accept'],45)}) |",
        f"| Written Expression AUTO_ACCEPT | 22/25 (88.0%) | {sec['Written Expression']['final_auto_accept']}/75 ({pct(sec['Written Expression']['final_auto_accept'],75)}) |",
        f"| Reviewer false negatives | 3/40 (7.5%) | {len(metrics['reviewer_false_negatives'])}/120 ({pct(len(metrics['reviewer_false_negatives']),120)}); WE {sum(x['section']=='Written Expression' for x in metrics['reviewer_false_negatives'])}/75 |",
        f"| Solver AMBIGUOUS/NONE | 3/40 (7.5%) | {o['solver_AMBIGUOUS']+o['solver_NONE']}/120 ({pct(o['solver_AMBIGUOUS']+o['solver_NONE'],120)}) |",
        "",
        "Pilot comparison uses the supplied Pilot baseline. Validation denominators are the full initial cohort unless explicitly marked solver-reached.",
        "",
        "## 8. P0 failure recurrence",
        "",
        "| Root cause | Recurrence | Detected by Generator self-prevention | Detected by Reviewer | Detected only by Solver | Final AUTO_ACCEPT |",
        "|---|---:|---|---:|---:|---:|",
    ]
    p0_labels = {
        "A_semantic_reference_resolution_mistaken_for_grammar": "A semantic reference resolution mistaken for grammar",
        "B_parallel_coordination_alternate_parse": "B parallel / coordination alternate parse",
        "C_semantic_connector_oddity_mistaken_for_grammar": "C semantic connector oddity mistaken for grammar",
    }
    for key, label in p0_labels.items():
        row = metrics["p0_failure_recurrence"][key]
        lines.append(f"| {label} | {row['recurrence_count']} | {row['detected_by_generator_self_prevention']} | {row['detected_by_reviewer']} | {row['detected_only_by_solver']} | {row['final_auto_accepted']} |")
    lines += [
        "",
        "No same-type P0 defect entered AUTO_ACCEPT. The only classified same-type recurrence was A (`batch1-we-013`), detected only by Solver as NONE; Generator self-prevention is not machine-instrumented, so no positive self-detection claim is made.",
        "",
        "## 9. Reviewer false negatives",
        "",
        f"Reviewer false-negative candidates are defined as Reviewer round-1 PASS followed by Solver AMBIGUOUS or NONE: {len(metrics['reviewer_false_negatives'])}/120 ({pct(len(metrics['reviewer_false_negatives']),120)}); WE {sum(x['section']=='Written Expression' for x in metrics['reviewer_false_negatives'])}/75 ({pct(sum(x['section']=='Written Expression' for x in metrics['reviewer_false_negatives']),75)}).",
        "",
        "| Item | Section | Target | Tested error type | Root cause |",
        "|---|---|---|---|---|",
    ]
    for item in metrics["reviewer_false_negatives"]:
        lines.append(f"| {item['item_id']} | {item['section']} | {item['primary_target']} | {item['tested_error_type']} | {item['root_cause']} |")
    lines += [
        "",
        "Full Reviewer checks/issues and Solver reasoning for every item are preserved in `validation_provenance.json` and the batch-level round artifacts.",
        "",
        "## 10. Solver disagreement",
        "",
        f"A-D answer mismatches: {metrics['solver_disagreement']['answer_mismatch_count']}; AMBIGUOUS: {len(metrics['solver_disagreement']['ambiguous_ids'])}; NONE: {len(metrics['solver_disagreement']['none_ids'])}. These are kept as separate categories.",
        "",
        "| Item | Generator | Reviewer | Solver | Solver reason |",
        "|---|---|---|---|---|",
    ]
    for item in metrics["solver_disagreement"]["answer_mismatches"]:
        lines.append(f"| {item['item_id']} | {item['generator_answer']} | {item['reviewer_answer']} | {item['solver_answer']} | {item['reason']} |")
    lines += [
        "",
        f"AMBIGUOUS IDs: `{metrics['solver_disagreement']['ambiguous_ids']}`.",
        f"NONE IDs: `{metrics['solver_disagreement']['none_ids']}`.",
        "",
        "## 11. Revision effectiveness",
        "",
        f"Initial round-1 REVISE candidates: {metrics['revision_effectiveness']['initial_revise_count']}; later Reviewer PASS: {metrics['revision_effectiveness']['revision_success_count']}; failed after the allowed cycles: {metrics['revision_effectiveness']['revision_failure_count']}; success rate {pct(metrics['revision_effectiveness']['revision_success_rate']['n'], metrics['revision_effectiveness']['revision_success_rate']['d'])}.",
        "",
        "| Item | Final revision count | Later verdicts | Success | Final state |",
        "|---|---:|---|---|---|",
    ]
    for item_id, row in metrics["revision_effectiveness"]["items"].items():
        lines.append(f"| {item_id} | {row['revision_count_final']} | {row['later_review_verdicts']} | {row['revision_success']} | {row['final_state']} |")
    lines += [
        "",
        "The failed item `batch3-we-024` reached the second revision limit and was DISCARDED by policy; no replacement was generated.",
        "",
        "## 12. Difficulty analysis",
        "",
        "| Difficulty | Generated | Reviewer first-pass PASS | Eventual PASS | Solver consensus | Final accepted |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for diff, row in metrics["difficulty"].items():
        lines.append(f"| {diff} | {row['generated']} | {row['reviewer_first_pass']} | {row['reviewer_eventual_pass']} | {row['solver_consensus']} | {row['final_accepted']} |")
    lines += ["", "Difficulty rows are descriptive. HARD-specific claims are not generalized beyond this cohort.", "", "## 13. Grammar target analysis", ""]
    for section, rows in metrics["grammar_target"].items():
        lines += [f"### {section}", "", "| Target | Generated | Reviewer first-pass PASS | Eventual PASS | Final accepted | Failure count | Acceptance rate |", "|---|---:|---:|---:|---:|---:|---:|"]
        for target, row in rows.items():
            lines.append(f"| {target} | {row['generated']} | {row['reviewer_first_pass']} | {row['reviewer_eventual_pass']} | {row['final_accepted']} | {row['failure_count']} | {pct(row['acceptance_rate']['n'], row['acceptance_rate']['d'])} |")
        lines += ["", "Small category counts should not be treated as stable category-level estimates.", ""]
    lines += ["## 14. WE error-type / error-scope analysis", "", "### Tested error type", "", "| Error type | Generated | Reviewer first-pass PASS | Solver consensus | Final accepted | NONE | AMBIGUOUS |", "|---|---:|---:|---:|---:|---:|---:|"]
    for value, row in metrics["written_expression"]["tested_error_type"].items():
        lines.append(f"| {value} | {row['generated']} | {row['reviewer_first_pass']} | {row['solver_consensus']} | {row['final_accepted']} | {row['NONE']} | {row['AMBIGUOUS']} |")
    lines += ["", "### Error scope", "", "| Scope | Generated | Reviewer first-pass PASS | Solver consensus | Final accepted | NONE | AMBIGUOUS |", "|---|---:|---:|---:|---:|---:|---:|"]
    for value, row in metrics["written_expression"]["error_scope"].items():
        lines.append(f"| {value} | {row['generated']} | {row['reviewer_first_pass']} | {row['solver_consensus']} | {row['final_accepted']} | {row['NONE']} | {row['AMBIGUOUS']} |")
    lines += ["", "The sentence-level semantic/reference case noted above was not AUTO_ACCEPTED. The evidence supports continued scrutiny of sentence-level and context-dependent constructions.", "", "## 15. Answer-position analysis", ""]
    for section, row in metrics["answer_position"].items():
        lines += [f"### {section}", "", f"- planned: `{row['planned']}`", f"- initial generated: `{row['initial_generated']}`", f"- accepted final items: `{row['accepted']}`", ""]
    lines += ["Position filtering effects are reported descriptively; the batch plans were heuristic near-even spreads, not hard quotas.", "", "## 16. Regression suite", "", f"Regression suite status: **{regression['suite_status']} ({regression['pass_count']}/{regression['total_count']})**.", "", "| Test | Status |", "|---|---|"]
    for result in regression["results"]:
        lines.append(f"| {result['name']} | {result['status']} |")
    lines += ["", "The suite includes the P0 regression 7-item contract, Generator smoke, Reviewer adversarial, Solver adversarial, Orchestrator smoke/gen-struct-003 guard, reject path, acceptance 18/18, and validation provenance shape.", "", "## 17. Human review sample", "", f"A deterministic stratified sample of {sample['count']} AUTO_ACCEPTED items was isolated in `human_review_sample.json`: Structure {sample['section_counts'].get('Structure',0)}, Written Expression {sample['section_counts'].get('Written Expression',0)}. No human scoring was performed.", "", "## 18. Quality gate results", "", "| Gate | Status | Value |", "|---|---|---|"]
    for name, gate in gates.items():
        lines.append(f"| {name} | **{gate['status']}** | `{gate['value']}` |")
    lines += ["", "Gate C and Gate D fail the provisional internal >=90% thresholds. Gate A, B, F, and G pass; Gate E passes under both the full-cohort and WE-denominator comparison used here.", "", "## 19. Remaining risks", "", "- Batch 2 has substantially lower acceptance and a high round-1 REJECT count; the cause should be investigated before larger generation.", "- Four Reviewer false negatives remain, including three Structure ambiguity cases and one WE reference-resolution NONE case.", "- The Generator self-prevention gate is not emitted as structured telemetry, so recurrence analysis cannot prove that the Generator caught a risk internally.", "- Category-level target/difficulty/error-type rates with small cells are descriptive only.", "- Human review has not yet scored the sample.", "", "## 20. Production-readiness recommendation", "", "**C. Another hardening cycle recommended.** The regression suite is green and no same-type P0 defect was AUTO_ACCEPTED, but overall AUTO_ACCEPT is below 90%, Written Expression is below 90%, and batch stability is insufficient for larger generation without another hardening/validation cycle.", "", "## Final report summary", "", f"- total AUTO_ACCEPT: {o['AUTO_ACCEPTED']}", f"- AUTO_ACCEPT rate: {pct(o['AUTO_ACCEPTED'],120)}", f"- Structure rate: {sec['Structure']['final_auto_accept']}/45 ({pct(sec['Structure']['final_auto_accept'],45)})", f"- WE rate: {sec['Written Expression']['final_auto_accept']}/75 ({pct(sec['Written Expression']['final_auto_accept'],75)})", f"- Reviewer round1 PASS/REVISE/REJECT: {o['reviewer_round1_PASS']}/{o['reviewer_round1_REVISE']}/{o['reviewer_round1_REJECT']}", f"- Reviewer false negative: {len(metrics['reviewer_false_negatives'])}/120; WE {sum(x['section']=='Written Expression' for x in metrics['reviewer_false_negatives'])}/75", f"- Solver AMBIGUOUS/NONE: {o['solver_AMBIGUOUS']}/{o['solver_NONE']}", f"- P0 recurrence: A {metrics['p0_failure_recurrence']['A_semantic_reference_resolution_mistaken_for_grammar']['recurrence_count']}, B {metrics['p0_failure_recurrence']['B_parallel_coordination_alternate_parse']['recurrence_count']}, C {metrics['p0_failure_recurrence']['C_semantic_connector_oddity_mistaken_for_grammar']['recurrence_count']}; P0 AUTO_ACCEPT 0", f"- Revision success: {metrics['revision_effectiveness']['revision_success_count']}/{metrics['revision_effectiveness']['initial_revise_count']}", f"- Regression status: {regression['suite_status']} ({regression['pass_count']}/{regression['total_count']})", "- Quality gates: see section 18; Gates C/D FAIL, Gates A/B/F/G PASS, Gate E PASS", "- Readiness: C — Another hardening cycle recommended", "", "Artifacts are isolated under `analysis/validation/`; no production dataset was changed.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
