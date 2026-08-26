"""Regression tests for Reviewer blinding, run provenance, and queue schemas."""

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
from shared.json_io import JsonPersistenceError  # noqa: E402
from shared.reviewer_blinding import (  # noqa: E402
    canonical_reviewer_input,
    canonical_reviewer_input_sha256,
    reviewer_input_errors,
    reviewer_input_sha256,
)


def fixture(path: str, index: int = 0) -> dict:
    return copy.deepcopy(json.loads((ROOT / path).read_text(encoding="utf-8"))["items"][index])


def reviewing_candidate(index: int = 0) -> core.Candidate:
    item = fixture("analysis/generator_smoke_test.json", index)
    candidate = core.Candidate(item["item_id"], item["item_id"], item["section"])
    candidate.state = core.State.REVIEWING
    candidate.state_history = [core.State.GENERATED, core.State.REVIEWING]
    candidate.generator_item = item
    return candidate


class ReviewerBlindingBoundaryTests(unittest.TestCase):
    def test_structure_and_written_expression_use_deterministic_allowlists(self) -> None:
        cases = (
            (
                fixture("analysis/generator_smoke_test.json", 0),
                {"item_id", "section", "stem", "options"},
            ),
            (
                fixture("analysis/we_v2/we_v2_smoke_items.json", 0),
                {"item_id", "section", "sentence", "marked_parts"},
            ),
        )
        forbidden = {
            "correct_answer",
            "answer_explanation",
            "distractor_rationales",
            "minimal_correction",
            "primary_target",
            "subtype",
            "secondary_features",
            "tested_error_type",
            "difficulty",
            "grammar_metadata",
            "provenance",
            "qa_metadata",
        }
        for source, expected_keys in cases:
            with self.subTest(section=source["section"]):
                before = copy.deepcopy(source)
                first = canonical_reviewer_input(source)
                second = canonical_reviewer_input(source)
                self.assertEqual(set(first), expected_keys)
                self.assertFalse(forbidden.intersection(first))
                self.assertEqual(first, second)
                self.assertEqual(canonical_reviewer_input_sha256(source), canonical_reviewer_input_sha256(source))
                self.assertEqual(source, before)

                if source["section"] == "Structure":
                    first["options"]["A"] = "tampered"
                else:
                    first["marked_parts"]["A"] = "tampered"
                self.assertEqual(source, before)

    def test_blind_payload_digest_and_source_projection_detect_tampering(self) -> None:
        source = fixture("analysis/generator_smoke_test.json", 0)
        payload = canonical_reviewer_input(source)
        digest = reviewer_input_sha256(payload)
        self.assertEqual(reviewer_input_errors(source, payload, digest), [])

        tampered = copy.deepcopy(payload)
        tampered["stem"] = "changed"
        self.assertTrue(reviewer_input_errors(source, tampered, digest))

        wrong_digest = "sha256:" + ("0" * 64)
        self.assertTrue(reviewer_input_errors(source, payload, wrong_digest))

    def test_reviewer_batch_is_allowlisted_deterministic_and_state_bound(self) -> None:
        candidate = reviewing_candidate()
        candidates = {candidate.item_id: candidate}
        artifact = core.build_reviewer_batch_artifact(candidates)
        self.assertEqual(core.validate_reviewer_batch_artifact(artifact, candidates), [])
        self.assertEqual(artifact, core.build_reviewer_batch_artifact(candidates))
        self.assertNotIn("correct_answer", artifact["items"][0])
        self.assertNotIn("primary_target", artifact["items"][0])

        tampered = copy.deepcopy(artifact)
        tampered["items"][0]["stem"] = "tampered"
        self.assertTrue(core.validate_reviewer_batch_artifact(tampered, candidates))


