"""Small JSON persistence helpers for stage state and review queues."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, IO, Iterator, Mapping


class JsonPersistenceError(RuntimeError):
    """A persisted JSON document is unreadable or cannot be written safely."""


def read_json(path: Path) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonPersistenceError(f"cannot read JSON {path}: {exc}") from exc


def canonical_json_sha256(value: object) -> str:
    """Return a stable digest for JSON-compatible values."""
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JsonPersistenceError(f"cannot hash non-JSON value: {exc}") from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _fsync_parent_directory(parent: Path) -> None:
    """Make a successful ``os.replace`` durable on POSIX filesystems.

    Windows does not expose the same directory-fsync contract and continues
    to use the existing file-level durability path.  On POSIX, failure to
    fsync the directory is surfaced rather than silently claiming durability.
    """
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    try:
        directory_fd = os.open(str(parent), flags | directory_flag)
    except OSError:
        raise
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_json(path: Path, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        _fsync_parent_directory(target.parent)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise JsonPersistenceError(f"cannot atomically write JSON {target}: {exc}") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == len("sha256:") + 64
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[len("sha256:"):])
    )


def _artifact_set_sha256(files: Mapping[str, Mapping[str, str]]) -> str:
    return canonical_json_sha256({
        "files": dict(files),
        "required_artifacts": sorted(files),
    })


def _validate_artifact_identity(
    value: object, finalize_id: object, state_digest: object
) -> None:
    """Validate optional run-level identity fields in one artifact payload."""
    if state_digest is None:
        return
    if not _is_sha256(state_digest):
        raise JsonPersistenceError("state_digest must be a sha256 digest")
    if not isinstance(value, dict):
        raise JsonPersistenceError(
            "state-bound finalization artifacts must be JSON objects"
        )
    if value.get("finalize_id") != finalize_id:
        raise JsonPersistenceError(
            "state-bound finalization artifact has a mismatched finalize_id"
        )
    if value.get("state_digest") != state_digest:
        raise JsonPersistenceError(
            "state-bound finalization artifact has a mismatched state_digest"
        )


def publish_json_bundle(
    directory: Path,
    artifacts: Mapping[str, tuple[str, object]],
    *,
    finalize_id: str,
    manifest_name: str = "finalization_manifest.json",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage and publish a group of JSON artifacts with an in-progress marker.

    The individual files retain their historical names and JSON shapes.  The
    manifest is the run-level commit record: it is first written as
    ``IN_PROGRESS`` and becomes ``COMPLETE`` only after every staged file has
    been atomically moved into place and any caller-supplied side effects (for
    example the manual-review queue update) have succeeded.

    A crash can therefore leave old complete files or an in-progress manifest,
    but never a marker that vouches for a partial new generation.  Callers
    must invoke :func:`complete_json_bundle` after all external side effects.
    """
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not isinstance(finalize_id, str) or not finalize_id.strip():
        raise ValueError("finalize_id must be a non-empty string")
    if not artifacts:
        raise ValueError("at least one artifact is required")
    if not manifest_name or Path(manifest_name).name != manifest_name:
        raise ValueError(f"manifest filename must be a basename: {manifest_name!r}")
    reserved_metadata_keys = {
        "manifest_version", "status", "finalize_id", "files", "started_at",
        "required_artifacts", "artifact_set_sha256",
    }
    if metadata is not None and reserved_metadata_keys.intersection(metadata):
        raise ValueError("finalization metadata contains a reserved manifest key")

    staging_dir = Path(tempfile.mkdtemp(prefix=".finalize-", dir=target_dir))
    manifest_path = target_dir / manifest_name
    manifest_files: dict[str, dict[str, str]] = {}
    artifact_filenames: set[str] = set()
    try:
        # Invalidate any previous COMPLETE marker before staging. If an
        # artifact cannot even be serialized, a stale complete marker must not
        # be mistaken for the new finalization attempt.
        provisional = {
            "manifest_version": 1,
            "status": "IN_PROGRESS",
            "finalize_id": finalize_id,
            "files": {},
            "required_artifacts": [],
            "artifact_set_sha256": _artifact_set_sha256({}),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        if metadata is not None:
            provisional.update(dict(metadata))
        atomic_write_json(manifest_path, provisional)

        for artifact_key, (filename, value) in artifacts.items():
            if not isinstance(artifact_key, str) or not artifact_key.strip():
                raise ValueError("artifact key must be a non-empty string")
            if not filename or Path(filename).name != filename:
                raise ValueError(f"artifact filename must be a basename: {filename!r}")
            if filename in artifact_filenames or filename == manifest_name:
                raise ValueError(f"artifact filename is duplicated or reserved: {filename!r}")
            artifact_filenames.add(filename)
            _validate_artifact_identity(
                value,
                finalize_id,
                None if metadata is None else metadata.get("state_digest"),
            )
            staged_path = staging_dir / filename
            atomic_write_json(staged_path, value)
            manifest_files[artifact_key] = {
                "filename": filename,
                "sha256": _file_sha256(staged_path),
            }

        in_progress = {
            "manifest_version": 1,
            "status": "IN_PROGRESS",
            "finalize_id": finalize_id,
            "files": manifest_files,
            "required_artifacts": sorted(manifest_files),
            "artifact_set_sha256": _artifact_set_sha256(manifest_files),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        if metadata is not None:
            in_progress.update(dict(metadata))
        atomic_write_json(manifest_path, in_progress)

        for file_info in manifest_files.values():
            os.replace(staging_dir / file_info["filename"], target_dir / file_info["filename"])
        _fsync_parent_directory(target_dir)
        return in_progress
    finally:
        # Only the private directory created above is removed. If a publish
        # failed midway, the manifest remains IN_PROGRESS for recovery and a
        # subsequent run rebuilds the staging files from its source of truth.
        shutil.rmtree(staging_dir, ignore_errors=True)


def complete_json_bundle(
    directory: Path,
    manifest: Mapping[str, Any],
    *,
    manifest_name: str = "finalization_manifest.json",
) -> dict[str, Any]:
    """Verify published bundle files and atomically commit its manifest."""
    target_dir = Path(directory)
    if not manifest_name or Path(manifest_name).name != manifest_name:
        raise ValueError(f"manifest filename must be a basename: {manifest_name!r}")
    files = manifest.get("files")
    required_artifacts = manifest.get("required_artifacts")
    artifact_set_sha256 = manifest.get("artifact_set_sha256")
    if (
        manifest.get("manifest_version") != 1
        or manifest.get("status") != "IN_PROGRESS"
        or not isinstance(files, dict)
        or not files
        or not isinstance(required_artifacts, list)
        or not all(isinstance(key, str) for key in required_artifacts)
        or not all(isinstance(key, str) for key in files)
        or set(required_artifacts) != set(files)
        or not _is_sha256(artifact_set_sha256)
        or artifact_set_sha256 != _artifact_set_sha256(files)
    ):
        raise JsonPersistenceError("finalization manifest is not an in-progress bundle")
    current_manifest = read_json(target_dir / manifest_name)
    if current_manifest != dict(manifest):
        raise JsonPersistenceError("finalization manifest changed before completion")
    for file_info in files.values():
        if not isinstance(file_info, dict):
            raise JsonPersistenceError("finalization manifest contains malformed file metadata")
        filename = file_info.get("filename")
        expected_hash = file_info.get("sha256")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not _is_sha256(expected_hash)
        ):
            raise JsonPersistenceError("finalization manifest contains incomplete file metadata")
        path = target_dir / filename
        if not path.is_file() or _file_sha256(path) != expected_hash:
            raise JsonPersistenceError(
                f"finalization artifact {path} is missing or does not match the staged hash"
            )
        if "state_digest" in manifest:
            _validate_artifact_identity(
                read_json(path), manifest.get("finalize_id"), manifest.get("state_digest")
            )

    completed = dict(manifest)
    completed["status"] = "COMPLETE"
    completed["completed_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(target_dir / manifest_name, completed)
    return completed


def validate_complete_json_bundle(
    directory: Path, *, manifest_name: str = "finalization_manifest.json"
) -> list[str]:
    """Return errors when a published JSON bundle is not a complete run."""
    target_dir = Path(directory)
    try:
        manifest = read_json(target_dir / manifest_name)
    except JsonPersistenceError as exc:
        return [str(exc)]
    if (
        not isinstance(manifest, dict)
        or manifest.get("manifest_version") != 1
        or manifest.get("status") != "COMPLETE"
        or not isinstance(manifest.get("finalize_id"), str)
        or not manifest["finalize_id"].strip()
    ):
        return ["finalization manifest is absent or not COMPLETE"]
    files = manifest.get("files")
    required_artifacts = manifest.get("required_artifacts")
    artifact_set_sha256 = manifest.get("artifact_set_sha256")
    if (
        not isinstance(files, dict)
        or not files
        or not isinstance(required_artifacts, list)
        or not all(isinstance(key, str) for key in required_artifacts)
        or not all(isinstance(key, str) for key in files)
        or set(required_artifacts) != set(files)
        or not _is_sha256(artifact_set_sha256)
        or artifact_set_sha256 != _artifact_set_sha256(files)
    ):
        return ["finalization manifest contains no files"]
    errors: list[str] = []
    for file_info in files.values():
        if not isinstance(file_info, dict):
            errors.append("finalization manifest contains malformed file metadata")
            continue
        filename = file_info.get("filename")
        expected_hash = file_info.get("sha256")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not _is_sha256(expected_hash)
        ):
            errors.append("finalization manifest contains incomplete file metadata")
            continue
        path = target_dir / filename
        if not path.is_file():
            errors.append(f"finalization artifact {path} is missing")
        elif _file_sha256(path) != expected_hash:
            errors.append(f"finalization artifact {path} does not match the manifest hash")
        elif "state_digest" in manifest:
            try:
                _validate_artifact_identity(
                    read_json(path), manifest.get("finalize_id"), manifest.get("state_digest")
                )
            except (JsonPersistenceError, TypeError, ValueError) as exc:
                errors.append(
                    f"finalization artifact {path} has inconsistent state identity: {exc}"
                )
    return errors


def _lock_windows(handle: IO[bytes], mode_name: str) -> None:
    """Lock one byte using the Windows-only ``msvcrt`` API.

    The module is loaded dynamically so Linux type-checks do not try to
    resolve a platform-specific module.  The attribute checks also turn an
    unexpected Windows runtime/API mismatch into an explicit persistence
    failure instead of a partially-held lock.
    """
    msvcrt = importlib.import_module("msvcrt")
    locking = getattr(msvcrt, "locking", None)
    mode = getattr(msvcrt, mode_name, None)
    if not callable(locking) or not isinstance(mode, int):
        raise OSError(f"Windows file locking API is unavailable: {mode_name}")
    locking(handle.fileno(), mode, 1)


def _lock_posix(handle: IO[bytes], mode_name: str) -> None:
    """Apply a POSIX advisory lock without importing POSIX-only code on Windows."""
    import fcntl

    flock = getattr(fcntl, "flock", None)
    mode = getattr(fcntl, mode_name, None)
    if not callable(flock) or not isinstance(mode, int):
        raise OSError("POSIX file locking is unavailable")
    flock(handle.fileno(), mode)


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Best-effort cross-platform single-writer lock for one JSON file."""
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Windows byte-range locking requires a real byte at the lock offset.
    # Keep the lock file binary and seed it once before taking byte 0.
    handle = lock_path.open("a+b")
    try:
        if sys.platform == "win32":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _lock_windows(handle, "LK_LOCK")
        else:
            _lock_posix(handle, "LOCK_EX")
        yield
    finally:
        try:
            if sys.platform == "win32":
                handle.seek(0)
                _lock_windows(handle, "LK_UNLCK")
            else:
                try:
                    _lock_posix(handle, "LOCK_UN")
                except OSError:
                    # Preserve the historical best-effort unlock behavior.
                    pass
        finally:
            handle.close()


@contextmanager
def exclusive_state_transaction(path: Path, load, save) -> Iterator[object]:
    """Run one complete read-modify-write operation under one file lock.

    ``atomic_write_json`` protects the final replacement only.  Callers that
    need to update a shared state document must hold the lock while loading,
    mutating, and saving it; otherwise two writers can still overwrite one
    another's changes.  The callbacks deliberately stay outside this module
    so the helper can be reused for typed state objects without introducing a
    dependency from the persistence layer to the orchestrator.
    """
    with exclusive_file_lock(path):
        value = load()
        try:
            yield value
        except BaseException:
            raise
        else:
            save(value)
