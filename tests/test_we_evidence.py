"""Offline tests for the WE grammar evidence producer.

No live/model calls anywhere in this module. Every runtime invocation is a
FakeRuntime returning a pre-scripted InvocationResult or raising
RuntimeInvocationError; the real production validator subprocess is exercised
directly (it is itself fully deterministic and makes no live calls).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.adapters import InvocationResult, RuntimeInvocationError  # noqa: E402
from shared.schema_validation import load_schema, schema_errors  # noqa: E402
from we_evidence import cli, pipeline  # noqa: E402


FIXTURE_PATH = (
    ROOT
    / "analysis"
    / "we_v2_1_2_grammar_pilot"
    / "runtime"
    / "generator"
    / "we_v2.1.2_grammar_pilot_001.json"
)


def _load_validate_output_module() -> Any:
    path = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts" / "validate_output.py"
    spec = importlib.util.spec_from_file_location("we_evidence_test_validate_output", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_item() -> dict[str, Any]:
    item = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    item["qa_metadata"]["grammar_check_status"] = "PASS"
    return item


def _all_true_evidence() -> dict[str, bool]:
    return {name: True for name in pipeline.STRONG_INVARIANT_NAMES}


def _all_true_rationale() -> dict[str, str]:
    return {name: f"{name} holds because the analysis confirms it." for name in pipeline.STRONG_INVARIANT_NAMES}


def _raw_audit_output(item_id: str, evidence: dict[str, bool] | None = None) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "evidence": evidence if evidence is not None else _all_true_evidence(),
        "rationale": _all_true_rationale(),
    }


def _invocation_result(
    *,
    parsed: Any,
    invocation_id: str = "fake-invocation-1",
    model: str = "fake-model-1",
) -> InvocationResult:
    return InvocationResult(
        stage=pipeline.STAGE,
        agent_name=pipeline.AGENT_NAME,
        invocation_id=invocation_id,
        started_at="2026-08-26T00:00:00+00:00",
        completed_at="2026-08-26T00:00:01+00:00",
        provider="fake",
        model=model,
        parsed=parsed,
    )


class FakeRuntime:
    """A scripted AgentRuntime: pops one handler per invoke() call, in order."""

    provider = "fake"
    cli_version = "fake-1.0"

    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = list(handlers)
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> InvocationResult:
        self.calls.append(request)
        if not self._handlers:
            raise AssertionError("FakeRuntime.invoke called more times than scripted")
        handler = self._handlers.pop(0)
        if isinstance(handler, Exception):
            raise handler
        return handler


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# 24. Input projection
# ---------------------------------------------------------------------------


class InputProjectionTests(unittest.TestCase):
    def test_exact_visible_fields(self) -> None:
        payload = pipeline.build_audit_payload(_fixture_item())
        self.assertEqual(set(payload), set(pipeline.AUDIT_PROJECTION_KEYS))

    def test_reviewer_solver_and_disallowed_metadata_cannot_enter_projection(self) -> None:
        item = _fixture_item()
        item["reviewer_output"] = {"verdict": "PASS"}
        item["solver_output"] = {"independent_answer": "B"}
        item["test_result"] = {"passed": True}
        payload = pipeline.build_audit_payload(item)
        self.assertNotIn("reviewer_output", payload)
        self.assertNotIn("solver_output", payload)
        self.assertNotIn("test_result", payload)

    def test_grammar_check_status_not_included(self) -> None:
        payload = pipeline.build_audit_payload(_fixture_item())
        self.assertNotIn("grammar_check_status", payload)
        self.assertNotIn("qa_metadata", payload)

    def test_format_metadata_not_included(self) -> None:
        payload = pipeline.build_audit_payload(_fixture_item())
        self.assertNotIn("format_metadata", payload)

    def test_provenance_not_included(self) -> None:
        payload = pipeline.build_audit_payload(_fixture_item())
        self.assertNotIn("provenance", payload)

    def test_sentence_error_form_mismatch_fails_before_invocation(self) -> None:
        item = _fixture_item()
        item["qa_metadata"]["error_form"] = item["qa_metadata"]["error_form"] + " extra"
        with self.assertRaises(pipeline.GrammarEvidenceError):
            pipeline.build_audit_payload(item)

    def test_missing_clean_form_fails_before_invocation(self) -> None:
        item = _fixture_item()
        del item["qa_metadata"]["clean_form"]
        with self.assertRaises(pipeline.GrammarEvidenceError):
            pipeline.build_audit_payload(item)


# ---------------------------------------------------------------------------
# 25. Model contract
# ---------------------------------------------------------------------------


class ModelContractTests(unittest.TestCase):
    def test_valid_seven_boolean_response_accepted(self) -> None:
        raw = _raw_audit_output("item-1")
        self.assertEqual(pipeline.audit_output_errors(raw, "item-1"), [])

    def test_missing_invariant_rejected(self) -> None:
        raw = _raw_audit_output("item-1")
        del raw["evidence"]["clean_sentence_grammatical"]
        self.assertTrue(pipeline.audit_output_errors(raw, "item-1"))

    def test_extra_evidence_key_rejected(self) -> None:
        raw = _raw_audit_output("item-1")
        raw["evidence"]["extra_invariant"] = True
        self.assertTrue(pipeline.audit_output_errors(raw, "item-1"))

    def test_missing_rationale_rejected(self) -> None:
        raw = _raw_audit_output("item-1")
        del raw["rationale"]["clean_sentence_grammatical"]
        self.assertTrue(pipeline.audit_output_errors(raw, "item-1"))

    def test_wrong_item_id_rejected(self) -> None:
        raw = _raw_audit_output("item-1")
        self.assertTrue(pipeline.audit_output_errors(raw, "different-item"))

    def test_invalid_boolean_type_rejected(self) -> None:
        raw = _raw_audit_output("item-1")
        raw["evidence"]["clean_sentence_grammatical"] = "true"
        self.assertTrue(pipeline.audit_output_errors(raw, "item-1"))

    def test_extra_top_level_key_rejected(self) -> None:
        raw = _raw_audit_output("item-1")
        raw["evidence_producer"] = "forged"
        self.assertTrue(pipeline.audit_output_errors(raw, "item-1"))


# ---------------------------------------------------------------------------
# 26. Provenance
# ---------------------------------------------------------------------------


class ProvenanceTests(unittest.TestCase):
    def test_provenance_is_wrapper_owned_and_record_validates(self) -> None:
        item = _fixture_item()
        raw = _raw_audit_output(item["item_id"])
        invocation = _invocation_result(parsed=raw, invocation_id="inv-xyz", model="fake-model-7")
        record = pipeline.build_evidence_record(item, raw, invocation)

        self.assertEqual(record["evidence_producer"], pipeline.EVIDENCE_PRODUCER)
        self.assertEqual(record["evidence_producer_version"], pipeline.EVIDENCE_PRODUCER_VERSION)
        self.assertEqual(record["evidence_method"], pipeline.EVIDENCE_METHOD)
        self.assertEqual(record["invocation_id"], "inv-xyz")
        self.assertEqual(record["model_identifier"], "fake-model-7")
        self.assertEqual(record["content_hash"], pipeline.content_hash_for_item(item))

        parsed_timestamp = datetime.fromisoformat(record["created_at"])
        self.assertIsNotNone(parsed_timestamp.tzinfo)

        schema = load_schema(pipeline.EVIDENCE_SCHEMA_PATH)
        self.assertEqual(schema_errors(record, schema), [])

    def test_model_cannot_control_content_hash_or_producer(self) -> None:
        # The model contract schema itself has no content_hash/evidence_producer
        # key (additionalProperties: false), so any attempt is rejected before
        # a record is ever built.
        raw = _raw_audit_output("item-1")
        raw["content_hash"] = "sha256:" + ("0" * 64)
        self.assertTrue(pipeline.audit_output_errors(raw, "item-1"))


# ---------------------------------------------------------------------------
# 27. Content binding
# ---------------------------------------------------------------------------


class ContentBindingTests(unittest.TestCase):
    def test_hash_matches_authoritative_validator_function(self) -> None:
        module = _load_validate_output_module()
        item = _fixture_item()
        self.assertEqual(pipeline.content_hash_for_item(item), module.grammar_evidence_content_hash(item))

    def test_hash_changes_when_sentence_mutates(self) -> None:
        item = _fixture_item()
        original_hash = pipeline.content_hash_for_item(item)
        mutated = copy.deepcopy(item)
        mutated["sentence"] = mutated["sentence"] + " "
        mutated["qa_metadata"]["error_form"] = mutated["qa_metadata"]["error_form"] + " "
        self.assertNotEqual(pipeline.content_hash_for_item(mutated), original_hash)

    def test_hash_unaffected_by_field_outside_projection(self) -> None:
        item = _fixture_item()
        original_hash = pipeline.content_hash_for_item(item)
        mutated = copy.deepcopy(item)
        mutated["difficulty"] = "HARD" if mutated["difficulty"] != "HARD" else "MEDIUM"
        self.assertEqual(pipeline.content_hash_for_item(mutated), original_hash)


# ---------------------------------------------------------------------------
# 28/29. Fail-closed behavior and the existing validator as final authority
# ---------------------------------------------------------------------------


class PipelineDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _write_generator_file(self, items: list[dict[str, Any]]) -> Path:
        path = self.tmp / "generator_outputs.json"
        path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_all_true_evidence_and_correct_binding_yields_pass(self) -> None:
        item = _fixture_item()
        generator_path = self._write_generator_file([item])
        runtime = FakeRuntime([_invocation_result(parsed=_raw_audit_output(item["item_id"]))])

        result = pipeline.produce_grammar_evidence(
            generator_path, output_dir=self.tmp / "out", runtime=runtime
        )

        self.assertEqual(result["decision"], "PASS")
        self.assertTrue(result["production_validator_pass"])
        self.assertEqual(result["auditor_invocation_count"], 1)
        self.assertEqual(len(runtime.calls), 1)

        evidence_doc = json.loads(Path(result["evidence_output_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(evidence_doc["items"]), 1)
        schema = load_schema(pipeline.EVIDENCE_SCHEMA_PATH)
        self.assertEqual(schema_errors(evidence_doc["items"][0], schema), [])

    def test_one_false_strong_invariant_quarantines_and_skips_final_validator(self) -> None:
        item = _fixture_item()
        generator_path = self._write_generator_file([item])
        evidence = _all_true_evidence()
        evidence["no_plausible_alternate_parse"] = False
        runtime = FakeRuntime([_invocation_result(parsed=_raw_audit_output(item["item_id"], evidence))])

        result = pipeline.produce_grammar_evidence(
            generator_path, output_dir=self.tmp / "out", runtime=runtime
        )

        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertFalse(result["all_strong_invariants_pass"])
        self.assertFalse(result["production_validator_pass"])

    def test_runtime_exception_fails_closed_with_no_retry(self) -> None:
        item = _fixture_item()
        generator_path = self._write_generator_file([item])
        stub_result = _invocation_result(parsed=None)
        error = RuntimeInvocationError("infrastructure", "simulated transport failure", stub_result)
        runtime = FakeRuntime([error])

        result = pipeline.produce_grammar_evidence(
            generator_path, output_dir=self.tmp / "out", runtime=runtime
        )

        self.assertEqual(result["decision"], "INFRASTRUCTURE_FAILURE")
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(result["items"][0]["auditor_invoked"], False)

    def test_invalid_raw_output_fails_closed_with_no_retry(self) -> None:
        item = _fixture_item()
        generator_path = self._write_generator_file([item])
        bad_raw = _raw_audit_output(item["item_id"])
        del bad_raw["evidence"]["mutated_sentence_ungrammatical"]
        runtime = FakeRuntime([_invocation_result(parsed=bad_raw)])

        result = pipeline.produce_grammar_evidence(
            generator_path, output_dir=self.tmp / "out", runtime=runtime
        )

        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(len(runtime.calls), 1)
        self.assertFalse(result["items"][0]["auditor_contract_pass"])

    def test_item_id_mismatch_fails_closed_with_no_retry(self) -> None:
        item = _fixture_item()
        generator_path = self._write_generator_file([item])
        runtime = FakeRuntime([_invocation_result(parsed=_raw_audit_output("some-other-item-id"))])

        result = pipeline.produce_grammar_evidence(
            generator_path, output_dir=self.tmp / "out", runtime=runtime
        )

        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(len(runtime.calls), 1)
        self.assertFalse(result["items"][0]["auditor_contract_pass"])

    def test_production_validator_nonzero_quarantines_even_with_true_evidence(self) -> None:
        item = _fixture_item()
        # Structurally break the item beyond what the audit projection checks
        # (missing grammar_metadata) so the local validator's schema/contract
        # check fails even though every audited invariant is true.
        del item["grammar_metadata"]
        generator_path = self._write_generator_file([item])
        runtime = FakeRuntime([_invocation_result(parsed=_raw_audit_output(item["item_id"]))])

        result = pipeline.produce_grammar_evidence(
            generator_path, output_dir=self.tmp / "out", runtime=runtime
        )

        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertFalse(result["production_validator_pass"])
        self.assertTrue(result["all_strong_invariants_pass"])

    def test_exactly_one_invocation_per_item(self) -> None:
        item_one = _fixture_item()
        item_two = copy.deepcopy(item_one)
        item_two["item_id"] = item_one["item_id"] + "-second"
        generator_path = self._write_generator_file([item_one, item_two])
        runtime = FakeRuntime(
            [
                _invocation_result(parsed=_raw_audit_output(item_one["item_id"])),
                _invocation_result(parsed=_raw_audit_output(item_two["item_id"])),
            ]
        )

        result = pipeline.produce_grammar_evidence(
            generator_path, output_dir=self.tmp / "out", runtime=runtime
        )

        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(result["auditor_invocation_count"], 2)
        self.assertEqual(result["decision"], "PASS")


class ExistingValidatorAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_existing_validator_passes_with_full_true_evidence(self) -> None:
        item = _fixture_item()
        generator_path = self.tmp / "generator.json"
        generator_path.write_text(json.dumps({"items": [item]}), encoding="utf-8")
        evidence_path = self.tmp / "grammar_evidence.json"
        record = {
            "item_id": item["item_id"],
            "content_hash": pipeline.content_hash_for_item(item),
            "evidence": _all_true_evidence(),
            "evidence_producer": pipeline.EVIDENCE_PRODUCER,
            "evidence_producer_version": pipeline.EVIDENCE_PRODUCER_VERSION,
            "invocation_id": "inv-1",
            "created_at": "2026-08-26T00:00:00+00:00",
            "evidence_method": pipeline.EVIDENCE_METHOD,
            "model_identifier": "fake-model",
        }
        evidence_path.write_text(json.dumps({"items": [record]}), encoding="utf-8")

        self.assertTrue(pipeline.run_production_validator(generator_path, evidence_path))

    def test_existing_validator_fails_with_one_false_invariant(self) -> None:
        item = _fixture_item()
        generator_path = self.tmp / "generator.json"
        generator_path.write_text(json.dumps({"items": [item]}), encoding="utf-8")
        evidence_path = self.tmp / "grammar_evidence.json"
        evidence = _all_true_evidence()
        evidence["exactly_one_grammatical_defect"] = False
        record = {
            "item_id": item["item_id"],
            "content_hash": pipeline.content_hash_for_item(item),
            "evidence": evidence,
            "evidence_producer": pipeline.EVIDENCE_PRODUCER,
            "evidence_producer_version": pipeline.EVIDENCE_PRODUCER_VERSION,
            "invocation_id": "inv-1",
            "created_at": "2026-08-26T00:00:00+00:00",
            "evidence_method": pipeline.EVIDENCE_METHOD,
            "model_identifier": "fake-model",
        }
        evidence_path.write_text(json.dumps({"items": [record]}), encoding="utf-8")

        self.assertFalse(pipeline.run_production_validator(generator_path, evidence_path))

    def test_existing_validator_fails_with_absent_evidence(self) -> None:
        item = _fixture_item()
        generator_path = self.tmp / "generator.json"
        generator_path.write_text(json.dumps({"items": [item]}), encoding="utf-8")
        evidence_path = self.tmp / "grammar_evidence.json"
        evidence_path.write_text(json.dumps({"items": []}), encoding="utf-8")

        self.assertFalse(pipeline.run_production_validator(generator_path, evidence_path))


# ---------------------------------------------------------------------------
# 30. CLI
# ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _write_generator_file(self, items: list[dict[str, Any]]) -> Path:
        path = self.tmp / "generator_outputs.json"
        path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_valid_offline_run_returns_zero(self) -> None:
        item = _fixture_item()
        generator_path = self._write_generator_file([item])
        runtime = FakeRuntime([_invocation_result(parsed=_raw_audit_output(item["item_id"]))])
        output_dir = self.tmp / "out"

        with mock.patch.object(pipeline, "configure_runtime", return_value=runtime):
            exit_code = cli.main(
                ["--generator-output", str(generator_path), "--output-dir", str(output_dir)]
            )

        self.assertEqual(exit_code, 0)
        evidence_doc = json.loads((output_dir / "grammar_evidence.json").read_text(encoding="utf-8"))
        schema = load_schema(pipeline.EVIDENCE_SCHEMA_PATH)
        self.assertEqual(schema_errors(evidence_doc["items"][0], schema), [])

    def test_semantic_false_result_returns_one(self) -> None:
        item = _fixture_item()
        generator_path = self._write_generator_file([item])
        evidence = _all_true_evidence()
        evidence["defect_is_grammatical_not_semantic"] = False
        runtime = FakeRuntime([_invocation_result(parsed=_raw_audit_output(item["item_id"], evidence))])
        output_dir = self.tmp / "out"

        with mock.patch.object(pipeline, "configure_runtime", return_value=runtime):
            exit_code = cli.main(
                ["--generator-output", str(generator_path), "--output-dir", str(output_dir)]
            )

        self.assertEqual(exit_code, 1)

    def test_missing_input_file_returns_nonzero(self) -> None:
        missing_path = self.tmp / "does_not_exist.json"
        output_dir = self.tmp / "out"
        exit_code = cli.main(["--generator-output", str(missing_path), "--output-dir", str(output_dir)])
        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
