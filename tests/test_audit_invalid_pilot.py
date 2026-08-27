"""Regressions for offline historical schema discovery."""

from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_audit_module():
    path = ROOT / "scripts" / "audit_invalid_pilot.py"
    spec = importlib.util.spec_from_file_location("audit_invalid_pilot_regression", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HistoricalSchemaDiscoveryTests(unittest.TestCase):
    def test_unreachable_schema_blob_is_matched_by_content_hash(self) -> None:
        audit = load_audit_module()
        schema_bytes = b'{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object"}\n'
        recorded_hash = "sha256:" + hashlib.sha256(schema_bytes).hexdigest()

        with mock.patch.object(
            audit,
            "_git_rows",
            side_effect=(
                (["1111111111111111111111111111111111111111 historical/other.txt"], True),
                (["unreachable blob 2222222222222222222222222222222222222222"], True),
            ),
        ), mock.patch.object(audit.subprocess, "check_output", return_value=schema_bytes) as cat_file:
            candidates, scope = audit._exact_schema_candidates_with_scope(recorded_hash)

        self.assertTrue(scope["unreachable_git_blobs"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "2222222222222222222222222222222222222222")
        self.assertEqual(candidates[0]["search_scope"], "unreachable_git_blob_content")
        cat_file.assert_called_once_with(
            ["git", "cat-file", "blob", "2222222222222222222222222222222222222222"],
            cwd=audit.ROOT,
        )


if __name__ == "__main__":
    unittest.main()
