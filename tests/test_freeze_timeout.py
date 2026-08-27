"""Focused infrastructure regressions for immutable runs and timeouts."""

from __future__ import annotations

import json
import ctypes
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from runtime.adapters import (
    PROCESS_CLEANUP_GRACE_SECONDS,
    CodexRuntime,
    InvocationRequest,
    RuntimeInvocationError,
)
from runtime.freeze import (
    NONPROTECTED_WORKSPACE_DIRTY,
    PROTECTED_FREEZE_DRIFT,
    FreezeDriftError,
    classify_workspace_status,
    create_run_freeze,
    load_run_freeze,
    verify_detached_worktree,
)


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SCHEMA = ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json"
REVIEWER_SCHEMA = ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "schema" / "reviewer_output_v2.schema.json"
SOLVER_SCHEMA = ROOT / "agents" / "toefl_itp_grammar_solver" / "schema" / "solver_output.schema.json"
GENERATOR_AGENT = ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md"
REVIEWER_AGENT = ROOT / ".claude" / "agents" / "toefl-itp-we-reviewer-v2.md"
SOLVER_AGENT = ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md"
ORCHESTRATOR_REPLAY_OUTPUTS = (
    ROOT / "analysis" / "orchestrator_adversarial_test.json",
    ROOT / "analysis" / "orchestrator_reject_path_test.json",
    ROOT / "analysis" / "orchestrator_smoke_test.json",
)