class PipelineSnapshotBoundaryTests(unittest.TestCase):
    def test_current_config_and_code_drift_fail_closed(self) -> None:
        config = core.load_config()
        manifest = core.build_run_manifest(config)
        core.ensure_pipeline_snapshot_current(manifest, config)

        changed_config = copy.deepcopy(config)
        changed_config["pipeline_version"] = "changed-for-regression-test"
        with self.assertRaisesRegex(ValueError, "pipeline version snapshot mismatch"):
            core.ensure_pipeline_snapshot_current(manifest, changed_config)

        real_hash = core._hash_repo_file

        def changed_hash(path: str) -> str:
            digest = real_hash(path)
            if Path(path).as_posix().endswith("shared/reviewer_blinding.py"):
                return "sha256:" + ("f" * 64)
            return digest

        with mock.patch.object(core, "_hash_repo_file", side_effect=changed_hash):
            with self.assertRaisesRegex(ValueError, "reviewer_blinding"):
                core.ensure_pipeline_snapshot_current(manifest, config)

        def changed_we_hash(path: str) -> str:
            digest = real_hash(path)
            if Path(path).as_posix().endswith("mutation_safety.py"):
                return "sha256:" + ("e" * 64)
            return digest

        with mock.patch.object(core, "_hash_repo_file", side_effect=changed_we_hash):
            mismatches = core.current_version_mismatches(manifest, config)
        self.assertIn("validators.we_mutation_safety", mismatches)

    def test_provenance_uses_the_persisted_manifest_snapshot(self) -> None:
        config = core.load_config()
        manifest = core.build_run_manifest(config)
        self.assertEqual(
            manifest["pipeline_fingerprint"], core.manifest_pipeline_fingerprint(manifest)
        )
        self.assertIn("reviewer_blinding_version", manifest["versions"])
        self.assertIn("we_v2_versions", manifest["versions"])
        self.assertIn("reviewer_blinding", manifest["hashes"]["shared_modules"])
        self.assertIn("we_mutation_safety", manifest["hashes"]["validators"])
        self.assertIn("solver_blinding_cli", manifest["hashes"]["validators"])
        self.assertIn("taxonomy", manifest["hashes"]["policy_inputs"])
        self.assertIn("pilot", manifest["hashes"]["drivers"])


class ManualReviewQueueBoundaryTests(unittest.TestCase):
    def _current_entry(self) -> dict:
        candidate = core.Candidate("queue-current", "queue-current", "Structure")
        candidate.state = core.State.MANUAL_REVIEW
        candidate.state_history = [
            core.State.GENERATED,
            core.State.REVIEWING,
            core.State.SOLVING,
            core.State.MANUAL_REVIEW,
        ]
        candidate.generator_item = {
            "item_id": candidate.item_id,
            "section": candidate.section,
            "stem": "A question ____.",
            "options": {"A": "is", "B": "are", "C": "be", "D": "being"},
        }
        return core.build_manual_review_entry(candidate)

    def test_production_append_validates_full_entry_and_rejects_legacy_shape(self) -> None:
        entry = self._current_entry()
        config = copy.deepcopy(core.load_config())
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "queue.json"
            config["paths"]["manual_review_queue"] = str(queue)
            core.append_manual_review_queue(config, [entry])
            before = queue.read_bytes()

            legacy = {
                key: copy.deepcopy(entry[key])
                for key in (
                    "item_id", "section", "item", "disagreement_reasons",
                    "generator_answer", "reviewer_answer", "solver_answer",
                    "solver_confidence", "issues", "state_history", "possible_actions",
                )
            }
            legacy["item_id"] = "legacy-queue"
            legacy["item"]["item_id"] = "legacy-queue"
            with self.assertRaises(JsonPersistenceError):
                core.append_manual_review_queue(config, [legacy])
            self.assertEqual(queue.read_bytes(), before)

    def test_explicit_queue_migration_rejects_malformed_or_duplicate_legacy_entries(self) -> None:
        entry = self._current_entry()
        legacy = {
            key: copy.deepcopy(entry[key])
            for key in (
                "item_id", "section", "item", "disagreement_reasons",
                "generator_answer", "reviewer_answer", "solver_answer",
                "solver_confidence", "issues", "state_history", "possible_actions",
            )
        }
        migrated = core.migrate_manual_review_entry(legacy)
        self.assertEqual(core.validate_manual_review_entry(migrated), [])

        malformed = copy.deepcopy(legacy)
        del malformed["item"]
        with self.assertRaises(ValueError):
            core.migrate_manual_review_entry(malformed)

        duplicate = {"items": [legacy, copy.deepcopy(legacy)]}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            core.migrate_manual_review_queue(duplicate)

    def test_checked_in_queue_contains_only_current_non_synthetic_entries(self) -> None:
        document = json.loads((ROOT / "analysis/manual_review_queue.json").read_text(encoding="utf-8"))
        for entry in document["items"]:
            self.assertNotEqual(entry["item_id"], "synthetic-struct-001")
            self.assertEqual(core.validate_manual_review_entry(entry), [])


