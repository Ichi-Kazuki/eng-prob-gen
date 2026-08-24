from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis" / "we_v2_validation"))

from integrity import derive_correct_answer, mutation_location  # noqa: E402
from run_integrity_reaudit import (  # noqa: E402
    ITEMS_PATH,
    _ordered_count_text,
    audit_items,
    classify_old_metrics,
    read_json,
)


class IntegrityTests(unittest.TestCase):
    MARKED_PARTS = {
        "A": "The",
        "B": "scientist",
        "C": "approve",
        "D": "the proposal",
    }

    def test_single_marked_mutation_is_valid(self) -> None:
        clean = "The scientist approved the proposal yesterday."
        error = "The scientist approve the proposal yesterday."

        location = mutation_location(clean, error, self.MARKED_PARTS)

        self.assertTrue(location["valid_single_marked_location"])
        self.assertEqual(location["labels"], ["C"])
        self.assertEqual(derive_correct_answer(clean, error, self.MARKED_PARTS), "C")

    def test_unmarked_mutation_invalidates_single_marked_location(self) -> None:
        clean = "The scientist approved the proposal yesterday."
        error = "The scientist approve the proposal today."

        location = mutation_location(clean, error, self.MARKED_PARTS)

        self.assertEqual(location["labels"], ["C"])
        self.assertFalse(location["valid_single_marked_location"])
        self.assertTrue(any(not operation["affected_labels"] for operation in location["operations"]))
        with self.assertRaises(ValueError):
            derive_correct_answer(clean, error, self.MARKED_PARTS)

    def test_non_token_mutation_outside_marked_location_is_invalid(self) -> None:
        clean = "The scientist approved the proposal yesterday."
        error = "The scientist, approve the proposal yesterday."

        location = mutation_location(clean, error, self.MARKED_PARTS)

        self.assertEqual(location["labels"], ["C"])
        self.assertFalse(location["valid_single_marked_location"])
        self.assertTrue(any(operation["error_non_token_units"] for operation in location["operations"]))

    def test_deletion_before_marked_span_is_not_attributed_to_next_span(self) -> None:
        parts = {
            "A": "The",
            "B": "scientist",
            "C": "approved",
            "D": "proposal",
        }
        clean = "The scientist approved the proposal."
        error = "The scientist approved proposal."

        location = mutation_location(clean, error, parts)

        self.assertEqual(location["labels"], [])
        self.assertFalse(location["valid_single_marked_location"])
        with self.assertRaises(ValueError):
            derive_correct_answer(clean, error, parts)

    def test_deletion_at_end_of_final_marked_span_is_attributed_to_that_span(self) -> None:
        parts = {
            "A": "The",
            "B": "scientist",
            "C": "approved",
            "D": "the",
        }
        clean = "The scientist approved the proposal."
        error = "The scientist approved the."

        location = mutation_location(clean, error, parts)

        self.assertTrue(location["valid_single_marked_location"])
        self.assertEqual(location["labels"], ["D"])
        self.assertEqual(derive_correct_answer(clean, error, parts), "D")

    def test_deletion_before_marked_span_is_attributed_to_that_span(self) -> None:
        """A missing determiner or auxiliary belongs to the span it precedes.

        The previous token is unmarked here, which is the normal shape of this
        item type; refusing attribution would leave a well-formed item without
        a derivable key.
        """

        parts = {
            "A": "museum",
            "B": "unusually detailed map",
            "C": "coastal trade",
            "D": "routes",
        }
        clean = "The museum recently acquired an unusually detailed map of the coastal trade routes."
        error = "The museum recently acquired unusually detailed map of the coastal trade routes."

        location = mutation_location(clean, error, parts)

        self.assertTrue(location["valid_single_marked_location"])
        self.assertEqual(location["labels"], ["B"])
        self.assertEqual(derive_correct_answer(clean, error, parts), "B")

    def test_deletion_between_two_different_marked_spans_is_ambiguous(self) -> None:
        parts = {
            "A": "The",
            "B": "scientist",
            "C": "approved",
            "D": "proposal",
        }
        clean = "The scientist approved the proposal."
        error = "The scientist approved proposal."

        location = mutation_location(clean, error, parts)

        self.assertEqual(location["labels"], [])
        self.assertFalse(location["valid_single_marked_location"])
        with self.assertRaises(ValueError):
            derive_correct_answer(clean, error, parts)

    def test_spacing_change_merged_with_marked_mutation_is_invalid(self) -> None:
        """An extra space rides along in the same opcode as the replacement.

        The spacing mutation sits outside the marked span, so the operation
        must not be reported as a single valid marked location.
        """

        clean = "The scientist approved the proposal yesterday."
        error = "The scientist   approve the proposal yesterday."

        location = mutation_location(clean, error, self.MARKED_PARTS)

        self.assertFalse(location["valid_single_marked_location"])
        with self.assertRaises(ValueError):
            derive_correct_answer(clean, error, self.MARKED_PARTS)

    def test_ordinary_single_space_separator_stays_valid(self) -> None:
        clean = "The scientist approved the proposal yesterday."
        error = "The scientist approve the proposal yesterday."

        location = mutation_location(clean, error, self.MARKED_PARTS)

        self.assertTrue(location["valid_single_marked_location"])
        self.assertEqual(derive_correct_answer(clean, error, self.MARKED_PARTS), "C")

    def test_gate_i_cohort_keeps_items_whose_key_is_not_derivable(self) -> None:
        """Geometry does not depend on the answer key.

        An undecidable item must still contribute to the Gate I medians and
        band share, otherwise the gate judges a smaller cohort than the source.
        """

        items = read_json(ITEMS_PATH)["items"]
        broken = copy.deepcopy(items)
        # Make one item's key underivable without touching its geometry.
        broken[0]["qa_metadata"]["clean_form"] = broken[0]["sentence"]

        _, _, corrected_items, geometry_items = audit_items(broken)

        self.assertLess(len(corrected_items), len(broken))
        self.assertEqual(len(geometry_items), len(broken))

    def test_unclassified_spans_are_reported_not_dropped(self) -> None:
        text = _ordered_count_text(
            {"SINGLE_WORD": 21, "SHORT_PHRASE": 40, "CLAUSE_OR_CLAUSE_LIKE": 9, "UNRESOLVED": 5},
            ("SINGLE_WORD", "SHORT_PHRASE", "CLAUSE_OR_CLAUSE_LIKE"),
        )

        self.assertIn("5 UNRESOLVED", text)

    def test_old_conclusion_reports_previous_run_not_current_cohort(self) -> None:
        summary = {
            "item_count": 4,
            "diagnostics_integrity": {
                "complete": 3,
                "consistent_as_stored": 2,
                "consistent_after_deterministic_rekey": 4,
            },
            "answer_key_integrity": {"declared_vs_actual_mismatch": 1},
            "mutation_validity": {"valid": 3},
            "correct_span_distribution": {
                "declared": {"SINGLE_WORD": 1, "SHORT_PHRASE": 2, "CLAUSE_OR_CLAUSE_LIKE": 1},
                "recomputed": {"SINGLE_WORD": 2, "SHORT_PHRASE": 1, "CLAUSE_OR_CLAUSE_LIKE": 1},
            },
        }
        old_metrics = {
            "core_metrics": {
                "initial_generated": 4,
                "generator_schema_pass": 4,
                "diagnostics_complete": 4,
                "diagnostics_consistent": 4,
            },
            "defect_monitoring": {"wrong_answer_key": {"initial": 0}},
            "geometry_gate": {"pass": True, "actual": {"worst_band_classification": {}}},
        }

        by_metric = {
            row["metric"]: row
            for row in classify_old_metrics(
                summary,
                {"reason": "not evaluated"},
                {"all_required_pass": True},
                {"pass": False, "actual": {"worst_band_classification": {"EXTREME": 4}}},
                old_metrics,
            )
        }

        # The old run claimed zero wrong keys; the re-audit found one.  The
        # row must show the contradiction rather than echo the new number.
        self.assertEqual(by_metric["answer-key integrity"]["old_conclusion"], "0 wrong keys")
        self.assertEqual(by_metric["diagnostics consistency"]["old_conclusion"], "4/4")
        self.assertEqual(by_metric["format geometry"]["old_conclusion"], "Gate I PASS")
        self.assertIn("Gate I is FAIL", by_metric["format geometry"]["basis"])

    def test_metric_dispositions_use_current_cohort_values(self) -> None:
        summary = {
            "item_count": 4,
            "diagnostics_integrity": {
                "complete": 3,
                "consistent_as_stored": 2,
                "consistent_after_deterministic_rekey": 4,
            },
            "answer_key_integrity": {
                "declared_vs_actual_mismatch": 1,
            },
            "mutation_validity": {"valid": 3},
            "correct_span_distribution": {
                "declared": {
                    "SINGLE_WORD": 1,
                    "SHORT_PHRASE": 2,
                    "CLAUSE_OR_CLAUSE_LIKE": 1,
                },
                "recomputed": {
                    "SINGLE_WORD": 2,
                    "SHORT_PHRASE": 1,
                    "CLAUSE_OR_CLAUSE_LIKE": 1,
                },
            },
        }
        geometry = {
            "pass": True,
            "actual": {
                "worst_band_classification": {
                    "PREFERRED": 1,
                    "WARNING": 2,
                    "EXTREME": 1,
                },
            },
        }

        dispositions = classify_old_metrics(
            summary,
            {"reason": "not evaluated"},
            {"all_required_pass": True},
            geometry,
        )
        by_metric = {row["metric"]: row for row in dispositions}

        self.assertEqual(
            by_metric["format bands"]["basis"],
            "Current corrected-cohort worst-band distribution is 1 EXTREME / 2 WARNING / 1 PREFERRED.",
        )
        self.assertIn("current recomputed distribution is 2 / 1 / 1", by_metric["correct-span distribution"]["basis"])
        self.assertIn("3/4", by_metric["mutation validity"]["basis"])
        self.assertIn("Gate I is PASS", by_metric["format geometry"]["basis"])
        self.assertEqual(by_metric["format drift conclusion"]["status"], "INVALID")


if __name__ == "__main__":
    unittest.main()
