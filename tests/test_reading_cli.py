"""Focused tests for deterministic Reading CLI version routing."""

from __future__ import annotations

import unittest
from unittest import mock

from reading import cli


def historical_result() -> dict:
    return {
        "run_id": "reading-v01-test",
        "decision": "QUARANTINE",
        "generator": {"passage": "", "questions": []},
        "reviewer": {"questions": []},
        "solver": {"answers": []},
        "checks": {
            "generator_canonical": True,
            "deterministic": True,
            "reviewer_contract": True,
            "solver_contract": True,
            "answer_agreement": [],
            "blind_errors": [],
        },
        "infrastructure": {
            "live_invocations": 3,
            "synthetic_fallback": False,
            "runtime_failures": [],
        },
    }


class ReadingCliRoutingTests(unittest.TestCase):
    def test_default_command_routes_to_current_v028_batch(self) -> None:
        with (
            mock.patch.object(cli, "run_reading_batch", return_value={}) as batch,
            mock.patch.object(cli, "run_reading") as historical,
        ):
            self.assertEqual(cli.main([]), 0)

        historical.assert_not_called()
        batch.assert_called_once_with(
            None,
            count=1,
            parallel=1,
            mode="validated",
            domain=None,
            output_dir=None,
            provider=None,
            model=None,
        )

    def test_explicit_current_v028_route_accepts_batch_and_draft_options(self) -> None:
        with mock.patch.object(cli, "run_reading_batch", return_value={}) as batch:
            self.assertEqual(
                cli.main(["--version", "v0.2.8", "--seed", "17", "--count", "2", "--parallel", "2", "--mode", "draft"]),
                0,
            )

        batch.assert_called_once_with(
            17,
            count=2,
            parallel=2,
            mode="draft",
            domain=None,
            output_dir=None,
            provider=None,
            model=None,
        )

    def test_explicit_historical_v01_route_still_uses_historical_pipeline(self) -> None:
        with (
            mock.patch.object(cli, "run_reading", return_value=historical_result()) as historical,
            mock.patch.object(cli, "run_reading_batch") as batch,
        ):
            self.assertEqual(cli.main(["--version", "v0.1", "--seed", "17"]), 1)

        batch.assert_not_called()
        historical.assert_called_once_with(
            17,
            domain=None,
            output_dir=None,
            provider=None,
            model=None,
        )

    def test_current_options_are_not_interpreted_by_historical_v01(self) -> None:
        for option in (
            ["--count", "2"],
            ["--parallel", "2"],
            ["--parallel", "1"],
            ["--mode", "draft"],
        ):
            with self.subTest(option=option), mock.patch.object(cli, "run_reading") as historical:
                with self.assertRaises(SystemExit) as raised:
                    cli.main(["--version", "v0.1", *option])
                self.assertEqual(raised.exception.code, 2)
                historical.assert_not_called()

    def test_invalid_version_has_no_silent_fallback(self) -> None:
        with (
            mock.patch.object(cli, "run_reading") as historical,
            mock.patch.object(cli, "run_reading_batch") as current,
        ):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--version", "v0.1.legacy"])

        self.assertEqual(raised.exception.code, 2)
        historical.assert_not_called()
        current.assert_not_called()


if __name__ == "__main__":
    unittest.main()
