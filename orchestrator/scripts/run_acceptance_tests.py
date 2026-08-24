"""Orchestrator acceptance test suite (spec section 21).

Runs the three replay scripts (smoke / adversarial / reject-path) plus a
set of direct unit tests against the Orchestrator's own decision logic
(evaluate_consensus, retry limits, leakage guard, failure classification)
for scenarios the existing fixtures don't happen to exercise (e.g. a
solver AMBIGUOUS/NONE/LOW-confidence case reaching the consensus stage at
all, which requires a Reviewer PASS - none of the existing PASS fixtures
have a disagreeing Solver, so those branches are tested directly against
evaluate_consensus with small synthetic inputs rather than through a full
fixture replay).

Populates analysis/manual_review_queue.json with any MANUAL_REVIEW items
produced (from the synthetic disagreement cases, since none of the current
real fixtures produce a disagreement).

Usage:
    python run_acceptance_tests.py
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import (  # noqa: E402
    REPO_ROOT,
    Candidate,
    State,
    SystemCallError,
    append_manual_review_queue,
    blind_for_solver,
    build_generator_feedback,
    build_provenance_record,
    evaluate_consensus,
    leakage_guard,
    load_config,
    load_versions,
    parse_agent_json,
    process_generation_output,
    process_review_output,
    process_solver_stage,
    run_schema_validator,
)

RESULTS = []  # (criterion_number, description, passed: bool, detail: str)


def check(n: int, desc: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((n, desc, condition, detail))
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] #{n} {desc}" + (f" -- {detail}" if detail else ""))


def run_script(relpath: str, output_dir: Path | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(REPO_ROOT / relpath)]
    if output_dir is not None:
        output_names = {
            "orchestrator/scripts/run_smoke_test.py": "orchestrator_smoke_test.json",
            "orchestrator/scripts/run_adversarial_test.py": "orchestrator_adversarial_test.json",
            "orchestrator/scripts/run_reject_path_test.py": "orchestrator_reject_path_test.json",
        }
        output_name = output_names.get(relpath)
        if output_name is not None:
            command.append(str(output_dir / output_name))
    return subprocess.run(
        command,
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def base_generator_item(section: str = "Structure") -> dict:
    if section == "Structure":
        return {
            "item_id": "synthetic-struct-001",
            "section": "Structure",
            "primary_target": "RELATIVE_CLAUSES",
            "subtype": "test",
            "secondary_features": [],
            "difficulty": "MEDIUM",
            "vocabulary_domain": "test domain",
            "stem": "This is a synthetic stem ____.",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "correct_answer": "C",
            "answer_explanation": "test",
            "distractor_rationales": {"A": "x", "B": "x", "C": "correct", "D": "x"},
        }
    return {
        "item_id": "synthetic-we-001",
        "section": "Written Expression",
        "primary_target": "WORD_CLASS_FORM",
        "subtype": "test",
        "secondary_features": [],
        "tested_error_type": "incorrect_part_of_speech",
        "error_scope": "local",
        "difficulty": "MEDIUM",
        "vocabulary_domain": "test domain",
        "sentence": "This is a synthetic sentence.",
        "marked_parts": {"A": "This", "B": "is a", "C": "synthetic", "D": "sentence."},
        "correct_answer": "C",
        "minimal_correction": "synthesized",
        "answer_explanation": "test",
    }


def base_reviewer_item(generator_answer: str = "C", **overrides) -> dict:
    item = {
        "item_id": "synthetic-struct-001",
        "section": "Structure",
        "verdict": "PASS",
        "critical_failure": False,
        "independent_answer": generator_answer,
        "generator_answer": generator_answer,
        "answer_match": True,
        "reviewer_difficulty": "MEDIUM",
        "generator_difficulty": "MEDIUM",
        "difficulty_mismatch": False,
        "checks": {
            "grammar_validity": "PASS", "answer_uniqueness": "PASS", "target_alignment": "PASS",
            "naturalness": "PASS", "toefl_style": "PASS", "distractor_quality": "PASS",
            "metadata_consistency": "PASS",
        },
        "issues": [],
        "revision_requirements": [],
        "source_similarity_risk": "LOW",
    }
    item.update(overrides)
    return item


def base_solver_item(answer: str = "C", **overrides) -> dict:
    item = {
        "item_id": "synthetic-struct-001",
        "section": "Structure",
        "solver_answer": answer,
        "confidence": "HIGH",
        "reason": "test",
        "ambiguity_detected": answer in {"AMBIGUOUS", "NONE"},
    }
    item.update(overrides)
    return item


def main(output_dir: Path | None = None) -> int:
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    if output_dir is not None:
        # Acceptance replay must be side-effect free for tracked fixtures. The
        # synthetic manual-review entry belongs beside the other temporary
        # replay artifacts, never in analysis/manual_review_queue.json.
        config["paths"] = dict(config["paths"])
        config["paths"]["manual_review_queue"] = str((output_dir / "manual_review_queue.json").resolve())
    versions = load_versions(config)

    # -- #12 schema validation PASS, plus drives #1/#2/#9/#10/#4/#13 -------
    smoke = run_script("orchestrator/scripts/run_smoke_test.py", output_dir)
    adversarial = run_script("orchestrator/scripts/run_adversarial_test.py", output_dir)
    reject_path = run_script("orchestrator/scripts/run_reject_path_test.py", output_dir)

    check(12, "schema validation PASS for all valid fixtures (replay scripts exit 0)",
          smoke.returncode == 0 and adversarial.returncode == 0 and reject_path.returncode == 0,
          f"smoke_rc={smoke.returncode} adversarial_rc={adversarial.returncode} reject_rc={reject_path.returncode}")

    output_paths = {
        "orchestrator_smoke_test.json": (output_dir or REPO_ROOT / "analysis") / "orchestrator_smoke_test.json",
        "orchestrator_adversarial_test.json": (output_dir or REPO_ROOT / "analysis") / "orchestrator_adversarial_test.json",
        "orchestrator_reject_path_test.json": (output_dir or REPO_ROOT / "analysis") / "orchestrator_reject_path_test.json",
    }
    prov_checks = [
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "orchestrator" / "scripts" / "validate_provenance.py"),
             str(output_paths[fname])],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        for fname in output_paths
    ]
    check("12b", "Orchestrator's own provenance output passes its shape validator (validate_provenance.py)",
          all(p.returncode == 0 for p in prov_checks),
          f"returncodes={[p.returncode for p in prov_checks]}")

    smoke_data = json.loads(output_paths["orchestrator_smoke_test.json"].read_text(encoding="utf-8"))
    adversarial_data = json.loads(output_paths["orchestrator_adversarial_test.json"].read_text(encoding="utf-8"))
    reject_data = json.loads(output_paths["orchestrator_reject_path_test.json"].read_text(encoding="utf-8"))

    smoke_by_id = {i["item_id"]: i for i in smoke_data["items"]}

    check(1, "Reviewer PASS-only items reach SOLVING",
          all(State.SOLVING in smoke_by_id[i]["qa_audit"]["state_history"]
              for i in ["gen-struct-001", "gen-struct-002", "gen-we-001", "gen-we-002", "gen-we-003"]))

    check(2, "REVISE item (gen-struct-003) never sent directly to Solver",
          State.SOLVING not in smoke_by_id["gen-struct-003"]["qa_audit"]["state_history"]
          and "gen-struct-003: solver fixture data exists but was NOT sent to Solver"
          in " ".join(smoke_data["solver_skip_log"]))

    check(3, "REJECT items never sent into the revision loop",
          all(State.REVISE_REQUIRED not in r["qa_audit"]["state_history"] for r in reject_data["items"])
          and all(r["state"] == "REJECTED" for r in reject_data["items"]))

    # -- #4 leakage check ----------------------------------------------------
    struct_item = base_generator_item("Structure")
    blinded = blind_for_solver(config, struct_item)
    ok, problems = leakage_guard(blinded, "Structure")
    check(4, "Solver input contains only the allowlisted fields (real create_solver_input.py, real leakage guard)",
          ok and set(blinded.keys()) == {"item_id", "section", "stem", "options"},
          f"blinded_keys={sorted(blinded.keys())} problems={problems}")

    # -- #5 three-way consensus only ----------------------------------------
    good_consensus = evaluate_consensus(
        base_generator_item("Structure"), base_reviewer_item("C"), base_solver_item("C"), config
    )
    mismatched = evaluate_consensus(
        base_generator_item("Structure"), base_reviewer_item("C"), base_solver_item("D"), config
    )
    check(5, "AUTO_ACCEPT only when generator/reviewer/solver all agree; a single mismatch blocks it",
          good_consensus.auto_accept is True and mismatched.auto_accept is False
          and mismatched.routing == State.MANUAL_REVIEW,
          f"good={good_consensus.routing} mismatched={mismatched.routing} reasons={mismatched.disagreement_reasons}")

    # -- #6/#7/#8 non-consensus routing --------------------------------------
    ambiguous = evaluate_consensus(
        base_generator_item("Structure"), base_reviewer_item("C"),
        base_solver_item("AMBIGUOUS", confidence="MEDIUM"), config,
    )
    check(6, "Solver AMBIGUOUS is never AUTO_ACCEPTed",
          not ambiguous.auto_accept and ambiguous.routing == State.MANUAL_REVIEW,
          f"routing={ambiguous.routing}")

    none_case = evaluate_consensus(
        base_generator_item("Structure"), base_reviewer_item("C"),
        base_solver_item("NONE", confidence="HIGH"), config,
    )
    check(7, "Solver NONE is never AUTO_ACCEPTed",
          not none_case.auto_accept and none_case.routing == State.DISCARDED,
          f"routing={none_case.routing}")

    low_conf = evaluate_consensus(
        base_generator_item("Structure"), base_reviewer_item("C"),
        base_solver_item("C", confidence="LOW"), config,
    )
    check(8, "Solver confidence LOW is never AUTO_ACCEPTed even if the answer matches",
          not low_conf.auto_accept and low_conf.routing == State.MANUAL_REVIEW
          and "solver_confidence_low" in low_conf.disagreement_reasons,
          f"routing={low_conf.routing} reasons={low_conf.disagreement_reasons}")

    high_similarity = evaluate_consensus(
        base_generator_item("Structure"), base_reviewer_item("C", source_similarity_risk="HIGH"),
        base_solver_item("C"), config,
    )
    check("8b", "Reviewer source_similarity_risk=HIGH is never AUTO_ACCEPTed",
          not high_similarity.auto_accept and high_similarity.routing == State.MANUAL_REVIEW,
          f"routing={high_similarity.routing} reasons={high_similarity.disagreement_reasons}")

    check(9, "gen-struct-003 is never AUTO_ACCEPTed (regression case, real Reviewer REVISE data)",
          smoke_by_id["gen-struct-003"]["state"] != State.ACCEPTED,
          f"final_state={smoke_by_id['gen-struct-003']['state']}")

    check(10, "Adversarial item ACCEPT rate is 0%",
          adversarial_data["accept_count"] == 0 and adversarial_data["accept_rate"] == 0.0,
          f"accept_count={adversarial_data['accept_count']}/{adversarial_data['total_count']}")

    # -- #11 retry limit ------------------------------------------------------
    candidate = Candidate(item_id="retry-test-001", concept_id="retry-test-001", section="Structure")
    candidate.generator_item = base_generator_item("Structure")
    candidate.state = State.REVIEWING
    for cycle in range(3):
        candidate.reviewer_item = base_reviewer_item("C", verdict="REVISE", critical_failure=True,
                                                       issues=[{"severity": "MAJOR", "category": "test",
                                                                 "description": "test", "related_check": "distractor_quality"}],
                                                       revision_requirements=["fix it"])
        candidate = process_review_output(candidate, config)
        if candidate.state == State.REVISE_REQUIRED:
            candidate.state = State.REVIEWING  # simulate: sent back to Generator, regenerated, re-reviewed
    check(11, "retry limit (max_revision_cycles) is enforced: 3rd consecutive REVISE -> DISCARDED",
          candidate.revision_count == 3 and candidate.state == State.DISCARDED,
          f"revision_count={candidate.revision_count} state={candidate.state} "
          f"max_revision_cycles={config['retry_policy']['max_revision_cycles']}")

    real_revise_reviewer = json.loads(
        (REPO_ROOT / "analysis" / "reviewer_smoke_test.json").read_text(encoding="utf-8")
    )
    real_revise_item = next(
        i for i in real_revise_reviewer["items"] if i["item_id"] == "gen-struct-003"
    )
    feedback = build_generator_feedback(real_revise_item)
    check("5c", "Generator-revision feedback (real gen-struct-003 REVISE data) exposes only "
                "issues/revision_requirements, never independent_answer/verdict/checks",
          set(feedback.keys()) == {"item_id", "issues", "revision_requirements"}
          and feedback["revision_requirements"] == real_revise_item["revision_requirements"],
          f"feedback_keys={sorted(feedback.keys())}")

    check(13, "provenance records carry full state_history and revision_count",
          all("state_history" in r["qa_audit"] and "revision_count" in r["qa_audit"] for r in smoke_data["items"])
          and smoke_by_id["gen-struct-003"]["qa_audit"]["revision_count"] == 1)

    # -- #14 system vs content failure ---------------------------------------
    try:
        run_schema_validator("agents/toefl_itp_grammar_generator/scripts/does_not_exist.py", [base_generator_item()])
        system_failure_raised = False
    except SystemCallError:
        system_failure_raised = True

    broken_item = dict(base_generator_item("Structure"))
    del broken_item["correct_answer"]  # syntactically valid JSON, semantically incomplete -> content failure
    content_ok, content_output = run_schema_validator(
        "agents/toefl_itp_grammar_generator/scripts/validate_output.py", [broken_item]
    )
    try:
        parse_agent_json("{not valid json", stage="reviewer")
        json_parse_system_failure = False
    except SystemCallError:
        json_parse_system_failure = True

    check(14, "system failures (missing script, unparsable JSON) are classified separately from "
              "content/schema failures (missing required field)",
          system_failure_raised and json_parse_system_failure and content_ok is False,
          f"missing_script->SystemCallError={system_failure_raised} "
          f"bad_json->SystemCallError={json_parse_system_failure} "
          f"missing_field->schema_ok={content_ok}")

    # -- manual review queue (section 15) demonstration ----------------------
    mr_candidate = Candidate(item_id="synthetic-struct-001", concept_id="synthetic-struct-001", section="Structure")
    mr_candidate.generator_item = base_generator_item("Structure")
    mr_candidate.reviewer_item = base_reviewer_item("C")
    mr_candidate.state = State.SOLVING
    mr_candidate.state_history = [State.GENERATED, State.REVIEWING, State.SOLVING]
    mr_candidate = process_solver_stage(mr_candidate, config, base_solver_item("D", confidence="HIGH"))

    from orchestrator import build_manual_review_entry
    mr_entry = build_manual_review_entry(mr_candidate)
    mr_entry["_synthetic_test_entry"] = (
        "Produced by run_acceptance_tests.py to demonstrate manual-review-queue "
        "mechanics; not a real candidate awaiting human review."
    )
    queue_path = append_manual_review_queue(config, [mr_entry])
    queue_data = json.loads(queue_path.read_text(encoding="utf-8"))
    check("15", "MANUAL_REVIEW items are queued to analysis/manual_review_queue.json with actionable fields",
          mr_candidate.state == State.MANUAL_REVIEW
          and any(e["item_id"] == "synthetic-struct-001" and e["possible_actions"] == ["ACCEPT", "REGENERATE", "DISCARD"]
                  for e in queue_data["items"]),
          f"queue_path={queue_path}")

    print()
    passed = sum(1 for (_n, _d, ok, _det) in RESULTS if ok)
    total = len(RESULTS)
    print(f"Acceptance tests: {passed}/{total} passed")
    for n, desc, ok, detail in RESULTS:
        if not ok:
            print(f"  FAILED #{n}: {desc} ({detail})")

    return 0 if passed == total else 1


if __name__ == "__main__":
    output_dir = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python run_acceptance_tests.py [output-dir]")
    raise SystemExit(main(output_dir))
