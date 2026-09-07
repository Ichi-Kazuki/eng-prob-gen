"""Regression tests for deterministic Generator format-diagnostics ownership.

These tests prove the fix for the WE v2.1.3 live failure where the Generator
model almost always failed the deterministic pre-Reviewer precheck on
``format_metadata.diagnostics.*`` fields alone: the runtime harness
(``scripts/run_live_e2e.py``) now makes authoritative code, not the model,
the owner of that sub-object (``enrich_generator_format_diagnostics``), and
exposes the exact canonical taxonomy IDs to the live Generator prompt
(``canonical_taxonomy_prompt_block``) instead of relying on the model to
recall or paraphrase them. Neither change weakens
``validate_generator_precheck`` itself: a genuinely invalid artifact (bad
taxonomy ID, unparseable mutation/correction direction, or a structurally
broken span that diagnostics cannot even be computed for) is still rejected
before any live Reviewer/Solver invocation.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_VALID_ITEM_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "we_v2_1_3_generator_precheck"
    / "valid_generator_item.json"
)


def load_harness():
    path = ROOT / "scripts" / "run_live_e2e.py"
    spec = importlib.util.spec_from_file_location("live_e2e_format_enrichment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_valid_item() -> dict:
    return copy.deepcopy(json.loads(HISTORICAL_VALID_ITEM_PATH.read_text(encoding="utf-8"))["items"][0])


class FormatDiagnosticsEnrichmentTests(unittest.TestCase):
    """Directly exercise enrich_generator_format_diagnostics()."""

    def setUp(self) -> None:
        self.harness = load_harness()
        self.valid_item = load_valid_item()

    def test_stale_diagnostics_are_overwritten_with_authoritative_values(self) -> None:
        original_diagnostics = copy.deepcopy(self.valid_item["format_metadata"]["diagnostics"])
        stale = copy.deepcopy(self.valid_item)
        stale["format_metadata"]["diagnostics"]["format_band_status"] = "EXTREME"
        stale["format_metadata"]["diagnostics"]["sentence_word_count"] = 999
        stale["format_metadata"]["diagnostics"]["span_token_indices"] = {"A": [0], "B": [0], "C": [0], "D": [0]}

        enriched = self.harness.enrich_generator_format_diagnostics(stale)

        # The authoritative recomputation restores exactly the historically
        # correct values, proving the deterministic calculator -- not the
        # model -- now owns this sub-object.
        self.assertEqual(enriched["format_metadata"]["diagnostics"], original_diagnostics)

    def test_enriched_stale_item_passes_precheck(self) -> None:
        stale = copy.deepcopy(self.valid_item)
        stale["format_metadata"]["diagnostics"]["format_band_status"] = "EXTREME"
        stale["format_metadata"]["diagnostics"]["mean_span_length"] = 999.0

        enriched = self.harness.enrich_generator_format_diagnostics(stale)
        ok, errors = self.harness.validate_generator_precheck(enriched)
        self.assertTrue(ok, errors)
        self.assertEqual(errors, [])

    def test_unenriched_stale_item_still_fails_precheck(self) -> None:
        """The precheck gate itself is unchanged: it still fails closed."""
        stale = copy.deepcopy(self.valid_item)
        stale["format_metadata"]["diagnostics"]["format_band_status"] = "EXTREME"
        ok, errors = self.harness.validate_generator_precheck(stale)
        self.assertFalse(ok)
        self.assertTrue(
            any("format_metadata.diagnostics.format_band_status does not match deterministic calculation" in e for e in errors),
            errors,
        )

    def test_enrichment_does_not_touch_semantic_fields(self) -> None:
        stale = copy.deepcopy(self.valid_item)
        stale["format_metadata"]["diagnostics"]["sentence_word_count"] = 1

        enriched = self.harness.enrich_generator_format_diagnostics(stale)

        for field in (
            "sentence", "marked_parts", "correct_answer", "primary_target",
            "tested_error_type", "subtype", "grammar_metadata", "qa_metadata",
            "error_explanation", "minimal_correction",
        ):
            self.assertEqual(enriched[field], self.valid_item[field], field)
        for field in (
            "target_sentence_length_region", "expected_span_profile",
            "coverage_profile", "approximate_context_profile", "span_types",
        ):
            self.assertEqual(
                enriched["format_metadata"][field],
                self.valid_item["format_metadata"][field],
                field,
            )

    def test_structurally_broken_span_is_left_unchanged_and_still_rejected(self) -> None:
        broken = copy.deepcopy(self.valid_item)
        broken["marked_parts"]["A"] = "nonexistent phrase not in the sentence"

        enriched = self.harness.enrich_generator_format_diagnostics(broken)
        # No diagnostics computation was possible; nothing was overwritten.
        self.assertEqual(enriched, broken)

        ok, errors = self.harness.validate_generator_precheck(enriched)
        self.assertFalse(ok)
        self.assertTrue(
            any("span is not an exact lexical-token sequence in sentence" in e for e in errors),
            errors,
        )


class TaxonomyPromptExposureTests(unittest.TestCase):
    """canonical_taxonomy_prompt_block() must expose the real taxonomy, not a copy."""

    def setUp(self) -> None:
        self.harness = load_harness()

    def test_block_contains_every_authoritative_primary_target(self) -> None:
        taxonomy = json.loads((ROOT / "analysis" / "grammar_taxonomy.json").read_text(encoding="utf-8"))
        block = self.harness.canonical_taxonomy_prompt_block()
        for entry in taxonomy["primary_targets"]:
            self.assertIn(entry["id"], block)

    def test_block_contains_every_authoritative_tested_error_type_except_excluded(self) -> None:
        spec = json.loads((ROOT / "specs" / "toefl_itp_grammar_spec.json").read_text(encoding="utf-8"))
        block = self.harness.canonical_taxonomy_prompt_block()
        for entry in spec["tested_error_types"]:
            if entry["id"] in {"fragment", "wrong_complementation"}:
                continue
            self.assertIn(entry["id"], block)

    def test_block_is_sourced_dynamically_not_frozen_at_import_time(self) -> None:
        """A change to the authoritative source is reflected without code edits."""
        module = self.harness._generator_validator_module()
        original = module.load_json

        def patched(path):
            data = original(path)
            if path == module.TAXONOMY_PATH:
                data = copy.deepcopy(data)
                data["primary_targets"].append({"id": "ZZZ_TEST_ONLY_TARGET", "description": "test"})
            return data

        with mock.patch.object(module, "load_json", side_effect=patched):
            block = self.harness.canonical_taxonomy_prompt_block()
        self.assertIn("ZZZ_TEST_ONLY_TARGET", block)

    def test_generator_prompt_includes_taxonomy_block_and_minimal_correction_syntax(self) -> None:
        prompt = self.harness.generator_prompt("item-1", 1, "batch-1")
        self.assertIn("CLAUSE_STRUCTURE", prompt)
        self.assertIn("agreement_error", prompt)
        self.assertIn("source -> target", prompt)
        self.assertIn("who -> whom", prompt)


class ProcessOneEnrichmentIntegrationTests(unittest.TestCase):
    """Exercise the gate inside process_one with a stubbed live runtime."""

    def setUp(self) -> None:
        self.harness = load_harness()
        self.valid_item = load_valid_item()

    def _run_process_one(self, generator_item: dict, *, cohort_size: int):
        harness = self.harness
        batch_id = "enrichment-test-batch"
        item_id = f"we-v2.1.3-live-{batch_id[-8:]}-001"
        candidate = copy.deepcopy(generator_item)
        candidate["item_id"] = item_id
        call_counts = {"generator": 0, "reviewer": 0, "solver": 0}

        generated_result = harness.InvocationResult(
            "generator",
            harness.GENERATOR_AGENT,
            "generator-invocation",
            harness.now_iso(),
            completed_at=harness.now_iso(),
            provider="test",
            model="test",
            cli_version="test",
            parsed={"items": [candidate]},
        )

        def invoke(_agent, stage, *_args, **_kwargs):
            call_counts[stage] = call_counts.get(stage, 0) + 1
            if stage == "generator":
                return generated_result
            raise harness.LiveInvocationError("runtime", f"test stop at {stage}")

        outcomes: list[dict] = []
        generator_formal: list[dict] = []
        reviewer_formal: list[dict] = []
        solver_formal: list[dict] = []
        provenance: list[dict] = []
        config = copy.deepcopy(harness.orch.load_config())
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(harness, "INPUTS", Path(directory)), \
                 mock.patch.object(harness, "invoke", side_effect=invoke), \
                 mock.patch.object(
                     harness,
                     "current_runtime",
                     return_value=SimpleNamespace(provider="test", cli_version="test"),
                 ):
                harness.process_one(
                    1,
                    batch_id,
                    config,
                    generator_formal,
                    reviewer_formal,
                    solver_formal,
                    provenance,
                    outcomes,
                    cohort_size,
                )
        return outcomes, call_counts, generator_formal

    def test_stale_diagnostics_no_longer_block_reviewer(self) -> None:
        """The exact failure shape from the live pilot now reaches Reviewer."""
        stale = copy.deepcopy(self.valid_item)
        stale["format_metadata"]["diagnostics"]["sentence_word_count"] = 999
        stale["format_metadata"]["diagnostics"]["format_band_status"] = "EXTREME"
        stale["format_metadata"]["diagnostics"]["span_token_indices"] = {"A": [0], "B": [0], "C": [0], "D": [0]}

        outcomes, call_counts, generator_formal = self._run_process_one(stale, cohort_size=1)

        self.assertEqual(call_counts["generator"], 1)
        self.assertEqual(call_counts.get("reviewer", 0), 1)
        self.assertEqual(call_counts.get("solver", 0), 0)
        self.assertEqual(len(generator_formal), 1)
        # The formal record persisted for review carries the corrected
        # diagnostics, not the model's stale declaration.
        self.assertEqual(
            generator_formal[0]["format_metadata"]["diagnostics"]["format_band_status"],
            "PREFERRED",
        )
        # The stub Reviewer invocation always raises; reaching that call (and
        # not a generator-stage GENERATION_FAILED with no formal record) is
        # the proof enrichment cleared the deterministic format precheck.
        self.assertEqual(outcomes[0]["failure"]["stage"], "reviewer")

    def test_malformed_minimal_correction_still_rejected_before_reviewer(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["minimal_correction"] = "whom"
        invalid["qa_metadata"]["minimal_correction"] = "whom"

        outcomes, call_counts, generator_formal = self._run_process_one(invalid, cohort_size=1)

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome["state"], "GENERATION_FAILED")
        self.assertIn(
            "mutation_safety: minimal_correction must contain a parseable source -> target direction",
            outcome["failure"]["detail"],
        )
        self.assertEqual(generator_formal, [])
        self.assertEqual(call_counts.get("reviewer", 0), 0)
        self.assertEqual(call_counts.get("solver", 0), 0)

    def test_valid_arrow_minimal_correction_proceeds(self) -> None:
        outcomes, call_counts, generator_formal = self._run_process_one(self.valid_item, cohort_size=1)
        self.assertEqual(call_counts["generator"], 1)
        self.assertEqual(call_counts.get("reviewer", 0), 1)
        self.assertEqual(len(generator_formal), 1)
        self.assertEqual(outcomes[0]["failure"]["stage"], "reviewer")

    def test_invalid_primary_target_still_rejected_before_reviewer_with_enrichment_active(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["primary_target"] = "subject_verb_agreement"
        invalid["tested_error_type"] = "subject_verb_agreement"
        # Also stale diagnostics, matching the live pilot failure shape, to
        # prove enrichment fixing the format dimension does not paper over a
        # genuinely invalid taxonomy choice.
        invalid["format_metadata"]["diagnostics"]["format_band_status"] = "EXTREME"

        outcomes, call_counts, generator_formal = self._run_process_one(invalid, cohort_size=1)

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome["state"], "GENERATION_FAILED")
        self.assertIn("primary_target is not in the grammar taxonomy", outcome["failure"]["detail"])
        self.assertIn("tested_error_type is not in the grammar taxonomy", outcome["failure"]["detail"])
        self.assertEqual(generator_formal, [])
        self.assertEqual(call_counts.get("reviewer", 0), 0)
        self.assertEqual(call_counts.get("solver", 0), 0)


if __name__ == "__main__":
    unittest.main()
