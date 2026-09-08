"""Offline regressions for the WE v2.1.4 Generator-instruction clarity patch.

Pilot-006 (`we-pilots/we-batch-pilot-006`) surfaced three Generator-side
failure modes. These tests prove, against the real checked-in Production
validator helper (`mutation_safety.audit_mutation` / `_metadata_audit`), that:

1. the reported reversed `mutation_type` direction (item -010) is rejected and
   the paired opposite direction (`clean_form -> error_form`) is accepted;
2. the reported item -003 `error_explanation` is rejected under the current,
   unchanged validator, while a same-content, tighter-worded explanation is
   accepted -- this is a phrasing fix, not a claim that the original grammar
   judgment was wrong;
3. the item -010/-003/-009 sentences and the WE v2.1.4 Generator instruction
   file itself carry the new explicit guidance this patch adds.

No Production validator, Reviewer, Solver, or Orchestrator behavior is
exercised for correctness beyond calling the existing, unmodified helper.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))

from mutation_safety import audit_mutation  # noqa: E402


GENERATOR_AGENT_PATH = ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md"
GENERATOR_AGENTS_MD_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "AGENTS.md"

# Recorded from the pilot-006 diagnostic run (we-pilots/we-batch-pilot-006),
# item we-v2.1.3-live-T052544Z-010.
ITEM_010_CLEAN = (
    "The curator consulted the renowned astronomer, to whom the archive had "
    "entrusted its most valuable observational records."
)
ITEM_010_ERROR = (
    "The curator consulted the renowned astronomer, to who the archive had "
    "entrusted its most valuable observational records."
)

# Recorded from the pilot-006 diagnostic run, item
# we-v2.1.3-live-T052544Z-003.
ITEM_003_CLEAN = (
    "The historian to whom the research team sent its findings carefully "
    "reviewed the maps before approving the final report."
)
ITEM_003_ERROR = (
    "The historian to who the research team sent its findings carefully "
    "reviewed the maps before approving the final report."
)
ITEM_003_ORIGINAL_EXPLANATION = (
    'The relative pronoun follows the preposition "to" and must therefore be '
    'in the objective form "whom."'
)
ITEM_003_TIGHTENED_EXPLANATION = 'The preposition "to" requires "whom," not "who."'


class MutationDirectionPairingTests(unittest.TestCase):
    """Item -010: mutation_type and minimal_correction must be opposite pairs."""

    def test_reversed_mutation_type_direction_is_rejected(self) -> None:
        result = audit_mutation(
            clean_form=ITEM_010_CLEAN,
            error_form=ITEM_010_ERROR,
            mutation_type="who -> whom",
            minimal_correction="who -> whom",
            answer_explanation=ITEM_003_TIGHTENED_EXPLANATION,
            tested_error_type="incorrect_relative_marker",
            primary_target="RELATIVE_CLAUSES",
        )
        self.assertEqual(result.status, "REJECT")
        joined = " ".join(result.reasons)
        self.assertIn("mutation_type source does not match the clean_form token diff", joined)
        self.assertIn("mutation_type target does not match the error_form token diff", joined)

    def test_paired_opposite_direction_passes(self) -> None:
        result = audit_mutation(
            clean_form=ITEM_010_CLEAN,
            error_form=ITEM_010_ERROR,
            mutation_type="whom -> who",
            minimal_correction="who -> whom",
            answer_explanation=ITEM_003_TIGHTENED_EXPLANATION,
            tested_error_type="incorrect_relative_marker",
            primary_target="RELATIVE_CLAUSES",
        )
        self.assertEqual(result.status, "PASS", result.reasons)
        self.assertEqual(result.reasons, [])


class ExplanationClarityTests(unittest.TestCase):
    """Item -003: the grammar reason was correct; the wording was too diffuse."""

    def test_original_pilot_006_explanation_is_rejected_under_current_validator(self) -> None:
        result = audit_mutation(
            clean_form=ITEM_003_CLEAN,
            error_form=ITEM_003_ERROR,
            mutation_type="whom -> who",
            minimal_correction="who -> whom",
            answer_explanation=ITEM_003_ORIGINAL_EXPLANATION,
            tested_error_type="incorrect_relative_marker",
            primary_target="RELATIVE_CLAUSES",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn(
            "answer_explanation does not describe the clean -> error direction",
            result.reasons,
        )

    def test_tightened_same_content_explanation_passes(self) -> None:
        result = audit_mutation(
            clean_form=ITEM_003_CLEAN,
            error_form=ITEM_003_ERROR,
            mutation_type="whom -> who",
            minimal_correction="who -> whom",
            answer_explanation=ITEM_003_TIGHTENED_EXPLANATION,
            tested_error_type="incorrect_relative_marker",
            primary_target="RELATIVE_CLAUSES",
        )
        self.assertEqual(result.status, "PASS", result.reasons)
        self.assertEqual(result.reasons, [])


class GeneratorInstructionContentTests(unittest.TestCase):
    """The v2.1.4 patch text is present in the authoritative instruction files."""

    def test_generator_agent_file_documents_direction_pairing_and_alternate_parse(self) -> None:
        text = GENERATOR_AGENT_PATH.read_text(encoding="utf-8")
        self.assertIn("v2.1.4", text)
        self.assertIn("clean_form -> error_form", text)
        self.assertIn("error_form -> clean_form", text)
        self.assertIn("in that", text)
        self.assertIn("in which", text)
        # Preexisting v2.1.1/v2.1.2/v2.1.3 scope-lock text must survive.
        self.assertIn(
            "grammar generation logic unchanged, format planner + span-selection policy only",
            text,
        )

    def test_generator_agents_md_documents_v2_1_4_scope_boundary(self) -> None:
        text = GENERATOR_AGENTS_MD_PATH.read_text(encoding="utf-8")
        self.assertIn("v2.1.4", text)
        self.assertIn("mutation_safety.py", text)
        self.assertIn("unchanged", text)


if __name__ == "__main__":
    unittest.main()
