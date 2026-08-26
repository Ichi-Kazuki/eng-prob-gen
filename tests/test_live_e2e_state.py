from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_harness():
    path = ROOT / "scripts" / "run_live_e2e.py"
    spec = importlib.util.spec_from_file_location("live_e2e_state_regression", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveE2EStateRoutingTests(unittest.TestCase):
    @staticmethod
    def _generator(item_id: str) -> dict:
        return {
            "item_id": item_id,
            "section": "Written Expression",
            "sentence": "The archive preserves maps for researchers.",
            "marked_parts": {
                "A": "archive",
                "B": "preserves",
                "C": "maps",
                "D": "researchers",
            },
        }

    def _run_failure(self, stage: str, category: str):
        harness = load_harness()
        batch_id = "state-test-batch"
        item_id = f"we-v2.1.3-live-{batch_id[-8:]}-001"
        generator = self._generator(item_id)
        reviewer = {"item_id": item_id, "section": "Written Expression", "verdict": "PASS"}
        generated_result = harness.InvocationResult(
            "generator",
            harness.GENERATOR_AGENT,
            "generator-invocation",
            harness.now_iso(),
            completed_at=harness.now_iso(),
            provider="test",
            model="test",
            cli_version="test",
            parsed={"items": [generator]},
        )
        reviewer_result = harness.InvocationResult(
            "reviewer",
            harness.REVIEWER_AGENT,
            "reviewer-invocation",
            harness.now_iso(),
            completed_at=harness.now_iso(),
            provider="test",
            model="test",
            cli_version="test",
            parsed={"items": [reviewer]},
        )

        def invoke(_agent, invoked_stage, *_args, **_kwargs):
            if invoked_stage == "generator":
                return generated_result
            if invoked_stage == "reviewer":
                if stage == "reviewer":
                    raise harness.LiveInvocationError(category, "reviewer test failure")
                return reviewer_result
            if stage == "solver":
                raise harness.LiveInvocationError(category, "solver test failure")
            raise AssertionError(f"unexpected invocation stage: {invoked_stage}")

        outcomes: list[dict] = []
        generator_formal: list[dict] = []
        reviewer_formal: list[dict] = []
        solver_formal: list[dict] = []
        provenance: list[dict] = []
        config = copy.deepcopy(harness.orch.load_config())
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(harness, "INPUTS", Path(directory)), \
                 mock.patch.object(harness, "invoke", side_effect=invoke), \
                 mock.patch.object(harness, "validate_schema_only", return_value=(True, [])), \
                 mock.patch.object(harness, "validate_generator_finalization", return_value=(True, [])), \
                 mock.patch.object(harness, "formal_reviewer", return_value=reviewer), \
                 mock.patch.object(harness, "validate_existing_contract", return_value=(True, [])), \
                 mock.patch.object(harness.orch, "run_schema_validator", return_value=(True, "")), \
                 mock.patch.object(
                     harness,
                     "current_runtime",
                     return_value=SimpleNamespace(provider="test", cli_version="test"),
                 ), \
                 mock.patch.object(
                     harness.orch,
                     "record_stage_failure",
                     wraps=harness.orch.record_stage_failure,
                 ) as route_failure:
                harness.process_one(
                    1,
                    batch_id,
                    config,
                    generator_formal,
                    reviewer_formal,
                    solver_formal,
                    provenance,
                    outcomes,
                )

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        expected_state = (
            harness.orch.State.VALIDATION_FAILED
            if category == "schema"
            else harness.orch.State.GENERATION_FAILED
        )
        self.assertEqual(outcome["state"], expected_state)
        self.assertEqual(outcome["state_history"][-1], expected_state)
        self.assertEqual(route_failure.call_count, 1)
        self.assertEqual(route_failure.call_args.kwargs["stage"], stage)
        self.assertEqual(
            route_failure.call_args.kwargs["kind"],
            "content" if category == "schema" else "system",
        )
        return outcome

    def test_reviewer_schema_failure_uses_orchestrator_transition(self) -> None:
        self._run_failure("reviewer", "schema")

    def test_reviewer_runtime_failure_uses_orchestrator_transition(self) -> None:
        self._run_failure("reviewer", "runtime")

    def test_solver_schema_failure_uses_orchestrator_transition(self) -> None:
        self._run_failure("solver", "schema")

    def test_solver_runtime_failure_uses_orchestrator_transition(self) -> None:
        self._run_failure("solver", "runtime")


if __name__ == "__main__":
    unittest.main()
