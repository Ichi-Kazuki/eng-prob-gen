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
    normalize_codex_output_for_canonical,
)
from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SCHEMA = ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json"
GENERATOR_FIXTURE = ROOT / "analysis" / "we_v2" / "we_v2_smoke_items.json"
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

    def test_canonical_valid_we_v2_generator_item_passes_transport_schema(self) -> None:
        fixture = json.loads(GENERATOR_FIXTURE.read_text(encoding="utf-8"))
        valid_item = fixture["items"][0]
        canonical_schema = load_schema(GENERATOR_SCHEMA)
        transport_schema = build_codex_transport_schema(GENERATOR_SCHEMA)

        canonical_errors = schema_errors(valid_item, canonical_schema)
        transport_errors = schema_errors(valid_item, transport_schema)

        self.assertEqual(canonical_errors, [])
        self.assertEqual(transport_errors, [])
        for name in ("format_percentile_profile", "metric_band_status"):
            diagnostics_schema = canonical_schema["properties"]["format_metadata"]["properties"]["diagnostics"]
            field_schema = diagnostics_schema["properties"][name]
            self.assertFalse(field_schema["additionalProperties"])
            self.assertEqual(set(field_schema["required"]), {
                "sentence_word_count", "marked_coverage_ratio", "unmarked_word_count",
                "mean_span_length", "max_span_length", "gap_A_B", "gap_B_C", "gap_C_D",
            })

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

    def test_const_intersects_enum_in_base_and_does_not_mutate_source(self) -> None:
        for const, expected in (("A", ["A"]), ("C", [])):
            with self.subTest(const=const):
                canonical = {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value"],
                    "properties": {
                        "value": {"type": "string", "enum": ["A", "B"], "const": const}
                    },
                }
                original = copy.deepcopy(canonical)
                transport = build_codex_transport_schema(canonical)
                self.assertEqual(transport["properties"]["value"]["enum"], expected)
                self.assertEqual(canonical, original)

    def test_const_intersects_enum_flattened_from_allof(self) -> None:
        for const, expected in (("A", ["A"]), ("C", [])):
            with self.subTest(const=const):
                canonical = {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value"],
                    "properties": {
                        "value": {
                            "allOf": [{"enum": ["A", "B"]}],
                            "const": const,
                        }
                    },
                }
                original = copy.deepcopy(canonical)
                transport = build_codex_transport_schema(canonical)
                self.assertEqual(transport["properties"]["value"]["enum"], expected)
                self.assertEqual(canonical, original)

    def test_optional_ref_is_nullable_without_mutating_its_definition(self) -> None:
        canonical = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "optional_obj": {"$ref": "#/$defs/Foo"},
            },
            "$defs": {
                "Foo": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value"],
                    "properties": {"value": {"type": "string"}},
                },
            },
        }
        original = copy.deepcopy(canonical)

        artifact = build_codex_transport_artifact(canonical)
        transport_property = artifact.schema["properties"]["optional_obj"]
        self.assertEqual(
            transport_property,
            {"anyOf": [{"$ref": "#/$defs/Foo"}, {"type": "null"}]},
        )
        self.assertEqual(canonical, original)
        self.assertEqual(schema_errors({}, canonical), [])
        self.assertEqual(schema_errors({"optional_obj": None}, artifact.schema), [])

        normalized = normalize_codex_output_for_canonical(
            {"optional_obj": None}, canonical
        )
        self.assertEqual(normalized, {})
        self.assertEqual(schema_errors(normalized, canonical), [])
        ref_relaxations = [
            entry
            for entry in artifact.provenance["removed_or_relaxed_keywords"]
            if entry["path"] == "$.properties.optional_obj" and entry["keyword"] == "$ref"
        ]
        self.assertEqual(len(ref_relaxations), 1)
        self.assertEqual(ref_relaxations[0]["replacement"], "anyOf[$ref, null]")


if __name__ == "__main__":
    unittest.main()
