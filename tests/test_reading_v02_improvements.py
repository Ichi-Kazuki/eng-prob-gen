"""Targeted regression tests for the Reading v0.2 structural improvements."""

from __future__ import annotations

import copy
import json
import random
import unittest
from collections import Counter
from pathlib import Path

from reading.contracts import (
    DISTRACTOR_CATEGORIES,
    DISTRACTOR_METADATA_CORRECT,
    blind_input,
    blind_input_errors,
    deterministic_diagnostics,
    validate_generator_contract,
)
from reading.diagnostics import diagnostics_for_result
from reading.planner import (
    ALLOWED_DOMAINS,
    EMPIRICAL_PASSAGE_COMPOSITIONS,
    QUESTION_TYPES,
    adapt_question_type_counts,
    build_plan_v02,
)
from shared.schema_validation import load_schema, schema_errors

from tests.test_reading_v02_batch import quota_plan, variable_generator_fixture


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "analysis" / "reading_v0_2_empirical_profile.json"


def distractor_metadata(correct_answer: str) -> dict[str, dict[str, str]]:
    return {
        label: {
            "category": DISTRACTOR_METADATA_CORRECT if label == correct_answer else DISTRACTOR_CATEGORIES[0],
            "rationale": "The keyed choice is supported." if label == correct_answer else "It is text-related but does not answer the stem.",
        }
        for label in ("A", "B", "C", "D")
    }


class ReadingPlannerImprovementTests(unittest.TestCase):
    def test_legacy_calibration_is_explicitly_deprecated(self) -> None:
        calibration = json.loads((ROOT / "reading" / "calibration.json").read_text(encoding="utf-8"))
        self.assertEqual(calibration["status"], "deprecated")
        self.assertEqual(calibration["superseded_by"], "analysis/reading_v0_2_empirical_profile.json")

    def test_empirical_composition_rows_are_loaded_and_adapted(self) -> None:
        source = next(observation for observation in EMPIRICAL_PASSAGE_COMPOSITIONS if observation.question_count == 7)
        adapted = adapt_question_type_counts(source.counts(), 14, random.Random(99))
        self.assertEqual(sum(adapted.values()), 14)
        self.assertLessEqual(adapted["MAIN_IDEA"], 1)
        self.assertEqual(set(adapted), set(QUESTION_TYPES))

        overfull_main_idea = {
            "DETAIL": 5,
            "VOCABULARY_IN_CONTEXT": 3,
            "INFERENCE": 2,
            "MAIN_IDEA": 3,
            "REFERENCE": 1,
        }
        guarded = adapt_question_type_counts(overfull_main_idea, 14, random.Random(100))
        self.assertEqual(sum(guarded.values()), 14)
        self.assertEqual(guarded["MAIN_IDEA"], 1)

    def test_seed_reproducibility_and_exact_plan_totals(self) -> None:
        first = build_plan_v02(20260829)
        self.assertEqual(first, build_plan_v02(20260829))
        self.assertEqual(sum(first["question_type_counts"].values()), first["question_count"])
        self.assertEqual(Counter(first["question_plan"]), Counter(first["question_type_counts"]))
        self.assertIn(first["target_words"], {
            observation.target_words for observation in EMPIRICAL_PASSAGE_COMPOSITIONS
        })

    def test_expanded_domains_are_supported_by_planner(self) -> None:
        for domain in ALLOWED_DOMAINS:
            with self.subTest(domain=domain):
                plan = build_plan_v02(8000 + ALLOWED_DOMAINS.index(domain), domain=domain)
                self.assertEqual(plan["domain"], domain)

    def test_large_batch_preserves_type_and_question_count_profiles(self) -> None:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        expected_shares = profile["derived_profile"]["question_type_share"]
        expected_q_counts = {
            int(count): frequency / profile["measurement_scope"]["passages_measured"]
            for count, frequency in profile["derived_profile"]["questions_per_passage"]["frequency"].items()
        }
        plans = [build_plan_v02(seed) for seed in range(5000)]
        type_counts = Counter()
        question_counts = Counter()
        main_counts = Counter()
        length_counts = Counter()
        for plan in plans:
            type_counts.update(plan["question_type_counts"])
            question_counts[plan["question_count"]] += 1
            main_counts[plan["question_type_counts"]["MAIN_IDEA"]] += 1
            length_counts[plan["target_words"]] += 1
            self.assertLessEqual(plan["question_type_counts"]["MAIN_IDEA"], 1)
        total = sum(type_counts.values())
        for question_type, expected in expected_shares.items():
            self.assertAlmostEqual(type_counts[question_type] / total, expected, delta=0.03)
        for question_count, expected in expected_q_counts.items():
            self.assertAlmostEqual(question_counts[question_count] / len(plans), expected, delta=0.03)
        self.assertGreater(main_counts[0], 0)
        self.assertGreater(main_counts[1], 0)
        self.assertEqual(max(main_counts), 1)
        self.assertAlmostEqual(sum(plan["question_count"] for plan in plans) / len(plans), 10.0, delta=0.15)
        expected_lengths = Counter(
            observation.target_words for observation in EMPIRICAL_PASSAGE_COMPOSITIONS
        )
        for target_words, frequency in expected_lengths.items():
            self.assertAlmostEqual(length_counts[target_words] / len(plans), frequency / 20, delta=0.05)


