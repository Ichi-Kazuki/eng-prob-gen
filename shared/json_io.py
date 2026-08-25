"""Small JSON persistence helpers for stage state and review queues."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class JsonPersistenceError(RuntimeError):
    """A persisted JSON document is unreadable or cannot be written safely."""


def read_json(path: Path) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonPersistenceError(f"cannot read JSON {path}: {exc}") from exc


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
    except (OSError, TypeError, ValueError) as exc:
        temp_path.unlink(missing_ok=True)
        raise JsonPersistenceError(f"cannot atomically write JSON {target}: {exc}") from exc


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Best-effort cross-platform single-writer lock for one JSON file."""
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - Windows is the supported runtime here
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
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
