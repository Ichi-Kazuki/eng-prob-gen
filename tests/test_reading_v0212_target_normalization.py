"""Offline regression coverage for Reading v0.2.12 target locations."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from reading.cli import CURRENT_READING_VERSION
from reading.contracts import display_lines, normalize_target_line_metadata
from reading.pipeline import READING_CURRENT_VERSION, reading_v02_generator_instruction


ROOT = Path(__file__).resolve().parents[1]


class ReadingV0212TargetNormalizationTests(unittest.TestCase):
    passage = (
        "That first occurrence is deliberately placed before the anchored example so the target has multiple locations.\n\n"
        "Mineral films form smooth barriers, but some surfaces that water cannot readily enter remain dry longer."
    )

    def _output(
        self,
        *,
        question_type: str = "REFERENCE",
        target_text: str = "that",
        target_line: Any = 2,
        anchor: str = "surfaces that water cannot readily enter",
        paragraph: Any = 2,
    ) -> dict[str, Any]:
        stem_ending = "is closest in meaning to" if question_type == "VOCABULARY_IN_CONTEXT" else "refers to"
        question = {
            "item_id": "reading-v02.12-q1",
            "question_type": question_type,
            "subtype": "VOCABULARY_CONTEXT_MEANING" if question_type == "VOCABULARY_IN_CONTEXT" else "ANTECEDENT_REFERENCE",
            "stem": f"The word '{target_text}' in line {target_line} {stem_ending}",
            "choices": {"A": "one", "B": "two", "C": "three", "D": "four"},
            "correct_answer": "B",
            "distractor_metadata": {
                "A": {"category": "WRONG_REFERENT", "rationale": "A is not the intended option."},
                "B": {"category": "CORRECT_OPTION", "rationale": "B is the keyed option."},
                "C": {"category": "SCOPE_SHIFT", "rationale": "C changes the scope."},
                "D": {"category": "NEARBY_DETAIL_CONFUSION", "rationale": "D is a nearby detail."},
            },
            "target_text": target_text,
            "target_line": target_line,
            "evidence": {
                "paragraph": paragraph,
                "anchor": anchor,
                "rationale": "The anchor supplies the local evidence.",
            },
        }
        return {
            "schema_version": "reading-generator-v0.2",
            "passage": self.passage,
            "questions": [question],
        }

    def _record(self, audit: dict[str, Any]) -> dict[str, Any]:
        return audit["questions"][0]

    def test_current_reading_version_is_v0212(self) -> None:
        self.assertEqual(READING_CURRENT_VERSION, "v0.2.12")
        self.assertEqual(CURRENT_READING_VERSION, "v0.2.12")

    def test_supplied_correct_target_line_remains_unchanged(self) -> None:
        output = self._output(target_line=3)
        before = copy.deepcopy(output)
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, before)
        self.assertEqual(self._record(audit)["target_line_resolution"], "SUPPLIED_LINE_MATCH")

    def test_incorrect_line_with_one_global_match_preserves_existing_normalization(self) -> None:
        output = self._output(target_text="barriers", target_line=2, anchor="smooth barriers")
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized["questions"][0]["target_line"], 3)
        self.assertEqual(self._record(audit)["target_line_resolution"], "UNIQUE_SURFACE_MATCH")

    def test_unique_anchor_resolves_multiple_global_matches_for_both_target_types(self) -> None:
        for question_type in ("VOCABULARY_IN_CONTEXT", "REFERENCE"):
            with self.subTest(question_type=question_type):
                output = self._output(question_type=question_type)
                normalized, audit = normalize_target_line_metadata(output)
                question = normalized["questions"][0]
                self.assertEqual(question["target_line"], 3)
                self.assertEqual(self._record(audit)["target_line_resolution"], "EVIDENCE_ANCHOR_SURFACE_MATCH")

    def test_anchor_derived_line_rewrites_only_the_existing_safe_stem_number(self) -> None:
        output = self._output(question_type="VOCABULARY_IN_CONTEXT")
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized["questions"][0]["stem"], "The word 'that' in line 3 is closest in meaning to")
        self.assertTrue(self._record(audit)["stem_line_normalized"])

    def test_anchor_missing_target_fails_closed(self) -> None:
        output = self._output(anchor="Mineral films form smooth barriers")
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, output)
        self.assertEqual(self._record(audit)["target_line_resolution"], "MULTIPLE_SURFACE_MATCH")

    def test_target_occurring_more_than_once_inside_anchor_fails_closed(self) -> None:
        output = self._output(
            anchor="surfaces that water cannot readily enter and other surfaces that water cannot readily enter",
        )
        output["passage"] = (
            "That first occurrence is deliberately placed before the anchored example so the target has multiple locations.\n\n"
            "Mineral films form smooth barriers, but some surfaces that water cannot readily enter and other surfaces that "
            "water cannot readily enter remain dry longer."
        )
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, output)
        self.assertEqual(self._record(audit)["target_line_resolution"], "MULTIPLE_SURFACE_MATCH")

    def test_anchor_occurring_more_than_once_in_declared_paragraph_fails_closed(self) -> None:
        output = self._output()
        output["passage"] = (
            "That first occurrence is deliberately placed before the anchored example so the target has multiple locations.\n\n"
            "Mineral films form smooth barriers, but some surfaces that water cannot readily enter remain dry longer; other "
            "surfaces that water cannot readily enter remain wet."
        )
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, output)
        self.assertEqual(self._record(audit)["target_line_resolution"], "MULTIPLE_SURFACE_MATCH")

    def test_invalid_evidence_paragraph_fails_closed(self) -> None:
        for invalid_paragraph in (0, 3, True, "2"):
            with self.subTest(invalid_paragraph=invalid_paragraph):
                output = self._output(paragraph=invalid_paragraph)
                normalized, audit = normalize_target_line_metadata(output)
                self.assertEqual(normalized, output)
                self.assertEqual(self._record(audit)["target_line_resolution"], "MULTIPLE_SURFACE_MATCH")

    def test_zero_global_target_matches_does_not_attempt_anchor_resolution(self) -> None:
        output = self._output(target_text="unseen", anchor="surfaces that water cannot readily enter")
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, output)
        self.assertEqual(self._record(audit)["target_line_resolution"], "ZERO_SURFACE_MATCH")

    def test_multiple_matches_in_paragraph_alone_are_not_sufficient(self) -> None:
        output = self._output(anchor="Mineral films form smooth barriers")
        output["passage"] = (
            "That first occurrence is deliberately placed before the anchored example so the target has multiple locations.\n\n"
            "Mineral films form smooth barriers, but some surfaces that water cannot readily enter remain dry longer; another "
            "barrier has that effect as well."
        )
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, output)
        self.assertEqual(self._record(audit)["target_line_resolution"], "MULTIPLE_SURFACE_MATCH")

    def test_no_nearest_or_first_match_fallback_exists(self) -> None:
        output = self._output(anchor="surfaces that water cannot readily enter")
        output["passage"] = (
            "That first occurrence is deliberately placed before the anchored example so the target has multiple locations.\n\n"
            "Mineral films form smooth barriers, but some surfaces that water cannot readily enter remain dry longer; some "
            "surfaces that water cannot readily enter remain wet."
        )
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, output)
        self.assertEqual(self._record(audit)["target_line_resolution"], "MULTIPLE_SURFACE_MATCH")

    def test_no_fuzzy_target_matching_is_introduced(self) -> None:
        output = self._output(target_text="ater", anchor="surfaces that water cannot readily enter")
        normalized, audit = normalize_target_line_metadata(output)
        self.assertEqual(normalized, output)
        self.assertEqual(self._record(audit)["target_line_resolution"], "ZERO_SURFACE_MATCH")

    def test_normalization_does_not_modify_semantic_fields(self) -> None:
        output = self._output()
        before = copy.deepcopy(output["questions"][0])
        normalized, _audit = normalize_target_line_metadata(output)
        after = normalized["questions"][0]
        for field in (
            "target_text",
            "choices",
            "correct_answer",
            "distractor_metadata",
            "evidence",
            "question_type",
            "subtype",
        ):
            self.assertEqual(after[field], before[field], field)

    def test_generator_reference_guidance_requires_real_target_anchor_and_referent(self) -> None:
        agent = (ROOT / ".claude" / "agents" / "toefl-itp-reading-generator-v0.2.md").read_text(encoding="utf-8")
        prompt = reading_v02_generator_instruction()
        for instruction in (agent, prompt):
            flattened = " ".join(instruction.split())
            self.assertIn("exact expression", flattened)
            self.assertIn("appears in the passage", flattened)
            self.assertIn("evidence.anchor", flattened)
            self.assertIn("containing the actual target occurrence", flattened)
            self.assertIn("actual antecedent or referent", flattened)
            self.assertIn("Do not invent a pronoun", flattened)
            self.assertIn("merely because it would make a convenient question", flattened)
            self.assertIn("same surface pronoun occurs multiple", flattened)

    def test_generator_reference_guidance_preserves_allowed_reference_behavior(self) -> None:
        instruction = " ".join(reading_v02_generator_instruction().split())
        self.assertIn("do not need to be globally unique", instruction)
        self.assertIn("common pronouns are allowed", instruction)
        self.assertIn("do not force cross-sentence reference", instruction)
        self.assertIn("official-style line-based wording", instruction)

    def test_audit_is_json_serializable_and_records_distinct_resolution(self) -> None:
        output = self._output()
        _normalized, audit = normalize_target_line_metadata(output)
        json.dumps(audit)
        self.assertEqual(self._record(audit)["target_line_resolution"], "EVIDENCE_ANCHOR_SURFACE_MATCH")
        self.assertEqual(self._record(audit)["matched_display_lines"], [1, 3])
        self.assertEqual(display_lines(self.passage)[2], "Mineral films form smooth barriers, but some surfaces that water cannot")


if __name__ == "__main__":
    unittest.main()
