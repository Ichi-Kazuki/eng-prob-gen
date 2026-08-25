"""Focused regression coverage for the validation and state hardening pass."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

import orchestrator as core  # noqa: E402
import pilot_driver  # noqa: E402
import validation_driver  # noqa: E402
from shared.json_io import JsonPersistenceError  # noqa: E402


def fixture(path: str, index: int = 0) -> dict:
    return copy.deepcopy(json.loads((ROOT / path).read_text(encoding="utf-8"))["items"][index])


def run_validator(relpath: str, item: dict) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump({"items": [item]}, handle)
        path = handle.name
    try:
        return subprocess.run(
            [sys.executable, str(ROOT / relpath), path],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    finally:
        Path(path).unlink(missing_ok=True)


class GeneratorSchemaRegressions(unittest.TestCase):
    def test_required_fields_and_unknown_properties_are_rejected(self) -> None:
        structure = fixture("analysis/generator_smoke_test.json", 0)
        for field in ("subtype", "vocabulary_domain", "answer_explanation"):
            with self.subTest(field=field):
                invalid = copy.deepcopy(structure)
                invalid.pop(field)
                result = run_validator(
                    "agents/toefl_itp_grammar_generator/scripts/validate_output.py",
                    invalid,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("missing required property", result.stdout)
        invalid = copy.deepcopy(structure)
        invalid["unexpected"] = True
        result = run_validator(
            "agents/toefl_itp_grammar_generator/scripts/validate_output.py", invalid
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("additional property 'unexpected' is not allowed", result.stdout)

    def test_written_expression_minimal_correction_is_required(self) -> None:
        item = fixture("analysis/generator_smoke_test.json", 3)
        item.pop("minimal_correction")
        result = run_validator(
            "agents/toefl_itp_grammar_generator/scripts/validate_output.py", item
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("minimal_correction", result.stdout)

    def test_valid_fixture_passes(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "agents/toefl_itp_grammar_generator/scripts/validate_output.py"),
                str(ROOT / "analysis/generator_smoke_test.json"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ReviewerInvariantRegressions(unittest.TestCase):
    def base(self) -> dict:
        return fixture("analysis/reviewer_smoke_test.json", 0)

    def test_pass_requires_consistent_structured_findings(self) -> None:
        cases = []
        item = self.base()
        item["checks"]["grammar_validity"] = "REJECT"
        cases.append(item)
        item = self.base()
        item["issues"] = [{
            "severity": "MAJOR",
            "category": "test",
            "description": "test",
            "related_check": "grammar_validity",
        }]
        cases.append(item)
        item = self.base()
        item["revision_requirements"] = ["fix"]
        cases.append(item)
        item = self.base()
        item["answer_match"] = False
        cases.append(item)
        item = self.base()
        item["difficulty_mismatch"] = True
        cases.append(item)
        for invalid in cases:
            with self.subTest(invalid=invalid):
                self.assertEqual(
                    run_validator(
                        "agents/toefl_itp_grammar_reviewer/scripts/validate_output.py",
                        invalid,
                    ).returncode,
                    1,
                )

    def test_valid_pass_still_passes(self) -> None:
        result = run_validator(
            "agents/toefl_itp_grammar_reviewer/scripts/validate_output.py", self.base()
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_written_expression_pass_requires_one_error_and_matching_position(self) -> None:
        item = fixture("analysis/reviewer_smoke_test.json", 3)
        item["detected_error_count"] = 2
        item["detected_error_position"] = "A"
        result = run_validator(
            "agents/toefl_itp_grammar_reviewer/scripts/validate_output.py", item
        )
        self.assertEqual(result.returncode, 1)


class StateAndDriverRegressions(unittest.TestCase):
    def test_invalid_direct_transition_is_rejected(self) -> None:
        candidate = core.Candidate("state-001", "state-001", "Structure")
        with self.assertRaises(ValueError):
            candidate.transition(core.State.ACCEPTED)

    def test_normal_review_solver_route_is_allowed(self) -> None:
        candidate = core.Candidate("state-002", "state-002", "Structure")
        candidate.transition(core.State.REVIEWING)
        candidate.transition(core.State.SOLVING)
        candidate.transition(core.State.ACCEPTED)

    def test_pilot_rejects_cross_file_duplicate_ids(self) -> None:
        payload = {"items": [{"item_id": "same", "section": "Structure"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            structure = root / "structure.json"
            written_expression = root / "written_expression.json"
            structure.write_text(json.dumps(payload), encoding="utf-8")
            written_expression.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate initial item_id"):
                pilot_driver.cmd_init(str(structure), str(written_expression))

    def test_leakage_failure_is_not_written_to_solver_batch(self) -> None:
        candidate = core.Candidate("leak-001", "leak-001", "Structure")
        candidate.state = core.State.SOLVING
        candidate.generator_item = {"item_id": "leak-001", "section": "Structure"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(pilot_driver, "PILOT_DIR", root), \
                 mock.patch.object(pilot_driver, "STATE_PATH", root / "state.json"), \
                 mock.patch.object(pilot_driver, "load_state", return_value={candidate.item_id: candidate}), \
                 mock.patch.object(pilot_driver, "blind_for_solver", return_value={
                     "item_id": "leak-001", "section": "Structure", "stem": "x",
                     "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                     "correct_answer": "A",
                 }):
                pilot_driver.cmd_prepare_solver_batch()
            batch = json.loads((root / "solver_input_batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["items"], [])
            self.assertEqual(candidate.state, core.State.MANUAL_REVIEW)

    def test_finalize_rejects_transient_state_in_both_drivers(self) -> None:
        candidate = core.Candidate("transient-001", "transient-001", "Structure")
        candidate.state = core.State.SOLVING
        with mock.patch.object(pilot_driver, "load_state", return_value={candidate.item_id: candidate}):
            with self.assertRaisesRegex(ValueError, "nonterminal"):
                pilot_driver.cmd_finalize()
        with mock.patch.object(validation_driver, "load_state", return_value={candidate.item_id: candidate}):
            with self.assertRaisesRegex(ValueError, "nonterminal"):
                validation_driver.cmd_finalize()


class PersistenceAndSubprocessRegressions(unittest.TestCase):
    def test_queue_deduplicates_and_fails_closed_on_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "queue.json"
            config = {"paths": {"manual_review_queue": str(queue)}}
            entry = {"item_id": "queue-001"}
            core.append_manual_review_queue(config, [entry, entry])
            core.append_manual_review_queue(config, [entry])
            self.assertEqual(len(json.loads(queue.read_text(encoding="utf-8"))["items"]), 1)
            original = "{broken"
            queue.write_text(original, encoding="utf-8")
            with self.assertRaises(JsonPersistenceError):
                core.append_manual_review_queue(config, [{"item_id": "queue-002"}])
            self.assertEqual(queue.read_text(encoding="utf-8"), original)

    def test_validator_timeout_and_unexpected_exit_are_system_failures(self) -> None:
        script = "agents/toefl_itp_grammar_generator/scripts/validate_output.py"
        with mock.patch.object(
            core.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(["python"], 0.01, output="partial", stderr="timeout"),
        ):
            with self.assertRaises(core.SystemCallError) as timeout:
                core.run_schema_validator(script, [{}], timeout_seconds=0.01)
        self.assertIn("timed out", str(timeout.exception))
        with mock.patch.object(
            core.subprocess, "run",
            return_value=subprocess.CompletedProcess(["python"], 2, stdout="", stderr="crash"),
        ):
            with self.assertRaises(core.SystemCallError) as exit_error:
                core.run_schema_validator(script, [{}])
        self.assertIn("exit", str(exit_error.exception))


if __name__ == "__main__":
    unittest.main()
