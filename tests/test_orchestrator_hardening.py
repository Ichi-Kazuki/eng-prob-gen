"""Regression tests for the second Orchestrator hardening pass."""

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
from shared.solver_blinding import canonical_solver_input  # noqa: E402


def fixture(path: str, index: int = 0) -> dict:
    return copy.deepcopy(json.loads((ROOT / path).read_text(encoding="utf-8"))["items"][index])


def solving_candidate(index: int) -> tuple[core.Candidate, dict, dict, dict]:
    generator = fixture("analysis/generator_smoke_test.json", index)
    reviewer = fixture("analysis/reviewer_smoke_test.json", index)
    solver = fixture("analysis/solver_smoke_test.json", index)
    candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
    candidate.state = core.State.SOLVING
    candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
    candidate.generator_item = generator
    candidate.reviewer_item = reviewer
    return candidate, generator, reviewer, solver


class SolverCanonicalBoundaryTests(unittest.TestCase):
    def assert_solver_payload_rejected(self, payload: dict) -> None:
        candidate, _, _, solver = solving_candidate(0 if "stem" in payload else 3)
        with mock.patch.object(core, "run_schema_validator") as validator:
            result = core.process_solver_stage(
                candidate,
                core.load_config(),
                solver,
                precomputed_solver_input=payload,
            )
        self.assertEqual(result.state, core.State.VALIDATION_FAILED)
        self.assertIsNotNone(result.failure)
        self.assertEqual(result.failure.kind, "content")
        self.assertIn("canonical", result.failure.detail)
        self.assertIsNone(result.solver_input)
        validator.assert_not_called()

    def test_structure_stem_tampering_is_rejected_before_solver(self) -> None:
        _, generator, _, _ = solving_candidate(0)
        payload = canonical_solver_input(generator)
        payload["stem"] += " altered"
        self.assert_solver_payload_rejected(payload)

    def test_structure_options_tampering_is_rejected_before_solver(self) -> None:
        _, generator, _, _ = solving_candidate(0)
        payload = canonical_solver_input(generator)
        payload["options"] = copy.deepcopy(payload["options"])
        payload["options"]["A"] += " altered"
        self.assert_solver_payload_rejected(payload)

    def test_written_expression_sentence_tampering_is_rejected_before_solver(self) -> None:
        _, generator, _, _ = solving_candidate(3)
        payload = canonical_solver_input(generator)
        payload["sentence"] += " altered"
        self.assert_solver_payload_rejected(payload)

    def test_written_expression_marked_parts_tampering_is_rejected_before_solver(self) -> None:
        _, generator, _, _ = solving_candidate(3)
        payload = canonical_solver_input(generator)
        payload["marked_parts"] = copy.deepcopy(payload["marked_parts"])
        payload["marked_parts"]["B"] += " altered"
        self.assert_solver_payload_rejected(payload)

    def test_valid_precomputed_payload_still_reaches_consensus(self) -> None:
        candidate, generator, _, solver = solving_candidate(0)
        payload = canonical_solver_input(generator)
        with mock.patch.object(core, "run_schema_validator", return_value=(True, "")):
            result = core.process_solver_stage(
                candidate,
                core.load_config(),
                solver,
                precomputed_solver_input=payload,
            )
        self.assertEqual(result.state, core.State.ACCEPTED)
        self.assertEqual(result.solver_input, payload)

    def test_transient_solver_retry_reuses_correct_persisted_payload(self) -> None:
        candidate, generator, _, solver = solving_candidate(0)
        payload = canonical_solver_input(generator)
        candidate.solver_input = copy.deepcopy(payload)
        with mock.patch.object(core, "blind_for_solver", side_effect=AssertionError("must reuse input")), \
             mock.patch.object(core, "run_schema_validator", return_value=(True, "")):
            result = core.process_solver_stage(candidate, core.load_config(), solver)
        self.assertEqual(result.state, core.State.ACCEPTED)
        self.assertEqual(result.solver_input, payload)

    def test_new_blind_result_is_checked_against_canonical_payload(self) -> None:
        candidate, generator, _, solver = solving_candidate(0)
        altered = canonical_solver_input(generator)
        altered["stem"] += " altered"
        with mock.patch.object(core, "blind_for_solver", return_value=altered), \
             mock.patch.object(core, "run_schema_validator") as validator:
            result = core.process_solver_stage(candidate, core.load_config(), solver)
        self.assertEqual(result.state, core.State.VALIDATION_FAILED)
        self.assertIsNone(result.solver_input)
        validator.assert_not_called()


