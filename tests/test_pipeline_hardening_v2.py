"""Regression tests for run snapshots, state semantics, and Solver isolation."""

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
sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))

import orchestrator as core  # noqa: E402
from runtime.adapters import ClaudeRuntime, CodexRuntime, InvocationRequest  # noqa: E402
from shared.json_io import JsonPersistenceError  # noqa: E402
from format_planner import get_official_profile  # noqa: E402


def fixture(path: str, index: int = 0) -> dict:
    return copy.deepcopy(json.loads((ROOT / path).read_text(encoding="utf-8"))["items"][index])


def solving_candidate(index: int = 0) -> tuple[core.Candidate, dict, dict, dict]:
    generator = fixture("analysis/generator_smoke_test.json", index)
    reviewer = fixture("analysis/reviewer_smoke_test.json", index)
    solver = fixture("analysis/solver_smoke_test.json", index)
    candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
    candidate.state = core.State.SOLVING
    candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
    candidate.generator_item = generator
    candidate.reviewer_item = reviewer
    return candidate, generator, reviewer, solver


def accepted_candidate() -> core.Candidate:
    candidate, _, _, solver = solving_candidate(0)
    with mock.patch.object(core, "run_schema_validator", return_value=(True, "")):
        return core.process_solver_stage(candidate, core.load_config(), solver)


