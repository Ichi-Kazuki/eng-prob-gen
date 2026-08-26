"""Tests for the Codex-only schema projection boundary."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from runtime.codex_schema import (
    build_codex_transport_artifact,
    build_codex_transport_schema,
    codex_transport_schema_errors,
)
from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SCHEMA = ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json"
SOLVER_SCHEMA = ROOT / "agents" / "toefl_itp_grammar_solver" / "schema" / "solver_output.schema.json"
SOLVER_VALIDATOR = ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts" / "validate_output.py"


def load_solver_validator():
    spec = importlib.util.spec_from_file_location("codex_schema_solver_validator", SOLVER_VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def all_keywords(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            found.append(key)
            found.extend(all_keywords(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(all_keywords(nested))
    return found


class CodexSchemaAdapterTests(unittest.TestCase):
    def test_canonical_schema_is_byte_for_byte_unchanged(self) -> None:
        before = GENERATOR_SCHEMA.read_bytes()
        canonical = json.loads(before.decode("utf-8"))
        transport = build_codex_transport_schema(GENERATOR_SCHEMA)
        self.assertNotEqual(transport, canonical)
        self.assertEqual(GENERATOR_SCHEMA.read_bytes(), before)

    def test_generator_transport_retains_shape_and_relaxes_conditionals_only(self) -> None:
        artifact = build_codex_transport_artifact(GENERATOR_SCHEMA)
        schema = artifact.schema
        keywords = all_keywords(schema)
        for keyword in ("allOf", "if", "then", "else", "not", "oneOf", "const"):
            self.assertNotIn(keyword, keywords)
        self.assertEqual(schema["type"], "object")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["section"]["enum"], ["Written Expression"])
        self.assertEqual(schema["properties"]["correct_answer"]["enum"], ["A", "B", "C", "D"])
        self.assertEqual(schema["properties"]["marked_parts"]["type"], "object")
        self.assertEqual(schema["properties"]["marked_parts"]["properties"]["A"]["type"], "string")
        self.assertIn("allOf", {entry["keyword"] for entry in artifact.provenance["removed_or_relaxed_keywords"]})
        self.assertIn("if", {entry["keyword"] for entry in artifact.provenance["removed_or_relaxed_keywords"]})
        self.assertIn("then", {entry["keyword"] for entry in artifact.provenance["removed_or_relaxed_keywords"]})
        self.assertEqual(artifact.provenance["provider"], "codex")
        self.assertTrue(artifact.provenance["canonical_validation_still_required"])
        self.assertEqual(artifact.provenance["canonical_schema_path"], str(GENERATOR_SCHEMA))
        self.assertEqual(codex_transport_schema_errors(schema), [])

    def test_canonical_valid_solver_sample_passes_transport_schema(self) -> None:
        sample = {
            "item_id": "contract-001",
            "section": "Written Expression",
            "solver_answer": "A",
            "confidence": "HIGH",
            "reason": "The candidate is grammatical only with A.",
            "ambiguity_detected": False,
            "suggested_correction": "The report was completed yesterday.",
        }
        canonical_errors = schema_errors(sample, load_schema(SOLVER_SCHEMA))
        transport = build_codex_transport_schema(SOLVER_SCHEMA)
        transport_errors = schema_errors(sample, transport)
        self.assertEqual(canonical_errors, [])
        self.assertEqual(transport_errors, [])

    def test_transport_valid_conditional_adversary_is_rejected_by_canonical_validator(self) -> None:
        canonical = load_schema(SOLVER_SCHEMA)
        transport = build_codex_transport_schema(SOLVER_SCHEMA)
        adversary = {
            "item_id": "adversarial-001",
            "section": "Written Expression",
            "solver_answer": "A",
            "confidence": "HIGH",
            "reason": "The answer label is deliberately inconsistent with the conditional invariant.",
            "ambiguity_detected": True,
            "suggested_correction": "The report was completed yesterday.",
        }
        self.assertEqual(codex_transport_schema_errors(transport), [])
        self.assertEqual(schema_errors(adversary, transport), [])
        self.assertTrue(schema_errors(adversary, canonical))
        solver_validator = load_solver_validator()
        self.assertTrue(solver_validator.validate_contract(adversary))

    def test_structural_allof_is_flattened_and_conditional_allof_is_recorded(self) -> None:
        canonical = {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind"],
            "properties": {
                "kind": {"type": "string", "enum": ["A", "B"]},
                "value": {"type": "string"},
            },
            "allOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["extra"],
                    "properties": {"extra": {"type": "integer"}},
                },
                {
                    "if": {"properties": {"kind": {"const": "A"}}},
                    "then": {"required": ["value"]},
                    "else": {"properties": {"value": {"minLength": 2}}},
                },
            ],
        }
        original = copy.deepcopy(canonical)
        artifact = build_codex_transport_artifact(canonical)
        self.assertEqual(canonical, original)
        self.assertNotIn("allOf", json.dumps(artifact.schema))
        self.assertEqual(artifact.schema["properties"]["extra"]["type"], "integer")
        sample = {"kind": "B", "value": "ok", "extra": 3}
        self.assertEqual(schema_errors(sample, artifact.schema), [])
        keywords = {entry["keyword"] for entry in artifact.provenance["removed_or_relaxed_keywords"]}
        self.assertTrue({"allOf", "if", "then", "else"}.issubset(keywords))


if __name__ == "__main__":
    unittest.main()
