"""Runtime enforcement of the committed JSON Schemas.

These tests cover the two High-severity findings from the implementation
review:

High #1 - the committed ``agents/*/schema/*.schema.json`` documents were never
loaded at runtime, so a structurally invalid agent output could pass
``validate_output.py`` and (for the Generator) reach ``build_accepted_item()``
and raise an uncaught ``KeyError``.

High #2 - Solver leakage validation was a denylist of known field names, so a
leaked field under an unanticipated name was accepted.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from shared.schema_validation import (  # noqa: E402
    ENFORCED_KEYWORDS,
    UNENFORCED_KEYWORDS,
    load_schema,
    schema_errors,
)

GENERATOR_VALIDATOR = "agents/toefl_itp_grammar_generator/scripts/validate_output.py"
SOLVER_VALIDATOR = "agents/toefl_itp_grammar_solver/scripts/validate_output.py"
REVIEWER_VALIDATOR = "agents/toefl_itp_grammar_reviewer/scripts/validate_output.py"
WE_GENERATOR_VALIDATOR = "agents/toefl_itp_we_generator_v2/scripts/validate_output.py"
WE_REVIEWER_VALIDATOR = "agents/toefl_itp_we_reviewer_v2/scripts/validate_output.py"

ALL_VALIDATORS = (
    GENERATOR_VALIDATOR,
    REVIEWER_VALIDATOR,
    SOLVER_VALIDATOR,
    WE_GENERATOR_VALIDATOR,
    WE_REVIEWER_VALIDATOR,
)


def run_validator(script_relpath: str, payload) -> subprocess.CompletedProcess:
    """Run an agent validator over a payload written to a temporary file.

    Temporary output only: no tracked artifact is read or written.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "payload.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(ROOT / script_relpath), str(path)],
            capture_output=True, text=True, cwd=ROOT,
        )


def valid_structure_item() -> dict:
    return {
        "item_id": "gate-struct-001",
        "section": "Structure",
        "primary_target": "RELATIVE_CLAUSES",
        "subtype": "restrictive relative clause",
        "secondary_features": [],
        "difficulty": "MEDIUM",
        "vocabulary_domain": "administration",
        "stem": "The committee approved the proposal ____ the director had drafted.",
        "options": {"A": "which", "B": "that", "C": "what", "D": "whom"},
        "correct_answer": "B",
        "answer_explanation": "A restrictive relative clause takes 'that'.",
        "distractor_rationales": {"A": "x", "B": "correct", "C": "x", "D": "x"},
    }


def valid_solver_item() -> dict:
    return {
        "item_id": "gate-struct-001",
        "section": "Structure",
        "solver_answer": "B",
        "confidence": "HIGH",
        "reason": "Restrictive relative clause with a non-human antecedent.",
        "ambiguity_detected": False,
    }


