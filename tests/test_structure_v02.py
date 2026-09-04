"""Offline schema and freeze tests for the Structure v0.2 foundation scaffolding.

This commit adds only namespace scaffolding and schemas under structure/v02/.
No v0.2 orchestration, prompts, or behavioral code exist yet, so these tests
only exercise schema loading/validation and protect the frozen v0.1 files.
"""

from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path
from typing import Any

from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parents[1]
V02_SCHEMAS = ROOT / "structure" / "v02" / "schemas"

GENERATOR_OUTPUT_SCHEMA = V02_SCHEMAS / "generator_output.schema.json"
REVIEWER_INPUT_SCHEMA = V02_SCHEMAS / "reviewer_input.schema.json"
REVIEWER_OUTPUT_SCHEMA = V02_SCHEMAS / "reviewer_output.schema.json"
CANDIDATE_SELECTION_SCHEMA = V02_SCHEMAS / "candidate_selection.schema.json"
GENERATOR_FINAL_SCHEMA = V02_SCHEMAS / "generator_final.schema.json"
PLAN_SCHEMA = V02_SCHEMAS / "plan.schema.json"

# Protected v0.1 files at the approved base commit. Do not update these hashes.
BASE_COMMIT = "1240881af864f3eb26f9b9365d873a2165e61c7a"
V01_PROTECTED_HASHES: dict[str, str] = {
    "structure/planner.py": "d50e130a7c05fb79ba399c552322130aa4b5833eb6aff39144c3f6449748a7ee",
    "structure/profile.json": "66f9ad0cc2a7323ae396ab8c5f9766204327b0ecb4f5b275ec6a5b2e6295c6c5",
    "structure/pipeline.py": "bfa2775767c86d9bc0b5c7777a6edfdce449827c1f2ed161b3976a27b7634eaf",
    "structure/contracts.py": "c6fae71840a4d4a840f2c455ef97c39181ea8d7d4320b054f5d6face0eea313a",
    "structure/blinding.py": "b39dcdad846adda25d46784c5d75b75e49f5b01d44df75a011bfe2c96546b351",
    "structure/permutation.py": "1efdba8054a14540ba838e31c2b57401faf97770c6da3ea14ea9850cc8c31b42",
    "structure/prompts/generator.md": "ed5cd4f4a26ce5de97648e668df0ef44dac47521ec229d1103ad955692f99332",
    "structure/prompts/reviewer.md": "0359e7f5dc3103a05082163bfb225b049923cffc72e2e5b373c6c8c5e88e70ae",
    "structure/prompts/solver.md": "e83c1a95cf4a098f43733101a63751ac151993cfbd02e25b9f9af0e238b862f3",
    "structure/schemas/generator_item.schema.json": "229a8c39ca0daa2e79e516b0cc362eb740204fd5369252c478c79facaf857fff",
    "structure/schemas/generator_output.schema.json": "78ad5e758052928bf51f973cdc009ab103c4f535e243e6bd17b0631fb361b2dd",
    "structure/schemas/plan.schema.json": "ecfe3f6714e72fd6ac7282c8adb6356eb0678e77bcc039290e728b3908840807",
    "structure/schemas/provenance.schema.json": "2979c3520cb79c5bdc96933f812f751be2c62db47cd2fea6c7294b30159904f2",
    "structure/schemas/result.schema.json": "9f049f94ec8a819bf228bd59845eb64deddd6f974f523a64abccbaae69bfb5c5",
    "structure/schemas/reviewer_input.schema.json": "8e5181664253967064a4c415377f5bc9f75a55e69984e54c01148d413d9e8b19",
    "structure/schemas/reviewer_output.schema.json": "9f47df07f99acfc34a6da22c6bdaa0f383246d2c090c2841598a7e8de0aa599e",
    "structure/schemas/solver_input.schema.json": "2a511be9e2192f45b8928c3612eb5083af29abc2b05ab31aa4d231d7f4b958e8",
    "structure/schemas/solver_output.schema.json": "90588686793f16f5ff2aefd6c19a834eb444e1bda9a0c1aff73de74e3506d031",
    "tests/test_structure_v01.py": "399ac40b912db8c8f1f28efa9e7d5a5fd5bdbffb1294a9aaf920869347c21e1b",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _generator_item(index: int) -> dict[str, Any]:
    return {
        "item_id": f"structure-v02-fixture-{index:02d}",
        "section": "Structure",
        "primary_target": "VERB_FORM_VOICE",
        "subtype": f"generator-authored construction {index}",
        "secondary_features": ["academic register"],
        "difficulty": "MEDIUM",
        "vocabulary_domain": f"generator-owned domain {index}",
        "stem": "The researcher ____ the documented pattern before the review concluded.",
        "correct_option": {"text": "confirmed"},
        "answer_explanation": "The finite past-tense verb is required in this main clause.",
        "distractor_candidates": {
            "d1": {"text": "confirming", "rationale": "A participle cannot stand as the finite main verb."},
            "d2": {"text": "confirm", "rationale": "The base form does not carry the required tense."},
            "d3": {"text": "confirms", "rationale": "The present tense does not match the past-tense context."},
            "d4": {"text": "to confirm", "rationale": "The infinitive cannot stand as the finite main verb."},
            "d5": {"text": "having confirmed", "rationale": "The perfect participle cannot stand as the finite main verb."},
            "d6": {"text": "be confirmed", "rationale": "The passive base form cannot stand as the finite main verb here."},
        },
    }


def generator_output_fixture() -> dict[str, Any]:
    return {"items": [_generator_item(index) for index in range(1, 16)]}


def _reviewer_input_item(index: int) -> dict[str, Any]:
    return {
        "item_id": f"structure-v02-fixture-{index:02d}",
        "section": "Structure",
        "stem": "The researcher ____ the documented pattern before the review concluded.",
        "candidate_options": [
            "confirmed", "confirming", "confirm", "confirms", "to confirm", "having confirmed", "be confirmed",
        ],
    }


def reviewer_input_fixture() -> dict[str, Any]:
    return {"items": [_reviewer_input_item(index) for index in range(1, 16)]}


def _reviewer_output_item(index: int) -> dict[str, Any]:
    options = [
        "confirmed", "confirming", "confirm", "confirms", "to confirm", "having confirmed", "be confirmed",
    ]
    return {
        "item_id": f"structure-v02-fixture-{index:02d}",
        "option_judgments": [
            {"option_text": option, "judgment": "VALID" if option == "confirmed" else "INVALID"}
            for option in options
        ],
        "candidate_diagnostics": [
            {
                "option_text": "confirmed",
                "natural_wording": True,
                "serious_defect": False,
                "observed_clause_count": 2,
                "candidate_pool_observed_difficulty": "MEDIUM",
                "difficulty_confidence": "HIGH",
            }
        ],
        "comment": "Only the finite past-tense form completes the main clause naturally.",
    }


def reviewer_output_fixture() -> dict[str, Any]:
    return {"items": [_reviewer_output_item(index) for index in range(1, 16)]}


def _candidate_selection_item(index: int) -> dict[str, Any]:
    item_id = f"structure-v02-fixture-{index:02d}"
    return {
        "item_id": item_id,
        "intended_correct_text": "confirmed",
        "intended_correct_judgment": "VALID",
        "intended_correct_natural_wording": True,
        "intended_correct_serious_defect": False,
        "eligible_invalid_candidate_ids": ["d2", "d3", "d4", "d5", "d6"],
        "rejected_valid_candidate_ids": [],
        "rejected_marginal_candidate_ids": [],
        "deterministic_priority_order": ["d2", "d3", "d4", "d5", "d6"],
        "selected_candidate_ids": ["d2", "d3", "d4"],
        "selected_candidate_texts": ["confirming", "confirm", "confirms"],
        "passed": True,
        "failure_reasons": [],
    }


def candidate_selection_fixture() -> dict[str, Any]:
    return {
        "schema_version": "structure-candidate-selection-v0.2",
        "version": "v0.2",
        "seed": 1,
        "items": [_candidate_selection_item(index) for index in range(1, 16)],
    }


def _generator_final_item(index: int) -> dict[str, Any]:
    return {
        "item_id": f"structure-v02-fixture-{index:02d}",
        "section": "Structure",
        "primary_target": "VERB_FORM_VOICE",
        "subtype": f"generator-authored construction {index}",
        "secondary_features": ["academic register"],
        "difficulty": "MEDIUM",
        "vocabulary_domain": f"generator-owned domain {index}",
        "stem": "The researcher ____ the documented pattern before the review concluded.",
        "options": {"A": "confirmed", "B": "confirming", "C": "confirm", "D": "confirms"},
        "correct_answer": "A",
        "answer_explanation": "The finite past-tense verb is required in this main clause.",
        "distractor_rationales": {
            "A": "Correct finite past-tense completion.",
            "B": "A participle cannot stand as the finite main verb.",
            "C": "The base form does not carry the required tense.",
            "D": "The present tense does not match the past-tense context.",
        },
    }


def generator_final_fixture() -> dict[str, Any]:
    return {"items": [_generator_final_item(index) for index in range(1, 16)]}


def _plan_item(order: int) -> dict[str, Any]:
    return {
        "item_id": f"structure-v02-fixture-{order:02d}",
        "order": order,
        "section": "Structure",
        "primary_target": "VERB_FORM_VOICE",
        "difficulty": "MEDIUM",
        "clause_count": 2,
        "sentence_length_bin": {"label": "medium", "minimum": 14, "maximum": 20, "weight": 1},
        "target_word_count": 16,
    }


def plan_fixture() -> dict[str, Any]:
    return {
        "schema_version": "structure-plan-v0.2",
        "plan_id": "structure-v02-fixture-plan",
        "version": "v0.2",
        "seed": 1,
        "question_count": 15,
        "items": [_plan_item(order) for order in range(1, 16)],
    }


class SchemaLoadTests(unittest.TestCase):
    def test_all_v02_schemas_load(self) -> None:
        for path in (
            GENERATOR_OUTPUT_SCHEMA,
            REVIEWER_INPUT_SCHEMA,
            REVIEWER_OUTPUT_SCHEMA,
            CANDIDATE_SELECTION_SCHEMA,
            GENERATOR_FINAL_SCHEMA,
            PLAN_SCHEMA,
        ):
            with self.subTest(path=path):
                load_schema(path)


class GeneratorOutputSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(generator_output_fixture(), load_schema(GENERATOR_OUTPUT_SCHEMA)))

    def test_rejects_missing_candidate(self) -> None:
        payload = generator_output_fixture()
        del payload["items"][0]["distractor_candidates"]["d6"]
        self.assertTrue(schema_errors(payload, load_schema(GENERATOR_OUTPUT_SCHEMA)))

    def test_rejects_extra_candidate(self) -> None:
        payload = generator_output_fixture()
        payload["items"][0]["distractor_candidates"]["d7"] = {"text": "x", "rationale": "y"}
        self.assertTrue(schema_errors(payload, load_schema(GENERATOR_OUTPUT_SCHEMA)))

    def test_rejects_four_option_letter_fields(self) -> None:
        payload = generator_output_fixture()
        payload["items"][0]["options"] = {"A": "confirmed", "B": "confirming", "C": "confirm", "D": "confirms"}
        payload["items"][0]["correct_answer"] = "A"
        self.assertTrue(schema_errors(payload, load_schema(GENERATOR_OUTPUT_SCHEMA)))

    def test_rejects_wrong_item_count(self) -> None:
        payload = generator_output_fixture()
        payload["items"] = payload["items"][:14]
        self.assertTrue(schema_errors(payload, load_schema(GENERATOR_OUTPUT_SCHEMA)))


class ReviewerInputSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(reviewer_input_fixture(), load_schema(REVIEWER_INPUT_SCHEMA)))

    def test_rejects_wrong_candidate_option_count(self) -> None:
        payload = reviewer_input_fixture()
        payload["items"][0]["candidate_options"] = payload["items"][0]["candidate_options"][:6]
        self.assertTrue(schema_errors(payload, load_schema(REVIEWER_INPUT_SCHEMA)))

    def test_rejects_internal_candidate_ids(self) -> None:
        payload = reviewer_input_fixture()
        payload["items"][0]["distractor_candidates"] = {"d1": {"text": "x"}}
        self.assertTrue(schema_errors(payload, load_schema(REVIEWER_INPUT_SCHEMA)))


class ReviewerOutputSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(reviewer_output_fixture(), load_schema(REVIEWER_OUTPUT_SCHEMA)))

    def test_no_best_answer_text_or_reference_candidate_text(self) -> None:
        schema_text = REVIEWER_OUTPUT_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("best_answer_text", schema_text)
        self.assertNotIn("reference_candidate_text", schema_text)
        self.assertNotIn("AMBIGUOUS", schema_text)
        self.assertNotIn("NONE", schema_text)

    def test_rejects_wrong_option_judgment_count(self) -> None:
        payload = reviewer_output_fixture()
        payload["items"][0]["option_judgments"] = payload["items"][0]["option_judgments"][:6]
        self.assertTrue(schema_errors(payload, load_schema(REVIEWER_OUTPUT_SCHEMA)))

    def test_rejects_invalid_judgment_enum(self) -> None:
        payload = reviewer_output_fixture()
        payload["items"][0]["option_judgments"][0]["judgment"] = "PASS"
        self.assertTrue(schema_errors(payload, load_schema(REVIEWER_OUTPUT_SCHEMA)))

    def test_rejects_invalid_diagnostic_difficulty_enum(self) -> None:
        payload = reviewer_output_fixture()
        payload["items"][0]["candidate_diagnostics"][0]["candidate_pool_observed_difficulty"] = "IMPOSSIBLE"
        self.assertTrue(schema_errors(payload, load_schema(REVIEWER_OUTPUT_SCHEMA)))

    def test_rejects_invalid_diagnostic_confidence_enum(self) -> None:
        payload = reviewer_output_fixture()
        payload["items"][0]["candidate_diagnostics"][0]["difficulty_confidence"] = "CERTAIN"
        self.assertTrue(schema_errors(payload, load_schema(REVIEWER_OUTPUT_SCHEMA)))

    def test_allows_zero_diagnostics(self) -> None:
        payload = reviewer_output_fixture()
        payload["items"][0]["candidate_diagnostics"] = []
        self.assertEqual([], schema_errors(payload, load_schema(REVIEWER_OUTPUT_SCHEMA)))

    def test_rejects_eight_diagnostics(self) -> None:
        payload = reviewer_output_fixture()
        diagnostic = payload["items"][0]["candidate_diagnostics"][0]
        payload["items"][0]["candidate_diagnostics"] = [copy.deepcopy(diagnostic) for _ in range(8)]
        self.assertTrue(schema_errors(payload, load_schema(REVIEWER_OUTPUT_SCHEMA)))


class CandidateSelectionSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(candidate_selection_fixture(), load_schema(CANDIDATE_SELECTION_SCHEMA)))

    def test_rejects_selected_ids_over_three(self) -> None:
        payload = candidate_selection_fixture()
        payload["items"][0]["selected_candidate_ids"] = ["d2", "d3", "d4", "d5"]
        self.assertTrue(schema_errors(payload, load_schema(CANDIDATE_SELECTION_SCHEMA)))

    def test_rejects_selected_texts_over_three(self) -> None:
        payload = candidate_selection_fixture()
        payload["items"][0]["selected_candidate_texts"] = ["a", "b", "c", "d"]
        self.assertTrue(schema_errors(payload, load_schema(CANDIDATE_SELECTION_SCHEMA)))


class GeneratorFinalSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(generator_final_fixture(), load_schema(GENERATOR_FINAL_SCHEMA)))

    def test_rejects_missing_option_letter(self) -> None:
        payload = generator_final_fixture()
        del payload["items"][0]["options"]["D"]
        self.assertTrue(schema_errors(payload, load_schema(GENERATOR_FINAL_SCHEMA)))


class PlanSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(plan_fixture(), load_schema(PLAN_SCHEMA)))

    def test_rejects_wrong_schema_version(self) -> None:
        payload = plan_fixture()
        payload["schema_version"] = "structure-plan-v0.1"
        self.assertTrue(schema_errors(payload, load_schema(PLAN_SCHEMA)))

    def test_rejects_wrong_version(self) -> None:
        payload = plan_fixture()
        payload["version"] = "v0.1"
        self.assertTrue(schema_errors(payload, load_schema(PLAN_SCHEMA)))

    def test_rejects_wrong_question_count(self) -> None:
        payload = plan_fixture()
        payload["question_count"] = 14
        self.assertTrue(schema_errors(payload, load_schema(PLAN_SCHEMA)))


class V01FreezeTests(unittest.TestCase):
    """Protect the approved v0.1 boundaries at base commit {}.""".format(BASE_COMMIT)

    def test_v01_protected_files_unchanged(self) -> None:
        for relative_path, expected_hash in V01_PROTECTED_HASHES.items():
            path = ROOT / relative_path
            with self.subTest(path=relative_path):
                self.assertTrue(path.is_file(), f"missing protected v0.1 file: {relative_path}")
                self.assertEqual(
                    _sha256(path),
                    expected_hash,
                    f"frozen v0.1 file changed: {relative_path}",
                )


if __name__ == "__main__":
    unittest.main()