class RunManifestRegressionTests(unittest.TestCase):
    def test_manifest_is_persisted_and_provenance_uses_snapshot_after_config_drift(self) -> None:
        config = core.load_config()
        manifest = core.build_run_manifest(config)
        candidate = accepted_candidate()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            core.save_candidate_state(path, {candidate.item_id: candidate}, run_manifest=manifest)
            changed_config = copy.deepcopy(config)
            changed_config["auto_accept"]["allowed_solver_confidence"] = ["LOW"]
            with mock.patch.object(core, "load_config", return_value=changed_config):
                loaded, loaded_manifest = core.load_state_bundle(path)
                record = core.build_provenance_record(
                    loaded[candidate.item_id],
                    core.manifest_versions(loaded_manifest),
                    run_manifest=loaded_manifest,
                )

        self.assertEqual(loaded_manifest, manifest)
        self.assertEqual(record["versions"], manifest["versions"])
        self.assertEqual(record["run_manifest_id"], manifest["manifest_id"])
        self.assertEqual(record["run_manifest_sha256"], manifest["manifest_sha256"])

    def test_validator_drift_is_detected_but_does_not_change_snapshot_provenance(self) -> None:
        manifest = core.build_run_manifest(core.load_config())
        candidate = accepted_candidate()
        changed_hash = "sha256:" + ("f" * 64)
        with mock.patch.object(
            core,
            "_manifest_file_hashes",
            return_value={
                **manifest["hashes"],
                "validators": {**manifest["hashes"]["validators"], "solver": changed_hash},
            },
        ):
            self.assertIn("validators.solver", core.current_version_mismatches(manifest))
        with mock.patch.object(core, "load_versions", side_effect=AssertionError("must use snapshot")):
            record = core.build_provenance_record(
                candidate,
                core.manifest_versions(manifest),
                run_manifest=manifest,
            )
        self.assertEqual(record["run_manifest_sha256"], manifest["manifest_sha256"])

    def test_legacy_manifest_version_is_rejected_without_silent_upgrade(self) -> None:
        manifest = core.build_run_manifest(core.load_config())
        manifest["manifest_schema_version"] = 2
        manifest.pop("environment")
        with self.assertRaisesRegex(ValueError, "legacy.*explicit migration"):
            core.validate_run_manifest(manifest)

    def test_legacy_state_without_manifest_remains_readable(self) -> None:
        candidate = core.Candidate("legacy-001", "legacy-001", "Structure")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            core.save_candidate_state(path, {candidate.item_id: candidate})
            loaded, manifest = core.load_state_bundle(path)
        self.assertIsNone(manifest)
        self.assertEqual(loaded[candidate.item_id].state, core.State.GENERATED)
        self.assertTrue(loaded[candidate.item_id].legacy_compatibility)

    def test_corrupt_manifest_hash_and_id_fail_closed(self) -> None:
        manifest = core.build_run_manifest(core.load_config())
        candidate = accepted_candidate()
        for field, value in (
            ("manifest_sha256", "sha256:" + ("0" * 64)),
            ("manifest_id", "run-manifest-" + ("0" * 24)),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                core.save_candidate_state(path, {candidate.item_id: candidate}, run_manifest=manifest)
                document = json.loads(path.read_text(encoding="utf-8"))
                document["run_manifest"][field] = value
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(core.JsonPersistenceError):
                    core.load_candidate_state(path)

    def test_run_snapshot_policy_is_used_for_accepted_validation(self) -> None:
        config = core.load_config()
        manifest = core.build_run_manifest(config)
        candidate = accepted_candidate()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            core.save_candidate_state(path, {candidate.item_id: candidate}, run_manifest=manifest)
            changed = copy.deepcopy(core.load_config())
            changed["auto_accept"]["allowed_solver_confidence"] = ["LOW"]
            with mock.patch.object(core, "load_config", return_value=changed):
                loaded = core.load_candidate_state(path)
        self.assertEqual(loaded[candidate.item_id].state, core.State.ACCEPTED)
        self.assertEqual(
            loaded[candidate.item_id].acceptance_policy,
            core.acceptance_policy_record(config),
        )

    def test_current_format_truncated_history_is_rejected(self) -> None:
        config = core.load_config()
        manifest = core.build_run_manifest(config)
        candidate = accepted_candidate()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            core.save_candidate_state(path, {candidate.item_id: candidate}, run_manifest=manifest)
            document = json.loads(path.read_text(encoding="utf-8"))
            document["candidates"][candidate.item_id]["state_history"] = [core.State.ACCEPTED]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(JsonPersistenceError, "start with GENERATED"):
                core.load_candidate_state(path)

    def test_current_format_tampered_acceptance_policy_is_rejected(self) -> None:
        config = core.load_config()
        manifest = core.build_run_manifest(config)
        candidate = accepted_candidate()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            core.save_candidate_state(path, {candidate.item_id: candidate}, run_manifest=manifest)
            document = json.loads(path.read_text(encoding="utf-8"))
            policy = document["candidates"][candidate.item_id]["acceptance_policy"]
            policy["allowed_solver_confidence"] = ["LOW"]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(JsonPersistenceError, "acceptance_policy"):
                core.load_candidate_state(path)


class PersistedStateSemanticInvariantTests(unittest.TestCase):
    def _candidate(self, state: str, index: int = 0) -> core.Candidate:
        generator = fixture("analysis/generator_smoke_test.json", index)
        candidate = core.Candidate(generator["item_id"], generator["item_id"], generator["section"])
        candidate.generator_item = generator
        candidate.state = state
        candidate.state_history = [core.State.GENERATED]
        return candidate

    def test_normal_states_are_loadable(self) -> None:
        generated = self._candidate(core.State.GENERATED)
        reviewing = self._candidate(core.State.REVIEWING)
        reviewing.state_history = [core.State.GENERATED, core.State.REVIEWING]

        solving, _, _, _ = solving_candidate(0)
        revise = self._candidate(core.State.REVISE_REQUIRED, 2)
        revise.reviewer_item = fixture("analysis/reviewer_smoke_test.json", 2)
        revise.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.REVISE_REQUIRED]

        rejected = self._candidate(core.State.REJECTED)
        rejected.reviewer_item = fixture("analysis/reviewer_smoke_test.json", 0)
        rejected.reviewer_item["verdict"] = "REJECT"
        rejected.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.REJECTED]

        manual = solving_candidate(0)[0]
        manual.state = core.State.MANUAL_REVIEW
        manual.state_history.append(core.State.MANUAL_REVIEW)
        manual.consensus = core.ConsensusResult(False, core.State.MANUAL_REVIEW, ["test"], ["test"])

        discarded = solving_candidate(0)[0]
        discarded.state = core.State.DISCARDED
        discarded.state_history.append(core.State.DISCARDED)
        discarded.consensus = core.ConsensusResult(False, core.State.DISCARDED, ["test"], ["solver_none"])

        failed = self._candidate(core.State.GENERATION_FAILED)
        failed.generator_item = None
        failed.state_history = [core.State.GENERATED, core.State.GENERATION_FAILED]
        failed.failure = core.FailureInfo("system", "generator", "temporary provider failure")

        validation_failed = self._candidate(core.State.VALIDATION_FAILED)
        validation_failed.state_history = [core.State.GENERATED, core.State.VALIDATION_FAILED]
        validation_failed.failure = core.FailureInfo("content", "generator", "schema mismatch")

        accepted = accepted_candidate()
        candidates = [generated, reviewing, solving, revise, rejected, manual, discarded, failed, validation_failed, accepted]
        for candidate in candidates:
            with self.subTest(state=candidate.state):
                core.validate_candidate_invariants(candidate)

    def test_rejected_with_pass_revise_with_pass_manual_without_evidence_are_rejected(self) -> None:
        rejected = self._candidate(core.State.REJECTED)
        rejected.reviewer_item = fixture("analysis/reviewer_smoke_test.json", 0)
        rejected.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.REJECTED]
        revise = self._candidate(core.State.REVISE_REQUIRED)
        revise.reviewer_item = fixture("analysis/reviewer_smoke_test.json", 0)
        revise.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.REVISE_REQUIRED]
        manual = self._candidate(core.State.MANUAL_REVIEW)
        manual.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.MANUAL_REVIEW]
        for candidate in (rejected, revise, manual):
            with self.subTest(state=candidate.state):
                with self.assertRaisesRegex(ValueError, "invariant validation failed"):
                    core.validate_candidate_invariants(candidate)

    def test_history_must_start_with_generated(self) -> None:
        candidate = self._candidate(core.State.REVIEWING)
        candidate.state_history = [core.State.REVIEWING]
        with self.assertRaisesRegex(ValueError, "start with GENERATED"):
            core.validate_candidate_invariants(candidate)


