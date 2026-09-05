"""Offline architecture/end-to-end tests for the Structure v0.3 sharded pipeline.

No provider/model/live calls. Uses a deterministic offline scripted fake
runtime in the style of tests/test_structure_v02.py. Frozen v0.1/v0.2 files
and tests/test_structure_v02.py are never modified or re-hashed here; a
separate diff check against the frozen baseline is the source of truth for
that freeze.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import structure.planner as v01_planner
from structure import contracts as v01_contracts
from shared.json_io import canonical_json_sha256
from shared.schema_validation import load_schema, schema_errors
from runtime.adapters import InvocationRequest, InvocationResult, RuntimeInvocationError
from structure.v02 import blinding as v02_blinding
from structure.v03 import cli as v03_cli
from structure.v03 import contracts as v03_contracts
from structure.v03 import pipeline as v03_pipeline
from structure.v03 import planner as v03_planner


ROOT = Path(__file__).resolve().parents[1]
V03_SCHEMAS = ROOT / "structure" / "v03" / "schemas"

PLAN_SCHEMA = V03_SCHEMAS / "plan.schema.json"
SHARD_OUTPUT_SCHEMA = V03_SCHEMAS / "generator_shard_output.schema.json"
RESULT_SCHEMA = V03_SCHEMAS / "result.schema.json"
PROVENANCE_SCHEMA = V03_SCHEMAS / "provenance.schema.json"

SEED = 7


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

STEM_FILLER_WORDS = [
    "carefully", "gradually", "widely", "typically", "eventually", "notably",
    "consistently", "increasingly", "broadly", "originally", "subsequently", "generally",
]


def _stem_for_word_count(word_count: int) -> str:
    words = ["The", "researcher", v01_contracts.BLANK_MARKER, "the", "documented", "pattern"]
    index = 0
    while len(words) < word_count:
        words.append(STEM_FILLER_WORDS[index % len(STEM_FILLER_WORDS)])
        index += 1
    words = words[:word_count]
    words[-1] = f"{words[-1]}."
    return " ".join(words)


def _distractor_candidates() -> dict[str, Any]:
    return {
        "d1": {"text": "confirming", "rationale": "A participle cannot stand as the finite main verb."},
        "d2": {"text": "confirm", "rationale": "The base form does not carry the required tense."},
        "d3": {"text": "confirms", "rationale": "The present tense does not match the past-tense context."},
        "d4": {"text": "to confirm", "rationale": "The infinitive cannot stand as the finite main verb."},
        "d5": {"text": "having confirmed", "rationale": "The perfect participle cannot stand as the finite main verb."},
        "d6": {"text": "be confirmed", "rationale": "The passive base form cannot stand as the finite main verb here."},
    }


def _generator_item_for_plan(planned: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": planned["item_id"],
        "section": "Structure",
        "primary_target": planned["primary_target"],
        "subtype": f"{planned['primary_target']} generator-authored construction",
        "secondary_features": ["academic register"],
        "difficulty": planned["difficulty"],
        "vocabulary_domain": "generator-owned domain",
        "stem": _stem_for_word_count(planned["target_word_count"]),
        "correct_option": {"text": "confirmed"},
        "answer_explanation": "The finite past-tense verb is required in this main clause.",
        "distractor_candidates": _distractor_candidates(),
    }


def plan_fixture(seed: int = SEED) -> dict[str, Any]:
    return v03_planner.build_plan(seed)


def shard_payload_fixture(plan: dict[str, Any], shard: int) -> dict[str, Any]:
    start, end = v03_contracts.SHARD_ORDER_RANGES[shard]
    return {"items": copy.deepcopy(plan["items"][start - 1:end])}


def shard_output_fixture(plan: dict[str, Any], shard: int) -> dict[str, Any]:
    payload = shard_payload_fixture(plan, shard)
    return {"items": [_generator_item_for_plan(item) for item in payload["items"]]}


def merged_output_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    return {"items": [_generator_item_for_plan(item) for item in plan["items"]]}


def _reviewer_output_for_merged(merged: dict[str, Any], seed: int = SEED) -> dict[str, Any]:
    reviewer_input = v02_blinding.build_reviewer_candidate_input(merged, seed)
    correct_text = "confirmed"
    items = []
    for item in reviewer_input["items"]:
        options = item["candidate_options"]
        judgments = [
            {"option_text": text, "judgment": "VALID" if text == correct_text else "INVALID"}
            for text in options
        ]
        diagnostics = [{
            "option_text": correct_text,
            "natural_wording": True,
            "serious_defect": False,
            "observed_clause_count": 2,
            "candidate_pool_observed_difficulty": "MEDIUM",
            "difficulty_confidence": "HIGH",
        }]
        items.append({
            "item_id": item["item_id"],
            "option_judgments": judgments,
            "candidate_diagnostics": diagnostics,
            "comment": "Only the finite past-tense form completes the main clause naturally.",
        })
    return {"items": items}


def _solver_output_for_final(solver_input: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in solver_input["items"]:
        options = item["options"]
        correct_letter = next(letter for letter in v01_contracts.LETTERS if options[letter] == "confirmed")
        items.append({
            "item_id": item["item_id"],
            "answer_text": options[correct_letter],
            "confidence": "HIGH",
            "reason": "The finite past-tense completion is the only acceptable choice.",
        })
    return {"items": items}


# ---------------------------------------------------------------------------
# A. Planner tests
# ---------------------------------------------------------------------------

class PlannerTests(unittest.TestCase):
    def test_identity_and_version(self) -> None:
        plan = plan_fixture()
        self.assertEqual(plan["schema_version"], "structure-plan-v0.3")
        self.assertEqual(plan["version"], "v0.3")
        self.assertEqual(plan["plan_id"], f"structure-plan-v0.3-{SEED:016x}")

    def test_exactly_fifteen_items_and_ids(self) -> None:
        plan = plan_fixture()
        self.assertEqual(len(plan["items"]), 15)
        expected_ids = [f"structure-v03-{SEED:016x}-{order:02d}" for order in range(1, 16)]
        self.assertEqual([item["item_id"] for item in plan["items"]], expected_ids)
        self.assertEqual([item["order"] for item in plan["items"]], list(range(1, 16)))

    def test_sampled_fields_match_frozen_v01_planner(self) -> None:
        plan = plan_fixture()
        v01_plan = v01_planner.build_plan(SEED)
        for v03_item, v01_item in zip(plan["items"], v01_plan["items"]):
            for key in (
                "order", "section", "primary_target", "difficulty",
                "clause_count", "sentence_length_bin", "target_word_count",
            ):
                self.assertEqual(v03_item[key], v01_item[key])

    def test_no_shard_or_domain_field(self) -> None:
        plan = plan_fixture()
        for item in plan["items"]:
            for forbidden in ("shard_id", "domain_pool", "shard", "generator_group", "subtype", "vocabulary_domain"):
                self.assertNotIn(forbidden, item)

    def test_schema_valid(self) -> None:
        self.assertEqual([], schema_errors(plan_fixture(), load_schema(PLAN_SCHEMA)))

    def test_negative_seed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            v03_planner.build_plan(-1)


# ---------------------------------------------------------------------------
# B. Shard schema/contract tests
# ---------------------------------------------------------------------------

class ShardContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = plan_fixture()

    def test_valid_shard_passes_each_shard(self) -> None:
        for shard in (1, 2, 3):
            with self.subTest(shard=shard):
                output = shard_output_fixture(self.plan, shard)
                self.assertEqual([], v03_contracts.validate_generator_shard_contract(output, self.plan, shard))

    def test_four_items_rejected(self) -> None:
        output = shard_output_fixture(self.plan, 1)
        output["items"] = output["items"][:4]
        self.assertTrue(v03_contracts.validate_generator_shard_contract(output, self.plan, 1))

    def test_six_items_rejected(self) -> None:
        output = shard_output_fixture(self.plan, 1)
        extra = copy.deepcopy(output["items"][0])
        extra["item_id"] = "extra-item"
        output["items"].append(extra)
        self.assertTrue(v03_contracts.validate_generator_shard_contract(output, self.plan, 1))

    def test_wrong_shard_item_ids_rejected(self) -> None:
        # Shard 2's items do not match shard 1's expected plan slice.
        output = shard_output_fixture(self.plan, 2)
        self.assertTrue(v03_contracts.validate_generator_shard_contract(output, self.plan, 1))

    def test_wrong_order_rejected(self) -> None:
        output = shard_output_fixture(self.plan, 1)
        output["items"][0], output["items"][1] = output["items"][1], output["items"][0]
        self.assertTrue(v03_contracts.validate_generator_shard_contract(output, self.plan, 1))

    def test_sentence_length_violation_rejected(self) -> None:
        output = shard_output_fixture(self.plan, 1)
        output["items"][0]["correct_option"]["text"] = " ".join(["extremely"] * 20)
        errors = v03_contracts.validate_generator_shard_contract(output, self.plan, 1)
        self.assertTrue(any("word count" in error for error in errors))

    def test_duplicate_candidate_text_rejected(self) -> None:
        output = shard_output_fixture(self.plan, 1)
        output["items"][0]["distractor_candidates"]["d1"]["text"] = output["items"][0]["correct_option"]["text"]
        self.assertTrue(v03_contracts.validate_generator_shard_contract(output, self.plan, 1))

    def test_invalid_shard_number_rejected(self) -> None:
        output = shard_output_fixture(self.plan, 1)
        self.assertTrue(v03_contracts.validate_generator_shard_contract(output, self.plan, 4))

    def test_shard_schema_valid_fixture(self) -> None:
        self.assertEqual([], schema_errors(shard_output_fixture(self.plan, 1), load_schema(SHARD_OUTPUT_SCHEMA)))


# ---------------------------------------------------------------------------
# C. Merge tests
# ---------------------------------------------------------------------------

class MergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = plan_fixture()
        self.shards = {shard: shard_output_fixture(self.plan, shard) for shard in (1, 2, 3)}

    def test_three_valid_shards_merge_to_fifteen_in_plan_order(self) -> None:
        merged = v03_contracts.merge_generator_shards(self.shards, self.plan)
        self.assertEqual(len(merged["items"]), 15)
        self.assertEqual(
            [item["item_id"] for item in merged["items"]],
            [item["item_id"] for item in self.plan["items"]],
        )
        self.assertEqual([], v03_contracts.validate_merged_generator_contract(merged, self.plan))

    def test_missing_shard_fails(self) -> None:
        incomplete = {1: self.shards[1], 2: self.shards[2]}
        with self.assertRaises(ValueError):
            v03_contracts.merge_generator_shards(incomplete, self.plan)

    def test_duplicate_shard_key_not_representable(self) -> None:
        with self.assertRaises(ValueError):
            v03_contracts.merge_generator_shards({1: self.shards[1], 2: self.shards[2], 4: self.shards[3]}, self.plan)

    def test_wrong_identity_in_one_shard_fails_before_merge(self) -> None:
        bad_shards = dict(self.shards)
        bad_shards[2] = shard_output_fixture(self.plan, 3)  # wrong slice for shard 2
        with self.assertRaises(ValueError):
            v03_contracts.merge_generator_shards(bad_shards, self.plan)

    def test_no_partial_merged_result_on_failure(self) -> None:
        bad_shards = dict(self.shards)
        bad_shards[3]["items"] = bad_shards[3]["items"][:4]
        with self.assertRaises(ValueError):
            v03_contracts.merge_generator_shards(bad_shards, self.plan)


# ---------------------------------------------------------------------------
# D/E/F/G. Pipeline tests using a deterministic offline fake runtime
# ---------------------------------------------------------------------------

class FakeV03Runtime:
    """Deterministic offline scripted runtime. No subprocess, no network."""

    provider = "offline-fixture"
    cli_version = "offline-fixture"
    model = "offline-fixture"

    def __init__(
        self,
        *,
        shard_overrides: dict[int, Any] | None = None,
        shard_errors: dict[int, tuple[str, str]] | None = None,
        reviewer: Any = None,
        solver: Any = None,
        reviewer_error: tuple[str, str] | None = None,
        solver_error: tuple[str, str] | None = None,
    ) -> None:
        self.shard_overrides = shard_overrides or {}
        self.shard_errors = shard_errors or {}
        self.reviewer_override = reviewer
        self.solver_override = solver
        self.reviewer_error = reviewer_error
        self.solver_error = solver_error
        self.requests: list[InvocationRequest] = []

    def _result(self, request: InvocationRequest) -> InvocationResult:
        return InvocationResult(
            stage=request.stage,
            agent_name=request.agent_name,
            invocation_id=f"offline-{len(self.requests)}",
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:01+00:00",
            provider=self.provider,
            model=self.model,
            cli_version=self.cli_version,
            input_keys=list(request.input_keys),
        )

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
        result = self._result(request)

        for shard, stage_name in v03_pipeline.GENERATOR_SHARD_STAGES.items():
            if request.stage != stage_name:
                continue
            error = self.shard_errors.get(shard)
            if error is not None:
                category, detail = error
                result.error_category = category
                result.error_detail = detail
                raise RuntimeInvocationError(category, detail, result)
            override = self.shard_overrides.get(shard)
            if callable(override):
                parsed = override(payload)
            elif override is not None:
                parsed = override
            else:
                parsed = {"items": [_generator_item_for_plan(item) for item in payload["items"]]}
            result.parsed = parsed
            return result

        if request.stage == v03_pipeline.REVIEWER_STAGE:
            if self.reviewer_error is not None:
                category, detail = self.reviewer_error
                result.error_category = category
                result.error_detail = detail
                raise RuntimeInvocationError(category, detail, result)
            override = self.reviewer_override
            if callable(override):
                parsed = override(payload)
            elif override is not None:
                parsed = override
            else:
                parsed = _reviewer_output_from_input(payload)
            result.parsed = parsed
            return result

        if request.stage == v03_pipeline.SOLVER_STAGE:
            if self.solver_error is not None:
                category, detail = self.solver_error
                result.error_category = category
                result.error_detail = detail
                raise RuntimeInvocationError(category, detail, result)
            override = self.solver_override
            if callable(override):
                parsed = override(payload)
            elif override is not None:
                parsed = override
            else:
                parsed = _solver_output_for_final(payload)
            result.parsed = parsed
            return result

        raise AssertionError(f"unexpected stage: {request.stage}")  # pragma: no cover


def _reviewer_output_from_input(reviewer_input: dict[str, Any]) -> dict[str, Any]:
    correct_text = "confirmed"
    items = []
    for item in reviewer_input["items"]:
        options = item["candidate_options"]
        judgments = [
            {"option_text": text, "judgment": "VALID" if text == correct_text else "INVALID"}
            for text in options
        ]
        diagnostics = [{
            "option_text": correct_text,
            "natural_wording": True,
            "serious_defect": False,
            "observed_clause_count": 2,
            "candidate_pool_observed_difficulty": "MEDIUM",
            "difficulty_confidence": "HIGH",
        }]
        items.append({
            "item_id": item["item_id"],
            "option_judgments": judgments,
            "candidate_diagnostics": diagnostics,
            "comment": "Only the finite past-tense form completes the main clause naturally.",
        })
    return {"items": items}


def _run_pipeline(runtime: FakeV03Runtime, seed: int = SEED, tmp_dir: Path | None = None) -> dict[str, Any]:
    pipeline = v03_pipeline.StructureV03Pipeline(runtime=runtime)
    return pipeline.run(seed=seed, output_dir=tmp_dir)


ALL_SIXTEEN_ARTIFACTS = (
    "plan.json",
    "generator_shard_1_raw.json", "generator_shard_1_candidates.json",
    "generator_shard_2_raw.json", "generator_shard_2_candidates.json",
    "generator_shard_3_raw.json", "generator_shard_3_candidates.json",
    "generator_candidates.json",
    "reviewer_input.json", "reviewer.json",
    "candidate_selection.json", "generator_final.json", "permutation.json",
    "generator.json", "solver_input.json", "solver.json",
)


class PipelineCleanRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.runtime = FakeV03Runtime()
        self.result = _run_pipeline(self.runtime, tmp_dir=self.tmp_dir)

    def test_exactly_five_logical_calls_in_order(self) -> None:
        self.assertEqual(len(self.runtime.requests), 5)
        self.assertEqual(
            [request.stage for request in self.runtime.requests],
            [
                v03_pipeline.GENERATOR_SHARD_STAGES[1],
                v03_pipeline.GENERATOR_SHARD_STAGES[2],
                v03_pipeline.GENERATOR_SHARD_STAGES[3],
                v03_pipeline.REVIEWER_STAGE,
                v03_pipeline.SOLVER_STAGE,
            ],
        )
        self.assertEqual(self.result["live_invocation_count"], 5)

    def test_shard_counters_clean(self) -> None:
        self.assertEqual(self.result["generator_shard_calls_completed"], 3)
        self.assertEqual(self.result["generator_shard_contract_pass_count"], 3)
        self.assertTrue(self.result["merged_candidate_batch_constructed"])
        for entry in self.result["checks"]["generator_shards"]["items"]:
            self.assertTrue(entry["invoked"])
            self.assertTrue(entry["contract_passed"])
            self.assertEqual(entry["errors"], [])

    def test_reviewer_receives_fifteen_merged_items(self) -> None:
        reviewer_request = self.runtime.requests[3]
        payload = json.loads(reviewer_request.prompt.split("INPUT_JSON:\n", 1)[1])
        self.assertEqual(len(payload["items"]), 15)

    def test_candidate_selection_and_downstream_complete(self) -> None:
        self.assertEqual(self.result["candidate_selection_pass_count"], 15)
        self.assertEqual(self.result["candidate_selection_failure_count"], 0)
        self.assertTrue(self.result["checks"]["final_assembly"]["passed"])
        self.assertTrue(self.result["checks"]["permutation"]["passed"])

    def test_all_solver_keys_agree_and_accept(self) -> None:
        self.assertEqual(self.result["solver_key_agreement_count"], 15)
        self.assertEqual(self.result["solver_ambiguous_none_count"], 0)
        self.assertEqual(self.result["decision"], "ACCEPT")
        self.assertEqual(len(self.result["item_results"]), 15)
        self.assertTrue(all(item["accepted"] for item in self.result["item_results"]))

    def test_answer_position_distribution(self) -> None:
        self.assertEqual(sorted(self.result["final_answer_position_distribution"].values()), [3, 4, 4, 4])

    def test_sixteen_artifacts_non_null(self) -> None:
        for name in ALL_SIXTEEN_ARTIFACTS:
            with self.subTest(name=name):
                value = json.loads((self.tmp_dir / name).read_text(encoding="utf-8"))
                self.assertIsNotNone(value)

    def test_result_and_provenance_schema_valid(self) -> None:
        self.assertEqual([], schema_errors(self.result, load_schema(RESULT_SCHEMA)))
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual([], schema_errors(provenance, load_schema(PROVENANCE_SCHEMA)))

    def test_logical_invocation_counts_clean(self) -> None:
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(
            provenance["logical_invocation_counts"],
            {
                "generator_shard_1": 1,
                "generator_shard_2": 1,
                "generator_shard_3": 1,
                "reviewer": 1,
                "solver": 1,
            },
        )

    def test_provenance_generator_shards_summary(self) -> None:
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        shards = provenance["generator_shards"]
        self.assertEqual(shards["completed_calls"], 3)
        self.assertEqual(shards["contract_pass_count"], 3)
        self.assertTrue(shards["all_three_contracts_passed"])
        self.assertTrue(shards["merged_candidate_batch_constructed"])
        self.assertEqual(len(shards["items"]), 3)
        self.assertEqual([entry["shard"] for entry in shards["items"]], [1, 2, 3])

    def test_fallback_policy(self) -> None:
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["fallback"], {"used": False, "policy": "no_semantic_fallback"})

    def test_blindness_allowlists_preserved(self) -> None:
        provenance = json.loads((self.tmp_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(provenance["blind_inputs"]["reviewer"]["allowlist"]),
            {"item_id", "section", "stem", "candidate_options"},
        )
        self.assertEqual(
            provenance["blind_inputs"]["solver"]["allowlist"],
            ["item_id", "section", "stem", "options"],
        )

    def test_result_artifact_hashes_exactly_sixteen_keys_no_legacy_raw(self) -> None:
        self.assertEqual(set(self.result["artifact_hashes"]), set(ALL_SIXTEEN_ARTIFACTS))
        self.assertNotIn("generator_raw.json", self.result["artifact_hashes"])

    def test_no_obsolete_reviewer_solver_agreement_fields(self) -> None:
        schema_text = RESULT_SCHEMA.read_text(encoding="utf-8")
        for forbidden in (
            "reviewer_solver_agreement",
            "reviewer_difficulty_agreement_count",
            "reviewer_difficulty_low_confidence_count",
            "reviewer_ambiguous_none_count",
        ):
            self.assertNotIn(forbidden, schema_text)


class PipelineShardFailFastTests(unittest.TestCase):
    def _bad_shard_output(self, plan: dict[str, Any], shard: int) -> dict[str, Any]:
        output = shard_output_fixture(plan, shard)
        output["items"][0]["stem"] = output["items"][0]["stem"].replace(v01_contracts.BLANK_MARKER, "")
        return output

    def test_shard_one_failure_stops_before_shard_two(self) -> None:
        plan = plan_fixture()
        bad = self._bad_shard_output(plan, 1)
        runtime = FakeV03Runtime(shard_overrides={1: bad})
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(len(runtime.requests), 1)
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertEqual(result["generator_shard_calls_completed"], 1)
            self.assertEqual(result["generator_shard_contract_pass_count"], 0)
            self.assertFalse(result["merged_candidate_batch_constructed"])
            self.assertIsNotNone(json.loads((Path(directory) / "generator_shard_1_raw.json").read_text(encoding="utf-8")))
            for name in (
                "generator_shard_1_candidates.json",
                "generator_shard_2_raw.json", "generator_shard_2_candidates.json",
                "generator_shard_3_raw.json", "generator_shard_3_candidates.json",
                "generator_candidates.json", "reviewer_input.json", "reviewer.json",
                "candidate_selection.json", "generator_final.json", "permutation.json",
                "generator.json", "solver_input.json", "solver.json",
            ):
                self.assertIsNone(json.loads((Path(directory) / name).read_text(encoding="utf-8")))
        for item in result["item_results"]:
            self.assertEqual(item["rejection_reasons"], ["generator_shard_1_contract_failed"])

    def test_shard_two_failure_stops_before_shard_three(self) -> None:
        plan = plan_fixture()
        bad = self._bad_shard_output(plan, 2)
        runtime = FakeV03Runtime(shard_overrides={2: bad})
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(len(runtime.requests), 2)
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertEqual(result["generator_shard_calls_completed"], 2)
            self.assertEqual(result["generator_shard_contract_pass_count"], 1)
        for item in result["item_results"]:
            self.assertEqual(item["rejection_reasons"], ["generator_shard_2_contract_failed"])

    def test_shard_three_failure_stops_before_reviewer(self) -> None:
        plan = plan_fixture()
        bad = self._bad_shard_output(plan, 3)
        runtime = FakeV03Runtime(shard_overrides={3: bad})
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(len(runtime.requests), 3)
            self.assertEqual(
                [request.stage for request in runtime.requests],
                [v03_pipeline.GENERATOR_SHARD_STAGES[shard] for shard in (1, 2, 3)],
            )
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertEqual(result["generator_shard_calls_completed"], 3)
            self.assertEqual(result["generator_shard_contract_pass_count"], 2)
            self.assertFalse(result["merged_candidate_batch_constructed"])
        for item in result["item_results"]:
            self.assertEqual(item["rejection_reasons"], ["generator_shard_3_contract_failed"])

    def test_shard_one_runtime_failure_stops_everything(self) -> None:
        runtime = FakeV03Runtime(shard_errors={1: ("timeout", "shard 1 timed out")})
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(len(runtime.requests), 1)
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertEqual(result["generator_shard_calls_completed"], 1)
            self.assertTrue(result["item_results"][0]["rejection_reasons"][0].startswith("runtime_failure:"))


class PipelineArtifactHashTests(unittest.TestCase):
    def test_null_artifact_hash_matches_canonical_null(self) -> None:
        runtime = FakeV03Runtime(shard_errors={1: ("timeout", "shard 1 timed out")})
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertEqual(result["artifact_hashes"]["reviewer.json"], canonical_json_sha256(None))
            self.assertEqual(
                result["artifact_hashes"]["generator_shard_2_raw.json"], canonical_json_sha256(None)
            )

    def test_result_and_provenance_are_not_self_hashed(self) -> None:
        runtime = FakeV03Runtime()
        with tempfile.TemporaryDirectory() as directory:
            result = _run_pipeline(runtime, tmp_dir=Path(directory))
            self.assertNotIn("result.json", result["artifact_hashes"])
            self.assertNotIn("provenance.json", result["artifact_hashes"])


class CliTests(unittest.TestCase):
    def test_accept_returns_zero_exit_code(self) -> None:
        fake_result = {
            "run_id": "structure-v03-fixture",
            "version": "v0.3",
            "seed": 1,
            "decision": "ACCEPT",
            "question_count": 15,
            "live_invocation_count": 5,
            "generator_shard_calls_completed": 3,
            "generator_shard_contract_pass_count": 3,
            "merged_candidate_batch_constructed": True,
            "deterministic_hard_failure_count": 0,
            "candidate_selection_pass_count": 15,
            "candidate_selection_failure_count": 0,
            "solver_key_agreement_count": 15,
            "solver_ambiguous_none_count": 0,
            "final_answer_position_distribution": {"A": 4, "B": 4, "C": 4, "D": 3},
            "output_dir": "/tmp/fixture",
        }
        with patch.object(v03_cli, "run_structure_v03", return_value=fake_result) as mocked:
            exit_code = v03_cli.main(["--seed", "1"])
        mocked.assert_called_once()
        self.assertEqual(exit_code, 0)

    def test_quarantine_returns_nonzero_exit_code(self) -> None:
        fake_result = {
            "run_id": "structure-v03-fixture",
            "version": "v0.3",
            "seed": 1,
            "decision": "QUARANTINE",
            "question_count": 15,
            "live_invocation_count": 1,
            "generator_shard_calls_completed": 1,
            "generator_shard_contract_pass_count": 0,
            "merged_candidate_batch_constructed": False,
            "deterministic_hard_failure_count": 1,
            "candidate_selection_pass_count": 0,
            "candidate_selection_failure_count": 0,
            "solver_key_agreement_count": 0,
            "solver_ambiguous_none_count": 0,
            "final_answer_position_distribution": {"A": 0, "B": 0, "C": 0, "D": 0},
            "output_dir": "/tmp/fixture",
        }
        with patch.object(v03_cli, "run_structure_v03", return_value=fake_result):
            exit_code = v03_cli.main(["--seed", "1"])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
