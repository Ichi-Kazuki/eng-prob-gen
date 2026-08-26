"""Adversarial coverage for stage batches, finalization, and replay policy."""

from __future__ import annotations

import copy
import json
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
from shared import json_io  # noqa: E402


def fixture(path: str, index: int = 0) -> dict:
    return copy.deepcopy(json.loads((ROOT / path).read_text(encoding="utf-8"))["items"][index])


def reviewing_candidate(index: int = 0) -> core.Candidate:
    generator = fixture("analysis/generator_smoke_test.json", index)
    candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
    candidate.state = core.State.REVIEWING
    candidate.state_history = [core.State.GENERATED, core.State.REVIEWING]
    candidate.generator_item = generator
    return candidate


def solving_candidate(index: int = 0) -> core.Candidate:
    generator = fixture("analysis/generator_smoke_test.json", index)
    reviewer = fixture("analysis/reviewer_smoke_test.json", index)
    candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
    candidate.state = core.State.SOLVING
    candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
    candidate.generator_item = generator
    candidate.reviewer_item = reviewer
    return candidate


def terminal_candidate() -> core.Candidate:
    generator = fixture("analysis/generator_smoke_test.json", 0)
    reviewer = fixture("analysis/reviewer_smoke_test.json", 0)
    solver = fixture("analysis/solver_smoke_test.json", 0)
    candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
    candidate.state = core.State.MANUAL_REVIEW
    candidate.state_history = [
        core.State.GENERATED,
        core.State.REVIEWING,
        core.State.SOLVING,
        core.State.MANUAL_REVIEW,
    ]
    candidate.generator_item = generator
    candidate.reviewer_item = reviewer
    candidate.solver_item = solver
    candidate.solver_input = core.canonicalize_solver_input(core.load_config(), generator)
    candidate.leakage_check = {
        "ok": True,
        "problems": [],
        "blinded_keys": sorted(candidate.solver_input),
    }
    candidate.consensus = core.ConsensusResult(
        auto_accept=False,
        routing=core.State.MANUAL_REVIEW,
        failed_conditions=["solver.confidence not in ['HIGH']"],
        disagreement_reasons=["solver_confidence_low"],
    )
    return candidate


