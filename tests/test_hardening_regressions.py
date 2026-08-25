"""Focused regression coverage for the validation and state hardening pass."""

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

    def test_pilot_prepare_solver_persists_input_across_process_boundary(self) -> None:
        generator = fixture("analysis/generator_smoke_test.json", 0)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
        solver_path = ROOT / "analysis/solver_smoke_test.json"
        candidate = core.Candidate(
            item_id=generator["item_id"],
            concept_id=generator["item_id"],
            section=generator["section"],
        )
        candidate.state = core.State.SOLVING
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
        candidate.generator_item = generator
        candidate.reviewer_item = reviewer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(pilot_driver, "PILOT_DIR", root), \
                 mock.patch.object(pilot_driver, "STATE_PATH", root / "candidates_state.json"):
                pilot_driver.save_state({candidate.item_id: candidate})
                pilot_driver.cmd_prepare_solver_batch()
                reloaded = pilot_driver.load_state()[candidate.item_id]
                self.assertIsNotNone(reloaded.solver_input)
                self.assertEqual(reloaded.solver_input["item_id"], candidate.item_id)
                pilot_driver.cmd_apply_solver(str(solver_path))
                final = pilot_driver.load_state()[candidate.item_id]

            self.assertEqual(final.state, core.State.ACCEPTED)
            self.assertIsNotNone(final.solver_item)
            self.assertIsNotNone(final.solver_input)

    def test_finalize_rejects_transient_state_in_both_drivers(self) -> None:
        candidate = core.Candidate("transient-001", "transient-001", "Structure")
        candidate.state = core.State.SOLVING
        with mock.patch.object(pilot_driver, "load_state", return_value={candidate.item_id: candidate}):
            with self.assertRaisesRegex(ValueError, "nonterminal"):
                pilot_driver.cmd_finalize()
        with mock.patch.object(validation_driver, "load_state", return_value={candidate.item_id: candidate}):
            with self.assertRaisesRegex(ValueError, "nonterminal"):
                validation_driver.cmd_finalize()

    def test_stage_identity_mismatches_fail_closed(self) -> None:
        generator_a = fixture("analysis/generator_smoke_test.json", 0)
        generator_b = fixture("analysis/generator_smoke_test.json", 1)
        reviewer_a = fixture("analysis/reviewer_smoke_test.json", 0)
        solver_a = fixture("analysis/solver_smoke_test.json", 0)

        review_candidate = core.Candidate("gen-struct-001", "gen-struct-001", "Structure")
        review_candidate.state = core.State.REVIEWING
        review_candidate.generator_item = generator_a
        review_candidate.reviewer_item = copy.deepcopy(reviewer_a)
        review_candidate.reviewer_item["item_id"] = generator_b["item_id"]
        review_candidate = core.process_review_output(review_candidate, core.load_config())
        self.assertEqual(review_candidate.state, core.State.VALIDATION_FAILED)
        self.assertEqual(review_candidate.failure.kind, "content")

        section_candidate = core.Candidate("gen-struct-001", "gen-struct-001", "Structure")
        section_candidate.state = core.State.REVIEWING
        section_candidate.generator_item = generator_a
        section_candidate.reviewer_item = copy.deepcopy(reviewer_a)
        section_candidate.reviewer_item["section"] = "Written Expression"
        section_candidate = core.process_review_output(section_candidate, core.load_config())
        self.assertEqual(section_candidate.state, core.State.VALIDATION_FAILED)
        self.assertIn("section", section_candidate.failure.detail)

        generator_candidate = core.Candidate("gen-struct-001", "gen-struct-001", "Structure")
        generator_candidate.generator_item = copy.deepcopy(generator_b)
        generator_candidate.generator_item["item_id"] = "other-item"
        generator_candidate = core.process_generation_output(generator_candidate, core.load_config())
        self.assertEqual(generator_candidate.state, core.State.VALIDATION_FAILED)

        solver_candidate = core.Candidate("gen-struct-001", "gen-struct-001", "Structure")
        solver_candidate.state = core.State.SOLVING
        solver_candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
        solver_candidate.generator_item = generator_a
        solver_candidate.reviewer_item = reviewer_a
        mismatched_solver = copy.deepcopy(solver_a)
        mismatched_solver["item_id"] = "other-solver-item"
        solver_candidate = core.process_solver_stage(
            solver_candidate,
            core.load_config(),
            mismatched_solver,
            precomputed_solver_input={
                "item_id": "gen-struct-001",
                "section": "Structure",
                "stem": generator_a["stem"],
                "options": generator_a["options"],
            },
        )
        self.assertEqual(solver_candidate.state, core.State.VALIDATION_FAILED)
        self.assertEqual(solver_candidate.failure.kind, "content")

    def test_batch_planned_distribution_keeps_initial_slot_after_revision(self) -> None:
        original = fixture("analysis/generator_smoke_test.json", 0)
        revised = copy.deepcopy(original)
        revised["correct_answer"] = "B"
        candidate = core.Candidate(original["item_id"], original["item_id"], original["section"])
        candidate.generator_item = revised
        candidate.planned_slot = core.derive_slot_requirements(original)
        tracker = core.BatchIntegrityTracker()
        tracker.record_planned(candidate.generator_item, candidate.planned_slot)
        summary = tracker.summary()
        self.assertEqual(summary["planned"]["correct_answer_position"], {"C": 1})

    def test_reviewer_system_failure_retries_and_reaches_solving(self) -> None:
        generator = fixture("analysis/generator_smoke_test.json", 0)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
        candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
        candidate.state = core.State.REVIEWING
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING]
        candidate.generator_item = generator
        candidate.reviewer_item = reviewer

        with mock.patch.object(
            core,
            "run_schema_validator",
            side_effect=[core.SystemCallError("temporary reviewer outage"), (True, "")],
        ):
            candidate = core.process_review_output(candidate, core.load_config())
            self.assertEqual(candidate.state, core.State.GENERATION_FAILED)
            self.assertEqual(candidate.system_failure_retries["reviewer"], 1)
            candidate = core.retry_failed_stage(candidate, core.load_config())
            self.assertIsNone(candidate.failure)
            candidate = core.process_review_output(candidate, core.load_config())

        self.assertEqual(candidate.state, core.State.SOLVING)
        self.assertIsNone(candidate.failure)
        self.assertEqual(candidate.revision_count, 0)

    def test_solver_system_failure_retries_same_solver_stage(self) -> None:
        generator = fixture("analysis/generator_smoke_test.json", 0)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
        solver = fixture("analysis/solver_smoke_test.json", 0)
        solver_input = {
            "item_id": generator["item_id"],
            "section": generator["section"],
            "stem": generator["stem"],
            "options": generator["options"],
        }
        candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
        candidate.state = core.State.SOLVING
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
        candidate.generator_item = generator
        candidate.reviewer_item = reviewer

        with mock.patch.object(
            core,
            "run_schema_validator",
            side_effect=[core.SystemCallError("temporary solver outage"), (True, "")],
        ):
            candidate = core.process_solver_stage(
                candidate, core.load_config(), solver, precomputed_solver_input=solver_input
            )
            self.assertEqual(candidate.state, core.State.GENERATION_FAILED)
            self.assertEqual(candidate.system_failure_retries["solver"], 1)
            candidate = core.retry_failed_stage(candidate, core.load_config())
            candidate = core.process_solver_stage(
                candidate,
                core.load_config(),
                solver,
                precomputed_solver_input=candidate.solver_input,
            )

        self.assertEqual(candidate.state, core.State.ACCEPTED)
        self.assertIsNone(candidate.failure)

    def test_retry_limit_routes_to_manual_review(self) -> None:
        generator = fixture("analysis/generator_smoke_test.json", 0)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
        candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
        candidate.state = core.State.REVIEWING
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING]
        candidate.generator_item = generator
        candidate.reviewer_item = reviewer
        config = copy.deepcopy(core.load_config())
        config["retry_policy"]["max_system_failure_retries"] = 1

        with mock.patch.object(
            core,
            "run_schema_validator",
            side_effect=core.SystemCallError("persistent reviewer outage"),
        ):
            candidate = core.process_review_output(candidate, config)
            candidate = core.retry_failed_stage(candidate, config)
            candidate = core.process_review_output(candidate, config)

        self.assertEqual(candidate.state, core.State.MANUAL_REVIEW)
        self.assertEqual(candidate.system_failure_retries["reviewer"], 2)
        self.assertIsNotNone(candidate.failure)

    def test_validation_failure_retries_without_changing_revision_count(self) -> None:
        generator = fixture("analysis/generator_smoke_test.json", 0)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
        candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
        candidate.state = core.State.REVIEWING
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING]
        candidate.generator_item = generator
        candidate.reviewer_item = reviewer

        with mock.patch.object(
            core,
            "run_schema_validator",
            side_effect=[(False, "schema mismatch"), (True, "")],
        ):
            candidate = core.process_review_output(candidate, core.load_config())
            self.assertEqual(candidate.state, core.State.VALIDATION_FAILED)
            self.assertEqual(candidate.validation_failure_retries["reviewer"], 1)
            candidate = core.retry_failed_stage(candidate, core.load_config())
            candidate = core.process_review_output(candidate, core.load_config())

        self.assertEqual(candidate.state, core.State.SOLVING)
        self.assertEqual(candidate.revision_count, 0)
        self.assertIsNone(candidate.failure)

    def test_both_drivers_rearm_a_persisted_reviewer_failure(self) -> None:
        generator = fixture("analysis/generator_smoke_test.json", 0)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
        reviewer_path = ROOT / "analysis/reviewer_smoke_test.json"

        for driver, directory_name in (
            (pilot_driver, "PILOT_DIR"),
            (validation_driver, "VALIDATION_DIR"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "candidates_state.json"
                candidate = core.Candidate(
                    generator["item_id"], generator["item_id"], generator["section"]
                )
                candidate.state = core.State.REVIEWING
                candidate.state_history = [core.State.GENERATED, core.State.REVIEWING]
                candidate.generator_item = generator
                candidate.reviewer_item = reviewer

                with mock.patch.object(
                    core,
                    "run_schema_validator",
                    side_effect=core.SystemCallError("temporary reviewer outage"),
                ):
                    candidate = core.process_review_output(candidate, core.load_config())
                with mock.patch.object(driver, directory_name, root), \
                     mock.patch.object(driver, "STATE_PATH", state_path):
                    driver.save_state({candidate.item_id: candidate})
                    with mock.patch.object(core, "run_schema_validator", return_value=(True, "")):
                        driver.cmd_apply_review(str(reviewer_path), "retry")
                    self.assertEqual(driver.load_state()[candidate.item_id].state, core.State.SOLVING)
                    self.assertIsNone(driver.load_state()[candidate.item_id].failure)


class CandidatePersistenceInvariantRegressions(unittest.TestCase):
    def assert_corrupt_state_rejected(self, payload: dict, message: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates_state.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(JsonPersistenceError, message):
                core.load_candidate_state(path)

    def base_solver_candidate(self) -> core.Candidate:
        generator = fixture("analysis/generator_smoke_test.json", 0)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
        candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
        candidate.state = core.State.SOLVING
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
        candidate.generator_item = generator
        candidate.reviewer_item = reviewer
        return candidate

    def test_solving_with_revise_verdict_is_rejected_on_load(self) -> None:
        candidate = self.base_solver_candidate()
        candidate.reviewer_item = copy.deepcopy(candidate.reviewer_item)
        candidate.reviewer_item["verdict"] = "REVISE"
        self.assert_corrupt_state_rejected(
            {candidate.item_id: core.candidate_to_dict(candidate)},
            "reviewer verdict PASS",
        )

    def test_state_history_tail_must_match_current_state(self) -> None:
        candidate = self.base_solver_candidate()
        data = core.candidate_to_dict(candidate)
        data["state_history"] = [core.State.GENERATED, core.State.REVIEWING]
        self.assert_corrupt_state_rejected(
            {candidate.item_id: data},
            "does not match current state",
        )

    def test_invalid_state_transition_is_rejected_on_load(self) -> None:
        candidate = self.base_solver_candidate()
        data = core.candidate_to_dict(candidate)
        data["state_history"] = [core.State.GENERATED, core.State.ACCEPTED, core.State.SOLVING]
        self.assert_corrupt_state_rejected(
            {candidate.item_id: data},
            "invalid state transition",
        )


class GenericGeneratorValidatorRegressions(unittest.TestCase):
    @staticmethod
    def validator_module():
        path = ROOT / "agents/toefl_itp_grammar_generator/scripts/validate_output.py"
        spec = importlib.util.spec_from_file_location("generic_generator_validator", path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_custom_primary_targets_only(self) -> None:
        module = self.validator_module()
        item = fixture("analysis/generator_smoke_test.json", 0)
        self.assertEqual(
            module.validate_contract(item, primary_targets={item["primary_target"]}),
            [],
        )

    def test_custom_tested_error_types_only(self) -> None:
        module = self.validator_module()
        item = fixture("analysis/generator_smoke_test.json", 3)
        self.assertEqual(
            module.validate_contract(item, tested_error_types={item["tested_error_type"]}),
            [],
        )
        errors = module.validate_contract(item, tested_error_types=set())
        self.assertTrue(any("tested_error_type" in error for error in errors))

    def test_custom_primary_targets_and_tested_error_types(self) -> None:
        module = self.validator_module()
        item = fixture("analysis/generator_smoke_test.json", 3)
        self.assertEqual(
            module.validate_contract(
                item,
                primary_targets={item["primary_target"]},
                tested_error_types={item["tested_error_type"]},
            ),
            [],
        )

    def test_both_taxonomy_arguments_unspecified_use_defaults(self) -> None:
        module = self.validator_module()
        for index in (0, 3):
            with self.subTest(index=index):
                self.assertEqual(
                    module.validate_contract(fixture("analysis/generator_smoke_test.json", index)),
                    [],
                )


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

    def test_validator_exit_code_two_is_not_content_failure(self) -> None:
        script = "agents/toefl_itp_grammar_generator/scripts/validate_output.py"
        with mock.patch.object(
            core.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                ["python"], 2, stdout="", stderr="SYSTEM ERROR: validator boom"
            ),
        ):
            with self.assertRaises(core.SystemCallError):
                core.run_schema_validator(script, [{}])


class WrittenExpressionV2Regressions(unittest.TestCase):
    GENERATOR_VALIDATOR = "agents/toefl_itp_we_generator_v2/scripts/validate_output.py"
    REVIEWER_VALIDATOR = "agents/toefl_itp_we_reviewer_v2/scripts/validate_output.py"

    def test_generator_v2_malformed_types_are_content_failures(self) -> None:
        base = fixture("analysis/we_v2/we_v2_smoke_items.json", 0)
        cases = []
        for field in ("qa_metadata", "format_metadata", "grammar_metadata", "marked_parts"):
            invalid = copy.deepcopy(base)
            invalid[field] = []
            cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["sentence"] = None
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["marked_parts"]["A"] = 123
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["format_metadata"]["diagnostics"] = []
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["format_metadata"]["diagnostics"] = {}
        cases.append(invalid)

        for invalid in cases:
            with self.subTest(case=invalid):
                result = run_validator(self.GENERATOR_VALIDATOR, invalid)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("SYSTEM ERROR", result.stderr)

    def test_generator_v2_schema_required_unknown_nested_and_valid_fixture(self) -> None:
        base = fixture("analysis/we_v2/we_v2_smoke_items.json", 0)
        missing = copy.deepcopy(base)
        del missing["format_metadata"]["diagnostics"]
        unknown = copy.deepcopy(base)
        unknown["unexpected"] = True
        nested = copy.deepcopy(base)
        nested["format_metadata"]["span_types"]["A"] = 123
        for invalid, needle in (
            (missing, "missing required property 'diagnostics'"),
            (unknown, "additional property 'unexpected' is not allowed"),
            (nested, "span_types.A"),
        ):
            with self.subTest(needle=needle):
                result = run_validator(self.GENERATOR_VALIDATOR, invalid)
                self.assertEqual(result.returncode, 1)
                self.assertIn(needle, result.stdout)
        valid = subprocess.run(
            [sys.executable, str(ROOT / self.GENERATOR_VALIDATOR), str(ROOT / "analysis/we_v2/we_v2_smoke_items.json")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

    def test_reviewer_v2_pass_invariants_and_schema_fail_closed(self) -> None:
        base = fixture("analysis/we_v2/we_v2_smoke_review.json", 0)
        cases = []
        invalid = copy.deepcopy(base)
        invalid["answer_match"] = False
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["detected_error_position"] = "B"
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["non_error_parts_valid"] = False
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["minimal_correction_valid"] = False
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["revision_requirements"] = ["fix"]
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["unknown"] = True
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["checks"]["grammar_validity"] = 123
        cases.append(invalid)
        for invalid in cases:
            with self.subTest(case=invalid):
                result = run_validator(self.REVIEWER_VALIDATOR, invalid)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("SYSTEM ERROR", result.stderr)
        valid = subprocess.run(
            [sys.executable, str(ROOT / self.REVIEWER_VALIDATOR), str(ROOT / "analysis/we_v2/we_v2_smoke_review.json")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)


class RepositoryHygieneRegressions(unittest.TestCase):
    def test_acceptance_tests_do_not_modify_real_manual_review_queue(self) -> None:
        queue = ROOT / "analysis/manual_review_queue.json"
        before = queue.read_bytes() if queue.exists() else None
        result = subprocess.run(
            [sys.executable, str(ROOT / "orchestrator/scripts/run_acceptance_tests.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = queue.read_bytes() if queue.exists() else None
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
