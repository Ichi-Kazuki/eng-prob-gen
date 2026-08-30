"""Offline tests for variable-length Reading v0.2 batches."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import threading
import time
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reading.contracts import (
    blind_input,
    CHOICE_PERMUTATION_VERSION,
    EMPIRICAL_FORMAT_WARNING,
    FORMAT_ADHERENCE_FAILURE,
    HARD_VALIDITY,
    canonicalize_generator_output,
    deterministic_diagnostics,
    generator_model_schema_for_plan,
    permute_generator_choices,
    validate_deterministic,
    validate_generator_contract,
    validate_plan_contract,
    word_count,
)
from reading.pipeline import ReadingV02Pipeline, run_reading_batch
from reading.pipeline import (
    READING_INFERENCE_GUIDANCE,
    READING_LENGTH_GUIDANCE,
    READING_PARAGRAPH_GUIDANCE,
    READING_REVIEWER_INFERENCE_GUIDANCE,
    reading_v02_generator_instruction,
)
from reading.planner import (
    EMPIRICAL_PASSAGE_LENGTHS,
    EMPIRICAL_PROFILE_PATH,
    QUESTION_COUNT_WEIGHTS,
    QUESTION_TYPE_WEIGHTS,
    build_plan_v02,
    passage_id_for_seed,
)
from runtime.adapters import InvocationResult, RuntimeInvocationError
from shared.schema_validation import schema_errors

from tests.test_reading_pipeline import generator_fixture


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ARTIFACT_ROOT = ROOT / "runs" / "reading_v0_2" / "reading-v02-batch-20260828T003310Z-f0d7615efc"
HISTORICAL_ARTIFACT_HASHES = {
    "passage-001/generator.json": "1B9F9574EB8E69CF9E01ABEBB81E1737474C0788AC8D20FECFDA881BD10B580C",
    "passage-001/invocations.json": "D1CCC1DB8394011975A9D3B7D756B633A991593472ACEC596CB4D34FDAAA4468",
    "passage-001/plan.json": "60DD21C4EEAC8D235C293AA3A793C939F1C44EFC96AB361FF60F85727120DB18",
    "passage-001/provenance/provenance.json": "EB45E7DA1F2DCFD4148F7783F7DAD2D7129CE8A87ED4B479F58B0BFEFC3F4D10",
    "passage-001/result.json": "8832CFBD39489E8AECF43090060B575450235022A0FA098E7019977362F0253C",
    "passage-001/runtime/logs/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.last-message.json": "1D5B194F1B7A73DB6892A42BEF379298A6C910E0AD433D2C83FB16A9951D7FC4",
    "passage-001/runtime/logs/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.stderr.txt": "BACD69CD8DB7EC046793AC9D976E7CCFFBD6A3733B82C99BA7A1071CB3D11EC8",
    "passage-001/runtime/logs/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.stdout.txt": "E5D266DF0966CD2512F0E79D8B6DD340C904D8B8CE75B5AFBA7490F96C0F81BC",
    "passage-001/runtime/logs/transport-schemas/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.json": "AB5772F2F7575C6BC5EA5272A5565302BCE4192E9B55B7396F084D91D8AD43AA",
    "passage-001/runtime/logs/transport-schemas/reading_generator-fd641e8a-2e7c-4857-8021-4b1df4ad7a56.provenance.json": "02CF5889882846C4A20335F1CD2B2538F6567E968F8AC8D3745F173E8A8F677F",
    "passage-002/generator.json": "CC5C99A0305806A966DF120785A0FE9186CBBC69E09368F03471175A9DB8D968",
    "passage-002/invocations.json": "305EA0330EC2199670D2B8B0CBF29BF14FF093CDFDF2038356ED4640982DF83C",
    "passage-002/plan.json": "8C6A41970E7B761BD2DB5258492C79E102F046F58B95BDE5084A20232A6F9187",
    "passage-002/provenance/provenance.json": "059F6511FAD446AF271411CA18A88AAF0A19C8D4B664A9B8AA5F3587B9E071CF",
    "passage-002/result.json": "14EA6C3C3CE86946F2707DB90826F914E38FC1A5555999BBDC3FBF0CC259E013",
    "passage-002/runtime/logs/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.last-message.json": "0E46485F1895BE8F4D339CBED5F3E702BDB237C4969B7EC3E86E709FD707E15B",
    "passage-002/runtime/logs/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.stderr.txt": "F8A6857DAF23C3B4C6BDC15072578CAF61001831E3A3F1DEB670379398BE3D29",
    "passage-002/runtime/logs/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.stdout.txt": "2296B2E53D884D25246E0C1396026494EF47A17DFCC575B9340C668A6CFEF9BF",
    "passage-002/runtime/logs/transport-schemas/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.json": "AB5772F2F7575C6BC5EA5272A5565302BCE4192E9B55B7396F084D91D8AD43AA",
    "passage-002/runtime/logs/transport-schemas/reading_generator-15400215-ea57-470b-adc3-c257688c4a20.provenance.json": "02CF5889882846C4A20335F1CD2B2538F6567E968F8AC8D3745F173E8A8F677F",
}


def variable_generator_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    """Expand the stable offline passage into the plan's variable q sequence."""

    _legacy_plan, legacy = generator_fixture(7)
    output = copy.deepcopy(legacy)
    output["schema_version"] = "reading-generator-v0.2"
    output["passage_id"] = f"rc-{plan['seed']:08x}"
    questions = []
    question_plan = plan.get("question_plan") or [
        question_type
        for question_type, count in plan["question_type_counts"].items()
        for _ in range(count)
    ]
    for index, question_type in enumerate(question_plan, 1):
        question = copy.deepcopy(legacy["questions"][(index - 1) % len(legacy["questions"])])
        question["item_id"] = f"{output['passage_id']}-q{index}"
        question["question_type"] = question_type
        question["stem"] = f"Which statement is supported by the passage in item {index}?"
        question["subtype"] = {
            "DETAIL": "DIRECT_FACTUAL_DETAIL",
            "VOCABULARY_IN_CONTEXT": "VOCABULARY_CONTEXT_MEANING",
            "INFERENCE": "LOCAL_INFERENCE",
            "MAIN_IDEA": "PASSAGE_MAIN_IDEA",
            "REFERENCE": "ANTECEDENT_REFERENCE",
        }[question_type]
        question["distractor_metadata"] = {
            label: {
                "category": "CORRECT_OPTION" if label == question["correct_answer"] else "TEXT_TRUE_BUT_NOT_ANSWER",
                "rationale": "The keyed choice is supported." if label == question["correct_answer"] else "It is related but does not answer the stem.",
            }
            for label in ("A", "B", "C", "D")
        }
        questions.append(question)
    output["questions"] = questions
    return output


