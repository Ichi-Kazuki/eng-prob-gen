"""Source-specific eligibility validation and normalization adapters.

Production Assembly consumes only explicit, already-validated source run
directories. Each adapter here independently re-verifies that one supplied
source is production-eligible under its own family's frozen contract, then
normalizes only the learner/site-facing content needed for the final bank.
No model calls occur anywhere in this module.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from reading import contracts as reading_contracts
from runtime.freeze import sha256_file
from shared.json_io import JsonPersistenceError, canonical_json_sha256, read_json
from shared.schema_validation import load_schema, schema_errors


class ProductionSourceError(RuntimeError):
    """An explicitly supplied source is not production-eligible."""


REPO_ROOT = Path(__file__).resolve().parent.parent

STRUCTURE_V03_SCHEMA_DIR = REPO_ROOT / "structure" / "v03" / "schemas"
STRUCTURE_RESULT_SCHEMA = STRUCTURE_V03_SCHEMA_DIR / "result.schema.json"
STRUCTURE_PROVENANCE_SCHEMA = STRUCTURE_V03_SCHEMA_DIR / "provenance.schema.json"
STRUCTURE_PIPELINE_VERSION = "v0.3"
STRUCTURE_ANSWER_LETTERS = ("A", "B", "C", "D")

READING_PIPELINE_VERSION = "v0.2.12"

WE_PIPELINE_VERSION = "v2.1.3"
WE_ANSWER_LETTERS = ("A", "B", "C", "D")
WE_VALIDATOR_SCRIPT = (
    REPO_ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts" / "validate_output.py"
)
# Mirrors scripts/run_live_e2e.py's EVIDENCE_ARTIFACTS: the exact immutable
# evidence set protected by that harness's artifact manifest. Production
# Assembly independently re-verifies this set; it never reruns the harness.
WE_EVIDENCE_ARTIFACTS = (
    "runtime/formal/generator_outputs.json",
    "runtime/formal/reviewer_outputs.json",
    "runtime/formal/solver_outputs.json",
    "runtime/provenance/runtime_provenance.json",
    "runtime/outcomes.json",
    "runtime/test_result.json",
    "runtime/freeze/freeze_manifest.json",
)
WE_ARTIFACT_MANIFEST_VERSION = 1
WE_ARTIFACT_MANIFEST_RELATIVE_PATH = "runtime/artifact_manifest_v1.json"
# The exact JSON representation of orchestrator.scripts.orchestrator.State.ACCEPTED.
# That module is not imported here: several frozen test modules insert
# orchestrator/scripts onto sys.path and import a top-level "orchestrator"
# module directly (see tests/test_orchestrator_hardening.py), which makes a
# later "orchestrator.scripts.orchestrator" submodule import order-dependent
# and unsafe under full-suite discovery. The literal below is that same
# frozen State.ACCEPTED value, not an invented vocabulary.
WE_ACCEPTED_OUTCOME_STATE = "ACCEPTED"


def _load_json_file(path: Path, label: str) -> Any:
    try:
        return read_json(path)
    except JsonPersistenceError as exc:
        raise ProductionSourceError(f"{label} could not be read: {exc}") from exc


# ---------------------------------------------------------------------------
# Structure v0.3
# ---------------------------------------------------------------------------


def load_structure_source(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    result_path = run_dir / "result.json"
    generator_path = run_dir / "generator.json"
    provenance_path = run_dir / "provenance.json"
    for path in (result_path, generator_path, provenance_path):
        if not path.is_file():
            raise ProductionSourceError(f"Structure source is missing required file: {path}")

    result = _load_json_file(result_path, "Structure result.json")
    generator = _load_json_file(generator_path, "Structure generator.json")
    provenance = _load_json_file(provenance_path, "Structure provenance.json")

    result_errors = schema_errors(result, load_schema(STRUCTURE_RESULT_SCHEMA))
    if result_errors:
        raise ProductionSourceError(
            "Structure result.json failed schema validation: " + "; ".join(result_errors)
        )
    provenance_errors = schema_errors(provenance, load_schema(STRUCTURE_PROVENANCE_SCHEMA))
    if provenance_errors:
        raise ProductionSourceError(
            "Structure provenance.json failed schema validation: " + "; ".join(provenance_errors)
        )

    if result.get("schema_version") != "structure-result-v0.3":
        raise ProductionSourceError("Structure result.schema_version must be structure-result-v0.3")
    if result.get("version") != "v0.3":
        raise ProductionSourceError("Structure result.version must be v0.3")
    if result.get("decision") != "ACCEPT":
        raise ProductionSourceError(f"Structure source is not ACCEPT: {result.get('decision')!r}")
    if result.get("question_count") != 15:
        raise ProductionSourceError("Structure result.question_count must be 15")
    checks = result.get("checks")
    if not isinstance(checks, dict) or checks.get("all_15_items_pass") is not True:
        raise ProductionSourceError("Structure result.checks.all_15_items_pass must be true")
    item_results = result.get("item_results")
    if not isinstance(item_results, list) or len(item_results) != 15:
        raise ProductionSourceError("Structure result.item_results must contain exactly 15 records")
    if not all(isinstance(entry, dict) and entry.get("accepted") is True for entry in item_results):
        raise ProductionSourceError("every Structure item_result must have accepted == true")

    if not isinstance(generator, dict):
        raise ProductionSourceError("Structure generator.json must be a JSON object")
    items = generator.get("items")
    if not isinstance(items, list) or len(items) != 15:
        raise ProductionSourceError("Structure generator.json must contain exactly 15 final items")

    if provenance.get("schema_version") != "structure-provenance-v0.3":
        raise ProductionSourceError("Structure provenance.schema_version must be structure-provenance-v0.3")
    if provenance.get("version") != "v0.3":
        raise ProductionSourceError("Structure provenance.version must be v0.3")
    if result.get("run_id") != provenance.get("run_id"):
        raise ProductionSourceError("Structure result.run_id must equal provenance.run_id")
    if result.get("seed") != provenance.get("seed"):
        raise ProductionSourceError("Structure result.seed must equal provenance.seed")
    if result.get("artifact_hashes") != provenance.get("artifact_hashes"):
        raise ProductionSourceError("Structure result.artifact_hashes must equal provenance.artifact_hashes")

    expected_generator_hash = canonical_json_sha256(generator)
    recorded_generator_hash = (result.get("artifact_hashes") or {}).get("generator.json")
    if recorded_generator_hash != expected_generator_hash:
        raise ProductionSourceError(
            "Structure generator.json content does not match the accepted run's recorded hash"
        )

    seen_item_ids: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    run_id = result["run_id"]
    for item in items:
        if not isinstance(item, dict):
            raise ProductionSourceError("Structure generator.json items must be objects")
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ProductionSourceError("Structure generator item is missing item_id")
        if item_id in seen_item_ids:
            raise ProductionSourceError(f"duplicate Structure item_id within one source: {item_id!r}")
        seen_item_ids.add(item_id)
        normalized_items.append(_normalize_structure_item(item, run_id))

    source_descriptor = {
        "section": "Structure",
        "source_id": run_id,
        "pipeline_version": STRUCTURE_PIPELINE_VERSION,
        "content_sha256": expected_generator_hash,
    }
    return {"source": source_descriptor, "items": normalized_items}


def _normalize_structure_item(item: dict[str, Any], run_id: str) -> dict[str, Any]:
    options = item.get("options")
    rationales = item.get("distractor_rationales")
    if not isinstance(options, dict) or set(options) != set(STRUCTURE_ANSWER_LETTERS):
        raise ProductionSourceError("Structure item options must contain exactly A/B/C/D")
    if not isinstance(rationales, dict) or set(rationales) != set(STRUCTURE_ANSWER_LETTERS):
        raise ProductionSourceError("Structure item distractor_rationales must contain exactly A/B/C/D")
    return {
        "item_id": item["item_id"],
        "source_id": run_id,
        "section": "Structure",
        "difficulty": item.get("difficulty"),
        "vocabulary_domain": item.get("vocabulary_domain"),
        "stem": item.get("stem"),
        "options": {letter: options[letter] for letter in STRUCTURE_ANSWER_LETTERS},
        "correct_answer": item.get("correct_answer"),
        "explanation": {
            "answer_explanation": item.get("answer_explanation"),
            "distractor_rationales": {letter: rationales[letter] for letter in STRUCTURE_ANSWER_LETTERS},
        },
        "taxonomy": {
            "primary_target": item.get("primary_target"),
            "subtype": item.get("subtype"),
            "secondary_features": list(item.get("secondary_features") or []),
        },
    }


# ---------------------------------------------------------------------------
# Reading v0.2.12
# ---------------------------------------------------------------------------


def load_reading_source(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    result_path = run_dir / "result.json"
    generator_path = run_dir / "generator.json"
    provenance_path = run_dir / "provenance" / "provenance.json"
    for path in (result_path, generator_path, provenance_path):
        if not path.is_file():
            raise ProductionSourceError(f"Reading source is missing required file: {path}")

    result = _load_json_file(result_path, "Reading result.json")
    generator = _load_json_file(generator_path, "Reading generator.json")
    provenance = _load_json_file(provenance_path, "Reading provenance.json")

    result_errors = reading_contracts.validate_result_contract(result)
    if result_errors:
        raise ProductionSourceError(
            "Reading result.json failed contract validation: " + "; ".join(result_errors)
        )
    if not isinstance(result, dict):
        raise ProductionSourceError("Reading result.json must be a JSON object")

    if result.get("schema_version") != "reading-result-v0.2":
        raise ProductionSourceError("Reading result.schema_version must be reading-result-v0.2")
    if result.get("section") != "READING_COMPREHENSION":
        raise ProductionSourceError("Reading result.section must be READING_COMPREHENSION")
    if result.get("decision") != "ACCEPT":
        raise ProductionSourceError(f"Reading source is not ACCEPT: {result.get('decision')!r}")

    result_generator = result.get("generator")
    if not isinstance(result_generator, dict):
        raise ProductionSourceError("Reading result.generator must be a non-null object")
    if result_generator != generator:
        raise ProductionSourceError("Reading generator.json does not equal result.generator")

    generator_schema_path = reading_contracts.SCHEMA_PATHS_V02["generator"]
    generator_errors = schema_errors(generator, load_schema(generator_schema_path))
    if generator_errors:
        raise ProductionSourceError(
            "Reading generator.json failed schema validation: " + "; ".join(generator_errors)
        )

    if not isinstance(provenance, dict):
        raise ProductionSourceError("Reading provenance.json must be a JSON object")
    if provenance.get("run_id") != result.get("run_id"):
        raise ProductionSourceError("Reading provenance.run_id must equal result.run_id")
    if provenance.get("reading_version") != READING_PIPELINE_VERSION:
        raise ProductionSourceError(
            f"Reading provenance.reading_version must be {READING_PIPELINE_VERSION!r}"
        )
    canonical_artifact = provenance.get("canonical_generator_artifact")
    if canonical_artifact is not None and canonical_artifact != "generator.json":
        raise ProductionSourceError(
            "Reading provenance.canonical_generator_artifact must identify generator.json"
        )

    infrastructure = result.get("infrastructure")
    if not isinstance(infrastructure, dict) or infrastructure.get("synthetic_fallback") is not False:
        raise ProductionSourceError("Reading result.infrastructure.synthetic_fallback must be false")

    run_id = result["run_id"]
    passage_id = generator.get("passage_id")
    if not isinstance(passage_id, str) or not passage_id:
        raise ProductionSourceError("Reading generator.json is missing passage_id")

    questions = generator.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ProductionSourceError("Reading generator.json must contain at least one question")

    seen_question_ids: set[str] = set()
    normalized_questions: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            raise ProductionSourceError("Reading questions must be objects")
        item_id = question.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ProductionSourceError("Reading question is missing item_id")
        if item_id in seen_question_ids:
            raise ProductionSourceError(f"duplicate Reading question item_id within one source: {item_id!r}")
        seen_question_ids.add(item_id)
        normalized_questions.append(_normalize_reading_question(question))

    content_hash = canonical_json_sha256(generator)
    source_descriptor = {
        "section": "Reading",
        "source_id": run_id,
        "pipeline_version": READING_PIPELINE_VERSION,
        "content_sha256": content_hash,
    }
    passage = {
        "passage_id": passage_id,
        "source_id": run_id,
        "section": "Reading",
        "title": generator.get("title"),
        "passage": generator.get("passage"),
        "questions": normalized_questions,
    }
    return {"source": source_descriptor, "passage": passage}


def _normalize_reading_question(question: dict[str, Any]) -> dict[str, Any]:
    choices = question.get("choices")
    if not isinstance(choices, dict) or set(choices) != {"A", "B", "C", "D"}:
        raise ProductionSourceError("Reading question choices must contain exactly A/B/C/D")
    evidence = question.get("evidence")
    if not isinstance(evidence, dict):
        raise ProductionSourceError("Reading question is missing evidence")
    distractor_metadata = question.get("distractor_metadata")
    if not isinstance(distractor_metadata, dict) or set(distractor_metadata) != {"A", "B", "C", "D"}:
        raise ProductionSourceError("Reading question distractor_metadata must contain exactly A/B/C/D")
    choice_rationales: dict[str, Any] = {}
    for letter in ("A", "B", "C", "D"):
        entry = distractor_metadata[letter]
        if not isinstance(entry, dict):
            raise ProductionSourceError("Reading question distractor_metadata entries must be objects")
        choice_rationales[letter] = entry.get("rationale")

    normalized: dict[str, Any] = {
        "item_id": question["item_id"],
        "question_type": question.get("question_type"),
        "subtype": question.get("subtype"),
        "stem": question.get("stem"),
        "choices": {letter: choices[letter] for letter in ("A", "B", "C", "D")},
        "correct_answer": question.get("correct_answer"),
        "explanation": {
            "evidence_paragraph": evidence.get("paragraph"),
            "evidence_anchor": evidence.get("anchor"),
            "answer_rationale": evidence.get("rationale"),
            "choice_rationales": choice_rationales,
        },
    }
    if "target_text" in question:
        normalized["target_text"] = question["target_text"]
    if "target_line" in question:
        normalized["target_line"] = question["target_line"]
    return normalized


# ---------------------------------------------------------------------------
# Written Expression v2.1.3
# ---------------------------------------------------------------------------


def _resolve_within(run_dir: Path, relative: str) -> Path:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ProductionSourceError(f"WE artifact manifest contains an unsafe path: {relative!r}")
    base = run_dir.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ProductionSourceError(f"WE artifact manifest path escapes the run directory: {relative!r}") from exc
    return candidate


def _verify_we_immutable_evidence(run_dir: Path) -> None:
    manifest_path = run_dir / WE_ARTIFACT_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        raise ProductionSourceError(f"WE run is missing the immutable evidence manifest: {manifest_path}")
    document = _load_json_file(manifest_path, "WE artifact manifest")
    if not isinstance(document, dict):
        raise ProductionSourceError("WE artifact manifest must be a JSON object")
    if document.get("artifact_manifest_version") != WE_ARTIFACT_MANIFEST_VERSION:
        raise ProductionSourceError("WE artifact manifest has an unsupported artifact_manifest_version")

    recorded_hash = document.get("artifact_manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "artifact_manifest_sha256"}
    if not isinstance(recorded_hash, str) or recorded_hash != canonical_json_sha256(unsigned):
        raise ProductionSourceError("WE artifact manifest self-hash does not match its contents")

    files = document.get("files")
    if not isinstance(files, dict) or set(files) != set(WE_EVIDENCE_ARTIFACTS):
        raise ProductionSourceError("WE artifact manifest does not list exactly the required evidence set")

    for relative in WE_EVIDENCE_ARTIFACTS:
        info = files.get(relative)
        expected = info.get("sha256") if isinstance(info, dict) else None
        candidate = _resolve_within(run_dir, relative)
        if not isinstance(expected, str) or not candidate.is_file() or sha256_file(candidate) != expected:
            raise ProductionSourceError(f"WE immutable evidence artifact is missing or tampered: {relative}")


def _validate_we_consensus(run_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    outcomes_document = _load_json_file(run_dir / "runtime" / "outcomes.json", "WE outcomes.json")
    if not isinstance(outcomes_document, dict):
        raise ProductionSourceError("WE outcomes.json must be a JSON object")
    batch_id = outcomes_document.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ProductionSourceError("WE outcomes.batch_id must be a non-empty string")
    outcomes = outcomes_document.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        raise ProductionSourceError("WE outcomes.outcomes must be a non-empty array")

    seen_ids: set[str] = set()
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise ProductionSourceError("WE outcome entries must be objects")
        item_id = outcome.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ProductionSourceError("WE outcome entry is missing item_id")
        if item_id in seen_ids:
            raise ProductionSourceError(f"duplicate WE outcome item_id: {item_id!r}")
        seen_ids.add(item_id)
        if outcome.get("state") != WE_ACCEPTED_OUTCOME_STATE:
            raise ProductionSourceError(
                f"WE outcome for {item_id!r} is not {WE_ACCEPTED_OUTCOME_STATE!r}: {outcome.get('state')!r}"
            )

    test_result = _load_json_file(run_dir / "runtime" / "test_result.json", "WE test_result.json")
    if not isinstance(test_result, dict) or test_result.get("passed") is not True:
        raise ProductionSourceError("WE test_result.passed must be true")

    return batch_id, outcomes


def _run_we_production_validator(generator_outputs_path: Path, grammar_evidence_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(WE_VALIDATOR_SCRIPT), str(generator_outputs_path), str(grammar_evidence_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProductionSourceError(
            "WE production validator (v2.1.3 grammar-evidence mode) rejected the source"
        )


def load_written_expression_source(run_dir: Path, grammar_evidence_path: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    grammar_evidence_path = Path(grammar_evidence_path)
    if not grammar_evidence_path.is_file():
        raise ProductionSourceError(f"WE grammar evidence file is missing: {grammar_evidence_path}")

    _verify_we_immutable_evidence(run_dir)
    batch_id, outcomes = _validate_we_consensus(run_dir)

    generator_outputs_path = run_dir / "runtime" / "formal" / "generator_outputs.json"
    generator_document = _load_json_file(generator_outputs_path, "WE generator_outputs.json")
    if not isinstance(generator_document, dict) or not isinstance(generator_document.get("items"), list):
        raise ProductionSourceError("WE generator_outputs.json must be an object with an items array")
    items = generator_document["items"]

    generator_item_ids = {
        item.get("item_id") for item in items if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }
    accepted_item_ids = {outcome["item_id"] for outcome in outcomes}
    if generator_item_ids != accepted_item_ids:
        raise ProductionSourceError(
            "every WE Generator item must have exactly one matching ACCEPTED outcome and vice versa"
        )

    _run_we_production_validator(generator_outputs_path, grammar_evidence_path)

    seen_item_ids: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ProductionSourceError("WE generator_outputs.json items must be objects")
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ProductionSourceError("WE generator item is missing item_id")
        if item_id in seen_item_ids:
            raise ProductionSourceError(f"duplicate WE item_id within one source: {item_id!r}")
        seen_item_ids.add(item_id)
        normalized_items.append(_normalize_we_item(item, batch_id))

    content_hash = canonical_json_sha256(generator_document)
    source_descriptor = {
        "section": "Written Expression",
        "source_id": batch_id,
        "pipeline_version": WE_PIPELINE_VERSION,
        "content_sha256": content_hash,
    }
    return {"source": source_descriptor, "items": normalized_items}


def _normalize_we_item(item: dict[str, Any], batch_id: str) -> dict[str, Any]:
    marked_parts = item.get("marked_parts")
    if not isinstance(marked_parts, dict) or set(marked_parts) != set(WE_ANSWER_LETTERS):
        raise ProductionSourceError("WE item marked_parts must contain exactly A/B/C/D")
    grammar_metadata = item.get("grammar_metadata")
    if not isinstance(grammar_metadata, dict):
        raise ProductionSourceError("WE item is missing grammar_metadata")
    return {
        "item_id": item["item_id"],
        "source_id": batch_id,
        "section": "Written Expression",
        "difficulty": item.get("difficulty"),
        "vocabulary_domain": item.get("vocabulary_domain"),
        "sentence": item.get("sentence"),
        "marked_parts": {letter: marked_parts[letter] for letter in WE_ANSWER_LETTERS},
        "correct_answer": item.get("correct_answer"),
        "explanation": {
            "error_explanation": item.get("error_explanation"),
            "minimal_correction": item.get("minimal_correction"),
        },
        "taxonomy": {
            "primary_target": item.get("primary_target"),
            "subtype": item.get("subtype"),
            "secondary_features": list(item.get("secondary_features") or []),
            "tested_error_type": item.get("tested_error_type"),
            "error_scope": grammar_metadata.get("error_scope"),
        },
    }
