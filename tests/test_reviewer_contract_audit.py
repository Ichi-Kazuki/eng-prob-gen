"""Offline regression coverage for the recorded WE v2.1.3 Reviewer failures.

This test loads the checked-in immutable historical audit fixture rather than
re-running scripts/audit_reviewer_contract_failures.py against the historical
run directory, which is gitignored and absent from a fresh checkout. The
fixture is the recorded, hermetic snapshot of that offline audit result.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKED_IN_HISTORICAL_AUDIT_FIXTURE = (
    ROOT / "analysis" / "we_v2_1_3_reviewer_contract_audit_20260827.json"
)


def load_checked_in_historical_audit_fixture() -> dict:
    with CHECKED_IN_HISTORICAL_AUDIT_FIXTURE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ReviewerContractAuditTests(unittest.TestCase):
    def test_all_recorded_failures_are_target_metadata_contract_failures(self) -> None:
        result = load_checked_in_historical_audit_fixture()

        self.assertEqual(result["status"], "OFFLINE_AUDIT_COMPLETE")
        self.assertEqual(result["model_invocations"], 0)
        self.assertEqual(result["failure_count"], 22)
        self.assertEqual(result["canonical_error_variants"], 1)
        self.assertEqual(result["target_metadata_origins"], ["BLIND_REVIEWER_RESPONSE"])
        self.assertTrue(result["historical_run_modified"] is False)
        self.assertTrue(result["all_failures_are_reviewer_contract_failures"])

        for item in result["items"]:
            self.assertEqual(item["raw_live_reviewer_response"]["checks"]["target_metadata"], "AMBIGUOUS")
            self.assertEqual(item["normalized_adapter_representation"]["checks_target_metadata"], "AMBIGUOUS")
            self.assertTrue(item["normalized_adapter_representation"]["judgment_fields_unchanged"])
            self.assertEqual(item["final_formal_reviewer_record"]["present"], False)
            self.assertEqual(item["target_metadata_provenance"]["blind_input_keys"], [
                "item_id", "marked_parts", "section", "sentence"
            ])
            self.assertEqual(item["historical_transport_schema_errors"], [])
            self.assertEqual(
                item["canonical_validation_errors"][0].split("$.checks", 1)[-1],
                ": PASS forbids failed/ambiguous checks=['target_metadata']",
            )


if __name__ == "__main__":
    unittest.main()
