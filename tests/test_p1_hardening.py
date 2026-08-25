"""P1 regressions for batch joins, provenance versions, and test hygiene."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

import orchestrator as core  # noqa: E402
import pilot_driver  # noqa: E402


def generator_item() -> dict:
    document = json.loads((ROOT / "analysis/generator_smoke_test.json").read_text(encoding="utf-8"))
    return copy.deepcopy(document["items"][0])


def provenance_validator():
    path = ROOT / "orchestrator/scripts/validate_provenance.py"
    spec = importlib.util.spec_from_file_location("p1_provenance_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PilotJoinTests(unittest.TestCase):
    def test_duplicate_item_id_across_pilot_batches_is_rejected(self) -> None:
        item = generator_item()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            structure = directory / "structure.json"
            written_expression = directory / "written-expression.json"
            payload = json.dumps({"items": [item]})
            structure.write_text(payload, encoding="utf-8")
            written_expression.write_text(payload, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, item["item_id"]):
                pilot_driver.cmd_init(str(structure), str(written_expression))


class ProvenanceVersionTests(unittest.TestCase):
    REQUIRED_HASHES = {
        "orchestrator_version",
        "config_version",
        "generator_validator_version",
        "reviewer_validator_version",
        "solver_validator_version",
        "solver_blinding_version",
        "schema_runtime_version",
        "generator_schema_version",
        "reviewer_schema_version",
        "solver_schema_version",
        "provenance_schema_version",
    }

    def test_all_acceptance_inputs_have_sha256_versions(self) -> None:
        versions = core.load_versions(core.load_config())
        self.assertTrue(self.REQUIRED_HASHES.issubset(versions))
        for key in self.REQUIRED_HASHES:
            self.assertRegex(versions[key], r"^sha256:[0-9a-f]{12}$")

    def test_multi_file_hash_depends_on_names_and_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.json"
            second = Path(directory) / "b.json"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            before = core.compute_files_version([first, second])
            second.write_text("changed", encoding="utf-8")
            after = core.compute_files_version([first, second])
        self.assertNotEqual(before, after)

    def test_generated_provenance_with_extended_versions_passes_schema(self) -> None:
        item = generator_item()
        candidate = core.Candidate(item["item_id"], item["item_id"], item["section"])
        candidate.generator_item = item
        candidate.transition(core.State.REJECTED, "test terminal state")
        record = core.build_provenance_record(candidate, core.load_versions(core.load_config()))
        self.assertEqual(provenance_validator().validate_contract(record), [])


class RepositoryHygieneTests(unittest.TestCase):
    def test_acceptance_default_uses_temporary_output(self) -> None:
        source = (ROOT / "orchestrator/scripts/run_acceptance_tests.py").read_text(encoding="utf-8")
        self.assertIn("TemporaryDirectory", source)
        self.assertNotIn('output_dir or REPO_ROOT / "analysis"', source)
        self.assertIn('output_dir / "manual_review_queue.json"', source)

    def test_manifest_ci_and_ignore_contracts_exist(self) -> None:
        self.assertTrue((ROOT / "pyproject.toml").exists())
        self.assertTrue((ROOT / "requirements.lock").exists())
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for command in (
            "unittest discover",
            "run_smoke_test.py",
            "run_adversarial_test.py",
            "run_reject_path_test.py",
            "run_acceptance_tests.py",
            "run_p0_hardening_regression.py",
            "git diff --exit-code",
        ):
            self.assertIn(command, workflow)
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("__pycache__/", "*.py[cod]", ".analysis_tmp_deps/", "tmp/"):
            self.assertIn(pattern, ignore)


if __name__ == "__main__":
    unittest.main(verbosity=2)
