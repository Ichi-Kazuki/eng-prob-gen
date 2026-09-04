"""Offline schema and freeze tests for the Structure v0.2 foundation scaffolding.

This commit adds only namespace scaffolding and schemas under structure/v02/.
No v0.2 orchestration, prompts, or behavioral code exist yet, so these tests
only exercise schema loading/validation and protect the frozen v0.1 files.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from structure.permutation import permute_generator_output

from shared.schema_validation import load_schema, schema_errors
from structure.v02 import blinding as v02_blinding
from structure.v02 import contracts as v02_contracts
from structure.v02 import selection as v02_selection


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


if __name__ == "__main__":
    unittest.main()