class SolverBlindingSharedImplementationTests(unittest.TestCase):
    def test_cli_output_equals_shared_pure_function_for_both_sections(self) -> None:
        items = [
            fixture("analysis/generator_smoke_test.json", 0),
            fixture("analysis/generator_smoke_test.json", 3),
        ]
        script = ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts" / "create_solver_input.py"
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            output_path = Path(directory) / "output.json"
            input_path.write_text(json.dumps({"items": items}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script), str(input_path), str(output_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = json.loads(output_path.read_text(encoding="utf-8"))["items"]

        self.assertEqual(output, [canonical_solver_input(item) for item in items])
        self.assertEqual(set(output[0]), {"item_id", "section", "stem", "options"})
        self.assertEqual(set(output[1]), {"item_id", "section", "sentence", "marked_parts"})
        for payload in output:
            self.assertNotIn("correct_answer", payload)
            self.assertNotIn("explanation", payload)
            self.assertNotIn("generator_metadata", payload)

    def test_persisted_state_validation_does_not_start_a_blinder_subprocess(self) -> None:
        candidate, _, _, solver = solving_candidate(0)
        with mock.patch.object(core, "run_schema_validator", return_value=(True, "")):
            candidate = core.process_solver_stage(candidate, core.load_config(), solver)
        self.assertEqual(candidate.state, core.State.ACCEPTED)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            core.save_candidate_state(path, {candidate.item_id: candidate})
            with mock.patch.object(core.subprocess, "run", side_effect=AssertionError("no subprocess")):
                loaded = core.load_candidate_state(path)
        self.assertEqual(loaded[candidate.item_id].solver_input, candidate.solver_input)


class ProvenanceSlotTests(unittest.TestCase):
    def test_provenance_keeps_planned_slot_and_exposes_final_slot_after_revision(self) -> None:
        original = fixture("analysis/generator_smoke_test.json", 0)
        revised = copy.deepcopy(original)
        revised["primary_target"] = "DIFFERENT_TARGET"
        revised["difficulty"] = "HARD" if original["difficulty"] != "HARD" else "EASY"
        revised["correct_answer"] = "B" if original["correct_answer"] != "B" else "A"

        candidate = core.Candidate(original["item_id"], original["item_id"], original["section"])
        candidate.state = core.State.REVISE_REQUIRED
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.REVISE_REQUIRED]
        candidate.generator_item = revised
        candidate.planned_slot = core.derive_slot_requirements(original)
        record = core.build_provenance_record(candidate, core.load_versions(core.load_config()))

        self.assertEqual(record["batch_slot"], candidate.planned_slot)
        self.assertEqual(record["planned_slot"], candidate.planned_slot)
        self.assertEqual(record["final_slot"], core.derive_slot_requirements(revised))
        self.assertEqual(record["batch_slot"]["correct_answer_position"], original["correct_answer"])
        self.assertEqual(core.validate_final_record(record), [])

        tracker = core.BatchIntegrityTracker()
        tracker.record_planned(candidate.generator_item, candidate.planned_slot)
        self.assertEqual(
            tracker.summary()["planned"]["correct_answer_position"],
            {original["correct_answer"]: 1},
        )


class InitGuardTests(unittest.TestCase):
    @staticmethod
    def pilot_inputs(root: Path) -> tuple[Path, Path]:
        structure = root / "structure.json"
        written_expression = root / "written_expression.json"
        structure.write_text(json.dumps({"items": [{"item_id": "pilot-s", "section": "Structure"}]}), encoding="utf-8")
        written_expression.write_text(json.dumps({"items": [{"item_id": "pilot-w", "section": "Written Expression"}]}), encoding="utf-8")
        return structure, written_expression

    @staticmethod
    def validation_inputs(root: Path) -> list[Path]:
        items = [
            {"item_id": f"validation-s-{index:03d}", "section": "Structure"}
            for index in range(45)
        ] + [
            {"item_id": f"validation-w-{index:03d}", "section": "Written Expression"}
            for index in range(75)
        ]
        paths = []
        for index in range(3):
            path = root / f"batch-{index}.json"
            path.write_text(json.dumps({"items": items[index * 40:(index + 1) * 40]}), encoding="utf-8")
            paths.append(path)
        return paths

    def test_pilot_init_requires_explicit_force_reset_and_preserves_other_artifacts(self) -> None:
        for existing, force_reset in ((False, False), (True, False), (True, True)):
            with self.subTest(existing=existing, force_reset=force_reset), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                structure, written_expression = self.pilot_inputs(root)
                state_path = root / "candidates_state.json"
                old_artifact = root / "round_feedback_old.json"
                old_artifact.write_text("keep", encoding="utf-8")
                if existing:
                    state_path.write_text("old-state", encoding="utf-8")
                with mock.patch.object(pilot_driver, "PILOT_DIR", root), \
                     mock.patch.object(pilot_driver, "STATE_PATH", state_path), \
                     mock.patch.object(pilot_driver, "process_generation_output", side_effect=lambda c, config: c):
                    if existing and not force_reset:
                        with self.assertRaisesRegex(SystemExit, "existing state file at"):
                            pilot_driver.cmd_init(str(structure), str(written_expression))
                    else:
                        pilot_driver.cmd_init(
                            str(structure), str(written_expression), force_reset=force_reset
                        )
                self.assertEqual(old_artifact.read_text(encoding="utf-8"), "keep")
                if not existing or force_reset:
                    self.assertNotEqual(state_path.read_text(encoding="utf-8"), "old-state")

    def test_validation_init_requires_explicit_force_reset_and_preserves_other_artifacts(self) -> None:
        for existing, force_reset in ((False, False), (True, False), (True, True)):
            with self.subTest(existing=existing, force_reset=force_reset), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                batch_paths = self.validation_inputs(root)
                state_path = root / "validation_candidates_state.json"
                old_artifact = root / "validation_round_feedback_old.json"
                old_artifact.write_text("keep", encoding="utf-8")
                if existing:
                    state_path.write_text("old-state", encoding="utf-8")
                with mock.patch.object(validation_driver, "VALIDATION_DIR", root), \
                     mock.patch.object(validation_driver, "STATE_PATH", state_path), \
                     mock.patch.object(validation_driver, "process_generation_output", side_effect=lambda c, config: c):
                    if existing and not force_reset:
                        with self.assertRaisesRegex(SystemExit, "existing state file at"):
                            validation_driver.cmd_init(*(str(path) for path in batch_paths))
                    else:
                        validation_driver.cmd_init(
                            *(str(path) for path in batch_paths), force_reset=force_reset
                        )
                self.assertEqual(old_artifact.read_text(encoding="utf-8"), "keep")
                if not existing or force_reset:
                    self.assertNotEqual(state_path.read_text(encoding="utf-8"), "old-state")


class FeedbackRegenerationTests(unittest.TestCase):
    def test_feedback_can_be_rebuilt_after_write_failure_in_both_drivers(self) -> None:
        generator = fixture("analysis/generator_smoke_test.json", 2)
        reviewer = fixture("analysis/reviewer_smoke_test.json", 2)
        reviewer_path = ROOT / "analysis" / "reviewer_smoke_test.json"

        for driver, directory_name, feedback_name in (
            (pilot_driver, "PILOT_DIR", "round_feedback_rebuild.json"),
            (validation_driver, "VALIDATION_DIR", "validation_round_feedback_rebuild.json"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
                candidate.state = core.State.REVIEWING
                candidate.state_history = [core.State.GENERATED, core.State.REVIEWING]
                candidate.generator_item = generator
                with mock.patch.object(driver, directory_name, root), \
                     mock.patch.object(driver, "STATE_PATH", state_path), \
                     mock.patch.object(core, "run_schema_validator", return_value=(True, "")):
                    driver.save_state({candidate.item_id: candidate})
                    with mock.patch.object(driver, "atomic_write_json", side_effect=OSError("disk full")):
                        with self.assertRaises(OSError):
                            driver.cmd_apply_review(str(reviewer_path), "rebuild")

                    saved = driver.load_state()[candidate.item_id]
                    self.assertEqual(saved.state, core.State.REVISE_REQUIRED)
                    self.assertEqual(saved.review_history[-1]["round"], "rebuild")
                    driver.cmd_rebuild_feedback("rebuild")
                    feedback = json.loads((root / feedback_name).read_text(encoding="utf-8"))

                self.assertEqual(feedback, {"items": [core.build_generator_feedback(reviewer)]})


if __name__ == "__main__":
    unittest.main()