class ReadingTaxonomyAndDistractorTests(unittest.TestCase):
    def test_secondary_subtypes_and_rhetorical_purpose_are_accepted(self) -> None:
        plan = quota_plan(8100, {
            "DETAIL": 0,
            "VOCABULARY_IN_CONTEXT": 0,
            "INFERENCE": 7,
            "MAIN_IDEA": 0,
            "REFERENCE": 0,
        })
        generator = variable_generator_fixture(plan)
        generator["questions"][0]["subtype"] = "RHETORICAL_PURPOSE"
        generator["questions"][0]["distractor_metadata"] = distractor_metadata(
            generator["questions"][0]["correct_answer"]
        )
        self.assertEqual(validate_generator_contract(generator, plan), [])
        self.assertEqual(
            schema_errors(
                generator,
                load_schema(ROOT / "reading" / "schemas" / "reading_generator_output_v0_2.schema.json"),
            ),
            [],
        )

    def test_invalid_primary_type_and_incompatible_subtype_are_rejected(self) -> None:
        plan = build_plan_v02(8101)
        generator = variable_generator_fixture(plan)
        generator["questions"][0]["question_type"] = "RHETORICAL_PURPOSE"
        self.assertTrue(validate_generator_contract(generator, plan))

        generator = variable_generator_fixture(plan)
        generator["questions"][0]["subtype"] = "LOCAL_INFERENCE"
        if generator["questions"][0]["question_type"] == "INFERENCE":
            generator["questions"][0]["subtype"] = "ANTECEDENT_REFERENCE"
        self.assertTrue(validate_generator_contract(generator, plan))

    def test_distractor_metadata_must_match_the_key_and_known_categories(self) -> None:
        plan = build_plan_v02(8102)
        generator = variable_generator_fixture(plan)
        question = generator["questions"][0]
        question["distractor_metadata"] = distractor_metadata(question["correct_answer"])
        self.assertEqual(validate_generator_contract(generator, plan), [])

        malformed = copy.deepcopy(generator)
        malformed["questions"][0]["distractor_metadata"][malformed["questions"][0]["correct_answer"]]["category"] = "WRONG_REFERENT"
        self.assertTrue(validate_generator_contract(malformed, plan))

        malformed = copy.deepcopy(generator)
        malformed["questions"][0]["distractor_metadata"]["A"]["category"] = "NOT_A_REAL_MECHANISM"
        self.assertTrue(validate_generator_contract(malformed, plan))

    def test_distractor_metadata_and_subtypes_never_enter_blind_inputs(self) -> None:
        plan = build_plan_v02(8103)
        generator = variable_generator_fixture(plan)
        for question in generator["questions"]:
            question["subtype"] = {
                "DETAIL": "DIRECT_FACTUAL_DETAIL",
                "VOCABULARY_IN_CONTEXT": "VOCABULARY_CONTEXT_MEANING",
                "INFERENCE": "LOCAL_INFERENCE",
                "MAIN_IDEA": "PASSAGE_MAIN_IDEA",
                "REFERENCE": "ANTECEDENT_REFERENCE",
            }[question["question_type"]]
            question["distractor_metadata"] = distractor_metadata(question["correct_answer"])
        blind = blind_input(generator, schema_version="reading-blind-input-v0.2")
        serialized = json.dumps(blind)
        self.assertNotIn("distractor_metadata", serialized)
        self.assertNotIn("RHETORICAL_PURPOSE", serialized)
        self.assertEqual(
            blind_input_errors(generator, blind, schema_version="reading-blind-input-v0.2"),
            [],
        )

    def test_surface_choice_diagnostics_flag_suspicious_patterns_without_hard_failure(self) -> None:
        plan = build_plan_v02(8104)
        generator = variable_generator_fixture(plan)
        question = generator["questions"][0]
        answer = question["correct_answer"]
        question["choices"][answer] = "This unusually long answer contains substantially more information than every other choice in the item and should be flagged."
        report = deterministic_diagnostics(generator, plan)
        self.assertTrue(any("CHOICE_LENGTH_OUTLIER" in warning for warning in report["choice_quality_warnings"]))
        self.assertEqual(report["hard_failures"], [])
        result_report = diagnostics_for_result({"plan": plan, "generator": generator, "checks": {}})
        self.assertTrue(result_report["choice_quality_warnings"])


if __name__ == "__main__":
    unittest.main()