class IsolatedSolverWorkspaceTests(unittest.TestCase):
    def _request(self, tmp: Path, section: str) -> InvocationRequest:
        if section == "Structure":
            prompt = 'BLINDED INPUT: {"item_id":"mock-001","section":"Structure","stem":"The report was completed.","options":{"A":"yesterday","B":"quickly","C":"by noon","D":"with care"}}'
        else:
            prompt = 'BLINDED INPUT: {"item_id":"mock-001","section":"Written Expression","sentence":"The report was completed yesterday.","marked_parts":{"A":"The","B":"report","C":"was completed","D":"yesterday"}}'
        return InvocationRequest(
            stage="solver",
            agent_name="toefl-itp-grammar-solver",
            agent_definition=ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md",
            prompt=prompt,
            input_keys=("item_id", "section", "stem", "options", "sentence", "marked_parts"),
            formal_output_schema=ROOT / "agents" / "toefl_itp_grammar_solver" / "schema" / "solver_output.schema.json",
            system_directive="Return only the final JSON object.",
            sandbox="read-only",  # type: ignore[arg-type]
            cwd=ROOT,
            artifact_dir=tmp,
            isolate_workspace=True,
            timeout_seconds=5,
        )

    def test_structure_and_written_expression_workspaces_are_minimal(self) -> None:
        observed: list[tuple[Path, list[str]]] = []

        def runner(command: list[str], **kwargs):
            workspace = Path(kwargs["cwd"])
            names = [str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file()]
            observed.append((workspace, names))
            self.assertFalse(workspace.is_relative_to(ROOT))
            forbidden = {
                "candidates_state.json",
                "validation_candidates_state.json",
                "provenance.json",
                "pilot_provenance.json",
                "validation_provenance.json",
                "accepted_items.json",
                "human_review_calibration_key.json",
                "human_review_results.json",
            }
            self.assertTrue(forbidden.isdisjoint({Path(name).name for name in names}))
            self.assertFalse(any(name.endswith("_sealed_key.json") for name in names))
            self.assertFalse(any("reviewer_output" in name.lower() for name in names))
            self.assertNotIn("correct_answer", " ".join(names))
            task_payload = kwargs["input"].split("TASK-SPECIFIC INVOCATION:", 1)[1]
            self.assertNotIn("correct_answer", task_payload)
            self.assertNotIn("verdict", task_payload)
            self.assertNotIn("reviewer_output", task_payload)
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text(json.dumps({
                "item_id": "mock-001",
                "section": "Written Expression",
                "solver_answer": "A",
                "confidence": "HIGH",
                "reason": "mock",
                "ambiguity_detected": False,
                "suggested_correction": "The report was completed yesterday.",
            }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = CodexRuntime(executable="codex", runner=runner, cli_version="mock")
            runtime.invoke(self._request(Path(directory), "Structure"))
            runtime.invoke(self._request(Path(directory), "Written Expression"))
        self.assertEqual(len(observed), 2)
        self.assertTrue(all(not workspace.exists() for workspace, _names in observed))

    def test_claude_also_uses_the_isolated_workspace(self) -> None:
        observed: list[Path] = []

        def runner(command: list[str], **kwargs):
            workspace = Path(kwargs["cwd"])
            observed.append(workspace)
            self.assertFalse(workspace.is_relative_to(ROOT))
            envelope = {"result": json.dumps({
                "item_id": "mock-001",
                "section": "Written Expression",
                "solver_answer": "A",
                "confidence": "HIGH",
                "reason": "mock",
                "ambiguity_detected": False,
                "suggested_correction": "The report was completed yesterday.",
            })}
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(envelope), stderr="")

        with tempfile.TemporaryDirectory() as directory:
            runtime = ClaudeRuntime(executable="claude", runner=runner, cli_version="mock")
            runtime.invoke(self._request(Path(directory), "Written Expression"))
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0].exists())


class OfficialProfileCacheTests(unittest.TestCase):
    def test_public_profile_mutation_does_not_modify_cached_profile(self) -> None:
        baseline = get_official_profile()
        expected_sentence_count = baseline["counts"]["sentence_word_count"][20]
        first = get_official_profile()
        first["counts"]["correct_answer"]["A"] = -1
        first["counts"]["sentence_word_count"][20] = -1
        first["correct_types"][0] = "tampered"

        second = get_official_profile()
        self.assertEqual(second["counts"]["correct_answer"]["A"], 24)
        self.assertEqual(second["counts"]["sentence_word_count"][20], expected_sentence_count)
        self.assertNotEqual(second["correct_types"][0], "tampered")


if __name__ == "__main__":
    unittest.main()
