"""Offline regression coverage for the recorded WE v2.1.3 Reviewer failures."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts" / "audit_reviewer_contract_failures.py"


def load_audit():
    spec = importlib.util.spec_from_file_location("reviewer_contract_audit_test", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewerContractAuditTests(unittest.TestCase):
    def test_all_recorded_failures_are_target_metadata_contract_failures(self) -> None:
        audit = load_audit()
        result = audit.audit(audit.DEFAULT_RUN)

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
