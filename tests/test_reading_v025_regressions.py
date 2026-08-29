"""Regression tests for the Reading v0.2.5 contract hardening."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reading.contracts import (
    DISTRACTOR_METADATA_CORRECT,
    blind_input,
    blind_input_errors,
    canonicalize_generator_output,
    display_lines,
    generator_model_schema_for_plan,
    normalize_target_line_metadata,
    permute_generator_choices,
    solver_input_errors,
    target_line_for_text,
    validate_generator_contract,
)
from reading.pipeline import ReadingV02Pipeline
from reading.planner import build_plan_v02
from runtime.adapters import InvocationResult
from shared.schema_validation import load_schema, schema_errors

from tests.test_reading_v02_batch import (
    grouped_model_fixture,
    inference_verifier_for,
    quota_plan,
    reviewer_for,
    solver_for,
    variable_generator_fixture,
)


def _metadata(correct_answer: str) -> dict[str, dict[str, str]]:
    return {
        label: {
            "category": DISTRACTOR_METADATA_CORRECT if label == correct_answer else "TEXT_TRUE_BUT_NOT_ANSWER",
            "rationale": "The keyed choice is supported." if label == correct_answer else "It is related but does not answer the stem.",
        }
        for label in ("A", "B", "C", "D")
    }


def _grouped_questions(grouped: dict[str, object]) -> list[dict[str, object]]:
    questions: list[dict[str, object]] = []
    for field_name in (
        "detail_questions",
        "vocabulary_in_context_questions",
        "inference_questions",
        "main_idea_questions",
        "reference_questions",
    ):
        values = grouped[field_name]
        assert isinstance(values, list)
        questions.extend(question for question in values if isinstance(question, dict))
    return questions


class ReadingV025RegressionTests(unittest.TestCase):
    def test_transport_null_targets_are_omitted_without_changing_raw_or_answers(self) -> None:
        plan = quota_plan(
            9206,
            {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2},
        )
        grouped = grouped_model_fixture(plan)
        for question in _grouped_questions(grouped):
            question["target_text"] = None
            question["target_line"] = None
        raw_snapshot = copy.deepcopy(grouped)

        permuted, provenance = permute_generator_choices(grouped, plan)
        self.assertEqual(grouped, raw_snapshot)
        for question in _grouped_questions(permuted):
            self.assertNotIn("target_text", question)
            self.assertNotIn("target_line", question)

        absent_grouped = grouped_model_fixture(plan)
        absent_permuted, _absent_provenance = permute_generator_choices(absent_grouped, plan)
        for question in _grouped_questions(absent_permuted):
            self.assertNotIn("target_text", question)
            self.assertNotIn("target_line", question)

        canonical = canonicalize_generator_output(permuted, plan)
        self.assertEqual(schema_errors(canonical, load_schema("reading/schemas/reading_generator_output_v0_2.schema.json")), [])
        self.assertEqual(validate_generator_contract(canonical, plan), [])
        self.assertEqual(len(provenance["questions"]), plan["question_count"])
        for record in provenance["questions"]:
            self.assertEqual(set(record["original_to_canonical"]), {"A", "B", "C", "D"})
            self.assertEqual(set(record["canonical_to_original"]), {"A", "B", "C", "D"})

        blind = blind_input(canonical, schema_version="reading-blind-input-v0.2")
        self.assertEqual(
            blind_input_errors(canonical, blind, schema_version="reading-blind-input-v0.2"),
            [],
        )
        self.assertEqual(
            solver_input_errors(canonical, blind, schema_version="reading-blind-input-v0.2"),
            [],
        )

    def test_valid_targets_survive_permutation_and_nulls_are_not_synthesized(self) -> None:
        plan = quota_plan(
            9207,
            {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2},
        )
        grouped = grouped_model_fixture(plan)
        questions = _grouped_questions(grouped)
        questions[0]["target_text"] = "exact target text"
        questions[0]["target_line"] = 4
        questions[1]["target_text"] = None
        questions[1]["target_line"] = None
        original_values = {
            questions[0]["stem"]: ("exact target text", 4),
            questions[1]["stem"]: (None, None),
        }

        permuted, _provenance = permute_generator_choices(grouped, plan)
        for question in _grouped_questions(permuted):
            expected = original_values.get(question["stem"])
            if expected is None:
                continue
            target_text, target_line = expected
            self.assertEqual(question.get("target_text"), target_text)
            self.assertEqual(question.get("target_line"), target_line)
            if target_text is None:
                self.assertNotIn("target_text", question)
                self.assertNotIn("target_line", question)

        canonical = canonicalize_generator_output(permuted, plan)
        for question in canonical["questions"]:
            if question["stem"] == questions[0]["stem"]:
                self.assertEqual(question["target_text"], "exact target text")
                self.assertEqual(question["target_line"], 4)
            self.assertFalse(
                ("target_text" in question and question["target_text"] is None)
                or ("target_line" in question and question["target_line"] is None)
            )

    def test_line_target_presence_validation_still_rejects_omitted_transport_targets(self) -> None:
        plan = quota_plan(
            9208,
            {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2},
        )
        generator = variable_generator_fixture(plan)
        question = next(item for item in generator["questions"] if item["question_type"] == "REFERENCE")
        target_text = "the communities"
        line = target_line_for_text(generator["passage"], target_text)
        assert line is not None
        question["stem"] = f"The word '{target_text}' in line {line} refers to"
        question["target_text"] = None
        question["target_line"] = None
        question["evidence"]["paragraph"] = 2
        question["evidence"]["anchor"] = "filaments bind loose particles"

        permuted, _provenance = permute_generator_choices(generator, plan)
        canonical = canonicalize_generator_output(permuted, plan)
        errors = validate_generator_contract(canonical, plan)
        self.assertTrue(any("REFERENCE_TARGET_METADATA_MISSING" in error for error in errors))

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

    def _wrong_unique_line_case(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        plan, generator = self._line_target_generator("VOCABULARY_IN_CONTEXT")
        question = next(item for item in generator["questions"] if item["question_type"] == "VOCABULARY_IN_CONTEXT")
        canonical_line = question["target_line"]
        assert isinstance(canonical_line, int)
        generator_line = canonical_line - 1
        target_text = "Filaments"
        question["target_text"] = target_text
        question["target_line"] = generator_line
        question["stem"] = (
            f" \tThe  word  'filaments'  in  line {generator_line} "
            "is closest in meaning to  "
        )
        return plan, generator, {
            "question": question,
            "canonical_line": canonical_line,
            "generator_line": generator_line,
        }

    def test_unique_target_normalizes_structured_and_embedded_lines_only(self) -> None:
        plan, raw, details = self._wrong_unique_line_case()
        raw_snapshot = copy.deepcopy(raw)
        permuted, permutation = permute_generator_choices(raw, plan)
        canonical = canonicalize_generator_output(permuted, plan)
        target = next(
            question for question in canonical["questions"]
            if question["question_type"] == "VOCABULARY_IN_CONTEXT"
        )
        original_canonical_question = copy.deepcopy(target)

        normalized, provenance = normalize_target_line_metadata(canonical)
        corrected = next(
            question for question in normalized["questions"]
            if question["question_type"] == "VOCABULARY_IN_CONTEXT"
        )
        expected_line = details["canonical_line"]
        self.assertEqual(corrected["target_line"], expected_line)
        self.assertEqual(corrected["target_text"], "Filaments")
        self.assertEqual(
            corrected["stem"],
            original_canonical_question["stem"].replace(
                f"line {details['generator_line']}", f"line {expected_line}"
            ),
        )
        self.assertEqual(
            corrected["stem"].replace(f"line {expected_line}", "line N"),
            original_canonical_question["stem"].replace(
                f"line {details['generator_line']}", "line N"
            ),
        )
        self.assertEqual(corrected["choices"], original_canonical_question["choices"])
        self.assertEqual(corrected["correct_answer"], original_canonical_question["correct_answer"])
        self.assertEqual(raw, raw_snapshot)
        self.assertEqual(
            validate_generator_contract(normalized, plan),
            [],
        )

        record = next(
            item for item in provenance["questions"]
            if item["item_id"] == corrected["item_id"]
        )
        self.assertEqual(record["generator_target_line"], details["generator_line"])
        self.assertEqual(record["canonical_target_line"], expected_line)
        self.assertEqual(record["target_line_resolution"], "UNIQUE_SURFACE_MATCH")
        self.assertTrue(record["stem_line_normalized"])
        self.assertEqual(record["matched_display_lines"], [expected_line])
        self.assertEqual(
            permutation["questions"][0]["original_to_canonical"].keys(),
            {"A", "B", "C", "D"},
        )

    def test_correct_generator_line_is_unchanged_and_normalization_is_idempotent(self) -> None:
        plan, generator = self._line_target_generator("REFERENCE")
        raw_snapshot = copy.deepcopy(generator)
        permuted, _permutation = permute_generator_choices(generator, plan)
        canonical = canonicalize_generator_output(permuted, plan)
        before = copy.deepcopy(canonical)

        normalized, provenance = normalize_target_line_metadata(canonical)
        self.assertEqual(normalized, before)
        record = next(item for item in provenance["questions"] if item["canonical_target_line"] is not None)
        self.assertEqual(record["generator_target_line"], record["canonical_target_line"])
        self.assertFalse(record["stem_line_normalized"])
        normalized_again, provenance_again = normalize_target_line_metadata(normalized)
        self.assertEqual(normalized_again, normalized)
        self.assertEqual(provenance_again, provenance)
        self.assertEqual(generator, raw_snapshot)

    def test_zero_target_match_remains_a_hard_target_not_found_failure(self) -> None:
        plan, generator = self._line_target_generator("VOCABULARY_IN_CONTEXT")
        question = next(item for item in generator["questions"] if item["question_type"] == "VOCABULARY_IN_CONTEXT")
        target_line = question["target_line"]
        question["target_text"] = "not-present"
        question["stem"] = f"The word 'not-present' in line {target_line} is closest in meaning to"

        normalized, provenance = normalize_target_line_metadata(generator)
        self.assertEqual(normalized, generator)
        record = next(item for item in provenance["questions"] if item["question_index"] == generator["questions"].index(question) + 1)
        self.assertEqual(record["target_line_resolution"], "ZERO_SURFACE_MATCH")
        self.assertTrue(any("VOCABULARY_IN_CONTEXT_TARGET_NOT_FOUND" in error for error in validate_generator_contract(normalized, plan)))

    def test_multiple_target_matches_preserve_a_valid_supplied_line(self) -> None:
        plan, generator = self._line_target_generator("REFERENCE")
        paragraphs = generator["passage"].split("\n\n")
        paragraphs[0] += " Some"
        paragraphs[1] += " Some"
        generator["passage"] = "\n\n".join(paragraphs)
        question = next(item for item in generator["questions"] if item["question_type"] == "REFERENCE")
        question["target_text"] = "Some"
        lines = display_lines(generator["passage"])
        matching_lines = [index for index, line in enumerate(lines, 1) if "some" in line.casefold().split()]
        self.assertGreaterEqual(len(matching_lines), 2)
        question["target_line"] = matching_lines[0]
        question["stem"] = f"The word 'Some' in line {matching_lines[0]} refers to"

        normalized, provenance = normalize_target_line_metadata(generator)
        self.assertEqual(normalized, generator)
        record = next(item for item in provenance["questions"] if item["target_line_resolution"] == "SUPPLIED_LINE_MATCH")
        self.assertEqual(record["canonical_target_line"], matching_lines[0])
        self.assertEqual(record["matched_display_lines"], matching_lines)
        self.assertFalse(record["stem_line_normalized"])
        self.assertEqual(validate_generator_contract(normalized, plan), [])

    def test_multiple_target_matches_fail_closed_when_supplied_line_is_not_a_match(self) -> None:
        plan, generator = self._line_target_generator("REFERENCE")
        paragraphs = generator["passage"].split("\n\n")
        paragraphs[0] += " Some"
        paragraphs[1] += " Some"
        generator["passage"] = "\n\n".join(paragraphs)
        question = next(item for item in generator["questions"] if item["question_type"] == "REFERENCE")
        question["target_text"] = "Some"
        lines = display_lines(generator["passage"])
        matching_lines = [index for index, line in enumerate(lines, 1) if "some" in line.casefold().split()]
        supplied_line = next(index for index in range(1, len(lines) + 1) if index not in matching_lines)
        question["target_line"] = supplied_line
        question["stem"] = f"The word 'Some' in line {supplied_line} refers to"

        normalized, provenance = normalize_target_line_metadata(generator)
        self.assertEqual(normalized, generator)
        record = next(item for item in provenance["questions"] if item["question_index"] == generator["questions"].index(question) + 1)
        self.assertEqual(record["target_line_resolution"], "MULTIPLE_SURFACE_MATCH")
        self.assertIsNone(record["canonical_target_line"])
        self.assertEqual(record["matched_display_lines"], matching_lines)
        self.assertTrue(any("REFERENCE_TARGET_MULTIPLE_MATCHES" in error for error in validate_generator_contract(normalized, plan)))

    def test_unsafe_stem_pattern_fails_closed_without_general_replacement(self) -> None:
        plan, generator = self._line_target_generator("REFERENCE")
        question = next(item for item in generator["questions"] if item["question_type"] == "REFERENCE")
        canonical_line = question["target_line"]
        question["target_text"] = "the communities"
        question["target_line"] = canonical_line
        question["stem"] = "The token 'the communities' appears near line 999"

        normalized, provenance = normalize_target_line_metadata(generator)
        self.assertEqual(normalized["questions"][generator["questions"].index(question)]["stem"], question["stem"])
        self.assertTrue(provenance["questions"])
        self.assertTrue(validate_generator_contract(normalized, plan))

    def test_non_target_question_fields_are_unchanged(self) -> None:
        plan = quota_plan(9210, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 1, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2})
        generator = variable_generator_fixture(plan)
        detail = next(item for item in generator["questions"] if item["question_type"] == "DETAIL")
        detail["target_text"] = "filaments"
        detail["target_line"] = 999
        before = copy.deepcopy(detail)
        normalized, provenance = normalize_target_line_metadata(generator)
        after = next(item for item in normalized["questions"] if item["item_id"] == detail["item_id"])
        self.assertEqual(after, before)
        self.assertEqual(provenance["questions"], [])

    def test_pipeline_persists_normalization_and_sends_corrected_stem_to_both_blind_stages(self) -> None:
        plan = build_plan_v02(9211, domain="biology")
        raw = variable_generator_fixture(plan)
        question = next(item for item in raw["questions"] if item["question_type"] == "VOCABULARY_IN_CONTEXT")
        canonical_line = target_line_for_text(raw["passage"], "filaments")
        assert canonical_line is not None
        generator_line = canonical_line - 1
        question["target_text"] = "Filaments"
        question["target_line"] = generator_line
        question["stem"] = f"The word 'filaments' in line {generator_line} is closest in meaning to"
        details = {
            "canonical_line": canonical_line,
            "generator_line": generator_line,
        }
        expected_permuted, _permutation = permute_generator_choices(raw, plan)
        expected_canonical = canonicalize_generator_output(expected_permuted, plan)
        expected, _expected_normalization = normalize_target_line_metadata(expected_canonical)

        class OfflineNormalizationRuntime:
            provider = "offline-test"
            cli_version = "offline-target-line-normalization"

            def __init__(self) -> None:
                self.requests: list[Any] = []

            def invoke(self, request: Any) -> InvocationResult:
                self.requests.append(request)
                if request.stage == "reading_generator":
                    parsed = raw
                elif request.stage == "reading_inference_verifier":
                    parsed = inference_verifier_for(expected)
                elif request.stage == "reading_reviewer":
                    parsed = reviewer_for(expected)
                elif request.stage == "reading_solver":
                    parsed = solver_for(expected)
                else:
                    raise AssertionError(f"unexpected stage: {request.stage}")
                return InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=f"offline-normalization-{len(self.requests)}",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:01+00:00",
                    provider=self.provider,
                    model="offline",
                    cli_version=self.cli_version,
                    exit_code=0,
                    parsed=copy.deepcopy(parsed),
                    input_keys=list(request.input_keys),
                )

        runtime = OfflineNormalizationRuntime()
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(runtime).run(
                plan["seed"], domain=plan["domain"], output_dir=Path(directory)
            )
            self.assertEqual(result["decision"], "ACCEPT")
            self.assertEqual(result["generator"], expected)
            provenance = json.loads((Path(directory) / "provenance" / "provenance.json").read_text(encoding="utf-8"))
            records = provenance["target_line_normalization"]["questions"]
            target_record = next(record for record in records if record["canonical_target_line"] == details["canonical_line"])
            self.assertEqual(target_record["generator_target_line"], details["generator_line"])
            self.assertTrue(target_record["stem_line_normalized"])

        self.assertEqual(len(runtime.requests), 4)
        for request in runtime.requests[2:]:
            payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
            visible_question = next(
                item for item in payload["questions"]
                if item["stem"] == next(
                    question["stem"] for question in expected["questions"]
                    if question["question_type"] == "VOCABULARY_IN_CONTEXT"
                )
            )
            self.assertIn(f"line {details['canonical_line']}", visible_question["stem"])
            self.assertNotIn("target_line", visible_question)

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
