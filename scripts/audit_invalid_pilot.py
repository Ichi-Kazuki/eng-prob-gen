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
sys.path.insert(0, str(ROOT / "scripts"))
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


def _git_rows(command: list[str]) -> tuple[list[str], bool]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return [], False
    if completed.returncode != 0:
        return [], False
    return completed.stdout.splitlines(), True


def _exact_schema_candidates_with_scope(
    recorded_hash: str,
    *,
    canonical_path: Path | None = None,
    schema_filename: str = "written_expression_item_v2.schema.json",
) -> tuple[list[dict[str, str]], dict[str, bool]]:
    candidates: list[dict[str, str]] = []
    search_scope = {
        "filesystem": False,
        "reachable_git_objects": False,
        "unreachable_git_blobs": False,
    }
    paths = [canonical_path or ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / schema_filename]
    freeze_snapshot_root = PILOT_ROOT / "runtime" / "freeze" / "snapshots" / "canonical-schemas"
    if freeze_snapshot_root.exists():
        paths.extend(freeze_snapshot_root.glob("*.json"))
    search_scope["filesystem"] = True
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

    reachable_rows, reachable_ok = _git_rows(["git", "rev-list", "--all", "--objects", "--reflog"])
    search_scope["reachable_git_objects"] = reachable_ok
    unreachable_rows, unreachable_ok = _git_rows(["git", "fsck", "--full", "--no-reflogs", "--unreachable"])
    search_scope["unreachable_git_blobs"] = unreachable_ok
    seen_objects: set[str] = set()
    for row in reachable_rows:
        parts = row.split(" ", 1)
        if len(parts) != 2 or schema_filename not in parts[1]:
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
    # ``git fsck`` reports unreachable blobs as ``unreachable blob <object>``
    # without their historical filename.  Search their content directly and
    # accept only an exact content SHA-256 match to the recorded contract.
    for row in unreachable_rows:
        parts = row.split()
        if len(parts) != 3 or parts[0] != "unreachable" or parts[1] != "blob":
            continue
        object_id = parts[2]
        if object_id in seen_objects:
            continue
        seen_objects.add(object_id)
        try:
            raw = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=ROOT)
        except (OSError, subprocess.CalledProcessError):
            continue
        if "sha256:" + hashlib.sha256(raw).hexdigest() == recorded_hash:
            candidates.append(
                {
                    "source": object_id,
                    "kind": "git-blob",
                    "path": f"unreachable/{object_id}",
                    "search_scope": "unreachable_git_blob_content",
                }
            )
    return candidates, search_scope


def _exact_schema_candidates(
    recorded_hash: str,
    *,
    canonical_path: Path | None = None,
    schema_filename: str = "written_expression_item_v2.schema.json",
) -> list[dict[str, str]]:
    """Find exact historical schema content without filtering unreachable blobs by name."""

    candidates, _scope = _exact_schema_candidates_with_scope(
        recorded_hash, canonical_path=canonical_path, schema_filename=schema_filename
    )
    return candidates


def _schema_document(candidate: dict[str, str]) -> dict[str, Any]:
    if candidate["kind"] == "filesystem":
        document = load_schema(Path(candidate["source"]))
    else:
        raw = subprocess.check_output(["git", "cat-file", "blob", candidate["source"]], cwd=ROOT)
        document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("historical schema blob is not a JSON object")
    return document


