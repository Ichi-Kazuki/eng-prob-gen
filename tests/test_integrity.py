from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis" / "we_v2_validation"))

from integrity import derive_correct_answer, mutation_location  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
