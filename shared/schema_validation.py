"""Draft 2020-12 JSON Schema validation shared by pipeline boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
except ImportError as exc:  # pragma: no cover - exercised in deployment failures
    Draft202012Validator = None  # type: ignore[assignment]
    SchemaError = Exception  # type: ignore[assignment,misc]
    _IMPORT_ERROR: ImportError | None = exc
else:
    _IMPORT_ERROR = None


class SchemaValidationRuntimeError(RuntimeError):
    """The schema or the JSON Schema runtime could not be used."""


def _require_runtime() -> None:
    if _IMPORT_ERROR is not None:
        raise SchemaValidationRuntimeError(
            "the 'jsonschema' package is required for Draft 2020-12 validation"
        ) from _IMPORT_ERROR


def load_schema(path: Path) -> dict[str, Any]:
    _require_runtime()
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaValidationRuntimeError(f"cannot load schema {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise SchemaValidationRuntimeError(f"schema {path} must be a JSON object")
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as exc:
        raise SchemaValidationRuntimeError(f"invalid schema {path}: {exc.message}") from exc
    return document


def _path(parts: tuple[object, ...], root: str = "$") -> str:
    result = root
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _message(error: Any) -> list[str]:
    if error.validator == "required":
        missing = sorted(set(error.validator_value) - set(error.instance))
        return [f"missing required property {name!r}" for name in missing]
    if error.validator == "additionalProperties" and error.validator_value is False:
        allowed = set(error.schema.get("properties", {}))
        unexpected = sorted(set(error.instance) - allowed)
        return [f"additional property {name!r} is not allowed" for name in unexpected]
    return [error.message]


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return stable path-prefixed errors; invalid schemas raise runtime errors."""
    _require_runtime()
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except SchemaError as exc:
        raise SchemaValidationRuntimeError(f"invalid Draft 2020-12 schema: {exc.message}") from exc
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(value),
        key=lambda current: (tuple(current.absolute_path), current.validator or "", current.message),
    ):
        errors.extend(f"{_path(tuple(error.absolute_path), path)}: {message}" for message in _message(error))
    return errors
