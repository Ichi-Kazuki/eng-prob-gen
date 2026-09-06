"""Offline tests for the deterministic Production Assembly layer.

No model/provider/live calls. Structure fixtures reuse the offline pipeline
machinery from tests.test_structure_v03 (a scripted fake runtime). Reading
and Written Expression fixtures are small, hand-built, schema-valid source
directories. The WE production validator subprocess boundary is mocked; the
real validator has its own dedicated test suite and is not duplicated here.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from runtime.freeze import sha256_file
from shared.json_io import atomic_write_json, canonical_json_sha256
from shared.schema_validation import load_schema, schema_errors

from production import adapters, assembly
from production.adapters import ProductionSourceError
from production.assembly import ProductionAssemblyError, assemble_problem_bank, write_problem_bank
from production import cli as production_cli

from tests.test_structure_v03 import FakeV03Runtime, _run_pipeline


ROOT = Path(__file__).resolve().parents[1]
BANK_SCHEMA = load_schema(assembly.SCHEMA_PATH)


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# Structure v0.3 fixture helpers
# ---------------------------------------------------------------------------


def _build_structure_accept_run(directory: Path, seed: int = 11) -> Path:
    runtime = FakeV03Runtime()
    _run_pipeline(runtime, seed=seed, tmp_dir=directory)
    return directory


# ---------------------------------------------------------------------------
# Reading v0.2.12 fixture helpers
# ---------------------------------------------------------------------------


def _distractor_entry(letter: str, correct_letter: str, item_id: str) -> dict[str, Any]:
    if letter == correct_letter:
        return {"category": "CORRECT_OPTION", "rationale": f"{item_id}:{letter} is correct because the evidence supports it."}
    categories = ["TEXT_TRUE_BUT_NOT_ANSWER", "WRONG_REFERENT", "SCOPE_SHIFT"]
    category = categories[hash((item_id, letter)) % len(categories)]
    return {"category": category, "rationale": f"{item_id}:{letter} rationale explaining why this choice is wrong."}


def _reading_question(
    item_id: str,
    question_type: str,
    subtype: str,
    correct: str,
    *,
    target_text: str | None = None,
    target_line: int | None = None,
) -> dict[str, Any]:
    question: dict[str, Any] = {
        "item_id": item_id,
        "question_type": question_type,
        "subtype": subtype,
        "stem": f"According to the passage, what does the evidence for {item_id} best support?",
        "choices": {
            "A": "The observatory records signals reliably.",
            "B": "The engineers ignore seasonal changes.",
            "C": "The comets are visible without instruments.",
            "D": "The telescopes require no calibration.",
        },
        "correct_answer": correct,
        "evidence": {
            "paragraph": 1,
            "anchor": "distant comets using radio telescopes",
            "rationale": f"The anchor text directly supports the correct answer for {item_id}.",
        },
        "distractor_metadata": {
            letter: _distractor_entry(letter, correct, item_id) for letter in ("A", "B", "C", "D")
        },
    }
    if target_text is not None:
        question["target_text"] = target_text
    if target_line is not None:
        question["target_line"] = target_line
    return question


READING_PASSAGE_TEXT = (
    "The observatory tracks distant comets using radio telescopes that record faint "
    "signals from the outer solar system every night of operation.\n\n"
    "Engineers calibrate the equipment every season to maintain accuracy across "
    "changing weather conditions and shifting atmospheric interference patterns."
)


def _reading_generator_fixture(passage_id: str = "rc-fixture01") -> dict[str, Any]:
    return {
        "schema_version": "reading-generator-v0.2",
        "passage_id": passage_id,
        "section": "READING_COMPREHENSION",
        "title": "Comet Tracking Techniques",
        "passage": READING_PASSAGE_TEXT,
        "questions": [
            _reading_question(f"{passage_id}-q1", "MAIN_IDEA", "PASSAGE_MAIN_IDEA", "A"),
            _reading_question(f"{passage_id}-q2", "DETAIL", "DIRECT_FACTUAL_DETAIL", "A"),
            _reading_question(f"{passage_id}-q3", "DETAIL", "DIRECT_FACTUAL_DETAIL", "B"),
            _reading_question(
                f"{passage_id}-q4", "VOCABULARY_IN_CONTEXT", "VOCABULARY_CONTEXT_MEANING", "C",
                target_text="calibrate", target_line=3,
            ),
            _reading_question(
                f"{passage_id}-q5", "REFERENCE", "ANTECEDENT_REFERENCE", "D",
                target_text="the equipment",
            ),
            _reading_question(f"{passage_id}-q6", "INFERENCE", "LOCAL_INFERENCE", "A"),
            _reading_question(f"{passage_id}-q7", "DETAIL", "DIRECT_FACTUAL_DETAIL", "B"),
        ],
    }


def _reading_result_fixture(run_id: str, generator: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading-result-v0.2",
        "run_id": run_id,
        "decision": "ACCEPT",
        "passage_id": generator["passage_id"],
        "section": "READING_COMPREHENSION",
        "plan": {"seed": 1},
        "generator": generator,
        "reviewer": {},
        "solver": {},
        "checks": {
            "generator_canonical": True,
            "deterministic": True,
            "reviewer_contract": True,
            "reviewer_set_pass": True,
            "reviewer_no_ambiguous_none": True,
            "solver_contract": True,
            "solver_no_ambiguous_none": True,
            "all_answers_agree": True,
            "no_leakage": True,
            "no_synthetic_fallback": True,
            "inference_gate_pass": True,
        },
        "infrastructure": {
            "live_invocations": 4,
            "provider": "offline-fixture",
            "runtime_failures": [],
            "synthetic_fallback": False,
        },
    }


def _reading_provenance_fixture(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": "reading-provenance-v0.2",
        "run_id": run_id,
        "reading_version": "v0.2.12",
        "canonical_generator_artifact": "generator.json",
    }


def _build_reading_accept_run(directory: Path, *, run_id: str = "reading-v02-fixture-0001", passage_id: str = "rc-fixture01") -> Path:
    generator = _reading_generator_fixture(passage_id)
    result = _reading_result_fixture(run_id, generator)
    provenance = _reading_provenance_fixture(run_id)
    atomic_write_json(directory / "result.json", result)
    atomic_write_json(directory / "generator.json", generator)
    atomic_write_json(directory / "provenance" / "provenance.json", provenance)
    return directory


# ---------------------------------------------------------------------------
# Written Expression v2.1.3 fixture helpers
# ---------------------------------------------------------------------------


def _we_item_fixture(item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "section": "Written Expression",
        "agent_version": "Written Expression Generator v2.1",
        "primary_target": "VERB_FORM_VOICE",
        "subtype": "VERB_FORM_VOICE fixture subtype",
        "secondary_features": ["academic register"],
        "tested_error_type": "verb_form",
        "difficulty": "MEDIUM",
        "vocabulary_domain": "fixture domain",
        "sentence": "The committee reviewing the proposal have approved the budget.",
        "marked_parts": {
            "A": "reviewing",
            "B": "have",
            "C": "approved",
            "D": "the budget",
        },
        "correct_answer": "B",
        "error_explanation": "The singular subject requires 'has', not 'have'.",
        "minimal_correction": "has",
        "grammar_metadata": {
            "error_scope": "local",
            "correction_locality": "LOCAL_SINGLE_TOKEN",
            "decision_granularity": "AGREEMENT_DEPENDENCY",
            "intended_error_position": "B",
            "correct_span_type": "SINGLE_WORD",
        },
        "format_metadata": {"target_sentence_length_region": "fixture"},
        "provenance": {"agent_version": "Written Expression Generator v2.1", "generation_batch_id": "fixture-batch"},
        "qa_metadata": {"clean_form": "fixture", "grammar_check_status": "PASS"},
    }


def _build_we_run(
    directory: Path,
    *,
    item_ids: list[str],
    batch_id: str = "we-v2.1.3-fixture-0001",
    outcome_state: str = "ACCEPTED",
    test_passed: bool = True,
    tamper_after_manifest: bool = False,
    omit_file: str | None = None,
) -> Path:
    runtime_dir = directory / "runtime"
    formal_dir = runtime_dir / "formal"
    provenance_dir = runtime_dir / "provenance"
    freeze_dir = runtime_dir / "freeze"

    generator_items = [_we_item_fixture(item_id) for item_id in item_ids]
    atomic_write_json(formal_dir / "generator_outputs.json", {"items": generator_items})
    atomic_write_json(formal_dir / "reviewer_outputs.json", {"items": []})
    atomic_write_json(formal_dir / "solver_outputs.json", {"items": []})
    atomic_write_json(provenance_dir / "runtime_provenance.json", {"items": []})
    atomic_write_json(
        runtime_dir / "outcomes.json",
        {"batch_id": batch_id, "outcomes": [{"item_id": item_id, "state": outcome_state} for item_id in item_ids]},
    )
    atomic_write_json(runtime_dir / "test_result.json", {"passed": test_passed})
    atomic_write_json(freeze_dir / "freeze_manifest.json", {"freeze_manifest_version": 2, "note": "fixture"})

    relative_paths = adapters.WE_EVIDENCE_ARTIFACTS
    if omit_file is not None:
        (directory / omit_file).unlink()

    files = {}
    for relative in relative_paths:
        path = directory / relative
        if not path.is_file():
            continue
        files[relative] = {"sha256": sha256_file(path)}

    payload = {
        "artifact_manifest_version": 1,
        "freeze_manifest_sha256": "sha256:" + "0" * 64,
        "files": dict(sorted(files.items())),
    }
    payload["artifact_manifest_sha256"] = canonical_json_sha256(payload)
    atomic_write_json(runtime_dir / "artifact_manifest_v1.json", payload)

    if tamper_after_manifest:
        atomic_write_json(formal_dir / "generator_outputs.json", {"items": generator_items, "tampered": True})

    return directory


def _we_evidence_path(directory: Path) -> Path:
    path = directory / "grammar_evidence.json"
    atomic_write_json(path, {"items": []})
    return path


# ---------------------------------------------------------------------------
# Structure adapter tests
# ---------------------------------------------------------------------------


class StructureAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_accepted_run_normalizes(self) -> None:
        run_dir = _build_structure_accept_run(self.tmp)
        loaded = adapters.load_structure_source(run_dir)
        self.assertEqual(loaded["source"]["section"], "Structure")
        self.assertEqual(loaded["source"]["pipeline_version"], "v0.3")
        self.assertEqual(len(loaded["items"]), 15)
        first = loaded["items"][0]
        generator = json.loads((run_dir / "generator.json").read_text(encoding="utf-8"))
        self.assertEqual(first["options"], generator["items"][0]["options"])
        self.assertEqual(first["correct_answer"], generator["items"][0]["correct_answer"])
        self.assertEqual(first["source_id"], loaded["source"]["source_id"])

    def test_real_quarantine_run_rejected(self) -> None:
        quarantine_dir = ROOT / "runs" / "structure_v0_3" / "structure-v03-live-20260905T125844Z-seed2026090504"
        with self.assertRaises(ProductionSourceError):
            adapters.load_structure_source(quarantine_dir)

    def test_item_results_false_rejected(self) -> None:
        run_dir = _build_structure_accept_run(self.tmp)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        result["item_results"][0]["accepted"] = False
        atomic_write_json(run_dir / "result.json", result)
        with self.assertRaises(ProductionSourceError):
            adapters.load_structure_source(run_dir)

    def test_run_identity_mismatch_rejected(self) -> None:
        run_dir = _build_structure_accept_run(self.tmp)
        provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
        provenance["run_id"] = provenance["run_id"] + "-tampered"
        atomic_write_json(run_dir / "provenance.json", provenance)
        with self.assertRaises(ProductionSourceError):
            adapters.load_structure_source(run_dir)

    def test_tampered_generator_hash_rejected(self) -> None:
        run_dir = _build_structure_accept_run(self.tmp)
        generator = json.loads((run_dir / "generator.json").read_text(encoding="utf-8"))
        generator["items"][0]["stem"] = generator["items"][0]["stem"] + " "
        atomic_write_json(run_dir / "generator.json", generator)
        with self.assertRaises(ProductionSourceError):
            adapters.load_structure_source(run_dir)

    def test_duplicate_item_id_rejected(self) -> None:
        run_dir = _build_structure_accept_run(self.tmp)
        generator = json.loads((run_dir / "generator.json").read_text(encoding="utf-8"))
        generator["items"][1]["item_id"] = generator["items"][0]["item_id"]
        atomic_write_json(run_dir / "generator.json", generator)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        result["artifact_hashes"]["generator.json"] = canonical_json_sha256(generator)
        atomic_write_json(run_dir / "result.json", result)
        provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
        provenance["artifact_hashes"] = result["artifact_hashes"]
        atomic_write_json(run_dir / "provenance.json", provenance)
        with self.assertRaises(ProductionSourceError):
            adapters.load_structure_source(run_dir)


# ---------------------------------------------------------------------------
# Reading adapter tests
# ---------------------------------------------------------------------------


class ReadingAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_accepted_run_normalizes(self) -> None:
        run_dir = _build_reading_accept_run(self.tmp)
        loaded = adapters.load_reading_source(run_dir)
        self.assertEqual(loaded["source"]["section"], "Reading")
        self.assertEqual(loaded["source"]["pipeline_version"], "v0.2.12")
        passage = loaded["passage"]
        self.assertEqual(passage["title"], "Comet Tracking Techniques")
        self.assertEqual(passage["passage"], READING_PASSAGE_TEXT)
        self.assertEqual(len(passage["questions"]), 7)
        self.assertEqual(
            [q["item_id"] for q in passage["questions"]],
            [f"rc-fixture01-q{i}" for i in range(1, 8)],
        )
        vocab_question = passage["questions"][3]
        self.assertEqual(vocab_question["target_text"], "calibrate")
        self.assertEqual(vocab_question["target_line"], 3)
        reference_question = passage["questions"][4]
        self.assertEqual(reference_question["target_text"], "the equipment")
        self.assertNotIn("target_line", reference_question)
        main_idea_question = passage["questions"][0]
        self.assertNotIn("target_text", main_idea_question)
        self.assertNotIn("target_line", main_idea_question)
        self.assertEqual(
            main_idea_question["explanation"]["evidence_paragraph"], 1,
        )
        self.assertEqual(
            main_idea_question["explanation"]["evidence_anchor"], "distant comets using radio telescopes",
        )
        self.assertIn("rc-fixture01-q1", main_idea_question["explanation"]["answer_rationale"])
        for letter in ("A", "B", "C", "D"):
            self.assertIn(f"rc-fixture01-q1:{letter}", main_idea_question["explanation"]["choice_rationales"][letter])
        raw_serialized = json.dumps(passage)
        self.assertNotIn("distractor_metadata", raw_serialized)
        self.assertNotIn("CORRECT_OPTION", raw_serialized)

    def test_quarantine_rejected(self) -> None:
        run_dir = _build_reading_accept_run(self.tmp)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        result["decision"] = "QUARANTINE"
        atomic_write_json(run_dir / "result.json", result)
        with self.assertRaises(ProductionSourceError):
            adapters.load_reading_source(run_dir)

    def test_infrastructure_failure_rejected(self) -> None:
        run_dir = _build_reading_accept_run(self.tmp)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        result["decision"] = "INFRASTRUCTURE_FAILURE"
        atomic_write_json(run_dir / "result.json", result)
        with self.assertRaises(ProductionSourceError):
            adapters.load_reading_source(run_dir)

    def test_draft_result_rejected(self) -> None:
        run_dir = _build_reading_accept_run(self.tmp)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        result["schema_version"] = "reading-draft-result-v0.2"
        result["decision"] = "UNVALIDATED_DRAFT"
        atomic_write_json(run_dir / "result.json", result)
        with self.assertRaises(ProductionSourceError):
            adapters.load_reading_source(run_dir)

    def test_wrong_provenance_reading_version_rejected(self) -> None:
        run_dir = _build_reading_accept_run(self.tmp)
        provenance = json.loads((run_dir / "provenance" / "provenance.json").read_text(encoding="utf-8"))
        provenance["reading_version"] = "v0.2.8"
        atomic_write_json(run_dir / "provenance" / "provenance.json", provenance)
        with self.assertRaises(ProductionSourceError):
            adapters.load_reading_source(run_dir)

    def test_generator_mismatch_with_result_generator_rejected(self) -> None:
        run_dir = _build_reading_accept_run(self.tmp)
        generator = json.loads((run_dir / "generator.json").read_text(encoding="utf-8"))
        generator["title"] = "Tampered title"
        atomic_write_json(run_dir / "generator.json", generator)
        with self.assertRaises(ProductionSourceError):
            adapters.load_reading_source(run_dir)

    def test_duplicate_question_id_rejected(self) -> None:
        run_dir = _build_reading_accept_run(self.tmp)
        generator = json.loads((run_dir / "generator.json").read_text(encoding="utf-8"))
        generator["questions"][1]["item_id"] = generator["questions"][0]["item_id"]
        atomic_write_json(run_dir / "generator.json", generator)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        result["generator"] = generator
        atomic_write_json(run_dir / "result.json", result)
        with self.assertRaises(ProductionSourceError):
            adapters.load_reading_source(run_dir)


# ---------------------------------------------------------------------------
# Written Expression adapter tests
# ---------------------------------------------------------------------------


class WrittenExpressionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.item_ids = ["we-fixture-001", "we-fixture-002"]

    def test_valid_source_normalizes_with_mocked_validator(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=self.item_ids)
        evidence_path = _we_evidence_path(self.tmp)
        with patch.object(adapters.subprocess, "run") as mocked_run:
            mocked_run.return_value.returncode = 0
            loaded = adapters.load_written_expression_source(run_dir, evidence_path)
        mocked_run.assert_called_once()
        call_args = mocked_run.call_args[0][0]
        self.assertNotIn("--legacy-v20", call_args)
        self.assertEqual(loaded["source"]["section"], "Written Expression")
        self.assertEqual(loaded["source"]["pipeline_version"], "v2.1.3")
        self.assertEqual(len(loaded["items"]), 2)
        item = loaded["items"][0]
        self.assertEqual(item["explanation"]["error_explanation"], "The singular subject requires 'has', not 'have'.")
        self.assertEqual(item["explanation"]["minimal_correction"], "has")
        self.assertEqual(item["taxonomy"]["error_scope"], "local")
        serialized = json.dumps(item)
        for forbidden in ("format_metadata", "qa_metadata", "provenance"):
            self.assertNotIn(forbidden, serialized)

    def test_valid_single_item_source_normalizes_with_mocked_validator(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=[self.item_ids[0]])
        evidence_path = _we_evidence_path(self.tmp)
        with patch.object(adapters.subprocess, "run") as mocked_run:
            mocked_run.return_value.returncode = 0
            loaded = adapters.load_written_expression_source(run_dir, evidence_path)
        mocked_run.assert_called_once()
        self.assertEqual([item["item_id"] for item in loaded["items"]], [self.item_ids[0]])

    def test_tampered_manifest_file_rejected(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=[self.item_ids[0]], tamper_after_manifest=True)
        evidence_path = _we_evidence_path(self.tmp)
        with self.assertRaises(ProductionSourceError):
            adapters.load_written_expression_source(run_dir, evidence_path)

    def test_missing_evidence_file_rejected(self) -> None:
        run_dir = _tmp_dir()
        self.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)
        _build_we_run(run_dir, item_ids=self.item_ids, omit_file="runtime/test_result.json")
        evidence_path = _we_evidence_path(self.tmp)
        with self.assertRaises(ProductionSourceError):
            adapters.load_written_expression_source(run_dir, evidence_path)

    def test_test_result_failed_rejected(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=self.item_ids, test_passed=False)
        evidence_path = _we_evidence_path(self.tmp)
        with self.assertRaises(ProductionSourceError):
            adapters.load_written_expression_source(run_dir, evidence_path)

    def test_non_accepted_outcome_rejected(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=[self.item_ids[0]], outcome_state="MANUAL_REVIEW")
        evidence_path = _we_evidence_path(self.tmp)
        with self.assertRaises(ProductionSourceError):
            adapters.load_written_expression_source(run_dir, evidence_path)

    def test_single_item_generator_outcome_id_mismatch_rejected(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=[self.item_ids[0]])
        outcomes_path = run_dir / "runtime" / "outcomes.json"
        outcomes = json.loads(outcomes_path.read_text(encoding="utf-8"))
        outcomes["outcomes"][0]["item_id"] = "we-fixture-mismatch"
        atomic_write_json(outcomes_path, outcomes)
        _rehash_we_manifest(run_dir)
        evidence_path = _we_evidence_path(self.tmp)
        with self.assertRaises(ProductionSourceError):
            adapters.load_written_expression_source(run_dir, evidence_path)

    def test_unknown_outcome_item_id_rejected(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=self.item_ids)
        outcomes_path = run_dir / "runtime" / "outcomes.json"
        outcomes = json.loads(outcomes_path.read_text(encoding="utf-8"))
        outcomes["outcomes"].append({"item_id": "we-fixture-unknown", "state": "ACCEPTED"})
        atomic_write_json(outcomes_path, outcomes)
        # Recompute the manifest so only the outcomes.json hash changes, isolating this check.
        _rehash_we_manifest(run_dir)
        evidence_path = _we_evidence_path(self.tmp)
        with self.assertRaises(ProductionSourceError):
            adapters.load_written_expression_source(run_dir, evidence_path)

    def test_missing_grammar_evidence_rejected(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=self.item_ids)
        with self.assertRaises(ProductionSourceError):
            adapters.load_written_expression_source(run_dir, self.tmp / "does_not_exist.json")

    def test_validator_nonzero_exit_rejected(self) -> None:
        run_dir = _build_we_run(self.tmp, item_ids=self.item_ids)
        evidence_path = _we_evidence_path(self.tmp)
        with patch.object(adapters.subprocess, "run") as mocked_run:
            mocked_run.return_value.returncode = 1
            with self.assertRaises(ProductionSourceError):
                adapters.load_written_expression_source(run_dir, evidence_path)


def _rehash_we_manifest(run_dir: Path) -> None:
    manifest_path = run_dir / "runtime" / "artifact_manifest_v1.json"
    files = {}
    for relative in adapters.WE_EVIDENCE_ARTIFACTS:
        files[relative] = {"sha256": sha256_file(run_dir / relative)}
    payload = {
        "artifact_manifest_version": 1,
        "freeze_manifest_sha256": "sha256:" + "0" * 64,
        "files": dict(sorted(files.items())),
    }
    payload["artifact_manifest_sha256"] = canonical_json_sha256(payload)
    atomic_write_json(manifest_path, payload)


# ---------------------------------------------------------------------------
# Assembly tests
# ---------------------------------------------------------------------------


class AssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _we_source(self, tmp_subdir: str, item_ids: list[str], batch_id: str) -> tuple[Path, Path]:
        run_dir = self.tmp / tmp_subdir
        _build_we_run(run_dir, item_ids=item_ids, batch_id=batch_id)
        evidence_path = _we_evidence_path(run_dir)
        return run_dir, evidence_path

    def test_single_family_builds_valid_bank(self) -> None:
        reading_dir = self.tmp / "reading-only"
        _build_reading_accept_run(reading_dir)
        bank = assemble_problem_bank(reading_runs=[reading_dir])
        self.assertEqual([], schema_errors(bank, BANK_SCHEMA))
        self.assertEqual(bank["counts"]["reading_passages"], 1)
        self.assertEqual(bank["counts"]["reading_questions"], 7)
        self.assertEqual(bank["counts"]["total_questions"], 7)
        self.assertEqual(bank["source_count"], 1)

    def test_all_three_families_combine(self) -> None:
        structure_dir = self.tmp / "structure"
        _build_structure_accept_run(structure_dir)
        reading_dir = self.tmp / "reading"
        _build_reading_accept_run(reading_dir)
        we_run, we_evidence = self._we_source("we", ["we-a-001", "we-a-002"], "we-batch-a")

        with patch.object(adapters.subprocess, "run") as mocked_run:
            mocked_run.return_value.returncode = 0
            bank = assemble_problem_bank(
                structure_runs=[structure_dir],
                written_expression_sources=[(we_run, we_evidence)],
                reading_runs=[reading_dir],
            )
        self.assertEqual([], schema_errors(bank, BANK_SCHEMA))
        self.assertEqual(bank["counts"]["structure_items"], 15)
        self.assertEqual(bank["counts"]["written_expression_items"], 2)
        self.assertEqual(bank["counts"]["reading_passages"], 1)
        self.assertEqual(bank["counts"]["reading_questions"], 7)
        self.assertEqual(bank["counts"]["total_questions"], 15 + 2 + 7)
        self.assertEqual(bank["source_count"], 3)
        self.assertEqual(
            [source["section"] for source in bank["sources"]],
            ["Structure", "Written Expression", "Reading"],
        )

    def test_deterministic_source_ordering_independent_of_cli_order(self) -> None:
        structure_a = self.tmp / "structure-a"
        _build_structure_accept_run(structure_a, seed=101)
        structure_b = self.tmp / "structure-b"
        _build_structure_accept_run(structure_b, seed=202)

        bank_forward = assemble_problem_bank(structure_runs=[structure_a, structure_b])
        bank_reversed = assemble_problem_bank(structure_runs=[structure_b, structure_a])
        ids_forward = [source["source_id"] for source in bank_forward["sources"]]
        ids_reversed = [source["source_id"] for source in bank_reversed["sources"]]
        self.assertEqual(ids_forward, sorted(ids_forward))
        self.assertEqual(ids_forward, ids_reversed)

    def test_equivalent_sources_in_different_locations_produce_equal_banks(self) -> None:
        reading_a = self.tmp / "location-a"
        _build_reading_accept_run(reading_a, run_id="reading-v02-equal-run", passage_id="rc-equalfixture")
        reading_b = self.tmp / "location-b"
        _build_reading_accept_run(reading_b, run_id="reading-v02-equal-run", passage_id="rc-equalfixture")

        bank_a = assemble_problem_bank(reading_runs=[reading_a])
        bank_b = assemble_problem_bank(reading_runs=[reading_b])
        self.assertEqual(bank_a, bank_b)

    def test_duplicate_global_item_id_fails_closed(self) -> None:
        structure_dir = self.tmp / "structure"
        _build_structure_accept_run(structure_dir, seed=55)
        reading_dir = self.tmp / "reading"
        _build_reading_accept_run(reading_dir)
        generator = json.loads((structure_dir / "generator.json").read_text(encoding="utf-8"))
        reading_generator = json.loads((reading_dir / "generator.json").read_text(encoding="utf-8"))
        # Force a collision between a Structure item_id and a Reading question item_id.
        reading_generator["questions"][0]["item_id"] = generator["items"][0]["item_id"]
        atomic_write_json(reading_dir / "generator.json", reading_generator)
        result = json.loads((reading_dir / "result.json").read_text(encoding="utf-8"))
        result["generator"] = reading_generator
        atomic_write_json(reading_dir / "result.json", result)
        with self.assertRaises(ProductionAssemblyError):
            assemble_problem_bank(structure_runs=[structure_dir], reading_runs=[reading_dir])

    def test_duplicate_source_id_in_one_section_fails_closed(self) -> None:
        structure_a = self.tmp / "structure-a"
        _build_structure_accept_run(structure_a, seed=77)
        structure_b = self.tmp / "structure-b"
        shutil.copytree(structure_a, structure_b)
        with self.assertRaises(ProductionAssemblyError):
            assemble_problem_bank(structure_runs=[structure_a, structure_b])

    def test_output_contains_no_absolute_source_paths(self) -> None:
        reading_dir = self.tmp / "reading"
        _build_reading_accept_run(reading_dir)
        bank = assemble_problem_bank(reading_runs=[reading_dir])
        for source in bank["sources"]:
            self.assertEqual(set(source), {"section", "source_id", "pipeline_version", "content_sha256"})

    def test_invalid_source_prevents_partial_output(self) -> None:
        reading_dir = self.tmp / "reading"
        _build_reading_accept_run(reading_dir)
        structure_dir = self.tmp / "structure-quarantine"
        _build_structure_accept_run(structure_dir)
        result = json.loads((structure_dir / "result.json").read_text(encoding="utf-8"))
        result["decision"] = "QUARANTINE"
        atomic_write_json(structure_dir / "result.json", result)

        output_path = self.tmp / "problem_bank.json"
        with self.assertRaises(ProductionAssemblyError):
            write_problem_bank(output_path, structure_runs=[structure_dir], reading_runs=[reading_dir])
        self.assertFalse(output_path.exists())

    def test_existing_output_not_overwritten_by_later_failure(self) -> None:
        reading_dir = self.tmp / "reading"
        _build_reading_accept_run(reading_dir)
        output_path = self.tmp / "problem_bank.json"
        first_bank = write_problem_bank(output_path, reading_runs=[reading_dir])
        original_bytes = output_path.read_bytes()

        structure_dir = self.tmp / "structure-quarantine"
        _build_structure_accept_run(structure_dir)
        result = json.loads((structure_dir / "result.json").read_text(encoding="utf-8"))
        result["decision"] = "QUARANTINE"
        atomic_write_json(structure_dir / "result.json", result)

        with self.assertRaises(ProductionAssemblyError):
            write_problem_bank(output_path, structure_runs=[structure_dir], reading_runs=[reading_dir])
        self.assertEqual(output_path.read_bytes(), original_bytes)
        self.assertEqual(json.loads(original_bytes.decode("utf-8")), first_bank)

    def test_zero_total_sources_rejected(self) -> None:
        with self.assertRaises(ProductionAssemblyError):
            assemble_problem_bank()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _tmp_dir()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_we_run_evidence_count_mismatch_rejected(self) -> None:
        run_dir = self.tmp / "we"
        _build_we_run(run_dir, item_ids=["we-cli-001"])
        exit_code = production_cli.main([
            "--we-run", str(run_dir),
            "--output", str(self.tmp / "bank.json"),
        ])
        self.assertNotEqual(exit_code, 0)

    def test_cli_success_returns_zero(self) -> None:
        reading_dir = self.tmp / "reading"
        _build_reading_accept_run(reading_dir)
        output_path = self.tmp / "bank.json"
        exit_code = production_cli.main([
            "--reading-run", str(reading_dir),
            "--output", str(output_path),
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(output_path.exists())

    def test_cli_failure_returns_nonzero(self) -> None:
        exit_code = production_cli.main(["--output", str(self.tmp / "bank.json")])
        self.assertNotEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
