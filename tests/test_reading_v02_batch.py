"""Offline tests for variable-length Reading v0.2 batches."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reading.contracts import (
    EMPIRICAL_FORMAT_WARNING,
    FORMAT_ADHERENCE_FAILURE,
    HARD_VALIDITY,
    canonicalize_generator_output,
    deterministic_diagnostics,
    validate_deterministic,
    validate_generator_contract,
    validate_plan_contract,
    word_count,
)
from reading.pipeline import ReadingV02Pipeline, run_reading_batch
from reading.planner import build_plan_v02, passage_id_for_seed
from runtime.adapters import InvocationResult, RuntimeInvocationError

from tests.test_reading_pipeline import generator_fixture


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ARTIFACT_ROOT = ROOT / "runs" / "reading_v0_2" / "reading-v02-batch-20260828T003310Z-f0d7615efc"
HISTORICAL_ARTIFACT_HASHES = {
    "passage-001/generator.json": "1B9F9574EB8E69CF9E01ABEBB81E1737474C0788AC8D20FECFDA881BD10B580C",
    "passage-001/invocations.json": "D1CCC1DB8394011975A9D3B7D756B633A991593472ACEC596CB4D34FDAAA4468",
    "passage-001/plan.json": "60DD21C4EEAC8D235C293AA3A793C939F1C44EFC96AB361FF60F85727120DB18",
    "passage-001/provenance/provenance.json": "EB45E7DA1F2DCFD4148F7783F7DAD2D7129CE8A87ED4B479F58B0BFEFC3F4D10",
    "passage-001/result.json": "8832CFBD39489E8AECF43090060B575450235022A0FA098E7019977362F0253C",
    "passage-001/runtime/logs/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.last-message.json": "1D5B194F1B7A73DB6892A42BEF379298A6C910E0AD433D2C83FB16A9951D7FC4",
    "passage-001/runtime/logs/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.stderr.txt": "BACD69CD8DB7EC046793AC9D976E7CCFFBD6A3733B82C99BA7A1071CB3D11EC8",
    "passage-001/runtime/logs/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.stdout.txt": "E5D266DF0966CD2512F0E79D8B6DD340C904D8B8CE75B5AFBA7490F96C0F81BC",
    "passage-001/runtime/logs/transport-schemas/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.json": "AB5772F2F7575C6BC5EA5272A5565302BCE4192E9B55B7396F084D91D8AD43AA",
    "passage-001/runtime/logs/transport-schemas/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.provenance.json": "02CF5889882846C4A20335F1CD2B2538F6567E968F8AC8D3745F173E8A8F677F",
    "passage-002/generator.json": "CC5C99A0305806A966DF120785A0FE9186CBBC69E09368F03471175A9DB8D968",
    "passage-002/invocations.json": "305EA0330EC2199670D2B8B0CBF29BF14FF093CDFDF2038356ED4640982DF83C",
    "passage-002/plan.json": "8C6A41970E7B761BD2DB5258492C79E102F046F58B95BDE5084A20232A6F9187",
    "passage-002/provenance/provenance.json": "059F6511FAD446AF271411CA18A88AAF0A19C8D4B664A9B8AA5F3587B9E071CF",
    "passage-002/result.json": "14EA6C3C3CE86946F2707DB90826F914E38FC1A5555999BBDC3FBF0CC259E013",
    "passage-002/runtime/logs/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.last-message.json": "0E46485F1895BE8F4D339CBED5F3E702BDB237C4969B7EC3E86E709FD707E15B",
    "passage-002/runtime/logs/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.stderr.txt": "F8A6857DAF23C3B4C6BDC15072578CAF61001831E3A3F1DEB670379398BE3D29",
    "passage-002/runtime/logs/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.stdout.txt": "2296B2E53D884D25246E0C1396026494EF47A17DFCC575B9340C668A6CFEF9BF",
    "passage-002/runtime/logs/transport-schemas/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.json": "AB5772F2F7575C6BC5EA5272A5565302BCE4192E9B55B7396F084D91D8AD43AA",
    "passage-002/runtime/logs/transport-schemas/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.provenance.json": "02CF5889882846C4A20335F1CD2B2538F6567E968F8AC8D3745F173E8A8F677F",
}


def variable_generator_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    """Expand the stable offline passage into the plan's variable q sequence."""

    _legacy_plan, legacy = generator_fixture(7)
    output = copy.deepcopy(legacy)
    output["schema_version"] = "reading-generator-v0.2"
    output["passage_id"] = f"rc-{plan['seed']:08x}"
    questions = []
    for index, question_type in enumerate(plan["question_plan"], 1):
        question = copy.deepcopy(legacy["questions"][(index - 1) % len(legacy["questions"])])
        question["item_id"] = f"{output['passage_id']}-q{index}"
        question["question_type"] = question_type
        question["stem"] = f"Which statement is supported by the passage in item {index}?"
        questions.append(question)
    output["questions"] = questions
    return output