def sized_generator_fixture(plan: dict[str, Any], target_words: int, paragraph_count: int) -> dict[str, Any]:
    """Create a valid-shape fixture with a controlled passage profile."""

    output = variable_generator_fixture(plan)
    paragraph_sizes = [target_words // paragraph_count] * paragraph_count
    for index in range(target_words % paragraph_count):
        paragraph_sizes[index] += 1
    anchors_by_paragraph: dict[int, list[str]] = {index: [] for index in range(1, paragraph_count + 1)}
    for index, question in enumerate(output["questions"], 1):
        paragraph = (index - 1) % paragraph_count + 1
        anchor = f"evidence marker {index}"
        question["evidence"]["paragraph"] = paragraph
        question["evidence"]["anchor"] = anchor
        anchors_by_paragraph[paragraph].append(anchor)
    paragraphs = []
    for paragraph_index, size in enumerate(paragraph_sizes, 1):
        tokens = [f"paragraph {paragraph_index}"]
        tokens.extend(anchors_by_paragraph[paragraph_index])
        token_index = 0
        while word_count(" ".join(tokens)) < size:
            tokens.append(f"topic{paragraph_index}_{token_index}")
            token_index += 1
        paragraphs.append(" ".join(tokens))
    output["passage"] = "\n\n".join(paragraphs)
    assert word_count(output["passage"]) == target_words
    return output


def quota_plan(seed: int, counts: dict[str, int]) -> dict[str, Any]:
    plan = build_plan_v02(seed, domain="biology")
    question_plan = [question_type for question_type, count in counts.items() for _ in range(count)]
    plan["question_count"] = sum(counts.values())
    plan["question_plan"] = question_plan
    plan["question_type_counts"] = dict(counts)
    return plan


def grouped_model_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    flat = variable_generator_fixture(plan)
    grouped = copy.deepcopy(flat)
    grouped.pop("passage_id")
    grouped_questions = {field: [] for field in (
        "detail_questions",
        "vocabulary_in_context_questions",
        "inference_questions",
        "main_idea_questions",
        "reference_questions",
    )}
    field_by_type = {
        "DETAIL": "detail_questions",
        "VOCABULARY_IN_CONTEXT": "vocabulary_in_context_questions",
        "INFERENCE": "inference_questions",
        "MAIN_IDEA": "main_idea_questions",
        "REFERENCE": "reference_questions",
    }
    for question in grouped.pop("questions"):
        question.pop("item_id", None)
        grouped_questions[field_by_type[question["question_type"]]].append(question)
    grouped.update(grouped_questions)
    return grouped


def reviewer_for(generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-reviewer-v0.2",
        "passage_id": generator["passage_id"],
        "section": "READING_COMPREHENSION",
        "questions": [
            {
                "item_id": question["item_id"],
                "best_answer": question["correct_answer"],
                "unique_answer": True,
                "distractors_incorrect": True,
                "answerable": True,
                "natural_wording": True,
                "serious_defect": False,
                "comment": "One answer is supported by the passage.",
            }
            for question in generator["questions"]
        ],
        "set_judgment": "PASS",
        "set_comment": "All visible items are clean.",
    }


def solver_for(generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-solver-v0.2",
        "passage_id": generator["passage_id"],
        "section": "READING_COMPREHENSION",
        "answers": [
            {
                "item_id": question["item_id"],
                "answer": question["correct_answer"],
                "confidence": "HIGH",
                "reason": "The visible passage supports the selected choice.",
            }
            for question in generator["questions"]
        ],
    }


def inference_verifier_for(generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-inference-verifier-v0.2",
        "passage_id": generator["passage_id"],
        "section": "READING_COMPREHENSION",
        "questions": [
            {
                "item_id": question["item_id"],
                "best_answer": question["correct_answer"],
                "status": "VALID_SHALLOW_INFERENCE",
                "supporting_propositions": ["The passage states the relevant fact.", "A second passage detail supports the conclusion."],
                "conclusion": "The selected answer follows from the visible passage.",
                "comment": "The item is independently answerable from the passage.",
            }
            for question in generator["questions"]
            if question["question_type"] == "INFERENCE"
        ],
    }


class BatchTrace:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.requests: list[Any] = []


class BatchFakeRuntime:
    provider = "fake"
    cli_version = "offline-v0.2"

    def __init__(self, label: str, trace: BatchTrace, fail_generator: bool = False) -> None:
        self.label = label
        self.trace = trace
        self.fail_generator = fail_generator
        self.generators: dict[str, dict[str, Any]] = {}
        self.call_number = 0

    def invoke(self, request):
        with self.trace.lock:
            self.trace.active += 1
            self.trace.max_active = max(self.trace.max_active, self.trace.active)
            self.trace.requests.append(request)
        self.call_number += 1
        invocation_id = f"offline-{self.label}-{self.call_number}"
        try:
            time.sleep(0.02)
            if self.fail_generator and request.stage == "reading_generator":
                failed = InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=invocation_id,
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:01+00:00",
                    provider=self.provider,
                    model="offline",
                    cli_version=self.cli_version,
                    exit_code=1,
                    error_category="infrastructure",
                    error_detail="intentional offline worker failure",
                    input_keys=list(request.input_keys),
                )
                raise RuntimeInvocationError("infrastructure", "intentional offline worker failure", failed)

            payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
            if request.stage == "reading_generator":
                passage_id = f"rc-{payload['seed']:08x}"
            elif request.stage == "reading_inference_repair":
                passage_id = payload["items"][0]["item_id"].rsplit("-q", 1)[0]
            else:
                passage_id = payload["passage_id"]
            if request.stage == "reading_generator":
                parsed = variable_generator_fixture(payload)
                worker_plan = build_plan_v02(payload["seed"], domain=payload.get("domain"))
                canonical = canonicalize_generator_output(parsed, worker_plan)
                self.generators[parsed["passage_id"]], _permutation = permute_generator_choices(canonical, worker_plan)
            elif request.stage == "reading_reviewer":
                parsed = reviewer_for(self.generators[passage_id])
            elif request.stage == "reading_inference_verifier":
                parsed = inference_verifier_for(self.generators[passage_id])
            elif request.stage == "reading_inference_repair":
                raise AssertionError("the stable fake should not need inference repair")
            elif request.stage == "reading_solver":
                parsed = solver_for(self.generators[passage_id])
            else:
                raise AssertionError(f"unexpected stage: {request.stage}")
            return InvocationResult(
                stage=request.stage,
                agent_name=request.agent_name,
                invocation_id=invocation_id,
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:01+00:00",
                provider=self.provider,
                model="offline",
                cli_version=self.cli_version,
                exit_code=0,
                parsed=parsed,
                input_keys=list(request.input_keys),
            )
        finally:
            with self.trace.lock:
                self.trace.active -= 1


