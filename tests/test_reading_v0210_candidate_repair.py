"""Offline regression coverage for Reading v0.2.10 candidate repair."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from reading.contracts import (
    candidate_verifier_input,
    validate_candidate_verifier_contract,
    validate_inference_repair_contract,
)
from reading.pipeline import ReadingV02Pipeline
from reading.planner import build_plan_v02
from tests.test_reading_v028_inference_gate import GateRuntime, repair_output


class ReadingV0210CandidateRepairTests(unittest.TestCase):
    def run_pipeline(self, runtime: GateRuntime) -> tuple[dict, Path]:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        result = ReadingV02Pipeline(runtime).run(runtime.plan["seed"], domain="biology", output_dir=root)
        return result, root

    @staticmethod
    def repair_ids(runtime: GateRuntime) -> list[str]:
        return [
            question["item_id"]
            for question in runtime.initial_generator["questions"]
            if question["question_type"] == "INFERENCE"
        ]

    def make_repair_runtime(self, **kwargs) -> GateRuntime:
        plan = build_plan_v02(kwargs.pop("seed", 2890), domain="biology")
        return GateRuntime(plan, initial_verifier_status="INVALID_UNSUPPORTED", **kwargs)

    def test_repair_output_has_exactly_two_indexed_candidates(self) -> None:
        runtime = self.make_repair_runtime()
        item_ids = self.repair_ids(runtime)
        output = repair_output(runtime.initial_generator, item_ids)
        self.assertEqual(validate_inference_repair_contract(output, item_ids), [])
        for replacement in output["replacements"]:
            self.assertEqual([candidate["candidate_index"] for candidate in replacement["candidates"]], [1, 2])
            for candidate in replacement["candidates"]:
                self.assertEqual(candidate["question_type"], "INFERENCE")
                self.assertEqual(set(candidate["choices"]), {"A", "B", "C", "D"})
                self.assertIn("evidence", candidate)
                self.assertIn("distractor_metadata", candidate)

    def test_duplicate_missing_and_extra_candidate_indices_fail_closed(self) -> None:
        runtime = self.make_repair_runtime()
        item_ids = self.repair_ids(runtime)
        for mode in ("duplicate_index", "missing_candidate", "extra_candidate"):
            output = repair_output(runtime.initial_generator, item_ids)
            if mode == "duplicate_index":
                output["replacements"][0]["candidates"][1]["candidate_index"] = 1
            elif mode == "missing_candidate":
                output["replacements"][0]["candidates"].pop()
            else:
                extra = copy.deepcopy(output["replacements"][0]["candidates"][0])
                extra["candidate_index"] = 3
                output["replacements"][0]["candidates"].append(extra)
            with self.subTest(mode=mode):
                self.assertTrue(validate_inference_repair_contract(output, item_ids))

    def test_missing_and_extra_parent_ids_fail_closed(self) -> None:
        runtime = self.make_repair_runtime()
        item_ids = self.repair_ids(runtime)
        missing = repair_output(runtime.initial_generator, item_ids[:-1])
        extra = repair_output(runtime.initial_generator, item_ids)
        extra["replacements"].append(copy.deepcopy(extra["replacements"][0]))
        self.assertTrue(validate_inference_repair_contract(missing, item_ids))
        self.assertTrue(validate_inference_repair_contract(extra, item_ids))

    def test_one_deterministic_invalid_candidate_does_not_quarantine_parent(self) -> None:
        runtime = self.make_repair_runtime(repair_output_mode="invalid_anchor_1")
        result, root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual([request.stage for request in runtime.requests].count("reading_inference_candidate_verifier"), 1)
        validation = json.loads((root / "candidate_validation.json").read_text(encoding="utf-8"))
        parent = validation["parent_item_ids"][0]
        records = [candidate for candidate in validation["candidates"] if candidate["parent_item_id"] == parent]
        self.assertFalse(records[0]["deterministic_valid"])
        self.assertTrue(records[1]["deterministic_valid"])

    def test_candidate_two_deterministic_failure_leaves_candidate_one_eligible(self) -> None:
        runtime = self.make_repair_runtime(repair_output_mode="invalid_anchor_2")
        result, root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        validation = json.loads((root / "candidate_validation.json").read_text(encoding="utf-8"))
        parent = validation["parent_item_ids"][0]
        records = sorted(
            (candidate for candidate in validation["candidates"] if candidate["parent_item_id"] == parent),
            key=lambda candidate: candidate["candidate_index"],
        )
        self.assertTrue(records[0]["deterministic_valid"])
        self.assertFalse(records[1]["deterministic_valid"])
        self.assertEqual(result["checks"]["candidate_selection"]["selected"][0]["candidate_index"], 1)

    def test_both_deterministically_invalid_quarantines_before_candidate_verifier(self) -> None:
        runtime = self.make_repair_runtime(repair_output_mode="both_invalid")
        result, root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual([request.stage for request in runtime.requests], [
            "reading_generator", "reading_inference_verifier", "reading_reviewer", "reading_inference_repair",
        ])
        self.assertIsNone(result["solver"])
        self.assertFalse((root / "candidate_verifier.json").exists())
        self.assertTrue((root / "candidate_validation.json").exists())
        self.assertTrue((root / "candidate_selection.json").exists())

    def test_candidate_verifier_input_is_visible_only_and_uses_temporary_identity(self) -> None:
        runtime = self.make_repair_runtime()
        result, root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        request = next(request for request in runtime.requests if request.stage == "reading_inference_candidate_verifier")
        payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
        self.assertTrue(all(set(candidate) == {"parent_item_id", "candidate_index", "stem", "choices"} for candidate in payload["candidates"]))
        for candidate in payload["candidates"]:
            self.assertNotIn("correct_answer", candidate)
            self.assertNotIn("evidence", candidate)
            self.assertNotIn("rationale", candidate)
            self.assertNotIn("subtype", candidate)
            self.assertNotIn("question_type", candidate)
            self.assertNotIn("distractor_metadata", candidate)
            self.assertNotIn("target_metadata", candidate)
            self.assertNotIn("permutation", candidate)
        self.assertEqual(payload, json.loads((root / "candidate_verifier_input.json").read_text(encoding="utf-8")))

    def test_direct_restatement_candidate_is_rejected_when_genuine_candidate_is_eligible(self) -> None:
        runtime = self.make_repair_runtime()
        item_id = self.repair_ids(runtime)[0]
        runtime.candidate_statuses = {
            (item_id, 1): "INVALID_DIRECT_RESTATEMENT",
            (item_id, 2): "VALID_GENUINE_INFERENCE",
        }
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(result["checks"]["candidate_selection"]["selected"][0]["candidate_index"], 2)

    def test_status_ranking_is_genuine_then_cross_idea_then_shallow(self) -> None:
        cases = (
            ("VALID_SHALLOW_INFERENCE", "VALID_GENUINE_INFERENCE", 2),
            ("VALID_CROSS_IDEA_INFERENCE", "VALID_GENUINE_INFERENCE", 2),
            ("VALID_SHALLOW_INFERENCE", "VALID_CROSS_IDEA_INFERENCE", 2),
            ("VALID_GENUINE_INFERENCE", "VALID_GENUINE_INFERENCE", 1),
        )
        for first, second, selected in cases:
            with self.subTest(first=first, second=second):
                runtime = self.make_repair_runtime()
                item_id = self.repair_ids(runtime)[0]
                runtime.candidate_statuses = {(item_id, 1): first, (item_id, 2): second}
                result, _root = self.run_pipeline(runtime)
                self.assertEqual(result["decision"], "ACCEPT")
                self.assertEqual(result["checks"]["candidate_selection"]["selected"][0]["candidate_index"], selected)

    def test_answer_key_mismatch_invalidates_only_that_candidate(self) -> None:
        runtime = self.make_repair_runtime()
        item_id = self.repair_ids(runtime)[0]
        candidate_question = next(question for question in runtime.initial_generator["questions"] if question["item_id"] == item_id)
        mismatch = next(label for label in ("A", "B", "C", "D") if label != candidate_question["correct_answer"])
        runtime.candidate_answer_overrides = {(item_id, 1): mismatch}
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        selected = result["checks"]["candidate_selection"]["selected"][0]
        self.assertEqual(selected["candidate_index"], 2)

    def test_multiple_parents_use_one_repair_and_one_candidate_verifier_call(self) -> None:
        runtime = self.make_repair_runtime(seed=2924)
        result, root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(sum(request.stage == "reading_inference_repair" for request in runtime.requests), 1)
        self.assertEqual(sum(request.stage == "reading_inference_candidate_verifier" for request in runtime.requests), 1)
        repair = json.loads((root / "inference_repair.json").read_text(encoding="utf-8"))
        candidate_input = json.loads((root / "candidate_verifier_input.json").read_text(encoding="utf-8"))
        self.assertEqual(len(repair["replacements"]), len(candidate_input["candidates"]) // 2)

    def test_selected_candidate_preserves_parent_slot_and_unaffected_items(self) -> None:
        runtime = self.make_repair_runtime()
        original = copy.deepcopy(runtime.initial_generator)
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        final = result["generator"]
        self.assertEqual([question["item_id"] for question in final["questions"]], [question["item_id"] for question in original["questions"]])
        for before, after in zip(original["questions"], final["questions"]):
            if before["question_type"] != "INFERENCE":
                self.assertEqual(before, after)
        self.assertEqual(len(final["questions"]), runtime.plan["question_count"])

    def test_candidate_artifacts_and_hashes_are_persisted(self) -> None:
        runtime = self.make_repair_runtime()
        _result, root = self.run_pipeline(runtime)
        for name in (
            "inference_repair.json",
            "candidate_validation.json",
            "candidate_verifier_input.json",
            "candidate_verifier.json",
            "candidate_selection.json",
        ):
            self.assertTrue((root / name).is_file(), name)
        provenance = json.loads((root / "provenance" / "provenance.json").read_text(encoding="utf-8"))
        for key in (
            "inference_repair_output_sha256",
            "candidate_validation_sha256",
            "candidate_verifier_input_sha256",
            "candidate_verifier_output_sha256",
            "candidate_selection_sha256",
            "final_generator_sha256",
        ):
            self.assertTrue(provenance[key].startswith("sha256:"), key)

    def test_final_reviewer_receives_selected_set_and_solver_projection_is_identical(self) -> None:
        runtime = self.make_repair_runtime()
        result, root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        reviewer_requests = [request for request in runtime.requests if request.stage == "reading_reviewer"]
        final_payload = json.loads(reviewer_requests[-1].prompt.split("INPUT_JSON:\n")[1])
        solver_payload = json.loads(next(request for request in runtime.requests if request.stage == "reading_solver").prompt.split("INPUT_JSON:\n")[1])
        self.assertEqual(final_payload, solver_payload)
        self.assertEqual(final_payload, json.loads((root / "reviewer_input.json").read_text(encoding="utf-8")))

    def test_final_reviewer_failure_blocks_solver_without_second_repair(self) -> None:
        runtime = self.make_repair_runtime(final_reviewer_set_judgment="FAIL")
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(sum(request.stage == "reading_inference_repair" for request in runtime.requests), 1)
        self.assertEqual(sum(request.stage == "reading_inference_candidate_verifier" for request in runtime.requests), 1)
        self.assertEqual(sum(request.stage == "reading_solver" for request in runtime.requests), 0)

    def test_candidate_verifier_contract_failure_blocks_final_reviewer(self) -> None:
        runtime = self.make_repair_runtime(reverify_output_mode="malformed")
        result, _root = self.run_pipeline(runtime)
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(sum(request.stage == "reading_reviewer" for request in runtime.requests), 1)
        self.assertEqual(sum(request.stage == "reading_solver" for request in runtime.requests), 0)

    def test_candidate_verifier_contract_requires_exact_surviving_pairs(self) -> None:
        runtime = self.make_repair_runtime()
        item_id = self.repair_ids(runtime)[0]
        candidate = {
            "parent_item_id": item_id,
            "candidate_index": 1,
            "question": runtime.initial_generator["questions"][0],
        }
        verifier_input = candidate_verifier_input(runtime.initial_generator, [candidate])
        valid_output = {
            "schema_version": "reading-inference-candidate-verifier-v0.2",
            "passage_id": runtime.initial_generator["passage_id"],
            "section": "READING_COMPREHENSION",
            "candidates": [{
                "parent_item_id": item_id,
                "candidate_index": 1,
                "best_answer": "A",
                "status": "VALID_SHALLOW_INFERENCE",
                "supporting_propositions": ["A", "B"],
                "conclusion": "C",
                "comment": "D",
            }],
        }
        self.assertEqual(validate_candidate_verifier_contract(valid_output, verifier_input), [])
        duplicate = copy.deepcopy(valid_output)
        duplicate["candidates"].append(copy.deepcopy(duplicate["candidates"][0]))
        self.assertTrue(validate_candidate_verifier_contract(duplicate, verifier_input))


if __name__ == "__main__":
    unittest.main()
