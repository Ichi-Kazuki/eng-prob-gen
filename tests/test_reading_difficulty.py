"""Regression tests for the provisional Reading difficulty layer."""

from __future__ import annotations

import unittest

from reading.difficulty import estimate_difficulty_alignment, plan_difficulty_profile
from reading.planner import build_plan_v02


class ReadingDifficultyTests(unittest.TestCase):
    def test_planner_emits_difficulty_profile(self) -> None:
        plan = build_plan_v02(12345)
        profile = plan["difficulty_profile"]
        self.assertEqual(profile["target_band"], "ITP_STYLE_STANDARD")
        self.assertEqual(profile["calibration_status"], "PROVISIONAL_STRUCTURAL_PROXY")
        self.assertFalse(profile["psychometric_equivalence"])
        self.assertEqual(
            set(profile["dimensions"]),
            {
                "lexical",
                "syntactic",
                "paraphrase",
                "evidence_distance",
                "inference_depth",
                "distractor_competitiveness",
            },
        )

    def test_estimator_never_claims_score_equivalence(self) -> None:
        report = estimate_difficulty_alignment(
            {"difficulty_profile": plan_difficulty_profile()},
            {"passage": "Plants store energy. Researchers compare several sites.", "questions": []},
        )
        self.assertFalse(report["psychometric_equivalence"])
        self.assertIn(report["status"], {"PASS", "WARN"})


if __name__ == "__main__":
    unittest.main()
