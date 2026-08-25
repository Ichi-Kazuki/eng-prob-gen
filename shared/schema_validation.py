"""Shared Draft 2020-12 JSON Schema validation utilities.

Committed JSON Schema documents are the structural source of truth. Agent
validators call :func:`schema_errors` first and run only genuinely semantic
or cross-field checks in Python afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
except ImportError as exc:  # reported as validator runtime failure by the CLIs
    Draft202012Validator = None  # type: ignore[assignment]
    SchemaError = Exception  # type: ignore[assignment,misc]
    _JSONSCHEMA_IMPORT_ERROR: ImportError | None = exc
else:
    _JSONSCHEMA_IMPORT_ERROR = None

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}

# Compatibility exports for existing introspection tests/importers. Unlike the
# former partial engine, the standard Draft 2020-12 validator enforces all
# applicable vocabulary keywords, including conditionals and references.
ENFORCED_KEYWORDS = (
    "type", "enum", "const", "required", "properties", "additionalProperties",
    "minLength", "minimum", "maximum", "minItems", "items", "propertyNames",
    "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "$ref",
)
UNENFORCED_KEYWORDS: tuple[str, ...] = ()

__all__ = [
    "TYPE_MAP",
    "ENFORCED_KEYWORDS",
    "UNENFORCED_KEYWORDS",
    "SchemaValidationRuntimeError",
    "load_schema",
    "schema_errors",
]


class SchemaValidationRuntimeError(RuntimeError):
    """The validation engine or a committed schema could not be used."""


def _require_jsonschema() -> None:
    if _JSONSCHEMA_IMPORT_ERROR is not None:
        raise SchemaValidationRuntimeError(
            "the 'jsonschema' package is required for Draft 2020-12 validation"
        ) from _JSONSCHEMA_IMPORT_ERROR


def load_schema(path: Path) -> dict[str, Any]:
    """Load and meta-validate a committed Draft 2020-12 schema."""
    _require_jsonschema()
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SchemaValidationRuntimeError(f"cannot read schema {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise SchemaValidationRuntimeError(f"schema {path} is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SchemaValidationRuntimeError(f"schema {path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise SchemaValidationRuntimeError(f"schema {path} must be a JSON object")
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as exc:
        raise SchemaValidationRuntimeError(
            f"invalid Draft 2020-12 schema {path}: {exc.message}"
        ) from exc
    return document


_VALIDATOR_CACHE: dict[str, Any] = {}


def _validator_for(schema: dict[str, Any]) -> Any:
    """Return a memoized validator so meta-validation runs once per schema.

    Validator CLIs call :func:`schema_errors` once per item, and Draft 2020-12
    meta-validation is expensive enough that repeating it per item dominates
    batch runtime.
    """
    try:
        key = json.dumps(schema, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise SchemaValidationRuntimeError(
            f"schema is not a JSON document: {exc}"
        ) from exc
    validator = _VALIDATOR_CACHE.get(key)
    if validator is None:
        try:
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
        except SchemaError as exc:
            raise SchemaValidationRuntimeError(
                f"invalid Draft 2020-12 schema: {exc.message}"
            ) from exc
        _VALIDATOR_CACHE[key] = validator
    return validator


def _json_path(parts: Iterable[object], root: str = "$") -> str:
    result = root
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        elif isinstance(part, str) and part.isidentifier():
            result += f".{part}"
        else:
            result += f"[{json.dumps(part, ensure_ascii=False)}]"
    return result


def _messages_for_error(error: Any) -> list[str]:
    """Return stable, concise messages while retaining jsonschema semantics."""
    validator = error.validator
    if validator == "required":
        missing = sorted(set(error.validator_value) - set(error.instance))
        return [f"missing required property {name!r}" for name in missing]
    if validator == "additionalProperties" and error.validator_value is False:
        allowed = set(error.schema.get("properties", {}))
        unexpected = sorted(set(error.instance) - allowed)
        return [f"additional property {name!r} is not allowed" for name in unexpected]
    if validator == "type":
        expected = error.validator_value
        expected_types = expected if isinstance(expected, list) else [expected]
        return [f"expected type {expected_types}, got {type(error.instance).__name__}"]
    if validator == "enum":
        return [f"{error.instance!r} not in {error.validator_value}"]
    if validator == "const":
        return [f"must equal {error.validator_value!r}"]
    if validator == "minLength":
        return [f"shorter than minLength {error.validator_value}"]
    if validator == "minimum":
        return [f"below minimum {error.validator_value}"]
    if validator == "maximum":
        return [f"above maximum {error.validator_value}"]
    if validator == "minItems":
        return [f"fewer than minItems {error.validator_value}"]
    return [error.message]


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate ``value`` using the standard Draft 2020-12 implementation.

    Every returned error includes a JSON path. Invalid schemas and missing
    dependencies raise :class:`SchemaValidationRuntimeError`, allowing a CLI
    to distinguish runtime failure (exit 2+) from content failure (exit 1).
    """
    _require_jsonschema()
    validator = _validator_for(schema)
    raw_errors = sorted(
        validator.iter_errors(value),
        key=lambda error: (
            _json_path(error.absolute_path),
            error.validator or "",
            error.message,
        ),
    )

    formatted: list[str] = []
    for error in raw_errors:
        where = _json_path(error.absolute_path, root=path)
        formatted.extend(f"{where}: {message}" for message in _messages_for_error(error))
    return formatted
