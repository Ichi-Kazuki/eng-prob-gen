"""Focused offline tests for Reading target-presence hardening."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reading.contracts import (
    HARD_VALIDITY,
    canonicalize_generator_output,
    deterministic_diagnostics,
    validate_deterministic,
    validate_generator_contract,
)
from reading.pipeline import ReadingV02Pipeline
from reading.planner import build_plan_v02
from runtime.adapters import InvocationResult


ROOT = Path(__file__).resolve().parents[1]
MALFORMED_V024_GENERATOR = (
    ROOT
    / "runs"
    / "reading_v0_2"
    / "reading-v02-batch-20260828T103121Z-9cbb1bade1"
    / "passage-001"
    / "generator.json"
)
MALFORMED_V024_PLAN = MALFORMED_V024_GENERATOR.with_name("plan.json")


def target_generator(question_type: str, stem: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan = build_plan_v02(1002, domain="biology")
    generator = local_generator_fixture(plan)
    question = next(question for question in generator["questions"] if question["question_type"] == question_type)
    question["stem"] = stem
    question["evidence"] = {
        "paragraph": 2,
        "anchor": "filaments bind loose particles",
        "rationale": question["evidence"]["rationale"],
    }
    return plan, generator, question


def local_generator_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    passage = "\n\n".join([
        "In shallow coastal marshes, algae form thin communities on sediment surfaces. These communities influence how oxygen and nutrients move through mud. During daylight, algae draw carbon dioxide from water and release oxygen. Their activity changes with temperature, salinity, and exposure. Researchers compare plots to understand this pattern. Evidence marker 1.",
        "Researchers have found that these communities do more than provide food for small animals. Their filaments bind loose particles, reducing sediment carried away by tides. This stabilizing effect is strongest where water moves slowly. A sheltered inlet may retain fine material and support additional organisms. Evidence marker 2.",
        "The algae are not equally abundant in every season. Intense sunlight can increase growth, but prolonged exposure can dry the surface and interrupt gas exchange. Field teams compare shaded and exposed plots rather than treating one measurement as representative. This approach reveals how resilience depends on repeated adjustments. Evidence marker 3.",
        "These observations have practical implications for restoring damaged wetlands. A project that adds sediment but ignores surface communities may create a landscape that looks stable while remaining vulnerable to erosion. Planners protect sheltered zones and monitor oxygen, salinity, and particle movement together. Evidence marker 4.",
    ])
    questions = []
    for index, question_type in enumerate(plan["question_plan"], 1):
        paragraph = (index - 1) % 4 + 1
        questions.append({
            "item_id": f"{plan['passage_id']}-q{index}",
            "question_type": question_type,
            "stem": f"Which statement is supported by the passage in item {index}?",
            "choices": {
                "A": "It is connected with the conditions described by the author.",
                "B": "It occurs only after the marsh has completely dried.",
                "C": "It is unrelated to the movement of water or sediment.",
                "D": "It was rejected by every researcher in the study.",
            },
            "correct_answer": "A",
            "evidence": {
                "paragraph": paragraph,
                "anchor": f"Evidence marker {paragraph}",
                "rationale": "The cited passage language supports the intended choice.",
            },
        })
    return {
        "schema_version": "reading-generator-v0.2",
        "passage_id": plan["passage_id"],
        "section": "READING_COMPREHENSION",
        "title": "Surface Communities in Coastal Marshes",
        "passage": passage,
        "questions": questions,
    }


class CountingGeneratorRuntime:
    provider = "offline-test"
    cli_version = "offline-target-presence"

    def __init__(self, generator: dict[str, Any]) -> None:
        self.generator = generator
        self.stages: list[str] = []

    def invoke(self, request: Any) -> InvocationResult:
        self.stages.append(request.stage)
        if request.stage != "reading_generator":
            raise AssertionError("Reviewer/Solver must not be invoked after a hard target failure")
        return InvocationResult(
            stage=request.stage,
            agent_name=request.agent_name,
            invocation_id="offline-generator-1",
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:01+00:00",
            provider=self.provider,
            model="offline",
            cli_version=self.cli_version,
            exit_code=0,
            parsed=copy.deepcopy(self.generator),
            input_keys=list(request.input_keys),
        )


class ReadingTargetPresenceTests(unittest.TestCase):
    def test_reference_target_present_in_claimed_paragraph_passes(self) -> None:
        plan, generator, _question = target_generator(
            "REFERENCE",
            'The word "filaments" in paragraph 2 refers to',
        )
        self.assertEqual(validate_generator_contract(generator, plan), [])
        self.assertEqual(validate_deterministic(generator, plan), [])

    def test_reference_target_absent_is_hard_validity_failure(self) -> None:
        plan, generator, question = target_generator(
            "REFERENCE",
            'The word "unmentioned" in paragraph 2 refers to',
        )
        errors = validate_deterministic(generator, plan)
        self.assertTrue(any("REFERENCE_TARGET_NOT_FOUND" in error for error in errors))
        self.assertEqual(deterministic_diagnostics(generator, plan)["classification"], HARD_VALIDITY)
        self.assertEqual(question["stem"], 'The word "unmentioned" in paragraph 2 refers to')

    def test_reference_target_in_another_paragraph_is_a_hard_failure(self) -> None:
        plan, generator, _question = target_generator(
            "REFERENCE",
            'The word "algae" in paragraph 2 refers to',
        )
        errors = validate_deterministic(generator, plan)
        self.assertTrue(any("REFERENCE_TARGET_NOT_FOUND" in error for error in errors))
        self.assertEqual(deterministic_diagnostics(generator, plan)["classification"], HARD_VALIDITY)

    def test_reference_target_allows_quotes_and_edge_punctuation(self) -> None:
        plan, generator, _question = target_generator(
            "REFERENCE",
            'The word “filaments,” in paragraph 2 refers to',
        )
        self.assertEqual(validate_deterministic(generator, plan), [])

    def test_target_check_does_not_use_fuzzy_substrings_or_semantics(self) -> None:
        plan, generator, _question = target_generator(
            "REFERENCE",
            'The word "filament" in paragraph 2 refers to',
        )
        errors = validate_deterministic(generator, plan)
        self.assertTrue(any("REFERENCE_TARGET_NOT_FOUND" in error for error in errors))

        plan, generator, _question = target_generator(
            "REFERENCE",
            'The word "soil" in paragraph 2 refers to',
        )
        errors = validate_deterministic(generator, plan)
        self.assertTrue(any("REFERENCE_TARGET_NOT_FOUND" in error for error in errors))

    def test_vocabulary_target_presence_is_checked_when_explicitly_identified(self) -> None:
        plan, generator, _question = target_generator(
            "VOCABULARY_IN_CONTEXT",
            'The word "filaments" in paragraph 2 is closest in meaning to',
        )
        self.assertEqual(validate_deterministic(generator, plan), [])

        _plan, generator, _question = target_generator(
            "VOCABULARY_IN_CONTEXT",
            'The word "unmentioned" in paragraph 2 is closest in meaning to',
        )
        self.assertTrue(any("VOCABULARY_IN_CONTEXT_TARGET_NOT_FOUND" in error for error in validate_deterministic(generator, plan)))

    def test_v024_malformed_target_pattern_is_caught_offline(self) -> None:
        self.assertTrue(MALFORMED_V024_GENERATOR.is_file())
        self.assertTrue(MALFORMED_V024_PLAN.is_file())
        generator = json.loads(MALFORMED_V024_GENERATOR.read_text(encoding="utf-8"))
        plan = json.loads(MALFORMED_V024_PLAN.read_text(encoding="utf-8"))
        generator["questions"][0]["stem"] = 'The word "not-present" in paragraph 2 refers to'
        errors = validate_deterministic(generator, plan)
        self.assertTrue(any("REFERENCE_TARGET_NOT_FOUND" in error for error in errors))
        self.assertEqual(deterministic_diagnostics(generator, plan)["classification"], HARD_VALIDITY)

    def test_hard_target_failure_skips_reviewer_and_solver(self) -> None:
        plan, generator, _question = target_generator(
            "REFERENCE",
            'The word "not-present" in paragraph 2 refers to',
        )
        runtime = CountingGeneratorRuntime(generator)
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(runtime).run(plan["seed"], domain=plan["domain"], output_dir=Path(directory))
        self.assertEqual(runtime.stages, ["reading_generator"])
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(result["checks"]["deterministic_classification"], HARD_VALIDITY)
        self.assertTrue(any("REFERENCE_TARGET_NOT_FOUND" in error for error in result["checks"]["generator_errors"]))

    def test_canonicalization_remains_semantically_unchanged(self) -> None:
        plan, generator, _question = target_generator(
            "REFERENCE",
            'The word "filaments" in paragraph 2 refers to',
        )
        snapshot = copy.deepcopy(generator)
        canonical = canonicalize_generator_output(generator, plan)
        self.assertEqual(generator, snapshot)
        self.assertEqual(canonical["questions"][0]["stem"], generator["questions"][0]["stem"])
        self.assertEqual(canonical["questions"][0]["evidence"], generator["questions"][0]["evidence"])


if __name__ == "__main__":
    unittest.main()
