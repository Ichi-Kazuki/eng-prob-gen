"""Focused offline coverage for the bounded Reading v0.2.8 inference gate."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reading.contracts import (
    apply_choice_permutation_to_question,
    canonicalize_generator_output,
    inference_verifier_input,
    payload_sha256,
    permute_generator_choices,
    validate_inference_repair_contract,
    validate_inference_verifier_contract,
)
from reading.pipeline import ReadingV02Pipeline, run_reading_batch
from reading.planner import build_plan_v02
from runtime.adapters import InvocationResult, RuntimeInvocationError

from tests.test_reading_v02_batch import (
    inference_verifier_for,
    reviewer_for,
    solver_for,
    variable_generator_fixture,
)


ROOT = Path(__file__).resolve().parents[1]


def metadata(correct_answer: str) -> dict[str, dict[str, str]]:
    return {
        label: {
            "category": "CORRECT_OPTION" if label == correct_answer else "TEXT_TRUE_BUT_NOT_ANSWER",
            "rationale": "The keyed choice is supported." if label == correct_answer else "It is related but does not answer the stem.",
        }
        for label in ("A", "B", "C", "D")
    }


def repair_output(generator: dict[str, Any], item_ids: list[str]) -> dict[str, Any]:
    by_id = {question["item_id"]: question for question in generator["questions"]}
    replacements = []
    for item_id in item_ids:
        original = by_id[item_id]
        replacements.append({
            "item_id": item_id,
            "question_type": "INFERENCE",
            "subtype": "LOCAL_INFERENCE",
            "stem": "Which conclusion can be drawn from the two related facts in the passage?",
            "choices": {
                "A": "The passage establishes a different conclusion.",
                "B": "The two facts jointly imply a cautious conclusion.",
                "C": "The passage leaves every consequence unexplained.",
                "D": "The topic is unrelated to the evidence presented.",
            },
            "correct_answer": "B",
            "evidence": copy.deepcopy(original["evidence"]),
            "distractor_metadata": metadata("B"),
        })
    return {"schema_version": "reading-inference-repair-v0.2", "replacements": replacements}


class GateRuntime:
    provider = "offline-test"
    cli_version = "offline-v0.2.8"

    def __init__(
        self,
        plan: dict[str, Any],
        *,
        initial_verifier_status: str = "VALID_SHALLOW_INFERENCE",
        initial_answer_overrides: dict[str, str] | None = None,
        reverify_status: str = "VALID_SHALLOW_INFERENCE",
        repair: bool = True,
        fail_stage: str | None = None,
    ) -> None:
        self.plan = plan
        self.raw = variable_generator_fixture(plan)
        initial_canonical = canonicalize_generator_output(self.raw, plan)
        self.initial_generator, self.permutation = permute_generator_choices(initial_canonical, plan)
        self.final_generator = copy.deepcopy(self.initial_generator)
        self.initial_verifier_status = initial_verifier_status
        self.initial_answer_overrides = initial_answer_overrides or {}
        self.reverify_status = reverify_status
        self.repair = repair
        self.fail_stage = fail_stage
        self.requests: list[Any] = []
        self.repair_calls = 0
        self.verifier_calls = 0

    def _invocation_error(self, request: Any, invocation_id: str) -> RuntimeInvocationError:
        result = InvocationResult(
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
            error_detail=f"intentional failure at {request.stage}",
            input_keys=list(request.input_keys),
        )
        return RuntimeInvocationError("infrastructure", result.error_detail, result)

    def invoke(self, request: Any) -> InvocationResult:
        self.requests.append(request)
        invocation_id = f"offline-{len(self.requests)}"
        if request.stage == self.fail_stage:
            raise self._invocation_error(request, invocation_id)
        payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
        if request.stage == "reading_generator":
            parsed = copy.deepcopy(self.raw)
        elif request.stage == "reading_inference_verifier":
            self.verifier_calls += 1
            is_reverify = self.verifier_calls == 2
            status = self.reverify_status if is_reverify else self.initial_verifier_status
            source = self.final_generator if is_reverify else self.initial_generator
            parsed = copy.deepcopy(inference_verifier_for(source))
            for item in parsed["questions"]:
                item["status"] = status
                if not is_reverify and item["item_id"] in self.initial_answer_overrides:
                    item["best_answer"] = self.initial_answer_overrides[item["item_id"]]
        elif request.stage == "reading_inference_repair":
            self.repair_calls += 1
            self.final_generator = copy.deepcopy(self.initial_generator)
            item_ids = [item["item_id"] for item in payload["items"]]
            replacements = repair_output(self.initial_generator, item_ids)
            by_id = {replacement["item_id"]: replacement for replacement in replacements["replacements"]}
            for question in self.final_generator["questions"]:
                if question["item_id"] in by_id:
                    replacement = by_id[question["item_id"]]
                    record = next(item for item in self.permutation["questions"] if item["item_id"] == question["item_id"])
                    remapped = apply_choice_permutation_to_question(
                        replacement,
                        original_to_canonical=record["original_to_canonical"],
                        canonical_to_original=record["canonical_to_original"],
                    )
                    question.clear()
                    question.update(remapped)
            parsed = replacements if self.repair else {
                "schema_version": "reading-inference-repair-v0.2",
                "replacements": [],
            }
        elif request.stage == "reading_reviewer":
            parsed = reviewer_for(self.final_generator)
        elif request.stage == "reading_solver":
            parsed = solver_for(self.final_generator)
        else:
            raise AssertionError(f"unexpected stage: {request.stage}")
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


class ReadingV028InferenceGateTests(unittest.TestCase):
    def run_pipeline(self, runtime: GateRuntime) -> tuple[dict[str, Any], Path]:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        result = ReadingV02Pipeline(runtime).run(runtime.plan["seed"], domain="biology", output_dir=root)
        return result, root

    def test_zero_inference_skips_verifier_and_repair(self) -> None:
        plan = build_plan_v02(2892, domain="biology")
        runtime = GateRuntime(plan)
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual([request.stage for request in runtime.requests], ["reading_generator", "reading_reviewer", "reading_solver"])
        self.assertFalse(result["checks"]["inference_gate_required"])
        self.assertTrue(result["checks"]["inference_gate_pass"])
        self.assertEqual(result["infrastructure"]["live_invocations"], 3)

    def test_all_inference_valid_uses_one_verifier_and_no_repair(self) -> None:
        plan = build_plan_v02(2900, domain="biology")
        runtime = GateRuntime(plan)
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual([request.stage for request in runtime.requests], [
            "reading_generator", "reading_inference_verifier", "reading_reviewer", "reading_solver",
        ])
        self.assertEqual(result["infrastructure"]["invocation_counts"]["inference_verifier"], 1)
        self.assertEqual(result["infrastructure"]["invocation_counts"]["inference_repair"], 0)

    def test_invalid_statuses_trigger_exactly_one_repair(self) -> None:
        for status in ("INVALID_DIRECT_RESTATEMENT", "INVALID_UNSUPPORTED", "INVALID_AMBIGUOUS"):
            with self.subTest(status=status):
                plan = build_plan_v02(2890, domain="biology")
                runtime = GateRuntime(plan, initial_verifier_status=status)
                result, _root = self.run_pipeline(runtime)
                self.assertEqual(result["decision"], "ACCEPT")
                self.assertEqual(runtime.repair_calls, 1)
                self.assertEqual(result["checks"]["inference_repair_attempted"], True)
                self.assertEqual(result["checks"]["inference_repair_succeeded"], True)
                self.assertEqual(result["infrastructure"]["live_invocations"], 6)

    def test_verifier_answer_mismatch_repairs_without_key_leakage(self) -> None:
        plan = build_plan_v02(2830, domain="biology")
        probe = GateRuntime(plan)
        trusted = next(question for question in probe.initial_generator["questions"] if question["question_type"] == "INFERENCE")
        initial_id = trusted["item_id"]
        mismatch = next(label for label in ("A", "B", "C", "D") if label != trusted["correct_answer"])
        runtime = GateRuntime(plan, initial_answer_overrides={initial_id: mismatch})
        result, _root = self.run_pipeline(runtime)
        verifier_request = next(request for request in runtime.requests if request.stage == "reading_inference_verifier")
        verifier_payload = json.loads(verifier_request.prompt.split("INPUT_JSON:\n", 1)[1])
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(runtime.repair_calls, 1)
        self.assertNotIn("correct_answer", json.dumps(verifier_payload))
        self.assertNotIn("evidence", json.dumps(verifier_payload))
        self.assertNotIn("distractor_metadata", json.dumps(verifier_payload))
        self.assertIn("disagrees with the trusted Generator answer", json.dumps(result["checks"]["inference_gate_results"]))

    def test_multiple_bad_items_repair_together_and_preserve_unaffected_slots(self) -> None:
        plan = build_plan_v02(2924, domain="biology")
        runtime = GateRuntime(plan, initial_verifier_status="INVALID_DIRECT_RESTATEMENT")
        original = copy.deepcopy(runtime.initial_generator)
        result, root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(runtime.repair_calls, 1)
        repair_request = next(request for request in runtime.requests if request.stage == "reading_inference_repair")
        repair_payload = json.loads(repair_request.prompt.split("INPUT_JSON:\n", 1)[1])
        self.assertEqual(len(repair_payload["items"]), 3)
        self.assertEqual(result["checks"]["inference_repair_succeeded"], True)
        final = result["generator"]
        for before, after in zip(original["questions"], final["questions"]):
            if before["question_type"] != "INFERENCE":
                self.assertEqual(before, after)
        self.assertEqual([question["item_id"] for question in final["questions"]], [question["item_id"] for question in original["questions"]])
        self.assertEqual(
            {question["question_type"]: sum(item["question_type"] == question["question_type"] for item in final["questions"]) for question in final["questions"]},
            plan["question_type_counts"],
        )
        self.assertTrue((root / "generator_pre_repair.json").is_file())

    def test_repair_reverification_failure_quarantines_without_second_repair(self) -> None:
        plan = build_plan_v02(2890, domain="biology")
        runtime = GateRuntime(plan, initial_verifier_status="INVALID_UNSUPPORTED", reverify_status="INVALID_AMBIGUOUS")
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(runtime.repair_calls, 1)
        self.assertEqual(runtime.verifier_calls, 2)
        self.assertFalse(result["reviewer"])
        self.assertFalse(result["solver"])
        self.assertFalse(result["checks"]["inference_repair_succeeded"])

    def test_raw_and_pre_repair_artifacts_and_provenance_are_auditable(self) -> None:
        plan = build_plan_v02(2900, domain="biology")
        runtime = GateRuntime(plan, initial_verifier_status="INVALID_DIRECT_RESTATEMENT")
        result, root = self.run_pipeline(runtime)
        raw_bytes = (root / "generator_raw.json").read_bytes()
        self.assertEqual(json.loads(raw_bytes), runtime.raw)
        self.assertEqual((root / "generator_raw.json").read_bytes(), raw_bytes)
        self.assertEqual(
            json.loads((root / "generator_pre_repair.json").read_text(encoding="utf-8")),
            runtime.initial_generator,
        )
        provenance = json.loads((root / "provenance" / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["generator_raw_sha256"], payload_sha256(runtime.raw))
        self.assertEqual(provenance["repair_attempt_count"], 1)
        self.assertEqual(provenance["repaired_item_ids"], provenance["flagged_inference_item_ids"])
        self.assertTrue(provenance["inference_verifier_input_sha256"].startswith("sha256:"))
        self.assertTrue(provenance["inference_reverify_output_sha256"].startswith("sha256:"))
        self.assertEqual(provenance["final_specialized_inference_gate_result"], True)
        self.assertEqual(provenance["final_generator_sha256"], payload_sha256(result["generator"]))
        self.assertEqual(result["checks"]["inference_gate_pass"], True)

    def test_recorded_permutation_is_reused_for_repair_and_blind_inputs_match(self) -> None:
        plan = build_plan_v02(2901, domain="biology")
        runtime = GateRuntime(plan, initial_verifier_status="INVALID_DIRECT_RESTATEMENT")
        result, root = self.run_pipeline(runtime)
        item_id = result["checks"]["inference_gate_results"]["initial"][0]["item_id"]
        record = next(record for record in runtime.permutation["questions"] if record["item_id"] == item_id)
        repaired = next(question for question in result["generator"]["questions"] if question["item_id"] == item_id)
        self.assertEqual(repaired["correct_answer"], record["original_to_canonical"]["B"])
        self.assertEqual(repaired["choices"][record["original_to_canonical"]["B"]], "The two facts jointly imply a cautious conclusion.")
        self.assertEqual(repaired["distractor_metadata"][record["original_to_canonical"]["B"]]["category"], "CORRECT_OPTION")
        reviewer_payload = json.loads((root / "reviewer_input.json").read_text(encoding="utf-8"))
        solver_payload = json.loads((root / "solver_input.json").read_text(encoding="utf-8"))
        self.assertEqual(reviewer_payload, solver_payload)
        self.assertIn("questions", reviewer_payload)

    def test_verifier_and_repair_runtime_failures_are_infrastructure_failures(self) -> None:
        for fail_stage in ("reading_inference_verifier", "reading_inference_repair"):
            with self.subTest(fail_stage=fail_stage):
                plan = build_plan_v02(2900, domain="biology")
                initial_status = "INVALID_UNSUPPORTED" if fail_stage == "reading_inference_repair" else "VALID_SHALLOW_INFERENCE"
                runtime = GateRuntime(plan, initial_verifier_status=initial_status, fail_stage=fail_stage)
                result, _root = self.run_pipeline(runtime)
                self.assertEqual(result["decision"], "INFRASTRUCTURE_FAILURE")
                self.assertEqual(result["infrastructure"]["runtime_failures"][0]["stage"], fail_stage)

    def test_draft_remains_generator_only(self) -> None:
        plan = build_plan_v02(2880, domain="biology")
        runtime = GateRuntime(plan)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        result = ReadingV02Pipeline(runtime).run_draft(plan["seed"], domain="biology", output_dir=Path(directory.name))
        self.assertEqual(result["decision"], "UNVALIDATED_DRAFT")
        self.assertEqual([request.stage for request in runtime.requests], ["reading_generator"])
        self.assertEqual(result["infrastructure"]["live_invocations"], 1)

    def test_batch_aggregation_includes_verifier_and_repair_calls(self) -> None:
        runtimes: dict[int, GateRuntime] = {}

        def factory(index: int) -> GateRuntime:
            plan = build_plan_v02(2892 + index - 1, domain=None)
            runtime = GateRuntime(plan, initial_verifier_status="INVALID_UNSUPPORTED" if index == 1 else "VALID_SHALLOW_INFERENCE")
            runtimes[index] = runtime
            return runtime

        with TemporaryDirectory() as directory:
            batch = run_reading_batch(2892, count=2, parallel=1, output_dir=Path(directory), runtime_factory=factory)
        self.assertEqual(batch["inference_verifier_invocation_count"], 3)
        self.assertEqual(batch["inference_repair_invocation_count"], 1)
        self.assertEqual(batch["total_live_invocation_count"], 10)

    def test_verifier_contract_has_no_set_level_judgment_and_repair_schema_is_exact(self) -> None:
        plan = build_plan_v02(2900, domain="biology")
        runtime = GateRuntime(plan)
        verifier = inference_verifier_for(runtime.initial_generator)
        verifier_input = inference_verifier_input(runtime.initial_generator)
        self.assertEqual(validate_inference_verifier_contract(verifier, verifier_input), [])
        self.assertNotIn("set_judgment", verifier)
        requested = [question["item_id"] for question in runtime.initial_generator["questions"] if question["question_type"] == "INFERENCE"]
        repair = repair_output(runtime.initial_generator, requested)
        self.assertEqual(validate_inference_repair_contract(repair, requested), [])


if __name__ == "__main__":
    unittest.main()