def git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _pid_exists(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_uint()
        try:
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ImmutableRunFreezeTests(unittest.TestCase):
    def test_workspace_status_separates_ephemeral_and_protected_rows(self) -> None:
        status = classify_workspace_status(
            "?? .mypy_cache/new.bin\n M runtime/freeze.py\n?? runs/pilot/out.json\n"
        )
        self.assertEqual(status["protected"]["entries"], [" M runtime/freeze.py"])
        self.assertEqual(
            status["nonprotected"]["entries"],
            ["?? .mypy_cache/new.bin", "?? runs/pilot/out.json"],
        )

    def test_allowlisted_workspace_dirtiness_does_not_invalidate_v2_freeze(self) -> None:
        statuses = iter(
            (
                "?? .pytest_cache/initial.bin\n",
                "?? .pytest_cache/new.bin\n",
                "?? .pytest_cache/new.bin\n",
            )
        )

        def fake_git(_repo_root: Path, *args: str) -> str | None:
            if args[:2] == ("rev-parse", "HEAD"):
                return "test-head\n"
            if args[:2] == ("status", "--porcelain"):
                return next(statuses)
            return None

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            protected = root / "protected.py"
            protected.write_text("original\n", encoding="utf-8")
            with mock.patch("runtime.freeze._run_git", side_effect=fake_git):
                freeze = create_run_freeze(
                    root / "freeze",
                    repo_root=ROOT,
                    protected_file_groups={"orchestrator": {"test_file": protected}},
                    canonical_schemas={"generator": GENERATOR_SCHEMA},
                    agent_instructions={},
                    provider="test",
                    codex_cli_version="test",
                    model="test",
                    reasoning_effort="unset",
                    sandbox="read-only",
                    timeout_seconds=1,
                )
                freeze.verify("after", "allowlisted-dirty")
                self.assertEqual(
                    freeze.workspace_status()["category"],
                    NONPROTECTED_WORKSPACE_DIRTY,
                )

            manifest = json.loads(freeze.manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["git_status"]["nonprotected_dirty"])

    def test_detached_worktree_preflight_requires_exact_clean_source(self) -> None:
        with mock.patch(
            "runtime.freeze._run_git",
            side_effect=("abc123\n", None),
        ), mock.patch("runtime.freeze._git_status_porcelain", return_value=""):
            self.assertEqual(verify_detached_worktree(ROOT, expected_commit="abc123"), "abc123")

    def test_detached_worktree_preflight_rejects_branch_or_protected_dirtiness(self) -> None:
        with mock.patch(
            "runtime.freeze._run_git",
            side_effect=("abc123\n", "master\n"),
        ), mock.patch("runtime.freeze._git_status_porcelain", return_value=" M runtime/freeze.py\n"):
            with self.assertRaises(ValueError) as raised:
                verify_detached_worktree(ROOT, expected_commit="abc123")
        self.assertIn("detached_head", str(raised.exception))

    def test_freeze_captures_settings_hashes_and_schema_snapshots(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            protected = root / "protected.py"
            protected.write_text("original\n", encoding="utf-8")
            freeze = create_run_freeze(
                root / "freeze",
                repo_root=ROOT,
                protected_file_groups={"orchestrator": {"test_file": protected}},
                canonical_schemas={"generator": GENERATOR_SCHEMA, "reviewer": REVIEWER_SCHEMA, "solver": SOLVER_SCHEMA},
                agent_instructions={"generator": GENERATOR_AGENT, "reviewer": REVIEWER_AGENT, "solver": SOLVER_AGENT},
                provider="codex",
                codex_cli_version="codex-cli test",
                model="gpt-5.6-luna",
                reasoning_effort="medium",
                sandbox="read-only",
                timeout_seconds=300,
            )
            manifest = json.loads(freeze.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["runtime"]["model"], "gpt-5.6-luna")
            self.assertEqual(manifest["runtime"]["reasoning_effort"], "medium")
            self.assertEqual(manifest["runtime"]["sandbox"], "read-only")
            self.assertEqual(manifest["runtime"]["timeout_seconds"], 300)
            self.assertIn("git_head", manifest)
            self.assertIn("git_status", manifest)
            self.assertIn("generator", manifest["canonical_schema_hashes"])
            self.assertIn("generator", freeze.schema_snapshots)
            self.assertEqual(
                freeze.schema_snapshots["generator"].read_bytes(),
                GENERATOR_SCHEMA.read_bytes(),
            )
            freeze.verify("test", "generator")
            loaded = load_run_freeze(freeze.manifest_path, repo_root=ROOT)
            loaded.verify("test", "loaded-generator")

            on_disk = json.loads(freeze.manifest_path.read_text(encoding="utf-8"))
            on_disk["runtime"]["model"] = "tampered"
            freeze.manifest_path.write_text(json.dumps(on_disk), encoding="utf-8")
            with self.assertRaises(FreezeDriftError) as raised_manifest:
                loaded.verify("test", "tampered-manifest")
            self.assertIn("freeze_manifest_contents", raised_manifest.exception.mismatches)

            protected.write_text("drifted\n", encoding="utf-8")
            with self.assertRaises(FreezeDriftError) as raised:
                freeze.verify("after", "generator")
            self.assertEqual(raised.exception.category, PROTECTED_FREEZE_DRIFT)
            self.assertTrue(any("protected_file_hashes" in item for item in raised.exception.mismatches))

    def test_dirty_state_change_is_detected_by_porcelain_hash(self) -> None:
        statuses = iter((" M dirty-a.txt\n", " M dirty-b.txt\n"))

        def fake_git(_repo_root: Path, *args: str) -> str | None:
            if args[:2] == ("rev-parse", "HEAD"):
                return "test-head\n"
            if args[:2] == ("status", "--porcelain"):
                return next(statuses)
            return None

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            freeze_root = Path(directory) / "freeze"
            with mock.patch("runtime.freeze._run_git", side_effect=fake_git):
                freeze = create_run_freeze(
                    freeze_root,
                    repo_root=ROOT,
                    protected_file_groups={},
                    canonical_schemas={"generator": GENERATOR_SCHEMA},
                    agent_instructions={},
                    provider="codex",
                    codex_cli_version="test",
                    model="test",
                    reasoning_effort="unset",
                    sandbox="read-only",
                    timeout_seconds=1,
                )
                with self.assertRaises(FreezeDriftError) as raised:
                    freeze.verify("after", "dirty-state")

        self.assertIn("git_status.protected_porcelain_sha256", raised.exception.mismatches)
        self.assertIn("git_status.protected_porcelain", raised.exception.mismatches)

    def test_runtime_guard_runs_before_and_after_process(self) -> None:
        events: list[tuple[str, str]] = []
        request = InvocationRequest(
            stage="reviewer",
            agent_name="dummy",
            agent_definition=Path(__file__),
            prompt="dummy",
            timeout_seconds=2,
            artifact_dir=Path(tempfile.mkdtemp(dir=ROOT)),
            freeze_guard=lambda phase, stage: events.append((phase, stage)),
        )
        try:
            runtime = CodexRuntime(
                executable=sys.executable,
                runner=subprocess.run,
                cli_version="dummy",
            )
            result = runtime._new_result(request)
            runtime._run(request, result, [sys.executable, "-c", "pass"])
            self.assertEqual(events, [("before", "reviewer"), ("after", "reviewer")])
        finally:
            if request.artifact_dir.exists():
                for path in request.artifact_dir.iterdir():
                    path.unlink(missing_ok=True)
                request.artifact_dir.rmdir()


class BoundedTimeoutTests(unittest.TestCase):
    def test_dummy_process_tree_is_terminated_and_classified_with_bounded_cleanup(self) -> None:
        parent_script = (
            "import pathlib, subprocess, sys, time; "
            "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii'); "
            "time.sleep(30)"
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            pid_file = root / "child.pid"
            request = InvocationRequest(
                stage="generator",
                agent_name="dummy",
                agent_definition=Path(__file__),
                prompt="dummy",
                timeout_seconds=0.35,
                artifact_dir=root / "artifacts",
            )
            runtime = CodexRuntime(
                executable=sys.executable,
                runner=subprocess.run,
                cli_version="dummy",
            )
            result = runtime._new_result(request)
            started = time.monotonic()
            with self.assertRaises(RuntimeInvocationError) as raised:
                runtime._run(
                    request,
                    result,
                    [sys.executable, "-c", parent_script, str(pid_file)],
                )
            elapsed = time.monotonic() - started

            self.assertEqual(raised.exception.category, "HARNESS_TIMEOUT")
            self.assertEqual(result.requested_timeout_seconds, 0.35)
            self.assertIsNotNone(result.timeout_triggered_at)
            self.assertIsNotNone(result.termination_started_at)
            self.assertIsNotNone(result.termination_completed_at)
            self.assertTrue(result.termination_method)
            self.assertIsNotNone(result.cleanup_duration_seconds)
            self.assertLessEqual(result.cleanup_duration_seconds or 0, PROCESS_CLEANUP_GRACE_SECONDS + 0.1)
            self.assertLessEqual(elapsed, 0.35 + PROCESS_CLEANUP_GRACE_SECONDS + 0.75)

            deadline = time.monotonic() + 2
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(pid_file.exists(), "dummy child did not start before timeout")
            child_pid = int(pid_file.read_text(encoding="ascii"))
            deadline = time.monotonic() + 2
            while _pid_exists(child_pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(_pid_exists(child_pid), "timeout cleanup left the dummy child alive")


class RepositoryFreezeRegressionTests(unittest.TestCase):
    def test_offline_acceptance_preserves_protected_sources_and_freeze_passes(self) -> None:
        protected_before = {path: path.read_bytes() for path in ORCHESTRATOR_REPLAY_OUTPUTS}
        status_before = git_status()
        protected_groups = {
            "orchestrator_replay_outputs": {
                path.relative_to(ROOT).as_posix(): path for path in ORCHESTRATOR_REPLAY_OUTPUTS
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            freeze = create_run_freeze(
                Path(directory) / "freeze",
                repo_root=ROOT,
                protected_file_groups=protected_groups,
                canonical_schemas={},
                agent_instructions={},
                provider="test",
                codex_cli_version="test",
                model="test",
                reasoning_effort="unset",
                sandbox="read-only",
                timeout_seconds=180,
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "orchestrator/scripts/run_acceptance_tests.py")],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                {path: path.read_bytes() for path in ORCHESTRATOR_REPLAY_OUTPUTS},
                protected_before,
            )
            self.assertEqual(git_status(), status_before)
            freeze.verify("after", "offline tests")


if __name__ == "__main__":
    unittest.main()
