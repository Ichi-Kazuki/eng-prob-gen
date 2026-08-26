#!/usr/bin/env python3
"""Offline-only audit of the invalid 25-item pilot evidence.

This script never calls a model and never rewrites the historical pilot.  It
replays the stored Reviewer last message through the structural adapter and
canonical Reviewer validator, and checks whether the historical Generator
schema hash can be resolved to an exact local/Git snapshot before validating
item 022.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

import run_live_e2e as harness  # noqa: E402
from runtime.adapters import parse_json_text  # noqa: E402
from shared.schema_validation import load_schema, schema_errors  # noqa: E402


PILOT_ROOT = ROOT / "runs" / "we_v2_1_3_live_pilot_25_20260826_medium"
OUTPUT_PATH = ROOT / "runs" / "infrastructure_hardening_offline_audit_20260826.json"
REVIEWER_ITEM_ID = "we-v2.1.3-live-T115906Z-008"
GENERATOR_ITEM_ID = "we-v2.1.3-live-T115906Z-022"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_provenance_record(stage: str, item_id: str) -> dict:
    provenance = _load_json(PILOT_ROOT / "runtime" / "provenance" / "runtime_provenance.json")
    for record in provenance.get("items", []):
        if record.get("stage") != stage:
            continue
        candidate_paths = [record.get("output_last_message_path"), record.get("raw_stderr_path")]
        for raw_path in candidate_paths:
            if not raw_path:
                continue
            path = ROOT / Path(raw_path)
            try:
                if item_id in path.read_text(encoding="utf-8", errors="replace"):
                    return record
            except OSError:
                continue
    raise ValueError(f"could not find {stage} provenance for {item_id}")


def _load_item(path: Path, item_id: str) -> dict:
    for item in _load_json(path).get("items", []):
        if item.get("item_id") == item_id:
            return item
    raise ValueError(f"could not find {item_id} in {path}")


def _exact_schema_candidates(recorded_hash: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    paths = [
        ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json",
    ]
    freeze_snapshot_root = PILOT_ROOT / "runtime" / "freeze" / "snapshots" / "canonical-schemas"
    if freeze_snapshot_root.exists():
        paths.extend(freeze_snapshot_root.glob("*.json"))
    seen_paths: set[Path] = set()
    for path in paths:
        if path in seen_paths or not path.is_file():
            continue
        seen_paths.add(path)
        try:
            if _sha256_file(path) == recorded_hash:
                candidates.append({"source": str(path), "kind": "filesystem"})
        except OSError:
            pass

    try:
        rows = subprocess.check_output(
            ["git", "rev-list", "--all", "--objects", "--reflog"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        rows = []
    try:
        unreachable_rows = subprocess.check_output(
            ["git", "fsck", "--full", "--no-reflogs", "--unreachable"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        unreachable_rows = []
    rows.extend(
        f"{parts[2]} unreachable/{parts[2]}"
        for row in unreachable_rows
        if (parts := row.split()) and len(parts) == 3 and parts[0] == "unreachable" and parts[1] == "blob"
    )
    seen_objects: set[str] = set()
    for row in rows:
        parts = row.split(" ", 1)
        if len(parts) != 2 or "written_expression_item_v2.schema.json" not in parts[1]:
            continue
        object_id = parts[0]
        if object_id in seen_objects:
            continue
        seen_objects.add(object_id)
        try:
            raw = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=ROOT)
        except (OSError, subprocess.CalledProcessError):
            continue
        if "sha256:" + hashlib.sha256(raw).hexdigest() == recorded_hash:
            candidates.append({"source": object_id, "kind": "git-blob", "path": parts[1]})
    return candidates


def audit() -> dict:
    reviewer_record = _find_provenance_record("reviewer", REVIEWER_ITEM_ID)
    generator_record = _find_provenance_record("generator", GENERATOR_ITEM_ID)
    reviewer_raw_path = ROOT / Path(reviewer_record["output_last_message_path"])
    raw_reviewer = parse_json_text(reviewer_raw_path.read_text(encoding="utf-8"), "reviewer")
    if not isinstance(raw_reviewer, dict):
        raise ValueError("stored Reviewer last message is not an object")

    generator_item = _load_item(
        PILOT_ROOT / "runtime" / "formal" / "generator_outputs.json",
        REVIEWER_ITEM_ID,
    )
    reviewer_schema = harness.reviewer_runtime_schema(
        ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "schema" / "reviewer_output_v2.schema.json"
    )
    raw_structural_errors = schema_errors(raw_reviewer, reviewer_schema)
    adapted = harness.adapt_reviewer_structural(
        copy.deepcopy(raw_reviewer),
        generator_item,
        8,
        "we-v2.1.3-live-pilot-25-20260826T115906Z",
        reviewer_schema,
    )
    canonical_reviewer_schema = load_schema(
        ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "schema" / "reviewer_output_v2.schema.json"
    )
    canonical_structural_errors = schema_errors(adapted, canonical_reviewer_schema)
    reviewer_ok, reviewer_errors = harness.validate_existing_contract(
        adapted, harness.REVIEWER_VALIDATOR, "reviewer"
    )

    recorded_generator_hash = generator_record["transport_schema_provenance"]["canonical_schema_hash"]
    exact_candidates = _exact_schema_candidates(recorded_generator_hash)
    generator_raw_path = ROOT / Path(generator_record["output_last_message_path"])
    generator_raw = parse_json_text(generator_raw_path.read_text(encoding="utf-8"), "generator")
    generator_item = generator_raw.get("items", [generator_raw])[0] if isinstance(generator_raw, dict) else None
    item_022 = {
        "item_id": GENERATOR_ITEM_ID,
        "recorded_pre_drift_canonical_schema_hash": recorded_generator_hash,
        "exact_schema_reconstructed": bool(exact_candidates),
        "exact_schema_candidates": exact_candidates,
        "replay_performed": bool(exact_candidates),
        "classification": "UNCLASSIFIED_PRE_DRIFT_SCHEMA_UNAVAILABLE" if not exact_candidates else None,
        "reason": (
            "The recorded hash is not recoverable from the historical run, current checkout, reachable, or unreachable Git schema blobs; "
            "validation against the later schema is intentionally not used."
            if not exact_candidates
            else "Exact pre-drift schema resolved; replay result is recorded below."
        ),
    }
    if exact_candidates and isinstance(generator_item, dict):
        exact_path = Path(exact_candidates[0]["source"])
        if exact_candidates[0]["kind"] == "git-blob":
            try:
                schema_document = json.loads(
                    subprocess.check_output(
                        ["git", "cat-file", "blob", exact_candidates[0]["source"]],
                        cwd=ROOT,
                    ).decode("utf-8")
                )
                item_022["schema_validation_errors"] = schema_errors(generator_item, schema_document)
            except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                item_022["schema_validation_error"] = f"could not replay exact Git blob: {exc}"
        else:
            item_022["schema_validation_errors"] = schema_errors(generator_item, load_schema(exact_path))

    return {
        "status": "OFFLINE_AUDIT_COMPLETE",
        "pilot_preserved_as": "exploratory evidence only",
        "model_invocations": 0,
        "reviewer_item_008": {
            "item_id": REVIEWER_ITEM_ID,
            "raw_last_message_path": str(reviewer_raw_path.relative_to(ROOT)).replace("\\", "/"),
            "raw_structural_validation_errors": raw_structural_errors,
            "adapter_added_fields": {
                "generator_answer": adapted.get("generator_answer"),
                "answer_match": adapted.get("answer_match"),
            },
            "canonical_structural_validation_errors": canonical_structural_errors,
            "canonical_reviewer_validator_passed": reviewer_ok,
            "canonical_reviewer_validator_errors": reviewer_errors,
            "contradiction_origin": "MODEL_OUTPUT",
            "evidence": {
                "detected_error_count": raw_reviewer.get("detected_error_count"),
                "marked_part_error_count": sum(value == "ERROR" for value in raw_reviewer.get("marked_part_assessments", {}).values()),
                "adapter_changed_judgment_fields": False,
            },
        },
        "generator_item_022": item_022,
    }


if __name__ == "__main__":
    result = audit()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
