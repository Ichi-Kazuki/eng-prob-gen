"""Regression coverage for the validation review findings."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

import orchestrator as core  # noqa: E402
import pilot_driver  # noqa: E402
import validation_driver  # noqa: E402
from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)


def valid_v2_review() -> dict:
    path = ROOT / "tests" / "fixtures" / "we_reviewer_v2_valid_record.json"
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8"))["items"][0])


class ConsensusFormatGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = {
            "item_id": "format-gate-001",
            "section": "Written Expression",
            "correct_answer": "B",
        }
        self.reviewer = valid_v2_review()
        self.reviewer["item_id"] = self.generator["item_id"]
        self.solver = {
            "item_id": self.generator["item_id"],
            "section": "Written Expression",
            "solver_answer": "B",
            "confidence": "HIGH",
            "ambiguity_detected": False,
        }

    def test_format_warn_is_allowed_but_top_level_and_nested_failures_block(self) -> None:
        accepted = core.evaluate_consensus(
            self.generator, self.reviewer, self.solver, core.load_config()
        )
        self.assertTrue(accepted.auto_accept)

        for location in ("top_level", "nested"):
            with self.subTest(location=location):
                reviewer = copy.deepcopy(self.reviewer)
                if location == "top_level":
                    reviewer["format_validity"] = "FAIL"
                else:
                    reviewer["checks"]["format_validity"] = "FAIL"
                result = core.evaluate_consensus(
                    self.generator, reviewer, self.solver, core.load_config()
                )
                self.assertFalse(result.auto_accept)
                self.assertIn("format_validity", " ".join(result.failed_conditions))


class ProvenanceInvariantTests(unittest.TestCase):
    def record(self, state: str = core.State.REJECTED) -> dict:
        candidate = core.Candidate("provenance-fix-001", "concept", "Structure")
        candidate.transition(state, "test terminal state")
        return core.build_provenance_record(
            candidate, core.load_versions(core.load_config())
        )

    def test_state_allowlist_rejects_unknown_state(self) -> None:
        from validate_provenance import validate_contract

        record = self.record()
        record["state"] = "BOGUS"
        record["state_history"][-1] = "BOGUS"
        record["qa_audit"]["state"] = "BOGUS"
        record["qa_audit"]["state_history"][-1] = "BOGUS"
        self.assertTrue(validate_contract(record))

    def test_solver_output_is_rejected_before_solver_terminal_state(self) -> None:
        from validate_provenance import validate_contract

        for state in (core.State.REVIEWING, core.State.REJECTED):
            with self.subTest(state=state):
                record = self.record(state)
                record["solver"] = {"answer": "B", "confidence": "HIGH"}
                record["qa_audit"]["solver"] = record["solver"]
                errors = validate_contract(record)
                self.assertTrue(any("solver" in error for error in errors), errors)

    def test_qa_audit_applies_formal_reviewer_and_solver_contracts(self) -> None:
        from validate_provenance import validate_contract

        record = self.record()
        record["qa_audit"]["reviewer"] = {"judgment_mode": "CONTRACT_REPLAY_ONLY"}
        record["qa_audit"]["solver"] = {"item_id": "wrong-shape"}
        errors = validate_contract(record)
        self.assertTrue(any("qa_audit.reviewer" in error for error in errors), errors)
        self.assertTrue(any("qa_audit.solver" in error for error in errors), errors)

    def test_accepted_item_requires_fields_for_its_section(self) -> None:
        common = {
            "item_id": "accepted-fix-001",
            "difficulty": "MEDIUM",
            "vocabulary_domain": "science",
            "spec_version": "1",
            "taxonomy_version": "1",
            "correct_answer": "A",
            "explanation": {"answer_explanation": "because"},
            "taxonomy": {
                "primary_target": "target",
                "subtype": "subtype",
                "secondary_features": [],
            },
        }
        schema = load_schema(ROOT / "orchestrator" / "schemas" / "accepted_item.schema.json")
        structure_errors = schema_errors({**common, "section": "Structure"}, schema)
        written_errors = schema_errors({**common, "section": "Written Expression"}, schema)
        self.assertTrue(any("stem" in error or "options" in error for error in structure_errors))
        self.assertTrue(any("sentence" in error or "marked_parts" in error for error in written_errors))

    def test_accepted_item_nested_text_must_be_nonempty(self) -> None:
        accepted = {
            "item_id": "accepted-fix-002",
            "section": "Structure",
            "difficulty": "MEDIUM",
            "vocabulary_domain": "science",
            "spec_version": "1",
            "taxonomy_version": "1",
            "stem": "Choose the correct form.",
            "options": {letter: f"option {letter}" for letter in "ABCD"},
            "correct_answer": "A",
            "explanation": {
                "answer_explanation": "The finite verb agrees with the subject.",
                "distractor_rationales": {
                    letter: f"rationale {letter}" for letter in "ABCD"
                },
            },
            "taxonomy": {
                "primary_target": "CLAUSE_STRUCTURE",
                "subtype": "agreement",
                "secondary_features": ["subject-verb agreement"],
            },
        }
        schema = load_schema(ROOT / "orchestrator" / "schemas" / "accepted_item.schema.json")
        for location in (
            ("options", "A"),
            ("explanation", "answer_explanation"),
            ("explanation", "distractor_rationales", "A"),
            ("taxonomy", "primary_target"),
            ("taxonomy", "subtype"),
        ):
            with self.subTest(location=location):
                invalid = copy.deepcopy(accepted)
                target = invalid
                for key in location[:-1]:
                    target = target[key]
                target[location[-1]] = ""
                self.assertTrue(schema_errors(invalid, schema), location)

    def test_exhausted_invalid_stage_payloads_are_quarantined(self) -> None:
        from validate_provenance import validate_contract

        config = core.load_config()
        versions = core.load_versions(config)
        generator = json.loads(
            (ROOT / "analysis/generator_smoke_test.json").read_text(encoding="utf-8")
        )["items"][0]

        reviewer_candidate = core.Candidate(
            "exhausted-reviewer-001", "concept", generator["section"]
        )
        reviewer_candidate.generator_item = copy.deepcopy(generator)
        with mock.patch.object(core, "run_schema_validator", return_value=(True, "ok")):
            core.process_generation_output(reviewer_candidate, config)
        reviewer_candidate.reviewer_item = {"item_id": reviewer_candidate.item_id}
        with mock.patch.object(core, "run_schema_validator", return_value=(False, "bad reviewer")):
            for _ in range(config["retry_policy"]["max_generation_validation_retries"] + 1):
                core.process_review_output(reviewer_candidate, config)

        self.assertIsNone(reviewer_candidate.reviewer_item)
        self.assertEqual(
            validate_contract(core.build_provenance_record(reviewer_candidate, versions)), []
        )

        invalid_generator = core.Candidate(
            "exhausted-generator-001", "concept", "not-a-section"
        )
        invalid_generator.generator_item = {"item_id": invalid_generator.item_id}
        with mock.patch.object(core, "run_schema_validator", return_value=(False, "bad generator")):
            for _ in range(config["retry_policy"]["max_generation_validation_retries"] + 1):
                core.process_generation_output(invalid_generator, config)

        record = core.build_provenance_record(invalid_generator, versions)
        self.assertEqual(record["section"], "Structure")
        self.assertEqual(validate_contract(record), [])

        solver_candidate = core.Candidate(
            "exhausted-solver-001", "concept", generator["section"]
        )
        solver_candidate.generator_item = copy.deepcopy(generator)
        reviewer = json.loads(
            (ROOT / "analysis/reviewer_smoke_test.json").read_text(encoding="utf-8")
        )["items"][0]
        reviewer["item_id"] = solver_candidate.item_id
        solver_candidate.reviewer_item = reviewer
        solver_candidate.state = core.State.SOLVING
        solver_candidate.state_history = [
            core.State.GENERATED,
            core.State.REVIEWING,
            core.State.SOLVING,
        ]
        solver_candidate.solver_item = {"item_id": solver_candidate.item_id}
        with mock.patch.object(
            core, "blind_for_solver", return_value={
                "item_id": solver_candidate.item_id,
                "section": "Structure",
                "stem": "Choose one.",
                "options": {letter: f"option {letter}" for letter in "ABCD"},
            }
        ), mock.patch.object(core, "run_schema_validator", return_value=(False, "bad solver")):
            for _ in range(config["retry_policy"]["max_generation_validation_retries"] + 1):
                core.process_solver_stage(
                    solver_candidate, config, solver_candidate.solver_item
                )

        self.assertIsNone(solver_candidate.solver_item)
        self.assertEqual(
            validate_contract(core.build_provenance_record(solver_candidate, versions)), []
        )


class LegacySolverBatchCompatibilityTests(unittest.TestCase):
    def _assert_legacy_batch_is_restored(self, driver, state_name: str, batch_name: str) -> None:
        candidate = core.Candidate("legacy-solver-001", "legacy-solver-001", "Structure")
        candidate.state = core.State.SOLVING
        candidate.state_history = [core.State.GENERATED, core.State.REVIEWING, core.State.SOLVING]
        record = core.candidate_to_dict(candidate)
        record.pop("solver_input")
        batch_item = {
            "item_id": candidate.item_id,
            "section": "Structure",
            "stem": "Choose one.",
            "options": {letter: f"option {letter}" for letter in "ABCD"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            state_path.write_text(
                json.dumps({candidate.item_id: record}), encoding="utf-8"
            )
            (root / batch_name).write_text(
                json.dumps({"items": [batch_item]}), encoding="utf-8"
            )
            with mock.patch.object(driver, "STATE_PATH", state_path), mock.patch.object(
                driver, "PILOT_DIR" if state_name == "pilot" else "VALIDATION_DIR", root
            ):
                restored = driver.load_state()[candidate.item_id]
            self.assertEqual(restored.solver_input, batch_item)

    def test_pilot_restores_legacy_in_flight_solver_batch(self) -> None:
        self._assert_legacy_batch_is_restored(pilot_driver, "pilot", "solver_input_batch.json")

    def test_validation_restores_legacy_in_flight_solver_batch(self) -> None:
        self._assert_legacy_batch_is_restored(
            validation_driver, "validation", "validation_solver_input_batch.json"
        )


class SchemaEncodingRuntimeTests(unittest.TestCase):
    def test_invalid_utf8_schema_is_a_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.schema.json"
            path.write_bytes(b"{\xff}")
            with self.assertRaises(SchemaValidationRuntimeError):
                load_schema(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
