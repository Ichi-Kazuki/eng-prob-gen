"""Immutable run-start snapshots and executable freeze checks.

The live harness is allowed to write artifacts while a run is in progress,
but the executable contracts it evaluates are treated as immutable.  This
module snapshots the canonical schemas used by a run and provides a small
guard that can be called immediately before and after each external agent
invocation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from shared.json_io import atomic_write_json  # noqa: E402


FREEZE_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _run_git(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _repo_relative(repo_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")


def _safe_snapshot_name(key: str, source: Path) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in key).strip("._")
    return (safe or source.stem) + source.suffix


class FreezeDriftError(RuntimeError):
    """A run-start contract no longer matches the live checkout."""

    category = "FREEZE_DRIFT"

    def __init__(self, phase: str, stage: str, mismatches: list[str], manifest_path: Path):
        self.phase = phase
        self.stage = stage
        self.mismatches = tuple(mismatches)
        self.manifest_path = manifest_path
        detail = (
            f"{self.category}: {phase} freeze check failed for {stage}; "
            + ", ".join(mismatches)
        )
        super().__init__(detail)


@dataclass(frozen=True)
class RunFreeze:
    """The persisted run-start manifest and its immutable local snapshots."""

    manifest_path: Path
    snapshot_root: Path
    manifest: dict
    schema_snapshots: dict[str, Path]
    agent_snapshots: dict[str, Path]
    repo_root: Path

    @property
    def manifest_sha256(self) -> str:
        return str(self.manifest["freeze_manifest_sha256"])

    def _manifest_mismatches(self) -> list[str]:
        mismatches: list[str] = []
        try:
            on_disk = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ["freeze_manifest"]
        if on_disk != self.manifest:
            mismatches.append("freeze_manifest_contents")
        payload = copy.deepcopy(self.manifest)
        payload.pop("freeze_manifest_sha256", None)
        expected = _sha256_bytes(_canonical_json(payload))
        if self.manifest.get("freeze_manifest_sha256") != expected:
            mismatches.append("freeze_manifest_sha256")
        return mismatches

    def _live_mismatches(self) -> list[str]:
        mismatches: list[str] = []
        for relative_path, expected in self.manifest["protected_file_hashes"].items():
            path = self.repo_root / relative_path
            try:
                actual = sha256_file(path)
            except OSError:
                actual = "MISSING"
            if actual != expected:
                mismatches.append(f"protected_file_hashes.{relative_path}")

        expected_head = self.manifest.get("git_head")
        actual_head = (_run_git(self.repo_root, "rev-parse", "HEAD") or "").strip() or None
        if actual_head != expected_head:
            mismatches.append("git_head")

        expected_status = self.manifest.get("git_status", {})
        actual_porcelain = _run_git(self.repo_root, "status", "--porcelain", "--untracked-files=all")
        if actual_porcelain is None:
            mismatches.append("git_status(unavailable)")
        else:
            actual_clean = actual_porcelain == ""
            if actual_clean != expected_status.get("clean"):
                mismatches.append("git_status.clean")

        for key, snapshot_path in self.schema_snapshots.items():
            expected = self.manifest["canonical_schema_snapshots"][key]["sha256"]
            try:
                actual = sha256_file(snapshot_path)
            except OSError:
                actual = "MISSING"
            if actual != expected:
                mismatches.append(f"canonical_schema_snapshots.{key}")
        for key, snapshot_path in self.agent_snapshots.items():
            record = self.manifest.get("agent_instruction_snapshots", {}).get(key)
            if record is None:
                continue
            expected = record["sha256"]
            try:
                actual = sha256_file(snapshot_path)
            except OSError:
                actual = "MISSING"
            if actual != expected:
                mismatches.append(f"agent_instruction_snapshots.{key}")
        return mismatches

    def verify(self, phase: str, stage: str) -> None:
        """Fail closed if the freeze manifest or protected files drifted."""

        mismatches = self._manifest_mismatches() + self._live_mismatches()
        if mismatches:
            raise FreezeDriftError(phase, stage, sorted(set(mismatches)), self.manifest_path)

    def guard(self, phase: str, stage: str) -> None:
        self.verify(phase, stage)


def create_run_freeze(
    freeze_root: Path,
    *,
    repo_root: Path,
    protected_file_groups: Mapping[str, Mapping[str, Path]],
    canonical_schemas: Mapping[str, Path],
    agent_instructions: Mapping[str, Path],
    provider: str,
    codex_cli_version: str,
    model: str,
    reasoning_effort: str,
    sandbox: str,
    timeout_seconds: float,
) -> RunFreeze:
    """Create and persist a run-start freeze plus schema/instruction snapshots."""

    repo_root = repo_root.resolve()
    freeze_root = freeze_root.resolve()
    snapshot_root = freeze_root / "snapshots"
    schema_root = snapshot_root / "canonical-schemas"
    agent_root = snapshot_root / "agent-instructions"
    schema_root.mkdir(parents=True, exist_ok=True)
    agent_root.mkdir(parents=True, exist_ok=True)

    protected: dict[str, str] = {}
    normalized_groups: dict[str, dict[str, str]] = {}
    for group, files in protected_file_groups.items():
        normalized_groups[group] = {}
        for label, source in files.items():
            source = source.resolve()
            relative = _repo_relative(repo_root, source)
            digest = sha256_file(source)
            protected[relative] = digest
            normalized_groups[group][label] = digest

    schema_snapshots: dict[str, Path] = {}
    schema_snapshot_records: dict[str, dict[str, str]] = {}
    for key, source in canonical_schemas.items():
        source = source.resolve()
        target = schema_root / _safe_snapshot_name(key, source)
        shutil.copyfile(source, target)
        digest = sha256_file(source)
        if sha256_file(target) != digest:
            raise OSError(f"schema snapshot hash mismatch for {key}")
        relative = _repo_relative(repo_root, target)
        schema_snapshots[key] = target
        source_relative = _repo_relative(repo_root, source)
        protected[source_relative] = digest
        normalized_groups.setdefault("canonical_schemas", {})[key] = digest
        schema_snapshot_records[key] = {
            "source_path": source_relative,
            "snapshot_path": relative,
            "sha256": digest,
        }

    agent_snapshots: dict[str, Path] = {}
    agent_hashes: dict[str, str] = {}
    agent_snapshot_records: dict[str, dict[str, str]] = {}
    for key, source in agent_instructions.items():
        source = source.resolve()
        target = agent_root / _safe_snapshot_name(key, source)
        shutil.copyfile(source, target)
        digest = sha256_file(source)
        if sha256_file(target) != digest:
            raise OSError(f"agent-instruction snapshot hash mismatch for {key}")
        agent_snapshots[key] = target
        source_relative = _repo_relative(repo_root, source)
        snapshot_relative = _repo_relative(repo_root, target)
        agent_hashes[source_relative] = digest
        protected[source_relative] = digest
        normalized_groups.setdefault("agent_instructions", {})[key] = digest
        agent_snapshot_records[key] = {
            "source_path": source_relative,
            "snapshot_path": snapshot_relative,
            "sha256": digest,
        }

    git_head = (_run_git(repo_root, "rev-parse", "HEAD") or "").strip() or None
    git_porcelain = _run_git(repo_root, "status", "--porcelain", "--untracked-files=all")
    if git_porcelain is None:
        raise RuntimeError("could not capture Git status for run freeze")

    manifest = {
        "freeze_schema_version": FREEZE_SCHEMA_VERSION,
        "run_id": "run-" + uuid.uuid4().hex,
        "created_at": _now_iso(),
        "git_head": git_head,
        "git_status": {
            "clean": git_porcelain == "",
            "porcelain": git_porcelain,
            "porcelain_sha256": _sha256_bytes(git_porcelain.encode("utf-8")),
        },
        "protected_file_groups": normalized_groups,
        "protected_file_hashes": dict(sorted(protected.items())),
        "canonical_schema_hashes": {
            key: record["sha256"] for key, record in sorted(schema_snapshot_records.items())
        },
        "canonical_schema_snapshots": schema_snapshot_records,
        "agent_instruction_hashes": dict(sorted(agent_hashes.items())),
        "agent_instruction_snapshots": agent_snapshot_records,
        "runtime": {
            "provider": provider,
            "codex_cli_version": codex_cli_version,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "sandbox": sandbox,
            "timeout_seconds": timeout_seconds,
        },
    }
    manifest["freeze_manifest_sha256"] = _sha256_bytes(_canonical_json(manifest))
    manifest_path = freeze_root / "freeze_manifest.json"
    atomic_write_json(manifest_path, manifest)
    return RunFreeze(
        manifest_path=manifest_path,
        snapshot_root=snapshot_root,
        manifest=copy.deepcopy(manifest),
        schema_snapshots=schema_snapshots,
        agent_snapshots=agent_snapshots,
        repo_root=repo_root,
    )


__all__ = [
    "FREEZE_SCHEMA_VERSION",
    "FreezeDriftError",
    "RunFreeze",
    "create_run_freeze",
    "sha256_file",
]
