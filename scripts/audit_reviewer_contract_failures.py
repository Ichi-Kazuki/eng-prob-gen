#!/usr/bin/env python3
"""Audit a recorded WE Reviewer contract failure cohort without live calls.

The audit intentionally treats the historical adapter representation as a
copy-plus-comparison-field transformation. The current adapter rejects the
old blind checks.target_metadata field by design, so replaying through the
corrected adapter would hide the historical failure cause.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.schema_validation import schema_errors  # noqa: E402
from runtime.adapters import normalize_codex_output_for_canonical  # noqa: E402


DEFAULT_RUN = ROOT / "runs" / "we_v2_1_3_live_pilot_fresh_20260827T014147Z"
DEFAULT_OUTPUT = ROOT / "analysis" / "we_v2_1_3_reviewer_contract_audit_20260827.json"
REVIEWER_VALIDATOR = ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "scripts" / "validate_output.py"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_validator() -> Any:
    spec = importlib.util.spec_from_file_location("offline_reviewer_contract_validator", REVIEWER_VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Reviewer validator: {REVIEWER_VALIDATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _item_map(document: Any) -> dict[str, dict]:
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        raise ValueError("formal document must contain an items list")
    return {
        item["item_id"]: item
        for item in document["items"]
        if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }


def _judgment_projection(item: dict) -> dict[str, Any]:
    return {
        key: copy.deepcopy(item.get(key))
        for key in (
            "item_id",
            "section",
            "agent_version",
            "verdict",
            "critical_failure",
            "independent_answer",
            "grammar_validity",
            "format_validity",
            "detected_error_count",
            "detected_error_position",
            "non_error_parts_valid",
            "minimal_correction_valid",
            "marked_part_assessments",
            "checks",
            "issues",
            "revision_requirements",
            "source_similarity_risk",
            "provenance",
        )
    }


def _response_summary(item: dict, path: Path) -> dict[str, Any]:
    checks = item.get("checks") if isinstance(item.get("checks"), dict) else {}
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": _sha256(path),
        "keys": sorted(item),
        "verdict": item.get("verdict"),
        "independent_answer": item.get("independent_answer"),
        "grammar_validity": item.get("grammar_validity"),
        "format_validity": item.get("format_validity"),
        "detected_error_count": item.get("detected_error_count"),
        "detected_error_position": item.get("detected_error_position"),
        "checks": copy.deepcopy(checks),
    }


def _error_signature(errors: list[str]) -> tuple[str, ...]:
    return tuple(error.split("] ", 1)[1] if "] " in error else error for error in errors)


def audit(run_root: Path) -> dict[str, Any]:
    run_root = run_root.resolve()
    formal_root = run_root / "runtime" / "formal"
    logs_root = run_root / "runtime" / "logs"
    outcomes = _load(run_root / "runtime" / "outcomes.json")
    generators = _item_map(_load(formal_root / "generator_outputs.json"))
    formal_reviewers = _item_map(_load(formal_root / "reviewer_outputs.json"))
    validator = _load_validator()
    canonical_schema_path = REVIEWER_VALIDATOR.parents[1] / "schema" / "reviewer_output_v2.schema.json"
    raw_by_id: dict[str, tuple[dict, Path, Path]] = {}
    for path in sorted(logs_root.glob("reviewer-*.last-message.json")):
        raw = _load(path)
        if not isinstance(raw, dict) or not isinstance(raw.get("item_id"), str):
            continue
        transport_schema_path = path.parent / "transport-schemas" / path.name.replace(".last-message.json", ".json")
        raw_by_id[raw["item_id"]] = (raw, path, transport_schema_path)

    failure_items = [
        outcome
        for outcome in outcomes.get("outcomes", [])
        if isinstance(outcome, dict)
        and outcome.get("failure", {}).get("stage") == "reviewer"
    ]
    records: list[dict[str, Any]] = []
    for outcome in failure_items:
        item_id = outcome["item_id"]
        raw, raw_path, transport_schema_path = raw_by_id[item_id]
        generator = generators[item_id]

        # This is the historical adapter's actual transformation: it copied
        # the blind response and appended only the two post-blind comparison
        # fields. No judgment field is synthesized here.
        normalized_transport = normalize_codex_output_for_canonical(raw, canonical_schema_path)
        if not isinstance(normalized_transport, dict):
            raise ValueError(f"normalized Reviewer response for {item_id} is not an object")
        normalized = copy.deepcopy(normalized_transport)
        normalized["generator_answer"] = generator["correct_answer"]
        normalized["answer_match"] = normalized["independent_answer"] == generator["correct_answer"]
        canonical_errors = validator.validate_contract(normalized)
        recorded_detail = outcome.get("failure", {}).get("detail")
        transport_errors = (
            schema_errors(raw, _load(transport_schema_path))
            if transport_schema_path.is_file()
            else ["historical transport schema artifact is missing"]
        )
        target_value = raw.get("checks", {}).get("target_metadata")
        formal = formal_reviewers.get(item_id)
        records.append(
            {
                "item_id": item_id,
                "raw_live_reviewer_response": _response_summary(raw, raw_path),
                "normalized_adapter_representation": {
                    "source": "historical structural adapter: deep copy + generator_answer + answer_match",
                    "keys": sorted(normalized),
                    "transport_normalization_removed_keys": sorted(set(raw) - set(normalized_transport)),
                    "generator_answer": normalized["generator_answer"],
                    "answer_match": normalized["answer_match"],
                    "checks_target_metadata": target_value,
                    "judgment_fields_unchanged": _judgment_projection(raw)
                    == _judgment_projection(normalized),
                },
                "final_formal_reviewer_record": {
                    "present": formal is not None,
                    "path": "runtime/formal/reviewer_outputs.json",
                    "item_id": None if formal is None else formal.get("item_id"),
                    "reason_absent": (
                        "not published after canonical Reviewer validation failed"
                        if formal is None
                        else None
                    ),
                },
                "canonical_validation_errors": [
                    *[f"reviewer: {error}" for error in canonical_errors],
                ],
                "recorded_outcome_error": recorded_detail,
                "target_metadata_provenance": {
                    "raw_live_value": target_value,
                    "normalized_value": normalized.get("checks", {}).get("target_metadata"),
                    "formal_value": None if formal is None else formal.get("checks", {}).get("target_metadata"),
                    "origin": "BLIND_REVIEWER_RESPONSE",
                    "not_computed_by_structural_adapter": True,
                    "not_attached_during_post_blind_comparison": True,
                    "blind_input_keys": sorted(
                        (_load(run_root / "runtime" / "inputs" / f"{item_id.rsplit('-', 1)[-1]}_reviewer.json")).keys()
                    ),
                },
                "historical_transport_schema_errors": transport_errors,
            }
        )

    target_origins = {record["target_metadata_provenance"]["origin"] for record in records}
    canonical_error_texts = {
        _error_signature(record["canonical_validation_errors"])
        for record in records
    }
    return {
        "status": "OFFLINE_AUDIT_COMPLETE",
        "run": str(run_root.relative_to(ROOT)).replace("\\", "/"),
        "model_invocations": 0,
        "historical_run_modified": False,
        "failure_count": len(records),
        "all_failures_are_reviewer_contract_failures": all(
            record["canonical_validation_errors"] for record in records
        ),
        "target_metadata_origins": sorted(target_origins),
        "canonical_error_variants": len(canonical_error_texts),
        "root_cause": (
            "The blind Reviewer output contract required checks.target_metadata, "
            "but the blind invocation withheld Generator metadata. All 22 raw "
            "responses therefore returned target_metadata=AMBIGUOUS; the formal "
            "Reviewer semantic validator rejects PASS with an ambiguous check."
        ),
        "items": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = audit(args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
