"""Build isolated Pilot Batch artifacts and a human-readable report.

This file is post-run analytics only.  The live pipeline remains the existing
orchestrator.py/pilot_driver.py state machine and its agent validators.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "analysis" / "pilot"


def load(name: str, default=None):
    path = PILOT / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(name: str, value) -> None:
    (PILOT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def by_id(items):
    return {item["item_id"]: item for item in items}


def items_from(name: str):
    data = load(name, {"items": []})
    return data.get("items", []) if isinstance(data, dict) else data


def section_of(item_id: str) -> str:
    return "Structure" if item_id.startswith("pilot-struct-") else "Written Expression"


def round_number(name: str) -> int:
    match = re.search(r"round(\d+)", name)
    return int(match.group(1)) if match else 1


def reviewer_rounds():
    result = defaultdict(list)
    for path in sorted(PILOT.glob("round*_reviewer_*.json")):
        for item in items_from(path.name):
            result[item["item_id"]].append(
                {"round": round_number(path.name), "file": path.name, "output": item}
            )
    for values in result.values():
        values.sort(key=lambda x: (x["round"], x["file"]))
    return result


def generator_rounds(initial_by_id):
    result = defaultdict(list)
    for item_id, item in initial_by_id.items():
        result[item_id].append({"round": 1, "file": "round1_generator", "item": item})
    for path in sorted(PILOT.glob("revision_round*.json")):
        for item in items_from(path.name):
            result[item["item_id"]].append(
                {"round": round_number(path.name), "file": path.name, "item": item}
            )
    for values in result.values():
        values.sort(key=lambda x: (x["round"], x["file"]))
    return result


def solver_outputs():
    result = defaultdict(list)
    for path in sorted(PILOT.glob("*.json")):
        if "solver" not in path.stem.lower() or "input" in path.stem.lower():
            continue
        data = load(path.name, {})
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            continue
        for item in data["items"]:
            if "solver_answer" in item:
                result[item["item_id"]].append(
                    {"file": path.name, "output": item}
                )
    return result


def issue_text(issue: dict) -> str:
    return " ".join(
        str(issue.get(key, "")) for key in ("category", "description", "related_check")
    ).lower()


def classify_issue(issue: dict) -> str:
    text = issue_text(issue)
    if "marked_span_not_genuinely_erroneous" in text or "no unambiguous grammatical error" in text:
        return "no_genuine_error"
    if "grammatically_defensible_alternate_reading" in text or "alternate bracketing" in text:
        return "multiple_valid_answers"
    if "second" in text and ("error" in text or "genuine" in text):
        return "second_genuine_error"
    if "no genuine" in text or "no_error" in text or "zero error" in text:
        return "no_genuine_error"
    if "multiple" in text or "two valid" in text or "multiple_valid" in text:
        return "multiple_valid_answers"
    if "marginal" in text and "distractor" in text:
        return "marginal_distractor"
    if "weak" in text and "distractor" in text:
        return "weak_distractor"
    if "unnatural" in text or "naturalness" in text:
        return "unnatural_english"
    if "target" in text and ("mismatch" in text or "alignment" in text):
        return "target_mismatch"
    if "metadata" in text:
        return "metadata_mismatch"
    if "difficulty" in text:
        return "difficulty_mismatch"
    if "scope" in text:
        return "error_scope_mismatch"
    if "source" in text or "similarity" in text:
        return "source_similarity_risk"
    if "no valid" in text or "zero valid" in text:
        return "no_valid_answer"
    return "other"


def reviewer_failure_reasons(reviews):
    reasons = []
    for issue in reviews.get("issues", []):
        reasons.append(classify_issue(issue))
    if reviews.get("detected_error_count") == 0:
        reasons.append("no_genuine_error")
    if isinstance(reviews.get("detected_error_count"), int) and reviews["detected_error_count"] > 1:
        reasons.append("second_genuine_error")
    if reviews.get("source_similarity_risk") == "HIGH":
        reasons.append("source_similarity_risk")
    return list(dict.fromkeys(reasons)) or ["other"]


def first_review_map(reviewers):
    return {
        item_id: sorted(values, key=lambda x: x["round"])[0]["output"]
        for item_id, values in reviewers.items()
        if values
    }


def final_review(item_id, reviewers):
    values = reviewers.get(item_id, [])
    return sorted(values, key=lambda x: x["round"])[-1]["output"] if values else None


def final_solver(item_id, solvers):
    values = solvers.get(item_id, [])
    return values[-1]["output"] if values else None


def answer_consensus(state_item, solver):
    if not solver or solver.get("solver_answer") not in {"A", "B", "C", "D"}:
        return False
    reviewer = state_item.get("reviewer_item") or {}
    generator = state_item.get("generator_item") or {}
    return (
        solver.get("solver_answer") == generator.get("correct_answer")
        and solver.get("solver_answer") == reviewer.get("independent_answer")
        and solver.get("ambiguity_detected") is False
    )


def classify_candidate_failure(state_item, reviewer_values, solver):
    """Return one primary reason plus optional secondary reasons per candidate."""
    reasons = []
    for entry in reviewer_values:
        if entry["output"].get("verdict") != "PASS":
            reasons.extend(reviewer_failure_reasons(entry["output"]))
    if solver and solver.get("solver_answer") == "AMBIGUOUS":
        reasons.append("solver_ambiguous")
    elif solver and solver.get("solver_answer") == "NONE":
        reasons.append("no_valid_answer")
    elif solver and solver.get("solver_answer") in {"A", "B", "C", "D"} and not answer_consensus(state_item, solver):
        reasons.append("solver_disagreement")
    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        reasons = ["other"]
    priority = [
        "solver_ambiguous", "no_valid_answer", "solver_disagreement",
        "multiple_valid_answers", "no_genuine_error", "second_genuine_error",
        "marginal_distractor", "weak_distractor", "target_mismatch",
        "metadata_mismatch", "difficulty_mismatch", "error_scope_mismatch",
        "unnatural_english", "source_similarity_risk", "other",
    ]
    primary = next((reason for reason in priority if reason in reasons), reasons[0])
    return {"primary_failure_reason": primary, "secondary_reasons": [r for r in reasons if r != primary]}


def normalize_plan(plan):
    struct_basis = {
        "primary_target": "DERIVED",
        "subtype": "HEURISTIC",
        "difficulty": "HEURISTIC",
        "correct_answer_position": "HEURISTIC",
        "vocabulary_domain": "HEURISTIC",
        "sentence_length_target_words": "OBSERVED",
        "clause_count_target": "OBSERVED",
        "distractor_error_types": "OBSERVED",
    }
    we_basis = {
        "primary_target": "DERIVED",
        "subtype": "HEURISTIC",
        "tested_error_type": "DERIVED",
        "error_span_type": "HEURISTIC",
        "error_scope": "HEURISTIC",
        "error_location": "HEURISTIC",
        "difficulty": "HEURISTIC",
        "correct_answer_position": "HEURISTIC",
        "vocabulary_domain": "HEURISTIC",
    }
    for slot in plan.get("structure_slots", []):
        slot.setdefault("section", "Structure")
        slot["basis"] = dict(struct_basis)
    for slot in plan.get("written_expression_slots", []):
        slot.setdefault("section", "Written Expression")
        slot["basis"] = dict(we_basis)
    plan["basis_legend"] = {
        "OBSERVED": "Directly informed by analyzed source ranges or modes; guidance only, never a hard quota.",
        "DERIVED": "A pilot slot allocation derived from observed guidance and the 15/25 sample sizes.",
        "HEURISTIC": "A design choice for diversity, clarity, or difficulty; not an observed proportion.",
    }
    plan["distribution_notes"]["quota_policy"] = (
        "OBSERVED values are center-of-gravity guidance. DERIVED/HEURISTIC slot choices are not strict quotas; quality and uniqueness take priority."
    )
    return plan


def make_provenance(plan, state, initial_by_id, generators, reviewers, solvers, base_records):
    slot_by_id = {
        slot.get("item_id"): slot
        for key in ("structure_slots", "written_expression_slots")
        for slot in plan.get(key, [])
    }
    records = []
    for item_id in sorted(initial_by_id):
        current = state.get(item_id, {})
        base = base_records.get(item_id, {"item_id": item_id})
        full = {
            "original_item": initial_by_id[item_id],
            "revisions": [
                entry["item"] for entry in generators.get(item_id, [])[1:]
            ],
            "generator_outputs": generators.get(item_id, []),
            "reviewer_outputs": reviewers.get(item_id, []),
            "solver_outputs": solvers.get(item_id, []),
            "state_history": current.get("state_history", base.get("state_history", [])),
            "final_state": current.get("state", base.get("state")),
            "final_generator_item": current.get("generator_item"),
            "final_reviewer_item": current.get("reviewer_item"),
            "final_solver_item": current.get("solver_item"),
            "batch_slot": slot_by_id.get(item_id),
        }
        record = dict(base)
        had_reviewer_failure = any(
            entry["output"].get("verdict") != "PASS"
            for entry in reviewers.get(item_id, [])
        )
        if current.get("state") != "ACCEPTED" or had_reviewer_failure:
            record["failure_classification"] = classify_candidate_failure(
                current, reviewers.get(item_id, []), final_solver(item_id, solvers)
            )
        record["candidate_provenance"] = full
        records.append(record)
    return records


def pct(n, d):
    return f"{(100*n/d):.1f}%" if d else "n/a"


def table_rows(counter, keys=None):
    keys = keys or sorted(counter)
    return "\n".join(f"| {k} | {counter.get(k, 0)} |" for k in keys)


def build_metrics(plan, state, initial_by_id, reviewers, solvers, records):
    first = first_review_map(reviewers)
    initial_n = len(initial_by_id)
    accepted = [item_id for item_id, item in state.items() if item.get("state") == "ACCEPTED"]
    manual = [item_id for item_id, item in state.items() if item.get("state") == "MANUAL_REVIEW"]
    discarded = [item_id for item_id, item in state.items() if item.get("state") == "DISCARDED"]
    solver_by_id = {item_id: final_solver(item_id, solvers) for item_id in initial_by_id}
    solver_by_id = {k: v for k, v in solver_by_id.items() if v}
    consensus_ids = [item_id for item_id, item in solver_by_id.items() if answer_consensus(state[item_id], item)]
    ambiguous = [k for k, v in solver_by_id.items() if v.get("solver_answer") == "AMBIGUOUS"]
    none = [k for k, v in solver_by_id.items() if v.get("solver_answer") == "NONE"]
    disagreement = [
        k for k, v in solver_by_id.items()
        if v.get("solver_answer") in {"A", "B", "C", "D"} and not answer_consensus(state[k], v)
    ]
    low = [k for k, v in solver_by_id.items() if v.get("confidence") == "LOW"]
    first_verdicts = Counter(v.get("verdict") for v in first.values())
    all_verdicts = Counter(
        entry["output"].get("verdict")
        for values in reviewers.values() for entry in values
    )
    metrics = {
        "overall": {
            "initial_generated": initial_n,
            "generator_validation_pass": sum("REVIEWING" in item.get("state_history", []) for item in state.values()),
            "reviewer_PASS": first_verdicts.get("PASS", 0),
            "reviewer_REVISE": first_verdicts.get("REVISE", 0),
            "reviewer_REJECT": first_verdicts.get("REJECT", 0),
            "reviewer_all_rounds": dict(all_verdicts),
            "reviewer_submission_count": sum(len(v) for v in reviewers.values()),
            "solver_reached": len(solver_by_id),
            "solver_consensus": len(consensus_ids),
            "solver_disagreement": len(disagreement),
            "solver_AMBIGUOUS": len(ambiguous),
            "solver_NONE": len(none),
            "solver_LOW_confidence": len(low),
            "AUTO_ACCEPTED": len(accepted),
            "MANUAL_REVIEW": len(manual),
            "DISCARDED": len(discarded),
            "REJECTED": sum(item.get("state") == "REJECTED" for item in state.values()),
        },
        "rates": {
            "generator_schema_pass_rate": {"n": sum("REVIEWING" in item.get("state_history", []) for item in state.values()), "d": initial_n},
            "reviewer_first_pass_rate": {"n": first_verdicts.get("PASS", 0), "d": initial_n},
            "reviewer_revise_rate": {"n": first_verdicts.get("REVISE", 0), "d": initial_n},
            "reviewer_reject_rate": {"n": first_verdicts.get("REJECT", 0), "d": initial_n},
            "solver_consensus_rate": {"n": len(consensus_ids), "d": len(solver_by_id)},
            "final_auto_accept_rate": {"n": len(accepted), "d": initial_n},
        },
        "solver_ids": {"consensus": consensus_ids, "disagreement": disagreement, "ambiguous": ambiguous, "none": none, "low_confidence": low},
    }
    section = {}
    for sec in ("Structure", "Written Expression"):
        ids = [k for k, v in initial_by_id.items() if v.get("section") == sec]
        sec_accepted = [k for k in accepted if initial_by_id[k].get("section") == sec]
        sec_first = Counter(first[k].get("verdict") for k in ids if k in first)
        section[sec] = {
            "generated": len(ids),
            "reviewer_PASS": sec_first.get("PASS", 0),
            "reviewer_REVISE": sec_first.get("REVISE", 0),
            "reviewer_REJECT": sec_first.get("REJECT", 0),
            "first_pass_rate": {"n": sec_first.get("PASS", 0), "d": len(ids)},
            "final_accepted": len(sec_accepted),
            "final_acceptance_rate": {"n": len(sec_accepted), "d": len(ids)},
        }
    metrics["section"] = section
    return metrics


def build_analyses(plan, state, initial_by_id, reviewers, records):
    first = first_review_map(reviewers)
    accepted = {k for k, v in state.items() if v.get("state") == "ACCEPTED"}
    targets = sorted({v.get("primary_target") for v in initial_by_id.values()})
    target_rows = {}
    for target in targets:
        ids = [k for k, v in initial_by_id.items() if v.get("primary_target") == target]
        target_rows[target] = {
            "generated": len(ids),
            "reviewer_PASS": sum(first.get(k, {}).get("verdict") == "PASS" for k in ids),
            "final_ACCEPTED": sum(k in accepted for k in ids),
            "failure_count": sum(k not in accepted for k in ids),
            "acceptance_rate": {"n": sum(k in accepted for k in ids), "d": len(ids)},
        }
    difficulties = {}
    for diff in ("EASY", "MEDIUM", "HARD"):
        ids = [k for k, v in initial_by_id.items() if v.get("difficulty") == diff]
        solver_consensus = sum(
            k in accepted and (state[k].get("solver_item") or {}).get("solver_answer") == (state[k].get("generator_item") or {}).get("correct_answer")
            for k in ids
        )
        difficulties[diff] = {
            "generated": len(ids),
            "reviewer_PASS": sum(first.get(k, {}).get("verdict") == "PASS" for k in ids),
            "solver_consensus": solver_consensus,
            "final_accepted": sum(k in accepted for k in ids),
        }
    positions = {}
    for sec in ("Structure", "Written Expression"):
        ids = [k for k, v in initial_by_id.items() if v.get("section") == sec]
        planned = Counter(
            next((s.get("correct_answer_position") for group in ("structure_slots", "written_expression_slots") for s in plan.get(group, []) if s.get("item_id") == k), "?")
            for k in ids
        )
        generated = Counter(initial_by_id[k].get("correct_answer") for k in ids)
        accepted_pos = Counter((state[k].get("generator_item") or {}).get("correct_answer") for k in accepted if initial_by_id[k].get("section") == sec)
        positions[sec] = {"planned_generated": dict(planned), "generated_actual": dict(generated), "accepted": dict(accepted_pos)}
    domains = Counter(v.get("vocabulary_domain") for v in initial_by_id.values())
    domain_rejects = Counter(
        v.get("vocabulary_domain") for k, v in initial_by_id.items() if state.get(k, {}).get("state") in {"REJECTED", "DISCARDED", "MANUAL_REVIEW"}
    )
    reviewer_failure_events = Counter()
    reviewer_failure_items = defaultdict(set)
    for item_id, values in reviewers.items():
        for entry in values:
            if entry["output"].get("verdict") != "PASS":
                reasons = reviewer_failure_reasons(entry["output"])
                for reason in reasons:
                    reviewer_failure_events[reason] += 1
                    reviewer_failure_items[reason].add(item_id)
    revised_ids = sorted({item_id for item_id, values in reviewers.items() if len(values) > 1})
    revision_by_reason = {}
    for reason, ids in reviewer_failure_items.items():
        revised = sorted(set(ids) & set(revised_ids))
        if ids:
            revision_by_reason[reason] = {"items_with_failure": len(ids), "revised_items": len(revised), "revision_improved": sum(any(e["output"].get("verdict") == "PASS" for e in reviewers[i][1:]) for i in revised)}
    revision_success = sum(any(e["output"].get("verdict") == "PASS" for e in reviewers[i][1:]) for i in revised_ids)
    final_failure_primary = Counter(
        record.get("failure_classification", {}).get("primary_failure_reason", "other")
        for record in records
        if record.get("state") != "ACCEPTED"
    )
    analyses = {
        "grammar_target": target_rows,
        "difficulty": difficulties,
        "answer_position": positions,
        "domain": {"topic_diversity": len(domains), "counts": dict(domains), "repeated_domains": {k: v for k, v in domains.items() if v > 1}, "domain_nonaccepted": dict(domain_rejects)},
        "reviewer_failure_reasons": {"event_counts": dict(reviewer_failure_events), "item_counts": {k: len(v) for k, v in reviewer_failure_items.items()}, "primary_reason_order": [k for k, _ in reviewer_failure_events.most_common()]},
        "final_failure_taxonomy": {
            "primary_counts": dict(final_failure_primary),
            "affected_final_nonaccepted": sum(final_failure_primary.values()),
        },
        "revision_effectiveness": {
            "revised_item_count": len(revised_ids),
            "revision_items": {i: {"attempt_count": len(reviewers[i]) - 1, "after_revision_PASS": any(e["output"].get("verdict") == "PASS" for e in reviewers[i][1:]), "final_verdict": reviewers[i][-1]["output"].get("verdict")} for i in revised_ids},
            "revision_success_count": revision_success,
            "revision_failed_count": len(revised_ids) - revision_success,
            "revision_success_rate": {"n": revision_success, "d": len(revised_ids)},
            "by_failure_reason": revision_by_reason,
        },
    }
    return analyses


def report_md(plan, metrics, analyses, state):
    o = metrics["overall"]
    r = metrics["rates"]
    sec = metrics["section"]
    failures = analyses["reviewer_failure_reasons"]["event_counts"]
    domain = analyses["domain"]
    rev = analyses["revision_effectiveness"]
    lines = [
        "# TOEFL ITP Grammar Pipeline — Pilot Batch Report",
        "",
        "> Scope: isolated Pilot Batch only (15 Structure + 25 Written Expression). No production DB insert, site connection, production merge, or mass generation was performed.",
        "",
        "## 1. Executive summary",
        "",
        f"The initial cohort contained **{o['initial_generated']}** candidates. **{o['AUTO_ACCEPTED']}** reached AUTO_ACCEPTED ({pct(o['AUTO_ACCEPTED'], o['initial_generated'])}); {o['MANUAL_REVIEW']} went to MANUAL_REVIEW, {o['DISCARDED']} were DISCARDED, and {o['REJECTED']} were REJECTED. This is a small n=40 pilot: rates are operational estimates for finding pipeline and quality failures, not stable category-level conclusions.",
        "",
        "## 2. Pipeline totals",
        "",
        "| Metric | Count | Denominator / definition |", "|---|---:|---|",
        f"| Initial generated | {o['initial_generated']} | initial cohort |",
        f"| Generator schema validation pass | {o['generator_validation_pass']} | / {o['initial_generated']} initial candidates |",
        f"| Reviewer PASS (round 1) | {o['reviewer_PASS']} | / {o['initial_generated']} |",
        f"| Reviewer REVISE (round 1) | {o['reviewer_REVISE']} | / {o['initial_generated']} |",
        f"| Reviewer REJECT (round 1) | {o['reviewer_REJECT']} | / {o['initial_generated']} |",
        f"| Solver reached | {o['solver_reached']} | candidates after Reviewer PASS |",
        f"| Solver consensus | {o['solver_consensus']} | / {o['solver_reached']} solver outputs; answer agrees with Generator and Reviewer |",
        f"| Solver disagreement | {o['solver_disagreement']} | answer A-D but not all three-way agreement |",
        f"| Solver AMBIGUOUS / NONE | {o['solver_AMBIGUOUS']} / {o['solver_NONE']} | solver outputs |",
        f"| Solver LOW confidence | {o['solver_LOW_confidence']} | solver outputs |",
        f"| AUTO_ACCEPTED | {o['AUTO_ACCEPTED']} | / {o['initial_generated']} initial candidates |",
        f"| MANUAL_REVIEW | {o['MANUAL_REVIEW']} | final state |",
        f"| DISCARDED | {o['DISCARDED']} | final state |",
        "",
        "Rates (all denominators are explicit):",
        "",
        f"- Generator schema pass: {pct(r['generator_schema_pass_rate']['n'], r['generator_schema_pass_rate']['d'])} ({r['generator_schema_pass_rate']['n']}/{r['generator_schema_pass_rate']['d']}).",
        f"- Reviewer first-pass: {pct(r['reviewer_first_pass_rate']['n'], r['reviewer_first_pass_rate']['d'])}; REVISE {pct(r['reviewer_revise_rate']['n'], r['reviewer_revise_rate']['d'])}; REJECT {pct(r['reviewer_reject_rate']['n'], r['reviewer_reject_rate']['d'])} — each / {r['reviewer_first_pass_rate']['d']} initial candidates.",
        f"- Solver consensus: {pct(r['solver_consensus_rate']['n'], r['solver_consensus_rate']['d'])} ({r['solver_consensus_rate']['n']}/{r['solver_consensus_rate']['d']} solver-reached).",
        f"- Final auto-accept: {pct(r['final_auto_accept_rate']['n'], r['final_auto_accept_rate']['d'])} ({r['final_auto_accept_rate']['n']}/{r['final_auto_accept_rate']['d']} initial candidates).",
        "",
        "## 3. Structure results",
        "",
        f"Structure: first-pass {pct(sec['Structure']['first_pass_rate']['n'], sec['Structure']['first_pass_rate']['d'])} ({sec['Structure']['reviewer_PASS']}/{sec['Structure']['generated']}); final acceptance {pct(sec['Structure']['final_acceptance_rate']['n'], sec['Structure']['final_acceptance_rate']['d'])} ({sec['Structure']['final_accepted']}/{sec['Structure']['generated']}).",
        "",
        "## 4. Written Expression results",
        "",
        f"Written Expression: first-pass {pct(sec['Written Expression']['first_pass_rate']['n'], sec['Written Expression']['first_pass_rate']['d'])} ({sec['Written Expression']['reviewer_PASS']}/{sec['Written Expression']['generated']}); final acceptance {pct(sec['Written Expression']['final_acceptance_rate']['n'], sec['Written Expression']['final_acceptance_rate']['d'])} ({sec['Written Expression']['final_accepted']}/{sec['Written Expression']['generated']}).",
        "",
        "## 5. Reviewer failure reasons",
        "",
        "Counts below are failure events across Reviewer submissions, including repaired REVISE items; one item can contribute secondary reasons. The primary reason is retained per failure item in provenance.",
        "",
        "Final non-accepted candidate taxonomy:",
        "",
        "| Primary failure reason | Final candidate count |",
        "|---|---:|",
    ]
    for reason, count in sorted(analyses["final_failure_taxonomy"]["primary_counts"].items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {reason} | {count} |")
    lines += [
        "",
        "Reviewer failure events:",
        "",
        "| Reason | Failure events | Affected items |", "|---|---:|---:|",
    ]
    for reason, count in sorted(failures.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {reason} | {count} | {analyses['reviewer_failure_reasons']['item_counts'].get(reason, 0)} |")
    lines += [
        "",
        "## 6. Solver disagreement results",
        "",
        f"Solver outputs: consensus {o['solver_consensus']}, answer disagreement {o['solver_disagreement']}, AMBIGUOUS {o['solver_AMBIGUOUS']}, NONE {o['solver_NONE']}, LOW confidence {o['solver_LOW_confidence']}. AMBIGUOUS/NONE were not forced into an answer; the existing Orchestrator routing was used.",
        "",
        "## 7. Revision effectiveness",
        "",
        f"{rev['revised_item_count']} initial items were revised. Revision success was {rev['revision_success_count']}/{rev['revision_effectiveness']['d'] if 'revision_effectiveness' in rev else rev['revised_item_count']} ({pct(rev['revision_success_count'], rev['revised_item_count'])}), defined as a later Reviewer PASS. Failed-after-revision count: {rev['revision_failed_count']}.",
        "",
        "| Item | Revision attempts | After-revision PASS | Final verdict |", "|---|---:|---|---|",
    ]
    for item_id, row in rev["revision_items"].items():
        lines.append(f"| {item_id} | {row['attempt_count']} | {'yes' if row['after_revision_PASS'] else 'no'} | {row['final_verdict']} |")
    lines += [
        "",
        "## 8. Grammar-target analysis",
        "",
        "| Primary target | Generated | Reviewer PASS | Final accepted | Failure count | Acceptance rate |", "|---|---:|---:|---:|---:|---:|",
    ]
    for target, row in analyses["grammar_target"].items():
        lines.append(f"| {target} | {row['generated']} | {row['reviewer_PASS']} | {row['final_ACCEPTED']} | {row['failure_count']} | {pct(row['acceptance_rate']['n'], row['acceptance_rate']['d'])} |")
    lines += [
        "",
        "Category samples are small (often 1–3 items); no category-level difficulty conclusion is warranted.",
        "",
        "## 9. Difficulty analysis",
        "",
        "| Difficulty | Generated | Reviewer PASS | Solver consensus | Final accepted |", "|---|---:|---:|---:|---:|",
    ]
    for diff, row in analyses["difficulty"].items():
        lines.append(f"| {diff} | {row['generated']} | {row['reviewer_PASS']} | {row['solver_consensus']} | {row['final_accepted']} |")
    lines += [
        "",
        "The HARD row is descriptive only; this pilot does not support a general claim about hard-item generation difficulty.",
        "",
        "## 10. Answer-position distribution",
        "",
    ]
    for section, row in analyses["answer_position"].items():
        lines += [f"### {section}", "", f"- Planned/generated positions: `{row['planned_generated']}`; generated actual positions: `{row['generated_actual']}`; accepted positions: `{row['accepted']}`.", ""]
    lines += [
        "Accepted-position skew is reported against the initial planned/generated distribution; with n=15 and n=25, small changes are not statistically meaningful.",
        "",
        "## 11. Vocabulary-domain diversity",
        "",
        f"{domain['topic_diversity']} vocabulary domains were used. Counts: `{domain['counts']}`. Repeated domains: `{domain['repeated_domains']}`. Non-accepted candidates by domain: `{domain['domain_nonaccepted']}`. These are descriptive diagnostics, not evidence of domain-specific quality differences.",
        "",
        "## 12. Manual review items",
        "",
        f"Final MANUAL_REVIEW count: {o['MANUAL_REVIEW']}. See `pilot_manual_review.json` and the existing `analysis/manual_review_queue.json`; no manual decision was auto-resolved.",
        "",
        "## 13. Representative failure patterns",
        "",
        "Observed patterns are recorded from Reviewer issue text and Orchestrator outcomes. Typical pilot signals include ambiguous alternate parses, non-genuine Written Expression errors, target/metadata mismatch, and solver disagreement. The exact item-level evidence is preserved in `pilot_provenance.json` and `pilot_failure_items.json`.",
        "",
        "## 14. Recommended Generator improvements",
        "",
        "- Add a pre-generation ambiguity check for alternate constituent bracketing and reduced-relative parses, especially for distractors and ordinal + infinitive constructions.",
        "- Strengthen the Written Expression rule that the marked span must be unambiguously ungrammatical under ordinary edited-English readings; avoid complement choices with legitimate noun-object readings.",
        "- Add a taxonomy-alignment gate for fronted-negative inversion (for example, `Not only ...`) so it is not labeled as `CLAUSE_STRUCTURE`.",
        "- Use a second-error audit for Written Expression items before submission, while preserving the Reviewer as the independent quality authority.",
        "- Do not automatically change Generator prompts/specification from this report; these are recommendations for the next engineering decision.",
        "",
        "## 15. Larger-scale generation readiness",
        "",
        "**Not ready for unbounded larger-scale generation yet.** The pipeline mechanics completed a real isolated end-to-end path, but the pilot is small and any non-trivial REVISE/manual/discard rate, solver disagreement, or taxonomy/ambiguity pattern should be addressed and re-piloted before scaling. No production deployment was performed.",
        "",
        "## Artifact and provenance notes",
        "",
        "All initial candidates remain in `pilot_initial_items.json`. `pilot_provenance.json` retains original item text, revisions, every available Reviewer/Solver output, state history, final state, slot plan, and the Orchestrator QA record. Failed candidates were not deleted.",
        "",
        "Generated by `analysis/pilot/build_pilot_artifacts.py` after the existing Orchestrator finalized the batch.",
    ]
    return "\n".join(lines) + "\n"


def main():
    initial_struct = items_from("round1_generator_structure.json")
    initial_we = items_from("round1_generator_we.json")
    initial = initial_struct + initial_we
    initial_by_id = by_id(initial)
    save("pilot_initial_items.json", {"items": initial})

    plan = normalize_plan(load("pilot_batch_plan.json", {}))
    save("pilot_batch_plan.json", plan)
    state = load("candidates_state.json", {})
    reviewers = reviewer_rounds()
    generators = generator_rounds(initial_by_id)
    solvers = solver_outputs()
    base = by_id((load("pilot_provenance.json", {"items": []}) or {}).get("items", []))
    records = make_provenance(plan, state, initial_by_id, generators, reviewers, solvers, base)
    save("pilot_provenance.json", {
        "pipeline_version": (load("orchestrator_config_snapshot.json", {}) or {}).get("pipeline_version", "1.0.0"),
        "pilot_scope": "isolated pilot; no production DB/site/dataset writes",
        "initial_cohort_size": len(initial),
        "replacement_policy": "none in the initial-cohort measurement; replacements, if any, must be a separate bounded cohort",
        "items": records,
        "batch_summary": {"planned": len(initial), "accepted": sum(x.get("state") == "ACCEPTED" for x in records)},
    })

    accepted = [x.get("accepted_item") for x in records if x.get("state") == "ACCEPTED" and x.get("accepted_item")]
    failures = [x for x in records if x.get("state") != "ACCEPTED"]
    save("pilot_accepted_items.json", {"items": accepted})
    save("pilot_failure_items.json", {"items": failures})
    manual = []
    for record in records:
        if record.get("state") != "MANUAL_REVIEW":
            continue
        full = record.get("candidate_provenance", {})
        generator = full.get("final_generator_item") or {}
        reviewer = full.get("final_reviewer_item") or {}
        solver = full.get("final_solver_item") or {}
        consensus = (record.get("qa_audit") or {}).get("consensus") or {}
        entry = {
            "item_id": record["item_id"],
            "section": record.get("section"),
            "item": generator,
            "disagreement_reasons": consensus.get("disagreement_reasons", []),
            "generator_answer": generator.get("correct_answer"),
            "reviewer_answer": reviewer.get("independent_answer"),
            "solver_answer": solver.get("solver_answer"),
            "solver_confidence": solver.get("confidence"),
            "issues": reviewer.get("issues", []),
            "state_history": record.get("state_history", []),
            "possible_actions": ["ACCEPT", "REGENERATE", "DISCARD"],
        }
        if record.get("failure_classification"):
            entry["failure_classification"] = record["failure_classification"]
        manual.append(entry)
    save("pilot_manual_review.json", {"items": manual})

    metrics = build_metrics(plan, state, initial_by_id, reviewers, solvers, records)
    analyses = build_analyses(plan, state, initial_by_id, reviewers, records)
    save("pilot_metrics.json", {"metrics": metrics, "analyses": analyses})
    (PILOT / "PILOT_BATCH_REPORT.md").write_text(report_md(plan, metrics, analyses, state), encoding="utf-8")


if __name__ == "__main__":
    main()
