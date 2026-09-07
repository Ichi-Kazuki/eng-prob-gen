from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts" / "run_live_e2e.py"

_LIVE_PILOT_ENV_VARS = (
    "WE_E2E_FINAL_PILOT",
    "WE_E2E_EXPECTED_COMMIT",
    "WE_E2E_OUTPUT_DIR",
    "WE_E2E_REPORT_ONLY",
)


def load_harness():
    spec = importlib.util.spec_from_file_location("offline_test_gate_regression", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineTestTimeoutTests(unittest.TestCase):
    def test_default_offline_test_timeout_is_900_seconds(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WE_E2E_OFFLINE_TEST_TIMEOUT_SECONDS", None)
            harness = load_harness()
        self.assertEqual(harness.OFFLINE_TEST_TIMEOUT_SECONDS, 900)

    def test_env_override_controls_offline_test_timeout(self) -> None:
        with mock.patch.dict(os.environ, {"WE_E2E_OFFLINE_TEST_TIMEOUT_SECONDS": "1800"}, clear=False):
            harness = load_harness()
        self.assertEqual(harness.OFFLINE_TEST_TIMEOUT_SECONDS, 1800)

    def test_nonpositive_override_fails_clearly(self) -> None:
        with mock.patch.dict(os.environ, {"WE_E2E_OFFLINE_TEST_TIMEOUT_SECONDS": "0"}, clear=False):
            with self.assertRaises(ValueError):
                load_harness()
        with mock.patch.dict(os.environ, {"WE_E2E_OFFLINE_TEST_TIMEOUT_SECONDS": "-5"}, clear=False):
            with self.assertRaises(ValueError):
                load_harness()

    def test_malformed_override_fails_clearly(self) -> None:
        with mock.patch.dict(os.environ, {"WE_E2E_OFFLINE_TEST_TIMEOUT_SECONDS": "not-a-number"}, clear=False):
            with self.assertRaises(ValueError):
                load_harness()


class TestSubprocessEnvironmentIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WE_E2E_OFFLINE_TEST_TIMEOUT_SECONDS", None)
            self.harness = load_harness()

    def test_run_existing_tests_passes_explicit_sanitized_env(self) -> None:
        live_env = dict(os.environ)
        live_env.update(
            {
                "WE_E2E_FINAL_PILOT": "1",
                "WE_E2E_EXPECTED_COMMIT": "deadbeef",
                "WE_E2E_OUTPUT_DIR": "/tmp/some-attempt",
                "WE_E2E_REPORT_ONLY": "1",
                "WE_E2E_UNRELATED_VAR": "keep-me",
            }
        )
        original_environ_snapshot = dict(os.environ)

        captured = {}

        def fake_run(command, cwd=None, capture_output=None, text=None, encoding=None, errors=None, timeout=None, env=None):
            captured["env"] = env
            return mock.Mock(stdout="", stderr="", returncode=0)

        with mock.patch.dict(os.environ, live_env, clear=False), \
             mock.patch.object(self.harness.subprocess, "run", side_effect=fake_run):
            self.harness.run_existing_tests()

        self.assertIsNotNone(captured["env"], "run_existing_tests() must pass an explicit env to subprocess.run")
        child_env = captured["env"]

        for key in _LIVE_PILOT_ENV_VARS:
            self.assertNotIn(key, child_env, f"{key} must be excluded from the child test environment")

        self.assertEqual(child_env.get("WE_E2E_UNRELATED_VAR"), "keep-me")

        # The parent process environment must remain untouched by run_existing_tests().
        self.assertEqual(dict(os.environ), original_environ_snapshot)


if __name__ == "__main__":
    unittest.main()
