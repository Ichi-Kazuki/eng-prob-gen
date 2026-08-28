"""Regression tests for the Reading v0.2.5 contract hardening."""

from __future__ import annotations

import copy
import json
import unittest

from reading.contracts import (
    DISTRACTOR_METADATA_CORRECT,
    blind_input,
    blind_input_errors,
    canonicalize_generator_output,
    display_lines,
    generator_model_schema_for_plan,
    permute_generator_choices,
    target_line_for_text,
    validate_generator_contract,
)
from shared.schema_validation import schema_errors

from tests.test_reading_v02_batch import grouped_model_fixture, quota_plan, variable_generator_fixture


def _metadata(correct_answer: str) -> dict[str, dict[str, str]]:
    return {
        label: {
            "category": DISTRACTOR_METADATA_CORRECT if label == correct_answer else "TEXT_TRUE_BUT_NOT_ANSWER",
            "rationale": "The keyed choice is supported." if label == correct_answer else "It is related but does not answer the stem.",
        }
        for label in ("A", "B", "C", "D")
    }


class ReadingV025RegressionTests(unittest.TestCase):
    def test_distractor_metadata_moves_with_permuted_choices_and_does_not_mutate_input(self) -> None:
        for seed in range(9100, 9200):
            plan = quota_plan(seed, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2})
            canonical = canonicalize_generator_output(variable_generator_fixture(plan), plan)
            canonical["questions"][0]["correct_answer"] = "A"
            canonical["questions"][0]["distractor_metadata"] = _metadata("A")
            snapshot = copy.deepcopy(canonical)
            permuted, provenance = permute_generator_choices(canonical, plan)
            record = provenance["questions"][0]
            if record["original_to_canonical"]["A"] != "D":
                continue
            original_question = snapshot["questions"][0]
            permuted_question = permuted["questions"][0]
            self.assertEqual(permuted_question["correct_answer"], "D")
            self.assertEqual(permuted_question["distractor_metadata"]["D"]["category"], DISTRACTOR_METADATA_CORRECT)
            for original_label, canonical_label in record["original_to_canonical"].items():
                self.assertEqual(
                    permuted_question["distractor_metadata"][canonical_label],
                    original_question["distractor_metadata"][original_label],
                )
                self.assertEqual(permuted_question["choices"][canonical_label], original_question["choices"][original_label])
            self.assertEqual(canonical, snapshot)
            self.assertEqual(permuted, permute_generator_choices(canonical, plan)[0])
            return
        self.fail("the deterministic permutation search did not produce A -> D")

    def test_v02_schema_requires_subtype_and_distractor_metadata(self) -> None:
        plan = quota_plan(9201, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2})
        grouped = grouped_model_fixture(plan)
        schema = generator_model_schema_for_plan(plan)
        missing_subtype = copy.deepcopy(grouped)
        del missing_subtype["detail_questions"][0]["subtype"]
        self.assertTrue(schema_errors(missing_subtype, schema))
        missing_metadata = copy.deepcopy(grouped)
        del missing_metadata["detail_questions"][0]["distractor_metadata"]
        self.assertTrue(schema_errors(missing_metadata, schema))

        canonical = canonicalize_generator_output(grouped, plan)
        del canonical["questions"][0]["subtype"]
        self.assertTrue(validate_generator_contract(canonical, plan))
        canonical = canonicalize_generator_output(grouped, plan)
        del canonical["questions"][0]["distractor_metadata"]
        self.assertTrue(validate_generator_contract(canonical, plan))

    def test_v02_subtype_compatibility_and_correct_metadata_are_fail_closed(self) -> None:
        plan = quota_plan(9202, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2})
        generator = variable_generator_fixture(plan)
        generator["questions"][0]["subtype"] = "ANTECEDENT_REFERENCE"
        self.assertTrue(validate_generator_contract(generator, plan))
        generator = variable_generator_fixture(plan)
        question = generator["questions"][0]
        question["distractor_metadata"][question["correct_answer"]]["category"] = "TEXT_TRUE_BUT_NOT_ANSWER"
        self.assertTrue(validate_generator_contract(generator, plan))

    def test_v02_blind_payload_is_titleless_but_v01_retains_title(self) -> None:
        plan = quota_plan(9203, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2})
        generator = variable_generator_fixture(plan)
        generator["questions"][0]["target_text"] = "private target"
        generator["questions"][0]["target_line"] = 1
        blind = blind_input(generator, schema_version="reading-blind-input-v0.2")
        self.assertNotIn("title", blind)
        self.assertNotIn("title", json.dumps(blind))
        self.assertEqual(blind_input_errors(generator, blind, schema_version="reading-blind-input-v0.2"), [])
        legacy_blind = blind_input({**generator, "schema_version": "reading-generator-v0.1"})
        self.assertEqual(legacy_blind["title"], generator["title"])
        self.assertNotIn("correct_answer", json.dumps(blind))
        self.assertNotIn("subtype", json.dumps(blind))
        self.assertNotIn("distractor_metadata", json.dumps(blind))
        self.assertNotIn("evidence", json.dumps(blind))
        self.assertNotIn("target_text", json.dumps(blind))
        self.assertNotIn("target_line", json.dumps(blind))
        tampered = copy.deepcopy(blind)
        tampered["questions"][0]["target_line"] = 1
        self.assertTrue(blind_input_errors(generator, tampered, schema_version="reading-blind-input-v0.2"))

    def _line_target_generator(self, question_type: str) -> tuple[dict[str, object], dict[str, object]]:
        plan = quota_plan(9204, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2})
        generator = variable_generator_fixture(plan)
        question = next(item for item in generator["questions"] if item["question_type"] == question_type)
        target_text = "filaments" if question_type == "VOCABULARY_IN_CONTEXT" else "the communities"
        line = target_line_for_text(generator["passage"], target_text)
        assert line is not None
        if question_type == "VOCABULARY_IN_CONTEXT":
            question["stem"] = f"The word '{target_text}' in line {line} is closest in meaning to"
        else:
            question["stem"] = f"The word '{target_text}' in line {line} refers to"
        question["target_text"] = target_text
        question["target_line"] = line
        question["evidence"] = {
            "paragraph": 2,
            "anchor": "filaments bind loose particles",
            "rationale": question["evidence"]["rationale"],
        }
        return plan, generator

    def test_line_number_target_resolves_and_is_validated(self) -> None:
        for question_type in ("VOCABULARY_IN_CONTEXT", "REFERENCE"):
            with self.subTest(question_type=question_type):
                plan, generator = self._line_target_generator(question_type)
                self.assertEqual(validate_generator_contract(generator, plan), [])
                question = next(item for item in generator["questions"] if item["question_type"] == question_type)
                self.assertIn(question["target_text"], display_lines(generator["passage"])[question["target_line"] - 1])

    def test_invalid_line_and_absent_target_fail_closed(self) -> None:
        plan, generator = self._line_target_generator("REFERENCE")
        question = next(item for item in generator["questions"] if item["question_type"] == "REFERENCE")
        question["target_line"] = 10_000
        question["stem"] = "The word 'it' in line 10000 refers to"
        self.assertTrue(validate_generator_contract(generator, plan))

        plan, generator = self._line_target_generator("VOCABULARY_IN_CONTEXT")
        question = next(item for item in generator["questions"] if item["question_type"] == "VOCABULARY_IN_CONTEXT")
        question["target_line"] += 1
        self.assertTrue(any("VOCABULARY_IN_CONTEXT_TARGET_LINE_MISMATCH" in error for error in validate_generator_contract(generator, plan)))

        plan, generator = self._line_target_generator("VOCABULARY_IN_CONTEXT")
        question = next(item for item in generator["questions"] if item["question_type"] == "VOCABULARY_IN_CONTEXT")
        question["target_text"] = "not-present"
        question["stem"] = f"The word 'not-present' in line {question['target_line']} is closest in meaning to"
        errors = validate_generator_contract(generator, plan)
        self.assertTrue(any("VOCABULARY_IN_CONTEXT_TARGET_NOT_FOUND" in error for error in errors))

    def test_canonical_order_uses_evidence_position_and_is_replayable(self) -> None:
        plan = quota_plan(9205, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2})
        generator = variable_generator_fixture(plan)
        anchors = {
            1: "During daylight",
            2: "Researchers studying",
            3: "The algae are",
            4: "These observations",
        }
        for index, question in enumerate(generator["questions"]):
            paragraph = index % 4 + 1
            question["evidence"] = {
                "paragraph": paragraph,
                "anchor": anchors[paragraph],
                "rationale": question["evidence"]["rationale"],
            }
        paragraph_two = [question for question in generator["questions"] if question["evidence"]["paragraph"] == 2]
        paragraph_two[0]["evidence"]["anchor"] = "Researchers studying"
        paragraph_two[1]["evidence"]["anchor"] = "filaments bind loose particles"
        main = next(question for question in generator["questions"] if question["question_type"] == "MAIN_IDEA")
        main["evidence"]["paragraph"] = 4
        main["evidence"]["anchor"] = anchors[4]
        first = canonicalize_generator_output(generator, plan)
        second = canonicalize_generator_output(generator, plan)
        self.assertEqual(first, second)
        self.assertEqual(first["questions"][0]["question_type"], "MAIN_IDEA")
        non_global = [question for question in first["questions"] if question["question_type"] != "MAIN_IDEA"]
        self.assertEqual(
            [question["evidence"]["paragraph"] for question in non_global],
            sorted(question["evidence"]["paragraph"] for question in non_global),
        )
        paragraph_two_order = [
            question["evidence"]["anchor"]
            for question in first["questions"]
            if question["evidence"]["paragraph"] == 2
        ]
        self.assertEqual(paragraph_two_order, ["Researchers studying", "filaments bind loose particles"])
        permuted_first, provenance_first = permute_generator_choices(first, plan)
        permuted_second, provenance_second = permute_generator_choices(first, plan)
        self.assertEqual(permuted_first, permuted_second)
        self.assertEqual(provenance_first, provenance_second)
        self.assertEqual([record["item_id"] for record in provenance_first["questions"]], [
            f"{plan['passage_id']}-q{index}" for index in range(1, plan["question_count"] + 1)
        ])


if __name__ == "__main__":
    unittest.main()
