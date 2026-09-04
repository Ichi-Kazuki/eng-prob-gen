"""Offline schema and freeze tests for the Structure v0.2 foundation scaffolding.

This commit adds only namespace scaffolding and schemas under structure/v02/.
No v0.2 orchestration, prompts, or behavioral code exist yet, so these tests
only exercise schema loading/validation and protect the frozen v0.1 files.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from structure.permutation import permute_generator_output

import structure.planner as v01_planner
from structure import blinding as v01_blinding
from structure import contracts as v01_contracts
from shared.json_io import canonical_json_sha256
from shared.schema_validation import load_schema, schema_errors
from runtime.adapters import InvocationRequest, InvocationResult, RuntimeInvocationError
from structure.v02 import blinding as v02_blinding
from structure.v02 import contracts as v02_contracts
from structure.v02 import pipeline as v02_pipeline
from structure.v02 import planner as v02_planner
from structure.v02 import selection as v02_selection
from structure.v02 import solver as v02_solver


ROOT = Path(__file__).resolve().parents[1]
V02_SCHEMAS = ROOT / "structure" / "v02" / "schemas"

GENERATOR_OUTPUT_SCHEMA = V02_SCHEMAS / "generator_output.schema.json"
REVIEWER_INPUT_SCHEMA = V02_SCHEMAS / "reviewer_input.schema.json"
REVIEWER_OUTPUT_SCHEMA = V02_SCHEMAS / "reviewer_output.schema.json"
CANDIDATE_SELECTION_SCHEMA = V02_SCHEMAS / "candidate_selection.schema.json"
GENERATOR_FINAL_SCHEMA = V02_SCHEMAS / "generator_final.schema.json"
PLAN_SCHEMA = V02_SCHEMAS / "plan.schema.json"
RESULT_SCHEMA = V02_SCHEMAS / "result.schema.json"
PROVENANCE_SCHEMA = V02_SCHEMAS / "provenance.schema.json"

# Protected v0.1 files at the approved base commit. Do not update these hashes.
BASE_COMMIT = "1240881af864f3eb26f9b9365d873a2165e61c7a"
V01_PROTECTED_HASHES: dict[str, str] = {
    "structure/planner.py": "d50e130a7c05fb79ba399c552322130aa4b5833eb6aff39144c3f6449748a7ee",
    "structure/profile.json": "66f9ad0cc2a7323ae396ab8c5f9766204327b0ecb4f5b275ec6a5b2e6295c6c5",
    "structure/pipeline.py": "bfa2775767c86d9bc0b5c7777a6edfdce449827c1f2ed161b3976a27b7634eaf",
    "structure/contracts.py": "c6fae71840a4d4a840f2c455ef97c39181ea8d7d4320b054f5d6face0eea313a",
    "structure/blinding.py": "b39dcdad846adda25d46784c5d75b75e49f5b01d44df75a011bfe2c96546b351",
    "structure/permutation.py": "1efdba8054a14540ba838e31c2b57401faf97770c6da3ea14ea9850cc8c31b42",
    "structure/prompts/generator.md": "dc723c8ca5054fbc7baffddb0dcadded24c11bcfefb1ea1e9b662fc8d991838f",
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
    "tests/test_structure_v01.py": "f98faf0d216ca62e8a96667b4f1714618876cc4c7443bea47ef8b078dd238b40",
}

# Protected v0.2 schemas at the approved base commit. Do not update these
# hashes unless a future explicitly approved schema migration occurs.
V02_BASE_COMMIT = "b7a1716b8233ffb794655fa28a71e3ed3292d0ad"
V02_PROTECTED_SCHEMA_HASHES: dict[str, str] = {
    "structure/v02/schemas/generator_output.schema.json": "87202d4ba025377aa06dedad14c4f3a00b9ec5d5e1a32240556ce1b0597b89ae",
    "structure/v02/schemas/reviewer_input.schema.json": "22e1865cec69ddf10472a5bcc0d2ae0ca29dc974481743d5995872e8b9c4471c",
    "structure/v02/schemas/reviewer_output.schema.json": "0d75f38b5d24a201f3efaac27c6bcedaa61f04b35e194a734460356e24824315",
    "structure/v02/schemas/candidate_selection.schema.json": "f8ca2ab1e5dd60c7db37f4d49bff4cfe50c370a79f2e8043d6a7b326e109038d",
    "structure/v02/schemas/generator_final.schema.json": "3c34b631f881fd1966730f6b5d2b93fad730885d5ca93ca1f808b3244efad385",
    "structure/v02/schemas/plan.schema.json": "39e8dcded26947556123a00218bddb6a605063bdc9be97cb9e36caf22245738b",
    "structure/v02/schemas/result.schema.json": "7c4efd2ced496099dcc8396c915e6e8a77fafd01f3c031c9729f4e2176f450b1",
    "structure/v02/schemas/provenance.schema.json": "94ef72769c528aa1e911c3ab690cbdc35e8b43e5e2337d3e5c26d407d0fed86f",
}

# Protected v0.2 authoring prompts. Do not update these hashes unless a
# future explicitly approved prompt revision occurs.
V02_PROTECTED_PROMPT_HASHES: dict[str, str] = {
    "structure/v02/prompts/generator.md": "da539121f3ea8cae9711484fe63b8930bf1f42cfa80b4ca6bd2fc82ac6389ea5",
    "structure/v02/prompts/reviewer.md": "0e42b778a5c4f7ae009375acbd28106755fb755bf83ac62d663a6233d003fbb5",
    "structure/v02/prompts/solver.md": "40d9588db09d8d1478b520ed44472d7914129b17bc2f2481d8329c370779aeb1",
}


def _canonical_text_sha256(text: str) -> str:
    """Hash text content after normalizing CRLF/CR line endings to LF.

    This protects the canonical committed text content rather than
    checkout-specific bytes (e.g. Windows CRLF checkouts of LF blobs).
    No whitespace stripping, newline trimming, or Unicode normalization
    is performed beyond the CRLF/CR -> LF substitution.
    """
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return _canonical_text_sha256(path.read_text(encoding="utf-8"))


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
    # The fixture's completed correct sentence ("The researcher confirmed the
    # documented pattern before the review concluded.") is exactly 10 words,
    # so the bin must actually contain 10 for Generator semantic tests to be
    # internally coherent (see Commit 3 fixture-correction note).
    return {
        "item_id": f"structure-v02-fixture-{order:02d}",
        "order": order,
        "section": "Structure",
        "primary_target": "VERB_FORM_VOICE",
        "difficulty": "MEDIUM",
        "clause_count": 2,
        "sentence_length_bin": {"label": "short", "minimum": 10, "maximum": 14, "weight": 1},
        "target_word_count": 10,
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
            RESULT_SCHEMA,
            PROVENANCE_SCHEMA,
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

    def test_intended_correct_invalid_with_null_diagnostics_validates(self) -> None:
        payload = candidate_selection_fixture()
        payload["items"][0]["intended_correct_judgment"] = "INVALID"
        payload["items"][0]["intended_correct_natural_wording"] = None
        payload["items"][0]["intended_correct_serious_defect"] = None
        self.assertEqual([], schema_errors(payload, load_schema(CANDIDATE_SELECTION_SCHEMA)))

    def test_intended_correct_natural_wording_rejects_non_boolean_non_null(self) -> None:
        payload = candidate_selection_fixture()
        payload["items"][0]["intended_correct_natural_wording"] = "true"
        self.assertTrue(schema_errors(payload, load_schema(CANDIDATE_SELECTION_SCHEMA)))

    def test_intended_correct_serious_defect_rejects_non_boolean_non_null(self) -> None:
        payload = candidate_selection_fixture()
        payload["items"][0]["intended_correct_serious_defect"] = "false"
        self.assertTrue(schema_errors(payload, load_schema(CANDIDATE_SELECTION_SCHEMA)))

    def test_intended_correct_natural_wording_still_required(self) -> None:
        payload = candidate_selection_fixture()
        del payload["items"][0]["intended_correct_natural_wording"]
        self.assertTrue(schema_errors(payload, load_schema(CANDIDATE_SELECTION_SCHEMA)))

    def test_intended_correct_serious_defect_still_required(self) -> None:
        payload = candidate_selection_fixture()
        del payload["items"][0]["intended_correct_serious_defect"]
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


class CanonicalTextHashTests(unittest.TestCase):
    def test_lf_and_crlf_content_hash_equal(self) -> None:
        lf_text = "alpha\nbeta\n"
        crlf_text = "alpha\r\nbeta\r\n"
        self.assertEqual(_canonical_text_sha256(lf_text), _canonical_text_sha256(crlf_text))


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


class V02SchemaFreezeTests(unittest.TestCase):
    """Protect the approved v0.2 schemas at base commit {}.""".format(V02_BASE_COMMIT)

    def test_v02_protected_schemas_unchanged(self) -> None:
        for relative_path, expected_hash in V02_PROTECTED_SCHEMA_HASHES.items():
            path = ROOT / relative_path
            with self.subTest(path=relative_path):
                self.assertTrue(path.is_file(), f"missing protected v0.2 schema: {relative_path}")
                self.assertEqual(
                    _sha256(path),
                    expected_hash,
                    f"frozen v0.2 schema changed: {relative_path}",
                )


class V02PromptFreezeTests(unittest.TestCase):
    """Protect the approved v0.2 authoring prompts against accidental drift."""

    def test_v02_protected_prompts_unchanged(self) -> None:
        for relative_path, expected_hash in V02_PROTECTED_PROMPT_HASHES.items():
            path = ROOT / relative_path
            with self.subTest(path=relative_path):
                self.assertTrue(path.is_file(), f"missing protected v0.2 prompt: {relative_path}")
                self.assertEqual(
                    _sha256(path),
                    expected_hash,
                    f"frozen v0.2 prompt changed: {relative_path}",
                )


SEED = 7


def _raw_reviewer_output_fixture(reviewer_input: dict[str, Any]) -> dict[str, Any]:
    """Build a schema-valid, contract-valid raw Reviewer response for a projection."""

    correct_text = "confirmed"
    items = []
    for item in reviewer_input["items"]:
        options = item["candidate_options"]
        judgments = [
            {"option_text": text, "judgment": "VALID" if text == correct_text else "INVALID"}
            for text in options
        ]
        diagnostics = [
            {
                "option_text": correct_text,
                "natural_wording": True,
                "serious_defect": False,
                "observed_clause_count": 2,
                "candidate_pool_observed_difficulty": "MEDIUM",
                "difficulty_confidence": "HIGH",
            }
        ]
        items.append({
            "item_id": item["item_id"],
            "option_judgments": judgments,
            "candidate_diagnostics": diagnostics,
            "comment": "Only the finite past-tense form completes the main clause naturally.",
        })
    return {"items": items}


class CandidateIdentityTests(unittest.TestCase):
    def test_internal_candidate_ids_are_exact(self) -> None:
        self.assertEqual(v02_blinding.CANDIDATE_IDS, ("correct", "d1", "d2", "d3", "d4", "d5", "d6"))

    def test_extract_candidate_entries_private_correct_identity(self) -> None:
        item = generator_output_fixture()["items"][0]
        entries = v02_blinding.extract_candidate_entries(item)
        self.assertEqual([candidate_id for candidate_id, _ in entries], list(v02_blinding.CANDIDATE_IDS))
        self.assertEqual(entries[0], ("correct", "confirmed"))


class ReviewerCandidateProjectionTests(unittest.TestCase):
    def test_projection_contains_exactly_expected_keys(self) -> None:
        payload = v02_blinding.build_reviewer_candidate_input(generator_output_fixture(), SEED)
        for item in payload["items"]:
            self.assertEqual(set(item), {"item_id", "section", "stem", "candidate_options"})

    def test_reviewer_sees_exactly_seven_strings(self) -> None:
        payload = v02_blinding.build_reviewer_candidate_input(generator_output_fixture(), SEED)
        for item in payload["items"]:
            self.assertEqual(7, len(item["candidate_options"]))
            self.assertTrue(all(isinstance(text, str) for text in item["candidate_options"]))

    def test_no_candidate_ids_leak(self) -> None:
        payload = v02_blinding.build_reviewer_candidate_input(generator_output_fixture(), SEED)
        serialized = json.dumps(payload)
        for candidate_id in v02_blinding.CANDIDATE_IDS:
            self.assertNotIn(f'"{candidate_id}"', serialized)

    def test_no_private_generator_metadata_leaks(self) -> None:
        payload = v02_blinding.build_reviewer_candidate_input(generator_output_fixture(), SEED)
        serialized = json.dumps(payload)
        for forbidden in (
            "correct_option", "distractor_candidates", "primary_target", "subtype",
            "difficulty", "vocabulary_domain", "answer_explanation", "rationale",
            "secondary_features", "clause_count", "sentence_length_bin", "target_word_count",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_same_seed_produces_identical_projection(self) -> None:
        generator = generator_output_fixture()
        first = v02_blinding.build_reviewer_candidate_input(generator, SEED)
        second = v02_blinding.build_reviewer_candidate_input(generator, SEED)
        self.assertEqual(first, second)

    def test_preserves_generator_item_order(self) -> None:
        generator = generator_output_fixture()
        payload = v02_blinding.build_reviewer_candidate_input(generator, SEED)
        self.assertEqual(
            [item["item_id"] for item in payload["items"]],
            [item["item_id"] for item in generator["items"]],
        )

    def test_validates_against_reviewer_input_schema(self) -> None:
        payload = v02_blinding.build_reviewer_candidate_input(generator_output_fixture(), SEED)
        self.assertEqual([], schema_errors(payload, load_schema(REVIEWER_INPUT_SCHEMA)))

    def test_exact_duplicate_candidate_texts_fail_closed(self) -> None:
        generator = generator_output_fixture()
        generator["items"][0]["distractor_candidates"]["d2"]["text"] = (
            generator["items"][0]["correct_option"]["text"]
        )
        with self.assertRaises(ValueError):
            v02_blinding.build_reviewer_candidate_input(generator, SEED)


class SeedValidationTests(unittest.TestCase):
    def test_negative_seed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            v02_blinding.build_reviewer_candidate_input(generator_output_fixture(), -1)

    def test_bool_seed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            v02_blinding.build_reviewer_candidate_input(generator_output_fixture(), True)

    def test_validate_seed_accepts_zero(self) -> None:
        self.assertEqual(0, v02_blinding.validate_seed(0))


class PriorityDeterminismTests(unittest.TestCase):
    def test_same_seed_item_candidate_gives_same_priority(self) -> None:
        first = v02_blinding.reviewer_order_priority(SEED, "item-1", "d3")
        second = v02_blinding.reviewer_order_priority(SEED, "item-1", "d3")
        self.assertEqual(first, second)

    def test_priority_is_sha256_hex(self) -> None:
        digest = v02_blinding.reviewer_order_priority(SEED, "item-1", "d3")
        self.assertEqual(64, len(digest))
        int(digest, 16)

    def test_reviewer_order_and_selection_domains_differ(self) -> None:
        reviewer_digest = v02_blinding.reviewer_order_priority(SEED, "item-1", "d3")
        selection_digest = v02_blinding.selection_priority(SEED, "item-1", "d3")
        self.assertNotEqual(reviewer_digest, selection_digest)

    def test_ordering_independent_of_dict_iteration(self) -> None:
        generator_a = generator_output_fixture()
        generator_b = generator_output_fixture()
        generator_b["items"][0]["distractor_candidates"] = dict(
            reversed(list(generator_b["items"][0]["distractor_candidates"].items()))
        )
        payload_a = v02_blinding.build_reviewer_candidate_input(generator_a, SEED)
        payload_b = v02_blinding.build_reviewer_candidate_input(generator_b, SEED)
        self.assertEqual(payload_a, payload_b)

    def test_different_seeds_can_produce_different_order(self) -> None:
        generator = generator_output_fixture()
        orders = {
            seed: tuple(
                v02_blinding.build_reviewer_candidate_input(generator, seed)["items"][0]["candidate_options"]
            )
            for seed in range(6)
        }
        self.assertGreater(len(set(orders.values())), 1)


class ReviewerCandidateProjectionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = generator_output_fixture()
        self.seed = SEED
        self.payload = v02_blinding.build_reviewer_candidate_input(self.generator, self.seed)

    def test_valid_payload_has_no_errors(self) -> None:
        self.assertEqual(
            [], v02_blinding.reviewer_candidate_input_errors(self.generator, self.payload, self.seed)
        )

    def test_modified_order_fails(self) -> None:
        payload = copy.deepcopy(self.payload)
        options = payload["items"][0]["candidate_options"]
        options[0], options[1] = options[1], options[0]
        self.assertTrue(v02_blinding.reviewer_candidate_input_errors(self.generator, payload, self.seed))

    def test_modified_text_fails(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["candidate_options"][0] = "modified text"
        self.assertTrue(v02_blinding.reviewer_candidate_input_errors(self.generator, payload, self.seed))

    def test_added_private_field_fails(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["correct_option"] = {"text": "leak"}
        self.assertTrue(v02_blinding.reviewer_candidate_input_errors(self.generator, payload, self.seed))


class ReviewerOutputContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = generator_output_fixture()
        self.seed = SEED
        self.reviewer_input = v02_blinding.build_reviewer_candidate_input(self.generator, self.seed)
        self.raw_reviewer = _raw_reviewer_output_fixture(self.reviewer_input)

    def test_valid_reviewer_output_passes(self) -> None:
        self.assertEqual(
            [], v02_contracts.validate_reviewer_contract(self.raw_reviewer, self.reviewer_input)
        )

    def test_schema_invalid_output_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["option_judgments"][0]["judgment"] = "MAYBE"
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_item_id_mismatch_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["item_id"] = "wrong-id"
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_item_order_mismatch_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0], raw["items"][1] = raw["items"][1], raw["items"][0]
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_option_judgments_missing_one_visible_text_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["option_judgments"][1]["option_text"] = raw["items"][0]["option_judgments"][0]["option_text"]
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_option_judgments_duplicates_one_visible_text_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["option_judgments"][2]["option_text"] = raw["items"][0]["option_judgments"][0]["option_text"]
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_option_judgments_invents_or_changes_text_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["option_judgments"][0]["option_text"] = "an entirely invented option"
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_exact_case_difference_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        original = raw["items"][0]["option_judgments"][0]["option_text"]
        raw["items"][0]["option_judgments"][0]["option_text"] = original.upper()
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_exact_whitespace_difference_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        original = raw["items"][0]["option_judgments"][0]["option_text"]
        raw["items"][0]["option_judgments"][0]["option_text"] = original + " "
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_exact_punctuation_difference_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        original = raw["items"][0]["option_judgments"][0]["option_text"]
        raw["items"][0]["option_judgments"][0]["option_text"] = original + "."
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_valid_candidate_missing_diagnostic_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["candidate_diagnostics"] = []
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_marginal_candidate_missing_diagnostic_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        target_entry = next(
            entry for entry in raw["items"][0]["option_judgments"] if entry["option_text"] != "confirmed"
        )
        target_entry["judgment"] = "MARGINAL"
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_invalid_candidate_with_diagnostic_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        invalid_text = next(
            entry["option_text"] for entry in raw["items"][0]["option_judgments"] if entry["judgment"] == "INVALID"
        )
        raw["items"][0]["candidate_diagnostics"].append({
            "option_text": invalid_text,
            "natural_wording": False,
            "serious_defect": True,
            "observed_clause_count": 2,
            "candidate_pool_observed_difficulty": "MEDIUM",
            "difficulty_confidence": "HIGH",
        })
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_duplicate_diagnostic_text_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["candidate_diagnostics"].append(copy.deepcopy(raw["items"][0]["candidate_diagnostics"][0]))
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_invented_diagnostic_text_fails(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["candidate_diagnostics"][0]["option_text"] = "an entirely invented option"
        self.assertTrue(v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_all_valid_marginal_diagnostics_exactly_present_passes(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        options = self.reviewer_input["items"][0]["candidate_options"]
        second_text = next(text for text in options if text != "confirmed")
        raw["items"][0]["option_judgments"] = [
            {"option_text": text, "judgment": "MARGINAL" if text == second_text else entry["judgment"]}
            for text, entry in zip(options, raw["items"][0]["option_judgments"])
        ]
        raw["items"][0]["candidate_diagnostics"].append({
            "option_text": second_text,
            "natural_wording": False,
            "serious_defect": False,
            "observed_clause_count": 2,
            "candidate_pool_observed_difficulty": "MEDIUM",
            "difficulty_confidence": "MEDIUM",
        })
        self.assertEqual([], v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_multiple_valid_candidates_are_allowed(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        options = self.reviewer_input["items"][0]["candidate_options"]
        second_text = next(text for text in options if text != "confirmed")
        for entry in raw["items"][0]["option_judgments"]:
            if entry["option_text"] == second_text:
                entry["judgment"] = "VALID"
        raw["items"][0]["candidate_diagnostics"].append({
            "option_text": second_text,
            "natural_wording": True,
            "serious_defect": False,
            "observed_clause_count": 2,
            "candidate_pool_observed_difficulty": "MEDIUM",
            "difficulty_confidence": "HIGH",
        })
        self.assertEqual([], v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_multiple_marginal_candidates_are_allowed(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        options = self.reviewer_input["items"][0]["candidate_options"]
        marginal_texts = [text for text in options if text != "confirmed"][:2]
        for entry in raw["items"][0]["option_judgments"]:
            if entry["option_text"] in marginal_texts:
                entry["judgment"] = "MARGINAL"
        for text in marginal_texts:
            raw["items"][0]["candidate_diagnostics"].append({
                "option_text": text,
                "natural_wording": False,
                "serious_defect": False,
                "observed_clause_count": 2,
                "candidate_pool_observed_difficulty": "MEDIUM",
                "difficulty_confidence": "MEDIUM",
            })
        self.assertEqual([], v02_contracts.validate_reviewer_contract(raw, self.reviewer_input))

    def test_no_global_best_answer_is_introduced(self) -> None:
        schema_text = REVIEWER_OUTPUT_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("best_answer_text", schema_text)
        self.assertNotIn("reference_candidate_text", schema_text)


class ReviewerCanonicalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = generator_output_fixture()
        self.seed = SEED
        self.reviewer_input = v02_blinding.build_reviewer_candidate_input(self.generator, self.seed)
        self.raw_reviewer = _raw_reviewer_output_fixture(self.reviewer_input)
        self.canonical = v02_contracts.canonicalize_reviewer_output(self.raw_reviewer, self.reviewer_input)

    def test_canonicalization_rejects_malformed_input(self) -> None:
        raw = copy.deepcopy(self.raw_reviewer)
        raw["items"][0]["item_id"] = "wrong-id"
        with self.assertRaises(ValueError):
            v02_contracts.canonicalize_reviewer_output(raw, self.reviewer_input)

    def test_canonical_judgments_keyed_by_exact_visible_text(self) -> None:
        canonical_item = self.canonical["items"][0]
        options = self.reviewer_input["items"][0]["candidate_options"]
        self.assertEqual(set(canonical_item["option_judgments"]), set(options))
        self.assertEqual(canonical_item["option_judgments"]["confirmed"], "VALID")

    def test_canonical_diagnostics_keyed_by_exact_visible_text(self) -> None:
        canonical_item = self.canonical["items"][0]
        self.assertEqual(set(canonical_item["candidate_diagnostics"]), {"confirmed"})
        self.assertEqual(
            canonical_item["candidate_diagnostics"]["confirmed"]["candidate_pool_observed_difficulty"], "MEDIUM"
        )

    def test_canonicalization_does_not_expose_a_d_letters(self) -> None:
        canonical_item = self.canonical["items"][0]
        self.assertEqual(set(), set(canonical_item["option_judgments"]) & {"A", "B", "C", "D"})

    def test_canonicalization_does_not_expose_private_candidate_ids(self) -> None:
        canonical_item = self.canonical["items"][0]
        self.assertEqual(set(), set(canonical_item["option_judgments"]) & set(v02_blinding.CANDIDATE_IDS))
        self.assertEqual(set(), set(canonical_item["candidate_diagnostics"]) & set(v02_blinding.CANDIDATE_IDS))

    def test_observed_difficulty_does_not_trigger_planned_comparison(self) -> None:
        diagnostic = self.canonical["items"][0]["candidate_diagnostics"]["confirmed"]
        self.assertEqual(set(diagnostic), {
            "natural_wording", "serious_defect", "observed_clause_count",
            "candidate_pool_observed_difficulty", "difficulty_confidence",
        })

    def test_observed_clause_count_does_not_trigger_planner_comparison(self) -> None:
        diagnostic = self.canonical["items"][0]["candidate_diagnostics"]["confirmed"]
        self.assertEqual(2, diagnostic["observed_clause_count"])
        self.assertNotIn("planned_clause_count", diagnostic)
        self.assertNotIn("clause_count_match", diagnostic)


def _fullwidth_variant(text: str) -> str:
    """Return an NFKC-equivalent (but not exact-string-equal) fullwidth variant."""

    return "".join(
        chr(0xFF00 + (ord(char) - 0x20)) if 0x21 <= ord(char) <= 0x7E else char
        for char in text
    )


def _canonical_reviewer_fixture(
    generator: dict[str, Any],
    distractor_judgment_by_id: dict[str, str] | None = None,
    correct_judgment: str = "VALID",
    correct_natural_wording: bool = True,
    correct_serious_defect: bool = False,
) -> dict[str, Any]:
    """Build a canonical (text-keyed) Reviewer object directly, bypassing the raw contract.

    Distractors default to INVALID unless overridden by `distractor_judgment_by_id`.
    """

    distractor_judgment_by_id = distractor_judgment_by_id or {}
    items: list[dict[str, Any]] = []
    for item in generator["items"]:
        entries = v02_blinding.extract_candidate_entries(item)
        text_by_id = dict(entries)
        correct_text = text_by_id["correct"]

        option_judgments: dict[str, str] = {correct_text: correct_judgment}
        candidate_diagnostics: dict[str, dict[str, Any]] = {}
        if correct_judgment in ("VALID", "MARGINAL"):
            candidate_diagnostics[correct_text] = {
                "natural_wording": correct_natural_wording,
                "serious_defect": correct_serious_defect,
                "observed_clause_count": 2,
                "candidate_pool_observed_difficulty": "MEDIUM",
                "difficulty_confidence": "HIGH",
            }

        for candidate_id in v02_blinding.DISTRACTOR_IDS:
            judgment = distractor_judgment_by_id.get(candidate_id, "INVALID")
            text = text_by_id[candidate_id]
            option_judgments[text] = judgment
            if judgment in ("VALID", "MARGINAL"):
                candidate_diagnostics[text] = {
                    "natural_wording": judgment == "VALID",
                    "serious_defect": False,
                    "observed_clause_count": 2,
                    "candidate_pool_observed_difficulty": "MEDIUM",
                    "difficulty_confidence": "HIGH",
                }

        items.append({
            "item_id": item["item_id"],
            "option_judgments": option_judgments,
            "candidate_diagnostics": candidate_diagnostics,
            "comment": "fixture comment",
        })
    return {"items": items}


class GeneratorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = plan_fixture()
        self.generator = generator_output_fixture()

    def test_valid_generator_and_plan_passes(self) -> None:
        self.assertEqual([], v02_contracts.validate_generator_contract(self.generator, self.plan))

    def test_wrong_item_count_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"] = generator["items"][:14]
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_item_id_mismatch_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["item_id"] = "wrong-id"
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_order_mismatch_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0], generator["items"][1] = generator["items"][1], generator["items"][0]
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_primary_target_mismatch_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["primary_target"] = "NOUN_CLAUSES"
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_difficulty_mismatch_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["difficulty"] = "HARD"
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_wrong_section_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["section"] = "WrittenExpression"
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_subtype_whitespace_only_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["subtype"] = "   "
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_vocabulary_domain_whitespace_only_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["vocabulary_domain"] = "   "
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_explanation_whitespace_only_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["answer_explanation"] = "   "
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_candidate_rationale_whitespace_only_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["distractor_candidates"]["d1"]["rationale"] = "   "
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_zero_blanks_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["stem"] = "The researcher confirmed the documented pattern before the review concluded."
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_multiple_blanks_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["stem"] = "The researcher ____ the ____ pattern before the review concluded."
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_exact_duplicate_candidate_text_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["distractor_candidates"]["d1"]["text"] = generator["items"][0]["correct_option"]["text"]
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_normalized_case_duplicate_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        base = generator["items"][0]["correct_option"]["text"]
        generator["items"][0]["distractor_candidates"]["d1"]["text"] = base.upper()
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_normalized_whitespace_duplicate_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        base = generator["items"][0]["correct_option"]["text"]
        generator["items"][0]["distractor_candidates"]["d1"]["text"] = f" {base} "
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_nfkc_equivalent_duplicate_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        base = generator["items"][0]["correct_option"]["text"]
        generator["items"][0]["distractor_candidates"]["d1"]["text"] = _fullwidth_variant(base)
        self.assertTrue(v02_contracts.validate_generator_contract(generator, self.plan))

    def test_all_seven_distinct_surfaces_pass(self) -> None:
        self.assertEqual([], v02_contracts.validate_generator_contract(self.generator, self.plan))

    def test_completed_sentence_below_bin_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["stem"] = "____ done."
        generator["items"][0]["correct_option"]["text"] = "OK"
        errors = v02_contracts.validate_generator_contract(generator, self.plan)
        self.assertTrue(any("word count" in error for error in errors))

    def test_completed_sentence_above_bin_fails(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["correct_option"]["text"] = " ".join(["extremely"] * 20)
        errors = v02_contracts.validate_generator_contract(generator, self.plan)
        self.assertTrue(any("word count" in error for error in errors))

    def test_completed_sentence_inside_bin_passes(self) -> None:
        self.assertEqual([], v02_contracts.validate_generator_contract(self.generator, self.plan))

    def test_actual_need_not_equal_target_word_count(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["stem"] = (
            "The senior researcher ____ that documented pattern before the extended review finally concluded now."
        )
        self.assertEqual(
            14, len(("The senior researcher confirmed that documented pattern before the extended "
                     "review finally concluded now.").split())
        )
        self.assertEqual([], v02_contracts.validate_generator_contract(generator, self.plan))

    def test_sentence_length_uses_correct_option_only(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["distractor_candidates"]["d1"]["text"] = " ".join(["extremely"] * 20)
        self.assertEqual([], v02_contracts.validate_generator_contract(generator, self.plan))

    def test_no_deterministic_grammar_semantic_checking_introduced(self) -> None:
        generator = copy.deepcopy(self.generator)
        generator["items"][0]["correct_option"]["text"] = "confirming"
        generator["items"][0]["distractor_candidates"]["d1"]["text"] = "confirmed"
        self.assertEqual([], v02_contracts.validate_generator_contract(generator, self.plan))


class CandidateSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = generator_output_fixture()
        self.seed = SEED

    def test_intended_correct_valid_natural_true_serious_false_passes(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertTrue(item["passed"])
        self.assertEqual([], item["failure_reasons"])

    def test_intended_correct_invalid_fails_with_null_diagnostics(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, correct_judgment="INVALID")
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertFalse(item["passed"])
        self.assertIn("intended_correct_not_valid:INVALID", item["failure_reasons"])
        self.assertIsNone(item["intended_correct_natural_wording"])
        self.assertIsNone(item["intended_correct_serious_defect"])

    def test_intended_correct_marginal_fails(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, correct_judgment="MARGINAL")
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertFalse(item["passed"])
        self.assertIn("intended_correct_not_valid:MARGINAL", item["failure_reasons"])
        self.assertEqual(True, item["intended_correct_natural_wording"])
        self.assertEqual(False, item["intended_correct_serious_defect"])

    def test_intended_correct_valid_natural_false_fails(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, correct_natural_wording=False)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertFalse(item["passed"])
        self.assertIn("intended_correct_natural_wording_false", item["failure_reasons"])

    def test_intended_correct_valid_serious_true_fails(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, correct_serious_defect=True)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertFalse(item["passed"])
        self.assertIn("intended_correct_serious_defect_true", item["failure_reasons"])

    def test_distractor_valid_is_discarded(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, distractor_judgment_by_id={"d1": "VALID"})
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertIn("d1", item["rejected_valid_candidate_ids"])
        self.assertNotIn("d1", item["selected_candidate_ids"])

    def test_distractor_marginal_is_discarded(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, distractor_judgment_by_id={"d1": "MARGINAL"})
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertIn("d1", item["rejected_marginal_candidate_ids"])
        self.assertNotIn("d1", item["selected_candidate_ids"])

    def test_extra_valid_distractor_does_not_fail_item_if_three_invalid_remain(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, distractor_judgment_by_id={"d1": "VALID"})
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertTrue(item["passed"])
        self.assertEqual(3, len(item["selected_candidate_ids"]))

    def test_extra_marginal_distractor_does_not_fail_item_if_three_invalid_remain(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, distractor_judgment_by_id={"d1": "MARGINAL"})
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertTrue(item["passed"])
        self.assertEqual(3, len(item["selected_candidate_ids"]))

    def test_exactly_three_invalid_selects_all_three(self) -> None:
        reviewer = _canonical_reviewer_fixture(
            self.generator, distractor_judgment_by_id={"d1": "VALID", "d2": "VALID", "d3": "MARGINAL"}
        )
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertTrue(item["passed"])
        self.assertEqual(set(item["selected_candidate_ids"]), set(item["eligible_invalid_candidate_ids"]))
        self.assertEqual(3, len(item["selected_candidate_ids"]))

    def test_more_than_three_invalid_selects_deterministic_first_three(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertEqual(item["deterministic_priority_order"][:3], item["selected_candidate_ids"])

    def test_fewer_than_three_invalid_fails(self) -> None:
        reviewer = _canonical_reviewer_fixture(
            self.generator,
            distractor_judgment_by_id={"d1": "VALID", "d2": "VALID", "d3": "VALID", "d4": "MARGINAL"},
        )
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertFalse(item["passed"])

    def test_insufficient_count_appears_in_failure_reason(self) -> None:
        reviewer = _canonical_reviewer_fixture(
            self.generator,
            distractor_judgment_by_id={"d1": "VALID", "d2": "VALID", "d3": "VALID", "d4": "MARGINAL"},
        )
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertIn("insufficient_invalid_distractors:2", item["failure_reasons"])

    def test_deterministic_priority_contains_d1_to_d6_exactly_once(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertEqual(sorted(v02_blinding.DISTRACTOR_IDS), sorted(item["deterministic_priority_order"]))
        self.assertEqual(6, len(item["deterministic_priority_order"]))

    def test_correct_never_in_priority_or_selected_ids(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        item = selection["items"][0]
        self.assertNotIn("correct", item["deterministic_priority_order"])
        self.assertNotIn("correct", item["selected_candidate_ids"])

    def test_same_seed_gives_identical_selection(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        first = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        second = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        self.assertEqual(first, second)

    def test_selection_replay_validator_accepts_exact_artifact(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        self.assertEqual(
            [], v02_selection.candidate_selection_errors(self.generator, reviewer, selection, self.seed)
        )

    def test_tampered_selection_fails_replay_validator(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        tampered = copy.deepcopy(selection)
        ids = tampered["items"][0]["selected_candidate_ids"]
        texts = tampered["items"][0]["selected_candidate_texts"]
        tampered["items"][0]["selected_candidate_ids"] = list(reversed(ids))
        tampered["items"][0]["selected_candidate_texts"] = list(reversed(texts))
        self.assertTrue(
            v02_selection.candidate_selection_errors(self.generator, reviewer, tampered, self.seed)
        )

    def test_changed_reviewer_comment_does_not_change_selection(self) -> None:
        reviewer_a = _canonical_reviewer_fixture(self.generator)
        reviewer_b = copy.deepcopy(reviewer_a)
        reviewer_b["items"][0]["comment"] = "a completely different comment"
        first = v02_selection.build_candidate_selection(self.generator, reviewer_a, self.seed)
        second = v02_selection.build_candidate_selection(self.generator, reviewer_b, self.seed)
        self.assertEqual(first, second)

    def test_changed_reviewer_difficulty_does_not_change_selection(self) -> None:
        reviewer_a = _canonical_reviewer_fixture(self.generator)
        reviewer_b = copy.deepcopy(reviewer_a)
        correct_text = self.generator["items"][0]["correct_option"]["text"]
        reviewer_b["items"][0]["candidate_diagnostics"][correct_text]["candidate_pool_observed_difficulty"] = "HARD"
        first = v02_selection.build_candidate_selection(self.generator, reviewer_a, self.seed)
        second = v02_selection.build_candidate_selection(self.generator, reviewer_b, self.seed)
        self.assertEqual(first, second)

    def test_changed_observed_clause_count_does_not_change_selection(self) -> None:
        reviewer_a = _canonical_reviewer_fixture(self.generator)
        reviewer_b = copy.deepcopy(reviewer_a)
        correct_text = self.generator["items"][0]["correct_option"]["text"]
        reviewer_b["items"][0]["candidate_diagnostics"][correct_text]["observed_clause_count"] = 99
        first = v02_selection.build_candidate_selection(self.generator, reviewer_a, self.seed)
        second = v02_selection.build_candidate_selection(self.generator, reviewer_b, self.seed)
        self.assertEqual(first, second)

    def test_malformed_canonical_reviewer_key_set_fails_closed(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        reviewer["items"][0]["option_judgments"]["an invented option text"] = "INVALID"
        with self.assertRaises(ValueError):
            v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)

    def test_invalid_candidate_with_diagnostic_fails_closed(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        entries = dict(v02_blinding.extract_candidate_entries(self.generator["items"][0]))
        invalid_text = entries["d1"]
        reviewer["items"][0]["candidate_diagnostics"][invalid_text] = {
            "natural_wording": False,
            "serious_defect": True,
            "observed_clause_count": 2,
            "candidate_pool_observed_difficulty": "MEDIUM",
            "difficulty_confidence": "HIGH",
        }
        with self.assertRaises(ValueError):
            v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)

    def test_valid_candidate_missing_diagnostic_fails_closed(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator, distractor_judgment_by_id={"d1": "VALID"})
        entries = dict(v02_blinding.extract_candidate_entries(self.generator["items"][0]))
        del reviewer["items"][0]["candidate_diagnostics"][entries["d1"]]
        with self.assertRaises(ValueError):
            v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)

    def test_exact_text_reconciliation_rejects_drift_rather_than_normalizing(self) -> None:
        reviewer = _canonical_reviewer_fixture(self.generator)
        correct_text = self.generator["items"][0]["correct_option"]["text"]
        judgment = reviewer["items"][0]["option_judgments"].pop(correct_text)
        diagnostic = reviewer["items"][0]["candidate_diagnostics"].pop(correct_text)
        reviewer["items"][0]["option_judgments"][correct_text.upper()] = judgment
        reviewer["items"][0]["candidate_diagnostics"][correct_text.upper()] = diagnostic
        with self.assertRaises(ValueError):
            v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)


class FinalAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = generator_output_fixture()
        self.seed = SEED
        self.reviewer = _canonical_reviewer_fixture(self.generator)
        self.selection = v02_selection.build_candidate_selection(self.generator, self.reviewer, self.seed)

    def test_all_fifteen_passed_gives_final_batch_of_fifteen(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        self.assertEqual(15, len(final["items"]))

    def test_any_failed_selection_prevents_assembly(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["items"][0]["passed"] = False
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_final_item_shape_matches_schema(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        self.assertEqual([], schema_errors(final, load_schema(GENERATOR_FINAL_SCHEMA)))

    def test_pre_permutation_correct_answer_is_a(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        self.assertTrue(all(item["correct_answer"] == "A" for item in final["items"]))

    def test_a_is_exact_intended_correct_text(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        self.assertEqual(self.generator["items"][0]["correct_option"]["text"], final["items"][0]["options"]["A"])

    def test_b_c_d_match_selected_texts_in_order(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        sel_item = self.selection["items"][0]
        self.assertEqual(sel_item["selected_candidate_texts"][0], final["items"][0]["options"]["B"])
        self.assertEqual(sel_item["selected_candidate_texts"][1], final["items"][0]["options"]["C"])
        self.assertEqual(sel_item["selected_candidate_texts"][2], final["items"][0]["options"]["D"])

    def test_b_c_d_rationales_match_selected_candidate_rationales(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        sel_item = self.selection["items"][0]
        gen_item = self.generator["items"][0]
        for letter, candidate_id in zip(("B", "C", "D"), sel_item["selected_candidate_ids"]):
            self.assertEqual(
                gen_item["distractor_candidates"][candidate_id]["rationale"],
                final["items"][0]["distractor_rationales"][letter],
            )

    def test_a_rationale_equals_answer_explanation(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        self.assertEqual(
            self.generator["items"][0]["answer_explanation"], final["items"][0]["distractor_rationales"]["A"]
        )

    def test_no_candidate_ids_leak(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        serialized = json.dumps(final)
        for candidate_id in v02_blinding.DISTRACTOR_IDS:
            self.assertNotIn(f'"{candidate_id}"', serialized)

    def test_no_reviewer_judgment_or_diagnostic_leaks(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        serialized = json.dumps(final)
        for forbidden in (
            "VALID", "INVALID", "MARGINAL", "natural_wording", "serious_defect",
            "candidate_pool_observed_difficulty", "difficulty_confidence",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_tampered_selected_text_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["items"][0]["selected_candidate_texts"][0] = "an invented distractor text"
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_tampered_selected_id_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        original = selection["items"][0]["selected_candidate_ids"]
        replacement_id = next(cid for cid in v02_blinding.DISTRACTOR_IDS if cid not in original)
        selection["items"][0]["selected_candidate_ids"] = [replacement_id] + original[1:]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_duplicated_selected_ids_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        ids = selection["items"][0]["selected_candidate_ids"]
        selection["items"][0]["selected_candidate_ids"] = [ids[0], ids[0], ids[1]]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_selected_non_eligible_id_fails(self) -> None:
        reviewer = _canonical_reviewer_fixture(
            self.generator, distractor_judgment_by_id={"d4": "VALID", "d5": "VALID"}
        )
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        eligible = set(selection["items"][0]["eligible_invalid_candidate_ids"])
        non_eligible = next(cid for cid in v02_blinding.DISTRACTOR_IDS if cid not in eligible)
        entries = dict(v02_blinding.extract_candidate_entries(self.generator["items"][0]))
        selection["items"][0]["selected_candidate_ids"][0] = non_eligible
        selection["items"][0]["selected_candidate_texts"][0] = entries[non_eligible]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_selected_order_inconsistent_with_priority_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        ids = selection["items"][0]["selected_candidate_ids"]
        texts = selection["items"][0]["selected_candidate_texts"]
        selection["items"][0]["selected_candidate_ids"] = [ids[1], ids[0], ids[2]]
        selection["items"][0]["selected_candidate_texts"] = [texts[1], texts[0], texts[2]]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_final_generator_ids_order_preserved(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        self.assertEqual(
            [item["item_id"] for item in self.generator["items"]],
            [item["item_id"] for item in final["items"]],
        )

    def test_final_output_compatible_with_frozen_permutation(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        permuted, _permutation = permute_generator_output(final, self.seed)
        distribution = Counter(item["correct_answer"] for item in permuted["items"])
        self.assertEqual([3, 4, 4, 4], sorted(distribution.values()))


class FinalAssemblyIntegrityTests(unittest.TestCase):
    """Fail-closed artifact-integrity boundary checks in final assembly.

    These deliberately construct schema-plausible but semantically or
    cross-field tampered selection artifacts that build_candidate_selection
    would never itself produce, and assert assemble_final_generator_output
    still rejects them rather than trusting the mutable fields.
    """

    def setUp(self) -> None:
        self.generator = generator_output_fixture()
        self.seed = SEED
        self.reviewer = _canonical_reviewer_fixture(self.generator)
        self.selection = v02_selection.build_candidate_selection(self.generator, self.reviewer, self.seed)

        # A selection with a non-trivial rejected_valid/rejected_marginal split
        # for classification-order and partition tests.
        self.mixed_reviewer = _canonical_reviewer_fixture(
            self.generator, distractor_judgment_by_id={"d1": "VALID", "d2": "MARGINAL"}
        )
        self.mixed_selection = v02_selection.build_candidate_selection(
            self.generator, self.mixed_reviewer, self.seed
        )

    def test_existing_valid_assembly_still_passes(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        self.assertEqual(15, len(final["items"]))

    def test_schema_invalid_selection_fails_assembly(self) -> None:
        selection = copy.deepcopy(self.selection)
        del selection["seed"]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_passed_true_but_intended_correct_marginal_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["items"][0]["intended_correct_judgment"] = "MARGINAL"
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_passed_true_but_intended_correct_invalid_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["items"][0]["intended_correct_judgment"] = "INVALID"
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_passed_true_but_natural_wording_false_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["items"][0]["intended_correct_natural_wording"] = False
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_passed_true_but_serious_defect_true_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["items"][0]["intended_correct_serious_defect"] = True
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_passed_true_but_nonempty_failure_reasons_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["items"][0]["failure_reasons"] = ["some_reason"]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_tampered_priority_order_still_a_valid_permutation_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        order = selection["items"][0]["deterministic_priority_order"]
        order[0], order[1] = order[1], order[0]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_changed_seed_without_recomputing_priority_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["seed"] = self.seed + 1
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_eligible_list_with_duplicate_id_fails(self) -> None:
        selection = copy.deepcopy(self.mixed_selection)
        eligible = selection["items"][0]["eligible_invalid_candidate_ids"]
        eligible.append(eligible[0])
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_classification_lists_overlap_fails(self) -> None:
        selection = copy.deepcopy(self.mixed_selection)
        item = selection["items"][0]
        self.assertTrue(item["rejected_valid_candidate_ids"])
        item["eligible_invalid_candidate_ids"].append(item["rejected_valid_candidate_ids"][0])
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_classification_lists_fail_to_cover_all_six_fails(self) -> None:
        selection = copy.deepcopy(self.mixed_selection)
        item = selection["items"][0]
        item["eligible_invalid_candidate_ids"].pop()
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_classification_list_with_non_distractor_id_fails(self) -> None:
        selection = copy.deepcopy(self.mixed_selection)
        selection["items"][0]["eligible_invalid_candidate_ids"].append("bogus")
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_eligible_list_order_inconsistent_with_priority_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        eligible = selection["items"][0]["eligible_invalid_candidate_ids"]
        self.assertGreaterEqual(len(eligible), 2)
        eligible[0], eligible[1] = eligible[1], eligible[0]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_rejected_valid_list_order_inconsistent_with_priority_fails(self) -> None:
        reviewer = _canonical_reviewer_fixture(
            self.generator, distractor_judgment_by_id={"d1": "VALID", "d2": "VALID"}
        )
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        rejected_valid = selection["items"][0]["rejected_valid_candidate_ids"]
        self.assertEqual(2, len(rejected_valid))
        rejected_valid[0], rejected_valid[1] = rejected_valid[1], rejected_valid[0]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_rejected_marginal_list_order_inconsistent_with_priority_fails(self) -> None:
        reviewer = _canonical_reviewer_fixture(
            self.generator, distractor_judgment_by_id={"d1": "MARGINAL", "d2": "MARGINAL"}
        )
        selection = v02_selection.build_candidate_selection(self.generator, reviewer, self.seed)
        rejected_marginal = selection["items"][0]["rejected_marginal_candidate_ids"]
        self.assertEqual(2, len(rejected_marginal))
        rejected_marginal[0], rejected_marginal[1] = rejected_marginal[1], rejected_marginal[0]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_selected_ids_not_first_three_eligible_fails(self) -> None:
        selection = copy.deepcopy(self.selection)
        item = selection["items"][0]
        eligible = item["eligible_invalid_candidate_ids"]
        entries = dict(v02_blinding.extract_candidate_entries(self.generator["items"][0]))
        reordered = [eligible[1], eligible[0], eligible[2]] + eligible[3:]
        item["selected_candidate_ids"] = reordered[:3]
        item["selected_candidate_texts"] = [entries[cid] for cid in reordered[:3]]
        with self.assertRaises(ValueError):
            v02_selection.assemble_final_generator_output(self.generator, selection)

    def test_valid_artifact_still_passes_frozen_permutation_compatibility(self) -> None:
        final = v02_selection.assemble_final_generator_output(self.generator, self.selection)
        permuted, _permutation = permute_generator_output(final, self.seed)
        distribution = Counter(item["correct_answer"] for item in permuted["items"])
        self.assertEqual([3, 4, 4, 4], sorted(distribution.values()))

    def test_candidate_selection_errors_behavior_unchanged(self) -> None:
        errors = v02_selection.candidate_selection_errors(
            self.generator, self.reviewer, self.selection, self.seed
        )
        self.assertEqual([], errors)


class PlannerAdapterTests(unittest.TestCase):
    """Offline tests for the v0.2 Planner adapter (structure/v02/planner.py)."""

    def test_same_seed_produces_identical_plan(self) -> None:
        self.assertEqual(v02_planner.build_plan(7), v02_planner.build_plan(7))

    def test_different_seeds_can_differ(self) -> None:
        self.assertNotEqual(v02_planner.build_plan(1), v02_planner.build_plan(2))

    def test_exactly_fifteen_items(self) -> None:
        plan = v02_planner.build_plan(7)
        self.assertEqual(15, len(plan["items"]))

    def test_version_is_v02(self) -> None:
        plan = v02_planner.build_plan(7)
        self.assertEqual("v0.2", plan["version"])

    def test_schema_version_is_structure_plan_v02(self) -> None:
        plan = v02_planner.build_plan(7)
        self.assertEqual("structure-plan-v0.2", plan["schema_version"])

    def test_exact_plan_id(self) -> None:
        plan = v02_planner.build_plan(7)
        self.assertEqual(f"structure-plan-v0.2-{7:016x}", plan["plan_id"])

    def test_exact_v02_item_ids(self) -> None:
        plan = v02_planner.build_plan(7)
        expected = [f"structure-v02-{7:016x}-{order:02d}" for order in range(1, 16)]
        self.assertEqual(expected, [item["item_id"] for item in plan["items"]])

    def test_order_is_1_through_15(self) -> None:
        plan = v02_planner.build_plan(7)
        self.assertEqual(list(range(1, 16)), [item["order"] for item in plan["items"]])

    def test_bool_seed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            v02_planner.build_plan(True)

    def test_negative_seed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            v02_planner.build_plan(-1)

    def test_plan_validates_against_v02_schema(self) -> None:
        plan = v02_planner.build_plan(7)
        self.assertEqual([], schema_errors(plan, load_schema(PLAN_SCHEMA)))

    def test_sampled_fields_match_frozen_v01_planner_slot_by_slot(self) -> None:
        preserved_fields = (
            "primary_target",
            "difficulty",
            "clause_count",
            "sentence_length_bin",
            "target_word_count",
        )
        for seed in (0, 1, 7, 42, 12345):
            with self.subTest(seed=seed):
                v01_plan = v01_planner.build_plan(seed)
                v02_plan = v02_planner.build_plan(seed)
                for v01_item, v02_item in zip(v01_plan["items"], v02_plan["items"]):
                    for field in preserved_fields:
                        self.assertEqual(
                            v01_item[field],
                            v02_item[field],
                            f"seed={seed} field={field} diverges from frozen v0.1 sampling",
                        )

    def test_adapter_does_not_mutate_v01_plan(self) -> None:
        before = v01_planner.build_plan(7)
        v02_planner.build_plan(7)
        after = v01_planner.build_plan(7)
        self.assertEqual(before, after)

    def test_no_subtype_in_plan(self) -> None:
        plan = v02_planner.build_plan(7)
        for item in plan["items"]:
            self.assertNotIn("subtype", item)

    def test_no_vocabulary_domain_in_plan(self) -> None:
        plan = v02_planner.build_plan(7)
        for item in plan["items"]:
            self.assertNotIn("vocabulary_domain", item)

    def test_no_candidate_data_in_plan(self) -> None:
        plan = v02_planner.build_plan(7)
        for item in plan["items"]:
            self.assertNotIn("correct_option", item)
            self.assertNotIn("distractor_candidates", item)
            self.assertNotIn("candidate_options", item)

    def test_no_random_random_usage_in_v02_planner_source(self) -> None:
        source = (ROOT / "structure" / "v02" / "planner.py").read_text(encoding="utf-8")
        self.assertNotIn("random.Random", source)
        self.assertNotIn("import random", source)

    def test_no_copied_empirical_weight_or_profile_tables_in_v02_planner_source(self) -> None:
        source = (ROOT / "structure" / "v02" / "planner.py").read_text(encoding="utf-8")
        for forbidden in (
            "profile.json",
            "JOINT_STRUCTURAL_WEIGHTS",
            "PRIMARY_TARGET_WEIGHTS",
            "DIFFICULTY_WEIGHTS",
            "CLAUSE_COUNT_WEIGHTS",
            "SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY",
            "weighted_choice",
        ):
            self.assertNotIn(forbidden, source)


GENERATOR_PROMPT_PATH = ROOT / "structure" / "v02" / "prompts" / "generator.md"
REVIEWER_PROMPT_PATH = ROOT / "structure" / "v02" / "prompts" / "reviewer.md"


def _generator_prompt_text() -> str:
    return GENERATOR_PROMPT_PATH.read_text(encoding="utf-8")


def _reviewer_prompt_text() -> str:
    return REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")


SOLVER_PROMPT_PATH = ROOT / "structure" / "v02" / "prompts" / "solver.md"


def _solver_prompt_text() -> str:
    return SOLVER_PROMPT_PATH.read_text(encoding="utf-8")


class GeneratorPromptContentTests(unittest.TestCase):
    """Assert the v0.2 Generator prompt encodes the candidate-pool architecture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _generator_prompt_text()

    def test_exactly_15_items(self) -> None:
        self.assertIn("15-item", self.text)
        self.assertIn("Exactly 15 items", self.text)

    def test_one_correct_option(self) -> None:
        self.assertIn("correct_option", self.text)
        self.assertIn("single intended grammatically\ncorrect completion", self.text)

    def test_six_distractor_candidates(self) -> None:
        self.assertIn("six `distractor_candidates`", self.text)
        self.assertIn("SIX distractor candidates", self.text)

    def test_d1_d6_schema_shape(self) -> None:
        self.assertIn("`d1`..`d6`", self.text)
        self.assertIn('"rationale"', self.text)
        self.assertIn("`{\"text\": ..., \"rationale\": ...}`", self.text)

    def test_no_a_d_generation_instruction(self) -> None:
        self.assertNotIn("exactly four non-empty A-D options", self.text)

    def test_no_correct_answer_field(self) -> None:
        self.assertIn("Do NOT emit any of the following", self.text)
        self.assertIn("a `correct_answer` field", self.text)

    def test_no_four_option_output_instruction(self) -> None:
        self.assertNotIn("Provide exactly four non-empty A-D options", self.text)

    def test_completed_sentence_first(self) -> None:
        self.assertIn("Completed-sentence-first length authoring procedure", self.text)

    def test_unicode_whitespace_word_counting(self) -> None:
        self.assertIn("splitting\non Unicode whitespace", self.text)

    def test_sentence_length_bin_hard_boundary(self) -> None:
        self.assertIn("deterministic hard gate remains the Planner-owned `sentence_length_bin`", self.text)

    def test_target_word_count_aim_only(self) -> None:
        self.assertIn("Exact `target_word_count` equality is\nnot required", self.text)

    def test_finite_clause_count_definition_preserved(self) -> None:
        self.assertIn("Count FINITE clauses only", self.text)
        self.assertIn("one modal + base verb is one finite clause", self.text)

    def test_generator_owned_subtype_preserved(self) -> None:
        self.assertIn("the Planner does not supply `subtype`", self.text)

    def test_free_form_vocabulary_domain_preserved(self) -> None:
        self.assertIn("value selected from a closed Structure domain enum or pool", self.text)

    def test_all_six_are_intended_invalid_distractors(self) -> None:
        self.assertIn("All six are still INTENDED DISTRACTORS", self.text)

    def test_later_filtering_is_not_permission_for_weak_distractors(self) -> None:
        self.assertIn("NOT permission to deliberately emit a weak", self.text)
        self.assertIn("not to replace careful", self.text)
        self.assertIn("Generator authorship", self.text)

    def test_complete_sentence_rescue_preserved(self) -> None:
        self.assertIn("Complete-sentence rescue test", self.text)

    def test_alternative_parse_rescue_preserved(self) -> None:
        self.assertIn("evaluate the complete sentence under\nthe candidate's own best ordinary parse".lower(), self.text.lower())

    def test_six_rationales_required(self) -> None:
        self.assertIn("one rationale for each of the six\n`distractor_candidates` (`d1`..`d6`)", self.text)

    def test_no_self_review_retry_repair_regeneration(self) -> None:
        self.assertIn(
            "Do not self-review, do not emit a\nPASS/FAIL or quality verdict, and do not perform a second call, repair, retry,\n"
            "regeneration, revision, or replacement over any item.",
            self.text,
        )

    def test_no_official_ets_copying_instruction_preserved(self) -> None:
        self.assertIn("Never copy or lightly\nparaphrase any ETS item", self.text)

    def test_no_exactly_four_non_empty_a_d_options_phrase(self) -> None:
        self.assertNotIn("exactly four non-empty A-D options", self.text)

    def test_no_correct_answer_output_contract(self) -> None:
        self.assertNotIn("`correct_answer`:", self.text)

    def test_no_a_d_options_output_contract(self) -> None:
        self.assertNotIn("Provide exactly four non-empty A-D options", self.text)
        self.assertIn("an `options` object", self.text)

    def test_no_a_d_distractor_rationales_output_contract(self) -> None:
        self.assertNotIn("A-D option.", self.text)


