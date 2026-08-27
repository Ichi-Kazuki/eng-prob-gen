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


class ConfigSchemaValidationTests(unittest.TestCase):
    def _load_variant(self, mutate) -> None:
        config = copy.deepcopy(core.load_config())
        mutate(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with mock.patch.object(core, "CONFIG_PATH", path):
                with self.assertRaisesRegex(ValueError, "schema validation failed"):
                    core.load_config()

    def test_current_config_passes_fail_fast_schema_validation(self) -> None:
        config = core.load_config()
        self.assertEqual(config["pipeline_version"], "1.0.0")

    def test_invalid_retry_policy_values_are_rejected_at_load(self) -> None:
        cases = (
            lambda config: config["retry_policy"].update(max_revision_cycles=-1),
            lambda config: config["retry_policy"].update(max_system_failure_retries=True),
            lambda config: config["retry_policy"].update(unexpected=True),
        )
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self._load_variant(mutate)

    def test_unknown_top_level_key_is_rejected_at_load(self) -> None:
        self._load_variant(lambda config: config.update(unexpected=True))

    def test_whitespace_only_pipeline_and_path_values_are_rejected(self) -> None:
        # Keep the path case explicit so this regression covers both a version
        # field and path-like fields using the shared non_empty_string shape.
        cases = (
            lambda config: config.update(pipeline_version="   "),
            lambda config: config.update(runtime_root="\t"),
            lambda config: config["paths"].update(spec_json="\n  "),
        )
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self._load_variant(mutate)

    def test_auto_accept_arrays_are_nonempty_unique_and_enum_checked(self) -> None:
        cases = (
            lambda config: config["auto_accept"].update(allowed_solver_confidence=["UNKNOWN"]),
            lambda config: config["auto_accept"].update(allowed_solver_confidence=[]),
            lambda config: config["auto_accept"].update(allowed_solver_confidence=["HIGH", "HIGH"]),
        )
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self._load_variant(mutate)

    def test_missing_and_unknown_path_keys_are_rejected_at_load(self) -> None:
        self._load_variant(lambda config: config["paths"].pop("solver_blinding_script"))
        self._load_variant(lambda config: config["paths"].update(unexpected="runs/other.json"))

    def test_run_manifest_config_snapshot_reuses_config_contract(self) -> None:
        manifest = core.build_run_manifest(core.load_config())
        manifest["config_snapshot"]["retry_policy"]["max_revision_cycles"] = -1
        with self.assertRaisesRegex(ValueError, "config_snapshot schema validation failed"):
            core.validate_run_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
