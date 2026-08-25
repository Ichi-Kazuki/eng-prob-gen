"""Crash-safe JSON persistence helpers used by pipeline state artifacts."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class JsonPersistenceError(RuntimeError):
    """A persisted JSON artifact cannot be read or safely updated."""


def read_json(path: Path) -> Any:
    """Read JSON without hiding missing, malformed, or inaccessible data."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise JsonPersistenceError(f"cannot read JSON file {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise JsonPersistenceError(f"{path} is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JsonPersistenceError(f"malformed JSON in {path}: {exc}") from exc


def atomic_write_json(path: Path, value: Any) -> Path:
    """Write JSON through a same-directory temporary file and ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise JsonPersistenceError(f"cannot atomically write JSON file {path}: {exc}") from exc
    # The new content is already visible at ``path``; a failure to fsync the
    # parent directory only weakens crash durability, so it must not be
    # reported as a failed write.
    if os.name != "nt":
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return path
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)
    return path


@contextmanager
def exclusive_file_lock(path: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Use atomic lock-file creation to serialize a short read/modify/write.

    This is intentionally small and cross-platform. A surviving stale lock is
    reported instead of being silently broken, because guessing that another
    writer is dead risks losing operational queue data.
    """
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            if time.monotonic() >= deadline:
                raise JsonPersistenceError(
                    f"timed out waiting for JSON write lock {lock_path}"
                ) from exc
            time.sleep(0.05)
        except OSError as exc:
            raise JsonPersistenceError(f"cannot create JSON write lock {lock_path}: {exc}") from exc
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
