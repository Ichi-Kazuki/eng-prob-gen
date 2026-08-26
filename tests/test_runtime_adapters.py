"""Contract tests for the provider-neutral live runtime layer."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.adapters import (
    ClaudeRuntime,
    CodexRuntime,
    InvocationRequest,
    RuntimeInvocationError,
)


ROOT = Path(__file__).resolve().parents[1]
SOLVER_SCHEMA = ROOT / "agents" / "toefl_itp_grammar_solver" / "schema" / "solver_output.schema.json"
SOLVER_AGENT = ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md"


def request(tmp: Path, *, stage: str = "solver", sandbox: str = "read-only") -> InvocationRequest:
    return InvocationRequest(
        stage=stage,
        agent_name="toefl-itp-grammar-solver",
        agent_definition=SOLVER_AGENT,
        prompt='BLINDED INPUT: {"item_id":"mock-001","section":"Written Expression","sentence":"The report was completed yesterday.","marked_parts":{"A":"The","B":"report","C":"was completed","D":"yesterday"}}',
        input_keys=("item_id", "section", "sentence", "marked_parts"),
        formal_output_schema=SOLVER_SCHEMA,
        system_directive="Return only the final JSON object.",
        sandbox=sandbox,  # type: ignore[arg-type]
        cwd=ROOT,
        artifact_dir=tmp,
        isolate_workspace=True,
        timeout_seconds=5,
    )


class RuntimeAdapterTests(unittest.TestCase):
    def test_codex_uses_ephemeral_exec_schema_last_message_and_read_only(self) -> None:
        calls: list[tuple[list[str], dict]] = []

        def runner(command: list[str], **kwargs):
            calls.append((command, kwargs))
            if "--output-last-message" in command:
                output = Path(command[command.index("--output-last-message") + 1])
                output.write_text(json.dumps({
                    "item_id": "mock-001",
                    "section": "Written Expression",
                    "solver_answer": "A",
                    "confidence": "HIGH",
                    "reason": "mock contract output",
                    "ambiguity_detected": False,
                    "suggested_correction": "The report was completed yesterday.",
                }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="diagnostic stdout", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = CodexRuntime(executable="codex", model="mock-model", runner=runner, cli_version="codex-cli 0.0-test")
            result = runtime.invoke(request(Path(directory)))
            self.assertTrue(result.output_last_message_path and result.output_last_message_path.exists())

        command, kwargs = calls[0]
        self.assertEqual(command[0:2], ["codex", "exec"])
        self.assertIn("--ephemeral", command)
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("--output-schema", command)
        transport_path = Path(command[command.index("--output-schema") + 1])
        self.assertTrue(result.transport_schema_path and result.transport_schema_path.exists())
        self.assertNotEqual(transport_path.resolve(), SOLVER_SCHEMA.resolve())
        transport = json.loads(result.transport_schema_path.read_text(encoding="utf-8"))
        self.assertNotIn("allOf", json.dumps(transport))
        self.assertEqual(transport_path.name, result.transport_schema_path.name)
        self.assertTrue(
            result.transport_schema_provenance_path
            and result.transport_schema_provenance_path.exists()
        )
        self.assertEqual(
            result.transport_schema_provenance["canonical_schema_path"],
            str(SOLVER_SCHEMA),
        )
        self.assertIn("--output-last-message", command)
        self.assertEqual(command[-1], "-")
        self.assertEqual(kwargs["input"].split("AUTHORITATIVE AGENT INSTRUCTIONS", 1)[0], "")
        self.assertIn(SOLVER_AGENT.read_text(encoding="utf-8"), kwargs["input"])
        self.assertNotEqual(result.raw_output, result.parsed)
        self.assertEqual(result.parsed["solver_answer"], "A")

    def test_each_codex_call_has_a_distinct_ephemeral_output_path(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], **kwargs):
            calls.append(command)
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = CodexRuntime(executable="codex", runner=runner, cli_version="mock")
            runtime.invoke(request(Path(directory)))
            runtime.invoke(request(Path(directory)))

        paths = [command[command.index("--output-last-message") + 1] for command in calls]
        self.assertEqual(len(paths), 2)
        self.assertNotEqual(paths[0], paths[1])
        for command in calls:
            self.assertIn("--ephemeral", command)
            self.assertNotIn("resume", command)

    def test_codex_cli_failure_is_infrastructure_and_preserves_raw_artifacts(self) -> None:
        def runner(command: list[str], **kwargs):
            return subprocess.CompletedProcess(command, 429, stdout="", stderr="usage limit exceeded")

        with tempfile.TemporaryDirectory() as directory:
            runtime = CodexRuntime(executable="codex", runner=runner, cli_version="mock")
            with self.assertRaises(RuntimeInvocationError) as raised:
                runtime.invoke(request(Path(directory)))
            error = raised.exception
            self.assertTrue(error.result.raw_stdout_path and error.result.raw_stdout_path.exists())
            self.assertTrue(error.result.raw_stderr_path and error.result.raw_stderr_path.exists())

        self.assertEqual(error.category, "infrastructure")
        self.assertEqual(error.result.exit_code, 429)

    def test_claude_retains_named_agent_and_json_envelope_behavior(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], **kwargs):
            calls.append(command)
            envelope = {"result": json.dumps({
                "item_id": "mock-001",
                "section": "Written Expression",
                "solver_answer": "A",
                "confidence": "HIGH",
                "reason": "mock contract output",
                "ambiguity_detected": False,
                "suggested_correction": "The report was completed yesterday.",
            })}
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(envelope), stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = ClaudeRuntime(executable="claude", model="sonnet", runner=runner, cli_version="Claude Code mock")
            result = runtime.invoke(request(Path(directory), sandbox=None))  # type: ignore[arg-type]

        command = calls[0]
        self.assertEqual(command[0], "claude")
        self.assertIn("--agent", command)
        self.assertIn("--no-session-persistence", command)
        self.assertIn("--json-schema", command)
        self.assertNotIn("exec", command)
        self.assertEqual(result.parsed["item_id"], "mock-001")

        claude_schema = json.loads(command[command.index("--json-schema") + 1])
        self.assertIn("allOf", claude_schema)

    def test_live_harness_uses_existing_solver_validate_contract(self) -> None:
        harness_path = ROOT / "analysis" / "we_v2_1_2_live_e2e" / "run_live_e2e.py"
        spec = importlib.util.spec_from_file_location("we_live_harness_contract_test", harness_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        valid_solver = {
            "item_id": "contract-001",
            "section": "Written Expression",
            "solver_answer": "A",
            "confidence": "HIGH",
            "reason": "The candidate is grammatical only with A.",
            "ambiguity_detected": False,
            "suggested_correction": "The report was completed yesterday.",
        }
        ok, errors = harness.validate_existing_contract(
            valid_solver,
            "agents/toefl_itp_grammar_solver/scripts/validate_output.py",
            "solver",
        )
        self.assertTrue(ok, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
