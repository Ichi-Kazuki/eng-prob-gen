from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SCRIPTS = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"
PILOT = ROOT / "analysis" / "we_v2_pilot"
PATCH = ROOT / "analysis" / "we_v2_patch"
sys.path.insert(0, str(GENERATOR_SCRIPTS))
sys.path.insert(0, str(PILOT))
sys.path.insert(0, str(PATCH))

from emit_output import emit_items  # noqa: E402
from prepare_revision_outputs import canonicalize_revision  # noqa: E402
from validate_format import (  # noqa: E402
    CONFIG_PATH,
    DiagnosticsEmissionError,
    REQUIRED_DIAGNOSTIC_KEYS,
    inject_canonical_diagnostics,
    load_json,
    validate_item,
)


class GeneratorContractBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_json(CONFIG_PATH)
        cls.item = json.loads(
            (PILOT / "we_v2_pilot_final_items.json").read_text(encoding="utf-8")
        )["items"][0]

    def test_malformed_geometry_and_metadata_fail_closed(self) -> None:
        mutations = {
            "sentence": lambda item: item.__setitem__("sentence", 17),
            "span": lambda item: item["marked_parts"].__setitem__("B", ["not", "a", "string"]),
            "format_metadata": lambda item: item.__setitem__("format_metadata", []),
            "grammar_metadata": lambda item: item.__setitem__("grammar_metadata", []),
            "correct_answer": lambda item: item.__setitem__("correct_answer", ["B"]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = copy.deepcopy(self.item)
                mutate(candidate)
                result = validate_item(candidate, self.config, set(), set())
                self.assertFalse(result["valid"])
                with self.assertRaises(DiagnosticsEmissionError):
                    inject_canonical_diagnostics(candidate, self.config)

        candidate = copy.deepcopy(self.item)
        candidate["grammar_metadata"]["error_scope"] = []
        self.assertFalse(validate_item(candidate, self.config, set(), set())["valid"])
        emitted, failures = emit_items([candidate], self.config)
        self.assertEqual(emitted, [])
        self.assertEqual(failures[0]["failure_kind"], "schema")

    def test_emitter_runs_schema_gate_after_injection(self) -> None:
        candidate = copy.deepcopy(self.item)
        candidate.pop("section")
        emitted, failures = emit_items([candidate], self.config)

        self.assertEqual(emitted, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["state"], "VALIDATION_FAILED")
        self.assertEqual(failures[0]["failure_kind"], "schema")
        self.assertEqual(failures[0]["stage"], "generator_schema_validation")
        self.assertTrue(any("section" in error for error in failures[0]["errors"]))

    def test_non_object_candidate_has_a_recordable_validation_result(self) -> None:
        result = validate_item(None, self.config, set(), set())

        self.assertFalse(result["valid"])
        self.assertEqual(result["diagnostics"], {})

    def test_revision_reuses_canonical_diagnostics_boundary(self) -> None:
        candidate = copy.deepcopy(self.item)
        candidate["format_metadata"]["diagnostics"] = {}
        source_errors: list[str] = []

        revised = canonicalize_revision(candidate, self.config, source_errors, candidate["item_id"])

        self.assertEqual(source_errors, [])
        self.assertEqual(set(revised["format_metadata"]["diagnostics"]), set(REQUIRED_DIAGNOSTIC_KEYS))

    def test_aggregate_records_malformed_candidates_without_indexing_them(self) -> None:
        import build_pilot_artifacts  # noqa: E402

        with tempfile.TemporaryDirectory(dir=ROOT, prefix="we-v2-aggregate-test-") as temp:
            pilot = Path(temp) / "pilot"
            raw = pilot / "raw"
            raw.mkdir(parents=True)
            shutil.copyfile(
                PILOT / "we_v2_pilot_plan.json",
                pilot / "we_v2_pilot_plan.json",
            )
            malformed = copy.deepcopy(self.item)
            malformed.pop("provenance")
            malformed["marked_parts"].pop("D")
            (raw / "gen_we-v2-live-pilot-20260824-micro-01.json").write_text(
                json.dumps({"items": [None, malformed]}), encoding="utf-8"
            )

            old_pilot, old_raw = build_pilot_artifacts.PILOT, build_pilot_artifacts.RAW
            try:
                build_pilot_artifacts.PILOT = pilot
                build_pilot_artifacts.RAW = raw
                status = build_pilot_artifacts.stage_aggregate()
            finally:
                build_pilot_artifacts.PILOT = old_pilot
                build_pilot_artifacts.RAW = old_raw

            self.assertEqual(status, 1)
            report = json.loads(
                (pilot / "we_v2_pilot_format_validation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["item_count"], 2)
            self.assertEqual(report["items"][0]["item_id"], "?")
            self.assertFalse(report["items"][0]["generator_schema_pass"])

    def test_fixture_smoke_is_not_labeled_live(self) -> None:
        import run_patch  # noqa: E402
        with tempfile.TemporaryDirectory(prefix="we-v2-patch-test-") as directory:
            old_output = run_patch.OUT
            try:
                run_patch.OUT = Path(directory)
                fixture = run_patch.run_fixture_smoke(
                    run_patch.load_json(run_patch.CONFIG_PATH),
                    run_patch.load_json(
                        ROOT / "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json"
                    ),
                    {
                        entry["id"]
                        for entry in run_patch.load_json(ROOT / "analysis/grammar_taxonomy.json")["primary_targets"]
                    },
                    {
                        entry["id"]
                        for entry in run_patch.load_json(ROOT / "specs/toefl_itp_grammar_spec.json")["tested_error_types"]
                        if entry["id"] not in {"fragment", "wrong_complementation"}
                    },
                )
            finally:
                run_patch.OUT = old_output

        self.assertFalse(fixture["metrics"].get("live_generation", False))
        self.assertIn("fixture_smoke_gate", fixture["metrics"])
        self.assertNotIn("live_smoke_gate", fixture["metrics"])


if __name__ == "__main__":
    unittest.main()
