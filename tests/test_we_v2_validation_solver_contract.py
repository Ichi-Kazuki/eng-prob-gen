"""Regression tests for the WE v2 validation Solver replay boundary."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "analysis" / "we_v2_validation" / "run_validation.py"


def load_runner():
    sys.path.insert(0, str(RUNNER_PATH.parent))
    spec = importlib.util.spec_from_file_location("we_v2_validation_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load validation runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WeV2SolverReplayContractTests(unittest.TestCase):
    def test_replay_solver_record_contains_only_formal_solver_fields(self) -> None:
        runner = load_runner()
        record = runner.solver_record(
            {"item_id": "we-v2-contract-001"},
            order=1,
            replay_answer="B",
            correction="have -> has",
            batch_id="batch-a",
        )

        self.assertEqual(set(record), runner.SOLVER_VALIDATOR.ALLOWED_TOP_KEYS)
        self.assertNotIn("judgment_mode", record)
        self.assertNotIn("grammar_quality_evaluable", record)

        errors: list[str] = []
        runner.SOLVER_VALIDATOR.validate_contract(record, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
