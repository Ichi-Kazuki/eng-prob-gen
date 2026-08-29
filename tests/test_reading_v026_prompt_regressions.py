"""Prompt-only regressions for the Reading v0.2.6 inference refinement."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from reading.pipeline import READING_INFERENCE_GUIDANCE


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_AGENT = ROOT / ".claude" / "agents" / "toefl-itp-reading-generator-v0.2.md"


def normalized_guidance() -> str:
    return " ".join(READING_INFERENCE_GUIDANCE.split())


def normalized_generator_agent() -> str:
    return " ".join(GENERATOR_AGENT.read_text(encoding="utf-8").split())


class ReadingV026InferencePromptRegressionTests(unittest.TestCase):
    def test_direct_sentence_restatement_is_explicitly_disallowed(self) -> None:
        guidance = normalized_guidance()

        self.assertIn("keyed answer must not be explicitly stated in the passage", guidance)
        self.assertIn(
            "must not be obtainable merely by replacing words in one passage sentence with synonyms or a close paraphrase",
            guidance,
        )
        self.assertIn("ordinary synonym substitution", guidance)
        self.assertIn("rewrite the inference item rather than labeling the paraphrase as INFERENCE", guidance)

    def test_local_genuine_inference_remains_allowed(self) -> None:
        guidance = normalized_guidance()

        self.assertIn("at least one reasoning step from the passage", guidance)
        self.assertIn("Local inference is allowed", guidance)
        self.assertIn("one sentence or adjacent sentences support a genuinely unstated implication", guidance)

    def test_cross_idea_inference_remains_allowed_without_being_required(self) -> None:
        guidance = normalized_guidance()

        self.assertIn("Cross-idea inference is allowed", guidance)
        self.assertIn("separated or multiple passage ideas naturally support the conclusion", guidance)
        self.assertIn("Do not manufacture unnecessary multi-sentence complexity or force cross-idea reasoning", guidance)

    def test_unsupported_or_ambiguous_inference_remains_disallowed(self) -> None:
        guidance = normalized_guidance()

        self.assertIn("fully supported", guidance)
        self.assertIn("fully entailed by the text", guidance)
        self.assertIn("uniquely answerable", guidance)
        self.assertIn("conservative", guidance)
        self.assertIn("free of outside knowledge", guidance)
        self.assertIn("unsupported or ambiguous inference is worse than a shallow inference", guidance)

    def test_no_percentage_or_inference_depth_quota_was_added(self) -> None:
        guidance = normalized_guidance().casefold()

        for forbidden in (
            "%",
            "percentage",
            "fixed quota",
            "fixed percentage",
            "fixed number of inference",
            "at least two sentences",
            "must use multiple sentences",
            "must use multiple paragraphs",
            "every inference must combine",
        ):
            self.assertNotIn(forbidden, guidance)
        self.assertNotRegex(guidance, re.compile(r"\bquota\b"))

    def test_shared_guidance_is_synchronized_with_v026_generator_agent(self) -> None:
        agent = normalized_generator_agent()

        self.assertIn("version: v0.2.6", agent)
        self.assertIn(normalized_guidance(), agent)


if __name__ == "__main__":
    unittest.main()