class StageItemSetTests(unittest.TestCase):
    def test_shared_stage_validation_rejects_missing_unexpected_and_accepts_exact_sets(self) -> None:
        reviewer_candidates = {
            "a": reviewing_candidate(0),
            "b": reviewing_candidate(1),
        }
        self.assertTrue(core.validate_stage_item_ids(reviewer_candidates, {"a"}, "reviewer"))
        self.assertTrue(
            core.validate_stage_item_ids(reviewer_candidates, {"a", "b", "extra"}, "reviewer")
        )
        self.assertEqual(
            core.validate_stage_item_ids(reviewer_candidates, {"a", "b"}, "reviewer"), []
        )

        solving = {"a": solving_candidate(0)}
        self.assertTrue(core.validate_stage_item_ids(solving, set(), "solver"))
        self.assertTrue(core.validate_stage_item_ids(solving, {"a", "unexpected"}, "solver"))
        self.assertEqual(core.validate_stage_item_ids(solving, {"a"}, "solver"), [])

        revision = reviewing_candidate(2)
        revision.state = core.State.REVISE_REQUIRED
        revision.state_history.append(core.State.REVISE_REQUIRED)
        revision.reviewer_item = fixture("analysis/reviewer_smoke_test.json", 2)
        self.assertTrue(core.validate_stage_item_ids({"a": revision}, set(), "revision"))

    def test_reviewer_missing_and_unexpected_ids_are_rejected_in_both_drivers(self) -> None:
        for driver, directory_name in (
            (pilot_driver, "PILOT_DIR"),
            (validation_driver, "VALIDATION_DIR"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = reviewing_candidate(0)
                input_path = root / "reviewer.json"
                input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
                with (
                    mock.patch.object(driver, directory_name, root),
                    mock.patch.object(driver, "STATE_PATH", state_path),
                ):
                    driver.save_state({candidate.item_id: candidate})
                    with self.assertRaisesRegex(ValueError, "missing expected"):
                        driver.cmd_apply_review(str(input_path), "strict")

                    unexpected_path = root / "reviewer-unexpected.json"
                    unexpected_path.write_text(
                        json.dumps({"items": [{"item_id": "unexpected"}]}), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(ValueError, "unexpected item_id"):
                        driver.cmd_apply_review(str(unexpected_path), "strict")

    def test_solver_missing_and_unexpected_ids_are_rejected_in_both_drivers(self) -> None:
        for driver, directory_name in (
            (pilot_driver, "PILOT_DIR"),
            (validation_driver, "VALIDATION_DIR"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = solving_candidate(0)
                missing_path = root / "solver-missing.json"
                missing_path.write_text(json.dumps({"items": []}), encoding="utf-8")
                with (
                    mock.patch.object(driver, directory_name, root),
                    mock.patch.object(driver, "STATE_PATH", state_path),
                ):
                    driver.save_state({candidate.item_id: candidate})
                    driver.cmd_prepare_solver_batch()
                    with self.assertRaisesRegex(ValueError, "missing expected"):
                        driver.cmd_apply_solver(str(missing_path))

                    unexpected_path = root / "solver-unexpected.json"
                    unexpected_path.write_text(
                        json.dumps({"items": [{"item_id": "unexpected"}]}), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(ValueError, "unexpected item_id"):
                        driver.cmd_apply_solver(str(unexpected_path))

    def test_revision_missing_and_unexpected_ids_are_rejected_in_both_drivers(self) -> None:
        for driver, directory_name in (
            (pilot_driver, "PILOT_DIR"),
            (validation_driver, "VALIDATION_DIR"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = reviewing_candidate(2)
                candidate.state = core.State.REVISE_REQUIRED
                candidate.state_history.append(core.State.REVISE_REQUIRED)
                candidate.reviewer_item = fixture("analysis/reviewer_smoke_test.json", 2)
                missing_path = root / "revision-missing.json"
                missing_path.write_text(json.dumps({"items": []}), encoding="utf-8")
                with (
                    mock.patch.object(driver, directory_name, root),
                    mock.patch.object(driver, "STATE_PATH", state_path),
                ):
                    driver.save_state({candidate.item_id: candidate})
                    with self.assertRaisesRegex(ValueError, "missing expected"):
                        driver.cmd_apply_revision(str(missing_path))

                    unexpected_path = root / "revision-unexpected.json"
                    unexpected_path.write_text(
                        json.dumps({"items": [{"item_id": "unexpected"}]}), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(ValueError, "unexpected item_id"):
                        driver.cmd_apply_revision(str(unexpected_path))


class FinalizationIdentityTests(unittest.TestCase):
    def test_legacy_state_cannot_be_finalized_as_current_in_both_drivers(self) -> None:
        for driver, directory_name in (
            (pilot_driver, "PILOT_DIR"),
            (validation_driver, "VALIDATION_DIR"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = terminal_candidate()
                core.save_candidate_state(state_path, {candidate.item_id: candidate})
                with (
                    mock.patch.object(driver, directory_name, root),
                    mock.patch.object(driver, "STATE_PATH", state_path),
                ):
                    with self.assertRaisesRegex(ValueError, "legacy compatibility"):
                        driver.cmd_finalize()

    def test_all_final_artifacts_share_identity_and_manifest_matches_set(self) -> None:
        for driver, directory_name, names in (
            (
                pilot_driver,
                "PILOT_DIR",
                (
                    "pilot_provenance.json",
                    "pilot_accepted_items.json",
                    "pilot_manual_review.json",
                    "pilot_failure_items.json",
                ),
            ),
            (
                validation_driver,
                "VALIDATION_DIR",
                (
                    "validation_provenance.json",
                    "validation_accepted_items.json",
                    "validation_manual_review.json",
                    "validation_failure_items.json",
                ),
            ),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = terminal_candidate()
                with (
                    mock.patch.object(driver, directory_name, root),
                    mock.patch.object(driver, "STATE_PATH", state_path),
                ):
                    driver.save_state({candidate.item_id: candidate})
                    driver.cmd_finalize()

                payloads = [json.loads((root / name).read_text(encoding="utf-8")) for name in names]
                identities = {(payload["finalize_id"], payload["state_digest"]) for payload in payloads}
                self.assertEqual(len(identities), 1)
                manifest = json.loads(
                    (root / ("pilot_finalize_manifest.json" if driver is pilot_driver else "validation_finalize_manifest.json"))
                    .read_text(encoding="utf-8")
                )
                self.assertEqual(manifest["status"], "COMPLETE")
                self.assertEqual(
                    set(manifest["files"]),
                    {"provenance", "accepted", "manual_review", "failures"},
                )
                self.assertEqual(manifest["state_digest"], payloads[0]["state_digest"])
                manifest_name = (
                    "pilot_finalize_manifest.json"
                    if driver is pilot_driver
                    else "validation_finalize_manifest.json"
                )
                self.assertEqual(
                    json_io.validate_complete_json_bundle(root, manifest_name=manifest_name), []
                )

    def test_stale_snapshot_is_rejected_before_publish_in_both_drivers(self) -> None:
        for driver, directory_name in (
            (pilot_driver, "PILOT_DIR"),
            (validation_driver, "VALIDATION_DIR"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = terminal_candidate()
                snapshot = {candidate.item_id: candidate}
                changed = copy.deepcopy(snapshot)
                changed[candidate.item_id].notes.append("concurrent update")
                with (
                    mock.patch.object(driver, directory_name, root),
                    mock.patch.object(driver, "STATE_PATH", state_path),
                ):
                    driver.save_state(snapshot)
                    with mock.patch.object(driver, "load_state", side_effect=[snapshot, changed]):
                        with self.assertRaisesRegex(ValueError, "snapshot is stale"):
                            driver.cmd_finalize()
                manifest_name = (
                    "pilot_finalize_manifest.json"
                    if driver is pilot_driver
                    else "validation_finalize_manifest.json"
                )
                self.assertFalse((root / manifest_name).exists())

    def test_artifact_failure_never_leaves_complete_manifest(self) -> None:
        for driver, directory_name, failing_name in (
            (pilot_driver, "PILOT_DIR", "pilot_manual_review.json"),
            (validation_driver, "VALIDATION_DIR", "validation_manual_review.json"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                candidate = terminal_candidate()
                real_replace = json_io.os.replace

                def fail_one(source: object, target: object) -> None:
                    if Path(target) == root / failing_name:
                        raise OSError("injected artifact failure")
                    real_replace(source, target)

                with (
                    mock.patch.object(driver, directory_name, root),
                    mock.patch.object(driver, "STATE_PATH", state_path),
                ):
                    driver.save_state({candidate.item_id: candidate})
                    with mock.patch.object(json_io.os, "replace", side_effect=fail_one):
                        with self.assertRaises(OSError):
                            driver.cmd_finalize()
                manifest_name = (
                    "pilot_finalize_manifest.json"
                    if driver is pilot_driver
                    else "validation_finalize_manifest.json"
                )
                manifest = json.loads((root / manifest_name).read_text(encoding="utf-8"))
                self.assertNotEqual(manifest["status"], "COMPLETE")
                self.assertTrue(json_io.validate_complete_json_bundle(root, manifest_name=manifest_name))


if __name__ == "__main__":
    unittest.main()
