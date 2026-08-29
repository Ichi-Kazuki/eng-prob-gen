"""Prompt-only regressions for the Reading v0.2.7 inference refinement."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from reading.pipeline import READING_INFERENCE_GUIDANCE, READING_REVIEWER_INFERENCE_GUIDANCE


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_AGENT = ROOT / ".claude" / "agents" / "toefl-itp-reading-generator-v0.2.md"


def normalized_guidance() -> str:
    return " ".join(READING_INFERENCE_GUIDANCE.split())


def normalized_generator_agent() -> str:
    return " ".join(GENERATOR_AGENT.read_text(encoding="utf-8").split())


class ReadingV027InferencePromptRegressionTests(unittest.TestCase):
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
        self.assertIn("provided that the support contains two distinct textual propositions", guidance)
        self.assertIn("Two adjacent textual propositions can support a valid local inference", guidance)

    def test_inference_requires_two_propositions_and_keys_the_conclusion(self) -> None:
        guidance = normalized_guidance()

        self.assertIn("Fact A, Fact B, and an unstated conclusion", guidance)
        self.assertIn("Fact A and Fact B must be two distinct textual propositions", guidance)
        self.assertIn("same paragraph", guidance)
        self.assertIn("adjacent sentences", guidance)
        self.assertIn("separated sentences or ideas", guidance)
        self.assertIn("final keyed option must express the unstated conclusion, not Fact A or Fact B themselves", guidance)
        self.assertIn("private rationale must identify both facts and demonstrate why both facts are needed", guidance)
        self.assertIn("one single passage proposition is sufficient to obtain the answer", guidance)
        self.assertIn("rationale cannot identify at least two distinct textual facts that jointly support the answer", guidance)
        self.assertIn("Keep these labels internal", guidance)

    def test_cross_idea_inference_remains_allowed_without_being_required(self) -> None:
        guidance = normalized_guidance()

        self.assertIn("Cross-idea inference is allowed", guidance)
        self.assertIn("separated or multiple passage ideas naturally support the conclusion", guidance)
        self.assertIn("Cross-paragraph evidence is allowed when naturally supported, but it is not required", guidance)
        self.assertIn("neither are multiple paragraphs, distant evidence, or cross-idea reasoning", guidance)
        self.assertIn("do not set a target mix of local, cross-idea, or cross-paragraph items", guidance)
        self.assertIn("Do not manufacture unnecessary multi-sentence complexity or force cross-idea reasoning", guidance)

    def test_unsupported_or_ambiguous_inference_remains_disallowed(self) -> None:
        guidance = normalized_guidance()

        self.assertIn("fully supported", guidance)
        self.assertIn("fully entailed by the text", guidance)
        self.assertIn("uniquely answerable", guidance)
        self.assertIn("conservative", guidance)
        self.assertIn("free of outside knowledge", guidance)
        self.assertIn("unsupported or ambiguous inference is worse than a shallow inference", guidance)

    def test_reviewer_uses_the_same_two_proposition_validity_rule(self) -> None:
        reviewer_guidance = " ".join(READING_REVIEWER_INFERENCE_GUIDANCE.split())
        reviewer_agent = " ".join(
            (ROOT / ".claude" / "agents" / "toefl-itp-reading-reviewer-v0.2.md")
            .read_text(encoding="utf-8")
            .split()
        )

        self.assertIn("For INFERENCE items only", reviewer_guidance)
        self.assertIn("serious defect", reviewer_guidance)
        self.assertIn("directly stated or paraphrased from one passage sentence", reviewer_guidance)
        self.assertIn("one textual proposition alone fully supports the keyed answer", reviewer_guidance)
        self.assertIn("at least two distinct textual propositions to derive an unstated conclusion", reviewer_guidance)
        self.assertIn("Local evidence may be adjacent within one paragraph", reviewer_guidance)
        self.assertIn("cross-idea and cross-paragraph evidence are allowed when supported but are not required", reviewer_guidance)
        self.assertIn("Do not apply this criterion to other question types", reviewer_guidance)
        self.assertIn(reviewer_guidance, reviewer_agent)

    def test_structural_rule_is_scoped_to_inference_guidance(self) -> None:
        from reading import pipeline

        for name in (
            "READING_DIFFICULTY_GUIDANCE",
            "READING_LENGTH_GUIDANCE",
            "READING_PARAGRAPH_GUIDANCE",
            "READING_VOCABULARY_GUIDANCE",
            "READING_TARGET_GUIDANCE",
            "READING_CHOICE_GUIDANCE",
            "READING_TAXONOMY_GUIDANCE",
            "READING_DISTRACTOR_GUIDANCE",
            "READING_DOMAIN_GUIDANCE",
        ):
            guidance = getattr(pipeline, name)
            self.assertNotIn("Fact A", guidance, name)
            self.assertNotIn("two distinct textual propositions", guidance, name)

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

    def test_shared_guidance_is_synchronized_with_v027_generator_agent(self) -> None:
        agent = normalized_generator_agent()

        self.assertIn("version: v0.2.7", agent)
        self.assertIn(normalized_guidance(), agent)


if __name__ == "__main__":
    unittest.main()