class SharedSchemaValidatorTests(unittest.TestCase):
    """The shared engine itself, independent of any one agent."""

    SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "required": ["a", "b"],
        "properties": {
            "a": {"type": "string", "minLength": 1},
            "b": {"enum": ["X", "Y"]},
            "c": {"type": "integer", "minimum": 0, "maximum": 5},
            "d": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
            "e": {"const": "fixed"},
        },
    }

    def test_valid_value_produces_no_errors(self) -> None:
        value = {"a": "ok", "b": "X", "c": 3, "d": ["one"], "e": "fixed"}
        self.assertEqual(schema_errors(value, self.SCHEMA), [])

    def test_each_enforced_keyword_reports_a_violation(self) -> None:
        cases = {
            "required": ({"a": "ok"}, "missing required property 'b'"),
            "additionalProperties": ({"a": "ok", "b": "X", "zz": 1}, "additional property 'zz' is not allowed"),
            "type": ({"a": 1, "b": "X"}, "expected type ['string']"),
            "enum": ({"a": "ok", "b": "Z"}, "not in ['X', 'Y']"),
            "const": ({"a": "ok", "b": "X", "e": "other"}, "must equal 'fixed'"),
            "minLength": ({"a": "", "b": "X"}, "shorter than minLength 1"),
            "minimum": ({"a": "ok", "b": "X", "c": -1}, "below minimum 0"),
            "maximum": ({"a": "ok", "b": "X", "c": 9}, "above maximum 5"),
            "minItems": ({"a": "ok", "b": "X", "d": []}, "fewer than minItems 1"),
            "items": ({"a": "ok", "b": "X", "d": [""]}, "shorter than minLength 1"),
        }
        for keyword, (value, expected) in cases.items():
            with self.subTest(keyword=keyword):
                errors = schema_errors(value, self.SCHEMA)
                self.assertTrue(
                    any(expected in error for error in errors),
                    f"{keyword}: expected {expected!r} in {errors}",
                )

    def test_booleans_are_not_accepted_as_integers(self) -> None:
        errors = schema_errors({"a": "ok", "b": "X", "c": True}, self.SCHEMA)
        self.assertTrue(any("expected type ['integer']" in error for error in errors))

    def test_conditional_keywords_are_enforced_by_draft_2020_12(self) -> None:
        for keyword in ("allOf", "if", "then"):
            self.assertIn(keyword, ENFORCED_KEYWORDS)
            self.assertNotIn(keyword, UNENFORCED_KEYWORDS)

        conditional = {
            "if": {"properties": {"kind": {"const": "WE"}}},
            "then": {"required": ["correction"]},
        }
        errors = schema_errors({"kind": "WE"}, conditional)
        self.assertTrue(any("correction" in error for error in errors), errors)


class CommittedSchemasAreLoadableTests(unittest.TestCase):
    """Every agent validator must load and enforce its own committed schema."""

    SCHEMA_PATHS = (
        "agents/toefl_itp_grammar_generator/schema/structure_item.schema.json",
        "agents/toefl_itp_grammar_generator/schema/written_expression_item.schema.json",
        "agents/toefl_itp_grammar_reviewer/schema/reviewer_output.schema.json",
        "agents/toefl_itp_grammar_solver/schema/solver_output.schema.json",
        "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json",
        "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json",
    )

    def test_every_committed_schema_loads(self) -> None:
        for relpath in self.SCHEMA_PATHS:
            with self.subTest(schema=relpath):
                schema = load_schema(ROOT / relpath)
                self.assertEqual(schema.get("type"), "object")
                self.assertIs(schema.get("additionalProperties"), False)

    def test_every_validator_references_its_schema(self) -> None:
        for relpath in ALL_VALIDATORS:
            with self.subTest(validator=relpath):
                source = (ROOT / relpath).read_text(encoding="utf-8")
                self.assertIn("schema_errors", source)
                self.assertIn(".schema.json", source)

    def test_every_validator_rejects_an_unknown_top_level_key(self) -> None:
        payloads = {
            GENERATOR_VALIDATOR: valid_structure_item(),
            SOLVER_VALIDATOR: valid_solver_item(),
        }
        for relpath, item in payloads.items():
            with self.subTest(validator=relpath):
                self.assertEqual(run_validator(relpath, {"items": [item]}).returncode, 0)
                polluted = dict(item)
                polluted["an_unknown_key_nobody_enumerated"] = "x"
                result = run_validator(relpath, {"items": [polluted]})
                self.assertEqual(result.returncode, 1)
                self.assertIn("an_unknown_key_nobody_enumerated", result.stdout)


class StructureAdversarialFixtureTests(unittest.TestCase):
    """The exact case demonstrated in the implementation review."""

    FIXTURE = FIXTURES / "adversarial_structure_item.json"

    def test_fixture_is_the_documented_adversarial_shape(self) -> None:
        item = json.loads(self.FIXTURE.read_text(encoding="utf-8"))["items"][0]
        for removed in ("subtype", "secondary_features", "vocabulary_domain", "answer_explanation"):
            self.assertNotIn(removed, item)
        self.assertIn("totally_unexpected_field", item)

    def test_validator_exits_1_with_actionable_diagnostics(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / GENERATOR_VALIDATOR), str(self.FIXTURE)],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 1)
        for removed in ("subtype", "secondary_features", "vocabulary_domain", "answer_explanation"):
            self.assertIn(f"missing required property '{removed}'", result.stdout)
        self.assertIn("additional property 'totally_unexpected_field' is not allowed", result.stdout)


