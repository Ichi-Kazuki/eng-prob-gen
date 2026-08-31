"""Stable Structure v0.1 artifact hashes and runtime provenance serialization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from shared.json_io import canonical_json_sha256
from runtime.adapters import InvocationResult


def _path(value: Path | None) -> str | None:
    return None if value is None else str(value)


def invocation_record(invocation: InvocationResult) -> dict[str, Any]:
    """Serialize runtime facts without serializing private prompt content."""

    return {
        "stage": invocation.stage,
        "agent_name": invocation.agent_name,
        "invocation_id": invocation.invocation_id,
        "provider": invocation.provider,
        "model": invocation.model,
        "cli_version": invocation.cli_version,
        "started_at": invocation.started_at,
        "completed_at": invocation.completed_at,
        "exit_code": invocation.exit_code,
        "error_category": invocation.error_category,
        "error_detail": invocation.error_detail,
        "input_keys": list(invocation.input_keys),
        "raw_stdout_path": _path(invocation.raw_stdout_path),
        "raw_stderr_path": _path(invocation.raw_stderr_path),
        "output_last_message_path": _path(invocation.output_last_message_path),
        "transport_schema_path": _path(invocation.transport_schema_path),
        "transport_schema_provenance_path": _path(invocation.transport_schema_provenance_path),
        "disabled_mcp_servers": list(invocation.disabled_mcp_servers),
        "config_isolation_mode": invocation.config_isolation_mode,
        "mcp_servers_exposed": list(invocation.mcp_servers_exposed),
        "mcp_servers_loaded": list(invocation.mcp_servers_loaded),
        "mcp_configuration_source": invocation.mcp_configuration_source,
        "user_config_loaded": invocation.user_config_loaded,
        "global_codex_config_bypassed": invocation.global_codex_config_bypassed,
        "auth_material_source": invocation.auth_material_source,
    }


def artifact_hashes(artifacts: dict[str, Any]) -> dict[str, str]:
    return {name: canonical_json_sha256(value) for name, value in artifacts.items()}


def logical_invocation_counts(invocations: Iterable[InvocationResult]) -> dict[str, int]:
    counts = {"generator": 0, "reviewer": 0, "solver": 0}
    for invocation in invocations:
        stage = invocation.stage.rsplit("_", 1)[-1]
        if stage in counts:
            counts[stage] += 1
    return counts