def audit() -> dict:
    reviewer_record = _find_provenance_record("reviewer", REVIEWER_ITEM_ID)
    generator_record = _find_provenance_record("generator", GENERATOR_ITEM_ID)
    reviewer_raw_path = ROOT / Path(reviewer_record["output_last_message_path"])
    raw_reviewer = parse_json_text(reviewer_raw_path.read_text(encoding="utf-8"), "reviewer")
    if not isinstance(raw_reviewer, dict):
        raise ValueError("stored Reviewer last message is not an object")

    reviewer_generator_item = _load_item(
        PILOT_ROOT / "runtime" / "formal" / "generator_outputs.json",
        REVIEWER_ITEM_ID,
    )
    reviewer_schema_path = ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "schema" / "reviewer_output_v2.schema.json"
    reviewer_transport_provenance = reviewer_record.get("transport_schema_provenance")
    reviewer_hash = (
        reviewer_transport_provenance.get("canonical_schema_hash")
        if isinstance(reviewer_transport_provenance, dict)
        else None
    )
    reviewer_candidates: list[dict[str, str]] = []
    reviewer_search_scope: dict[str, bool] = {}
    if isinstance(reviewer_hash, str):
        reviewer_candidates, reviewer_search_scope = _exact_schema_candidates_with_scope(
            reviewer_hash,
            canonical_path=reviewer_schema_path,
            schema_filename=reviewer_schema_path.name,
        )
    raw_structural_errors: list[str] = []
    canonical_structural_errors: list[str] = []
    adapted: dict[str, Any] = {}
    reviewer_ok: bool | None = None
    reviewer_errors: list[str] = []
    reviewer_replay_classification: str | None = None
    if reviewer_candidates:
        reviewer_document = _schema_document(reviewer_candidates[0])
        reviewer_schema = harness.reviewer_runtime_schema(reviewer_document)
        raw_structural_errors = schema_errors(raw_reviewer, reviewer_schema)
        if not raw_structural_errors:
            try:
                adapted = harness.adapt_reviewer_structural(
                    copy.deepcopy(raw_reviewer),
                    reviewer_generator_item,
                    8,
                    "we-v2.1.3-live-pilot-25-20260826T115906Z",
                    reviewer_schema,
                )
                canonical_structural_errors = schema_errors(adapted, reviewer_document)
            except (KeyError, TypeError, ValueError, harness.LiveInvocationError) as exc:
                reviewer_replay_classification = "UNCLASSIFIED_REVIEWER_REPLAY_ERROR"
                reviewer_errors = [str(exc)]
        # A schema hash alone does not prove that the semantic validator is
        # historical. Only a freeze that also protects the validator enables a
        # canonical validator replay; otherwise leave the result unclassified.
        historical_freeze_path = PILOT_ROOT / "runtime" / "freeze" / "freeze_manifest.json"
        if historical_freeze_path.exists():
            try:
                historical_freeze = harness.load_run_freeze(historical_freeze_path, repo_root=ROOT)
                historical_freeze.verify("audit", "reviewer")
                reviewer_ok, reviewer_errors = harness.validate_existing_contract(
                    adapted, harness.REVIEWER_VALIDATOR, "reviewer"
                )
            except (harness.FreezeDriftError, OSError, TypeError, ValueError, KeyError) as exc:
                reviewer_replay_classification = "UNCLASSIFIED_REVIEWER_VALIDATOR_UNAVAILABLE"
                reviewer_errors = [str(exc)]
        else:
            reviewer_replay_classification = "UNCLASSIFIED_REVIEWER_VALIDATOR_UNAVAILABLE"
            reviewer_errors = ["historical freeze does not protect the Reviewer validator"]
    else:
        reviewer_replay_classification = "UNCLASSIFIED_REVIEWER_SCHEMA_UNAVAILABLE"
        reviewer_errors = ["recorded Reviewer schema hash is not recoverable from the searched contract sources"]

    recorded_generator_hash = generator_record["transport_schema_provenance"]["canonical_schema_hash"]
    exact_candidates, search_scope = _exact_schema_candidates_with_scope(recorded_generator_hash)
    generator_raw_path = ROOT / Path(generator_record["output_last_message_path"])
    generator_raw = parse_json_text(generator_raw_path.read_text(encoding="utf-8"), "generator")
    generator_item = generator_raw.get("items", [generator_raw])[0] if isinstance(generator_raw, dict) else None
    item_022 = {
        "item_id": GENERATOR_ITEM_ID,
        "recorded_pre_drift_canonical_schema_hash": recorded_generator_hash,
        "exact_schema_reconstructed": bool(exact_candidates),
        "exact_schema_candidates": exact_candidates,
        "schema_search_scope": search_scope,
        "replay_performed": bool(exact_candidates),
        "classification": "UNCLASSIFIED_PRE_DRIFT_SCHEMA_UNAVAILABLE" if not exact_candidates else None,
        "reason": (
            "The recorded hash is not recoverable from the searched filesystem paths or Git object ranges "
            f"({', '.join(name for name, searched in search_scope.items() if searched)}); "
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
            "historical_schema_candidates": reviewer_candidates,
            "schema_search_scope": reviewer_search_scope,
            "classification": reviewer_replay_classification,
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
