"""P0 safety regressions for validators, retries, subprocesses, and persistence."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

import orchestrator as core  # noqa: E402
import pilot_driver  # noqa: E402
import validation_driver  # noqa: E402
from shared.json_io import JsonPersistenceError  # noqa: E402


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR_VALIDATOR = load_module(
    "p0_generator_validator",
    "agents/toefl_itp_grammar_generator/scripts/validate_output.py",
)
REVIEWER_VALIDATOR = load_module(
    "p0_reviewer_validator",
    "agents/toefl_itp_grammar_reviewer/scripts/validate_output.py",
)


def fixture_item(path: str, section: str) -> dict:
    document = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return copy.deepcopy(next(item for item in document["items"] if item["section"] == section))


def valid_generator(section: str = "Structure") -> dict:
    return fixture_item("analysis/generator_smoke_test.json", section)


def valid_reviewer(section: str = "Structure") -> dict:
    return fixture_item("analysis/reviewer_smoke_test.json", section)


def valid_solver(section: str = "Structure") -> dict:
    return fixture_item("analysis/solver_smoke_test.json", section)


class GeneratorSchemaSourceOfTruthTests(unittest.TestCase):
    def test_every_required_field_is_rejected_when_missing(self) -> None:
        cases = (
            ("Structure", "agents/toefl_itp_grammar_generator/schema/structure_item.schema.json"),
            (
                "Written Expression",
                "agents/toefl_itp_grammar_generator/schema/written_expression_item.schema.json",
            ),
        )
        for section, schema_path in cases:
            required = json.loads((ROOT / schema_path).read_text(encoding="utf-8"))["required"]
            for field in required:
                with self.subTest(section=section, field=field):
                    item = valid_generator(section)
                    del item[field]
                    errors = GENERATOR_VALIDATOR.validate_contract(item)
                    self.assertTrue(any(f"$.{field}" in error or repr(field) in error for error in errors), errors)

    def test_unknown_property_is_rejected_with_item_id_and_json_path(self) -> None:
        item = valid_generator()
        item["unexpected_contract_key"] = True
        errors = GENERATOR_VALIDATOR.validate_contract(item)
        self.assertTrue(errors)
        self.assertTrue(all(f"[{item['item_id']}]" in error for error in errors))
        self.assertTrue(any("$:" in error and "unexpected_contract_key" in error for error in errors))

    def test_cli_exit_codes_distinguish_content_and_runtime_failure(self) -> None:
        script = ROOT / "agents/toefl_itp_grammar_generator/scripts/validate_output.py"
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            invalid = valid_generator()
            del invalid["answer_explanation"]
            invalid_path = directory / "invalid.json"
            invalid_path.write_text(json.dumps({"items": [invalid]}), encoding="utf-8")
            malformed_path = directory / "malformed.json"
            malformed_path.write_text("{not-json", encoding="utf-8")
            content = subprocess.run([sys.executable, str(script), str(invalid_path)])
            runtime = subprocess.run([sys.executable, str(script), str(malformed_path)])
        self.assertEqual(content.returncode, 1)
        self.assertGreaterEqual(runtime.returncode, 2)


class ReviewerConsistencyTests(unittest.TestCase):
    def test_answer_and_difficulty_flags_are_derived_fields(self) -> None:
        reviewer = valid_reviewer()
        reviewer["answer_match"] = not reviewer["answer_match"]
        reviewer["difficulty_mismatch"] = not reviewer["difficulty_mismatch"]
        errors = REVIEWER_VALIDATOR.validate_contract(reviewer)
        self.assertTrue(any("$.answer_match" in error for error in errors), errors)
        self.assertTrue(any("$.difficulty_mismatch" in error for error in errors), errors)

    def test_pass_requires_all_checks_and_no_critical_issue(self) -> None:
        reviewer = valid_reviewer()
        reviewer["checks"]["naturalness"] = "REVISE"
        reviewer["issues"] = [{
            "severity": "CRITICAL",
            "category": "test",
            "description": "reported critical issue",
            "related_check": "naturalness",
        }]
        errors = REVIEWER_VALIDATOR.validate_contract(reviewer)
        self.assertTrue(any("every required check" in error for error in errors), errors)
        self.assertTrue(any("CRITICAL" in error for error in errors), errors)

    def test_nonpass_all_green_empty_output_is_rejected(self) -> None:
        reviewer = valid_reviewer()
        reviewer["verdict"] = "REJECT"
        errors = REVIEWER_VALIDATOR.validate_contract(reviewer)
        self.assertTrue(any("all checks PASS" in error for error in errors), errors)

    def test_written_expression_pass_requires_exactly_one_matching_error(self) -> None:
        for count in (0, 2):
            with self.subTest(count=count):
                reviewer = valid_reviewer("Written Expression")
                reviewer["detected_error_count"] = count
                errors = REVIEWER_VALIDATOR.validate_contract(reviewer)
                self.assertTrue(any("detected_error_count" in error for error in errors), errors)

        reviewer = valid_reviewer("Written Expression")
        reviewer["detected_error_position"] = "NONE"
        reviewer["non_error_parts_valid"] = False
        reviewer["minimal_correction_valid"] = False
        errors = REVIEWER_VALIDATOR.validate_contract(reviewer)
        for field in (
            "detected_error_position",
            "non_error_parts_valid",
            "minimal_correction_valid",
        ):
            self.assertTrue(any(field in error for error in errors), errors)

    def test_consensus_defence_blocks_inconsistent_reviewer_pass(self) -> None:
        generator = valid_generator()
        reviewer = valid_reviewer()
        solver = valid_solver()
        self.assertTrue(core.evaluate_consensus(generator, reviewer, solver, core.load_config()).auto_accept)
        reviewer["checks"]["grammar_validity"] = "REVISE"
        result = core.evaluate_consensus(generator, reviewer, solver, core.load_config())
        self.assertFalse(result.auto_accept)
        self.assertIn("reviewer.required_checks not all PASS", result.failed_conditions)


class SubprocessClassificationTests(unittest.TestCase):
    def test_validator_exit_codes_are_classified(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout="candidate bad", stderr="detail")
        with mock.patch.object(core.subprocess, "run", return_value=completed):
            ok, detail = core.run_schema_validator(
                "agents/toefl_itp_grammar_generator/scripts/validate_output.py", [{}]
            )
        self.assertFalse(ok)
        self.assertIn("candidate bad", detail)
        self.assertIn("detail", detail)

        crashed = subprocess.CompletedProcess([], 2, stdout="", stderr="traceback")
        with mock.patch.object(core.subprocess, "run", return_value=crashed):
            with self.assertRaises(core.SystemCallError):
                core.run_schema_validator(
                    "agents/toefl_itp_grammar_generator/scripts/validate_output.py", [{}]
                )

    def test_validator_timeout_is_system_failure_and_temp_file_is_removed(self) -> None:
        observed_path: Path | None = None

        def timeout(command, **kwargs):
            nonlocal observed_path
            observed_path = Path(command[-1])
            self.assertTrue(observed_path.exists())
            self.assertEqual(kwargs["timeout"], 0.01)
            raise subprocess.TimeoutExpired(command, 0.01, output="partial", stderr="timeout")

        with mock.patch.object(core.subprocess, "run", side_effect=timeout):
            with self.assertRaises(core.SystemCallError) as raised:
                core.run_schema_validator(
                    "agents/toefl_itp_grammar_generator/scripts/validate_output.py",
                    [{}],
                    timeout_seconds=0.01,
                )
        self.assertIn("timed out", str(raised.exception))
        self.assertIsNotNone(observed_path)
        self.assertFalse(observed_path.exists())

    def test_missing_validator_is_system_failure(self) -> None:
        with self.assertRaises(core.SystemCallError):
            core.run_schema_validator("missing-validator.py", [{}])

    def test_malformed_blinding_output_is_system_failure_and_temp_files_are_removed(self) -> None:
        paths: list[Path] = []

        def malformed(command, **_kwargs):
            paths.extend([Path(command[-2]), Path(command[-1])])
            Path(command[-1]).write_text("{bad", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with mock.patch.object(core.subprocess, "run", side_effect=malformed):
            with self.assertRaises(core.SystemCallError):
                core.blind_for_solver(core.load_config(), valid_generator())
        self.assertTrue(paths)
        self.assertTrue(all(not path.exists() for path in paths))


class RetryPolicyTests(unittest.TestCase):
    def candidate(self) -> core.Candidate:
        item = valid_generator()
        candidate = core.Candidate(item["item_id"], item["item_id"], item["section"])
        candidate.generator_item = item
        return candidate

    def test_content_retry_success_and_exhaustion(self) -> None:
        config = core.load_config()
        candidate = self.candidate()
        with mock.patch.object(core, "run_schema_validator", side_effect=[(False, "bad"), (True, "ok")]):
            core.process_generation_output(candidate, config)
            self.assertEqual(candidate.state, core.State.GENERATED)
            core.process_generation_output(candidate, config)
        self.assertEqual(candidate.state, core.State.REVIEWING)
        self.assertEqual(candidate.validation_retry_counts["generator"], 1)

        exhausted = self.candidate()
        exhausted.revision_count = 2
        with mock.patch.object(core, "run_schema_validator", return_value=(False, "bad")):
            for _ in range(config["retry_policy"]["max_generation_validation_retries"] + 1):
                core.process_generation_output(exhausted, config)
        self.assertEqual(exhausted.state, core.State.DISCARDED)
        self.assertEqual(exhausted.revision_count, 2)
        self.assertTrue(exhausted.retry_history[-1]["exhausted"])

    def test_system_retry_exhaustion_routes_to_manual_review(self) -> None:
        config = core.load_config()
        candidate = self.candidate()
        with mock.patch.object(core, "run_schema_validator", side_effect=core.SystemCallError("boom")):
            for _ in range(config["retry_policy"]["max_system_failure_retries"] + 1):
                core.process_generation_output(candidate, config)
        self.assertEqual(candidate.state, core.State.MANUAL_REVIEW)
        self.assertEqual(candidate.system_failure_retry_counts["generator"], 4)
        self.assertEqual(candidate.revision_count, 0)

    def test_stage_counters_and_serialization_are_independent(self) -> None:
        candidate = self.candidate()
        config = core.load_config()
        core.record_stage_failure(
            candidate, config, kind="system", stage="reviewer", detail="runtime",
            retry_state=core.State.REVIEWING,
        )
        core.record_stage_failure(
            candidate, config, kind="content", stage="solver", detail="shape",
            retry_state=core.State.SOLVING,
        )
        restored = core.candidate_from_dict(core.candidate_to_dict(candidate))
        self.assertEqual(restored.system_failure_retry_counts["reviewer"], 1)
        self.assertEqual(restored.validation_retry_counts["solver"], 1)
        self.assertEqual([event["stage"] for event in restored.retry_history], ["reviewer", "solver"])
        self.assertEqual(restored.revision_count, 0)


class PersistenceAndCompletenessTests(unittest.TestCase):
    def test_corrupt_manual_queue_fails_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "manual_review_queue.json"
            original = "{malformed but important"
            queue.write_text(original, encoding="utf-8")
            config = core.load_config()
            config["paths"] = dict(config["paths"])
            config["paths"]["manual_review_queue"] = str(queue)
            with self.assertRaises(JsonPersistenceError):
                core.append_manual_review_queue(config, [{"item_id": "new-item"}])
            self.assertEqual(queue.read_text(encoding="utf-8"), original)

    def test_validation_finalize_refuses_any_nonterminal_candidate_before_writing(self) -> None:
        candidates = {
            f"item-{index:03d}": core.Candidate(
                f"item-{index:03d}", f"item-{index:03d}", "Structure",
                state=core.State.REJECTED,
                state_history=[core.State.GENERATED, core.State.REJECTED],
            )
            for index in range(120)
        }
        candidates["item-042"].state = core.State.SOLVING
        candidates["item-042"].state_history[-1] = core.State.SOLVING
        with (
            mock.patch.object(validation_driver, "load_state", return_value=candidates),
            mock.patch.object(validation_driver, "atomic_write_json") as writer,
        ):
            with self.assertRaisesRegex(ValueError, "item-042=SOLVING"):
                validation_driver.cmd_finalize()
        writer.assert_not_called()

    def test_apply_review_and_solver_report_missing_ids(self) -> None:
        reviewer_candidate = core.Candidate("missing-review", "missing-review", "Structure")
        reviewer_candidate.state = core.State.REVIEWING
        solver_candidate = core.Candidate("missing-solver", "missing-solver", "Structure")
        solver_candidate.state = core.State.SOLVING
        # Only candidates actually blinded into the batch are expected back.
        solver_candidate.solver_input = {"item_id": "missing-solver"}
        with (
            mock.patch.object(pilot_driver, "load_state", return_value={"missing-review": reviewer_candidate}),
            mock.patch.object(pilot_driver, "load_stage_items", return_value={}),
        ):
            with self.assertRaisesRegex(ValueError, "missing-review"):
                pilot_driver.cmd_apply_review("unused.json", "r1")
        with (
            mock.patch.object(validation_driver, "load_state", return_value={"missing-solver": solver_candidate}),
            mock.patch.object(validation_driver, "load_stage_items", return_value={}),
        ):
            with self.assertRaisesRegex(ValueError, "missing-solver"):
                validation_driver.cmd_apply_solver("unused.json")

    def test_unreadable_agent_output_is_an_operator_error_not_a_retry(self) -> None:
        """A batch-level read failure must not consume per-candidate budget."""
        candidate = core.Candidate("review-json", "review-json", "Structure")
        candidate.state = core.State.REVIEWING
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in (("bad.json", b"{bad"), ("bad-utf8.json", bytes([0x7b, 0x22, 0x69, 0x74, 0x65, 0x6d, 0x73, 0x22, 0x3a, 0x20, 0x5b, 0xff, 0x5d, 0x7d]))):
                path = Path(directory) / name
                path.write_bytes(payload)
                with mock.patch.object(pilot_driver, "save_state") as saver:
                    with self.assertRaises(SystemExit):
                        pilot_driver.load_stage_items(path, "reviewer bad JSON")
                saver.assert_not_called()
        self.assertEqual(set(candidate.system_failure_retry_counts.values()), {0})
        self.assertEqual(candidate.state, core.State.REVIEWING)


if __name__ == "__main__":
    unittest.main(verbosity=2)
