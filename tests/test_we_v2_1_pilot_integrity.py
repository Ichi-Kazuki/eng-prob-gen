"""Regression coverage for the WE v2.1.1-compatible pilot mutation audit."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "analysis" / "we_v2_1_pilot" / "build_pilot_artifacts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("we_v2_1_pilot_builder", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WeV21PilotIntegrityTests(unittest.TestCase):
    def test_word_order_mutation_checks_clean_and_error_loci(self) -> None:
        module = load_module()
        item = {
            "sentence": "The quickly team works in Europe.",
            "marked_parts": {"A": "The", "B": "quickly team", "C": "works", "D": "Europe"},
            "correct_answer": "B",
            "grammar_metadata": {"intended_error_position": "B"},
            "qa_metadata": {
                "clean_form": "The team quickly works in Europe.",
                "error_form": "The quickly team works in Europe.",
                "clean_sentence_validated": True,
            },
        }

        result = module.integrity_check(item)

        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["reordered_surface_edit"])
        self.assertTrue(result["clean_locus_accounted_for"])
        self.assertTrue(result["error_locus_accounted_for"])
        self.assertEqual(result["changed_clean_token_indices"], [2])
        self.assertEqual(result["changed_error_token_indices"], [1])
        self.assertEqual(result["clean_locus_token_indices"], [1, 2])

    def test_unrelated_clean_side_change_fails_even_when_error_side_is_marked(self) -> None:
        module = load_module()
        item = {
            "sentence": "The team works slowly in Europe.",
            "marked_parts": {"A": "The", "B": "team", "C": "works", "D": "slowly"},
            "correct_answer": "B",
            "grammar_metadata": {"intended_error_position": "B"},
            "qa_metadata": {
                "clean_form": "The team works quickly in Europe.",
                "error_form": "The team works slowly in Europe.",
                "clean_sentence_validated": True,
            },
        }

        result = module.integrity_check(item)

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["clean_locus_accounted_for"])


if __name__ == "__main__":
    unittest.main()