def sized_generator_fixture(plan: dict[str, Any], target_words: int, paragraph_count: int) -> dict[str, Any]:
    """Create a valid-shape fixture with a controlled passage profile."""

    output = variable_generator_fixture(plan)
    paragraph_sizes = [target_words // paragraph_count] * paragraph_count
    for index in range(target_words % paragraph_count):
        paragraph_sizes[index] += 1
    anchors_by_paragraph: dict[int, list[str]] = {index: [] for index in range(1, paragraph_count + 1)}
    for index, question in enumerate(output["questions"], 1):
        paragraph = (index - 1) % paragraph_count + 1
        anchor = f"evidence marker {index}"
        question["evidence"]["paragraph"] = paragraph
        question["evidence"]["anchor"] = anchor
        anchors_by_paragraph[paragraph].append(anchor)
    paragraphs = []
    for paragraph_index, size in enumerate(paragraph_sizes, 1):
        tokens = [f"paragraph {paragraph_index}"]
        tokens.extend(anchors_by_paragraph[paragraph_index])
        token_index = 0
        while word_count(" ".join(tokens)) < size:
            tokens.append(f"topic{paragraph_index}_{token_index}")
            token_index += 1
        paragraphs.append(" ".join(tokens))
    output["passage"] = "\n\n".join(paragraphs)
    assert word_count(output["passage"]) == target_words
    return output


def reviewer_for(generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-reviewer-v0.2",
        "passage_id": generator["passage_id"],
        "section": "READING_COMPREHENSION",
        "questions": [
            {
                "item_id": question["item_id"],
                "best_answer": question["correct_answer"],
                "unique_answer": True,
                "distractors_incorrect": True,
                "answerable": True,
                "natural_wording": True,
                "serious_defect": False,
                "comment": "One answer is supported by the passage.",
            }
            for question in generator["questions"]
        ],
        "set_judgment": "PASS",
        "set_comment": "All visible items are clean.",
    }


def solver_for(generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-solver-v0.2",
        "passage_id": generator["passage_id"],
        "section": "READING_COMPREHENSION",
        "answers": [
            {
                "item_id": question["item_id"],
                "answer": question["correct_answer"],
                "confidence": "HIGH",
                "reason": "The visible passage supports the selected choice.",
            }
            for question in generator["questions"]
        ],
    }


class BatchTrace:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.requests: list[Any] = []


class BatchFakeRuntime:
    provider = "fake"
    cli_version = "offline-v0.2"

    def __init__(self, label: str, trace: BatchTrace, fail_generator: bool = False) -> None:
        self.label = label
        self.trace = trace
        self.fail_generator = fail_generator
        self.generators: dict[str, dict[str, Any]] = {}
        self.call_number = 0

    def invoke(self, request):
        with self.trace.lock:
            self.trace.active += 1
            self.trace.max_active = max(self.trace.max_active, self.trace.active)
            self.trace.requests.append(request)
        self.call_number += 1
        invocation_id = f"offline-{self.label}-{self.call_number}"
        try:
            time.sleep(0.02)
            if self.fail_generator and request.stage == "reading_generator":
                failed = InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=invocation_id,
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:01+00:00",
                    provider=self.provider,
                    model="offline",
                    cli_version=self.cli_version,
                    exit_code=1,
                    error_category="infrastructure",
                    error_detail="intentional offline worker failure",
                    input_keys=list(request.input_keys),
                )
                raise RuntimeInvocationError("infrastructure", "intentional offline worker failure", failed)

            payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
            passage_id = payload["passage_id"] if request.stage != "reading_generator" else f"rc-{payload['seed']:08x}"
            if request.stage == "reading_generator":
                parsed = variable_generator_fixture(payload)
                self.generators[parsed["passage_id"]] = parsed
            elif request.stage == "reading_reviewer":
                parsed = reviewer_for(self.generators[passage_id])
            else:
                parsed = solver_for(self.generators[passage_id])
            return InvocationResult(
                stage=request.stage,
                agent_name=request.agent_name,
                invocation_id=invocation_id,
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:01+00:00",
                provider=self.provider,
                model="offline",
                cli_version=self.cli_version,
                exit_code=0,
                parsed=parsed,
                input_keys=list(request.input_keys),
            )
        finally:
            with self.trace.lock:
                self.trace.active -= 1


