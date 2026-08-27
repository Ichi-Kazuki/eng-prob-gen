"""Contract tests for the provider-neutral live runtime layer."""

from __future__ import annotations

import copy
import json
import importlib.util
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from runtime.adapters import (
    ClaudeRuntime,
    CodexRuntime,
    InvocationRequest,
    RuntimeInvocationError,
)
from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parents[1]
SOLVER_SCHEMA = ROOT / "agents" / "toefl_itp_grammar_solver" / "schema" / "solver_output.schema.json"
REVIEWER_SCHEMA = ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "schema" / "reviewer_output_v2.schema.json"
SOLVER_AGENT = ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md"


def request(tmp: Path, *, stage: str = "solver", sandbox: str = "read-only", schema: Path = SOLVER_SCHEMA) -> InvocationRequest:
    return InvocationRequest(
        stage=stage,
        agent_name="toefl-itp-grammar-solver",
        agent_definition=SOLVER_AGENT,
        prompt='BLINDED INPUT: {"item_id":"mock-001","section":"Written Expression","sentence":"The report was completed yesterday.","marked_parts":{"A":"The","B":"report","C":"was completed","D":"yesterday"}}',
        input_keys=("item_id", "section", "sentence", "marked_parts"),
        formal_output_schema=schema,
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
            self.assertTrue(result.transport_schema_path and result.transport_schema_path.exists())
            self.assertTrue(result.workspace_path)
            self.assertFalse(result.workspace_path.exists())
            transport = json.loads(result.transport_schema_path.read_text(encoding="utf-8"))
            self.assertNotIn("allOf", json.dumps(transport))
            self.assertTrue(
                result.transport_schema_provenance_path
                and result.transport_schema_provenance_path.exists()
            )
            self.assertEqual(
                result.transport_schema_provenance["canonical_schema_path"],
                str(SOLVER_SCHEMA),
            )

        command, kwargs = calls[0]
        self.assertEqual(command[0:2], ["codex", "exec"])
        self.assertIn("--ephemeral", command)
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("--output-schema", command)
        transport_path = Path(command[command.index("--output-schema") + 1])
        self.assertNotEqual(transport_path.resolve(), SOLVER_SCHEMA.resolve())
        self.assertEqual(transport_path.name, result.transport_schema_path.name)
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

    def test_codex_isolated_workspace_allows_the_canonical_reviewer_schema(self) -> None:
        def runner(command: list[str], **kwargs):
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = CodexRuntime(executable="codex", runner=runner, cli_version="mock")
            result = runtime.invoke(request(Path(directory), stage="reviewer", schema=REVIEWER_SCHEMA))

        self.assertEqual(result.parsed, {})

    def test_codex_normalizes_nullable_transport_optionals_before_canonical_validation(self) -> None:
        def runner(command: list[str], **kwargs):
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text(json.dumps({
                "item_id": "mock-001",
                "section": "Structure",
                "solver_answer": "A",
                "confidence": "HIGH",
                "reason": "The live solver selected A.",
                "ambiguity_detected": False,
                "suggested_correction": None,
            }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = CodexRuntime(executable="codex", runner=runner, cli_version="mock")
            result = runtime.invoke(request(Path(directory)))

        self.assertNotIn("suggested_correction", result.parsed)
        self.assertEqual(schema_errors(result.parsed, load_schema(SOLVER_SCHEMA)), [])

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
            self.assertTrue(error.result.workspace_path)
            self.assertFalse(error.result.workspace_path.exists())

        self.assertEqual(error.category, "infrastructure")
        self.assertEqual(error.result.exit_code, 429)

    def test_isolated_workspace_is_removed_after_parse_failure(self) -> None:
        def runner(command: list[str], **kwargs):
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("not-json", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = CodexRuntime(executable="codex", runner=runner, cli_version="mock")
            with self.assertRaises(RuntimeInvocationError) as raised:
                runtime.invoke(request(Path(directory)))
            self.assertTrue(raised.exception.result.workspace_path)
            self.assertFalse(raised.exception.result.workspace_path.exists())

    def test_failed_workspace_can_be_retained_only_by_explicit_opt_in(self) -> None:
        def runner(command: list[str], **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

        with tempfile.TemporaryDirectory() as directory:
            invocation_request = replace(request(Path(directory)), retain_workspace_on_failure=True)
            runtime = CodexRuntime(executable="codex", runner=runner, cli_version="mock")
            with self.assertRaises(RuntimeInvocationError) as raised:
                runtime.invoke(invocation_request)
            workspace = raised.exception.result.workspace_path
            self.assertTrue(workspace and workspace.exists())
            shutil.rmtree(workspace, ignore_errors=True)

    def test_posix_timeout_cleanup_escalates_to_process_group_sigkill(self) -> None:
        runtime = CodexRuntime(
            executable="codex",
            runner=lambda *args, **kwargs: subprocess.CompletedProcess([], 0),
            cli_version="mock",
        )
        calls: list[tuple[int, int]] = []

        def killpg(pid: int, sig: int) -> None:
            calls.append((pid, sig))

        with mock.patch.object(os, "name", "posix"), mock.patch.object(
            os, "killpg", side_effect=killpg, create=True
        ):
            runtime._terminate_process_tree(123)
            runtime._terminate_process_tree(123, force=True)

        self.assertEqual(calls[0], (123, signal.SIGTERM))
        self.assertEqual(calls[1], (123, getattr(signal, "SIGKILL", signal.SIGTERM)))

    def test_posix_process_group_cleanup_tolerates_exited_group(self) -> None:
        runtime = CodexRuntime(
            executable="codex",
            runner=lambda *args, **kwargs: subprocess.CompletedProcess([], 0),
            cli_version="mock",
        )
        with mock.patch.object(os, "name", "posix"), mock.patch.object(
            os, "killpg", side_effect=ProcessLookupError, create=True
        ):
            runtime._terminate_process_tree(123, force=True)

    def test_codex_failure_categories_do_not_match_prompt_words(self) -> None:
        runtime = CodexRuntime(executable="codex", runner=lambda *args, **kwargs: subprocess.CompletedProcess([], 0), cli_version="mock")
        self.assertEqual(runtime._process_error_category("invalid_json_schema: allOf is not permitted"), "CODEX_SCHEMA_COMPATIBILITY_ERROR")
        self.assertEqual(runtime._process_error_category("prompt mentions network monitoring\nprocess exited unexpectedly"), "CODEX_PROCESS_ERROR")

    def test_harness_failure_classification_is_provider_neutral(self) -> None:
        harness_path = ROOT / "scripts" / "run_live_e2e.py"
        spec = importlib.util.spec_from_file_location("we_live_harness_failure_classification_test", harness_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        for provider, raw_category in (("claude-code-cli", "auth"), ("codex", "CODEX_AUTH_ERROR")):
            with self.subTest(provider=provider):
                invocation = harness.InvocationResult(
                    "reviewer",
                    harness.REVIEWER_AGENT,
                    f"{provider}-invocation",
                    harness.now_iso(),
                    completed_at=harness.now_iso(),
                    provider=provider,
                    model="test",
                    cli_version="test",
                    exit_code=1,
                    raw_stderr="authentication failed",
                    error_category=raw_category,
                )
                self.assertEqual(harness._classify_invocation_failure(invocation, None), "AUTH_ERROR")
                record = harness.sidecar(
                    invocation,
                    input_payload={},
                    contract_validated=False,
                    formal_output_exists=False,
                    leakage=[],
                )
                self.assertEqual(record["failure_classification"], "AUTH_ERROR")
                self.assertEqual(record["failure_source"], provider)
                self.assertEqual(record["provider_failure_category"], raw_category)

    def test_absolute_output_directory_keeps_external_snapshot_identity(self) -> None:
        harness_path = ROOT / "scripts" / "run_live_e2e.py"
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"WE_E2E_OUTPUT_DIR": str(Path(directory) / "external-run")}, clear=False
        ):
            spec = importlib.util.spec_from_file_location("we_live_harness_external_output_test", harness_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            harness = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(harness)
            self.assertEqual(harness.OUT, Path(directory).resolve() / "external-run")
            freeze = harness._create_run_freeze(
                SimpleNamespace(provider="codex", cli_version="test"),
                model="test",
                reasoning_effort="unset",
                sandbox="read-only",
                timeout_seconds=1,
            )
            generator_snapshot = freeze.manifest["canonical_schema_snapshots"]["generator"]
            self.assertEqual(generator_snapshot["snapshot_path_kind"], "external")
            self.assertTrue(Path(generator_snapshot["snapshot_path"]).is_absolute())
            freeze.verify("test", "external-output")

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
        harness_path = ROOT / "scripts" / "run_live_e2e.py"
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

    def test_live_harness_finalization_validation_uses_formal_sentence(self) -> None:
        harness_path = ROOT / "scripts" / "run_live_e2e.py"
        spec = importlib.util.spec_from_file_location("we_live_harness_finalization_test", harness_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        item = {
            "sentence": "The river valleys reveals patterns during winter surveys.",
            "correct_answer": "D",
            "marked_parts": {"A": "The", "B": "river", "C": "valleys", "D": "reveals"},
            "qa_metadata": {
                "clean_form": "The river valleys reveals patterns during winter surveys.",
                "error_form": "The river valleys reveal patterns during winter surveys.",
            },
        }
        ok, errors = harness.validate_generator_finalization(item)
        self.assertFalse(ok)
        self.assertIn("qa_metadata.error_form", " ".join(errors))

        item["sentence"] = item["qa_metadata"]["error_form"]
        item["marked_parts"]["D"] = "reveal"
        ok, errors = harness.validate_generator_finalization(item)
        self.assertTrue(ok, errors)

    def test_live_e2e_reviewer_error_metrics_are_distinct(self) -> None:
        harness_path = ROOT / "scripts" / "run_live_e2e.py"
        spec = importlib.util.spec_from_file_location("we_live_harness_metrics_test", harness_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)

        def reviewer(item_id: str, count: int, *, one_error: str, grammar: str = "PASS", answer: str = "A") -> dict:
            return {
                "item_id": item_id,
                "detected_error_count": count,
                "grammar_validity": grammar,
                "independent_answer": answer,
                "checks": {
                    "one_error_only": one_error,
                    "answer_uniqueness": "PASS" if answer != "AMBIGUOUS" else "AMBIGUOUS",
                },
            }

        metrics = harness.build_metrics(
            [],
            [
                reviewer("zero", 0, one_error="FAIL"),
                reviewer("multiple", 2, one_error="FAIL"),
                reviewer("ambiguous", 1, one_error="AMBIGUOUS"),
                reviewer("valid", 1, one_error="PASS"),
            ],
            [],
            [],
            [],
            {"passed": True},
            "metrics-test",
        )
        self.assertEqual(
            metrics["requested_metrics"]["reviewer_error_status_counts"],
            {
                "one_genuine_error": 1,
                "zero_genuine_errors": 1,
                "multiple_errors": 1,
                "ambiguous_one_error": 1,
            },
        )
        self.assertEqual(metrics["gates"]["reviewer_zero_genuine_errors"]["count"], 1)
        self.assertEqual(metrics["gates"]["reviewer_multiple_error"]["count"], 1)
        self.assertEqual(metrics["gates"]["reviewer_ambiguous_one_error"]["count"], 1)

    def test_live_e2e_report_only_rejects_tampered_artifact_without_invocation(self) -> None:
        harness_path = ROOT / "scripts" / "run_live_e2e.py"
        spec = importlib.util.spec_from_file_location("we_live_harness_report_test", harness_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            formal = out / "runtime" / "formal"
            provenance = out / "runtime" / "provenance"
            inputs = out / "runtime" / "inputs"
            logs = out / "runtime" / "logs"
            runtime_dir = out / "runtime"
            for path in (formal, provenance, inputs, logs):
                path.mkdir(parents=True)
            patched = {
                "OUT": out,
                "RUNTIME": runtime_dir,
                "FORMAL": formal,
                "PROVENANCE": provenance,
                "INPUTS": inputs,
                "LOGS": logs,
            }
            with mock.patch.multiple(harness, **patched):
                freeze = harness._create_run_freeze(SimpleNamespace(provider="test", cli_version="test"), model="test", reasoning_effort="unset", sandbox="read-only", timeout_seconds=1)
                with mock.patch.object(harness, "_RUN_FREEZE", freeze):
                    for filename in ("generator_outputs.json", "reviewer_outputs.json", "solver_outputs.json"):
                        harness.atomic_write_json(formal / filename, {"items": []})
                    harness.atomic_write_json(provenance / "runtime_provenance.json", {"items": []})
                    harness.atomic_write_json(runtime_dir / "outcomes.json", {"batch_id": "report-test", "outcomes": []})
                    harness.atomic_write_json(runtime_dir / "test_result.json", {"passed": False})
                    harness.write_artifact_manifest(freeze)

                    with mock.patch.object(harness, "invoke") as invoke:
                        self.assertEqual(harness.report_existing_run(), 1)
                    invoke.assert_not_called()
                    (formal / "generator_outputs.json").write_text('{"items": [{"tampered": true}]}\n', encoding="utf-8")
                    with mock.patch.object(harness, "invoke") as invoke:
                        self.assertEqual(harness.report_existing_run(), 2)
                    invoke.assert_not_called()


class LiveReviewerAdapterTests(unittest.TestCase):
    @staticmethod
    def _harness():
        harness_path = ROOT / "scripts" / "run_live_e2e.py"
        spec = importlib.util.spec_from_file_location("we_live_harness_reviewer_adapter_test", harness_path)
        assert spec is not None and spec.loader is not None
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        return harness

    @staticmethod
    def _records() -> tuple[dict, dict, dict]:
        generator = json.loads(
            (ROOT / "analysis/we_v2/we_v2_smoke_items.json").read_text(encoding="utf-8")
        )["items"][0]
        expected = json.loads(
            (ROOT / "analysis/we_v2/we_v2_smoke_review.json").read_text(encoding="utf-8")
        )["items"][0]
        raw = copy.deepcopy(expected)
        del raw["generator_answer"]
        del raw["answer_match"]
        del raw["checks"]["target_metadata"]
        return generator, expected, raw

    def test_valid_reviewer_output_is_structurally_adapted_without_rewriting(self) -> None:
        harness = self._harness()
        generator, expected, raw = self._records()
        formal = harness.formal_reviewer(raw, generator, 1, "adapter-test")
        self.assertEqual(formal, expected)

    def test_pass_with_failed_one_error_check_is_rejected(self) -> None:
        harness = self._harness()
        generator, _expected, raw = self._records()
        raw["checks"]["one_error_only"] = "FAIL"
        with self.assertRaises(harness.LiveInvocationError):
            harness.formal_reviewer(raw, generator, 1, "adapter-test")

    def test_blind_target_metadata_field_is_rejected(self) -> None:
        harness = self._harness()
        generator, expected, raw = self._records()
        raw["checks"]["target_metadata"] = expected["checks"]["target_metadata"]
        with self.assertRaises(harness.LiveInvocationError):
            harness.formal_reviewer(raw, generator, 1, "adapter-test")

    def test_target_metadata_is_added_after_blind_response(self) -> None:
        harness = self._harness()
        generator, expected, raw = self._records()
        live_schema = harness.reviewer_runtime_schema()
        checks_schema = live_schema["properties"]["checks"]
        self.assertNotIn("target_metadata", checks_schema["required"])
        self.assertNotIn("target_metadata", checks_schema["properties"])
        formal = harness.formal_reviewer(raw, generator, 1, "adapter-test")
        self.assertEqual(formal["checks"]["target_metadata"], "PASS")
        self.assertEqual(formal, expected)

    def test_generator_metadata_contradiction_fails_closed_without_changing_grammar(self) -> None:
        harness = self._harness()
        generator, _expected, raw = self._records()
        generator = copy.deepcopy(generator)
        generator["grammar_metadata"]["correct_span_type"] = "CLAUSE_OR_CLAUSE_LIKE"
        original_answer = raw["independent_answer"]
        original_grammar = raw["grammar_validity"]
        with self.assertRaises(harness.LiveInvocationError) as raised:
            harness.formal_reviewer(raw, generator, 1, "adapter-test")
        self.assertIn("target_metadata", str(raised.exception))
        self.assertEqual(raw["independent_answer"], original_answer)
        self.assertEqual(raw["grammar_validity"], original_grammar)

    def test_contradictory_formal_target_metadata_fails_closed(self) -> None:
        harness = self._harness()
        generator, _expected, raw = self._records()
        formal = harness.adapt_reviewer_structural(raw, generator, 1, "adapter-test")
        formal["checks"]["target_metadata"] = "AMBIGUOUS"
        errors = harness.validate_reviewer_post_blind_consistency(formal, generator)
        self.assertTrue(errors)
        self.assertIn("target_metadata", errors[0])

    def test_missing_verdict_is_rejected(self) -> None:
        harness = self._harness()
        generator, _expected, raw = self._records()
        del raw["verdict"]
        with self.assertRaises(harness.LiveInvocationError):
            harness.formal_reviewer(raw, generator, 1, "adapter-test")

    def test_missing_source_similarity_risk_is_rejected(self) -> None:
        harness = self._harness()
        generator, _expected, raw = self._records()
        del raw["source_similarity_risk"]
        with self.assertRaises(harness.LiveInvocationError):
            harness.formal_reviewer(raw, generator, 1, "adapter-test")


if __name__ == "__main__":
    unittest.main()
