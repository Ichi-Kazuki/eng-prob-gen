"""Unit and regression coverage for the WE v2.1 format-only policy."""

from __future__ import annotations

import json
import random
import statistics
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PLANNER_DIR = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"
sys.path.insert(0, str(PLANNER_DIR))

from format_planner import (  # noqa: E402
    CorrectSpanPlan,
    FormatPlan,
    SentenceLengthPlan,
    enumerate_candidate_spans,
    empirical_probabilities,
    get_official_profile,
    pre_emission_checks,
    sample_correct_span_plan,
    sample_sentence_length_plan,
    select_span_set,
    SpanSelectionError,
)


class WeV21FormatPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = get_official_profile()

    def test_official_empirical_source_counts_are_derived(self) -> None:
        self.assertEqual(self.profile["counts"]["correct_span_type"], {
            "SINGLE_WORD": 98,
            "SHORT_PHRASE": 12,
            "CLAUSE_OR_CLAUSE_LIKE": 15,
        })
        self.assertEqual(self.profile["counts"]["correct_answer"], {"A": 24, "B": 37, "C": 31, "D": 33})
        self.assertEqual(sum(self.profile["counts"]["sentence_word_count"].values()), 125)
        probabilities = empirical_probabilities(self.profile["counts"]["correct_span_type"])
        self.assertAlmostEqual(probabilities["SINGLE_WORD"], 98 / 125)
        self.assertAlmostEqual(probabilities["SHORT_PHRASE"], 12 / 125)

    def test_sentence_sampling_is_distribution_aware_not_fixed_to_13_or_20(self) -> None:
        rng = random.Random(2101)
        plans = [sample_sentence_length_plan(rng, self.profile) for _ in range(1250)]
        targets = [plan.target for plan in plans]
        self.assertEqual(statistics.median(targets), 20)
        self.assertGreater(len(set(targets)), 8)
        self.assertNotEqual(set(targets), {13})
        self.assertLess(sum(target < 15 for target in targets) / len(targets), 0.20)
        self.assertGreater(sum(target >= 25 for target in targets), 0)
        self.assertTrue(all(plan.lower <= plan.target <= plan.upper for plan in plans))

    def test_correct_span_sampling_makes_single_word_primary(self) -> None:
        rng = random.Random(2090)
        sampled = [sample_correct_span_plan(rng, self.profile).span_type for _ in range(2000)]
        self.assertGreater(sampled.count("SINGLE_WORD"), sampled.count("SHORT_PHRASE"))
        self.assertGreater(sampled.count("SINGLE_WORD"), sampled.count("CLAUSE_OR_CLAUSE_LIKE"))
        self.assertTrue(all(plan.target_word_count <= 4 for plan in [sample_correct_span_plan(rng, self.profile) for _ in range(200)]))

    def test_normal_candidates_exclude_five_plus_words(self) -> None:
        sentence = "The regional archive preserves detailed records that researchers compare with satellite observations during annual field studies across several coastal provinces."
        candidates = enumerate_candidate_spans(sentence)
        self.assertTrue(candidates)
        self.assertLessEqual(max(candidate.word_count for candidate in candidates), 4)

    def test_selection_searches_whole_sentence_and_avoids_zero_gap_clustering(self) -> None:
        sentence = (
            "The regional archive preserves detailed records that researchers compare "
            "with satellite observations during annual field studies across several coastal provinces."
        )
        plan = FormatPlan(
            sentence=SentenceLengthPlan(target=20, lower=18, upper=22),
            correct_span=CorrectSpanPlan("SINGLE_WORD", 1),
            gap_targets={"gap_A_B": 4, "gap_B_C": 4, "gap_C_D": 4},
            distractor_word_counts=(1, 1, 1),
            answer_position="C",
        )
        selection = select_span_set(sentence, "compare", plan, random.Random(12), self.profile)
        starts = [span.start for span in selection.spans]
        self.assertEqual(selection.candidate_scope, "whole_sentence")
        self.assertEqual(len(selection.spans), 4)
        self.assertTrue(any(start < starts[selection.correct_index] for start in starts))
        self.assertTrue(any(start > starts[selection.correct_index] for start in starts))
        self.assertTrue(all(gap >= 1 for gap in selection.gaps))
        self.assertNotIn(0, selection.gaps)
        self.assertEqual(selection.spans[selection.correct_index].text, "compare")
        self.assertTrue(all(span.word_count <= 4 for span in selection.spans))

    def test_pre_emission_checks_reject_plan_drift_before_output(self) -> None:
        sentence = "Researchers carefully compare archived records with satellite observations during annual field studies across coastal provinces."
        plan = FormatPlan(
            sentence=SentenceLengthPlan(target=15, lower=14, upper=16),
            correct_span=CorrectSpanPlan("SINGLE_WORD", 1),
            gap_targets={"gap_A_B": 4, "gap_B_C": 4, "gap_C_D": 4},
            distractor_word_counts=(1, 1, 1),
            answer_position="B",
        )
        selection = select_span_set(sentence, "compare", plan, random.Random(8), self.profile)
        result = pre_emission_checks(sentence, selection.spans, plan, selection.spans[selection.correct_index])
        self.assertTrue(result["valid"], result)

        drifted = FormatPlan(
            sentence=SentenceLengthPlan(target=10, lower=8, upper=12),
            correct_span=plan.correct_span,
            gap_targets=plan.gap_targets,
            distractor_word_counts=plan.distractor_word_counts,
            answer_position=plan.answer_position,
        )
        failed = pre_emission_checks(sentence, selection.spans, drifted, selection.spans[selection.correct_index])
        self.assertFalse(failed["valid"])
        self.assertTrue(any("outside planned range" in error for error in failed["errors"]))

    def test_grammar_span_type_override_is_normal_and_authoritative(self) -> None:
        sentence = "Researchers carefully compare archived records with satellite observations during annual field studies across coastal provinces."
        plan = FormatPlan(
            sentence=SentenceLengthPlan(target=15, lower=14, upper=16),
            correct_span=CorrectSpanPlan("CLAUSE_OR_CLAUSE_LIKE", 2),
            gap_targets={"gap_A_B": 4, "gap_B_C": 4, "gap_C_D": 4},
            distractor_word_counts=(1, 1, 1),
            answer_position="B",
        )
        selection = select_span_set(sentence, "compare", plan, random.Random(8), self.profile)
        anchor = selection.spans[selection.correct_index]
        self.assertEqual(anchor.text, "compare")
        self.assertEqual(anchor.span_type, "SINGLE_WORD")

        result = pre_emission_checks(sentence, selection.spans, plan, anchor)
        self.assertTrue(result["valid"], result)
        self.assertTrue(any("grammar locus retained" in warning for warning in result["warnings"]))

        strict = pre_emission_checks(
            sentence,
            selection.spans,
            plan,
            anchor,
            grammar_type_override=False,
        )
        self.assertFalse(strict["valid"])
        self.assertTrue(any("does not match sampled plan" in error for error in strict["errors"]))

    def test_justified_long_correct_span_has_an_explicit_exception_path(self) -> None:
        sentence = (
            "The committee determined that the revised procedure would reduce contamination "
            "during extended laboratory testing across facilities."
        )
        plan = FormatPlan(
            sentence=SentenceLengthPlan(target=16, lower=1, upper=30),
            correct_span=CorrectSpanPlan("SINGLE_WORD", 1),
            gap_targets={"gap_A_B": 3, "gap_B_C": 3, "gap_C_D": 3},
            distractor_word_counts=(1, 1, 1),
            answer_position="B",
        )
        correct_text = "the revised procedure would reduce contamination"
        with self.assertRaises(SpanSelectionError):
            select_span_set(sentence, correct_text, plan, random.Random(4), self.profile)

        rationale = "The grammar decision requires the complete verb-object locus."
        selection = select_span_set(
            sentence,
            correct_text,
            plan,
            random.Random(4),
            self.profile,
            long_span_rationale=rationale,
        )
        anchor = selection.spans[selection.correct_index]
        self.assertGreater(anchor.word_count, 4)
        self.assertTrue(all(span.word_count <= 4 for span in selection.spans if span != anchor))

        result = pre_emission_checks(
            sentence,
            selection.spans,
            plan,
            anchor,
            long_span_rationale=rationale,
        )
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["exceptions"]["long_span_rationale"], rationale)

        rejected = pre_emission_checks(sentence, selection.spans, plan, anchor)
        self.assertFalse(rejected["valid"])
        self.assertTrue(any("long_span_rationale" in error for error in rejected["errors"]))

    def test_v21_prompt_and_changelog_preserve_scope_boundary(self) -> None:
        prompt = (ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md").read_text(encoding="utf-8")
        changelog = (ROOT / "agents" / "toefl_itp_we_generator_v2" / "CHANGELOG.md").read_text(encoding="utf-8")
        for text in (prompt, changelog):
            self.assertIn("grammar generation logic unchanged, format planner + span-selection policy only", text)
        self.assertIn("candidate spans", prompt)
        self.assertIn("5+ word span", prompt)
        self.assertIn("zero-gap", prompt)
        self.assertIn("v2.1", prompt)

    def test_schema_accepts_historical_v20_and_current_v21_version_literals(self) -> None:
        schema = json.loads((ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json").read_text(encoding="utf-8"))
        version_schema = schema["properties"]["agent_version"]
        provenance_schema = schema["properties"]["provenance"]["properties"]["agent_version"]
        self.assertEqual(set(version_schema["enum"]), {
            "Written Expression Generator v2.0",
            "Written Expression Generator v2.1",
        })
        self.assertEqual(version_schema, provenance_schema)

        validator = Draft202012Validator(schema)
        for top_level, provenance in (
            ("Written Expression Generator v2.0", "Written Expression Generator v2.1"),
            ("Written Expression Generator v2.1", "Written Expression Generator v2.0"),
        ):
            errors = list(validator.iter_errors({
                "agent_version": top_level,
                "provenance": {"agent_version": provenance},
            }))
            self.assertTrue(
                any(
                    error.validator == "const"
                    and list(error.absolute_path) == ["provenance", "agent_version"]
                    for error in errors
                ),
                f"version mismatch unexpectedly passed: {top_level!r} / {provenance!r}",
            )


if __name__ == "__main__":
    unittest.main()
