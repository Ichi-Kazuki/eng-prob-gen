"""Focused offline tests for the isolated Reading v0.1 vertical slice."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from reading.contracts import (
    blind_input,
    blind_input_errors,
    post_blind_comparison,
    solver_input_errors,
    validate_deterministic,
    validate_generator_contract,
    validate_reviewer_contract,
    validate_solver_contract,
)
from reading.pipeline import ReadingPipeline
from reading.planner import QUESTION_TYPES, build_plan, build_plan_v01
from runtime.adapters import InvocationResult


ROOT = Path(__file__).resolve().parents[1]


def generator_fixture(seed: int = 7) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = build_plan_v01(seed, domain="biology")
    passage = "\n\n".join([
        "In shallow coastal marshes, microscopic algae form thin communities on sediment surfaces. These communities are easy to overlook, yet they influence how oxygen and nutrients move through the upper layer of mud. During daylight, the algae draw carbon dioxide from the water and release oxygen. Their activity changes with temperature, salinity, and the amount of time that the sediment remains exposed.",
        "Researchers studying these marshes have found that the communities do more than provide food for small animals. Their filaments bind loose particles, reducing the amount of sediment carried away by ordinary tides. This stabilizing effect is strongest where water moves slowly, so a sheltered inlet may retain more fine material than an open shore. The result is a surface that can support additional organisms.",
        "The algae are not equally abundant in every season. A brief period of intense sunlight can increase growth, but prolonged exposure can dry the surface and interrupt the exchange of gases. Field teams therefore compare shaded and exposed plots rather than treating one measurement as representative. This approach reveals that resilience depends on repeated small adjustments, including movement into damp cracks after the tide recedes.",
        "These observations have practical implications for restoring damaged wetlands. A project that adds sediment but ignores surface communities may create a landscape that looks stable while remaining vulnerable to erosion. Restoration planners increasingly protect sheltered zones and monitor oxygen, salinity, and particle movement together. In this way, the modest organisms at the sediment surface become indicators of whether a larger marsh system is recovering.",
    ])
    answers = ["B", "C", "A", "D", "B"]
    anchors = ["reducing the amount of sediment", "filaments bind loose particles", "resilience depends on repeated", "practical implications for restoring", "These observations"]
    questions = []
    for index, (question_type, answer, anchor) in enumerate(zip(QUESTION_TYPES, answers, anchors), 1):
        questions.append({
            "item_id": f"rc-{seed:08x}-q{index}",
            "question_type": question_type,
            "stem": f"Which statement is supported by the passage about {question_type.lower().replace('_', ' ')}?",
            "choices": {
                "A": "It occurs only after the marsh has completely dried.",
                "B": "It is connected with the conditions described by the author.",
                "C": "It is unrelated to the movement of water or sediment.",
                "D": "It was rejected by every researcher in the study.",
            },
            "correct_answer": answer,
            "evidence": {
                "paragraph": [2, 2, 3, 4, 4][index - 1],
                "anchor": anchor,
                "rationale": "The cited passage language supports the intended choice.",
            },
        })
    # Make each question's intended choice distinct in text so fixture answer
    # comparison remains meaningful while the structural tests stay synthetic.
    questions[0]["choices"]["B"] = "It reduces the amount of sediment carried away by ordinary tides."
    questions[1]["choices"]["C"] = "They bind loose particles and can stabilize the sediment surface."
    questions[2]["choices"]["A"] = "It depends on repeated adjustments to changing exposure."
    questions[3]["choices"]["D"] = "They help planners judge whether a damaged wetland is recovering."
    questions[4]["choices"]["B"] = "The observations described earlier have practical implications for restoration."
    return plan, {
        "schema_version": "reading-generator-v0.1",
        "passage_id": f"rc-{seed:08x}",
        "section": "READING_COMPREHENSION",
        "title": "Surface Communities in Coastal Marshes",
        "passage": passage,
        "questions": questions,
    }


def reviewer_fixture(generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-reviewer-v0.1",
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
        "set_comment": "All five items are independently answerable.",
    }


def solver_fixture(generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-solver-v0.1",
        "passage_id": generator["passage_id"],
        "section": "READING_COMPREHENSION",
        "answers": [
            {
                "item_id": question["item_id"],
                "answer": question["correct_answer"],
                "confidence": "HIGH",
                "reason": "The passage provides direct or implied support.",
            }
            for question in generator["questions"]
        ],
    }


class FakeRuntime:
    provider = "fake"
    cli_version = "offline-test"

    def __init__(self, outputs: dict[str, Any]) -> None:
        self.outputs = outputs
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        parsed = copy.deepcopy(self.outputs[request.stage])
        return InvocationResult(
            stage=request.stage,
            agent_name=request.agent_name,
            invocation_id=f"offline-{len(self.requests)}",
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:01:00+00:00",
            provider=self.provider,
            model="offline",
            cli_version=self.cli_version,
            exit_code=0,
            parsed=parsed,
            input_keys=list(request.input_keys),
        )


class ReadingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.generator = generator_fixture()
        self.blind = blind_input(self.generator)
        self.reviewer = reviewer_fixture(self.generator)
        self.solver = solver_fixture(self.generator)

    def test_planner_is_deterministic_and_allowlisted(self) -> None:
        self.assertEqual(build_plan(44), build_plan(44))
        self.assertNotEqual(build_plan(44), build_plan(45))
        self.assertEqual(build_plan(44, domain="history")["domain"], "history")
        with self.assertRaises(ValueError):
            build_plan(44, domain="medicine")

    def test_generator_schema_and_semantics(self) -> None:
        self.assertEqual(validate_generator_contract(self.generator, self.plan), [])
        self.assertEqual(validate_deterministic(self.generator, self.plan), [])

    def test_malformed_question_rejection(self) -> None:
        malformed = copy.deepcopy(self.generator)
        del malformed["questions"][0]["question_type"]
        self.assertTrue(validate_generator_contract(malformed, self.plan))

        malformed = copy.deepcopy(self.generator)
        del malformed["questions"][0]["choices"]["D"]
        self.assertTrue(validate_generator_contract(malformed, self.plan))

        malformed = copy.deepcopy(self.generator)
        malformed["questions"][0]["correct_answer"] = "E"
        self.assertTrue(validate_generator_contract(malformed, self.plan))

    def test_duplicate_choices_and_duplicate_question_types_rejected(self) -> None:
        duplicate_choices = copy.deepcopy(self.generator)
        duplicate_choices["questions"][0]["choices"]["D"] = duplicate_choices["questions"][0]["choices"]["A"]
        self.assertIn("duplicate answer choices", " ".join(validate_generator_contract(duplicate_choices, self.plan)))

        duplicate_types = copy.deepcopy(self.generator)
        duplicate_types["questions"][4]["question_type"] = duplicate_types["questions"][0]["question_type"]
        self.assertTrue(validate_generator_contract(duplicate_types, self.plan))

    def test_reviewer_and_solver_blinding_excludes_answer_metadata(self) -> None:
        for field in ("correct_answer", "evidence", "question_type"):
            self.assertNotIn(field, json.dumps(self.blind))
        leaked = copy.deepcopy(self.blind)
        leaked["questions"][0]["correct_answer"] = "B"
        self.assertTrue(blind_input_errors(self.generator, leaked))
        self.assertEqual(blind_input_errors(self.generator, self.blind), [])
        self.assertEqual(solver_input_errors(self.generator, self.blind), [])
        self.assertEqual(set(self.blind["questions"][0]), {"item_id", "number", "stem", "choices"})

    def test_reviewer_solver_contracts_and_post_blind_comparison(self) -> None:
        self.assertEqual(validate_reviewer_contract(self.reviewer, self.blind), [])
        self.assertEqual(validate_solver_contract(self.solver, self.blind), [])
        bad_reviewer = copy.deepcopy(self.reviewer)
        bad_reviewer["questions"][0]["best_answer"] = "AMBIGUOUS"
        bad_reviewer["questions"][0]["unique_answer"] = True
        self.assertTrue(validate_reviewer_contract(bad_reviewer, self.blind))
        bad_solver = copy.deepcopy(self.solver)
        bad_solver["answers"][0]["answer"] = "MAYBE"
        self.assertTrue(validate_solver_contract(bad_solver, self.blind))

        agreements, errors = post_blind_comparison(self.generator, self.reviewer, self.solver)
        self.assertEqual(len(agreements), 5)
        self.assertEqual(errors, [])
        changed = copy.deepcopy(self.solver)
        changed["answers"][0]["answer"] = "C"
        agreements, errors = post_blind_comparison(self.generator, self.reviewer, changed)
        self.assertFalse(agreements[0]["agree"])
        self.assertTrue(errors)

    def test_accept_path_is_three_calls_and_persists_artifacts(self) -> None:
        runtime = FakeRuntime({
            "reading_generator": self.generator,
            "reading_reviewer": self.reviewer,
            "reading_solver": self.solver,
        })
        with tempfile.TemporaryDirectory() as directory:
            result = ReadingPipeline(runtime).run(7, domain="biology", output_dir=Path(directory))
            self.assertEqual(result["decision"], "ACCEPT")
            self.assertEqual(result["infrastructure"]["live_invocations"], 3)
            self.assertTrue((Path(directory) / "result.json").is_file())
            self.assertTrue((Path(directory) / "reviewer_input.json").is_file())
            self.assertTrue((Path(directory) / "solver_input.json").is_file())
            self.assertEqual(result["checks"]["answer_agreement"][0]["generator"], "B")
        self.assertEqual(len(runtime.requests), 3)
        self.assertNotIn("correct_answer", runtime.requests[1].prompt)
        self.assertNotIn("correct_answer", runtime.requests[2].prompt)

    def test_quarantine_path_preserves_first_pass_without_repair(self) -> None:
        solver = copy.deepcopy(self.solver)
        solver["answers"][2]["answer"] = "AMBIGUOUS"
        runtime = FakeRuntime({
            "reading_generator": self.generator,
            "reading_reviewer": self.reviewer,
            "reading_solver": solver,
        })
        with tempfile.TemporaryDirectory() as directory:
            result = ReadingPipeline(runtime).run(7, domain="biology", output_dir=Path(directory))
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertEqual(result["infrastructure"]["live_invocations"], 3)
            self.assertEqual(result["solver"]["answers"][2]["answer"], "AMBIGUOUS")
            self.assertFalse(result["infrastructure"]["synthetic_fallback"])

    def test_reading_does_not_change_we_v213_contract(self) -> None:
        validator_path = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts" / "validate_output.py"
        fixture_path = ROOT / "analysis" / "we_v2" / "we_v2_smoke_items.json"
        before = hashlib.sha256(validator_path.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location("reading_we_regression_validator", validator_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(validator_path.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(validator_path.parent))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertTrue(fixture["items"])
        self.assertEqual(module.schema_errors(fixture["items"][0], module.output_schema()), [])
        self.assertEqual(hashlib.sha256(validator_path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
