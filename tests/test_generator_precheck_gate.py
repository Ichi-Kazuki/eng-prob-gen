"""Regression tests for the deterministic pre-Reviewer Generator gate.

These tests prove that a Generator artifact the frozen WE v2.1.3 Production
validator would reject on taxonomy, format-diagnostic, or mutation-direction
grounds is rejected by ``run_live_e2e.validate_generator_precheck`` before any
live Reviewer/Solver invocation, without any repair or hidden semantic
regeneration for a production-style ``--count 1`` attempt.
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
    / "runs"
    / "we_v2_1_3_live_one_20260827T132728"
    / "runtime"
    / "formal"
    / "generator_outputs.json"
)


def load_harness():
    path = ROOT / "scripts" / "run_live_e2e.py"
    spec = importlib.util.spec_from_file_location("live_e2e_precheck_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_valid_item() -> dict:
    return copy.deepcopy(json.loads(HISTORICAL_VALID_ITEM_PATH.read_text(encoding="utf-8"))["items"][0])


class GeneratorPrecheckUnitTests(unittest.TestCase):
    """Directly exercise validate_generator_precheck() without live invocation."""

    def setUp(self) -> None:
        self.harness = load_harness()
        self.valid_item = load_valid_item()

    def test_historical_valid_item_passes_precheck(self) -> None:
        ok, errors = self.harness.validate_generator_precheck(self.valid_item)
        self.assertTrue(ok, errors)
        self.assertEqual(errors, [])

    def test_invalid_primary_target_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["primary_target"] = "NOT_A_REAL_TAXONOMY_TARGET"
        ok, errors = self.harness.validate_generator_precheck(invalid)
        self.assertFalse(ok)
        self.assertTrue(any("primary_target is not in the grammar taxonomy" in error for error in errors), errors)

    def test_invalid_tested_error_type_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["tested_error_type"] = "not_a_real_error_type"
        ok, errors = self.harness.validate_generator_precheck(invalid)
        self.assertFalse(ok)
        self.assertTrue(any("tested_error_type is not in the grammar taxonomy" in error for error in errors), errors)

    def test_stale_format_diagnostics_are_rejected(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["format_metadata"]["diagnostics"]["format_band_status"] = "EXTREME"
        ok, errors = self.harness.validate_generator_precheck(invalid)
        self.assertFalse(ok)
        self.assertTrue(
            any("format_metadata.diagnostics.format_band_status does not match deterministic calculation" in error for error in errors),
            errors,
        )

    def test_unparseable_mutation_type_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["qa_metadata"]["mutation_type"] = "relative pronoun case error"
        ok, errors = self.harness.validate_generator_precheck(invalid)
        self.assertFalse(ok)
        self.assertTrue(
            any("mutation_safety: mutation_type must contain a parseable source -> target direction" in error for error in errors),
            errors,
        )


class GeneratorPrecheckGateIntegrationTests(unittest.TestCase):
    """Exercise the gate inside process_one with a stubbed live runtime."""

    def setUp(self) -> None:
        self.harness = load_harness()
        self.valid_item = load_valid_item()

    def _run_process_one(self, generator_item: dict, *, cohort_size: int):
        harness = self.harness
        batch_id = "precheck-test-batch"
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
            # A valid item is expected to reach the Reviewer; stop the test
            # right there with an ordinary live-stage failure so no Solver
            # contract fixture is required.
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

    def test_invalid_taxonomy_item_rejected_before_reviewer_count_one(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["primary_target"] = "NOT_A_REAL_TAXONOMY_TARGET"
        outcomes, call_counts, generator_formal = self._run_process_one(invalid, cohort_size=1)

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome["state"], "GENERATION_FAILED")
        self.assertEqual(outcome["failure"]["stage"], "generator")
        self.assertIn("primary_target is not in the grammar taxonomy", outcome["failure"]["detail"])
        # No repair: the rejected artifact is never appended to the formal set.
        self.assertEqual(generator_formal, [])
        # No consensus was ever reached for a rejected precheck attempt.
        self.assertNotIn("consensus", outcome)
        self.assertNotEqual(outcome["state"], "ACCEPTED")
        # Reviewer/Solver are never invoked, and a production-style --count 1
        # attempt does not hide a semantic regeneration behind a retry.
        self.assertEqual(call_counts.get("reviewer", 0), 0)
        self.assertEqual(call_counts.get("solver", 0), 0)
        self.assertEqual(call_counts["generator"], 1)

    def test_unparseable_mutation_type_rejected_before_reviewer_count_one(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["qa_metadata"]["mutation_type"] = "relative pronoun case error"
        outcomes, call_counts, generator_formal = self._run_process_one(invalid, cohort_size=1)

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome["state"], "GENERATION_FAILED")
        self.assertIn(
            "mutation_safety: mutation_type must contain a parseable source -> target direction",
            outcome["failure"]["detail"],
        )
        self.assertEqual(generator_formal, [])
        self.assertEqual(call_counts.get("reviewer", 0), 0)
        self.assertEqual(call_counts.get("solver", 0), 0)
        self.assertEqual(call_counts["generator"], 1)

    def test_count_one_deterministic_failure_does_not_retry(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["tested_error_type"] = "not_a_real_error_type"
        _outcomes, call_counts, _formal = self._run_process_one(invalid, cohort_size=1)
        # No hidden semantic regeneration for a production --count 1 attempt:
        # exactly one Generator invocation, no retries.
        self.assertEqual(call_counts["generator"], 1)

    def test_default_cohort_preserves_generator_retry_semantics(self) -> None:
        invalid = copy.deepcopy(self.valid_item)
        invalid["tested_error_type"] = "not_a_real_error_type"
        _outcomes, call_counts, _formal = self._run_process_one(invalid, cohort_size=self.harness.DEFAULT_COHORT_SIZE)
        # Default count=10 validation-harness semantics keep the existing
        # WE_E2E_GENERATOR_VALIDATION_RETRIES retry behavior unchanged.
        self.assertEqual(call_counts["generator"], self.harness.GENERATOR_VALIDATION_RETRIES + 1)
        self.assertEqual(call_counts.get("reviewer", 0), 0)
        self.assertEqual(call_counts.get("solver", 0), 0)

    def test_valid_historical_style_item_proceeds_to_reviewer(self) -> None:
        outcomes, call_counts, generator_formal = self._run_process_one(self.valid_item, cohort_size=1)

        self.assertEqual(call_counts["generator"], 1)
        self.assertEqual(call_counts.get("reviewer", 0), 1)
        self.assertEqual(call_counts.get("solver", 0), 0)
        self.assertEqual(len(generator_formal), 1)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["failure"]["stage"], "reviewer")


if __name__ == "__main__":
    unittest.main()