class ReviewerPromptContentTests(unittest.TestCase):
    """Assert the v0.2 Reviewer prompt encodes blind seven-candidate review semantics."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _reviewer_prompt_text()

    def test_input_allowlist(self) -> None:
        self.assertIn(
            "The input contains only `item_id`, `section`, `stem`, and", self.text
        )
        self.assertIn("`candidate_options`", self.text)

    def test_exactly_seven_visible_candidates(self) -> None:
        self.assertIn("exactly seven visible strings", self.text)
        self.assertIn("a list of exactly seven objects", self.text)

    def test_candidate_ids_private(self) -> None:
        self.assertIn("internal candidate IDs", self.text)

    def test_every_candidate_judged_independently(self) -> None:
        self.assertIn(
            "For every one of the seven visible candidate texts, independently insert it", self.text
        )

    def test_valid_invalid_marginal_meanings(self) -> None:
        for label in ("**VALID:**", "**INVALID:**", "**MARGINAL:**"):
            self.assertIn(label, self.text)

    def test_multiple_valid_explicitly_allowed(self) -> None:
        self.assertIn("two VALID candidates are allowed", self.text)

    def test_multiple_marginal_explicitly_allowed(self) -> None:
        self.assertIn("multiple MARGINAL candidates are allowed", self.text)

    def test_multiple_valid_does_not_imply_serious_defect(self) -> None:
        self.assertIn(
            "NOT set `serious_defect=true` on a candidate merely because more than one",
            self.text,
        )
        self.assertIn("visible candidate is VALID or MARGINAL.", self.text)

    def test_no_global_best_answer(self) -> None:
        self.assertIn("Do NOT return `best_answer_text` or any global best-answer field", self.text)

    def test_no_ambiguous_none(self) -> None:
        self.assertIn("Do NOT return `AMBIGUOUS`. Do NOT return `NONE`.", self.text)

    def test_exact_option_text_identity(self) -> None:
        self.assertIn("Do not trim, rewrite, normalize, casefold, or\nfuzzy-match a candidate.", self.text)

    def test_candidate_diagnostics_only_valid_marginal(self) -> None:
        self.assertIn(
            "return `candidate_diagnostics` ONLY for candidates you judged\n`VALID` or `MARGINAL`", self.text
        )

    def test_invalid_has_no_diagnostic(self) -> None:
        self.assertIn("`INVALID` candidates\nget NO diagnostic entry", self.text)

    def test_natural_wording_candidate_specific(self) -> None:
        self.assertIn("`natural_wording` is candidate-specific", self.text)

    def test_serious_defect_candidate_specific(self) -> None:
        self.assertIn("`serious_defect` is candidate-specific", self.text)

    def test_observed_clause_count_candidate_specific(self) -> None:
        self.assertIn(
            "report\n`observed_clause_count`: the number of FINITE clauses you observe in the\n"
            "completed sentence formed by inserting THAT candidate.",
            self.text,
        )

    def test_finite_clause_definition_preserved(self) -> None:
        self.assertIn("A modal + base verb belongs to ONE finite clause", self.text)

    def test_candidate_pool_difficulty_diagnostic_only(self) -> None:
        self.assertIn("This is a DIAGNOSTIC of the visible seven-candidate review context", self.text)

    def test_difficulty_not_equivalent_to_final_four_option(self) -> None:
        self.assertIn(
            "It is NOT\nequivalent to a final four-option item's difficulty classification", self.text
        )

    def test_no_planner_difficulty_comparison(self) -> None:
        self.assertIn("will NOT be compared against Planner difficulty for acceptance", self.text)

    def test_no_historical_quota_forcing(self) -> None:
        self.assertIn(
            "Do NOT\nattempt to force the historical 18/42/15 distribution or any historical\nquota.",
            self.text,
        )

    def test_reviewer_comment_not_acceptance_input(self) -> None:
        self.assertIn("not itself an acceptance input", self.text)

    def test_alternative_parse_protection_preserved(self) -> None:
        self.assertIn("own best ordinary parse", self.text)

    def test_tense_rescue_protection_preserved(self) -> None:
        self.assertIn("different plausible tense interpretation", self.text)

    def test_connector_complement_protection_preserved(self) -> None:
        self.assertIn("full syntactic complement after insertion through the end of the", self.text)

    def test_who_whom_structural_rule_preserved(self) -> None:
        self.assertIn("Bare object position (bare object relative position)", self.text)
        self.assertIn("Immediately after a fronted preposition", self.text)

    def test_no_a_b_c_d(self) -> None:
        self.assertNotIn("A/B/C/D references", self.text)

    def test_no_best_answer_text_field(self) -> None:
        self.assertNotIn("Return `best_answer_text` as", self.text)

    def test_no_unique_answer_requirement_across_seven_option_pool(self) -> None:
        self.assertIn("enforce final-answer", self.text)
        self.assertIn("uniqueness across the seven-candidate pool", self.text)


def _final_permuted_fixture(seed: int = SEED) -> dict[str, Any]:
    """Build the complete v0.2 pre-Solver artifact: Generator -> Reviewer ->
    candidate selection -> four-option assembly -> frozen permutation."""

    generator = generator_output_fixture()
    reviewer = _canonical_reviewer_fixture(generator)
    selection = v02_selection.build_candidate_selection(generator, reviewer, seed)
    final = v02_selection.assemble_final_generator_output(generator, selection)
    permuted, _permutation = permute_generator_output(final, seed)
    return permuted


def _raw_solver_output_fixture(solver_input: dict[str, Any]) -> dict[str, Any]:
    """Build a schema-valid, contract-valid raw Solver response for a projection.

    Always answers with the exact visible text of option "A", which is a
    faithful raw Solver-style response shape (it need not be semantically
    "correct" for these offline compatibility tests).
    """

    return {
        "items": [
            {
                "item_id": item["item_id"],
                "answer_text": item["options"]["A"],
                "confidence": "HIGH",
                "reason": "The option completes the sentence naturally.",
            }
            for item in solver_input["items"]
        ]
    }


class SolverProjectionTests(unittest.TestCase):
    """Structure v0.2 Solver compatibility layer: blind final-four projection."""

    def setUp(self) -> None:
        self.final_permuted = _final_permuted_fixture()
        self.solver_input = v02_solver.build_solver_input(self.final_permuted)

    def test_projection_succeeds(self) -> None:
        self.assertIsInstance(self.solver_input, dict)

    def test_exactly_fifteen_items(self) -> None:
        self.assertEqual(15, len(self.solver_input["items"]))

    def test_per_item_keys_are_exactly_allowlisted(self) -> None:
        for item in self.solver_input["items"]:
            self.assertEqual({"item_id", "section", "stem", "options"}, set(item))

    def test_options_exactly_a_through_d(self) -> None:
        for item in self.solver_input["items"]:
            self.assertEqual({"A", "B", "C", "D"}, set(item["options"]))

    def test_final_permuted_option_texts_preserved_exactly(self) -> None:
        for expected_item, projected_item in zip(self.final_permuted["items"], self.solver_input["items"]):
            self.assertEqual(expected_item["options"], projected_item["options"])

    def test_item_id_and_order_preserved(self) -> None:
        self.assertEqual(
            [item["item_id"] for item in self.final_permuted["items"]],
            [item["item_id"] for item in self.solver_input["items"]],
        )

    def test_validates_against_frozen_solver_input_schema(self) -> None:
        self.assertEqual(
            [], schema_errors(self.solver_input, load_schema(v02_solver.SOLVER_INPUT_SCHEMA_PATH))
        )

    def test_matches_frozen_v01_blind_projection_directly(self) -> None:
        self.assertEqual(v01_blinding.build_solver_input(self.final_permuted), self.solver_input)

    def test_same_final_permuted_gives_identical_projection(self) -> None:
        first = v02_solver.build_solver_input(self.final_permuted)
        second = v02_solver.build_solver_input(self.final_permuted)
        self.assertEqual(first, second)

    def test_no_correct_answer_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        self.assertNotIn("correct_answer", serialized)

    def test_no_answer_explanation_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        self.assertNotIn("answer_explanation", serialized)

    def test_no_distractor_rationale_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        self.assertNotIn("distractor_rationales", serialized)
        self.assertNotIn("rationale", serialized)

    def test_no_planner_generator_metadata_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        for forbidden in ("primary_target", "subtype", "difficulty", "vocabulary_domain", "secondary_features"):
            self.assertNotIn(forbidden, serialized)

    def test_no_seven_candidate_pool_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        for forbidden in ("candidate_options", "distractor_candidates", "correct_option"):
            self.assertNotIn(forbidden, serialized)

    def test_no_candidate_ids_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        for candidate_id in v02_blinding.CANDIDATE_IDS:
            self.assertNotIn(f'"{candidate_id}"', serialized)

    def test_no_reviewer_fields_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        for forbidden in (
            "option_judgments", "candidate_diagnostics", "natural_wording", "serious_defect",
            "observed_clause_count", "candidate_pool_observed_difficulty", "difficulty_confidence", "comment",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_no_candidate_selection_fields_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        for forbidden in (
            "eligible_invalid_candidate_ids", "rejected_valid_candidate_ids", "rejected_marginal_candidate_ids",
            "deterministic_priority_order", "selected_candidate_ids", "selected_candidate_texts",
            "intended_correct_text", "intended_correct_judgment", "failure_reasons", "passed",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_no_permutation_provenance_leak(self) -> None:
        serialized = json.dumps(self.solver_input)
        for forbidden in ("permutation", "original_to_canonical", "canonical_to_original"):
            self.assertNotIn(forbidden, serialized)


class SolverInputReplayValidationTests(unittest.TestCase):
    """solver_input_errors: deterministic rebuild, schema check, exact equality."""

    def setUp(self) -> None:
        self.final_permuted = _final_permuted_fixture()
        self.solver_input = v02_solver.build_solver_input(self.final_permuted)

    def test_matching_payload_has_no_errors(self) -> None:
        self.assertEqual([], v02_solver.solver_input_errors(self.final_permuted, self.solver_input))

    def test_modified_option_text_fails(self) -> None:
        payload = copy.deepcopy(self.solver_input)
        payload["items"][0]["options"]["A"] = payload["items"][0]["options"]["A"] + " extra"
        self.assertTrue(v02_solver.solver_input_errors(self.final_permuted, payload))

    def test_modified_option_letter_mapping_fails(self) -> None:
        payload = copy.deepcopy(self.solver_input)
        options = payload["items"][0]["options"]
        options["A"], options["B"] = options["B"], options["A"]
        self.assertTrue(v02_solver.solver_input_errors(self.final_permuted, payload))

    def test_modified_item_order_fails(self) -> None:
        payload = copy.deepcopy(self.solver_input)
        payload["items"][0], payload["items"][1] = payload["items"][1], payload["items"][0]
        self.assertTrue(v02_solver.solver_input_errors(self.final_permuted, payload))

    def test_modified_item_id_fails(self) -> None:
        payload = copy.deepcopy(self.solver_input)
        payload["items"][0]["item_id"] = payload["items"][0]["item_id"] + "-tampered"
        self.assertTrue(v02_solver.solver_input_errors(self.final_permuted, payload))

    def test_modified_stem_fails(self) -> None:
        payload = copy.deepcopy(self.solver_input)
        payload["items"][0]["stem"] = payload["items"][0]["stem"] + " Extra sentence."
        self.assertTrue(v02_solver.solver_input_errors(self.final_permuted, payload))

    def test_added_private_field_fails(self) -> None:
        payload = copy.deepcopy(self.solver_input)
        payload["items"][0]["primary_target"] = "VERB_FORM_VOICE"
        self.assertTrue(v02_solver.solver_input_errors(self.final_permuted, payload))

    def test_removed_field_fails(self) -> None:
        payload = copy.deepcopy(self.solver_input)
        del payload["items"][0]["stem"]
        self.assertTrue(v02_solver.solver_input_errors(self.final_permuted, payload))


class SolverInputFrozenSchemaCompatibilityTests(unittest.TestCase):
    def test_frozen_solver_input_schema_accepts_v02_projected_input(self) -> None:
        solver_input = v02_solver.build_solver_input(_final_permuted_fixture())
        self.assertEqual(
            [], schema_errors(solver_input, load_schema(v01_contracts.SCHEMA_PATHS["solver_input"]))
        )


class SolverOutputContractReuseTests(unittest.TestCase):
    """v0.2 Solver output validation/canonicalization delegates to the frozen v0.1 contract."""

    def setUp(self) -> None:
        self.final_permuted = _final_permuted_fixture()
        self.solver_input = v02_solver.build_solver_input(self.final_permuted)
        self.raw_solver = _raw_solver_output_fixture(self.solver_input)

    def test_valid_v01_style_raw_response_validates(self) -> None:
        self.assertEqual([], v02_solver.validate_solver_contract(self.raw_solver, self.solver_input))

    def test_canonicalizes_unique_answer_to_current_letter(self) -> None:
        canonical = v02_solver.canonicalize_solver_output(self.raw_solver, self.solver_input)
        for output_item in canonical["items"]:
            self.assertEqual("A", output_item["answer"])

    def test_ambiguous_sentinel_allowed(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["answer_text"] = "AMBIGUOUS"
        self.assertEqual([], v02_solver.validate_solver_contract(raw, self.solver_input))
        canonical = v02_solver.canonicalize_solver_output(raw, self.solver_input)
        self.assertEqual("AMBIGUOUS", canonical["items"][0]["answer"])

    def test_none_sentinel_allowed(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["answer_text"] = "NONE"
        self.assertEqual([], v02_solver.validate_solver_contract(raw, self.solver_input))
        canonical = v02_solver.canonicalize_solver_output(raw, self.solver_input)
        self.assertEqual("NONE", canonical["items"][0]["answer"])

    def test_case_drift_fails(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["answer_text"] = raw["items"][0]["answer_text"].upper()
        self.assertTrue(v02_solver.validate_solver_contract(raw, self.solver_input))

    def test_whitespace_drift_fails(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["answer_text"] = raw["items"][0]["answer_text"] + " "
        self.assertTrue(v02_solver.validate_solver_contract(raw, self.solver_input))

    def test_punctuation_drift_fails(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["answer_text"] = raw["items"][0]["answer_text"] + "."
        self.assertTrue(v02_solver.validate_solver_contract(raw, self.solver_input))

    def test_invented_option_text_fails(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["answer_text"] = "an invented completion nobody offered"
        self.assertTrue(v02_solver.validate_solver_contract(raw, self.solver_input))

    def test_letter_used_as_answer_text_fails_unless_it_is_itself_a_visible_option(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        options = self.solver_input["items"][0]["options"]
        raw["items"][0]["answer_text"] = "A"
        self.assertNotEqual("A", options["A"])
        self.assertTrue(v02_solver.validate_solver_contract(raw, self.solver_input))

    def test_malformed_item_id_order_fails(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0], raw["items"][1] = raw["items"][1], raw["items"][0]
        self.assertTrue(v02_solver.validate_solver_contract(raw, self.solver_input))

    def test_malformed_confidence_fails_through_frozen_contract(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["confidence"] = "CERTAIN"
        self.assertTrue(v02_solver.validate_solver_contract(raw, self.solver_input))

    def test_reason_does_not_determine_answer_identity(self) -> None:
        raw = copy.deepcopy(self.raw_solver)
        raw["items"][0]["reason"] = "I actually think option D is correct, not A."
        canonical = v02_solver.canonicalize_solver_output(raw, self.solver_input)
        self.assertEqual("A", canonical["items"][0]["answer"])

    def test_wrapper_equivalent_to_calling_frozen_contract_directly(self) -> None:
        self.assertEqual(
            v01_contracts.validate_solver_contract(self.raw_solver, self.solver_input),
            v02_solver.validate_solver_contract(self.raw_solver, self.solver_input),
        )
        self.assertEqual(
            v01_contracts.canonicalize_solver_output(self.raw_solver, self.solver_input),
            v02_solver.canonicalize_solver_output(self.raw_solver, self.solver_input),
        )


class SolverModuleScopeTests(unittest.TestCase):
    """The v0.2 Solver module must not perform Generator/Reviewer reconciliation."""

    def test_no_generator_reviewer_reconciliation_in_solver_module_source(self) -> None:
        source = (ROOT / "structure" / "v02" / "solver.py").read_text(encoding="utf-8")
        self.assertNotIn("import structure.v02.selection", source)
        self.assertNotIn("from structure.v02 import selection", source)
        self.assertNotIn("from structure.v02.selection", source)
        self.assertNotIn("import structure.v02.contracts", source)
        self.assertNotIn("from structure.v02 import contracts", source)
        self.assertNotIn("from structure.v02.contracts", source)
        for forbidden in (
            "option_judgments", "candidate_diagnostics",
            "best_answer", "extract_candidate_entries", "correct_answer",
        ):
            self.assertNotIn(forbidden, source)

    def test_no_new_solver_schemas_created(self) -> None:
        self.assertFalse((ROOT / "structure" / "v02" / "schemas" / "solver_input.schema.json").exists())
        self.assertFalse((ROOT / "structure" / "v02" / "schemas" / "solver_output.schema.json").exists())

    def test_v02_protected_schema_hashes_unchanged(self) -> None:
        self.assertNotIn(
            "structure/v02/schemas/solver_input.schema.json", V02_PROTECTED_SCHEMA_HASHES
        )
        self.assertNotIn(
            "structure/v02/schemas/solver_output.schema.json", V02_PROTECTED_SCHEMA_HASHES
        )


class SolverPromptFreezeTests(unittest.TestCase):
    def test_solver_prompt_hash_matches_protected_value(self) -> None:
        path = ROOT / "structure" / "v02" / "prompts" / "solver.md"
        self.assertEqual(
            _sha256(path), V02_PROTECTED_PROMPT_HASHES["structure/v02/prompts/solver.md"]
        )


class SolverPromptContentTests(unittest.TestCase):
    """Assert the v0.2 Solver prompt encodes the frozen blind final-four semantics."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _solver_prompt_text()

    def test_v02_identity(self) -> None:
        self.assertIn("name: structure-solver-v0.2", self.text)
        self.assertIn("# Structure v0.2 Blind Solver", self.text)

    def test_final_four_option_independent_test_taker_role(self) -> None:
        self.assertIn("independent test-taker solving\nthe FINAL four-option item", self.text)

    def test_input_allowlist_exactly_item_id_section_stem_options(self) -> None:
        self.assertIn(
            "The input contains only `item_id`, `section`,\n`stem`, and `options`",
            self.text,
        )

    def test_candidate_pool_forbidden(self) -> None:
        self.assertIn("the seven-candidate pool", self.text)

    def test_reviewer_output_forbidden(self) -> None:
        self.assertIn("Reviewer output or diagnostics", self.text)

    def test_candidate_selection_forbidden(self) -> None:
        self.assertIn("candidate selection", self.text)

    def test_literal_full_sentence_insertion_rule(self) -> None:
        self.assertIn(
            "literally insert it into the `____` blank and judge the\nresulting complete sentence, "
            "including all text before AND after the blank",
            self.text,
        )

    def test_ambiguous_rule(self) -> None:
        self.assertIn("Return\n`AMBIGUOUS` for two or more acceptable completions", self.text)

    def test_none_rule(self) -> None:
        self.assertIn("`NONE` when no\nacceptable completion exists", self.text)

    def test_exact_answer_text_identity(self) -> None:
        self.assertIn(
            "Copy that option string exactly, including case,\npunctuation, and whitespace", self.text
        )

    def test_answer_text_is_not_a_letter(self) -> None:
        self.assertIn("Do not return an A/B/C/D letter as the answer", self.text)

    def test_reason_not_source_of_truth(self) -> None:
        self.assertIn("The exact `answer_text` is the\nsource of truth; the reason is natural-language support only", self.text)

    def test_confidence_bands(self) -> None:
        self.assertIn("`HIGH`, `MEDIUM`, or `LOW` confidence", self.text)

    def test_no_forced_guess(self) -> None:
        self.assertIn("Do not force a guess", self.text)

    def test_exactly_fifteen_output_items(self) -> None:
        self.assertIn("Exactly 15 items", self.text)

    def test_output_json_only(self) -> None:
        self.assertIn("No\nmarkdown. No prose outside the JSON", self.text)

    def test_no_assumption_that_prior_filtering_guarantees_uniqueness(self) -> None:
        self.assertIn("you do not see that pool or its filtering, and you\nmust not assume", self.text)
        self.assertIn("hard production safeguard", self.text)