class ReadingV02BatchTests(unittest.TestCase):
    def test_planner_identity_envelope_does_not_change_semantic_generator_fields(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        self.assertEqual(plan["passage_id"], passage_id_for_seed(plan["seed"]))
        self.assertEqual(plan["passage_id"], build_plan_v02(1001, domain="biology")["passage_id"])

        raw = variable_generator_fixture(plan)
        raw["passage_id"] = "rc-legacy-model-choice"
        for index, question in enumerate(raw["questions"], 1):
            question["item_id"] = f"{raw['passage_id']}-q{index}"
        raw_snapshot = copy.deepcopy(raw)

        canonical = canonicalize_generator_output(raw, plan)
        self.assertEqual(canonical["passage_id"], plan["passage_id"])
        self.assertEqual(
            [question["item_id"] for question in canonical["questions"]],
            [f"{plan['passage_id']}-q{index}" for index in range(1, len(raw["questions"]) + 1)],
        )
        self.assertEqual(raw, raw_snapshot)
        self.assertEqual(validate_generator_contract(canonical, plan), [])
        for raw_question, canonical_question in zip(raw["questions"], canonical["questions"]):
            for field in ("question_type", "stem", "choices", "correct_answer", "evidence"):
                self.assertEqual(canonical_question[field], raw_question[field])

    def test_v02_pipeline_binds_legacy_model_identity_and_preserves_raw_artifact(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        raw = variable_generator_fixture(plan)
        raw["passage_id"] = "rc-model-selected"
        for index, question in enumerate(raw["questions"], 1):
            question["item_id"] = f"{raw['passage_id']}-q{index}"
        raw_snapshot = copy.deepcopy(raw)
        canonical = canonicalize_generator_output(raw, plan)
        reviewer = reviewer_for(canonical)
        solver = solver_for(canonical)

        class LegacyIdentityRuntime:
            provider = "fake"
            cli_version = "offline-legacy-identity"

            def __init__(self) -> None:
                self.requests: list[Any] = []

            def invoke(self, request):
                self.requests.append(request)
                parsed = {
                    "reading_generator": raw_snapshot,
                    "reading_reviewer": reviewer,
                    "reading_solver": solver,
                }[request.stage]
                return InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=f"legacy-{len(self.requests)}",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:01:00+00:00",
                    provider=self.provider,
                    model="offline",
                    cli_version=self.cli_version,
                    exit_code=0,
                    parsed=copy.deepcopy(parsed),
                    input_keys=list(request.input_keys),
                )

        runtime = LegacyIdentityRuntime()
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(runtime).run(1001, domain="biology", output_dir=Path(directory))
            root = Path(directory)
            self.assertEqual(result["decision"], "ACCEPT")
            self.assertEqual(result["passage_id"], plan["passage_id"])
            self.assertEqual(result["generator"]["passage_id"], plan["passage_id"])
            self.assertEqual(json.loads((root / "generator_raw.json").read_text(encoding="utf-8")), raw_snapshot)
            provenance = json.loads((root / "provenance" / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["generator_raw_artifact"], "generator_raw.json")
            self.assertTrue(provenance["generator_raw_sha256"].startswith("sha256:"))

            for raw_question, canonical_question in zip(raw_snapshot["questions"], result["generator"]["questions"]):
                self.assertEqual(canonical_question["stem"], raw_question["stem"])
                self.assertEqual(canonical_question["choices"], raw_question["choices"])
                self.assertEqual(canonical_question["correct_answer"], raw_question["correct_answer"])
                self.assertEqual(canonical_question["evidence"], raw_question["evidence"])

            self.assertEqual(
                Counter(question["question_type"] for question in result["generator"]["questions"]),
                Counter(plan["question_type_counts"]),
            )
            self.assertEqual(result["checks"]["blind_errors"], [])
            self.assertTrue(result["checks"]["reviewer_contract"])
            self.assertTrue(result["checks"]["solver_contract"])

        self.assertEqual(len(runtime.requests), 3)
        for request in runtime.requests[1:]:
            payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
            self.assertEqual(payload["passage_id"], plan["passage_id"])
            self.assertTrue(all(set(question) == {"item_id", "number", "stem", "choices"} for question in payload["questions"]))

    def test_variable_plan_is_replayable_and_repeated_types_are_valid(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        self.assertEqual(plan, build_plan_v02(1001, domain="biology"))
        self.assertEqual(plan["question_count"], len(plan["question_plan"]))
        self.assertEqual(sum(plan["question_type_counts"].values()), plan["question_count"])
        self.assertEqual(validate_plan_contract(plan), [])
        self.assertGreaterEqual(plan["question_count"], 7)
        self.assertLessEqual(plan["question_count"], 14)
        self.assertLess(len(set(plan["question_plan"])), len(plan["question_plan"]))
        generator = variable_generator_fixture(plan)
        self.assertEqual(validate_generator_contract(generator, plan), [])
        malformed = copy.deepcopy(generator)
        malformed["questions"].pop()
        self.assertTrue(validate_generator_contract(malformed, plan))

    def test_same_question_type_multiset_in_different_order_passes(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        generator = variable_generator_fixture(plan)
        types = list(reversed(plan["question_plan"]))
        if types == plan["question_plan"]:
            types = types[1:] + types[:1]
        for question, question_type in zip(generator["questions"], types):
            question["question_type"] = question_type
        self.assertEqual(validate_generator_contract(generator, plan), [])

    def test_wrong_question_type_multiset_fails(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        generator = variable_generator_fixture(plan)
        original = generator["questions"][0]["question_type"]
        replacement = next(question_type for question_type in ("DETAIL", "VOCABULARY_IN_CONTEXT", "INFERENCE", "MAIN_IDEA", "REFERENCE") if question_type != original)
        generator["questions"][0]["question_type"] = replacement
        errors = validate_generator_contract(generator, plan)
        self.assertTrue(any("type counts" in error for error in errors))
        self.assertEqual(deterministic_diagnostics(generator, plan)["classification"], FORMAT_ADHERENCE_FAILURE)

    def test_v02_passage_length_and_paragraph_profile(self) -> None:
        plan = build_plan_v02(1001, domain="biology")

        too_short = sized_generator_fixture(plan, 67, 1)
        short_errors = validate_deterministic(too_short, plan)
        self.assertTrue(any("word count 67 is below 160" in error for error in short_errors))
        self.assertEqual(deterministic_diagnostics(too_short, plan)["classification"], HARD_VALIDITY)

        preferred_short = sized_generator_fixture(plan, 180, 3)
        self.assertEqual(validate_deterministic(preferred_short, plan), [])
        preferred_short_report = deterministic_diagnostics(preferred_short, plan)
        self.assertEqual(preferred_short_report["passage_word_count"], 180)
        self.assertEqual(preferred_short_report["paragraph_count"], 3)
        self.assertEqual(preferred_short_report["classification"], "VALID")

        preferred_long = sized_generator_fixture(plan, 292, 4)
        self.assertEqual(validate_deterministic(preferred_long, plan), [])

        above_band = sized_generator_fixture(plan, 320, 4)
        self.assertEqual(validate_deterministic(above_band, plan), [])
        above_band_report = deterministic_diagnostics(above_band, plan)
        self.assertEqual(above_band_report["classification"], EMPIRICAL_FORMAT_WARNING)
        self.assertTrue(above_band_report["empirical_warnings"])

    def test_generator_instruction_and_schema_use_exact_type_counts(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        trace = BatchTrace()
        runtime = BatchFakeRuntime("contract", trace)
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(runtime).run(1001, domain="biology", output_dir=Path(directory))
        self.assertEqual(result["decision"], "ACCEPT")
        generator_request = next(request for request in trace.requests if request.stage == "reading_generator")
        payload = json.loads(generator_request.prompt.split("INPUT_JSON:\n", 1)[1])
        self.assertEqual(payload["question_type_counts"], plan["question_type_counts"])
        self.assertIn("exactly match question_type_counts", generator_request.prompt)
        self.assertIn("ordering of the generated questions is free", generator_request.prompt)
        self.assertNotIn("exact planned question_plan order", generator_request.prompt)
        self.assertIn("question_type_counts", (ROOT / ".claude" / "agents" / "toefl-itp-reading-generator-v0.2.md").read_text(encoding="utf-8"))

    def test_historical_v02_passages_001_and_002_are_unchanged(self) -> None:
        required = [HISTORICAL_ARTIFACT_ROOT / relative_path for relative_path in HISTORICAL_ARTIFACT_HASHES]
        if not all(path.is_file() for path in required):
            self.skipTest("historical local Reading v0.2 artifacts are not present")
        for relative_path, expected_hash in HISTORICAL_ARTIFACT_HASHES.items():
            actual_hash = hashlib.sha256((HISTORICAL_ARTIFACT_ROOT / relative_path).read_bytes()).hexdigest().upper()
            self.assertEqual(actual_hash, expected_hash, relative_path)

    def test_historical_v01_smoke_path_remains_available(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        self.assertEqual(build_plan_v02(1001, domain="biology"), plan)
        legacy_plan, legacy_generator = generator_fixture(7)
        self.assertEqual(legacy_plan["schema_version"], "reading-plan-v0.1")
        self.assertEqual(len(legacy_generator["questions"]), 5)
        self.assertEqual(validate_generator_contract(legacy_generator, legacy_plan), [])

    def test_batch_is_bounded_isolated_and_three_calls_per_success(self) -> None:
        trace = BatchTrace()

        def factory(index: int) -> BatchFakeRuntime:
            return BatchFakeRuntime(str(index), trace)

        with TemporaryDirectory() as directory:
            batch = run_reading_batch(
                1001,
                count=3,
                parallel=2,
                domain="biology",
                output_dir=Path(directory),
                runtime_factory=factory,
            )
            root = Path(directory)
            self.assertEqual(batch["requested_passage_count"], 3)
            self.assertEqual(batch["completed_passage_count"], 3)
            self.assertEqual(batch["accept_count"], 3)
            self.assertEqual(batch["quarantine_count"], 0)
            self.assertEqual(batch["infrastructure_failure_count"], 0)
            self.assertEqual(batch["total_live_invocation_count"], 9)
            self.assertEqual(batch["generator_invocation_count"], 3)
            self.assertEqual(batch["reviewer_invocation_count"], 3)
            self.assertEqual(batch["solver_invocation_count"], 3)
            self.assertGreater(batch["total_questions_generated"], 15)
            self.assertLessEqual(trace.max_active, 2)
            self.assertEqual([item["seed"] for item in batch["passage_artifacts"]], [1001, 1002, 1003])
            self.assertEqual(len({item["run_id"] for item in batch["passage_artifacts"]}), 3)
            self.assertTrue((root / "batch_result.json").is_file())
            self.assertEqual(json.loads((root / "batch_result.json").read_text(encoding="utf-8"))["batch_id"], batch["batch_id"])
            self.assertEqual(
                sorted(path.name for path in root.iterdir() if path.is_dir()),
                ["passage-001", "passage-002", "passage-003"],
            )
            for index in range(1, 4):
                passage_dir = root / f"passage-{index:03d}"
                self.assertTrue((passage_dir / "generator.json").is_file())
                self.assertTrue((passage_dir / "reviewer.json").is_file())
                self.assertTrue((passage_dir / "solver.json").is_file())
                self.assertTrue((passage_dir / "provenance" / "provenance.json").is_file())
                passage_result = json.loads((passage_dir / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(passage_result["passage_id"], f"rc-{1000 + index:08x}")
            self.assertFalse(list(root.rglob("*.tmp")))
            self.assertEqual(len({str(request.artifact_dir) for request in trace.requests}), 3)
        for request in trace.requests:
            self.assertEqual(request.isolate_workspace, request.stage in {"reading_reviewer", "reading_solver"})
            if request.stage in {"reading_reviewer", "reading_solver"}:
                payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
                self.assertNotIn("correct_answer", request.prompt)
                self.assertNotIn("question_type", request.prompt)
                self.assertTrue(all(set(question) == {"item_id", "number", "stem", "choices"} for question in payload["questions"]))

    def test_failed_passage_is_infrastructure_failure_without_cancelling_others(self) -> None:
        trace = BatchTrace()

        def factory(index: int) -> BatchFakeRuntime:
            return BatchFakeRuntime(str(index), trace, fail_generator=index == 2)

        with TemporaryDirectory() as directory:
            batch = run_reading_batch(
                1001,
                count=3,
                parallel=2,
                output_dir=Path(directory),
                runtime_factory=factory,
            )
            decisions = [item["decision"] for item in batch["passage_decisions"]]
            self.assertEqual(decisions, ["ACCEPT", "INFRASTRUCTURE_FAILURE", "ACCEPT"])
            self.assertEqual(batch["total_live_invocation_count"], 7)
            self.assertEqual(batch["generator_invocation_count"], 3)
            self.assertEqual(batch["reviewer_invocation_count"], 2)
            self.assertEqual(batch["solver_invocation_count"], 2)
            self.assertEqual(batch["infrastructure_failure_count"], 1)
            failure_result = json.loads((Path(directory) / "passage-002" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(failure_result["decision"], "INFRASTRUCTURE_FAILURE")
            self.assertEqual(failure_result["infrastructure"]["runtime_failures"][0]["stage"], "reading_generator")

    def test_draft_mode_is_explicitly_non_production_and_generator_only(self) -> None:
        trace = BatchTrace()

        with TemporaryDirectory() as directory:
            batch = run_reading_batch(
                2001,
                count=2,
                parallel=2,
                mode="draft",
                output_dir=Path(directory),
                runtime_factory=lambda index: BatchFakeRuntime(str(index), trace),
            )
            self.assertEqual(batch["draft_count"], 2)
            self.assertEqual(batch["total_live_invocation_count"], 2)
            self.assertEqual(batch["reviewer_invocation_count"], 0)
            self.assertEqual(batch["solver_invocation_count"], 0)
            for index in range(1, 3):
                result = json.loads((Path(directory) / f"passage-{index:03d}" / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["decision"], "UNVALIDATED_DRAFT")
                self.assertFalse(result["production_eligible"])
                self.assertEqual(result["draft_status"], "VALIDATED_SHAPE")
                self.assertIsNone(result["reviewer"])
                self.assertIsNone(result["solver"])
                self.assertFalse((Path(directory) / f"passage-{index:03d}" / "reviewer.json").exists())
                self.assertFalse((Path(directory) / f"passage-{index:03d}" / "solver.json").exists())

    def test_direct_v02_pipeline_preserves_first_pass_quality_quarantine(self) -> None:
        plan = build_plan_v02(3001)
        generator = variable_generator_fixture(plan)
        reviewer = reviewer_for(generator)
        solver = solver_for(generator)
        solver["answers"][0]["answer"] = "AMBIGUOUS"

        class SingleRuntime(BatchFakeRuntime):
            def invoke(self, request):
                if request.stage == "reading_generator":
                    self.generators[generator["passage_id"]] = generator
                    parsed = generator
                elif request.stage == "reading_reviewer":
                    parsed = reviewer
                else:
                    parsed = solver
                return InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=f"single-{request.stage}",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:01+00:00",
                    provider="fake",
                    model="offline",
                    cli_version="offline",
                    exit_code=0,
                    parsed=copy.deepcopy(parsed),
                    input_keys=list(request.input_keys),
                )

        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(SingleRuntime("single", BatchTrace())).run(
                plan["seed"], output_dir=Path(directory)
            )
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertEqual(result["infrastructure"]["live_invocations"], 3)
            self.assertEqual(result["solver"]["answers"][0]["answer"], "AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
