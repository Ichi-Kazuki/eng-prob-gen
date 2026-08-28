"""Offline tests for variable-length Reading v0.2 batches."""

from __future__ import annotations

import copy
import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reading.contracts import validate_generator_contract
from reading.pipeline import ReadingV02Pipeline, run_reading_batch
from reading.planner import build_plan_v02
from runtime.adapters import InvocationResult, RuntimeInvocationError

from tests.test_reading_pipeline import generator_fixture


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
    def test_variable_plan_is_replayable_and_repeated_types_are_valid(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        self.assertEqual(plan, build_plan_v02(1001, domain="biology"))
        self.assertEqual(plan["question_count"], len(plan["question_plan"]))
        self.assertGreaterEqual(plan["question_count"], 7)
        self.assertLessEqual(plan["question_count"], 14)
        self.assertLess(len(set(plan["question_plan"])), len(plan["question_plan"]))
        generator = variable_generator_fixture(plan)
        self.assertEqual(validate_generator_contract(generator, plan), [])
        malformed = copy.deepcopy(generator)
        malformed["questions"].pop()
        self.assertTrue(validate_generator_contract(malformed, plan))

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