DUMMY_SHA256 = "0" * 64
ARTIFACT_HASH_KEYS: tuple[str, ...] = (
    "plan.json",
    "generator_raw.json",
    "generator_candidates.json",
    "reviewer_input.json",
    "reviewer.json",
    "candidate_selection.json",
    "generator_final.json",
    "permutation.json",
    "generator.json",
    "solver_input.json",
    "solver.json",
)


def artifact_hashes_fixture() -> dict[str, str]:
    return {name: f"sha256:{DUMMY_SHA256}" for name in ARTIFACT_HASH_KEYS}


def _result_item(index: int) -> dict[str, Any]:
    return {
        "item_id": f"structure-v02-fixture-{index:02d}",
        "accepted": True,
        "rejection_reasons": [],
    }


def result_fixture() -> dict[str, Any]:
    return {
        "schema_version": "structure-result-v0.2",
        "version": "v0.2",
        "run_id": "structure-v02-fixture-run",
        "seed": 1,
        "decision": "ACCEPT",
        "question_count": 15,
        "live_invocation_count": 3,
        "deterministic_hard_failure_count": 0,
        "candidate_selection_pass_count": 15,
        "candidate_selection_failure_count": 0,
        "solver_key_agreement_count": 15,
        "solver_ambiguous_none_count": 0,
        "final_answer_position_distribution": {"A": 4, "B": 4, "C": 4, "D": 3},
        "item_results": [_result_item(index) for index in range(1, 16)],
        "checks": {
            "generator_contract": True,
            "generator_errors": [],
            "reviewer_input_contract": True,
            "reviewer_input_errors": [],
            "reviewer_contract": True,
            "reviewer_errors": [],
            "reviewer_canonicalization": {},
            "candidate_selection": {},
            "final_assembly": {},
            "permutation": {},
            "solver_input_contract": True,
            "solver_input_errors": [],
            "solver_contract": True,
            "solver_errors": [],
            "solver_canonicalization": {},
            "solver_key_check": {},
            "reviewer_clause_count": {},
            "candidate_pool_difficulty": {},
            "all_15_items_pass": True,
        },
        "infrastructure": {"runtime_failures": []},
        "artifact_hashes": artifact_hashes_fixture(),
        "output_dir": "runs/structure_v0_2/fixture-run",
    }