class ReadingV02BatchTests(unittest.TestCase):
    def test_planner_uses_persisted_empirical_passage_lengths(self) -> None:
        profile = json.loads(EMPIRICAL_PROFILE_PATH.read_text(encoding="utf-8"))
        persisted = tuple(
            measurement["passage_word_count_approx"]
            for measurement in profile["passage_measurements"]
        )
        self.assertEqual(len(persisted), 20)
        self.assertEqual(EMPIRICAL_PASSAGE_LENGTHS, persisted)
        for seed in range(1001, 1101):
            self.assertIn(build_plan_v02(seed)["target_words"], persisted)

    def test_same_seed_reproduces_empirical_length_target(self) -> None:
        first = build_plan_v02(20260828, domain="biology")
        second = build_plan_v02(20260828, domain="biology")
        self.assertEqual(first, second)
        self.assertIn(first["target_words"], EMPIRICAL_PASSAGE_LENGTHS)

    def test_v023_planner_has_no_fixed_high_end_target_policy(self) -> None:
        planner_source = inspect.getsource(build_plan_v02)
        self.assertNotIn("280, 300, 320", planner_source)
        self.assertNotEqual(set(EMPIRICAL_PASSAGE_LENGTHS), {280, 300, 320})

    def test_question_quota_weights_and_behavior_remain_unchanged(self) -> None:
        self.assertEqual(
            QUESTION_COUNT_WEIGHTS,
            ((7, 2), (8, 2), (9, 3), (10, 6), (11, 3), (12, 3), (14, 1)),
        )
        self.assertEqual(
            QUESTION_TYPE_WEIGHTS,
            (("DETAIL", 74), ("VOCABULARY_IN_CONTEXT", 63), ("INFERENCE", 27), ("MAIN_IDEA", 15), ("REFERENCE", 21)),
        )
        for seed in range(1001, 1011):
            plan = build_plan_v02(seed)
            self.assertEqual(sum(plan["question_type_counts"].values()), plan["question_count"])
            self.assertEqual(Counter(plan["question_plan"]), Counter(plan["question_type_counts"]))

    def test_plan_specific_model_schema_enforces_d2_v4_i3_m0_r1(self) -> None:
        plan = quota_plan(1101, {
            "DETAIL": 2,
            "VOCABULARY_IN_CONTEXT": 4,
            "INFERENCE": 3,
            "MAIN_IDEA": 0,
            "REFERENCE": 1,
        })
        schema = generator_model_schema_for_plan(plan)
        expected = {
            "detail_questions": 2,
            "vocabulary_in_context_questions": 4,
            "inference_questions": 3,
            "main_idea_questions": 0,
            "reference_questions": 1,
        }
        for field, quota in expected.items():
            with self.subTest(field=field):
                self.assertEqual(schema["properties"][field]["minItems"], quota)
                self.assertEqual(schema["properties"][field]["maxItems"], quota)
        self.assertEqual(sum(schema["properties"][field]["maxItems"] for field in expected), plan["question_count"])

    def test_plan_specific_model_schema_supports_zero_and_variable_quotas(self) -> None:
        plans = (
            quota_plan(1102, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 4, "INFERENCE": 3, "MAIN_IDEA": 0, "REFERENCE": 1}),
            quota_plan(1103, {"DETAIL": 4, "VOCABULARY_IN_CONTEXT": 2, "INFERENCE": 1, "MAIN_IDEA": 1, "REFERENCE": 2}),
        )
        for plan in plans:
            schema = generator_model_schema_for_plan(plan)
            self.assertEqual(
                [schema["properties"][field]["maxItems"] for field in (
                    "detail_questions",
                    "vocabulary_in_context_questions",
                    "inference_questions",
                    "main_idea_questions",
                    "reference_questions",
                )],
                [plan["question_type_counts"][question_type] for question_type in (
                    "DETAIL",
                    "VOCABULARY_IN_CONTEXT",
                    "INFERENCE",
                    "MAIN_IDEA",
                    "REFERENCE",
                )],
            )

    def test_grouped_model_output_flattens_without_semantic_mutation(self) -> None:
        plan = quota_plan(1104, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 4, "INFERENCE": 3, "MAIN_IDEA": 0, "REFERENCE": 1})
        raw = grouped_model_fixture(plan)
        raw_snapshot = copy.deepcopy(raw)
        self.assertEqual(schema_errors(raw, generator_model_schema_for_plan(plan)), [])
        canonical = canonicalize_generator_output(raw, plan)
        self.assertEqual(raw, raw_snapshot)
        self.assertEqual(len(canonical["questions"]), sum(plan["question_type_counts"].values()))
        by_stem = {question["stem"]: question for question in canonical["questions"]}
        for field in (
            "detail_questions",
            "vocabulary_in_context_questions",
            "inference_questions",
            "main_idea_questions",
            "reference_questions",
        ):
            for raw_question in raw[field]:
                canonical_question = by_stem[raw_question["stem"]]
                for semantic_field in ("question_type", "stem", "choices", "correct_answer", "evidence"):
                    self.assertEqual(canonical_question[semantic_field], raw_question[semantic_field])
        self.assertEqual(
            [question["item_id"] for question in canonical["questions"]],
            [f"{plan['passage_id']}-q{index}" for index in range(1, plan["question_count"] + 1)],
        )

    def test_grouped_model_output_order_is_evidence_position_replayable_and_quota_preserving(self) -> None:
        plan = quota_plan(1105, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 4, "INFERENCE": 3, "MAIN_IDEA": 0, "REFERENCE": 1})
        first = canonicalize_generator_output(grouped_model_fixture(plan), plan)
        second = canonicalize_generator_output(grouped_model_fixture(plan), plan)
        self.assertEqual(first["questions"], second["questions"])
        actual_types = Counter(question["question_type"] for question in first["questions"])
        self.assertEqual(actual_types, Counter(plan["question_type_counts"]))
        self.assertEqual(
            [question["evidence"]["paragraph"] for question in first["questions"]],
            sorted(question["evidence"]["paragraph"] for question in first["questions"]),
        )
        self.assertNotEqual(
            [question["question_type"] for question in first["questions"]],
            [question_type for question_type, count in plan["question_type_counts"].items() for _ in range(count)],
        )

    def test_v025_choice_permutation_is_seeded_per_question_and_replayable(self) -> None:
        plan = build_plan_v02(1201, domain="biology")
        canonical = canonicalize_generator_output(variable_generator_fixture(plan), plan)
        first, first_provenance = permute_generator_choices(canonical, plan)
        second, second_provenance = permute_generator_choices(canonical, plan)

        self.assertEqual(first, second)
        self.assertEqual(first_provenance, second_provenance)
        self.assertEqual(first_provenance["version"], CHOICE_PERMUTATION_VERSION)
        mappings = {
            tuple(record["canonical_to_original"].items())
            for record in first_provenance["questions"]
        }
        self.assertGreater(len(mappings), 1)
        for record in first_provenance["questions"]:
            self.assertEqual(set(record["original_to_canonical"]), {"A", "B", "C", "D"})
            self.assertEqual(set(record["canonical_to_original"]), {"A", "B", "C", "D"})
            for original, canonical_label in record["original_to_canonical"].items():
                self.assertEqual(record["canonical_to_original"][canonical_label], original)

    def test_v025_choice_permutation_preserves_text_and_evidence_and_remaps_answer(self) -> None:
        plan = build_plan_v02(1202, domain="biology")
        canonical = canonicalize_generator_output(variable_generator_fixture(plan), plan)
        for question in canonical["questions"]:
            question["evidence"]["answer_label"] = question["correct_answer"]
        original = copy.deepcopy(canonical)
        permuted, provenance = permute_generator_choices(canonical, plan)

        for original_question, permuted_question, record in zip(
            original["questions"], permuted["questions"], provenance["questions"]
        ):
            self.assertEqual(permuted_question["stem"], original_question["stem"])
            self.assertEqual(permuted_question["evidence"]["paragraph"], original_question["evidence"]["paragraph"])
            self.assertEqual(permuted_question["evidence"]["anchor"], original_question["evidence"]["anchor"])
            self.assertEqual(permuted_question["evidence"]["rationale"], original_question["evidence"]["rationale"])
            for original_label, canonical_label in record["original_to_canonical"].items():
                self.assertEqual(
                    permuted_question["choices"][canonical_label],
                    original_question["choices"][original_label],
                )
            self.assertEqual(
                permuted_question["correct_answer"],
                record["original_to_canonical"][original_question["correct_answer"]],
            )
            self.assertEqual(
                permuted_question["evidence"]["answer_label"],
                permuted_question["correct_answer"],
            )
        self.assertEqual(canonical, original)

    def test_v025_pipeline_persists_raw_and_permuted_canonical_inputs(self) -> None:
        plan = build_plan_v02(1203, domain="biology")
        raw = variable_generator_fixture(plan)
        for question in raw["questions"]:
            question["target_text"] = None
            question["target_line"] = None
        canonical = canonicalize_generator_output(raw, plan)
        permuted, expected_provenance = permute_generator_choices(canonical, plan)
        requests: list[Any] = []

        class PermutationRuntime:
            provider = "fake"
            cli_version = "offline-v0.2.5"

            def invoke(self, request):
                requests.append(request)
                if request.stage == "reading_generator":
                    parsed = raw
                elif request.stage == "reading_reviewer":
                    parsed = reviewer_for(permuted)
                elif request.stage == "reading_inference_verifier":
                    parsed = inference_verifier_for(permuted)
                elif request.stage == "reading_solver":
                    parsed = solver_for(permuted)
                else:
                    raise AssertionError(f"unexpected stage: {request.stage}")
                return InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=f"permutation-{len(requests)}",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:01+00:00",
                    provider=self.provider,
                    model="offline",
                    cli_version=self.cli_version,
                    exit_code=0,
                    parsed=copy.deepcopy(parsed),
                    input_keys=list(request.input_keys),
                )

        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(PermutationRuntime()).run(
                plan["seed"], domain=plan["domain"], output_dir=Path(directory)
            )
            root = Path(directory)
            self.assertEqual(result["decision"], "ACCEPT")
            self.assertEqual(json.loads((root / "generator_raw.json").read_text(encoding="utf-8")), raw)
            self.assertEqual(json.loads((root / "generator.json").read_text(encoding="utf-8")), permuted)
            provenance = json.loads((root / "provenance" / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["reading_version"], "v0.2.9")
            self.assertEqual(provenance["choice_permutation"], expected_provenance)
            self.assertEqual(provenance["blind_prompt_fields"], ["passage_id", "section", "passage", "questions"])

            verifier_payload = json.loads(requests[1].prompt.split("INPUT_JSON:\n", 1)[1])
            reviewer_payload = json.loads(requests[2].prompt.split("INPUT_JSON:\n", 1)[1])
            solver_payload = json.loads(requests[3].prompt.split("INPUT_JSON:\n", 1)[1])
            self.assertEqual(verifier_payload["passage_id"], plan["passage_id"])
            self.assertTrue(all(set(question) == {"item_id", "stem", "choices"} for question in verifier_payload["questions"]))
            self.assertEqual(reviewer_payload, blind_input(permuted, schema_version="reading-blind-input-v0.2"))
            self.assertEqual(solver_payload, reviewer_payload)
            self.assertNotIn("title", reviewer_payload)
            self.assertEqual(requests[1].input_keys, ("passage_id", "section", "passage", "questions"))
            self.assertEqual(requests[2].input_keys, ("passage_id", "section", "passage", "questions"))
            self.assertNotIn("correct_answer", json.dumps(reviewer_payload))
            self.assertNotIn("evidence", json.dumps(reviewer_payload))
            self.assertEqual(validate_deterministic(permuted, plan), [])

    def test_v025_permutation_keeps_canonical_order_and_group_quota(self) -> None:
        plan = quota_plan(1204, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 3, "INFERENCE": 2, "MAIN_IDEA": 1, "REFERENCE": 1})
        canonical = canonicalize_generator_output(grouped_model_fixture(plan), plan)
        permuted, _provenance = permute_generator_choices(canonical, plan)
        self.assertEqual(
            [question["question_type"] for question in permuted["questions"]],
            [question["question_type"] for question in canonical["questions"]],
        )
        self.assertEqual(Counter(question["question_type"] for question in permuted["questions"]), Counter(plan["question_type_counts"]))
        self.assertEqual(
            [question["item_id"] for question in permuted["questions"]],
            [f"{plan['passage_id']}-q{index}" for index in range(1, plan["question_count"] + 1)],
        )

    def test_v025_permutation_precedes_canonicalization_for_grouped_model_output(self) -> None:
        plan = quota_plan(1206, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 2, "INFERENCE": 2, "MAIN_IDEA": 1, "REFERENCE": 1})
        raw = grouped_model_fixture(plan)
        raw_snapshot = copy.deepcopy(raw)
        permuted_raw, _provenance = permute_generator_choices(raw, plan)
        canonical = canonicalize_generator_output(permuted_raw, plan)

        self.assertEqual(raw, raw_snapshot)
        self.assertEqual(validate_generator_contract(canonical, plan), [])
        self.assertEqual(len(canonical["questions"]), plan["question_count"])
        self.assertEqual(
            Counter(question["question_type"] for question in canonical["questions"]),
            Counter(plan["question_type_counts"]),
        )

    def test_wrong_grouped_model_quota_fails_schema_and_canonicalization(self) -> None:
        plan = quota_plan(1106, {"DETAIL": 2, "VOCABULARY_IN_CONTEXT": 4, "INFERENCE": 3, "MAIN_IDEA": 0, "REFERENCE": 1})
        raw = grouped_model_fixture(plan)
        raw["inference_questions"].pop()
        self.assertTrue(schema_errors(raw, generator_model_schema_for_plan(plan)))
        with self.assertRaises(ValueError):
            canonicalize_generator_output(raw, plan)

    def test_planner_identity_envelope_does_not_change_semantic_generator_fields(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        self.assertEqual(plan["passage_id"], passage_id_for_seed(plan["seed"]))
        self.assertEqual(plan["passage_id"], build_plan_v02(1001, domain="biology")["passage_id"])

        raw = variable_generator_fixture(plan)
        raw["passage_id"] = "rc-legacy-model-choice"
        for index, question in enumerate(raw["questions"], 1):
            question["item_id"] = f"{raw['passage_id']}-q{index}"
        raw_snapshot = copy.deepcopy(raw)

        canonical = canonicalize_generator_output(raw, plan)
        self.assertEqual(canonical["passage_id"], plan["passage_id"])
        self.assertEqual(
            [question["item_id"] for question in canonical["questions"]],
            [f"{plan['passage_id']}-q{index}" for index in range(1, len(raw["questions"]) + 1)],
        )
        self.assertEqual(raw, raw_snapshot)
        self.assertEqual(validate_generator_contract(canonical, plan), [])
        canonical_by_stem = {question["stem"]: question for question in canonical["questions"]}
        for raw_question in raw["questions"]:
            canonical_question = canonical_by_stem[raw_question["stem"]]
            for field in ("question_type", "stem", "choices", "correct_answer", "evidence"):
                self.assertEqual(canonical_question[field], raw_question[field])

    def test_v02_pipeline_binds_legacy_model_identity_and_preserves_raw_artifact(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        raw = variable_generator_fixture(plan)
        raw["passage_id"] = "rc-model-selected"
        for index, question in enumerate(raw["questions"], 1):
            question["item_id"] = f"{raw['passage_id']}-q{index}"
        raw_snapshot = copy.deepcopy(raw)
        canonical = canonicalize_generator_output(raw, plan)
        permuted, _permutation = permute_generator_choices(canonical, plan)
        reviewer = reviewer_for(permuted)
        solver = solver_for(permuted)

        class LegacyIdentityRuntime:
            provider = "fake"
            cli_version = "offline-legacy-identity"

            def __init__(self) -> None:
                self.requests: list[Any] = []

            def invoke(self, request):
                self.requests.append(request)
                parsed = {
                    "reading_generator": raw_snapshot,
                    "reading_inference_verifier": inference_verifier_for(permuted),
                    "reading_reviewer": reviewer,
                    "reading_solver": solver,
                }[request.stage]
                return InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=f"legacy-{len(self.requests)}",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:01:00+00:00",
                    provider=self.provider,
                    model="offline",
                    cli_version=self.cli_version,
                    exit_code=0,
                    parsed=copy.deepcopy(parsed),
                    input_keys=list(request.input_keys),
                )

        runtime = LegacyIdentityRuntime()
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(runtime).run(1001, domain="biology", output_dir=Path(directory))
            root = Path(directory)
            self.assertEqual(result["decision"], "ACCEPT")
            self.assertEqual(result["passage_id"], plan["passage_id"])
            self.assertEqual(result["generator"]["passage_id"], plan["passage_id"])
            self.assertEqual(json.loads((root / "generator_raw.json").read_text(encoding="utf-8")), raw_snapshot)
            provenance = json.loads((root / "provenance" / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["generator_raw_artifact"], "generator_raw.json")
            self.assertTrue(provenance["generator_raw_sha256"].startswith("sha256:"))

            canonical_by_stem = {question["stem"]: question for question in result["generator"]["questions"]}
            permuted_by_stem = {question["stem"]: question for question in permuted["questions"]}
            for raw_question in raw_snapshot["questions"]:
                canonical_question = canonical_by_stem[raw_question["stem"]]
                expected_question = permuted_by_stem[raw_question["stem"]]
                self.assertEqual(canonical_question["stem"], raw_question["stem"])
                self.assertEqual(canonical_question["choices"], expected_question["choices"])
                self.assertEqual(canonical_question["correct_answer"], expected_question["correct_answer"])
                self.assertEqual(canonical_question["evidence"], raw_question["evidence"])

            self.assertEqual(
                Counter(question["question_type"] for question in result["generator"]["questions"]),
                Counter(plan["question_type_counts"]),
            )
            self.assertEqual(result["checks"]["blind_errors"], [])
            self.assertTrue(result["checks"]["reviewer_contract"])
            self.assertTrue(result["checks"]["solver_contract"])

        self.assertEqual(len(runtime.requests), 4)
        for request in runtime.requests[1:]:
            payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
            self.assertEqual(payload["passage_id"], plan["passage_id"])
            expected_fields = {"item_id", "stem", "choices"} if request.stage == "reading_inference_verifier" else {"item_id", "number", "stem", "choices"}
            self.assertTrue(all(set(question) == expected_fields for question in payload["questions"]))

    def test_variable_plan_is_replayable_and_repeated_types_are_valid(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        self.assertEqual(plan, build_plan_v02(1001, domain="biology"))
        self.assertEqual(plan["question_count"], len(plan["question_plan"]))
        self.assertEqual(sum(plan["question_type_counts"].values()), plan["question_count"])
        self.assertEqual(validate_plan_contract(plan), [])
        self.assertGreaterEqual(plan["question_count"], 7)
        self.assertLessEqual(plan["question_count"], 14)
        self.assertLess(len(set(plan["question_plan"])), len(plan["question_plan"]))
        generator = variable_generator_fixture(plan)
        self.assertEqual(validate_generator_contract(generator, plan), [])
        malformed = copy.deepcopy(generator)
        malformed["questions"].pop()
        self.assertTrue(validate_generator_contract(malformed, plan))

    def test_same_question_type_multiset_in_different_order_passes(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        generator = variable_generator_fixture(plan)
        types = list(reversed(plan["question_plan"]))
        if types == plan["question_plan"]:
            types = types[1:] + types[:1]
        for question, question_type in zip(generator["questions"], types):
            question["question_type"] = question_type
            question["subtype"] = {
                "DETAIL": "DIRECT_FACTUAL_DETAIL",
                "VOCABULARY_IN_CONTEXT": "VOCABULARY_CONTEXT_MEANING",
                "INFERENCE": "LOCAL_INFERENCE",
                "MAIN_IDEA": "PASSAGE_MAIN_IDEA",
                "REFERENCE": "ANTECEDENT_REFERENCE",
            }[question_type]
        self.assertEqual(validate_generator_contract(generator, plan), [])

    def test_wrong_question_type_multiset_fails(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        generator = variable_generator_fixture(plan)
        original = generator["questions"][0]["question_type"]
        replacement = next(question_type for question_type in ("DETAIL", "VOCABULARY_IN_CONTEXT", "INFERENCE", "MAIN_IDEA", "REFERENCE") if question_type != original)
        generator["questions"][0]["question_type"] = replacement
        generator["questions"][0]["subtype"] = {
            "DETAIL": "DIRECT_FACTUAL_DETAIL",
            "VOCABULARY_IN_CONTEXT": "VOCABULARY_CONTEXT_MEANING",
            "INFERENCE": "LOCAL_INFERENCE",
            "MAIN_IDEA": "PASSAGE_MAIN_IDEA",
            "REFERENCE": "ANTECEDENT_REFERENCE",
        }[replacement]
        errors = validate_generator_contract(generator, plan)
        self.assertTrue(any("type counts" in error for error in errors))
        self.assertEqual(deterministic_diagnostics(generator, plan)["classification"], FORMAT_ADHERENCE_FAILURE)

    def test_v02_passage_length_and_paragraph_profile(self) -> None:
        plan = build_plan_v02(1001, domain="biology")

        too_short = sized_generator_fixture(plan, 67, 1)
        short_errors = validate_deterministic(too_short, plan)
        self.assertTrue(any("word count 67 is below 160" in error for error in short_errors))
        self.assertEqual(deterministic_diagnostics(too_short, plan)["classification"], HARD_VALIDITY)

        preferred_short = sized_generator_fixture(plan, 180, 3)
        self.assertEqual(validate_deterministic(preferred_short, plan), [])
        preferred_short_report = deterministic_diagnostics(preferred_short, plan)
        self.assertEqual(preferred_short_report["passage_word_count"], 180)
        self.assertEqual(preferred_short_report["paragraph_count"], 3)
        self.assertEqual(preferred_short_report["classification"], "VALID")

        preferred_long = sized_generator_fixture(plan, 292, 4)
        self.assertEqual(validate_deterministic(preferred_long, plan), [])

        above_band = sized_generator_fixture(plan, 320, 4)
        self.assertEqual(validate_deterministic(above_band, plan), [])
        above_band_report = deterministic_diagnostics(above_band, plan)
        self.assertEqual(above_band_report["classification"], EMPIRICAL_FORMAT_WARNING)
        self.assertTrue(above_band_report["empirical_warnings"])

    def test_generator_instruction_and_schema_use_exact_type_counts(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        trace = BatchTrace()
        runtime = BatchFakeRuntime("contract", trace)
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(runtime).run(1001, domain="biology", output_dir=Path(directory))
        self.assertEqual(result["decision"], "ACCEPT")
        generator_request = next(request for request in trace.requests if request.stage == "reading_generator")
        payload = json.loads(generator_request.prompt.split("INPUT_JSON:\n", 1)[1])
        self.assertEqual(payload["question_type_counts"], plan["question_type_counts"])
        self.assertNotIn("question_plan", payload)
        assert generator_request.transport_output_schema is not None
        for question_type, field in (
            ("DETAIL", "detail_questions"),
            ("VOCABULARY_IN_CONTEXT", "vocabulary_in_context_questions"),
            ("INFERENCE", "inference_questions"),
            ("MAIN_IDEA", "main_idea_questions"),
            ("REFERENCE", "reference_questions"),
        ):
            self.assertEqual(
                generator_request.transport_output_schema["properties"][field]["minItems"],
                plan["question_type_counts"][question_type],
            )
            self.assertEqual(
                generator_request.transport_output_schema["properties"][field]["maxItems"],
                plan["question_type_counts"][question_type],
            )
        self.assertIn("exactly match question_type_counts", generator_request.prompt)
        self.assertIn("ordering of the generated questions is free", generator_request.prompt)
        self.assertIn("Fact A, Fact B, and an unstated conclusion", generator_request.prompt)
        self.assertIn("Fact A and Fact B must be two distinct textual propositions", generator_request.prompt)
        self.assertIn("final keyed option must express the unstated conclusion", generator_request.prompt)
        self.assertIn("private rationale must identify both facts", generator_request.prompt)
        self.assertIn("one single passage proposition is sufficient to obtain the answer", generator_request.prompt)
        self.assertIn("keyed answer must not be explicitly stated", generator_request.prompt)
        self.assertIn("must not be obtainable merely by replacing words", generator_request.prompt)
        self.assertIn("ordinary synonym substitution", generator_request.prompt)
        self.assertIn("rewrite the inference item rather than labeling the paraphrase", generator_request.prompt)
        self.assertIn("at least one reasoning step from the passage", generator_request.prompt)
        self.assertIn("Local inference is allowed", generator_request.prompt)
        self.assertIn("Cross-idea inference is allowed", generator_request.prompt)
        self.assertIn("Do not manufacture unnecessary multi-sentence complexity", generator_request.prompt)
        self.assertIn("unsupported or ambiguous inference is worse than a shallow inference", generator_request.prompt)
        self.assertIn("both ordinary dictionary senses and context-clarified senses are acceptable", generator_request.prompt)
        self.assertIn("Do not require strong context dependence", generator_request.prompt)
        self.assertIn("actual sense in its local sentence", generator_request.prompt)
        self.assertIn("grammatical construction, collocation, and local context", generator_request.prompt)
        self.assertIn("rationale must explain why the keyed sense fits the local usage", generator_request.prompt)
        self.assertNotIn("rather than direct sentence lookup", generator_request.prompt)
        self.assertNotIn("avoid dictionary-only answers", generator_request.prompt)
        self.assertNotIn("determined by", generator_request.prompt)
        self.assertNotIn("decided by", generator_request.prompt)
        self.assertIn("approximate information density", generator_request.prompt)
        self.assertIn("without padding for exact character-length equality", generator_request.prompt)
        self.assertNotIn("exact planned question_plan order", generator_request.prompt)
        reviewer_request = next(request for request in trace.requests if request.stage == "reading_reviewer")
        self.assertIn(" ".join(READING_REVIEWER_INFERENCE_GUIDANCE.split()), reviewer_request.prompt)
        generator_agent = (ROOT / ".claude" / "agents" / "toefl-itp-reading-generator-v0.2.md").read_text(encoding="utf-8")
        generator_agent = " ".join(generator_agent.split())
        self.assertIn("question_type_counts", generator_agent)
        self.assertIn("Fact A, Fact B, and an unstated conclusion", generator_agent)
        self.assertIn("Fact A and Fact B must be two distinct textual propositions", generator_agent)
        self.assertIn("final keyed option must express the unstated conclusion", generator_agent)
        self.assertIn("private rationale must identify both facts", generator_agent)
        self.assertIn("one single passage proposition is sufficient to obtain the answer", generator_agent)
        self.assertIn("keyed answer must not be explicitly stated", generator_agent)
        self.assertIn("must not be obtainable merely by replacing words", generator_agent)
        self.assertIn("ordinary synonym substitution", generator_agent)
        self.assertIn("rewrite the inference item rather than labeling the paraphrase", generator_agent)
        self.assertIn("at least one reasoning step from the passage", generator_agent)
        self.assertIn("Local inference is allowed", generator_agent)
        self.assertIn("Cross-idea inference is allowed", generator_agent)
        self.assertIn("Do not manufacture unnecessary multi-sentence complexity", generator_agent)
        self.assertIn("unsupported or ambiguous inference is worse than a shallow inference", generator_agent)
        self.assertIn("both ordinary dictionary senses and context-clarified senses are acceptable", generator_agent)
        self.assertIn("Do not require strong context", generator_agent)
        self.assertIn("grammatical construction, collocation, and local", generator_agent)
        self.assertIn("rationale must explain why the keyed", generator_agent)
        self.assertNotIn("rather than locate a sentence that directly", generator_agent)
        self.assertNotIn("Avoid words for which ordinary dictionary meaning alone", generator_agent)
        self.assertNotIn("determined by", generator_agent)
        self.assertNotIn("decided by", generator_agent)
        self.assertIn("approximate information", generator_agent)

    def test_draft_generator_instruction_uses_same_calibration(self) -> None:
        trace = BatchTrace()
        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(BatchFakeRuntime("draft", trace)).run_draft(
                1001,
                domain="biology",
                output_dir=Path(directory),
            )
        self.assertEqual(result["decision"], "UNVALIDATED_DRAFT")
        draft_request = next(request for request in trace.requests if request.stage == "reading_generator")
        for required in (
            "Fact A, Fact B, and an unstated conclusion",
            "Fact A and Fact B must be two distinct textual propositions",
            "final keyed option must express the unstated conclusion",
            "private rationale must identify both facts",
            "one single passage proposition is sufficient to obtain the answer",
            "keyed answer must not be explicitly stated",
            "must not be obtainable merely by replacing words",
            "ordinary synonym substitution",
            "rewrite the inference item rather than labeling the paraphrase",
            "at least one reasoning step from the passage",
            "Local inference is allowed",
            "Cross-idea inference is allowed",
            "Do not manufacture unnecessary multi-sentence complexity",
            "unsupported or ambiguous inference is worse than a shallow inference",
            "both ordinary dictionary senses and context-clarified senses are acceptable",
            "Do not require strong context dependence",
            "actual sense in its local sentence",
            "grammatical construction, collocation, and local context",
            "rationale must explain why the keyed sense fits the local usage",
        ):
            self.assertIn(required, draft_request.prompt)
        for forbidden in (
            "rather than direct sentence lookup",
            "avoid dictionary-only answers",
            "determined by",
            "decided by",
        ):
            self.assertNotIn(forbidden, draft_request.prompt)

    def test_v028_generator_guidance_is_synchronized_without_new_quotas(self) -> None:
        trace = BatchTrace()
        with TemporaryDirectory() as directory:
            ReadingV02Pipeline(BatchFakeRuntime("prompt", trace)).run(
                1205, domain="biology", output_dir=Path(directory)
            )
        generator_request = next(request for request in trace.requests if request.stage == "reading_generator")
        prompt = generator_request.prompt
        agent = " ".join(
            (ROOT / ".claude" / "agents" / "toefl-itp-reading-generator-v0.2.md")
            .read_text(encoding="utf-8")
            .split()
        )
        self.assertIn(" ".join(READING_INFERENCE_GUIDANCE.split()), prompt)
        self.assertIn(" ".join(READING_LENGTH_GUIDANCE.split()), prompt)
        paragraph_guidance = " ".join(READING_PARAGRAPH_GUIDANCE.split())
        self.assertIn(paragraph_guidance, prompt)
        self.assertIn(paragraph_guidance, agent)
        self.assertIn("blank line (`\\n\\n`)", prompt)
        self.assertIn("Evidence paragraph numbers must correspond exactly to the canonical paragraphs", prompt)
        self.assertIn("paragraph count as guidance only", prompt)
        self.assertNotIn("exactly four non-empty paragraphs", prompt.casefold())
        self.assertNotIn("exactly four non-empty paragraphs", agent.casefold())
        self.assertNotRegex(prompt.casefold(), r"exactly\s+(?:four|4)\s+(?:non-empty\s+)?paragraphs?")
        self.assertNotRegex(agent.casefold(), r"exactly\s+(?:four|4)\s+(?:non-empty\s+)?paragraphs?")
        self.assertIn(" ".join(READING_INFERENCE_GUIDANCE.split()), agent)
        self.assertIn(" ".join(READING_LENGTH_GUIDANCE.split()), agent)
        self.assertIn(reading_v02_generator_instruction(), prompt)
        self.assertNotIn("%", prompt)
        self.assertNotIn("25/25/25/25", prompt)
        self.assertNotIn("answer-position quota", prompt.casefold())
        self.assertNotIn("%", agent)
        self.assertNotIn("25/25/25/25", agent)
        self.assertNotIn("answer-position quota", agent.casefold())
        self.assertIn("both ordinary dictionary senses and context-clarified senses are acceptable", prompt)
        self.assertIn("both ordinary dictionary senses and context-clarified senses are acceptable", agent)

    def test_historical_v02_passages_001_and_002_are_unchanged(self) -> None:
        required = [HISTORICAL_ARTIFACT_ROOT / relative_path for relative_path in HISTORICAL_ARTIFACT_HASHES]
        if not all(path.is_file() for path in required):
            self.skipTest("historical local Reading v0.2 artifacts are not present")
        for relative_path, expected_hash in HISTORICAL_ARTIFACT_HASHES.items():
            actual_hash = hashlib.sha256((HISTORICAL_ARTIFACT_ROOT / relative_path).read_bytes()).hexdigest().upper()
            self.assertEqual(actual_hash, expected_hash, relative_path)

    def test_historical_v01_smoke_path_remains_available(self) -> None:
        plan = build_plan_v02(1001, domain="biology")
        self.assertEqual(build_plan_v02(1001, domain="biology"), plan)
        legacy_plan, legacy_generator = generator_fixture(7)
        self.assertEqual(legacy_plan["schema_version"], "reading-plan-v0.1")
        self.assertEqual(len(legacy_generator["questions"]), 5)
        self.assertEqual(validate_generator_contract(legacy_generator, legacy_plan), [])

    def test_batch_is_bounded_isolated_and_inference_gate_calls_per_success(self) -> None:
        trace = BatchTrace()

        def factory(index: int) -> BatchFakeRuntime:
            return BatchFakeRuntime(str(index), trace)

        with TemporaryDirectory() as directory:
            batch = run_reading_batch(
                1001,
                count=3,
                parallel=2,
                domain="biology",
                output_dir=Path(directory),
                runtime_factory=factory,
            )
            root = Path(directory)
            self.assertEqual(batch["requested_passage_count"], 3)
            self.assertEqual(batch["completed_passage_count"], 3)
            self.assertEqual(batch["accept_count"], 3)
            self.assertEqual(batch["quarantine_count"], 0)
            self.assertEqual(batch["infrastructure_failure_count"], 0)
            self.assertEqual(batch["total_live_invocation_count"], 12)
            self.assertEqual(batch["generator_invocation_count"], 3)
            self.assertEqual(batch["reviewer_invocation_count"], 3)
            self.assertEqual(batch["solver_invocation_count"], 3)
            self.assertEqual(batch["inference_verifier_invocation_count"], 3)
            self.assertEqual(batch["inference_repair_invocation_count"], 0)
            self.assertGreater(batch["total_questions_generated"], 15)
            self.assertLessEqual(trace.max_active, 2)
            self.assertEqual([item["seed"] for item in batch["passage_artifacts"]], [1001, 1002, 1003])
            self.assertEqual(len({item["run_id"] for item in batch["passage_artifacts"]}), 3)
            self.assertTrue((root / "batch_result.json").is_file())
            self.assertEqual(json.loads((root / "batch_result.json").read_text(encoding="utf-8"))["batch_id"], batch["batch_id"])
            self.assertEqual(
                sorted(path.name for path in root.iterdir() if path.is_dir()),
                ["passage-001", "passage-002", "passage-003"],
            )
            for index in range(1, 4):
                passage_dir = root / f"passage-{index:03d}"
                self.assertTrue((passage_dir / "generator.json").is_file())
                self.assertTrue((passage_dir / "reviewer.json").is_file())
                self.assertTrue((passage_dir / "solver.json").is_file())
                self.assertTrue((passage_dir / "provenance" / "provenance.json").is_file())
                passage_result = json.loads((passage_dir / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(passage_result["passage_id"], f"rc-{1000 + index:08x}")
            self.assertFalse(list(root.rglob("*.tmp")))
            self.assertEqual(len({str(request.artifact_dir) for request in trace.requests}), 3)
        for request in trace.requests:
            self.assertEqual(request.isolate_workspace, request.stage in {"reading_inference_verifier", "reading_reviewer", "reading_solver"})
            if request.stage in {"reading_inference_verifier", "reading_reviewer", "reading_solver"}:
                payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
                self.assertNotIn("correct_answer", request.prompt)
                self.assertNotIn("question_type", request.prompt)
                expected_fields = {"item_id", "stem", "choices"} if request.stage == "reading_inference_verifier" else {"item_id", "number", "stem", "choices"}
                self.assertTrue(all(set(question) == expected_fields for question in payload["questions"]))

    def test_failed_passage_is_infrastructure_failure_without_cancelling_others(self) -> None:
        trace = BatchTrace()

        def factory(index: int) -> BatchFakeRuntime:
            return BatchFakeRuntime(str(index), trace, fail_generator=index == 2)

        with TemporaryDirectory() as directory:
            batch = run_reading_batch(
                1001,
                count=3,
                parallel=2,
                output_dir=Path(directory),
                runtime_factory=factory,
            )
            decisions = [item["decision"] for item in batch["passage_decisions"]]
            self.assertEqual(decisions, ["ACCEPT", "INFRASTRUCTURE_FAILURE", "ACCEPT"])
            self.assertEqual(batch["total_live_invocation_count"], 9)
            self.assertEqual(batch["generator_invocation_count"], 3)
            self.assertEqual(batch["reviewer_invocation_count"], 2)
            self.assertEqual(batch["solver_invocation_count"], 2)
            self.assertEqual(batch["inference_verifier_invocation_count"], 2)
            self.assertEqual(batch["infrastructure_failure_count"], 1)
            failure_result = json.loads((Path(directory) / "passage-002" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(failure_result["decision"], "INFRASTRUCTURE_FAILURE")
            self.assertEqual(failure_result["infrastructure"]["runtime_failures"][0]["stage"], "reading_generator")

    def test_draft_mode_is_explicitly_non_production_and_generator_only(self) -> None:
        trace = BatchTrace()

        with TemporaryDirectory() as directory:
            batch = run_reading_batch(
                2001,
                count=2,
                parallel=2,
                mode="draft",
                output_dir=Path(directory),
                runtime_factory=lambda index: BatchFakeRuntime(str(index), trace),
            )
            self.assertEqual(batch["draft_count"], 2)
            self.assertEqual(batch["total_live_invocation_count"], 2)
            self.assertEqual(batch["reviewer_invocation_count"], 0)
            self.assertEqual(batch["solver_invocation_count"], 0)
            for index in range(1, 3):
                result = json.loads((Path(directory) / f"passage-{index:03d}" / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["decision"], "UNVALIDATED_DRAFT")
                self.assertFalse(result["production_eligible"])
                self.assertEqual(result["draft_status"], "VALIDATED_SHAPE")
                self.assertIsNone(result["reviewer"])
                self.assertIsNone(result["solver"])
                self.assertFalse((Path(directory) / f"passage-{index:03d}" / "reviewer.json").exists())
                self.assertFalse((Path(directory) / f"passage-{index:03d}" / "solver.json").exists())

    def test_direct_v02_pipeline_preserves_first_pass_quality_quarantine(self) -> None:
        plan = build_plan_v02(3001)
        generator = variable_generator_fixture(plan)
        canonical = canonicalize_generator_output(generator, plan)
        permuted, _permutation = permute_generator_choices(canonical, plan)
        reviewer = reviewer_for(permuted)
        verifier = inference_verifier_for(permuted)
        solver = solver_for(permuted)
        solver["answers"][0]["answer"] = "AMBIGUOUS"

        class SingleRuntime(BatchFakeRuntime):
            def invoke(self, request):
                if request.stage == "reading_generator":
                    self.generators[generator["passage_id"]] = generator
                    parsed = generator
                elif request.stage == "reading_inference_verifier":
                    parsed = verifier
                elif request.stage == "reading_reviewer":
                    parsed = reviewer
                elif request.stage == "reading_solver":
                    parsed = solver
                else:
                    raise AssertionError(f"unexpected stage: {request.stage}")
                return InvocationResult(
                    stage=request.stage,
                    agent_name=request.agent_name,
                    invocation_id=f"single-{request.stage}",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:01+00:00",
                    provider="fake",
                    model="offline",
                    cli_version="offline",
                    exit_code=0,
                    parsed=copy.deepcopy(parsed),
                    input_keys=list(request.input_keys),
                )

        with TemporaryDirectory() as directory:
            result = ReadingV02Pipeline(SingleRuntime("single", BatchTrace())).run(
                plan["seed"], output_dir=Path(directory)
            )
            self.assertEqual(result["decision"], "QUARANTINE")
            self.assertEqual(result["infrastructure"]["live_invocations"], 4)
            self.assertEqual(result["solver"]["answers"][0]["answer"], "AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
