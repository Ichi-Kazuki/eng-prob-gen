"""Build the Codex-only Structured Outputs schema projection.

Canonical JSON Schemas remain the contract used by the pipeline validators.
This module creates a separate, deterministic transport projection for
``codex exec --output-schema``.  The projection is deliberately allowed to
lose conditional/semantic constraints, but every such loss is recorded in
provenance and the caller must still validate the returned record against the
canonical contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


JsonObject = dict[str, Any]
SchemaInput = Mapping[str, Any] | Path | str


# These keywords are explicitly outside the Structured Outputs subset or are
# not safe to pass to the Codex endpoint.  ``anyOf`` and definitions/$ref are
# supported by Structured Outputs and are therefore retained after their
# children are projected.
UNSUPPORTED_COMPOSITION_KEYWORDS = frozenset(
    {
        "allOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
        "oneOf",
    }
)

# Keep this conservative for the current Codex endpoint.  The current
# Structured Outputs documentation supports the type-specific constraints for
# non-fine-tuned models, so minLength/minimum/minItems/etc. are retained.
UNSUPPORTED_SCHEMA_KEYWORDS = UNSUPPORTED_COMPOSITION_KEYWORDS | frozenset(
    {
        "$anchor",
        "$comment",
        "$dynamicRef",
        "$dynamicAnchor",
        "$vocabulary",
        "additionalItems",
        "contains",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "default",
        "deprecated",
        "discriminator",
        "examples",
        "propertyNames",
        "patternProperties",
        "prefixItems",
        "unevaluatedItems",
        "unevaluatedProperties",
        "uniqueItems",
        "maxProperties",
        "minProperties",
        "readOnly",
        "writeOnly",
    }
)

SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$defs",
        "$ref",
        "title",
        "description",
        "type",
        "enum",
        "anyOf",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
    }
)

# ``const`` is not one of the documented Structured Outputs property forms;
# singleton enum is its exact supported representation.


@dataclass(frozen=True)
class CodexTransportBuild:
    """A transport schema and its auditable derivation record."""

    schema: JsonObject
    provenance: JsonObject


class CodexTransportSchemaError(ValueError):
    """The canonical document cannot produce an object-root transport schema."""


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _schema_hash(schema: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_json(schema))


def _load_input(value: SchemaInput) -> tuple[JsonObject, str | None, str]:
    if isinstance(value, Path) or isinstance(value, str):
        path = Path(value)
        raw = path.read_bytes()
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise CodexTransportSchemaError(f"canonical schema {path} must be a JSON object")
        return loaded, str(path), _sha256_bytes(raw)
    loaded = copy.deepcopy(dict(value))
    if not isinstance(loaded, dict):  # defensive; Mapping is the public type
        raise CodexTransportSchemaError("canonical schema must be a JSON object")
    return loaded, None, _schema_hash(loaded)


def _record(
    records: list[JsonObject],
    *,
    path: str,
    keyword: str,
    action: str,
    reason: str,
    replacement: str | None = None,
) -> None:
    entry: JsonObject = {"path": path, "keyword": keyword, "action": action, "reason": reason}
    if replacement is not None:
        entry["replacement"] = replacement
    records.append(entry)


def _walk_omitted_subtree(value: Any, path: str, records: list[JsonObject], reason: str) -> None:
    """Record all schema keywords lost with an omitted conditional branch."""
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_omitted_subtree(nested, f"{path}[{index}]", records, reason)
        return
    if not isinstance(value, dict):
        return
    for key, nested in value.items():
        child_path = f"{path}.{key}"
        _record(records, path=child_path, keyword=key, action="omitted", reason=reason)
        _walk_omitted_subtree(nested, child_path, records, reason)
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_omitted_subtree(nested, f"{path}[{index}]", records, reason)


def _path_for_property(parent: str, name: str) -> str:
    # Schema property names in this repository are identifier-like.  Keeping
    # the path readable is more useful in sidecars than JSON Pointer escaping.
    return f"{parent}.properties.{name}"


def _merge_enum(left: Any, right: Any) -> Any:
    if isinstance(left, list) and isinstance(right, list):
        return [value for value in left if value in right]
    return left


def _enum_constraint_intersection(
    *nodes: Mapping[str, Any],
) -> tuple[bool, list[Any]]:
    """Return every visible enum constraint's conjunction without mutation.

    Structural ``allOf`` branches are projected into ``working`` before the
    ordinary node is processed.  A later ``const`` must therefore inspect
    both that projected node and the raw/partially-built ordinary node; using
    only ``value`` loses an enum that originated in ``allOf``.
    """

    constraints: list[list[Any]] = []
    for node in nodes:
        if "enum" not in node:
            continue
        enum = node["enum"]
        if not isinstance(enum, list):
            # The canonical schema is invalid, but an empty conjunction is
            # safer than accidentally widening a malformed constraint.
            return True, []
        constraints.append(enum)

    if not constraints:
        return False, []

    intersection = copy.deepcopy(constraints[0])
    for constraint in constraints[1:]:
        intersection = [candidate for candidate in intersection if candidate in constraint]
    return True, intersection


def _merge_structural_nodes(
    left: JsonObject,
    right: JsonObject,
    *,
    path: str,
    records: list[JsonObject],
) -> JsonObject:
    """Merge already-projected structural allOf branches deterministically."""
    result = copy.deepcopy(left)
    for key, right_value in right.items():
        if key not in result:
            result[key] = copy.deepcopy(right_value)
            continue
        left_value = result[key]
        key_path = f"{path}.{key}"
        if key == "properties" and isinstance(left_value, dict) and isinstance(right_value, dict):
            merged_properties = copy.deepcopy(left_value)
            for name, property_schema in right_value.items():
                property_path = _path_for_property(path, name)
                if name not in merged_properties:
                    merged_properties[name] = copy.deepcopy(property_schema)
                elif merged_properties[name] != property_schema:
                    merged_properties[name] = _merge_structural_nodes(
                        merged_properties[name],
                        property_schema,
                        path=property_path,
                        records=records,
                    )
            result[key] = merged_properties
        elif key == "$defs" and isinstance(left_value, dict) and isinstance(right_value, dict):
            merged_defs = copy.deepcopy(left_value)
            for name, definition in right_value.items():
                definition_path = f"{path}.$defs.{name}"
                if name not in merged_defs:
                    merged_defs[name] = copy.deepcopy(definition)
                elif merged_defs[name] != definition:
                    merged_defs[name] = _merge_structural_nodes(
                        merged_defs[name], definition, path=definition_path, records=records
                    )
            result[key] = merged_defs
        elif key == "required" and isinstance(left_value, list) and isinstance(right_value, list):
            # Preserve source order and append newly required properties in
            # the order they occur in the structural branch.
            result[key] = list(left_value)
            result[key].extend(value for value in right_value if value not in result[key])
        elif key == "enum":
            result[key] = _merge_enum(left_value, right_value)
        elif key == "additionalProperties" and left_value != right_value:
            # In an allOf intersection, false is the safe structural result.
            if left_value is False or right_value is False:
                result[key] = False
            else:
                _record(
                    records,
                    path=key_path,
                    keyword=key,
                    action="relaxed",
                    reason="conflicting allOf additionalProperties values cannot be represented as one transport node",
                )
        elif key == "type" and left_value != right_value:
            _record(
                records,
                path=key_path,
                keyword=key,
                action="relaxed",
                reason="conflicting allOf type values cannot be represented as one transport node",
            )
        elif left_value != right_value:
            # A structural allOf with a non-mergeable conflict is still
            # emitted without the unsupported composition.  Keep the first
            # definition and make the loss explicit.
            _record(
                records,
                path=key_path,
                keyword=key,
                action="relaxed",
                reason="conflicting allOf definitions retained the first deterministic definition",
            )
    return result


def _project_node(value: Any, path: str, records: list[JsonObject], *, root: bool = False) -> Any:
    if isinstance(value, list):
        return [_project_node(nested, f"{path}[{index}]", records) for index, nested in enumerate(value)]
    if not isinstance(value, dict):
        return copy.deepcopy(value)

    # First project structural allOf branches so flattening has no unsupported
    # children left in the merged result.
    working: JsonObject = {}
    all_of = value.get("allOf")
    if isinstance(all_of, list):
        for index, branch in enumerate(all_of):
            branch_path = f"{path}.allOf[{index}]"
            if not isinstance(branch, dict):
                _record(
                    records,
                    path=branch_path,
                    keyword="allOf",
                    action="omitted",
                    reason="non-object allOf branch cannot be safely flattened",
                )
                continue
            conditional_keys = [key for key in ("if", "then", "else") if key in branch]
            if conditional_keys:
                _record(
                    records,
                    path=path,
                    keyword="allOf",
                    action="relaxed",
                    reason="conditional allOf composition is enforced only by canonical validation",
                )
                for key in conditional_keys:
                    _record(
                        records,
                        path=f"{branch_path}.{key}",
                        keyword=key,
                        action="omitted",
                        reason="conditional constraint is not representable in the Codex transport subset",
                    )
                    _walk_omitted_subtree(
                        branch[key],
                        f"{branch_path}.{key}",
                        records,
                        "conditional constraint is not representable in the Codex transport subset",
                    )
                unconditional = {key: nested for key, nested in branch.items() if key not in conditional_keys}
                if unconditional:
                    projected = _project_node(unconditional, branch_path, records)
                    if isinstance(projected, dict):
                        working = _merge_structural_nodes(working, projected, path=path, records=records)
                continue
            projected_branch = _project_node(branch, branch_path, records)
            if isinstance(projected_branch, dict):
                working = _merge_structural_nodes(working, projected_branch, path=path, records=records)
        _record(
            records,
            path=path,
            keyword="allOf",
            action="rewritten",
            replacement="flattened structural branches / omitted conditional branches",
            reason="Codex Structured Outputs does not permit allOf",
        )
    elif "allOf" in value:
        _record(
            records,
            path=f"{path}.allOf",
            keyword="allOf",
            action="omitted",
            reason="malformed allOf value cannot be safely flattened",
        )

    base: JsonObject = {}
    for key, original in value.items():
        if key == "allOf":
            continue
        child_path = f"{path}.{key}"
        if key in {"if", "then", "else", "not", "dependentRequired", "dependentSchemas"}:
            _record(
                records,
                path=child_path,
                keyword=key,
                action="omitted",
                reason="keyword is not representable in the Codex Structured Outputs subset",
            )
            _walk_omitted_subtree(original, child_path, records, "keyword is not representable in the Codex Structured Outputs subset")
            continue
        if key == "anyOf" and root:
            _record(
                records,
                path=child_path,
                keyword=key,
                action="omitted",
                reason="Codex Structured Outputs root schemas may not use anyOf",
            )
            continue
        if key == "oneOf":
            # Keep branch shape coverage while explicitly recording that
            # oneOf's exclusivity is relaxed to supported anyOf.
            projected = _project_node(original, child_path, records)
            if not root:
                base["anyOf"] = projected
            _record(
                records,
                path=child_path,
                keyword=key,
                action="rewritten",
                replacement="anyOf",
                reason="Codex supports anyOf but not oneOf; exclusivity is canonical-only",
            )
            continue
        if key in UNSUPPORTED_SCHEMA_KEYWORDS:
            _record(
                records,
                path=child_path,
                keyword=key,
                action="omitted",
                reason="keyword is not representable in the Codex Structured Outputs subset",
            )
            continue
        if key not in SUPPORTED_SCHEMA_KEYWORDS and key not in {"const", "definitions"}:
            _record(
                records,
                path=child_path,
                keyword=key,
                action="omitted",
                reason="keyword is outside the Codex Structured Outputs schema subset",
            )
            continue
        if key == "const":
            has_enum, existing = _enum_constraint_intersection(working, value, base)
            if has_enum:
                # Intersecting an existing enum with const preserves the
                # conjunction exactly.  The enum may have come from an
                # allOf branch (working), the raw ordinary node (value), or
                # an earlier ordinary key (base).
                base["enum"] = [original] if original in existing else []
                _record(
                    records,
                    path=child_path,
                    keyword=key,
                    action="rewritten",
                    replacement="enum",
                    reason="const represented as an exact singleton enum",
                )
            else:
                base["enum"] = [copy.deepcopy(original)]
                _record(
                    records,
                    path=child_path,
                    keyword=key,
                    action="rewritten",
                    replacement="enum",
                    reason="const represented as an exact singleton enum",
                )
            continue
        if key == "definitions":
            projected = _project_node(original, child_path, records)
            base["$defs"] = projected
            _record(
                records,
                path=child_path,
                keyword=key,
                action="rewritten",
                replacement="$defs",
                reason="legacy definitions alias normalized to supported $defs",
            )
            continue
        if key == "$ref" and isinstance(original, str) and original.startswith("#/definitions/"):
            base[key] = "#/$defs/" + original[len("#/definitions/") :]
            _record(
                records,
                path=child_path,
                keyword=key,
                action="rewritten",
                replacement="#/$defs/",
                reason="reference target follows definitions normalization",
            )
            continue
        if key == "additionalProperties" and isinstance(value.get("type"), (str, list)):
            if original is not False:
                base[key] = False
                _record(
                    records,
                    path=child_path,
                    keyword=key,
                    action="rewritten",
                    replacement="false",
                    reason="Codex Structured Outputs requires additionalProperties:false on every object",
                )
            else:
                base[key] = False
            continue
        if key in {"properties", "$defs", "definitions"} and isinstance(original, dict):
            if key == "$defs":
                base[key] = {
                    name: _project_node(nested, f"{child_path}.{name}", records)
                    for name, nested in original.items()
                }
            else:
                base[key] = {
                    name: _project_node(nested, _path_for_property(path, name), records)
                    for name, nested in original.items()
                }
            continue
        base[key] = _project_node(original, child_path, records)

    # Merge the ordinary node after its allOf branches.  This retains every
    # non-conflicting property definition from structural composition instead
    # of allowing the base ``properties`` object to overwrite the flattened
    # branches.
    working = _merge_structural_nodes(working, base, path=path, records=records)

    # Object schemas must explicitly close their property set.  This also
    # handles canonical map-like objects whose semantic openness is later
    # checked by canonical validation.
    if working.get("type") == "object" or ("properties" in working and "type" not in working):
        if "type" not in working:
            working["type"] = "object"
            _record(
                records,
                path=path,
                keyword="type",
                action="rewritten",
                replacement="object",
                reason="object-shaped node requires an explicit Codex transport type",
            )
        if working.get("additionalProperties") is not False:
            working["additionalProperties"] = False
            _record(
                records,
                path=f"{path}.additionalProperties",
                keyword="additionalProperties",
                action="rewritten" if "additionalProperties" in working else "added",
                replacement="false",
                reason="Codex Structured Outputs requires additionalProperties:false on every object",
            )
        if "properties" not in working:
            working["properties"] = {}
            _record(
                records,
                path=f"{path}.properties",
                keyword="properties",
                action="added",
                reason="explicit empty properties map makes a closed empty object unambiguous to Codex",
            )
        properties = working.get("properties")
        if isinstance(properties, dict):
            current_required = working.get("required")
            required: list[str] = []
            if isinstance(current_required, list):
                for name in current_required:
                    if name in properties:
                        if name not in required:
                            required.append(name)
                    else:
                        _record(
                            records,
                            path=f"{path}.required",
                            keyword="required",
                            action="omitted",
                            replacement="property must be declared",
                            reason="Codex requires every required name to have a corresponding property definition",
                        )
            for name, property_schema in properties.items():
                if name not in required:
                    required.append(name)
                    _record(
                        records,
                        path=f"{path}.required",
                        keyword="required",
                        action="rewritten",
                        replacement=name,
                        reason="Codex Structured Outputs requires every declared object property",
                    )
                    if isinstance(property_schema, dict):
                        _make_nullable(property_schema, _path_for_property(path, name), records)
            working["required"] = required
    if root and working.get("type") != "object":
        raise CodexTransportSchemaError("Codex transport schema root must be an object")
    return working


def _make_nullable(schema: JsonObject, path: str, records: list[JsonObject]) -> None:
    """Preserve an optional canonical property after making it required."""
    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type != "null":
        schema["type"] = [schema_type, "null"]
    elif isinstance(schema_type, list) and "null" not in schema_type:
        schema["type"] = list(schema_type) + ["null"]
    elif schema_type is None and "anyOf" in schema and isinstance(schema["anyOf"], list):
        schema["anyOf"] = list(schema["anyOf"]) + [{"type": "null"}]
    elif schema_type is None and "enum" in schema and isinstance(schema["enum"], list):
        if None not in schema["enum"]:
            schema["enum"] = list(schema["enum"]) + [None]
    else:
        return
    if "enum" in schema and isinstance(schema["enum"], list) and None not in schema["enum"]:
        schema["enum"] = list(schema["enum"]) + [None]
    _record(
        records,
        path=path,
        keyword="type",
        action="relaxed",
        replacement="nullable",
        reason="optional canonical property is required by Codex and null preserves its optional state",
    )


def codex_transport_schema_errors(schema: Mapping[str, Any]) -> list[str]:
    """Check the local invariants that must hold before invoking Codex."""
    errors: list[str] = []

    def walk(value: Any, path: str, *, root: bool = False) -> None:
        if isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")
            return
        if not isinstance(value, dict):
            return
        for key in value:
            if key in UNSUPPORTED_SCHEMA_KEYWORDS or key == "const":
                errors.append(f"{path}.{key}: unsupported keyword remains")
            if key not in SUPPORTED_SCHEMA_KEYWORDS and key not in {"const", "definitions"}:
                errors.append(f"{path}.{key}: unsupported keyword remains")
        if root and value.get("type") != "object":
            errors.append("$: root type must be object")
        object_typed = value.get("type") == "object" or (
            isinstance(value.get("type"), list) and "object" in value["type"]
        )
        if object_typed:
            if value.get("additionalProperties") is not False:
                errors.append(f"{path}.additionalProperties: must be false")
            properties = value.get("properties", {})
            required = value.get("required", [])
            if isinstance(properties, dict) and (
                not isinstance(required, list) or set(properties) - set(required)
            ):
                errors.append(f"{path}.required: every property must be required")
        for key, nested in value.items():
            if key in {"properties", "$defs", "definitions"} and isinstance(nested, dict):
                # These are maps from names to schema nodes; the map keys are
                # identifiers, not JSON Schema keywords.
                for name, property_schema in nested.items():
                    walk(property_schema, f"{path}.{key}.{name}")
            elif key in {"items", "additionalProperties"} and isinstance(nested, dict):
                walk(nested, f"{path}.{key}")
            elif key in {"anyOf", "oneOf"} and isinstance(nested, list):
                for index, schema_node in enumerate(nested):
                    walk(schema_node, f"{path}.{key}[{index}]")
        if root and "anyOf" in value:
            errors.append("$.anyOf: root anyOf is not supported")

    walk(schema, "$", root=True)
    return sorted(set(errors))


def _resolve_local_ref(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return schema
    current: Any = root
    for component in reference[2:].split("/"):
        if not isinstance(current, Mapping):
            return schema
        current = current.get(component.replace("~1", "/").replace("~0", "~"))
    return current if isinstance(current, Mapping) else schema


def _property_schema(schema: Mapping[str, Any], name: str, root: Mapping[str, Any]) -> Mapping[str, Any] | None:
    resolved = _resolve_local_ref(schema, root)
    properties = resolved.get("properties")
    if isinstance(properties, Mapping) and isinstance(properties.get(name), Mapping):
        return properties[name]
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = resolved.get(keyword)
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, Mapping):
                    found = _property_schema(branch, name, root)
                    if found is not None:
                        return found
    return None


def _schema_allows_null(schema: Mapping[str, Any], root: Mapping[str, Any]) -> bool:
    resolved = _resolve_local_ref(schema, root)
    schema_type = resolved.get("type")
    if schema_type == "null" or (isinstance(schema_type, list) and "null" in schema_type):
        return True
    enum = resolved.get("enum")
    if isinstance(enum, list) and None in enum:
        return True
    any_of = resolved.get("anyOf")
    if isinstance(any_of, list):
        return any(isinstance(branch, Mapping) and _schema_allows_null(branch, root) for branch in any_of)
    return False


def _strip_transport_nulls(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any]) -> Any:
    """Undo only the nullable encoding used for canonical-optional fields."""
    resolved = _resolve_local_ref(schema, root)
    if isinstance(value, dict):
        required = resolved.get("required")
        required_names = set(required) if isinstance(required, list) else set()
        for name in list(value):
            child_schema = _property_schema(resolved, name, root)
            if (
                value[name] is None
                and child_schema is not None
                and name not in required_names
                and not _schema_allows_null(child_schema, root)
            ):
                del value[name]
                continue
            if child_schema is not None:
                value[name] = _strip_transport_nulls(value[name], child_schema, root)
        return value
    if isinstance(value, list):
        items = resolved.get("items")
        if isinstance(items, Mapping):
            return [_strip_transport_nulls(item, items, root) for item in value]
    return value


def normalize_codex_output_for_canonical(value: Any, canonical_schema: SchemaInput) -> Any:
    """Remove Codex-only nulls before the caller runs canonical validation.

    Structured Outputs requires canonical-optional properties to be present,
    so the transport schema encodes them as nullable.  A model may choose the
    null branch; converting that branch back to omission is a transport
    normalization, not contract validation, and conditional canonical rules
    still run unchanged afterward.
    """
    source, _, _ = _load_input(canonical_schema)
    return _strip_transport_nulls(copy.deepcopy(value), source, source)


def build_codex_transport_artifact(
    canonical_schema: SchemaInput,
    *,
    canonical_schema_path: Path | str | None = None,
) -> CodexTransportBuild:
    """Return a transport schema plus deterministic provenance.

    ``canonical_schema`` may be a path or an in-memory mapping.  When a
    derived pre-projection is supplied by a caller (for example the blinded
    Reviewer shape), ``canonical_schema_path`` identifies the original
    canonical file whose hash remains the contract identity.
    """
    source, source_path, source_hash = _load_input(canonical_schema)
    canonical_path = str(canonical_schema_path) if canonical_schema_path is not None else source_path
    if canonical_schema_path is not None:
        canonical_file = Path(canonical_schema_path)
        canonical_raw = canonical_file.read_bytes()
        source_hash = _sha256_bytes(canonical_raw)
    records: list[JsonObject] = []
    transport = _project_node(source, "$", records, root=True)
    if not isinstance(transport, dict):
        raise CodexTransportSchemaError("Codex transport schema must be a JSON object")
    compatibility_errors = codex_transport_schema_errors(transport)
    if compatibility_errors:
        raise CodexTransportSchemaError("; ".join(compatibility_errors))
    # Stable deduplication protects provenance from duplicate merge paths while
    # preserving the deterministic traversal order.
    unique: list[JsonObject] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for entry in records:
        key = (entry["path"], entry["keyword"], entry["action"], entry.get("replacement"))
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    provenance: JsonObject = {
        "canonical_schema_path": canonical_path,
        "canonical_schema_hash": source_hash,
        "transport_schema_hash": _schema_hash(transport),
        "removed_or_relaxed_keywords": unique,
        "provider": "codex",
        "canonical_validation_still_required": True,
    }
    return CodexTransportBuild(schema=transport, provenance=provenance)


def build_codex_transport_schema(
    canonical_schema: SchemaInput,
    *,
    canonical_schema_path: Path | str | None = None,
) -> JsonObject:
    """Build only the Codex transport schema from a canonical schema.

    Use :func:`build_codex_transport_artifact` when provenance is also needed.
    The returned object is a fresh deep projection; the source is never
    mutated.
    """
    return build_codex_transport_artifact(
        canonical_schema,
        canonical_schema_path=canonical_schema_path,
    ).schema


__all__ = [
    "CodexTransportBuild",
    "CodexTransportSchemaError",
    "build_codex_transport_artifact",
    "build_codex_transport_schema",
    "codex_transport_schema_errors",
    "normalize_codex_output_for_canonical",
]
