from __future__ import annotations

import copy
import io
import importlib.util
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
                 mock.patch.object(harness, "validate_generator_precheck", return_value=(True, [])), \
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


class LiveE2ECohortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = load_harness()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_directory = Path(self.temporary_directory.name) / "run"
        self.generator_items = json.loads(
            (ROOT / "analysis" / "we_v2" / "we_v2_smoke_items.json").read_text(encoding="utf-8")
        )["items"]
        self.reviewer_items = json.loads(
            (ROOT / "analysis" / "we_v2" / "we_v2_smoke_review.json").read_text(encoding="utf-8")
        )["items"]
        self.solver_items = json.loads(
            (ROOT / "analysis" / "we_v2" / "we_v2_smoke_solver.json").read_text(encoding="utf-8")
        )["items"]
        production_candidate = json.loads(
            (
                ROOT
                / "analysis"
                / "we_v2_1_2_grammar_pilot"
                / "runtime"
                / "generator"
                / "we_v2.1.2_grammar_pilot_001.json"
            ).read_text(encoding="utf-8")
        )
        matching_reviewer = copy.deepcopy(self.reviewer_items[1])
        matching_solver = copy.deepcopy(self.solver_items[1])
        matching_reviewer["item_id"] = production_candidate["item_id"]
        matching_solver["item_id"] = production_candidate["item_id"]
        self.generator_items[0] = production_candidate
        self.reviewer_items[0] = matching_reviewer
        self.solver_items[0] = matching_solver

    def _path_patch(self):
        runtime = self.output_directory / "runtime"
        return mock.patch.multiple(
            self.harness,
            OUT=self.output_directory,
            RUNTIME=runtime,
            FORMAL=runtime / "formal",
            PROVENANCE=runtime / "provenance",
            INPUTS=runtime / "inputs",
            LOGS=runtime / "logs",
        )

    def _run_mocked_main(self, argv: list[str], *, accepted: bool) -> tuple[int, list[int], str]:
        harness = self.harness
        orders: list[int] = []

        def process_one(
            order,
            _batch_id,
            _config,
            generator_formal,
            reviewer_formal,
            solver_formal,
            provenance_records,
            outcomes,
            _cohort_size=None,
        ):
            orders.append(order)
            generator = copy.deepcopy(self.generator_items[order - 1])
            reviewer = copy.deepcopy(self.reviewer_items[order - 1])
            solver = copy.deepcopy(self.solver_items[order - 1])
            generator_formal.append(generator)
            reviewer_formal.append(reviewer)
            solver_formal.append(solver)
            assert harness._RUN_FREEZE is not None
            for stage in ("generator", "reviewer", "solver"):
                provenance_records.append({
                    "stage": stage,
                    "provider": "offline-test",
                    "model": "offline-test",
                    "cli_version": "offline-test",
                    "live_invocation": True,
                    "contract_valid": True,
                    "contract_validated": True,
                    "formal_output_exists": True,
                    "formal_output_path": harness.FORMAL_OUTPUT_PATHS[stage],
                    "forbidden_input_fields_present": [],
                    "freeze_manifest_path": str(harness._RUN_FREEZE.manifest_path),
                    "freeze_manifest_sha256": harness._RUN_FREEZE.manifest_sha256,
                })
            state = harness.orch.State.ACCEPTED if accepted else harness.orch.State.MANUAL_REVIEW
            outcomes.append({
                "item_id": generator["item_id"],
                "state": state,
                "reviewer_verdict": reviewer["verdict"],
                "reviewer_answer": reviewer["independent_answer"],
                "solver_answer": solver["solver_answer"],
                "consensus": {
                    "auto_accept": accepted,
                    "routing": state,
                    "failed_conditions": [] if accepted else ["offline test rejection"],
                    "disagreement_reasons": [],
                },
            })

        runtime = SimpleNamespace(provider="offline-test", cli_version="offline-test")
        stdout = io.StringIO()
        with mock.patch.object(harness, "configure_runtime", return_value=runtime), \
             mock.patch.object(harness, "process_one", side_effect=process_one) as process_mock, \
             mock.patch.object(
                 harness,
                 "run_existing_tests",
                 return_value={"command": ["offline-tests"], "exit_code": 0, "passed": True},
             ), \
             mock.patch.dict(os.environ, {"WE_E2E_REPORT_ONLY": "0"}, clear=False), \
             redirect_stdout(stdout):
            exit_code = harness.main(argv)
        self.assertEqual(process_mock.call_count, len(orders))
        return exit_code, orders, stdout.getvalue()

    def test_default_count_preserves_ten_item_validation_semantics(self) -> None:
        with self._path_patch():
            exit_code, orders, stdout = self._run_mocked_main([], accepted=False)
            metrics = json.loads(
                (self.output_directory / "we_v2_1_3_live_e2e.json").read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(orders, list(range(1, 11)))
        self.assertIn("completed microbatch 10/10", stdout)
        self.assertEqual(metrics["cohort_size"], 10)
        self.assertEqual(metrics["microbatch_size"], 1)
        for gate_name in (
            "generator_schema",
            "reviewer_contract",
            "solver_contract",
            "reviewer_live_invocation",
            "solver_live_invocation",
        ):
            self.assertEqual(metrics["gates"][gate_name]["required"], 10)
        self.assertEqual(metrics["gates"]["generator_solver_agreement"]["required"], 9)
        self.assertEqual(metrics["gates"]["generator_solver_agreement"]["denominator"], 10)
        self.assertEqual(metrics["gates"]["solver_ambiguous"]["maximum"], 1)
        self.assertEqual(metrics["gates"]["reviewer_solver_structural_conflict"]["maximum"], 1)
        self.assertNotIn("single_item_production_acceptance", metrics["gates"])

    def test_count_one_runs_once_and_publishes_existing_evidence_set(self) -> None:
        with self._path_patch():
            exit_code, orders, stdout = self._run_mocked_main(["--count", "1"], accepted=True)
            metrics = json.loads(
                (self.output_directory / "we_v2_1_3_live_e2e.json").read_text(encoding="utf-8")
            )
            report = (self.output_directory / "WE_V2_1_3_LIVE_E2E_REPORT.md").read_text(encoding="utf-8")
            manifest = json.loads(
                (self.output_directory / "runtime" / self.harness.ARTIFACT_MANIFEST_FILENAME).read_text(
                    encoding="utf-8"
                )
            )
            evidence_exists = [
                (self.output_directory / relative).is_file() for relative in self.harness.EVIDENCE_ARTIFACTS
            ]

        self.assertEqual(exit_code, 0)
        self.assertEqual(orders, [1])
        self.assertNotIn(2, orders)
        self.assertIn("completed microbatch 1/1", stdout)
        self.assertIn("Scope: 1 requested fresh item", report)
        self.assertEqual(metrics["cohort_size"], 1)
        self.assertEqual(metrics["microbatch_size"], 1)
        for gate_name in (
            "generator_schema",
            "reviewer_contract",
            "solver_contract",
            "reviewer_live_invocation",
            "solver_live_invocation",
        ):
            self.assertEqual(metrics["gates"][gate_name]["required"], 1)
        self.assertEqual(metrics["gates"]["generator_solver_agreement"]["required"], 1)
        self.assertEqual(metrics["gates"]["generator_solver_agreement"]["denominator"], 1)
        self.assertEqual(metrics["gates"]["solver_ambiguous"]["maximum"], 0)
        self.assertEqual(metrics["gates"]["reviewer_solver_structural_conflict"]["maximum"], 0)
        self.assertTrue(metrics["gates"]["single_item_production_acceptance"]["ok"])
        self.assertEqual(set(manifest["files"]), set(self.harness.EVIDENCE_ARTIFACTS))
        self.assertTrue(all(evidence_exists))

    def test_count_one_nonaccepted_outcome_fails_overall(self) -> None:
        with self._path_patch():
            exit_code, orders, _stdout = self._run_mocked_main(["--count=1"], accepted=False)
            metrics = json.loads(
                (self.output_directory / "we_v2_1_3_live_e2e.json").read_text(encoding="utf-8")
            )

        self.assertEqual(orders, [1])
        self.assertEqual(exit_code, 1)
        self.assertFalse(metrics["gates"]["single_item_production_acceptance"]["ok"])

    def test_report_only_reconstructs_one_and_rejects_explicit_mismatch(self) -> None:
        with self._path_patch():
            exit_code, _orders, _stdout = self._run_mocked_main(["--count", "1"], accepted=True)
            self.assertEqual(exit_code, 0)
            with mock.patch.dict(os.environ, {"WE_E2E_REPORT_ONLY": "1"}, clear=False), \
                 mock.patch.object(self.harness, "invoke") as invoke:
                self.assertEqual(self.harness.main([]), 0)
                metrics = json.loads(
                    (self.output_directory / "we_v2_1_3_live_e2e.json").read_text(encoding="utf-8")
                )
                self.assertEqual(metrics["cohort_size"], 1)
                self.assertEqual(self.harness.main(["--count", "2"]), 2)
            invoke.assert_not_called()

    def test_cli_rejects_nonpositive_count_and_generator_probe_combination(self) -> None:
        self.assertEqual(self.harness._parse_args([]).count, 10)
        self.assertFalse(self.harness._parse_args([]).count_explicit)
        stderr = io.StringIO()
        with mock.patch.object(self.harness, "run_generator_probe") as probe, redirect_stderr(stderr):
            self.assertEqual(self.harness.main(["--count", "0"]), 2)
            self.assertEqual(self.harness.main(["--generator-probe", "--count", "1"]), 2)
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
