"""Immutable run-start snapshots and executable freeze checks.

The live harness is allowed to write artifacts while a run is in progress,
but the executable contracts it evaluates are treated as immutable.  This
module snapshots the canonical schemas used by a run and provides a small
guard that can be called immediately before and after each external agent
invocation.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from shared.json_io import atomic_write_json  # noqa: E402


FREEZE_SCHEMA_VERSION = 2
PROTECTED_FREEZE_DRIFT = "PROTECTED_FREEZE_DRIFT"
NONPROTECTED_WORKSPACE_DIRTY = "NONPROTECTED_WORKSPACE_DIRTY"

# These are deliberately narrow, repository-relative patterns.  A path that
# is not listed here is treated as protected source/configuration for a new
# freeze, even if it is not one of the individually hashed files.
DEFAULT_NONPROTECTED_PATHS = (
    ".analysis_tmp_deps/",
    ".analysis_tmp_pip_audit/",
    ".analysis_tmp_uv_cache/",
    ".coverage",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "artifacts/",
    "htmlcov/",
    "ocr/",
    "render/",
    "runs/",
    "tmp/",
    "*.ocr/",
    "*.render/",
    "*.tmp",
    "__pycache__/",
    "*.pyc",
)


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


def _git_status_porcelain(repo_root: Path, *, excluded_path: Path | None = None) -> str | None:
    """Read user checkout status while excluding generated freeze artifacts."""

    args = ["status", "--porcelain", "--untracked-files=all"]
    if excluded_path is not None:
        try:
            relative = _repo_relative(repo_root, excluded_path)
        except ValueError:
            relative = None
        if relative:
            args.extend(["--", ".", f":(exclude){relative}/**"])
    return _run_git(repo_root, *args)


def _status_paths(row: str) -> list[str]:
    """Extract all paths represented by one porcelain-v1 status row."""

    if len(row) < 4:
        return []
    value = row[3:].strip()
    if " -> " in value:
        return [part.strip().strip('"') for part in value.split(" -> ")]
    return [value.strip('"')]


def _allowlisted_workspace_path(path: str, allowlist: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in allowlist:
        candidate = pattern.replace("\\", "/").lstrip("./")
        if candidate.endswith("/"):
            if normalized == candidate[:-1] or normalized.startswith(candidate):
                return True
        elif fnmatch.fnmatchcase(normalized, candidate):
            return True
    return False


def classify_workspace_status(
    porcelain: str,
    *,
    allowlist: Sequence[str] = DEFAULT_NONPROTECTED_PATHS,
) -> dict[str, object]:
    """Separate protected freeze drift from explicitly ephemeral dirtiness."""

    protected_rows: list[str] = []
    nonprotected_rows: list[str] = []
    for row in porcelain.splitlines(keepends=True):
        paths = _status_paths(row.rstrip("\r\n"))
        if paths and all(_allowlisted_workspace_path(path, allowlist) for path in paths):
            nonprotected_rows.append(row)
        else:
            protected_rows.append(row)

    protected_porcelain = "".join(protected_rows)
    nonprotected_porcelain = "".join(nonprotected_rows)
    return {
        "protected": {
            "clean": protected_porcelain == "",
            "porcelain": protected_porcelain,
            "porcelain_sha256": _sha256_bytes(protected_porcelain.encode("utf-8")),
            "entries": [row.rstrip("\r\n") for row in protected_rows],
        },
        "nonprotected": {
            "dirty": nonprotected_porcelain != "",
            "porcelain": nonprotected_porcelain,
            "porcelain_sha256": _sha256_bytes(nonprotected_porcelain.encode("utf-8")),
            "entries": [row.rstrip("\r\n") for row in nonprotected_rows],
        },
    }


def _repo_relative(repo_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")


def _path_identity(repo_root: Path, path: Path) -> tuple[str, str]:
    """Return a manifest path without confusing repo sources and artifacts.

    Protected source files are required to live in the checkout and therefore
    use a stable repository-relative identity.  Snapshot/artifact paths may
    intentionally live outside the checkout (for example when
    ``WE_E2E_OUTPUT_DIR`` is absolute), so those paths retain their absolute
    identity in the manifest.
    """

    resolved = path.resolve()
    try:
        return _repo_relative(repo_root, resolved), "repo_relative"
    except ValueError:
        return str(resolved).replace("\\", "/"), "external"


def _resolve_manifest_path(repo_root: Path, value: object, kind: object = None) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("freeze manifest path must be a non-empty string")
    path = Path(value)
    if kind == "external" or path.is_absolute():
        return path.resolve()
    return (repo_root / path).resolve()


def _safe_snapshot_name(key: str, source: Path) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in key).strip("._")
    return (safe or source.stem) + source.suffix


class FreezeDriftError(RuntimeError):
    """A run-start contract no longer matches the live checkout."""

    category = PROTECTED_FREEZE_DRIFT

    def __init__(
        self,
        phase: str,
        stage: str,
        mismatches: list[str],
        manifest_path: Path,
        *,
        category: str = PROTECTED_FREEZE_DRIFT,
    ):
        self.category = category
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

    @property
    def workspace_allowlist(self) -> tuple[str, ...]:
        configured = self.manifest.get("workspace_allowlist", DEFAULT_NONPROTECTED_PATHS)
        if not isinstance(configured, list) or any(not isinstance(value, str) for value in configured):
            return DEFAULT_NONPROTECTED_PATHS
        return tuple(configured)

    def workspace_status(self) -> dict[str, object]:
        """Return current protected/nonprotected status without mutating evidence."""

        porcelain = _git_status_porcelain(self.repo_root, excluded_path=self.manifest_path.parent)
        if porcelain is None:
            return {"available": False, "category": PROTECTED_FREEZE_DRIFT}
        classified = classify_workspace_status(porcelain, allowlist=self.workspace_allowlist)
        protected = classified["protected"]
        nonprotected = classified["nonprotected"]
        category = (
            PROTECTED_FREEZE_DRIFT
            if isinstance(protected, dict) and not protected["clean"]
            else NONPROTECTED_WORKSPACE_DIRTY
            if isinstance(nonprotected, dict) and nonprotected["dirty"]
            else None
        )
        return {"available": True, "category": category, **classified}

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
        actual_porcelain = _git_status_porcelain(self.repo_root, excluded_path=self.manifest_path.parent)
        if actual_porcelain is None:
            mismatches.append("git_status(unavailable)")
        elif "protected_porcelain_sha256" in expected_status:
            # v2 freezes compare only the protected partition.  Ephemeral
            # cache/output churn is observable through workspace_status(), but
            # cannot invalidate the frozen cohort by itself.
            actual_status = classify_workspace_status(actual_porcelain, allowlist=self.workspace_allowlist)
            actual_protected = actual_status["protected"]
            expected_protected = expected_status.get("protected", {})
            if not isinstance(actual_protected, dict) or not isinstance(expected_protected, dict):
                mismatches.append("git_status.protected")
            else:
                if actual_protected["porcelain_sha256"] != expected_status.get("protected_porcelain_sha256"):
                    mismatches.append("git_status.protected_porcelain_sha256")
                if actual_protected["porcelain"] != expected_status.get("protected_porcelain"):
                    mismatches.append("git_status.protected_porcelain")
                if actual_protected["clean"] != expected_status.get("protected_clean"):
                    mismatches.append("git_status.protected_clean")
        else:
            # Preserve verification semantics for historical v1 manifests.
            actual_clean = actual_porcelain == ""
            if actual_clean != expected_status.get("clean"):
                mismatches.append("git_status.clean")
            expected_porcelain_hash = expected_status.get("porcelain_sha256")
            actual_porcelain_hash = _sha256_bytes(actual_porcelain.encode("utf-8"))
            if actual_porcelain_hash != expected_porcelain_hash:
                mismatches.append("git_status.porcelain_sha256")
            if actual_porcelain != expected_status.get("porcelain"):
                mismatches.append("git_status.porcelain")

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
    workspace_allowlist: Sequence[str] | None = None,
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
        snapshot_path, snapshot_path_kind = _path_identity(repo_root, target)
        schema_snapshots[key] = target
        source_relative = _repo_relative(repo_root, source)
        protected[source_relative] = digest
        normalized_groups.setdefault("canonical_schemas", {})[key] = digest
        schema_snapshot_records[key] = {
            "source_path": source_relative,
            "snapshot_path": snapshot_path,
            "snapshot_path_kind": snapshot_path_kind,
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
        snapshot_path, snapshot_path_kind = _path_identity(repo_root, target)
        agent_hashes[source_relative] = digest
        protected[source_relative] = digest
        normalized_groups.setdefault("agent_instructions", {})[key] = digest
        agent_snapshot_records[key] = {
            "source_path": source_relative,
            "snapshot_path": snapshot_path,
            "snapshot_path_kind": snapshot_path_kind,
            "sha256": digest,
        }

    allowlist = tuple(DEFAULT_NONPROTECTED_PATHS if workspace_allowlist is None else workspace_allowlist)
    git_head = (_run_git(repo_root, "rev-parse", "HEAD") or "").strip() or None
    git_porcelain = _git_status_porcelain(repo_root, excluded_path=freeze_root)
    if git_porcelain is None:
        raise RuntimeError("could not capture Git status for run freeze")
    workspace_status = classify_workspace_status(git_porcelain, allowlist=allowlist)
    protected_status = workspace_status["protected"]
    nonprotected_status = workspace_status["nonprotected"]
    if not isinstance(protected_status, dict) or not isinstance(nonprotected_status, dict):
        raise RuntimeError("workspace status classifier returned an invalid result")

    manifest = {
        "freeze_schema_version": FREEZE_SCHEMA_VERSION,
        "run_id": "run-" + uuid.uuid4().hex,
        "created_at": _now_iso(),
        "git_head": git_head,
        "git_status": {
            "clean": git_porcelain == "",
            "porcelain": git_porcelain,
            "porcelain_sha256": _sha256_bytes(git_porcelain.encode("utf-8")),
            "protected_clean": protected_status["clean"],
            "protected_porcelain": protected_status["porcelain"],
            "protected_porcelain_sha256": protected_status["porcelain_sha256"],
            "nonprotected_dirty": nonprotected_status["dirty"],
            "nonprotected_porcelain": nonprotected_status["porcelain"],
            "nonprotected_porcelain_sha256": nonprotected_status["porcelain_sha256"],
        },
        "workspace_allowlist": list(allowlist),
        "worktree": {
            "source_root": str(repo_root).replace("\\", "/"),
            "exact_commit": git_head,
            "detached": not bool((_run_git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD") or "").strip()),
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


def load_run_freeze(manifest_path: Path, *, repo_root: Path) -> RunFreeze:
    """Load an existing freeze without recreating any snapshot or manifest.

    The caller must invoke :meth:`RunFreeze.verify` before trusting the loaded
    contract.  Both current repository-relative manifests and the newer
    external snapshot identities are accepted so historical run artifacts can
    be checked without moving them into the checkout.
    """

    manifest_path = Path(manifest_path).resolve()
    repo_root = Path(repo_root).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load freeze manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"freeze manifest {manifest_path} must be a JSON object")

    snapshot_root = manifest_path.parent / "snapshots"
    schema_snapshots: dict[str, Path] = {}
    for key, record in manifest.get("canonical_schema_snapshots", {}).items():
        if not isinstance(record, dict):
            raise ValueError(f"malformed canonical schema snapshot record: {key}")
        schema_snapshots[str(key)] = _resolve_manifest_path(
            repo_root, record.get("snapshot_path"), record.get("snapshot_path_kind")
        )

    agent_snapshots: dict[str, Path] = {}
    for key, record in manifest.get("agent_instruction_snapshots", {}).items():
        if not isinstance(record, dict):
            raise ValueError(f"malformed agent instruction snapshot record: {key}")
        agent_snapshots[str(key)] = _resolve_manifest_path(
            repo_root, record.get("snapshot_path"), record.get("snapshot_path_kind")
        )

    return RunFreeze(
        manifest_path=manifest_path,
        snapshot_root=snapshot_root,
        manifest=copy.deepcopy(manifest),
        schema_snapshots=schema_snapshots,
        agent_snapshots=agent_snapshots,
        repo_root=repo_root,
    )


def create_detached_worktree(
    repository_root: Path,
    worktree_path: Path,
    *,
    commit: str,
) -> str:
    """Materialize one exact detached commit for a quality-pilot source tree.

    The caller owns the lifecycle of the resulting worktree.  This helper
    refuses an existing destination, verifies the resolved commit and detached
    HEAD, and requires an initially clean protected partition.  Pilot output
    should be directed outside this tree so generated evidence cannot become
    source input.
    """

    repository_root = Path(repository_root).resolve()
    worktree_path = Path(worktree_path).resolve()
    if worktree_path.exists():
        raise FileExistsError(f"quality pilot worktree already exists: {worktree_path}")
    resolved_commit = (_run_git(repository_root, "rev-parse", f"{commit}^{{commit}}") or "").strip()
    if not resolved_commit:
        raise ValueError(f"could not resolve quality pilot commit {commit!r}")
    try:
        completed = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree_path), resolved_commit],
            cwd=repository_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not create detached quality pilot worktree: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git worktree add failed").strip()
        raise RuntimeError(detail)

    actual_commit = (_run_git(worktree_path, "rev-parse", "HEAD") or "").strip()
    branch = (_run_git(worktree_path, "symbolic-ref", "--quiet", "--short", "HEAD") or "").strip()
    porcelain = _git_status_porcelain(worktree_path)
    if actual_commit != resolved_commit or branch or porcelain is None or porcelain:
        mismatches: list[str] = []
        if actual_commit != resolved_commit:
            mismatches.append("worktree.git_head")
        if branch:
            mismatches.append("worktree.detached_head")
        if porcelain:
            mismatches.append("worktree.protected_status")
        if porcelain is None:
            mismatches.append("worktree.status_unavailable")
        raise RuntimeError(
            "quality pilot worktree failed immutable preflight: " + ", ".join(mismatches)
        )
    return resolved_commit


def verify_detached_worktree(repository_root: Path, *, expected_commit: str | None = None) -> str:
    """Verify that a pilot source root is detached, exact, and protected-clean."""

    repository_root = Path(repository_root).resolve()
    actual_commit = (_run_git(repository_root, "rev-parse", "HEAD") or "").strip()
    branch = (_run_git(repository_root, "symbolic-ref", "--quiet", "--short", "HEAD") or "").strip()
    porcelain = _git_status_porcelain(repository_root)
    mismatches: list[str] = []
    if not actual_commit:
        mismatches.append("worktree.git_head_unavailable")
    if expected_commit and actual_commit != expected_commit:
        mismatches.append("worktree.git_head")
    if branch:
        mismatches.append("worktree.detached_head")
    if porcelain is None:
        mismatches.append("worktree.status_unavailable")
    elif porcelain:
        classified = classify_workspace_status(porcelain)
        protected = classified["protected"]
        if isinstance(protected, dict) and not protected["clean"]:
            mismatches.append("worktree.protected_status")
    if mismatches:
        raise ValueError("quality pilot worktree preflight failed: " + ", ".join(mismatches))
    return actual_commit


__all__ = [
    "DEFAULT_NONPROTECTED_PATHS",
    "FREEZE_SCHEMA_VERSION",
    "FreezeDriftError",
    "NONPROTECTED_WORKSPACE_DIRTY",
    "PROTECTED_FREEZE_DRIFT",
    "RunFreeze",
    "classify_workspace_status",
    "create_detached_worktree",
    "create_run_freeze",
    "load_run_freeze",
    "sha256_file",
    "verify_detached_worktree",
]
