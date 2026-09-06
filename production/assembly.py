"""Deterministic assembly of the cross-section production problem bank.

This module owns only: validating source-list uniqueness, invoking the
section adapters, deterministic ordering, global duplicate-identity checks,
counts, final bank construction, schema validation, and the atomic write. It
contains no section-specific grammar/content semantics -- those live in
``production.adapters``.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from shared.json_io import atomic_write_json
from shared.schema_validation import load_schema, schema_errors

from . import adapters
from .adapters import ProductionSourceError

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "problem_bank.schema.json"
SCHEMA_VERSION = "itp-production-bank-v1"


class ProductionAssemblyError(RuntimeError):
    """Assembly failed; no problem bank was written."""


def _check_unique_paths(label: str, paths: Sequence[Path]) -> None:
    resolved = [Path(path).resolve() for path in paths]
    counts = Counter(resolved)
    duplicates = sorted({str(path) for path, count in counts.items() if count > 1})
    if duplicates:
        raise ProductionAssemblyError(f"duplicate {label} source path(s) supplied: {duplicates}")


def _check_duplicate_source_ids(section: str, loaded: list[dict[str, Any]]) -> None:
    counts = Counter(entry["source"]["source_id"] for entry in loaded)
    duplicates = sorted(source_id for source_id, count in counts.items() if count > 1)
    if duplicates:
        raise ProductionAssemblyError(f"duplicate {section} source_id: {duplicates}")


def assemble_problem_bank(
    *,
    structure_runs: Sequence[Path] = (),
    written_expression_sources: Sequence[tuple[Path, Path]] = (),
    reading_runs: Sequence[Path] = (),
) -> dict[str, Any]:
    """Validate, normalize, and combine explicitly supplied sources into one bank.

    Fails closed: any ineligible/invalid source raises before any content is
    combined, and no partial bank is ever constructed.
    """

    structure_runs = list(structure_runs)
    written_expression_sources = list(written_expression_sources)
    reading_runs = list(reading_runs)

    if not structure_runs and not written_expression_sources and not reading_runs:
        raise ProductionAssemblyError("at least one explicit source is required")

    _check_unique_paths("Structure", structure_runs)
    _check_unique_paths("Written Expression run", [run for run, _evidence in written_expression_sources])
    _check_unique_paths("Reading", reading_runs)

    try:
        structure_loaded = [adapters.load_structure_source(path) for path in structure_runs]
        we_loaded = [
            adapters.load_written_expression_source(run, evidence)
            for run, evidence in written_expression_sources
        ]
        reading_loaded = [adapters.load_reading_source(path) for path in reading_runs]
    except ProductionSourceError as exc:
        raise ProductionAssemblyError(str(exc)) from exc

    _check_duplicate_source_ids("Structure", structure_loaded)
    _check_duplicate_source_ids("Written Expression", we_loaded)
    _check_duplicate_source_ids("Reading", reading_loaded)

    structure_loaded.sort(key=lambda entry: entry["source"]["source_id"])
    we_loaded.sort(key=lambda entry: entry["source"]["source_id"])
    reading_loaded.sort(key=lambda entry: entry["source"]["source_id"])

    structure_items = [item for entry in structure_loaded for item in entry["items"]]
    we_items = [item for entry in we_loaded for item in entry["items"]]
    reading_passages = [entry["passage"] for entry in reading_loaded]

    _check_duplicate_field("Structure item_id", (item["item_id"] for item in structure_items))
    _check_duplicate_field("Written Expression item_id", (item["item_id"] for item in we_items))
    _check_duplicate_field("Reading passage_id", (passage["passage_id"] for passage in reading_passages))
    _check_duplicate_field(
        "Reading question item_id",
        (question["item_id"] for passage in reading_passages for question in passage["questions"]),
    )

    all_item_ids = (
        [item["item_id"] for item in structure_items]
        + [item["item_id"] for item in we_items]
        + [question["item_id"] for passage in reading_passages for question in passage["questions"]]
    )
    _check_duplicate_field("item_id across the entire bank", all_item_ids)

    reading_question_count = sum(len(passage["questions"]) for passage in reading_passages)
    counts = {
        "structure_items": len(structure_items),
        "written_expression_items": len(we_items),
        "reading_passages": len(reading_passages),
        "reading_questions": reading_question_count,
        "total_questions": len(structure_items) + len(we_items) + reading_question_count,
    }
    source_count = len(structure_runs) + len(written_expression_sources) + len(reading_runs)

    sources = (
        [entry["source"] for entry in structure_loaded]
        + [entry["source"] for entry in we_loaded]
        + [entry["source"] for entry in reading_loaded]
    )

    bank: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_count": source_count,
        "counts": counts,
        "sources": sources,
        "sections": {
            "structure": {"items": structure_items},
            "written_expression": {"items": we_items},
            "reading": {"passages": reading_passages},
        },
    }

    errors = schema_errors(bank, load_schema(SCHEMA_PATH))
    if errors:
        raise ProductionAssemblyError(
            "assembled problem bank failed schema validation: " + "; ".join(errors)
        )
    return bank


def _check_duplicate_field(label: str, values: Any) -> None:
    counts = Counter(values)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    if duplicates:
        raise ProductionAssemblyError(f"duplicate {label}: {duplicates}")


def write_problem_bank(
    output_path: Path,
    *,
    structure_runs: Sequence[Path] = (),
    written_expression_sources: Sequence[tuple[Path, Path]] = (),
    reading_runs: Sequence[Path] = (),
) -> dict[str, Any]:
    """Assemble a validated bank and atomically write it. All-or-nothing."""

    bank = assemble_problem_bank(
        structure_runs=structure_runs,
        written_expression_sources=written_expression_sources,
        reading_runs=reading_runs,
    )
    atomic_write_json(Path(output_path), bank)
    return bank