def provenance_fixture() -> dict[str, Any]:
    return {
        "schema_version": "structure-provenance-v0.2",
        "version": "v0.2",
        "run_id": "structure-v02-fixture-run",
        "seed": 1,
        "provider": "codex",
        "model": "fixture-model",
        "invocations": [],
        "invocation_ids": [],
        "invocation_count": 3,
        "logical_invocation_counts": {"generator": 1, "reviewer": 1, "solver": 1},
        "deterministic_validation": {},
        "candidate_selection": {},
        "answer_position_permutation": {},
        "blind_inputs": {},
        "reviewer_canonicalization": {},
        "solver_canonicalization": {},
        "solver_key_check": {},
        "leakage": {},
        "fallback": {},
        "runtime_failures": [],
        "artifact_hashes": artifact_hashes_fixture(),
    }


class ResultSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(result_fixture(), load_schema(RESULT_SCHEMA)))

    def test_rejects_v01_schema_version(self) -> None:
        payload = result_fixture()
        payload["schema_version"] = "structure-result-v0.1"
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_v01_version(self) -> None:
        payload = result_fixture()
        payload["version"] = "v0.1"
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_wrong_question_count(self) -> None:
        payload = result_fixture()
        payload["question_count"] = 14
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_invalid_decision(self) -> None:
        payload = result_fixture()
        payload["decision"] = "MAYBE"
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_candidate_selection_pass_count_over_15(self) -> None:
        payload = result_fixture()
        payload["candidate_selection_pass_count"] = 16
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_candidate_selection_failure_count_over_15(self) -> None:
        payload = result_fixture()
        payload["candidate_selection_failure_count"] = 16
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_solver_key_agreement_count_over_15(self) -> None:
        payload = result_fixture()
        payload["solver_key_agreement_count"] = 16
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_solver_ambiguous_none_count_over_15(self) -> None:
        payload = result_fixture()
        payload["solver_ambiguous_none_count"] = 16
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_item_results_not_exactly_15(self) -> None:
        payload = result_fixture()
        payload["item_results"] = payload["item_results"][:14]
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_malformed_item_result(self) -> None:
        payload = result_fixture()
        del payload["item_results"][0]["rejection_reasons"]
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_missing_checks_category(self) -> None:
        payload = result_fixture()
        del payload["checks"]["all_15_items_pass"]
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_extra_checks_category(self) -> None:
        payload = result_fixture()
        payload["checks"]["extra_category"] = {}
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_infrastructure_missing_runtime_failures(self) -> None:
        payload = result_fixture()
        payload["infrastructure"] = {}
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_artifact_hashes_missing_one_artifact(self) -> None:
        payload = result_fixture()
        del payload["artifact_hashes"]["solver.json"]
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_artifact_hashes_extra_artifact(self) -> None:
        payload = result_fixture()
        payload["artifact_hashes"]["result.json"] = f"sha256:{DUMMY_SHA256}"
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_rejects_malformed_sha256(self) -> None:
        payload = result_fixture()
        payload["artifact_hashes"]["solver.json"] = "not-a-hash"
        self.assertTrue(schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_allows_zero_answer_distribution_for_pre_permutation_quarantine(self) -> None:
        payload = result_fixture()
        payload["decision"] = "QUARANTINE"
        payload["final_answer_position_distribution"] = {"A": 0, "B": 0, "C": 0, "D": 0}
        self.assertEqual([], schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_allows_4433_answer_distribution(self) -> None:
        payload = result_fixture()
        payload["final_answer_position_distribution"] = {"A": 4, "B": 4, "C": 4, "D": 3}
        self.assertEqual([], schema_errors(payload, load_schema(RESULT_SCHEMA)))

    def test_contains_no_reviewer_solver_agreement(self) -> None:
        schema_text = RESULT_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("reviewer_solver_agreement", schema_text)

    def test_contains_no_reviewer_difficulty_agreement_count(self) -> None:
        schema_text = RESULT_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("reviewer_difficulty_agreement_count", schema_text)

    def test_contains_no_reviewer_difficulty_low_confidence_count(self) -> None:
        schema_text = RESULT_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("reviewer_difficulty_low_confidence_count", schema_text)

    def test_contains_no_reviewer_ambiguous_none_count(self) -> None:
        schema_text = RESULT_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("reviewer_ambiguous_none_count", schema_text)


class ProvenanceSchemaTests(unittest.TestCase):
    def test_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(provenance_fixture(), load_schema(PROVENANCE_SCHEMA)))

    def test_rejects_wrong_schema_version(self) -> None:
        payload = provenance_fixture()
        payload["schema_version"] = "structure-provenance-v0.1"
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_rejects_wrong_version(self) -> None:
        payload = provenance_fixture()
        payload["version"] = "v0.1"
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_rejects_negative_seed(self) -> None:
        payload = provenance_fixture()
        payload["seed"] = -1
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_logical_invocation_counts_requires_exactly_generator_reviewer_solver(self) -> None:
        payload = provenance_fixture()
        del payload["logical_invocation_counts"]["solver"]
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_logical_invocation_counts_rejects_repair_revision_regeneration_keys(self) -> None:
        for key in ("repair", "revision", "regeneration"):
            with self.subTest(key=key):
                payload = provenance_fixture()
                payload["logical_invocation_counts"][key] = 1
                self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_answer_position_permutation_may_be_null(self) -> None:
        payload = provenance_fixture()
        payload["answer_position_permutation"] = None
        self.assertEqual([], schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_answer_position_permutation_may_be_object(self) -> None:
        payload = provenance_fixture()
        payload["answer_position_permutation"] = {"note": "fixture"}
        self.assertEqual([], schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_runtime_failures_must_be_array(self) -> None:
        payload = provenance_fixture()
        payload["runtime_failures"] = {}
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_rejects_missing_artifact_hash(self) -> None:
        payload = provenance_fixture()
        del payload["artifact_hashes"]["plan.json"]
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_rejects_extra_artifact_hash(self) -> None:
        payload = provenance_fixture()
        payload["artifact_hashes"]["provenance.json"] = f"sha256:{DUMMY_SHA256}"
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_rejects_malformed_artifact_hash(self) -> None:
        payload = provenance_fixture()
        payload["artifact_hashes"]["plan.json"] = "sha256:not-hex"
        self.assertTrue(schema_errors(payload, load_schema(PROVENANCE_SCHEMA)))

    def test_contains_no_reviewer_solver_agreement(self) -> None:
        schema_text = PROVENANCE_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("reviewer_solver_agreement", schema_text)

    def test_contains_no_planner_reviewer_difficulty_agreement_field(self) -> None:
        schema_text = PROVENANCE_SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn("difficulty_agreement", schema_text)


class CrossSchemaArtifactHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result_schema = load_schema(RESULT_SCHEMA)
        self.provenance_schema = load_schema(PROVENANCE_SCHEMA)

    def test_identical_required_key_sets(self) -> None:
        self.assertEqual(
            set(self.result_schema["properties"]["artifact_hashes"]["required"]),
            set(self.provenance_schema["properties"]["artifact_hashes"]["required"]),
        )

    def test_identical_property_key_sets(self) -> None:
        self.assertEqual(
            set(self.result_schema["properties"]["artifact_hashes"]["properties"]),
            set(self.provenance_schema["properties"]["artifact_hashes"]["properties"]),
        )

    def test_both_additional_properties_false(self) -> None:
        self.assertFalse(self.result_schema["properties"]["artifact_hashes"]["additionalProperties"])
        self.assertFalse(self.provenance_schema["properties"]["artifact_hashes"]["additionalProperties"])

    def test_exact_set_equals_approved_eleven_artifacts(self) -> None:
        self.assertEqual(set(ARTIFACT_HASH_KEYS), set(self.result_schema["properties"]["artifact_hashes"]["required"]))
        self.assertEqual(
            set(ARTIFACT_HASH_KEYS), set(self.provenance_schema["properties"]["artifact_hashes"]["required"])
        )
        self.assertEqual(11, len(ARTIFACT_HASH_KEYS))

    def test_result_json_not_in_artifact_hashes(self) -> None:
        self.assertNotIn("result.json", self.result_schema["properties"]["artifact_hashes"]["properties"])
        self.assertNotIn("result.json", self.provenance_schema["properties"]["artifact_hashes"]["properties"])

    def test_provenance_json_not_in_artifact_hashes(self) -> None:
        self.assertNotIn("provenance.json", self.result_schema["properties"]["artifact_hashes"]["properties"])
        self.assertNotIn("provenance.json", self.provenance_schema["properties"]["artifact_hashes"]["properties"])


PIPELINE_STEM_FILLER_WORDS = (
    "in", "the", "archive", "during", "the", "extended", "review", "process",
    "for", "the", "ongoing", "study", "across", "multiple", "sessions", "before",
    "the", "final", "report", "was", "submitted", "to", "the", "committee",
)


def _pipeline_stem_for_word_count(word_count: int) -> str:
    """Build a fixture stem whose completed ('confirmed') word count is exact."""

    words = ["The", "researcher", v01_contracts.BLANK_MARKER, "the", "documented", "pattern"]
    index = 0
    while len(words) < word_count:
        words.append(PIPELINE_STEM_FILLER_WORDS[index % len(PIPELINE_STEM_FILLER_WORDS)])
        index += 1
    words = words[:word_count]
    words[-1] = f"{words[-1]}."
    return " ".join(words)


def _pipeline_fake_generator_output(plan: dict[str, Any]) -> dict[str, Any]:
    """Dynamic Generator response built from the actual Planner-owned plan payload."""

    items = []
    for planned in plan["items"]:
        items.append({
            "item_id": planned["item_id"],
            "section": "Structure",
            "primary_target": planned["primary_target"],
            "subtype": f"{planned['primary_target']} generator-authored construction",
            "secondary_features": ["academic register"],
            "difficulty": planned["difficulty"],
            "vocabulary_domain": "generator-owned domain",
            "stem": _pipeline_stem_for_word_count(planned["target_word_count"]),
            "correct_option": {"text": "confirmed"},
            "answer_explanation": "The finite past-tense verb is required in this main clause.",
            "distractor_candidates": {
                "d1": {"text": "confirming", "rationale": "A participle cannot stand as the finite main verb."},
                "d2": {"text": "confirm", "rationale": "The base form does not carry the required tense."},
                "d3": {"text": "confirms", "rationale": "The present tense does not match the past-tense context."},
                "d4": {"text": "to confirm", "rationale": "The infinitive cannot stand as the finite main verb."},
                "d5": {
                    "text": "having confirmed",
                    "rationale": "The perfect participle cannot stand as the finite main verb.",
                },
                "d6": {
                    "text": "be confirmed",
                    "rationale": "The passive base form cannot stand as the finite main verb here.",
                },
            },
        })
    return {"items": items}


def _pipeline_fake_reviewer_output(reviewer_input: dict[str, Any]) -> dict[str, Any]:
    """Dynamic Reviewer response: copies exact shuffled candidate_options texts."""

    correct_text = "confirmed"
    items = []
    for item in reviewer_input["items"]:
        options = item["candidate_options"]
        judgments = [
            {"option_text": text, "judgment": "VALID" if text == correct_text else "INVALID"}
            for text in options
        ]
        diagnostics = [{
            "option_text": correct_text,
            "natural_wording": True,
            "serious_defect": False,
            "observed_clause_count": 2,
            "candidate_pool_observed_difficulty": "MEDIUM",
            "difficulty_confidence": "HIGH",
        }]
        items.append({
            "item_id": item["item_id"],
            "option_judgments": judgments,
            "candidate_diagnostics": diagnostics,
            "comment": "Only the finite past-tense form completes the main clause naturally.",
        })
    return {"items": items}


def _pipeline_fake_solver_output(solver_input: dict[str, Any]) -> dict[str, Any]:
    """Dynamic Solver response: copies exact final visible option text."""

    items = []
    for item in solver_input["items"]:
        options = item["options"]
        correct_letter = next(letter for letter in v01_contracts.LETTERS if options[letter] == "confirmed")
        items.append({
            "item_id": item["item_id"],
            "answer_text": options[correct_letter],
            "confidence": "HIGH",
            "reason": "The finite past-tense completion is the only acceptable choice.",
        })
    return {"items": items}


class FakePipelineRuntime:
    """Deterministic offline scripted runtime. No subprocess, no network."""

    provider = "offline-fixture"
    cli_version = "offline-fixture"
    model = "offline-fixture"

    def __init__(
        self,
        *,
        generator: Any = None,
        reviewer: Any = None,
        solver: Any = None,
        generator_error: tuple[str, str] | None = None,
        reviewer_error: tuple[str, str] | None = None,
        solver_error: tuple[str, str] | None = None,
    ) -> None:
        self.generator_override = generator
        self.reviewer_override = reviewer
        self.solver_override = solver
        self.generator_error = generator_error
        self.reviewer_error = reviewer_error
        self.solver_error = solver_error
        self.requests: list[InvocationRequest] = []

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
        stage_key = request.stage.rsplit("_", 1)[-1]
        result = InvocationResult(
            stage=request.stage,
            agent_name=request.agent_name,
            invocation_id=f"offline-{len(self.requests)}",
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:01+00:00",
            provider=self.provider,
            model=self.model,
            cli_version=self.cli_version,
            input_keys=list(request.input_keys),
        )
        error = getattr(self, f"{stage_key}_error")
        if error is not None:
            category, detail = error
            result.error_category = category
            result.error_detail = detail
            raise RuntimeInvocationError(category, detail, result)

        override = getattr(self, f"{stage_key}_override")
        if callable(override):
            parsed = override(payload)
        elif override is not None:
            parsed = override
        elif stage_key == "generator":
            parsed = _pipeline_fake_generator_output(payload)
        elif stage_key == "reviewer":
            parsed = _pipeline_fake_reviewer_output(payload)
        elif stage_key == "solver":
            parsed = _pipeline_fake_solver_output(payload)
        else:  # pragma: no cover
            raise AssertionError(f"unexpected stage: {request.stage}")
        result.parsed = parsed
        return result


def _run_pipeline(runtime: FakePipelineRuntime, seed: int = SEED, tmp_dir: Path | None = None) -> dict[str, Any]:
    pipeline = v02_pipeline.StructureV02Pipeline(runtime=runtime)
    return pipeline.run(seed=seed, output_dir=tmp_dir)


def _reviewer_override_with_correct_judgment(judgment: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _build(reviewer_input: dict[str, Any]) -> dict[str, Any]:
        items = []
        for item in reviewer_input["items"]:
            options = item["candidate_options"]
            judgments = []
            diagnostics = []
            for text in options:
                if text == "confirmed":
                    judgments.append({"option_text": text, "judgment": judgment})
                    if judgment in ("VALID", "MARGINAL"):
                        diagnostics.append({
                            "option_text": text,
                            "natural_wording": True,
                            "serious_defect": False,
                            "observed_clause_count": 2,
                            "candidate_pool_observed_difficulty": "MEDIUM",
                            "difficulty_confidence": "HIGH",
                        })
                else:
                    judgments.append({"option_text": text, "judgment": "INVALID"})
            items.append({
                "item_id": item["item_id"],
                "option_judgments": judgments,
                "candidate_diagnostics": diagnostics,
                "comment": "Reviewer judgment override for the intended correct candidate.",
            })
        return {"items": items}

    return _build


def _reviewer_override_two_valid(reviewer_input: dict[str, Any]) -> dict[str, Any]:
    """Marks both 'confirmed' (intended correct) and 'confirming' (a distractor) VALID."""

    items = []
    for item in reviewer_input["items"]:
        options = item["candidate_options"]
        judgments = []
        diagnostics = []
        for text in options:
            if text in ("confirmed", "confirming"):
                judgments.append({"option_text": text, "judgment": "VALID"})
                diagnostics.append({
                    "option_text": text,
                    "natural_wording": True,
                    "serious_defect": False,
                    "observed_clause_count": 2,
                    "candidate_pool_observed_difficulty": "MEDIUM",
                    "difficulty_confidence": "HIGH",
                })
            else:
                judgments.append({"option_text": text, "judgment": "INVALID"})
        items.append({
            "item_id": item["item_id"],
            "option_judgments": judgments,
            "candidate_diagnostics": diagnostics,
            "comment": "Two grammatically valid options; only one is generator-intended.",
        })
    return {"items": items}


def _solver_override_first_item_wrong(solver_input: dict[str, Any]) -> dict[str, Any]:
    items = []
    for index, item in enumerate(solver_input["items"]):
        options = item["options"]
        correct_letter = next(letter for letter in v01_contracts.LETTERS if options[letter] == "confirmed")
        if index == 0:
            wrong_letter = next(letter for letter in v01_contracts.LETTERS if letter != correct_letter)
            answer_text = options[wrong_letter]
        else:
            answer_text = options[correct_letter]
        items.append({
            "item_id": item["item_id"],
            "answer_text": answer_text,
            "confidence": "HIGH",
            "reason": "The finite past-tense completion is the only acceptable choice.",
        })
    return {"items": items}


def _solver_override_first_item_sentinel(sentinel: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _build(solver_input: dict[str, Any]) -> dict[str, Any]:
        items = []
        for index, item in enumerate(solver_input["items"]):
            options = item["options"]
            correct_letter = next(letter for letter in v01_contracts.LETTERS if options[letter] == "confirmed")
            if index == 0:
                answer_text = sentinel
            else:
                answer_text = options[correct_letter]
            items.append({
                "item_id": item["item_id"],
                "answer_text": answer_text,
                "confidence": "HIGH",
                "reason": "The finite past-tense completion is the only acceptable choice.",
            })
        return {"items": items}

    return _build


def _solver_override_first_item_low_confidence(solver_input: dict[str, Any]) -> dict[str, Any]:
    items = []
    for index, item in enumerate(solver_input["items"]):
        options = item["options"]
        correct_letter = next(letter for letter in v01_contracts.LETTERS if options[letter] == "confirmed")
        confidence = "LOW" if index == 0 else "HIGH"
        items.append({
            "item_id": item["item_id"],
            "answer_text": options[correct_letter],
            "confidence": confidence,
            "reason": "The finite past-tense completion is the only acceptable choice.",
        })
    return {"items": items}


class PipelineCleanRunTests(unittest.TestCase):
    """Commit 7 Section 50: one clean offline run proves the whole approved orchestration."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.runtime = FakePipelineRuntime()
        self.result = _run_pipeline(self.runtime, tmp_dir=self.tmp_dir)

    def test_exactly_three_logical_calls(self) -> None:
        self.assertEqual(len(self.runtime.requests), 3)
        self.assertEqual(
            [request.stage for request in self.runtime.requests],
            [v02_pipeline.GENERATOR_STAGE, v02_pipeline.REVIEWER_STAGE, v02_pipeline.SOLVER_STAGE],
        )
        self.assertEqual(self.result["live_invocation_count"], 3)

    def test_logical_invocation_counts(self) -> None:
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(
            provenance["logical_invocation_counts"], {"generator": 1, "reviewer": 1, "solver": 1}
        )

    def test_candidate_selection_all_pass(self) -> None:
        self.assertEqual(self.result["candidate_selection_pass_count"], 15)
        self.assertEqual(self.result["candidate_selection_failure_count"], 0)

    def test_permutation_distribution(self) -> None:
        self.assertEqual(
            sorted(self.result["final_answer_position_distribution"].values()), [3, 4, 4, 4]
        )

    def test_solver_counters(self) -> None:
        self.assertEqual(self.result["solver_key_agreement_count"], 15)
        self.assertEqual(self.result["solver_ambiguous_none_count"], 0)

    def test_all_items_accepted_and_accept_decision(self) -> None:
        self.assertEqual(len(self.result["item_results"]), 15)
        self.assertTrue(all(item["accepted"] for item in self.result["item_results"]))
        self.assertEqual(self.result["decision"], "ACCEPT")

    def test_eleven_artifacts_non_null(self) -> None:
        for name in (
            "plan.json", "generator_raw.json", "generator_candidates.json", "reviewer_input.json",
            "reviewer.json", "candidate_selection.json", "generator_final.json", "permutation.json",
            "generator.json", "solver_input.json", "solver.json",
        ):
            with self.subTest(name=name):
                value = json.loads((self.tmp_dir / name).read_text(encoding="utf-8"))
                self.assertIsNotNone(value)

    def test_result_and_provenance_schema_valid(self) -> None:
        self.assertEqual(
            [], schema_errors(self.result, load_schema(v02_pipeline.RESULT_SCHEMA_PATH))
        )
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual([], schema_errors(provenance, load_schema(v02_pipeline.PROVENANCE_SCHEMA_PATH)))

    def test_result_and_provenance_artifact_hashes_identical(self) -> None:
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(self.result["artifact_hashes"], provenance["artifact_hashes"])

    def test_all_thirteen_json_files_exist(self) -> None:
        for name in (
            "plan.json", "generator_raw.json", "generator_candidates.json", "reviewer_input.json",
            "reviewer.json", "candidate_selection.json", "generator_final.json", "permutation.json",
            "generator.json", "solver_input.json", "solver.json", "result.json", "provenance.json",
        ):
            with self.subTest(name=name):
                self.assertTrue((self.tmp_dir / name).is_file())


class PipelineGeneratorStopTests(unittest.TestCase):
    """Section 51: Generator contract failure stops the pipeline after one call."""

    def test_generator_contract_failure_quarantines(self) -> None:
        bad_generator = _pipeline_fake_generator_output(v02_planner.build_plan(SEED))
        bad_generator["items"][0]["stem"] = bad_generator["items"][0]["stem"].replace(
            v01_contracts.BLANK_MARKER, ""
        )
        runtime = FakePipelineRuntime(generator=bad_generator)
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(len(runtime.requests), 1)
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertIsNotNone(json.loads((Path(directory) / "generator_raw.json").read_text(encoding="utf-8")))
            for name in (
                "generator_candidates.json", "reviewer_input.json", "reviewer.json", "candidate_selection.json",
                "generator_final.json", "permutation.json", "generator.json", "solver_input.json", "solver.json",
            ):
                self.assertIsNone(json.loads((Path(directory) / name).read_text(encoding="utf-8")))
        self.assertTrue(all(not item["accepted"] for item in result["item_results"]))
        self.assertEqual(result["candidate_selection_pass_count"], 0)
        self.assertEqual(result["candidate_selection_failure_count"], 0)
        for item in result["item_results"]:
            self.assertEqual(item["rejection_reasons"], ["generator_contract_failed"])


class PipelineReviewerContractStopTests(unittest.TestCase):
    """Section 52: a schema-valid but exact-text-contract-invalid Reviewer response stops before Solver."""

    def test_reviewer_contract_failure_quarantines(self) -> None:
        def _bad_reviewer(reviewer_input: dict[str, Any]) -> dict[str, Any]:
            output = _pipeline_fake_reviewer_output(reviewer_input)
            output["items"][0]["option_judgments"][0]["option_text"] = "an invented option text"
            return output

        runtime = FakePipelineRuntime(reviewer=_bad_reviewer)
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(len(runtime.requests), 2)
            self.assertIsNotNone(json.loads((Path(directory) / "reviewer.json").read_text(encoding="utf-8")))
            for name in (
                "candidate_selection.json", "generator_final.json", "permutation.json",
                "generator.json", "solver_input.json", "solver.json",
            ):
                self.assertIsNone(json.loads((Path(directory) / name).read_text(encoding="utf-8")))
        self.assertEqual(result["decision"], "QUARANTINE")
        for item in result["item_results"]:
            self.assertEqual(item["rejection_reasons"], ["reviewer_contract_failed"])


class PipelineCandidateSelectionStopTests(unittest.TestCase):
    """Section 53: exactly one selection slot fails -> whole-set QUARANTINE, Solver never called."""

    def test_selection_failure_quarantines_whole_set(self) -> None:
        runtime = FakePipelineRuntime(reviewer=_reviewer_override_with_correct_judgment("MARGINAL"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(len(runtime.requests), 2)
            candidate_selection = json.loads(
                (Path(directory) / "candidate_selection.json").read_text(encoding="utf-8")
            )
            self.assertIsNotNone(candidate_selection)
            for name in ("generator_final.json", "permutation.json", "generator.json", "solver_input.json", "solver.json"):
                self.assertIsNone(json.loads((Path(directory) / name).read_text(encoding="utf-8")))
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(result["candidate_selection_pass_count"], 0)
        self.assertEqual(result["candidate_selection_failure_count"], 15)
        self.assertTrue(all(not item["accepted"] for item in result["item_results"]))
        for item in result["item_results"]:
            self.assertIn("solver_not_run_due_to_candidate_selection_failure", item["rejection_reasons"])
            self.assertTrue(any(reason.startswith("candidate_selection:") for reason in item["rejection_reasons"]))


class PipelineMultipleValidFilterTests(unittest.TestCase):
    """Section 54: multiple VALID candidates in the seven-pool is not itself a failure."""

    def test_valid_distractor_is_filtered_and_run_still_accepts(self) -> None:
        runtime = FakePipelineRuntime(reviewer=_reviewer_override_two_valid)
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            candidate_selection = json.loads(
                (Path(directory) / "candidate_selection.json").read_text(encoding="utf-8")
            )
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(result["candidate_selection_pass_count"], 15)
        for item in candidate_selection["items"]:
            self.assertIn("d1", item["rejected_valid_candidate_ids"])
            self.assertNotIn("d1", item["selected_candidate_ids"])
            self.assertEqual(3, len(item["selected_candidate_ids"]))


class PipelineIntendedCorrectInvalidMarginalTests(unittest.TestCase):
    """Section 55: intended correct judged INVALID or MARGINAL fails selection, no Solver."""

    def test_intended_correct_invalid(self) -> None:
        runtime = FakePipelineRuntime(reviewer=_reviewer_override_with_correct_judgment("INVALID"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(len(runtime.requests), 2)
        self.assertEqual(result["decision"], "QUARANTINE")

    def test_intended_correct_marginal(self) -> None:
        runtime = FakePipelineRuntime(reviewer=_reviewer_override_with_correct_judgment("MARGINAL"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(len(runtime.requests), 2)
        self.assertEqual(result["decision"], "QUARANTINE")


class PipelineReviewerRuntimeFailureTests(unittest.TestCase):
    """Section 56: a Reviewer runtime failure persists and quarantines without a Solver call."""

    def test_reviewer_runtime_failure(self) -> None:
        runtime = FakePipelineRuntime(reviewer_error=("infrastructure", "simulated Reviewer runtime failure"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertIsNone(json.loads((Path(directory) / "reviewer.json").read_text(encoding="utf-8")))
        self.assertEqual(len(runtime.requests), 2)
        self.assertEqual(result["live_invocation_count"], 2)
        self.assertEqual(len(result["infrastructure"]["runtime_failures"]), 1)
        self.assertEqual(result["decision"], "QUARANTINE")
        for item in result["item_results"]:
            self.assertEqual(
                item["rejection_reasons"],
                [f"runtime_failure:{v02_pipeline.REVIEWER_STAGE}:infrastructure"],
            )


class PipelineSolverRuntimeFailureTests(unittest.TestCase):
    """Section 57: a Solver runtime failure persists and quarantines after Generator/Reviewer succeed."""

    def test_solver_runtime_failure(self) -> None:
        runtime = FakePipelineRuntime(solver_error=("infrastructure", "simulated Solver runtime failure"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertIsNotNone(json.loads((Path(directory) / "generator.json").read_text(encoding="utf-8")))
            self.assertIsNotNone(json.loads((Path(directory) / "solver_input.json").read_text(encoding="utf-8")))
            self.assertIsNone(json.loads((Path(directory) / "solver.json").read_text(encoding="utf-8")))
        self.assertEqual(result["live_invocation_count"], 3)
        self.assertEqual(len(result["infrastructure"]["runtime_failures"]), 1)
        self.assertEqual(result["decision"], "QUARANTINE")


class PipelineSolverDisagreementTests(unittest.TestCase):
    """Section 58: exact-text-valid but key-disagreeing Solver answer rejects only that item."""

    def test_solver_disagreement(self) -> None:
        runtime = FakePipelineRuntime(solver=_solver_override_first_item_wrong)
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(len(runtime.requests), 3)
        self.assertEqual(result["solver_key_agreement_count"], 14)
        self.assertFalse(result["item_results"][0]["accepted"])
        self.assertTrue(all(item["accepted"] for item in result["item_results"][1:]))
        self.assertEqual(result["decision"], "QUARANTINE")


class PipelineSolverAmbiguousTests(unittest.TestCase):
    """Section 59: Solver AMBIGUOUS rejects that item and quarantines the set."""

    def test_solver_ambiguous(self) -> None:
        runtime = FakePipelineRuntime(solver=_solver_override_first_item_sentinel("AMBIGUOUS"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(len(runtime.requests), 3)
        self.assertEqual(result["solver_ambiguous_none_count"], 1)
        self.assertFalse(result["item_results"][0]["accepted"])
        self.assertEqual(result["decision"], "QUARANTINE")


class PipelineSolverNoneTests(unittest.TestCase):
    """Section 60: Solver NONE rejects that item and quarantines the set."""

    def test_solver_none(self) -> None:
        runtime = FakePipelineRuntime(solver=_solver_override_first_item_sentinel("NONE"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(len(runtime.requests), 3)
        self.assertEqual(result["solver_ambiguous_none_count"], 1)
        self.assertFalse(result["item_results"][0]["accepted"])
        self.assertEqual(result["decision"], "QUARANTINE")


class PipelineSolverLowConfidenceTests(unittest.TestCase):
    """Section 61: correct answer but LOW confidence still rejects that item."""

    def test_solver_low_confidence(self) -> None:
        runtime = FakePipelineRuntime(solver=_solver_override_first_item_low_confidence)
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(result["solver_key_agreement_count"], 15)
        self.assertFalse(result["item_results"][0]["accepted"])
        self.assertIn(
            "solver_confidence_not_accepted:LOW", result["item_results"][0]["rejection_reasons"]
        )
        self.assertEqual(result["decision"], "QUARANTINE")


class PipelineReviewerDiagnosticsTests(unittest.TestCase):
    """Section 62: reviewer diagnostics are diagnostic-only and never gate acceptance."""

    def test_diagnostic_variation_does_not_change_decision_or_selection(self) -> None:
        def _reviewer_with_diagnostics(clause_count: int, difficulty: str, confidence: str):
            def _build(reviewer_input: dict[str, Any]) -> dict[str, Any]:
                output = _pipeline_fake_reviewer_output(reviewer_input)
                for item in output["items"]:
                    item["candidate_diagnostics"][0]["observed_clause_count"] = clause_count
                    item["candidate_diagnostics"][0]["candidate_pool_observed_difficulty"] = difficulty
                    item["candidate_diagnostics"][0]["difficulty_confidence"] = confidence
                return output

            return _build

        with tempfile.TemporaryDirectory() as directory_a:
            result_a = _run_pipeline(
                FakePipelineRuntime(reviewer=_reviewer_with_diagnostics(2, "MEDIUM", "HIGH")),
                tmp_dir=Path(directory_a),
            )
        with tempfile.TemporaryDirectory() as directory_b:
            result_b = _run_pipeline(
                FakePipelineRuntime(reviewer=_reviewer_with_diagnostics(5, "HARD", "LOW")),
                tmp_dir=Path(directory_b),
            )

        self.assertEqual(result_a["decision"], result_b["decision"])
        self.assertEqual(result_a["candidate_selection_pass_count"], result_b["candidate_selection_pass_count"])
        self.assertEqual(
            [item["accepted"] for item in result_a["item_results"]],
            [item["accepted"] for item in result_b["item_results"]],
        )
        self.assertNotEqual(
            result_a["checks"]["reviewer_clause_count"], result_b["checks"]["reviewer_clause_count"]
        )
        self.assertNotEqual(
            result_a["checks"]["candidate_pool_difficulty"], result_b["checks"]["candidate_pool_difficulty"]
        )
        self.assertEqual(result_a["checks"]["reviewer_clause_count"]["policy"], "diagnostic_only")
        self.assertEqual(result_a["checks"]["candidate_pool_difficulty"]["planner_comparison"], "disabled")


class PipelineArtifactNullHashTests(unittest.TestCase):
    """Section 63: eleven artifact files always exist; unreachable ones are JSON null."""

    def test_early_stop_artifacts_and_hashes(self) -> None:
        runtime = FakePipelineRuntime(reviewer_error=("infrastructure", "simulated failure"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            names = (
                "plan.json", "generator_raw.json", "generator_candidates.json", "reviewer_input.json",
                "reviewer.json", "candidate_selection.json", "generator_final.json", "permutation.json",
                "generator.json", "solver_input.json", "solver.json",
            )
            for name in names:
                path = Path(directory) / name
                self.assertTrue(path.is_file())
            self.assertEqual(11, len(result["artifact_hashes"]))
            for name in names:
                path = Path(directory) / name
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(canonical_json_sha256(value), result["artifact_hashes"][name])
            self.assertIsNone(
                json.loads((Path(directory) / "candidate_selection.json").read_text(encoding="utf-8"))
            )


class PipelineBlindnessTests(unittest.TestCase):
    """Section 64: Reviewer/Solver requests carry only their allowlisted fields."""

    def test_reviewer_request_is_blind(self) -> None:
        runtime = FakePipelineRuntime()
        with tempfile.TemporaryDirectory() as directory:
            _run_pipeline(runtime, tmp_dir=Path(directory))
        reviewer_request = next(r for r in runtime.requests if r.stage == v02_pipeline.REVIEWER_STAGE)
        payload = json.loads(reviewer_request.prompt.split("INPUT_JSON:\n", 1)[1])
        for item in payload["items"]:
            self.assertEqual({"item_id", "section", "stem", "candidate_options"}, set(item))

    def test_solver_request_is_blind(self) -> None:
        runtime = FakePipelineRuntime()
        with tempfile.TemporaryDirectory() as directory:
            _run_pipeline(runtime, tmp_dir=Path(directory))
        solver_request = next(r for r in runtime.requests if r.stage == v02_pipeline.SOLVER_STAGE)
        payload = json.loads(solver_request.prompt.split("INPUT_JSON:\n", 1)[1])
        for item in payload["items"]:
            self.assertEqual({"item_id", "section", "stem", "options"}, set(item))


class PipelineFormalOutputSchemaTests(unittest.TestCase):
    """Section 65: no schema swapping across stages."""

    def test_schema_paths_per_stage(self) -> None:
        runtime = FakePipelineRuntime()
        with tempfile.TemporaryDirectory() as directory:
            _run_pipeline(runtime, tmp_dir=Path(directory))
        by_stage = {request.stage: request for request in runtime.requests}
        self.assertEqual(
            by_stage[v02_pipeline.GENERATOR_STAGE].formal_output_schema, v02_pipeline.SCHEMA_PATHS["generator"]
        )
        self.assertEqual(
            by_stage[v02_pipeline.REVIEWER_STAGE].formal_output_schema, v02_pipeline.SCHEMA_PATHS["reviewer"]
        )
        self.assertEqual(
            by_stage[v02_pipeline.SOLVER_STAGE].formal_output_schema, v01_contracts.SCHEMA_PATHS["solver"]
        )


class PipelineAgentPromptTests(unittest.TestCase):
    """Section 66: agent_definition paths are the v0.2 prompts."""

    def test_agent_definition_paths(self) -> None:
        runtime = FakePipelineRuntime()
        with tempfile.TemporaryDirectory() as directory:
            _run_pipeline(runtime, tmp_dir=Path(directory))
        by_stage = {request.stage: request for request in runtime.requests}
        self.assertEqual(
            by_stage[v02_pipeline.GENERATOR_STAGE].agent_definition,
            v02_pipeline.AGENT_PATHS[v02_pipeline.GENERATOR_AGENT],
        )
        self.assertEqual(
            by_stage[v02_pipeline.REVIEWER_STAGE].agent_definition,
            v02_pipeline.AGENT_PATHS[v02_pipeline.REVIEWER_AGENT],
        )
        self.assertEqual(
            by_stage[v02_pipeline.SOLVER_STAGE].agent_definition,
            v02_pipeline.AGENT_PATHS[v02_pipeline.SOLVER_AGENT],
        )


class PipelineIsolationTests(unittest.TestCase):
    """Section 67: every successful request isolates its workspace with no tools."""

    def test_all_requests_isolated_with_no_tools(self) -> None:
        runtime = FakePipelineRuntime()
        with tempfile.TemporaryDirectory() as directory:
            _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(len(runtime.requests), 3)
        for request in runtime.requests:
            self.assertTrue(request.isolate_workspace)
            self.assertEqual(request.tools, "")


class PipelineDecisionInvariantTests(unittest.TestCase):
    """Section 68: ACCEPT requires the final canonical Solver check to have run."""

    def test_selection_stop_never_marks_items_accepted(self) -> None:
        runtime = FakePipelineRuntime(reviewer=_reviewer_override_with_correct_judgment("INVALID"))
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertEqual(result["candidate_selection_failure_count"], 15)
        self.assertTrue(all(not item["accepted"] for item in result["item_results"]))
        self.assertNotEqual(result["decision"], "ACCEPT")

    def test_generator_stop_never_marks_items_accepted(self) -> None:
        bad_generator = _pipeline_fake_generator_output(v02_planner.build_plan(SEED))
        bad_generator["items"][0]["stem"] = bad_generator["items"][0]["stem"].replace(
            v01_contracts.BLANK_MARKER, ""
        )
        runtime = FakePipelineRuntime(generator=bad_generator)
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
        self.assertTrue(all(not item["accepted"] for item in result["item_results"]))


class PipelineNoGlobalReviewerAnswerTests(unittest.TestCase):
    """Section 69: the v0.2 pipeline never uses a Reviewer global-answer field."""

    def test_source_does_not_reference_reviewer_global_answer_fields(self) -> None:
        source = (ROOT / "structure" / "v02" / "pipeline.py").read_text(encoding="utf-8")
        for forbidden in ("best_answer_text", "best_answer", "reviewer_solver_agreement"):
            self.assertNotIn(forbidden, source)


class PipelineNoDifficultyAcceptanceTests(unittest.TestCase):
    """Section 70: diagnostics never become acceptance/rejection gates."""

    def test_source_does_not_gate_on_diagnostic_fields(self) -> None:
        source = (ROOT / "structure" / "v02" / "pipeline.py").read_text(encoding="utf-8")
        for forbidden in (
            "reviewer_difficulty_mismatch",
            "reviewer_difficulty_confidence_low",
            "clause_count_mismatch",
        ):
            self.assertNotIn(forbidden, source)


class PipelineNoRetryRepairTests(unittest.TestCase):
    """Section 71: no repair, revision, regeneration, or retry stage exists."""

    def test_no_repair_revision_regeneration_stage_or_agent_defined(self) -> None:
        source = (ROOT / "structure" / "v02" / "pipeline.py").read_text(encoding="utf-8")
        for forbidden in (
            "REPAIR_AGENT", "REVISION_AGENT", "REGENERATION_AGENT", "RETRY_AGENT",
            "_repair_stage", "_revision_stage", "_regeneration_stage", "_retry_stage",
            "repair_agent", "revision_agent",
        ):
            self.assertNotIn(forbidden, source)

    def test_invoke_called_exactly_three_times_in_source(self) -> None:
        # Structural guarantee that no loop/branch can call runtime.invoke a
        # fourth time for the same or a new stage: self._invoke(...) is only
        # ever written three times in the module source.
        source = (ROOT / "structure" / "v02" / "pipeline.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("self._invoke("), 3)

    def test_each_logical_stage_invoked_at_most_once_on_a_clean_run(self) -> None:
        runtime = FakePipelineRuntime()
        with tempfile.TemporaryDirectory() as directory:
            _run_pipeline(runtime, tmp_dir=Path(directory))
        stages = [request.stage for request in runtime.requests]
        self.assertEqual(sorted(stages), sorted(set(stages)))
        self.assertEqual(len(stages), 3)


if __name__ == "__main__":
    unittest.main()
