"""Offline regression coverage for Reading v0.2.11 Candidate Verifier parity."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from reading.cli import CURRENT_READING_VERSION
from reading.pipeline import READING_CURRENT_VERSION, ReadingV02Pipeline
from reading.planner import build_plan_v02
from tests.test_reading_v028_inference_gate import GateRuntime


ROOT = Path(__file__).resolve().parents[1]


class ReadingV0211CandidateVerifierTests(unittest.TestCase):
    def test_current_reading_version_is_v0211(self) -> None:
        self.assertEqual(READING_CURRENT_VERSION, "v0.2.12")
        self.assertEqual(CURRENT_READING_VERSION, "v0.2.12")

    def test_agent_instruction_has_one_proposition_direct_restatement_precedence(self) -> None:
        instruction = (ROOT / ".claude" / "agents" / "toefl-itp-reading-candidate-verifier-v0.2.md").read_text(
            encoding="utf-8"
        )
        instruction = " ".join(instruction.split())
        self.assertIn(
            "A candidate is INVALID_DIRECT_RESTATEMENT if ONE passage proposition alone directly supports the selected answer.",
            instruction,
        )
        self.assertIn("INVALID_DIRECT_RESTATEMENT", instruction)
        self.assertIn("explicitly stated answer", instruction)
        self.assertIn("ordinary synonym substitution", instruction)
        self.assertIn("close paraphrase", instruction)
        self.assertIn("reformulation of one sentence or one proposition", instruction)

    def test_agent_instruction_does_not_rescue_direct_restatement_and_preserves_shallow(self) -> None:
        instruction = (ROOT / ".claude" / "agents" / "toefl-itp-reading-candidate-verifier-v0.2.md").read_text(
            encoding="utf-8"
        )
        instruction = " ".join(instruction.split())
        self.assertIn("Do not rescue a direct restatement merely because another related passage", instruction)
        self.assertIn("VALID_SHALLOW_INFERENCE remains valid when no single passage proposition alone", instruction)
        self.assertIn("combining or extending multiple passage propositions", instruction)

    def test_runtime_prompt_contains_the_same_semantic_rule(self) -> None:
        runtime = GateRuntime(build_plan_v02(2890, domain="biology"), initial_verifier_status="INVALID_UNSUPPORTED")
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(runtime).run(
                runtime.plan["seed"], domain="biology", output_dir=Path(directory)
            )
        self.assertEqual(result["decision"], "ACCEPT")
        request = next(request for request in runtime.requests if request.stage == "reading_inference_candidate_verifier")
        prompt = request.prompt
        self.assertIn("ONE passage proposition alone directly supports the selected answer", prompt)
        self.assertIn("classify INVALID_DIRECT_RESTATEMENT", prompt)
        self.assertIn("do not rescue it by citing another related proposition", prompt)
        self.assertIn("VALID_SHALLOW_INFERENCE remains valid when multiple propositions are needed", prompt)
        self.assertIn("cross-paragraph evidence is not required", prompt)

    def test_candidate_verifier_schemas_retain_v02_contract(self) -> None:
        input_schema = json.loads(
            (ROOT / "reading" / "schemas" / "reading_inference_candidate_verifier_input_v0_2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        output_schema = json.loads(
            (ROOT / "reading" / "schemas" / "reading_inference_candidate_verifier_output_v0_2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(input_schema["$id"], "https://example.invalid/reading-inference-candidate-verifier-input-v0.2.schema.json")
        self.assertEqual(output_schema["$id"], "https://example.invalid/reading-inference-candidate-verifier-output-v0.2.schema.json")
        self.assertEqual(output_schema["properties"]["schema_version"]["const"], "reading-inference-candidate-verifier-v0.2")
        self.assertEqual(input_schema["required"], ["passage_id", "section", "passage", "candidates"])
        self.assertEqual(output_schema["required"], ["schema_version", "passage_id", "section", "candidates"])
        self.assertNotIn("v0.2.11", json.dumps(input_schema))
        self.assertNotIn("v0.2.11", json.dumps(output_schema))


if __name__ == "__main__":
    unittest.main()
