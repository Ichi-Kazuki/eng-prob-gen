"""Offline contract and integration tests for isolated Structure v0.1."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from runtime.adapters import InvocationRequest, InvocationResult
from structure.blinding import blind_input_errors, build_blind_input
from structure.contracts import (
    LETTERS,
    normalized_option_surface,
    validate_generator_contract,
    validate_plan,
    validate_reviewer_contract,
    validate_solver_contract,
)
from structure.permutation import PERMUTATION_VERSION, permute_generator_output
from structure.pipeline import StructurePipeline
from structure.planner import CLAUSE_COUNT_WEIGHTS, LENGTH_BINS, PRIMARY_TARGET_WEIGHTS, VOCABULARY_DOMAINS, build_plan


def generator_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    return {"items": [{
        "item_id": planned["item_id"], "section": "Structure", "primary_target": planned["primary_target"],
        "subtype": planned["subtype"], "secondary_features": ["academic register"],
        "difficulty": planned["difficulty"], "vocabulary_domain": planned["vocabulary_domain"],
        "stem": "The researcher ____ the documented pattern in the archive.",
        "options": {"A": "is", "B": "are", "C": "be", "D": "being"}, "correct_answer": "A",
        "answer_explanation": "The singular subject requires the finite form is.",
        "distractor_rationales": {
            "A": "Correct singular finite completion.", "B": "Plural agreement is incorrect.",
            "C": "The base form cannot fill this finite slot.", "D": "The participle cannot fill this finite slot.",
        },
    } for planned in plan["items"]]}


def reviewer_fixture(blind: dict[str, Any], *, first_best: str | None = None, natural: bool = True, serious: bool = False) -> dict[str, Any]:
    items = []
    for index, item in enumerate(blind["items"]):
        correct = next(letter for letter in LETTERS if item["options"][letter] == "is")
        items.append({
            "item_id": item["item_id"],
            "option_judgments": {letter: ("VALID" if letter == correct else "INVALID") for letter in LETTERS},
            "best_answer": first_best if index == 0 and first_best is not None else correct,
            "natural_wording": natural, "serious_defect": serious,
            "comment": "Only one option forms the intended sentence.",
        })
    return {"items": items}


def solver_fixture(blind: dict[str, Any], *, first_answer: str | None = None, confidence: str = "HIGH") -> dict[str, Any]:
    items = []
    for index, item in enumerate(blind["items"]):
        correct = next(letter for letter in LETTERS if item["options"][letter] == "is")
        items.append({
            "item_id": item["item_id"],
            "answer": first_answer if index == 0 and first_answer is not None else correct,
            "confidence": confidence, "reason": "The singular finite completion is the only acceptable choice.",
        })
    return {"items": items}


class FixtureRuntime:
    provider = "offline-fixture"
    cli_version = "offline-fixture"
    model = "offline-fixture"

    def __init__(self, *, reviewer: dict[str, Any] | None = None, solver: dict[str, Any] | None = None) -> None:
        self.reviewer_override = reviewer
        self.solver_override = solver
        self.requests: list[InvocationRequest] = []

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
        if request.stage == "structure_generator":
            parsed = generator_fixture(payload)
        elif request.stage == "structure_reviewer":
            parsed = self.reviewer_override or reviewer_fixture(payload)
        elif request.stage == "structure_solver":
            parsed = self.solver_override or solver_fixture(payload)
        else:  # pragma: no cover
            raise AssertionError(f"unexpected stage: {request.stage}")
        return InvocationResult(
            stage=request.stage, agent_name=request.agent_name, invocation_id=f"offline-{len(self.requests)}",
            started_at="2026-01-01T00:00:00+00:00", completed_at="2026-01-01T00:00:01+00:00",
            provider=self.provider, model=self.model, cli_version=self.cli_version, parsed=parsed,
            input_keys=list(request.input_keys),
        )


class StructurePlannerTests(unittest.TestCase):
    def test_replay_and_different_seed(self) -> None:
        self.assertEqual(build_plan(17), build_plan(17))
        self.assertNotEqual(build_plan(17), build_plan(18))

    def test_plan_size_profile_and_boundaries(self) -> None:
        plan = build_plan(91)
        self.assertEqual(len(plan["items"]), 15)
        self.assertEqual(validate_plan(plan), [])
        self.assertTrue(all(item["primary_target"] in PRIMARY_TARGET_WEIGHTS for item in plan["items"]))
        self.assertNotIn("WORD_CLASS_FORM", {item["primary_target"] for item in plan["items"]})
        self.assertTrue(all(item["vocabulary_domain"] in VOCABULARY_DOMAINS for item in plan["items"]))
        self.assertTrue(all(item["clause_count"] in CLAUSE_COUNT_WEIGHTS for item in plan["items"]))
        self.assertEqual(CLAUSE_COUNT_WEIGHTS, {1: 27, 2: 37, 3: 10, 4: 1})
        for item in plan["items"]:
            self.assertGreaterEqual(item["target_word_count"], item["sentence_length_bin"]["minimum"])
            self.assertLessEqual(item["target_word_count"], item["sentence_length_bin"]["maximum"])
        self.assertEqual([(entry["minimum"], entry["maximum"]) for entry in LENGTH_BINS], [(10, 14), (15, 19), (20, 24), (25, 27)])


class StructurePermutationTests(unittest.TestCase):
    def test_exact_answer_distribution_and_replay(self) -> None:
        source = generator_fixture(build_plan(31))
        first, record = permute_generator_output(source, 31)
        second, record_again = permute_generator_output(source, 31)
        self.assertEqual(first, second)
        self.assertEqual(record, record_again)
        self.assertEqual(record["version"], PERMUTATION_VERSION)
        self.assertEqual(sorted(record["final_answer_position_distribution"].values()), [3, 4, 4, 4])
        self.assertEqual(sum(record["final_answer_position_distribution"].values()), 15)

    def test_distractor_rationales_follow_the_option_mapping(self) -> None:
        source = generator_fixture(build_plan(32))
        permuted, record = permute_generator_output(source, 32)
        for source_item, output_item, mapping in zip(source["items"], permuted["items"], record["items"]):
            for canonical, original in mapping["canonical_to_original"].items():
                self.assertEqual(output_item["options"][canonical], source_item["options"][original])
                self.assertEqual(output_item["distractor_rationales"][canonical], source_item["distractor_rationales"][original])


class StructureContractTests(unittest.TestCase):
    def test_duplicate_option_and_unicode_surface_detection(self) -> None:
        self.assertEqual(normalized_option_surface("  Cafe" + chr(0x301) + "  "), normalized_option_surface("cafe" + chr(0x301)))
        output = generator_fixture(build_plan(41))
        output["items"][0]["options"]["B"] = "  IS  "
        self.assertTrue(any("duplicates option A" in error for error in validate_generator_contract(output, build_plan(41))))

    def test_missing_duplicate_ids_metadata_and_blank_are_rejected(self) -> None:
        plan = build_plan(42)
        output = generator_fixture(plan)
        output["items"][0]["item_id"] = output["items"][1]["item_id"]
        output["items"][1]["primary_target"] = "WORD_CLASS_FORM"
        output["items"][2]["stem"] = "The researcher examined the archive."
        errors = validate_generator_contract(output, plan)
        self.assertTrue(any("duplicate item_id" in error for error in errors))
        self.assertTrue(any("primary_target does not match" in error for error in errors))
        self.assertTrue(any("blank marker" in error for error in errors))

    def test_missing_or_malformed_item_ids_are_rejected(self) -> None:
        plan = build_plan(45)
        missing = generator_fixture(plan)
        missing["items"] = missing["items"][:-1]
        self.assertTrue(any("exactly 15" in error for error in validate_generator_contract(missing, plan)))
        malformed = generator_fixture(plan)
        malformed["items"][0] = "not an item"
        self.assertTrue(validate_generator_contract(malformed, plan))

    def test_blind_inputs_are_allowlisted_and_leakage_is_rejected(self) -> None:
        plan = build_plan(43)
        generator = generator_fixture(plan)
        blind = build_blind_input(generator)
        self.assertEqual(set(blind["items"][0]), {"item_id", "section", "stem", "options"})
        self.assertEqual(blind_input_errors(generator, blind, plan), [])
        leaked = copy.deepcopy(blind)
        leaked["items"][0]["correct_answer"] = "A"
        self.assertTrue(blind_input_errors(generator, leaked, plan))

    def test_reviewer_and_solver_contracts_reject_leakage(self) -> None:
        plan = build_plan(44)
        blind = build_blind_input(generator_fixture(plan))
        reviewer = reviewer_fixture(blind)
        reviewer["items"][0]["correct_answer"] = "A"
        solver = solver_fixture(blind)
        solver["items"][0]["primary_target"] = "CLAUSE_STRUCTURE"
        self.assertTrue(validate_reviewer_contract(reviewer, blind, plan))
        self.assertTrue(validate_solver_contract(solver, blind, plan))


class StructurePipelineTests(unittest.TestCase):
    def run_fixture(self, runtime: FixtureRuntime) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as directory:
            result = StructurePipeline(runtime).run(51, output_dir=Path(directory))
            for filename in ("plan.json", "generator_raw.json", "generator.json", "reviewer_input.json", "reviewer.json", "solver_input.json", "solver.json", "result.json"):
                self.assertTrue((Path(directory) / filename).is_file())
            self.assertTrue((Path(directory) / "provenance" / "provenance.json").is_file())
            return result

    def test_clean_fixture_accepts_with_exactly_three_logical_calls(self) -> None:
        runtime = FixtureRuntime()
        result = self.run_fixture(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(result["live_invocation_count"], 3)
        self.assertEqual([request.stage for request in runtime.requests], ["structure_generator", "structure_reviewer", "structure_solver"])
        self.assertEqual(sorted(result["final_answer_position_distribution"].values()), [3, 4, 4, 4])

    def test_one_defective_item_quarantines_the_whole_set(self) -> None:
        plan = build_plan(51)
        permuted, _ = permute_generator_output(generator_fixture(plan), 51)
        blind = build_blind_input(permuted)
        correct = next(letter for letter in LETTERS if blind["items"][0]["options"][letter] == "is")
        bad_best = next(letter for letter in LETTERS if letter != correct)
        result = self.run_fixture(FixtureRuntime(reviewer=reviewer_fixture(blind, first_best=bad_best)))
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(sum(item["accepted"] for item in result["item_results"]), 14)
        self.assertTrue(result["item_results"][0]["rejection_reasons"])

    def test_each_final_gate_blocks_accept(self) -> None:
        plan = build_plan(51)
        permuted, _ = permute_generator_output(generator_fixture(plan), 51)
        blind = build_blind_input(permuted)
        correct = next(letter for letter in LETTERS if blind["items"][0]["options"][letter] == "is")
        wrong = next(letter for letter in LETTERS if letter != correct)
        marginal = reviewer_fixture(blind)
        marginal["items"][0]["option_judgments"][wrong] = "MARGINAL"
        cases = {
            "reviewer_ambiguous": (reviewer_fixture(blind, first_best="AMBIGUOUS"), None),
            "reviewer_none": (reviewer_fixture(blind, first_best="NONE"), None),
            "solver_ambiguous": (None, solver_fixture(blind, first_answer="AMBIGUOUS")),
            "solver_none": (None, solver_fixture(blind, first_answer="NONE")),
            "reviewer_key_disagreement": (reviewer_fixture(blind, first_best=wrong), None),
            "solver_key_disagreement": (None, solver_fixture(blind, first_answer=wrong)),
            "low_confidence": (None, solver_fixture(blind, confidence="LOW")),
            "serious_defect": (reviewer_fixture(blind, serious=True), None),
            "unnatural_wording": (reviewer_fixture(blind, natural=False), None),
            "marginal_uniqueness": (marginal, None),
        }
        for name, (reviewer, solver) in cases.items():
            with self.subTest(case=name):
                result = self.run_fixture(FixtureRuntime(reviewer=reviewer, solver=solver))
                self.assertEqual(result["decision"], "QUARANTINE")

    def test_blind_payloads_have_no_private_fields(self) -> None:
        runtime = FixtureRuntime()
        result = self.run_fixture(runtime)
        for request in runtime.requests[1:]:
            payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
            self.assertEqual(set(payload), {"items"})
            self.assertEqual(set(payload["items"][0]), {"item_id", "section", "stem", "options"})
            self.assertNotIn("correct_answer", request.prompt)
            self.assertNotIn("primary_target", request.prompt)
            self.assertNotIn("distractor_rationales", request.prompt)
        self.assertEqual(result["infrastructure"]["invocation_counts"], {"generator": 1, "reviewer": 1, "solver": 1})


if __name__ == "__main__":
    unittest.main()