class ReviewerBatchDriverBoundaryTests(unittest.TestCase):
    def test_current_state_cannot_apply_review_without_canonical_batch(self) -> None:
        reviewer_path = ROOT / "analysis/reviewer_smoke_test.json"
        candidate = reviewing_candidate()
        for driver, directory_name in (
            (pilot_driver, "PILOT_DIR"),
            (validation_driver, "VALIDATION_DIR"),
        ):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "state.json"
                with mock.patch.object(driver, directory_name, root), mock.patch.object(driver, "STATE_PATH", state_path):
                    driver.save_state({candidate.item_id: copy.deepcopy(candidate)})
                    driver.reviewer_batch_path().unlink()
                    with self.assertRaisesRegex(ValueError, "canonical Reviewer batch is missing"):
                        driver.cmd_apply_review(str(reviewer_path), "missing-batch", allow_partial=True)


class RuntimeRootContainmentTests(unittest.TestCase):
    def test_normal_relative_runtime_root_is_accepted(self) -> None:
        configured = core.configured_runtime_root({"runtime_root": "runs/test"})
        self.assertEqual(configured, (core.REPO_ROOT / "runs/test").resolve())
        self.assertTrue(configured.is_relative_to(core.REPO_ROOT.resolve()))

    def test_parent_and_absolute_runtime_roots_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            core.configured_runtime_root({"runtime_root": "../outside"})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                core.configured_runtime_root({"runtime_root": directory})

    def test_symlink_to_outside_runtime_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory(
            dir=core.REPO_ROOT
        ) as inside:
            link = Path(inside) / "escape"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")
            relative = link.relative_to(core.REPO_ROOT)
            with self.assertRaises(ValueError):
                core.configured_runtime_root({"runtime_root": str(relative)})

    def test_symlink_to_path_inside_repo_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(dir=core.REPO_ROOT) as inside:
            target = Path(inside) / "target"
            target.mkdir()
            link = Path(inside) / "alias"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")
            relative = link.relative_to(core.REPO_ROOT) / "nested"
            configured = core.configured_runtime_root({"runtime_root": str(relative)})
            self.assertTrue(configured.is_relative_to(core.REPO_ROOT.resolve()))


class ContractFamilyBoundaryTests(unittest.TestCase):
    def test_we_v2_accepted_record_cannot_enter_production_finalizer(self) -> None:
        candidate = core.Candidate("we-v2-boundary", "we-v2-boundary", "Written Expression")
        candidate.state = core.State.ACCEPTED
        candidate.generator_item = {
            "item_id": candidate.item_id,
            "section": candidate.section,
            "agent_version": "Written Expression Generator v2.1",
        }
        candidate.reviewer_item = {
            "item_id": candidate.item_id,
            "section": candidate.section,
            "agent_version": "Written Expression Reviewer v2.0",
        }
        with self.assertRaisesRegex(ValueError, "cannot be passed to the production"):
            core.build_accepted_item(candidate, {"spec_version": "1", "taxonomy_version": "1"})


if __name__ == "__main__":
    unittest.main()
