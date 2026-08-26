#!/usr/bin/env python3
"""Validate WE Generator v2 output at the pipeline boundary.

The JSON Schema is the canonical structural contract. Only after an item
passes that contract do we run taxonomy, semantic, and deterministic format
checks supplied by ``validate_format.py``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)
from validate_format import (  # noqa: E402
    CONFIG_PATH,
    GRAMMAR_SPEC_PATH,
    TAXONOMY_PATH,
    load_items,
    load_json,
    validate_item,
)
from mutation_safety import (  # noqa: E402
    evidence_provenance_errors,
    finalization_integrity_errors,
    validate_item as validate_mutation_item,
)


OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "written_expression_item_v2.schema.json"
EVIDENCE_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "grammar_evidence.schema.json"
_SCHEMA: dict[str, Any] | None = None
MUTATION_SAFETY_AGENT_VERSION = "Written Expression Generator v2.1"
LEGACY_AGENT_VERSION = "Written Expression Generator v2.0"
LEGACY_VALIDATION_FLAG = "--legacy-v20"


def mutation_safety_required(
    item: dict[str, Any], *, validation_mode: str = "current"
) -> bool:
    """Require mutation safety unless an explicit legacy profile is selected.

    ``agent_version`` is producer-supplied metadata.  It is useful for
    diagnostics, but it is not an authenticity boundary and must not decide
    which checks the current validator performs.  The only weaker path is the
    explicitly requested legacy v2.0 profile.
    """

    if validation_mode not in {"current", "legacy_v20"}:
        raise ValueError(f"unsupported validation mode: {validation_mode!r}")
    return validation_mode == "current"


def _validation_mode_errors(item: dict[str, Any], validation_mode: str) -> list[str]:
    """Return version/profile errors without delegating policy to the item."""
    agent_version = item.get("agent_version")
    provenance = item.get("provenance")
    errors: list[str] = []
    if not isinstance(provenance, Mapping):
        return ["provenance must be an object"]
    if provenance.get("agent_version") != agent_version:
        errors.append(
            "provenance.agent_version must exactly match top-level agent_version"
        )

    if validation_mode == "current":
        if agent_version != MUTATION_SAFETY_AGENT_VERSION:
            errors.append(
                "current validation requires "
                f"agent_version {MUTATION_SAFETY_AGENT_VERSION!r}; "
                f"got {agent_version!r}. Use {LEGACY_VALIDATION_FLAG} only for v2.0 artifacts."
            )
    elif validation_mode == "legacy_v20":
        if agent_version != LEGACY_AGENT_VERSION:
            errors.append(
                f"{LEGACY_VALIDATION_FLAG} accepts only agent_version {LEGACY_AGENT_VERSION!r}"
            )
    else:
        raise ValueError(f"unsupported validation mode: {validation_mode!r}")
    return errors


def output_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = load_schema(OUTPUT_SCHEMA_PATH)
    return _SCHEMA


def grammar_evidence_content_hash(item: Mapping[str, Any]) -> str:
    """Return the hash of the item content reviewed by the grammar runtime.

    Dynamic QA/provenance fields are intentionally excluded.  The projection
    includes the emitted sentence and marked spans as well as both grammar
    forms and their mutation metadata, so evidence cannot be replayed after a
    reviewed mutation or its declared defect has changed.
    """

    qa = item.get("qa_metadata")
    qa = qa if isinstance(qa, Mapping) else {}
    reviewed_content = {
        "item_id": item.get("item_id"),
        "sentence": item.get("sentence"),
        "marked_parts": item.get("marked_parts"),
        "correct_answer": item.get("correct_answer"),
        "tested_error_type": item.get("tested_error_type"),
        "primary_target": item.get("primary_target"),
        "answer_explanation": item.get("answer_explanation", item.get("error_explanation")),
        "clean_form": qa.get("clean_form"),
        "error_form": qa.get("error_form"),
        "minimal_correction": qa.get("minimal_correction", item.get("minimal_correction")),
        "mutation_type": qa.get("mutation_type"),
    }
    canonical = json.dumps(
        reviewed_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def load_external_evidence(path: Path) -> dict[str, Mapping[str, Any]]:
    """Load per-item grammar evidence without expanding the item schema.

    The sidecar may be ``{"items": [{"item_id": "...",
    "content_hash": "sha256:...", "evidence": {...}}, ...]}`` or an
    item-keyed object whose values contain the same ``content_hash`` and
    evidence fields.  The hash is mandatory in either representation.
    Evidence is deliberately supplied out of band because it is produced by
    the independent grammar runtime rather than by the Generator item.
    """

    raw = load_json(path)
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        records = raw["items"]
    elif isinstance(raw, dict):
        records = []
        for item_id, value in raw.items():
            if not isinstance(value, dict):
                raise ValueError(
                    f"grammar evidence for {item_id} must include content_hash and evidence"
                )
            if "item_id" in value and value["item_id"] != item_id:
                raise ValueError(
                    f"grammar evidence key {item_id!r} conflicts with record item_id {value['item_id']!r}"
                )
            records.append({"item_id": item_id, **value})
    else:
        raise ValueError("grammar evidence must be an object or an object with an items array")

    evidence_by_item: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("item_id"), str):
            raise ValueError("each grammar evidence record requires a string item_id")
        hash_values = [
            record[field]
            for field in ("content_hash", "item_content_hash")
            if field in record
        ]
        if len(hash_values) > 1 and any(value != hash_values[0] for value in hash_values[1:]):
            raise ValueError(f"grammar evidence for {record['item_id']} has conflicting content hashes")
        content_hash = hash_values[0] if hash_values else None
        if not isinstance(content_hash, str) or not content_hash:
            raise ValueError(
                f"grammar evidence for {record['item_id']} requires a nonempty content_hash"
            )
        evidence_values = [
            record[field]
            for field in ("evidence", "external_evidence", "grammar_evidence", "invariants")
            if field in record
        ]
        if len(evidence_values) > 1 and any(value != evidence_values[0] for value in evidence_values[1:]):
            raise ValueError(f"grammar evidence for {record['item_id']} has conflicting evidence fields")
        evidence = evidence_values[0] if evidence_values else None
        if not isinstance(evidence, dict) or not all(
            isinstance(value, bool) for value in evidence.values()
        ):
            raise ValueError(f"grammar evidence for {record['item_id']} must be an object of booleans")
        if record["item_id"] in evidence_by_item:
            raise ValueError(f"duplicate grammar evidence item_id: {record['item_id']}")
        normalized = {
            "item_id": record["item_id"],
            "content_hash": content_hash,
            "evidence": evidence,
        }
        for field in (
            "evidence_producer",
            "evidence_producer_version",
            "invocation_id",
            "created_at",
            "evidence_method",
            "model_identifier",
        ):
            if field in record:
                normalized[field] = record[field]
        provenance_errors = evidence_provenance_errors(normalized)
        if provenance_errors:
            raise ValueError(
                f"grammar evidence for {record['item_id']} has invalid provenance: "
                + "; ".join(provenance_errors)
            )
        structural_errors = schema_errors(normalized, load_schema(EVIDENCE_SCHEMA_PATH))
        if structural_errors:
            raise ValueError(
                f"grammar evidence for {record['item_id']} failed schema validation: "
                + "; ".join(structural_errors)
            )
        evidence_by_item[record["item_id"]] = normalized
    return evidence_by_item


def validate_finalization_integrity(item: object) -> list[str]:
    """Validate only the serialized Generator finalization invariants."""

    if not isinstance(item, dict):
        return ["formal Generator record must be an object"]
    return finalization_integrity_errors(item)


def validate_contract(
    item: object,
    config: dict[str, Any],
    targets: set[str],
    error_types: set[str],
    external_evidence: Mapping[str, Any] | None = None,
    *,
    validation_mode: str = "current",
) -> dict[str, Any]:
    item_id = item.get("item_id", "?") if isinstance(item, dict) else "?"
    if not isinstance(item, dict):
        return {"item_id": item_id, "valid": False, "errors": ["$: item must be an object"], "diagnostics": {}}

    structural = schema_errors(item, output_schema())
    if structural:
        return {
            "item_id": item_id,
            "valid": False,
            "errors": [f"{OUTPUT_SCHEMA_PATH.name}: {error}" for error in structural],
            "diagnostics": {},
        }

    mode_errors = _validation_mode_errors(item, validation_mode)

    # This function owns semantic and deterministic checks only. Structural
    # required/type/enum/additional-property checks remain in the schema.
    result = validate_item(item, config, targets, error_types)
    result["errors"].extend(mode_errors)
    if validation_mode == "current":
        result["errors"].extend(
            f"finalization_integrity: {reason}"
            for reason in validate_finalization_integrity(item)
        )
    if mutation_safety_required(item, validation_mode=validation_mode):
        bound_evidence: Mapping[str, bool] | None = None
        if external_evidence is not None:
            candidate_evidence = external_evidence.get("evidence")
            supplied_hash = external_evidence.get("content_hash")
            expected_hash = grammar_evidence_content_hash(item)
            provenance_errors = evidence_provenance_errors(external_evidence)
            if "item_id" in external_evidence and external_evidence.get("item_id") != item_id:
                provenance_errors.append("item_id does not match the validated item")
            if provenance_errors:
                result["errors"].append(
                    "mutation_safety: external grammar evidence provenance is invalid: "
                    + "; ".join(provenance_errors)
                )
            result.setdefault("diagnostics", {})["grammar_evidence_provenance"] = {
                field: external_evidence.get(field)
                for field in (
                    "evidence_producer",
                    "evidence_producer_version",
                    "invocation_id",
                    "created_at",
                    "evidence_method",
                    "model_identifier",
                )
                if field in external_evidence
            }
            if (
                isinstance(candidate_evidence, Mapping)
                and all(isinstance(value, bool) for value in candidate_evidence.values())
                and supplied_hash == expected_hash
                and not provenance_errors
            ):
                bound_evidence = candidate_evidence
            else:
                result["errors"].append(
                    "mutation_safety: external grammar evidence is not bound to the exact item content"
                )
        mutation_result = validate_mutation_item(item, external_evidence=bound_evidence)
        if mutation_result.status != "PASS":
            result["errors"].extend(
                f"mutation_safety: {reason}" for reason in mutation_result.reasons
            )
        qa = item.get("qa_metadata")
        if isinstance(qa, dict) and qa.get("grammar_check_status") != "PASS":
            result["errors"].append(
                "mutation_safety: v2.1 items require grammar_check_status PASS; "
                "unreviewed or ambiguous grammar must be regenerated"
            )
        if mutation_result.grammar_evidence_status != "PASS":
            result["errors"].append(
                "mutation_safety: v2.1 items require attached grammar evidence for "
                "every strong one-error invariant; local metadata cannot substitute "
                f"for grammar_evidence_status PASS (got {mutation_result.grammar_evidence_status})"
            )
        result["valid"] = not result["errors"]
    return result


def main() -> int:
    args = sys.argv[1:]
    validation_mode = "current"
    if args and args[0] == LEGACY_VALIDATION_FLAG:
        validation_mode = "legacy_v20"
        args = args[1:]
    if len(args) not in {1, 2}:
        print(
            "Usage: python validate_output.py [--legacy-v20] "
            "<items.json> [grammar_evidence.json]"
        )
        return 2
    try:
        path = Path(args[0])
        config = load_json(CONFIG_PATH)
        grammar = load_json(GRAMMAR_SPEC_PATH)
        taxonomy = load_json(TAXONOMY_PATH)
        evidence_by_item = load_external_evidence(Path(args[1])) if len(args) == 2 else {}
        targets = {x["id"] for x in taxonomy["primary_targets"]}
        error_types = {
            x["id"]
            for x in grammar["tested_error_types"]
            if x["id"] not in {"fragment", "wrong_complementation"}
        }
        items = load_items(path)
        results = [
            validate_contract(
                item,
                config,
                targets,
                error_types,
                external_evidence=(
                    evidence_by_item.get(item.get("item_id"))
                    if isinstance(item, dict)
                    else None
                ),
                validation_mode=validation_mode,
            )
            for item in items
        ]
        input_item_ids = {
            item.get("item_id")
            for item in items
            if isinstance(item, dict) and isinstance(item.get("item_id"), str)
        }
        unknown_evidence_ids = sorted(set(evidence_by_item) - input_item_ids)
        if unknown_evidence_ids:
            raise ValueError(
                "grammar evidence contains records for unknown item_id(s): "
                + ", ".join(unknown_evidence_ids)
            )
    except ValueError as exc:
        print(f"CONTENT ERROR: {exc}")
        return 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationRuntimeError) as exc:
        print(f"SYSTEM ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # validator crash => explicit system failure
        print(f"SYSTEM ERROR: unexpected validator exception: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    failures = [result for result in results if not result["valid"]]
    print(f"Checked {len(results)} WE v2 item(s); {len(failures)} failed.")
    for result in failures:
        print(f"[{result['item_id']}]")
        for error in result["errors"]:
            print(f"  - {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