class SolverLeakageAllowlistTests(unittest.TestCase):
    """High #2: unknown keys are rejected by allowlist, not by denylist."""

    FIXTURE = FIXTURES / "adversarial_solver_output.json"
    LEAKED_KEYS = (
        "correct_answer_leak_via_new_name",
        "internal_chain_of_thought",
        "debug_generator_target",
    )

    def test_fixture_carries_the_three_novel_leak_fields(self) -> None:
        item = json.loads(self.FIXTURE.read_text(encoding="utf-8"))["items"][0]
        for key in self.LEAKED_KEYS:
            self.assertIn(key, item)

    def test_validator_rejects_all_three_as_unknown_properties(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / SOLVER_VALIDATOR), str(self.FIXTURE)],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 1)
        for key in self.LEAKED_KEYS:
            self.assertIn(f"additional property '{key}' is not allowed", result.stdout)

    def test_allowlist_is_the_gate_not_the_denylist(self) -> None:
        sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts"))
        import importlib

        module = importlib.import_module("validate_output")
        self.assertEqual(
            module.ALLOWED_TOP_KEYS,
            module.REQUIRED_TOP_KEYS | {"suggested_correction"},
        )
        # A novel name that appears in no denylist must still be rejected.
        item = valid_solver_item()
        item["a_name_no_denylist_ever_listed"] = "leak"
        errors: list[str] = []
        module.validate_item(item, errors)
        self.assertTrue(
            any("a_name_no_denylist_ever_listed" in error for error in errors),
            errors,
        )

    def test_legitimate_written_expression_correction_is_allowed(self) -> None:
        item = valid_solver_item()
        item["section"] = "Written Expression"
        item["suggested_correction"] = "approved"
        self.assertEqual(run_validator(SOLVER_VALIDATOR, {"items": [item]}).returncode, 0)


class OrchestratorCrashPathTests(unittest.TestCase):
    """A schema-invalid Generator output must never reach build_accepted_item.

    Before the schema gate, an item missing ``subtype``/``answer_explanation``
    passed the Generator validator (which only enumerated a few known fields)
    and then raised an uncaught KeyError inside build_accepted_item().
    """

    def _run_generation(self, item: dict):
        from orchestrator import Candidate, State, load_config, process_generation_output

        candidate = Candidate(
            item_id=item["item_id"], concept_id=item["item_id"], section=item["section"]
        )
        candidate.generator_item = item
        candidate.state = State.GENERATED
        return process_generation_output(candidate, load_config()), State

    def test_missing_answer_explanation_is_stopped_at_validation(self) -> None:
        item = valid_structure_item()
        del item["answer_explanation"]
        candidate, State = self._run_generation(item)
        self.assertEqual(candidate.state, State.GENERATED)
        self.assertIn(State.VALIDATION_FAILED, candidate.state_history)
        self.assertEqual(candidate.validation_retry_counts["generator"], 1)

    def test_missing_subtype_is_stopped_at_validation(self) -> None:
        item = valid_structure_item()
        del item["subtype"]
        candidate, State = self._run_generation(item)
        self.assertEqual(candidate.state, State.GENERATED)
        self.assertIn(State.VALIDATION_FAILED, candidate.state_history)
        self.assertEqual(candidate.validation_retry_counts["generator"], 1)

    def test_build_accepted_item_is_never_reached_for_invalid_items(self) -> None:
        from orchestrator import State, build_accepted_item

        item = valid_structure_item()
        del item["subtype"]
        del item["answer_explanation"]
        candidate, _ = self._run_generation(item)
        self.assertNotEqual(candidate.state, State.ACCEPTED)
        # build_accepted_item returns None for any non-ACCEPTED candidate, so
        # the KeyError path is unreachable once validation fails closed.
        self.assertIsNone(
            build_accepted_item(candidate, {"spec_version": "x", "taxonomy_version": "y"})
        )

    def test_a_fully_valid_item_still_passes_generation(self) -> None:
        candidate, State = self._run_generation(valid_structure_item())
        self.assertNotEqual(candidate.state, State.VALIDATION_FAILED)


if __name__ == "__main__":
    unittest.main()
