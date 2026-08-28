#!/usr/bin/env python3
"""Run the WE Generator v2.1.3 -> Reviewer v2 -> Solver -> Orchestrator smoke.

This driver is deliberately an integration harness, not a second Generator,
Reviewer, Solver, or grammar implementation. It invokes the checked-in agent
instructions through a provider-neutral runtime adapter, keeps Reviewer/Solver
inputs on explicit allowlists, delegates formal validation to the existing
validators, and delegates routing/consensus to the existing Orchestrator
engine. Set ``WE_E2E_RUNTIME=codex`` for Codex CLI or leave it unset to retain
the existing Claude Code CLI behavior.

The WE v2 pipeline is a compatibility harness, not the production accepted-item
finalizer. Its `ACCEPTED` outcome is recorded as a live consensus metric only;
it must not be passed to ``orchestrator.build_accepted_item()``.

The WE Generator is schema-checked and finalization-integrity-checked at the
stage boundary.  Its v2.1.3 production validator additionally requires an
out-of-band grammar evidence artifact; no such artifact is fabricated by this
smoke.  Grammar quality is independently exercised by the live Reviewer, as
requested.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "runs" / "we_v2_1_3_live_e2e"
if os.environ.get("WE_E2E_OUTPUT_DIR"):
    configured_out = Path(os.environ["WE_E2E_OUTPUT_DIR"])
    OUT = configured_out if configured_out.is_absolute() else ROOT / configured_out
RUNTIME = OUT / "runtime"
FORMAL = RUNTIME / "formal"
PROVENANCE = RUNTIME / "provenance"
INPUTS = RUNTIME / "inputs"
LOGS = RUNTIME / "logs"

sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))
import orchestrator as orch  # noqa: E402

from shared.schema_validation import load_schema, schema_errors  # noqa: E402
from shared.json_io import atomic_write_json  # noqa: E402
from shared.reviewer_blinding import (  # noqa: E402
    canonical_reviewer_input,
    reviewer_allowlist,
    reviewer_input_errors,
    reviewer_input_sha256,
)
from shared.solver_blinding import (  # noqa: E402
    WRITTEN_EXPRESSION_ALLOWLIST,
    canonical_solver_input,
)
from runtime.adapters import (  # noqa: E402
    AgentRuntime,
    ClaudeRuntime,
    CodexRuntime,
    InvocationRequest,
    InvocationResult,
    RuntimeInvocationError,
    SandboxMode,
)
from runtime.freeze import (  # noqa: E402
    FreezeDriftError,
    RunFreeze,
    create_run_freeze,
    load_run_freeze,
    sha256_file,
    verify_detached_worktree,
)


GENERATOR_AGENT = "toefl-itp-we-generator-v2"
REVIEWER_AGENT = "toefl-itp-we-reviewer-v2"
SOLVER_AGENT = "toefl-itp-grammar-solver"
MODEL = os.environ.get("WE_E2E_MODEL", "sonnet")
CLI_TIMEOUT_SECONDS = int(os.environ.get("WE_E2E_TIMEOUT_SECONDS", "300"))
PER_CALL_BUDGET = os.environ.get("WE_E2E_MAX_BUDGET_USD", "0.60")
GENERATOR_VALIDATION_RETRIES = int(os.environ.get("WE_E2E_GENERATOR_VALIDATION_RETRIES", "2"))

GENERATOR_AGENT_PATH = ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md"
REVIEWER_AGENT_PATH = ROOT / ".claude" / "agents" / "toefl-itp-we-reviewer-v2.md"
SOLVER_AGENT_PATH = ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md"

GENERATOR_SCHEMA_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json"
REVIEWER_SCHEMA_PATH = ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "schema" / "reviewer_output_v2.schema.json"
SOLVER_SCHEMA_PATH = ROOT / "agents" / "toefl_itp_grammar_solver" / "schema" / "solver_output.schema.json"
GENERATOR_VALIDATOR = "agents/toefl_itp_we_generator_v2/scripts/validate_output.py"
REVIEWER_VALIDATOR = "agents/toefl_itp_we_reviewer_v2/scripts/validate_output.py"
SOLVER_VALIDATOR = "agents/toefl_itp_grammar_solver/scripts/validate_output.py"

REVIEWER_REQUIRED = {
    "item_id", "section", "agent_version", "verdict", "critical_failure",
    "independent_answer", "grammar_validity", "format_validity",
    "detected_error_count", "detected_error_position", "non_error_parts_valid",
    "minimal_correction_valid", "marked_part_assessments", "checks", "issues",
    "revision_requirements", "source_similarity_risk", "provenance",
}
REVIEWER_POST_STAGE_KEYS = {"generator_answer", "answer_match"}
REVIEWER_LIVE_REQUIRED = REVIEWER_REQUIRED - REVIEWER_POST_STAGE_KEYS
REVIEWER_DEFERRED_POST_BLIND_CHECKS = {"target_metadata"}
REVIEWER_FORBIDDEN_OUTPUT_KEYS = {
    "correct_answer", "intended_answer", "mutation_metadata", "generation_plan",
    "answer_explanation", "error_explanation", "minimal_correction",
    "primary_target", "subtype", "secondary_features", "tested_error_type",
    "difficulty", "error_scope", "grammar_metadata", "qa_metadata",
}
SOLVER_FORBIDDEN_FIELDS = {
    "correct_answer", "intended_answer", "mutation_metadata", "generation_plan",
    "answer_explanation", "error_explanation", "minimal_correction",
    "primary_target", "subtype", "secondary_features", "tested_error_type",
    "difficulty", "error_scope", "grammar_metadata", "format_metadata",
    "qa_metadata", "verdict", "independent_answer", "checks",
}
FORMAL_OUTPUT_PATHS = {
    "generator": "runtime/formal/generator_outputs.json",
    "reviewer": "runtime/formal/reviewer_outputs.json",
    "solver": "runtime/formal/solver_outputs.json",
}
LIVE_FAILURE_CATEGORIES = {
    "HARNESS_TIMEOUT",
    "NETWORK_ERROR",
    "AUTH_ERROR",
    "SCHEMA_COMPATIBILITY_ERROR",
    "PROCESS_ERROR",
    "CONTRACT_VALIDATION_ERROR",
    "MODEL_OUTPUT_ERROR",
    "INFRASTRUCTURE_ERROR",
    "SUCCESS",
}

ARTIFACT_MANIFEST_VERSION = 1
ARTIFACT_MANIFEST_FILENAME = "artifact_manifest_v1.json"
EVIDENCE_ARTIFACTS = (
    "runtime/formal/generator_outputs.json",
    "runtime/formal/reviewer_outputs.json",
    "runtime/formal/solver_outputs.json",
    "runtime/provenance/runtime_provenance.json",
    "runtime/outcomes.json",
    "runtime/test_result.json",
    "runtime/freeze/freeze_manifest.json",
)
OFFLINE_TEST_TIMEOUT_SECONDS = 300


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _artifact_manifest_path() -> Path:
    return OUT / "runtime" / ARTIFACT_MANIFEST_FILENAME


def _outcomes_path() -> Path:
    return OUT / "runtime" / "outcomes.json"


def _test_result_path() -> Path:
    return OUT / "runtime" / "test_result.json"


def _freeze_manifest_path() -> Path:
    return OUT / "runtime" / "freeze" / "freeze_manifest.json"


def _artifact_manifest_payload(freeze: RunFreeze) -> dict[str, Any]:
    files: dict[str, dict[str, str]] = {}
    for relative in EVIDENCE_ARTIFACTS:
        path = OUT / Path(relative)
        if not path.is_file():
            raise FileNotFoundError(f"required immutable evidence artifact is missing: {path}")
        files[relative] = {"sha256": sha256_file(path)}
    payload: dict[str, Any] = {
        "artifact_manifest_version": ARTIFACT_MANIFEST_VERSION,
        "freeze_manifest_sha256": freeze.manifest_sha256,
        "files": dict(sorted(files.items())),
    }
    payload["artifact_manifest_sha256"] = sha256_json(payload)
    return payload


def write_artifact_manifest(freeze: RunFreeze) -> None:
    """Publish a deterministic hash set for the immutable report evidence."""

    freeze.verify("before", "artifact_manifest")
    atomic_write_json(_artifact_manifest_path(), _artifact_manifest_payload(freeze))
    freeze.verify("after", "artifact_manifest")


def _read_json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} cannot be read as JSON: {exc}") from exc


def verify_artifact_manifest(freeze: RunFreeze) -> None:
    """Fail closed when the evidence sidecar or any listed artifact changed."""

    path = _artifact_manifest_path()
    document = _read_json_file(path, "artifact manifest")
    if not isinstance(document, dict):
        raise ValueError("artifact manifest must be a JSON object")
    if document.get("artifact_manifest_version") != ARTIFACT_MANIFEST_VERSION:
        raise ValueError("unsupported artifact manifest version")
    recorded_hash = document.get("artifact_manifest_sha256")
    unsigned = copy.deepcopy(document)
    unsigned.pop("artifact_manifest_sha256", None)
    if recorded_hash != sha256_json(unsigned):
        raise ValueError("artifact manifest SHA-256 does not match its contents")
    if document.get("freeze_manifest_sha256") != freeze.manifest_sha256:
        raise ValueError("artifact manifest is bound to a different freeze manifest")

    files = document.get("files")
    if not isinstance(files, dict) or set(files) != set(EVIDENCE_ARTIFACTS):
        raise ValueError("artifact manifest does not contain the exact required evidence set")
    base = OUT.resolve()
    for relative in EVIDENCE_ARTIFACTS:
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"artifact manifest contains an unsafe path: {relative!r}")
        info = files.get(relative)
        expected = info.get("sha256") if isinstance(info, dict) else None
        candidate = (OUT / Path(relative)).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"artifact manifest path escapes output directory: {relative!r}") from exc
        if not isinstance(expected, str) or not candidate.is_file() or sha256_file(candidate) != expected:
            raise ValueError(f"immutable evidence artifact is missing or tampered: {relative}")


class LiveInvocationError(Exception):
    def __init__(self, category: str, detail: str):
        super().__init__(detail)
        self.category = category
        self.detail = detail
        self.invocation: InvocationResult | None = None


def _relative_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _elapsed_seconds(started_at: str, completed_at: str | None) -> float | None:
    if not completed_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        completed = datetime.fromisoformat(completed_at)
    except (TypeError, ValueError):
        return None
    return round((completed - started).total_seconds(), 6)


def _invocation_diagnostic(invocation: InvocationResult, error: LiveInvocationError | None) -> str:
    # Provider CLIs can echo the complete authoritative prompt and tool
    # transcript.  Classification must inspect the tail where CLI errors are
    # emitted, otherwise ordinary prompt words such as "network" can create a
    # false transport failure.
    parts = [invocation.raw_stderr[-8000:], invocation.raw_stdout[-4000:]]
    if error is not None:
        parts.append(error.detail)
    return "\n".join(part for part in parts if part).lower()


def _classify_invocation_failure(invocation: InvocationResult, error: LiveInvocationError | None) -> str | None:
    if error is None and invocation.error_category is None:
        return "SUCCESS"
    diagnostic = _invocation_diagnostic(invocation, error)
    if (
        invocation.error_category in {"CODEX_SCHEMA_COMPATIBILITY_ERROR", "SCHEMA_COMPATIBILITY_ERROR"}
        or (error is not None and error.category in {"CODEX_SCHEMA_COMPATIBILITY_ERROR", "SCHEMA_COMPATIBILITY_ERROR"})
        or "invalid_json_schema" in diagnostic
        or "invalid json schema" in diagnostic
    ):
        return "SCHEMA_COMPATIBILITY_ERROR"
    if (
        invocation.error_category in {"parsing", "MODEL_OUTPUT_ERROR"}
        or (error is not None and error.category in {"parsing", "MODEL_OUTPUT_ERROR"})
    ):
        return "MODEL_OUTPUT_ERROR"
    if (
        invocation.error_category == "CONTRACT_VALIDATION_ERROR"
        or (error is not None and error.category == "CONTRACT_VALIDATION_ERROR")
    ):
        return "CONTRACT_VALIDATION_ERROR"
    if (
        invocation.error_category in {"schema", "SCHEMA_ERROR"}
        or (error is not None and error.category in {"schema", "SCHEMA_ERROR"})
    ):
        return "CONTRACT_VALIDATION_ERROR"
    auth_tokens = ("unauthorized", "authentication", "api key", "invalid token", "login required", "not logged in")
    network_tokens = (
        "socket", "websocket", "dns", "econn", "connection refused", "connection reset",
        "stream disconnected", "failed to connect", "api.openai.com", "timed out waiting for network",
        "network is unreachable", "network error", "error sending request",
    )
    if any(token in diagnostic for token in auth_tokens):
        return "AUTH_ERROR"
    if any(token in diagnostic for token in network_tokens):
        return "NETWORK_ERROR"
    if invocation.exit_code is None:
        if "timeout" in diagnostic or "timed out" in diagnostic:
            return "HARNESS_TIMEOUT"
        return "PROCESS_ERROR"
    if invocation.exit_code != 0:
        return "PROCESS_ERROR"
    return "CONTRACT_VALIDATION_ERROR"


def _failure_source(invocation: InvocationResult, classification: str | None) -> str | None:
    if classification is None:
        return None
    if invocation.exit_code is None:
        detail = (invocation.error_detail or "").lower()
        if "timeout" in detail or "timed out" in detail:
            return "subprocess_timeout"
        return "subprocess_error"
    if classification == "CONTRACT_VALIDATION_ERROR":
        return "contract_validation"
    if classification == "SCHEMA_COMPATIBILITY_ERROR":
        return "transport_schema"
    return invocation.provider


def sidecar(
    invocation: InvocationResult,
    *,
    input_payload: Any,
    contract_validated: bool,
    formal_output_exists: bool,
    leakage: list[str],
    error: LiveInvocationError | None = None,
) -> dict:
    failure = None
    if error is not None:
        failure = {"category": error.category, "detail": error.detail}
    classification = _classify_invocation_failure(invocation, error)
    command = list(invocation.command)
    record = {
        "provider": invocation.provider,
        "runtime_provider": invocation.provider,
        "agent_identifier": invocation.agent_name,
        "cli_version": invocation.cli_version,
        "codex_cli_version": invocation.cli_version if invocation.provider == "codex" else None,
        "model": invocation.model,
        "model_identifier": invocation.model,
        "invocation_id": invocation.invocation_id,
        "timestamp": invocation.started_at,
        "invocation_timestamp": invocation.started_at,
        "completed_timestamp": invocation.completed_at,
        "start_timestamp": invocation.started_at,
        "end_timestamp": invocation.completed_at,
        "elapsed_seconds": _elapsed_seconds(invocation.started_at, invocation.completed_at),
        "requested_timeout_seconds": invocation.requested_timeout_seconds,
        "timeout_triggered_timestamp": invocation.timeout_triggered_at,
        "termination_start_timestamp": invocation.termination_started_at,
        "termination_end_timestamp": invocation.termination_completed_at,
        "termination_method": invocation.termination_method,
        "cleanup_duration_seconds": invocation.cleanup_duration_seconds,
        "total_elapsed_seconds": _elapsed_seconds(invocation.started_at, invocation.completed_at),
        "exit_code": invocation.exit_code,
        "process_exit_code": invocation.exit_code,
        "exact_command_argv": command,
        "exact_command": subprocess.list2cmdline(command) if command else None,
        "live_invocation": True,
        "contract_valid": contract_validated,
        "contract_validated": contract_validated,
        "formal_output_path": FORMAL_OUTPUT_PATHS.get(invocation.stage),
        "formal_output_exists": formal_output_exists,
        "stage": invocation.stage,
        "input_keys": invocation.input_keys,
        "input_payload_sha256": sha256_json(input_payload),
        "forbidden_input_fields_present": sorted(leakage),
        "raw_stdout_path": _relative_path(invocation.raw_stdout_path),
        "raw_stderr_path": _relative_path(invocation.raw_stderr_path),
        "output_last_message_path": _relative_path(invocation.output_last_message_path),
        "raw_output_log": _relative_path(invocation.raw_stdout_path),
        "transport_schema_path": _relative_path(invocation.transport_schema_path),
        "transport_schema_provenance_path": _relative_path(invocation.transport_schema_provenance_path),
        "transport_schema_provenance": copy.deepcopy(invocation.transport_schema_provenance),
        "disabled_mcp_servers": list(invocation.disabled_mcp_servers),
        "mcp_servers_exposed": list(invocation.mcp_servers_exposed),
        "mcp_servers_loaded": list(invocation.mcp_servers_loaded),
        "mcp_configuration_source": invocation.mcp_configuration_source,
        "user_config_loaded": invocation.user_config_loaded,
        "global_codex_config_bypassed": invocation.global_codex_config_bypassed,
        "auth_material_source": invocation.auth_material_source,
        "codex_home_source": invocation.codex_home_source,
        "codex_home_disposable": invocation.codex_home_disposable,
        "codex_home_cleaned": invocation.codex_home_cleaned,
        "freeze_manifest_path": _relative_path(_RUN_FREEZE.manifest_path) if _RUN_FREEZE is not None else None,
        "freeze_manifest_sha256": _RUN_FREEZE.manifest_sha256 if _RUN_FREEZE is not None else None,
    }
    if invocation.stage == "reviewer":
        record["deferred_post_blind_checks"] = sorted(REVIEWER_DEFERRED_POST_BLIND_CHECKS)
        record["target_metadata_origin"] = "deterministic_post_blind_comparison"
    if classification is not None:
        record["classification"] = classification
        if classification != "SUCCESS":
            record["failure_classification"] = classification
            record["failure_source"] = _failure_source(invocation, classification)
            record["provider_failure_category"] = (
                (error.category if error is not None else invocation.error_category)
            )
    if failure is not None:
        record["failure"] = failure
    elif invocation.error_category is not None:
        record["failure"] = {"category": invocation.error_category, "detail": invocation.error_detail}
    return record


_RUNTIME: AgentRuntime | None = None
_RUNTIME_MODEL_OVERRIDE: str | None = None
_RUN_FREEZE: RunFreeze | None = None


def _verify_freeze(phase: str, stage: str) -> None:
    if _RUN_FREEZE is not None:
        _RUN_FREEZE.verify(phase, stage)


def _schema_for_stage(stage: str, fallback: Path) -> Path:
    if _RUN_FREEZE is None:
        return fallback
    return _RUN_FREEZE.schema_snapshots.get(stage, fallback)


def _agent_definition_for_agent(agent: str, fallback: Path) -> Path:
    if _RUN_FREEZE is None:
        return fallback
    return _RUN_FREEZE.agent_snapshots.get(agent, fallback)


def _freeze_protected_files() -> dict[str, dict[str, Path]]:
    return {
        "generator": {
            "agent_definition": GENERATOR_AGENT_PATH,
            "canonical_schema": GENERATOR_SCHEMA_PATH,
            "validator": ROOT / GENERATOR_VALIDATOR,
            "mutation_safety": ROOT / "agents/toefl_itp_we_generator_v2/scripts/mutation_safety.py",
            "format_validator": ROOT / "agents/toefl_itp_we_generator_v2/scripts/validate_format.py",
            "format_planner": ROOT / "agents/toefl_itp_we_generator_v2/scripts/format_planner.py",
        },
        "reviewer": {
            "agent_definition": REVIEWER_AGENT_PATH,
            "canonical_schema": REVIEWER_SCHEMA_PATH,
            "validator": ROOT / REVIEWER_VALIDATOR,
        },
        "solver": {
            "agent_definition": SOLVER_AGENT_PATH,
            "canonical_schema": SOLVER_SCHEMA_PATH,
            "validator": ROOT / SOLVER_VALIDATOR,
        },
        "orchestrator": {
            "live_harness": Path(__file__).resolve(),
            "orchestrator": ROOT / "orchestrator/scripts/orchestrator.py",
            "driver_helpers": ROOT / "orchestrator/scripts/driver_helpers.py",
            "runtime_adapters": ROOT / "runtime/adapters.py",
            "codex_schema": ROOT / "runtime/codex_schema.py",
            "freeze_runtime": ROOT / "runtime/freeze.py",
            "schema_validation": ROOT / "shared/schema_validation.py",
            "reviewer_blinding": ROOT / "shared/reviewer_blinding.py",
            "solver_blinding": ROOT / "shared/solver_blinding.py",
            "config": ROOT / "orchestrator/config.json",
            "config_schema": ROOT / "orchestrator/schemas/config.schema.json",
        },
    }


def _create_run_freeze(
    runtime: AgentRuntime,
    *,
    model: str,
    reasoning_effort: str,
    sandbox: str,
    timeout_seconds: float,
) -> RunFreeze:
    return create_run_freeze(
        RUNTIME / "freeze",
        repo_root=ROOT,
        protected_file_groups=_freeze_protected_files(),
        canonical_schemas={
            "generator": GENERATOR_SCHEMA_PATH,
            "reviewer": REVIEWER_SCHEMA_PATH,
            "solver": SOLVER_SCHEMA_PATH,
        },
        agent_instructions={
            GENERATOR_AGENT: GENERATOR_AGENT_PATH,
            REVIEWER_AGENT: REVIEWER_AGENT_PATH,
            SOLVER_AGENT: SOLVER_AGENT_PATH,
        },
        provider=runtime.provider,
        codex_cli_version=runtime.cli_version,
        model=model,
        reasoning_effort=reasoning_effort,
        sandbox=sandbox,
        timeout_seconds=timeout_seconds,
    )


def _final_quality_pilot_preflight() -> None:
    """Require the explicitly selected immutable source architecture."""

    if os.environ.get("WE_E2E_FINAL_PILOT") != "1":
        return
    expected_commit = os.environ.get("WE_E2E_EXPECTED_COMMIT", "").strip()
    if not expected_commit:
        raise ValueError("WE_E2E_FINAL_PILOT=1 requires WE_E2E_EXPECTED_COMMIT")
    verify_detached_worktree(ROOT, expected_commit=expected_commit)
    if not OUT.is_absolute():
        raise ValueError("final quality pilot output directory must be absolute")
    try:
        OUT.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("final quality pilot output directory must be outside the source worktree")


def configure_runtime(
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> AgentRuntime:
    """Select a provider without changing any pipeline stage implementation."""

    global _RUNTIME, _RUNTIME_MODEL_OVERRIDE
    _RUNTIME_MODEL_OVERRIDE = model_override
    requested = (
        provider_override
        or os.environ.get("WE_E2E_RUNTIME", os.environ.get("WE_E2E_PROVIDER", "claude"))
    ).strip().lower()
    if requested in {"codex", "codex-cli"}:
        _RUNTIME = CodexRuntime(model=model_override or os.environ.get("WE_E2E_CODEX_MODEL"))
    elif requested in {"claude", "claude-code", "claude-code-cli"}:
        _RUNTIME = ClaudeRuntime(model=MODEL)
    else:
        raise ValueError(f"Unsupported live runtime provider: {requested!r}")
    return _RUNTIME


def current_runtime() -> AgentRuntime:
    if _RUNTIME is None:
        return configure_runtime()
    return _RUNTIME


def invoke(
    agent: str,
    stage: str,
    prompt: str,
    input_keys: list[str],
    tools: str,
    formal_schema_path: Path,
    transport_schema: dict | None = None,
    system_directive: str | None = None,
    *,
    reasoning_effort_override: str | None = None,
    sandbox_override: str | None = None,
    timeout_override: float | None = None,
) -> InvocationResult:
    agent_paths = {
        GENERATOR_AGENT: GENERATOR_AGENT_PATH,
        REVIEWER_AGENT: REVIEWER_AGENT_PATH,
        SOLVER_AGENT: SOLVER_AGENT_PATH,
    }
    if agent not in agent_paths:
        raise LiveInvocationError("infrastructure", f"No authoritative agent definition is configured for {agent!r}")
    runtime = current_runtime()
    live_sandbox = cast(
        SandboxMode | None,
        sandbox_override or ("read-only" if runtime.provider == "codex" else None),
    )
    request = InvocationRequest(
        stage=stage,
        agent_name=agent,
        agent_definition=_agent_definition_for_agent(agent, agent_paths[agent]),
        prompt=prompt,
        input_keys=tuple(input_keys),
        formal_output_schema=_schema_for_stage(stage, formal_schema_path),
        transport_output_schema=transport_schema,
        system_directive=system_directive,
        model=(
            MODEL
            if runtime.provider == "claude-code-cli"
            else (_RUNTIME_MODEL_OVERRIDE or os.environ.get("WE_E2E_CODEX_MODEL"))
        ),
        cwd=ROOT,
        # Codex has no Claude-style empty tools switch. A read-only isolated
        # workspace makes the Reviewer/Solver blind boundary enforceable even
        # if a Codex tool is selected by the model.
        sandbox=live_sandbox,
        tools=tools,
        max_budget_usd=PER_CALL_BUDGET if runtime.provider == "claude-code-cli" else None,
        timeout_seconds=timeout_override if timeout_override is not None else CLI_TIMEOUT_SECONDS,
        artifact_dir=LOGS,
        isolate_workspace=stage in {"reviewer", "solver"},
        reasoning_effort=(
            reasoning_effort_override
            if reasoning_effort_override is not None
            else os.environ.get("WE_E2E_CODEX_REASONING_EFFORT")
        ),
        freeze_guard=None,
    )
    if _RUN_FREEZE is not None:
        _RUN_FREEZE.verify("before", stage)
    try:
        result = runtime.invoke(request)
    except RuntimeInvocationError as exc:
        if _RUN_FREEZE is not None:
            _RUN_FREEZE.verify("after", stage)
        error = LiveInvocationError(exc.category, exc.detail)
        error.invocation = exc.result
        raise error from exc
    else:
        if _RUN_FREEZE is not None:
            _RUN_FREEZE.verify("after", stage)
        return result


def nested_forbidden(value: Any, forbidden: set[str], path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in forbidden:
                found.append(f"{path}.{key}")
            found.extend(nested_forbidden(nested, forbidden, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(nested_forbidden(nested, forbidden, f"{path}[{index}]"))
    return found


def validate_schema_only(item: dict, schema_path: Path, stage: str) -> tuple[bool, list[str]]:
    _verify_freeze("before", f"{stage}_schema_validation")
    errors = schema_errors(item, load_schema(schema_path))
    _verify_freeze("after", f"{stage}_schema_validation")
    return not errors, [f"{stage}: {error}" for error in errors]


_VALIDATOR_MODULES: dict[tuple[str, str | None], Any] = {}


def validate_existing_contract(item: dict, validator_path: str, stage: str) -> tuple[bool, list[str]]:
    """Run the stage's checked-in ``validate_contract()`` implementation."""
    _verify_freeze("before", f"{stage}_contract_validator_load")
    cache_key = (validator_path, _RUN_FREEZE.manifest_sha256 if _RUN_FREEZE is not None else None)
    module = _VALIDATOR_MODULES.get(cache_key)
    if module is None:
        path = ROOT / validator_path
        module_name = f"we_live_{stage}_validator"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return False, [f"{stage}: cannot load contract validator {path}"]
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATOR_MODULES[cache_key] = module
    _verify_freeze("after", f"{stage}_contract_validator_load")
    _verify_freeze("before", f"{stage}_contract_validation")
    errors = module.validate_contract(item)
    _verify_freeze("after", f"{stage}_contract_validation")
    return not errors, [f"{stage}: {error}" for error in errors]


def validate_generator_finalization(item: dict) -> tuple[bool, list[str]]:
    """Check the parsed formal Generator item before any Reviewer call."""

    validator_path = GENERATOR_VALIDATOR
    _verify_freeze("before", "generator_finalization_validator_load")
    cache_key = (validator_path, _RUN_FREEZE.manifest_sha256 if _RUN_FREEZE is not None else None)
    module = _VALIDATOR_MODULES.get(cache_key)
    if module is None:
        path = ROOT / validator_path
        module_name = "we_live_generator_finalization_validator"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return False, [f"generator: cannot load finalization validator {path}"]
        scripts_path = str(path.parent)
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATOR_MODULES[cache_key] = module
    _verify_freeze("after", "generator_finalization_validator_load")
    _verify_freeze("before", "generator_finalization_validation")
    errors = module.validate_finalization_integrity(item)
    _verify_freeze("after", "generator_finalization_validation")
    return not errors, [f"generator: {error}" for error in errors]


def _resolve_recorded_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def validate_frozen_run_contract(freeze: RunFreeze) -> tuple[str, dict, list]:
    """Validate every report input against the run-start frozen contract."""

    formal_paths = {
        "generator": FORMAL / "generator_outputs.json",
        "reviewer": FORMAL / "reviewer_outputs.json",
        "solver": FORMAL / "solver_outputs.json",
    }
    validator_paths = {
        "reviewer": REVIEWER_VALIDATOR,
        "solver": SOLVER_VALIDATOR,
    }
    formal_counts: dict[str, int] = {}
    generator_items_by_id: dict[str, dict] = {}
    for stage, path in formal_paths.items():
        _verify_freeze("before", f"report_{stage}_artifact")
        document = _read_json_file(path, f"{stage} formal output")
        if not isinstance(document, dict) or not isinstance(document.get("items"), list):
            raise ValueError(f"{stage} formal output must be an object with an items list")
        items = document["items"]
        formal_counts[stage] = len(items)
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"{stage} formal output item {index} is not an object")
            ok, errors = validate_schema_only(item, freeze.schema_snapshots[stage], stage)
            if not ok:
                raise ValueError("; ".join(errors))
            if stage == "generator":
                if isinstance(item.get("item_id"), str):
                    generator_items_by_id[item["item_id"]] = item
                ok, errors = validate_generator_finalization(item)
            else:
                ok, errors = validate_existing_contract(item, validator_paths[stage], stage)
                if stage == "reviewer":
                    reviewer_item_id = item.get("item_id")
                    if not isinstance(reviewer_item_id, str):
                        raise ValueError("reviewer formal item must contain a string item_id")
                    generator_item = generator_items_by_id.get(reviewer_item_id)
                    if generator_item is None:
                        raise ValueError(
                            f"reviewer formal item {item.get('item_id')!r} has no matching Generator item"
                        )
                    errors.extend(validate_reviewer_post_blind_consistency(item, generator_item))
                    ok = not errors
            if not ok:
                raise ValueError("; ".join(errors))
        _verify_freeze("after", f"report_{stage}_artifact")

    provenance_document = _read_json_file(PROVENANCE / "runtime_provenance.json", "runtime provenance")
    if not isinstance(provenance_document, dict) or not isinstance(provenance_document.get("items"), list):
        raise ValueError("runtime provenance must be an object with an items list")
    expected_manifest_path = freeze.manifest_path.resolve()
    expected_schema_hashes = freeze.manifest.get("canonical_schema_hashes", {})
    provenance_by_stage: dict[str, list[dict[str, Any]]] = {stage: [] for stage in formal_paths}
    for index, record in enumerate(provenance_document["items"]):
        if not isinstance(record, dict):
            raise ValueError(f"runtime provenance item {index} is not an object")
        if record.get("freeze_manifest_sha256") != freeze.manifest_sha256:
            raise ValueError(f"runtime provenance item {index} is not bound to the run freeze")
        if _resolve_recorded_path(record.get("freeze_manifest_path")) != expected_manifest_path:
            raise ValueError(f"runtime provenance item {index} points to a different freeze manifest")
        stage_value = record.get("stage")
        if not isinstance(stage_value, str) or stage_value not in formal_paths:
            raise ValueError(f"runtime provenance item {index} has an unknown stage")
        stage = stage_value
        provenance_by_stage[stage].append(record)
        transport_provenance = record.get("transport_schema_provenance")
        if isinstance(transport_provenance, dict) and "canonical_schema_hash" in transport_provenance:
            if transport_provenance.get("canonical_schema_hash") != expected_schema_hashes.get(stage):
                raise ValueError(f"runtime provenance item {index} uses a different canonical {stage} schema")
        if record.get("formal_output_exists") is True and record.get("formal_output_path") != FORMAL_OUTPUT_PATHS[stage]:
            raise ValueError(f"runtime provenance item {index} has an inconsistent formal output path")
    for stage in formal_paths:
        if formal_counts[stage]:
            if not any(record.get("formal_output_exists") is True for record in provenance_by_stage[stage]):
                raise ValueError(f"{stage} formal output is not represented by a successful provenance record")

    outcomes_document = _read_json_file(_outcomes_path(), "run outcomes")
    if not isinstance(outcomes_document, dict) or not isinstance(outcomes_document.get("outcomes"), list):
        raise ValueError("run outcomes must be an object with an outcomes list")
    batch_id = outcomes_document.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError("run outcomes must contain a non-empty batch_id")
    test_result = _read_json_file(_test_result_path(), "test result")
    if not isinstance(test_result, dict) or not isinstance(test_result.get("passed"), bool):
        raise ValueError("test result must contain a boolean passed field")
    _verify_freeze("after", "report_frozen_contract")
    return batch_id, test_result, outcomes_document["outcomes"]


def reviewer_runtime_schema(canonical_schema_path: Path | dict[str, Any] = REVIEWER_SCHEMA_PATH) -> dict:
    """The live Reviewer response contract, before Orchestrator comparison fields.

    The checked-in formal schema intentionally requires ``generator_answer``,
    ``answer_match``, and ``checks.target_metadata`` for the post-stage record.
    None is a blind Reviewer judgment: the first two are comparison fields and
    target metadata is deterministic Generator consistency.  The CLI receives
    a derived response schema that omits all three from the blind response.
    The formal checked-in schema itself is never edited.
    """
    schema = copy.deepcopy(
        canonical_schema_path
        if isinstance(canonical_schema_path, dict)
        else load_schema(canonical_schema_path)
    )
    schema["required"] = [
        key for key in schema.get("required", [])
        if key not in {"generator_answer", "answer_match"}
    ]
    schema.get("properties", {}).pop("generator_answer", None)
    schema.get("properties", {}).pop("answer_match", None)
    checks = schema.get("properties", {}).get("checks")
    if isinstance(checks, dict):
        required_checks = checks.get("required")
        if isinstance(required_checks, list):
            checks["required"] = [
                key for key in required_checks if key not in REVIEWER_DEFERRED_POST_BLIND_CHECKS
            ]
        properties = checks.get("properties")
        if isinstance(properties, dict):
            for key in REVIEWER_DEFERRED_POST_BLIND_CHECKS:
                properties.pop(key, None)
    return schema


def generator_prompt(item_id: str, order: int, batch_id: str) -> str:
    return f"""LIVE GENERATOR INVOCATION.

Follow the authoritative Generator instruction supplied by the runtime. Do
not copy an existing fixture and do not write files. Produce exactly one fresh
Written Expression Part B item for the frozen v2.1.3 runtime contract. The item_id
must be exactly {json.dumps(item_id)}; this is microbatch item {order} in batch
{json.dumps(batch_id)}. Return one JSON object only, matching the supplied
canonical Generator schema; do not use markdown or an items wrapper. Keep all
field names, enum values, nested shapes, sentence-first phases, format rules,
and mutation-safety rules from the authoritative instruction and schema.
"""


def generator_system_directive() -> str:
    return """The final response for this invocation MUST be exactly one JSON object matching the supplied output schema. Do not return analysis, phase notes, prose, markdown fences, an items wrapper, or any extra keys. The caller will reject non-contract output."""


def reviewer_prompt(candidate: dict) -> str:
    payload = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
    return f"""LIVE BLINDED REVIEWER INVOCATION.

Follow the authoritative Reviewer instruction supplied by the runtime, but
for this blind call use only the complete JSON candidate below. The candidate
contains exactly item_id, section, sentence, and marked_parts. Do not read
files, inspect other artifacts, infer or reconstruct any Generator answer,
intended answer, mutation metadata, generation plan, explanation, or Reviewer
judgment. Those withheld fields are not review failures.

Return one JSON object only using the live Reviewer response shape derived
from the canonical Reviewer schema. The post-stage Orchestrator will attach
generator_answer, answer_match, and the deterministic checks.target_metadata
result after this invocation; do not emit any of those fields. Do not emit
any other Generator fields or markdown.

BLINDED CANDIDATE:
{payload}
"""


def reviewer_system_directive() -> str:
    return """The final response for this invocation MUST be exactly one JSON object using only the supplied live Reviewer response schema keys. Use the exact keys and enum values in that schema. Do not return phase notes, alternate key names such as answer/candidate_answer, nested assessment objects, prose, markdown fences, Generator fields, generator_answer, answer_match, or checks.target_metadata. The caller will reject non-contract output."""


def solver_prompt(candidate: dict) -> str:
    payload = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
    return f"""LIVE BLINDED SOLVER INVOCATION.

Follow the authoritative Solver instruction supplied by the runtime. Solve
only the complete JSON object below; it is the only candidate input. Do not
read files, inspect other artifacts, or infer any Generator or Reviewer
judgment. Return one JSON object only matching the canonical Solver schema.
Do not include any field that is not allowed by that schema and do not use
markdown.

BLINDED SOLVER INPUT:
{payload}
"""


def solver_system_directive() -> str:
    return """The final response for this invocation MUST be exactly one JSON object matching the supplied Solver output schema. Do not return analysis, phase notes, prose, markdown fences, alternate key names, or any extra keys."""


def get_single_item(parsed: Any, stage: str) -> dict:
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        if len(parsed["items"]) != 1:
            raise LiveInvocationError("schema", f"{stage}: expected exactly one item, got {len(parsed['items'])}")
        parsed = parsed["items"][0]
    if not isinstance(parsed, dict):
        raise LiveInvocationError("schema", f"{stage}: live result was not an object")
    return parsed


def deterministic_target_metadata_errors(generator_item: dict) -> list[str]:
    """Check only Generator metadata relationships that are mechanically knowable.

    This function deliberately does not inspect or rewrite the Reviewer's
    grammar fields.  It verifies consistency among the Generator's declared
    target/format metadata and the emitted item so the blind Reviewer is not
    assigned a comparison it cannot perform.
    """

    errors: list[str] = []
    if not isinstance(generator_item, dict):
        return ["generator item must be an object"]

    correct_answer = generator_item.get("correct_answer")
    grammar = generator_item.get("grammar_metadata")
    format_metadata = generator_item.get("format_metadata")
    provenance = generator_item.get("provenance")
    qa_metadata = generator_item.get("qa_metadata")
    if not isinstance(grammar, dict):
        errors.append("grammar_metadata must be an object")
    if not isinstance(format_metadata, dict):
        errors.append("format_metadata must be an object")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    if not isinstance(qa_metadata, dict):
        errors.append("qa_metadata must be an object")
    if errors:
        return errors
    assert isinstance(grammar, dict)
    assert isinstance(format_metadata, dict)
    assert isinstance(provenance, dict)
    assert isinstance(qa_metadata, dict)

    if correct_answer not in {"A", "B", "C", "D"}:
        errors.append("correct_answer must be A/B/C/D")
    if grammar.get("intended_error_position") != correct_answer:
        errors.append("grammar_metadata.intended_error_position does not match correct_answer")

    span_types = format_metadata.get("span_types")
    if not isinstance(span_types, dict):
        errors.append("format_metadata.span_types must be an object")
    elif correct_answer in {"A", "B", "C", "D"}:
        if grammar.get("correct_span_type") != span_types.get(correct_answer):
            errors.append("grammar_metadata.correct_span_type does not match the correct span type")

    diagnostics = format_metadata.get("diagnostics")
    if not isinstance(diagnostics, dict):
        errors.append("format_metadata.diagnostics must be an object")
    else:
        for key in ("correct_span_type", "correction_locality", "decision_granularity"):
            if diagnostics.get(key) != grammar.get(key):
                errors.append(f"format_metadata.diagnostics.{key} does not match grammar_metadata.{key}")

    if provenance.get("agent_version") != generator_item.get("agent_version"):
        errors.append("provenance.agent_version does not match agent_version")
    return errors


def deterministic_target_metadata_status(generator_item: dict) -> str:
    """Return the formal enum value for the post-blind metadata check."""

    return "PASS" if not deterministic_target_metadata_errors(generator_item) else "FAIL"


def validate_reviewer_post_blind_consistency(reviewer_item: dict, generator_item: dict) -> list[str]:
    """Fail closed when a formal record contradicts deterministic metadata."""

    expected = deterministic_target_metadata_status(generator_item)
    actual = reviewer_item.get("checks", {}).get("target_metadata")
    if actual != expected:
        return [
            "reviewer: checks.target_metadata contradicts deterministic post-blind "
            f"evaluation (expected {expected}, got {actual})"
        ]
    return []


def adapt_reviewer_structural(
    raw: dict,
    generator_item: dict,
    order: int,
    batch_id: str,
    runtime_schema: dict | None = None,
) -> dict:
    """Adapt a blind Reviewer record without changing its judgment.

    The live response already uses the v2 Reviewer contract except for the two
    comparison fields that cannot be exposed during the blind call and the
    deterministic target-metadata check. Validate only its structural shape,
    copy its judgment fields unchanged, and attach only those post-invocation
    fields. Semantic consistency is deliberately left to the checked-in
    Reviewer validator.
    """
    del order, batch_id  # provenance is supplied by the Reviewer response
    forbidden = sorted(nested_forbidden(raw, REVIEWER_FORBIDDEN_OUTPUT_KEYS))
    if forbidden:
        raise LiveInvocationError("schema", f"reviewer: forbidden Generator field(s) appeared in live output: {forbidden}")
    unexpected_post_stage = sorted(set(raw) & REVIEWER_POST_STAGE_KEYS)
    if unexpected_post_stage:
        raise LiveInvocationError("schema", "reviewer: comparison fields must be attached after the live invocation")
    raw_checks = raw.get("checks")
    if isinstance(raw_checks, dict) and "target_metadata" in raw_checks:
        raise LiveInvocationError(
            "schema",
            "reviewer: checks.target_metadata is deferred to deterministic post-blind comparison",
        )

    missing = sorted(REVIEWER_LIVE_REQUIRED - set(raw))
    if missing:
        raise LiveInvocationError("schema", f"reviewer: required live field(s) missing: {missing}")
    # The canonical schema's only absent fields are post-stage fields. A
    # dedicated runtime schema check keeps this adapter structural.
    raw_errors = schema_errors(raw, runtime_schema or reviewer_runtime_schema())
    if raw_errors:
        raise LiveInvocationError("schema", "; ".join(f"reviewer: {error}" for error in raw_errors))
    if raw.get("item_id") != generator_item.get("item_id") or raw.get("section") != generator_item.get("section"):
        raise LiveInvocationError("schema", "reviewer: live identity does not match the blinded candidate")
    generator_answer = generator_item.get("correct_answer")
    if generator_answer not in {"A", "B", "C", "D"}:
        raise LiveInvocationError("schema", "reviewer: generator candidate has no contract-compatible answer")

    formal = copy.deepcopy(raw)
    formal["generator_answer"] = generator_answer
    formal["answer_match"] = formal["independent_answer"] == generator_answer
    formal.setdefault("checks", {})["target_metadata"] = deterministic_target_metadata_status(generator_item)
    return formal


def formal_reviewer(
    raw: dict,
    generator_item: dict,
    order: int,
    batch_id: str,
    runtime_schema: dict | None = None,
) -> dict:
    """Perform structural adaptation, then run the canonical Reviewer validator."""

    formal = adapt_reviewer_structural(raw, generator_item, order, batch_id, runtime_schema)
    post_blind_errors = validate_reviewer_post_blind_consistency(formal, generator_item)
    if post_blind_errors:
        raise LiveInvocationError("schema", "; ".join(post_blind_errors))
    formal_ok, formal_errors = validate_existing_contract(formal, REVIEWER_VALIDATOR, "reviewer")
    if not formal_ok:
        raise LiveInvocationError("schema", "; ".join(formal_errors))
    return formal


def live_config() -> dict:
    _verify_freeze("before", "config_load")
    config = copy.deepcopy(orch.load_config())
    config["paths"]["reviewer_validate_script"] = REVIEWER_VALIDATOR
    config["paths"]["solver_validate_script"] = SOLVER_VALIDATOR
    _verify_freeze("after", "config_load")
    return config


def record_live_stage_failure(
    candidate: orch.Candidate,
    config: dict,
    stage: str,
    error: LiveInvocationError,
) -> orch.Candidate:
    """Route a live stage failure through the production state machine."""
    kind = "content" if error.category == "schema" else "system"
    return orch.record_stage_failure(
        candidate,
        config,
        kind=kind,
        stage=stage,
        detail=error.detail,
    )


def candidate_from_generator(item: dict) -> orch.Candidate:
    candidate = orch.Candidate(item_id=item["item_id"], concept_id=item["item_id"], section=item["section"])
    candidate.generator_item = item
    candidate.planned_slot = orch.derive_slot_requirements(item)
    return candidate


def process_one(order: int, batch_id: str, config: dict, generator_formal: list, reviewer_formal: list, solver_formal: list, provenance_records: list, outcomes: list) -> None:
    item_id = f"we-v2.1.3-live-{batch_id[-8:]}-{order:03d}"
    reviewer_invocation: InvocationResult | None = None
    solver_invocation: InvocationResult | None = None
    generated: dict | None = None
    for attempt in range(1, GENERATOR_VALIDATION_RETRIES + 2):
        generator_invocation: InvocationResult | None = None
        try:
            generator_invocation = invoke(
                GENERATOR_AGENT, "generator", generator_prompt(item_id, order, batch_id), [], "Read,Glob,Grep",
                GENERATOR_SCHEMA_PATH,
                system_directive=generator_system_directive(),
            )
            candidate_item = get_single_item(generator_invocation.parsed, "generator")
            generator_ok, generator_errors = validate_schema_only(
                candidate_item,
                _schema_for_stage("generator", GENERATOR_SCHEMA_PATH),
                "generator",
            )
            if not generator_ok:
                raise LiveInvocationError("schema", "; ".join(generator_errors))
            if candidate_item.get("item_id") != item_id:
                raise LiveInvocationError("schema", f"generator: item_id mismatch; expected {item_id!r}, got {candidate_item.get('item_id')!r}")
            # Finalization must inspect the formal object returned by the
            # runtime. An intermediate mutation object is not authoritative.
            generator_ok, generator_errors = validate_generator_finalization(candidate_item)
            if not generator_ok:
                raise LiveInvocationError("schema", "; ".join(generator_errors))
            generated = candidate_item
            generator_formal.append(generated)
            provenance_records.append(sidecar(generator_invocation, input_payload={}, contract_validated=True, formal_output_exists=True, leakage=[]))
            break
        except LiveInvocationError as exc:
            if generator_invocation is None and exc.invocation is not None:
                generator_invocation = exc.invocation
            if generator_invocation is None:
                runtime = current_runtime()
                generator_invocation = InvocationResult(
                    "generator", GENERATOR_AGENT, str(uuid.uuid4()), now_iso(),
                    provider=runtime.provider, model=MODEL if runtime.provider == "claude-code-cli" else "default",
                    cli_version=runtime.cli_version,
                )
            provenance_records.append(sidecar(generator_invocation, input_payload={}, contract_validated=False, formal_output_exists=False, leakage=[], error=exc))
            if exc.category == "schema" and attempt <= GENERATOR_VALIDATION_RETRIES:
                print(f"generator validation retry {order}/10 attempt {attempt + 1}", flush=True)
                continue
            outcomes.append({"item_id": item_id, "state": "GENERATION_FAILED", "failure": {"stage": "generator", "category": exc.category, "detail": exc.detail}, "generator_attempts": attempt})
            return

    if generated is None:
        outcomes.append({"item_id": item_id, "state": "GENERATION_FAILED", "failure": {"stage": "generator", "category": "schema", "detail": "generator: no valid item after validation retries"}, "generator_attempts": GENERATOR_VALIDATION_RETRIES + 1})
        return

    candidate = candidate_from_generator(generated)
    candidate.transition(orch.State.REVIEWING, "Generator structural schema passed")
    reviewer_input: dict = {}
    reviewer_leakage: list[str] = []
    try:
        try:
            _verify_freeze("before", "reviewer_blinding")
            reviewer_input = canonical_reviewer_input(generated)
            _verify_freeze("after", "reviewer_blinding")
        except (TypeError, ValueError, KeyError) as exc:
            raise LiveInvocationError("schema", f"reviewer: canonical blind payload failed: {exc}") from exc
        reviewer_leakage = reviewer_input_errors(
            generated,
            reviewer_input,
            reviewer_input_sha256(reviewer_input),
        )
        if reviewer_leakage:
            raise LiveInvocationError(
                "schema",
                "reviewer: canonical blind payload failed: " + "; ".join(reviewer_leakage),
            )
        atomic_write_json(INPUTS / f"{order:03d}_reviewer.json", reviewer_input)
        reviewer_invocation = invoke(
            REVIEWER_AGENT, "reviewer", reviewer_prompt(reviewer_input), list(reviewer_input), "",
            _schema_for_stage("reviewer", REVIEWER_SCHEMA_PATH),
            reviewer_runtime_schema(_schema_for_stage("reviewer", REVIEWER_SCHEMA_PATH)),
            reviewer_system_directive(),
        )
        raw_reviewer = get_single_item(reviewer_invocation.parsed, "reviewer")
        reviewer = formal_reviewer(
            raw_reviewer,
            generated,
            order,
            batch_id,
            reviewer_runtime_schema(_schema_for_stage("reviewer", REVIEWER_SCHEMA_PATH)),
        )
        reviewer_ok, reviewer_errors = validate_existing_contract(reviewer, REVIEWER_VALIDATOR, "reviewer")
        if not reviewer_ok:
            raise LiveInvocationError("schema", "; ".join(reviewer_errors))
        reviewer_formal.append(reviewer)
        candidate.reviewer_item = reviewer
        _verify_freeze("before", "reviewer_orchestrator_validation")
        candidate = orch.process_review_output(candidate, config)
        _verify_freeze("after", "reviewer_orchestrator_validation")
        provenance_records.append(sidecar(reviewer_invocation, input_payload=reviewer_input, contract_validated=True, formal_output_exists=True, leakage=reviewer_leakage))
    except LiveInvocationError as exc:
        if reviewer_invocation is None and exc.invocation is not None:
            reviewer_invocation = exc.invocation
        if reviewer_invocation is None:
            runtime = current_runtime()
            reviewer_invocation = InvocationResult(
                "reviewer", REVIEWER_AGENT, str(uuid.uuid4()), now_iso(),
                provider=runtime.provider, model=MODEL if runtime.provider == "claude-code-cli" else "default",
                cli_version=runtime.cli_version, input_keys=list(reviewer_input),
            )
        provenance_records.append(sidecar(reviewer_invocation, input_payload=reviewer_input, contract_validated=False, formal_output_exists=False, leakage=reviewer_leakage, error=exc))
        candidate = record_live_stage_failure(candidate, config, "reviewer", exc)
        outcomes.append({
            "item_id": item_id,
            "state": candidate.state,
            "failure": {
                "stage": "reviewer",
                "category": exc.category,
                "detail": exc.detail,
            },
            "state_history": list(candidate.state_history),
        })
        return

    if candidate.state != orch.State.SOLVING:
        outcomes.append({"item_id": item_id, "state": candidate.state, "state_history": candidate.state_history, "reviewer_verdict": reviewer.get("verdict")})
        return

    _verify_freeze("before", "solver_blinding")
    solver_input = canonical_solver_input(generated)
    _verify_freeze("after", "solver_blinding")
    solver_leakage = nested_forbidden(solver_input, SOLVER_FORBIDDEN_FIELDS)
    ok, problems = orch.leakage_guard(solver_input, generated["section"])
    if not ok:
        candidate.leakage_check = {"ok": False, "problems": problems, "blinded_keys": sorted(solver_input)}
        candidate.transition(orch.State.MANUAL_REVIEW, "leakage guard failed")
        outcomes.append({"item_id": item_id, "state": candidate.state, "state_history": candidate.state_history, "leakage": problems})
        return
    if solver_leakage:
        candidate.leakage_check = {"ok": False, "problems": solver_leakage, "blinded_keys": sorted(solver_input)}
        candidate.transition(orch.State.MANUAL_REVIEW, "forbidden Solver input field detected")
        outcomes.append({"item_id": item_id, "state": candidate.state, "state_history": candidate.state_history, "leakage": solver_leakage})
        return
    candidate.solver_input = solver_input
    atomic_write_json(INPUTS / f"{order:03d}_solver.json", solver_input)
    try:
        solver_invocation = invoke(
            SOLVER_AGENT, "solver", solver_prompt(solver_input), list(solver_input), "",
            SOLVER_SCHEMA_PATH,
            system_directive=solver_system_directive(),
        )
        solver = get_single_item(solver_invocation.parsed, "solver")
        solver_ok, solver_errors = validate_existing_contract(solver, SOLVER_VALIDATOR, "solver")
        if not solver_ok:
            raise LiveInvocationError("schema", "; ".join(solver_errors))
        solver_formal.append(solver)
        _verify_freeze("before", "solver_orchestrator_validation")
        candidate = orch.process_solver_stage(candidate, config, solver, precomputed_solver_input=solver_input)
        _verify_freeze("after", "solver_orchestrator_validation")
        provenance_records.append(sidecar(solver_invocation, input_payload=solver_input, contract_validated=True, formal_output_exists=True, leakage=solver_leakage))
    except LiveInvocationError as exc:
        if solver_invocation is None and exc.invocation is not None:
            solver_invocation = exc.invocation
        if solver_invocation is None:
            runtime = current_runtime()
            solver_invocation = InvocationResult(
                "solver", SOLVER_AGENT, str(uuid.uuid4()), now_iso(),
                provider=runtime.provider, model=MODEL if runtime.provider == "claude-code-cli" else "default",
                cli_version=runtime.cli_version, input_keys=list(solver_input),
            )
        provenance_records.append(sidecar(solver_invocation, input_payload=solver_input, contract_validated=False, formal_output_exists=False, leakage=solver_leakage, error=exc))
        candidate = record_live_stage_failure(candidate, config, "solver", exc)
        outcomes.append({
            "item_id": item_id,
            "state": candidate.state,
            "failure": {
                "stage": "solver",
                "category": exc.category,
                "detail": exc.detail,
            },
            "state_history": list(candidate.state_history),
        })
        return

    outcomes.append({
        "item_id": item_id,
        "state": candidate.state,
        "state_history": candidate.state_history,
        "reviewer_verdict": reviewer.get("verdict"),
        "reviewer_answer": reviewer.get("independent_answer"),
        "solver_answer": solver.get("solver_answer"),
        "solver_confidence": solver.get("confidence"),
        "consensus": None if candidate.consensus is None else {
            "auto_accept": candidate.consensus.auto_accept,
            "routing": candidate.consensus.routing,
            "failed_conditions": candidate.consensus.failed_conditions,
            "disagreement_reasons": candidate.consensus.disagreement_reasons,
        },
        "leakage_check": {"ok": True, "problems": [], "blinded_keys": sorted(solver_input)},
    })


def reviewer_error_status(item: dict) -> str:
    """Classify Reviewer error-count outcomes without conflating categories."""

    count = item.get("detected_error_count")
    if not isinstance(count, int) or isinstance(count, bool):
        return "ambiguous_one_error"
    if count == 0:
        return "zero_genuine_errors"
    if count > 1:
        return "multiple_errors"

    checks_value = item.get("checks")
    checks = checks_value if isinstance(checks_value, dict) else {}
    one_error_status = checks.get("one_error_only")
    answer_status = checks.get("answer_uniqueness")
    if (
        item.get("grammar_validity") != "PASS"
        or one_error_status != "PASS"
        or answer_status != "PASS"
        or item.get("independent_answer") == "AMBIGUOUS"
    ):
        return "ambiguous_one_error"
    return "one_genuine_error"


def build_metrics(generator_items: list, reviewer_items: list, solver_items: list, provenance_records: list, outcomes: list, tests: dict, batch_id: str) -> dict:
    by_gen = {item.get("item_id"): item for item in generator_items if isinstance(item, dict)}
    by_review = {item.get("item_id"): item for item in reviewer_items if isinstance(item, dict)}
    by_solver = {item.get("item_id"): item for item in solver_items if isinstance(item, dict)}
    reviewer_sidecars = [x for x in provenance_records if x.get("stage") == "reviewer"]
    solver_sidecars = [x for x in provenance_records if x.get("stage") == "solver"]
    agreement = sum(
        1 for item_id, item in by_solver.items()
        if item_id in by_gen and item.get("solver_answer") == by_gen[item_id].get("correct_answer")
    )
    structural_conflict = sum(
        1 for item_id, item in by_solver.items()
        if item_id in by_review and item.get("solver_answer") != by_review[item_id].get("independent_answer")
    )
    reviewer_statuses = [reviewer_error_status(item) for item in reviewer_items]
    reviewer_status_counts = {
        status: reviewer_statuses.count(status)
        for status in (
            "one_genuine_error",
            "zero_genuine_errors",
            "multiple_errors",
            "ambiguous_one_error",
        )
    }
    reviewer_genuine_failure = sum(status != "one_genuine_error" for status in reviewer_statuses)
    reviewer_zero_genuine_errors = reviewer_status_counts["zero_genuine_errors"]
    reviewer_multiple_error = reviewer_status_counts["multiple_errors"]
    reviewer_ambiguous_one_error = reviewer_status_counts["ambiguous_one_error"]
    solver_none = sum(1 for item in solver_items if item.get("solver_answer") == "NONE")
    solver_ambiguous = sum(1 for item in solver_items if item.get("solver_answer") == "AMBIGUOUS")
    leakage_count = sum(len(item.get("forbidden_input_fields_present", [])) for item in provenance_records)
    acceptance_invariant_failures = []
    for outcome in outcomes:
        if outcome.get("state") == orch.State.ACCEPTED:
            consensus = outcome.get("consensus") or {}
            if consensus.get("auto_accept") is not True or consensus.get("routing") != orch.State.ACCEPTED:
                acceptance_invariant_failures.append(outcome.get("item_id"))
    raw_failures = [
        {
            "stage": record.get("stage"),
            "invocation_id": record.get("invocation_id"),
            "category": record.get("failure_classification") or record.get("failure", {}).get("category"),
            "detail": record.get("failure", {}).get("detail"),
        }
        for record in provenance_records if record.get("failure")
    ]
    invocation_failure_keys = {
        (failure.get("stage"), failure.get("detail"))
        for failure in raw_failures
    }
    for outcome in outcomes:
        outcome_failure = outcome.get("failure")
        if not outcome_failure:
            continue
        outcome_key = (outcome_failure.get("stage"), outcome_failure.get("detail"))
        if outcome_key in invocation_failure_keys:
            continue
        category = outcome_failure.get("category")
        if category in {"schema", "parsing"}:
            category = "CONTRACT_VALIDATION_ERROR"
        raw_failures.append({
            "stage": outcome_failure.get("stage"),
            "invocation_id": None,
            "category": category,
            "detail": outcome_failure.get("detail"),
        })
    failure_classification = []
    seen_failures: set[tuple[Any, ...]] = set()
    for failure in raw_failures:
        failure_key = (failure.get("stage"), failure.get("category"), failure.get("detail"))
        if failure_key in seen_failures:
            continue
        seen_failures.add(failure_key)
        failure_classification.append(failure)
    stage_contracts = {
        stage: {
            "valid": sum(record.get("stage") == stage and record.get("contract_valid") is True for record in provenance_records),
            "invalid": sum(record.get("stage") == stage and record.get("contract_valid") is False for record in provenance_records),
        }
        for stage in ("generator", "reviewer", "solver")
    }
    reviewer_findings = [
        {
            "item_id": item.get("item_id"),
            "verdict": item.get("verdict"),
            "independent_answer": item.get("independent_answer"),
            "issues": item.get("issues", []),
            "revision_requirements": item.get("revision_requirements", []),
        }
        for item in reviewer_items
    ]
    orchestrator_decisions = [
        {
            "item_id": outcome.get("item_id"),
            "state": outcome.get("state"),
            "reviewer_verdict": outcome.get("reviewer_verdict"),
            "solver_answer": outcome.get("solver_answer"),
            "consensus": outcome.get("consensus"),
        }
        for outcome in outcomes
    ]
    reviewer_input_records = [record for record in provenance_records if record.get("stage") == "reviewer"]
    solver_input_records = [record for record in provenance_records if record.get("stage") == "solver"]
    state_counts: dict[str, int] = {}
    for outcome in outcomes:
        state = str(outcome.get("state", "UNKNOWN"))
        state_counts[state] = state_counts.get(state, 0) + 1
    providers = sorted({record.get("provider") for record in provenance_records if record.get("provider")})
    provider = providers[0] if len(providers) == 1 else ("mixed" if providers else "unknown")
    models = sorted({record.get("model") for record in provenance_records if record.get("model")})
    return {
        "batch_id": batch_id,
        "cohort_size": 10,
        "microbatch_size": 1,
        "runtime": {
            "provider": provider,
            "model_identifier": models[0] if len(models) == 1 else models,
            "cli_versions": sorted({record.get("cli_version") for record in provenance_records if record.get("cli_version")}),
            "live_invocation": True,
            "synthetic_reviewer_output": False,
            "synthetic_solver_output": False,
        },
        "contract_boundary": {
            "production_finalizer_compatible": False,
            "accepted_item_published": False,
            "reason": "WE v2 live E2E is a compatibility harness; use the production contract pipeline for accepted items.",
        },
        "gates": {
            "generator_schema": {"passed": len(by_gen), "required": 10, "ok": len(by_gen) == 10},
            "reviewer_contract": {"passed": len(by_review), "required": 10, "ok": len(by_review) == 10},
            "solver_contract": {"passed": len(by_solver), "required": 10, "ok": len(by_solver) == 10},
            "reviewer_live_invocation": {"passed": sum(x.get("live_invocation") is True for x in reviewer_sidecars), "required": 10, "ok": sum(x.get("live_invocation") is True for x in reviewer_sidecars) == 10},
            "solver_live_invocation": {"passed": sum(x.get("live_invocation") is True for x in solver_sidecars), "required": 10, "ok": sum(x.get("live_invocation") is True for x in solver_sidecars) == 10},
            "answer_leakage": {"count": leakage_count, "required": 0, "ok": leakage_count == 0},
            "reviewer_genuine_error_failure": {"count": reviewer_genuine_failure, "required": 0, "ok": reviewer_genuine_failure == 0},
            "reviewer_zero_genuine_errors": {"count": reviewer_zero_genuine_errors, "required": 0, "ok": reviewer_zero_genuine_errors == 0},
            "reviewer_multiple_error": {"count": reviewer_multiple_error, "required": 0, "ok": reviewer_multiple_error == 0},
            "reviewer_ambiguous_one_error": {"count": reviewer_ambiguous_one_error, "required": 0, "ok": reviewer_ambiguous_one_error == 0},
            "solver_none": {"count": solver_none, "required": 0, "ok": solver_none == 0},
            "solver_ambiguous": {"count": solver_ambiguous, "maximum": 1, "ok": solver_ambiguous <= 1},
            "generator_solver_agreement": {"passed": agreement, "required": 9, "denominator": 10, "ok": agreement >= 9},
            "reviewer_solver_structural_conflict": {"count": structural_conflict, "maximum": 1, "ok": structural_conflict <= 1},
            "orchestrator_acceptance_logic": {"invariant_failures": acceptance_invariant_failures, "grammar_judgment_added": False, "ok": not acceptance_invariant_failures},
        },
        "outcomes": outcomes,
        "failure_classification": failure_classification,
        "requested_metrics": {
            "codex_live_invocation_count": sum(record.get("provider") == "codex" and record.get("live_invocation") is True for record in provenance_records),
            "reviewer_solver_contract_validity": stage_contracts,
            "blinding": {
                "reviewer_allowlist": list(reviewer_allowlist("Written Expression")),
                "solver_allowlist": list(WRITTEN_EXPRESSION_ALLOWLIST),
                "reviewer_invocation_count": len(reviewer_input_records),
                "solver_invocation_count": len(solver_input_records),
                "forbidden_fields_present": leakage_count,
                "ok": leakage_count == 0,
            },
            "generator_solver_agreement": {
                "passed": agreement,
                "denominator": len(by_solver),
                "ok": agreement >= 9 if len(by_solver) == 10 else False,
            },
            "reviewer_findings": reviewer_findings,
            "reviewer_error_status_counts": reviewer_status_counts,
            "orchestrator_decisions": {
                "state_counts": state_counts,
                "items": orchestrator_decisions,
            },
        },
        "attempts": {
            "generator_invocations": sum(record.get("stage") == "generator" for record in provenance_records),
            "reviewer_invocations": sum(record.get("stage") == "reviewer" for record in provenance_records),
            "solver_invocations": sum(record.get("stage") == "solver" for record in provenance_records),
            "codex_live_invocations": sum(record.get("provider") == "codex" and record.get("live_invocation") is True for record in provenance_records),
            "generator_validation_retries": sum(record.get("stage") == "generator" and record.get("contract_validated") is False for record in provenance_records),
        },
        "formal_output_counts": {
            "generator": len(generator_items),
            "reviewer": len(reviewer_items),
            "solver": len(solver_items),
        },
        "existing_tests": tests,
        "formal_output_files": {
            "generator": "runtime/formal/generator_outputs.json",
            "reviewer": "runtime/formal/reviewer_outputs.json",
            "solver": "runtime/formal/solver_outputs.json",
        },
        "runtime_provenance_sidecar": "runtime/provenance/runtime_provenance.json",
    }


def run_existing_tests() -> dict:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=OFFLINE_TEST_TIMEOUT_SECONDS,
        )
        output = (proc.stdout + proc.stderr).strip()
        return {"command": command, "exit_code": proc.returncode, "passed": proc.returncode == 0, "output_tail": output[-4000:]}
    except subprocess.TimeoutExpired as exc:
        return {"command": command, "exit_code": None, "passed": False, "failure_category": "infrastructure", "output_tail": str(exc)}


def final_decision(metrics: dict) -> tuple[str, str]:
    gates = metrics["gates"]
    if metrics.get("existing_tests", {}).get("passed") and all(gate.get("ok") for gate in gates.values()):
        return "A", "All requested live E2E gates and the existing regression suite passed."
    runtime_categories = {failure.get("category") for failure in metrics.get("failure_classification", [])}
    live_gate_failed = not gates["reviewer_live_invocation"]["ok"] or not gates["solver_live_invocation"]["ok"]
    runtime_failure_categories = LIVE_FAILURE_CATEGORIES - {"CONTRACT_VALIDATION_ERROR"}
    runtime_failure_categories |= {"infrastructure", "auth", "CLI", "agent invocation", "parsing"}
    if live_gate_failed and runtime_categories & runtime_failure_categories:
        return "E", "The runtime could not provide the required complete live pipeline; see classified invocation failures."
    reviewer_keys = {"reviewer_contract", "reviewer_live_invocation", "answer_leakage", "reviewer_genuine_error_failure", "reviewer_zero_genuine_errors", "reviewer_multiple_error", "reviewer_ambiguous_one_error"}
    if any(not gates[key]["ok"] for key in reviewer_keys):
        return "B", "Reviewer contract, blinded invocation, or independent grammar gates failed."
    solver_keys = {"solver_contract", "solver_live_invocation", "solver_none", "solver_ambiguous", "generator_solver_agreement", "reviewer_solver_structural_conflict"}
    if any(not gates[key]["ok"] for key in solver_keys):
        return "C", "Solver contract, blinded invocation, or solver agreement gates failed."
    if not gates["orchestrator_acceptance_logic"]["ok"]:
        return "D", "Orchestrator acceptance invariants failed."
    return "E", "The complete acceptance pipeline was not demonstrated; see gate and failure details."


def e2e_succeeded(metrics: dict) -> bool:
    return (
        metrics.get("existing_tests", {}).get("passed") is True
        and all(gate.get("ok") is True for gate in metrics.get("gates", {}).values())
    )


def write_report(metrics: dict, decision: str, decision_reason: str) -> None:
    gates = metrics["gates"]
    lines = [
        "# WE v2.1.3 Live E2E Report",
        "",
        f"- Batch: `{metrics['batch_id']}`",
        f"- Scope: 10 requested fresh items, one item per microbatch; recorded outcomes: {len(metrics.get('outcomes', []))}",
        "- Pipeline: Generator -> live Reviewer v2 -> live Grammar Solver -> existing Orchestrator",
        "- The 75-item Validation was not re-run.",
        "- Generator/Format/Mutation safety/Schema/Specification/Taxonomy source files: unchanged",
        "",
        f"## Final decision: {decision}",
        "",
        decision_reason,
        "",
        "## Gate results",
        "",
        "| Gate | Result | Requirement | Status |",
        "|---|---:|---:|---|",
    ]
    for name, gate in gates.items():
        result = gate.get("passed", gate.get("count", gate.get("invariant_failures", "-")))
        requirement = gate.get("required", gate.get("maximum", "-"))
        lines.append(f"| `{name}` | `{result}` | `{requirement}` | {'PASS' if gate.get('ok') else 'FAIL'} |")
    lines.extend([
        "",
        "## Runtime and provenance",
        "",
        f"The configured live paths use the `{metrics.get('runtime', {}).get('provider')}` runtime with the checked-in agent instructions. Reviewer input is projected only to `item_id`, `section`, `sentence`, and `marked_parts`; Solver input uses the existing canonical blinding projection. No Generator answer, mutation metadata, generation plan, explanation, Generator key, or Reviewer judgment was sent to either runtime.",
        "",
        "Formal records contain only their existing contracts. Runtime provider, agent/model identifier, exact Codex command, start/end timestamps, elapsed seconds, process exit code, timeout-vs-CLI source, formal-output existence, validation flag, input hash, and raw stdout/stderr paths are stored per invocation in the separate provenance sidecar.",
        "",
        "The Reviewer adapter only maps explicit fields/enums from the live response into the frozen formal record and attaches comparison fields after the blind invocation; it does not synthesize a grammar judgment or use Generator answer metadata to decide the answer.",
        "",
        f"Final formal record counts: Generator `{metrics.get('formal_output_counts', {}).get('generator', 0)}`, Reviewer `{metrics.get('formal_output_counts', {}).get('reviewer', 0)}`, Solver `{metrics.get('formal_output_counts', {}).get('solver', 0)}`. Codex live invocation count: `{metrics.get('attempts', {}).get('codex_live_invocations', 0)}`.",
        "",
        "## Requested final metrics",
        "",
        f"- Reviewer/Solver contract validity: `{json.dumps(metrics.get('requested_metrics', {}).get('reviewer_solver_contract_validity', {}), ensure_ascii=False)}`",
        f"- Blinding: `{json.dumps(metrics.get('requested_metrics', {}).get('blinding', {}), ensure_ascii=False)}`",
        f"- Generator/Solver agreement: `{json.dumps(metrics.get('requested_metrics', {}).get('generator_solver_agreement', {}), ensure_ascii=False)}`",
        f"- Reviewer findings: `{len(metrics.get('requested_metrics', {}).get('reviewer_findings', []))}` record(s); no finding is available when Reviewer was not reached.",
        f"- Orchestrator decisions: `{json.dumps(metrics.get('requested_metrics', {}).get('orchestrator_decisions', {}).get('state_counts', {}), ensure_ascii=False)}`",
        "",
        "## Failure classification",
        "",
    ])
    failures = metrics.get("failure_classification", [])
    if failures:
        lines.append("| Stage | Category | Detail |")
        lines.append("|---|---|---|")
        for failure in failures:
            detail = str(failure.get("detail", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{failure.get('stage')}` | `{failure.get('category')}` | {detail} |")
    else:
        lines.append("No live invocation failures were recorded.")
    lines.extend([
        "",
        "## Existing tests",
        "",
        f"Command: `{' '.join(metrics['existing_tests'].get('command', []))}`",
        f"Result: {'PASS' if metrics['existing_tests'].get('passed') else 'FAIL'}",
        "",
        "## Artifacts",
        "",
        "- Formal Generator output: `runtime/formal/generator_outputs.json`",
        "- Formal Reviewer output: `runtime/formal/reviewer_outputs.json`",
        "- Formal Solver output: `runtime/formal/solver_outputs.json`",
        "- Runtime provenance sidecar: `runtime/provenance/runtime_provenance.json`",
        "- Machine-readable report: `we_v2_1_3_live_e2e.json`",
        "",
    ])
    (OUT / "WE_V2_1_3_LIVE_E2E_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def report_existing_run() -> int:
    """Rebuild derived reports only after revalidating immutable evidence."""

    global _RUN_FREEZE
    metrics_path = OUT / "we_v2_1_3_live_e2e.json"
    previous_freeze = _RUN_FREEZE
    try:
        # This is deliberately the first trust decision in report-only mode.
        # The manifest's own contents/hash and every protected checkout file
        # must still match before any formal artifact is parsed.
        freeze = load_run_freeze(_freeze_manifest_path(), repo_root=ROOT)
        _RUN_FREEZE = freeze
        freeze.verify("report-only", "freeze_manifest")
        verify_artifact_manifest(freeze)

        batch_id, tests, outcomes = validate_frozen_run_contract(freeze)
        provenance_document = _read_json_file(PROVENANCE / "runtime_provenance.json", "runtime provenance")
        if not isinstance(provenance_document, dict):
            raise ValueError("runtime provenance must be an object")
        provenance_records = provenance_document["items"]
        formal_documents = {
            "generator": _read_json_file(FORMAL / "generator_outputs.json", "generator formal output"),
            "reviewer": _read_json_file(FORMAL / "reviewer_outputs.json", "reviewer formal output"),
            "solver": _read_json_file(FORMAL / "solver_outputs.json", "solver formal output"),
        }
        generator_items = formal_documents["generator"]["items"]
        reviewer_items = formal_documents["reviewer"]["items"]
        solver_items = formal_documents["solver"]["items"]
        if os.environ.get("WE_E2E_REPORT_ONLY_RUN_TESTS") == "1":
            tests = run_existing_tests()

        # Recheck both the source freeze and the evidence hash set after all
        # reads/validation. A report cannot turn a mid-report mutation into A.
        verify_artifact_manifest(freeze)
        freeze.verify("report-only", "before_metrics")
        metrics = build_metrics(
            generator_items,
            reviewer_items,
            solver_items,
            provenance_records,
            outcomes,
            tests,
            batch_id,
        )
        verify_artifact_manifest(freeze)
        freeze.verify("report-only", "after_metrics")
        decision, decision_reason = final_decision(metrics)
        metrics["final_decision"] = {
            "code": decision,
            "label": {
                "A": "Live Reviewer/Solver pipeline ready",
                "B": "Reviewer issue",
                "C": "Solver issue",
                "D": "Orchestrator issue",
                "E": "Runtime infrastructure unavailable",
            }[decision],
            "reason": decision_reason,
        }
        freeze.verify("report-only", "before_report_write")
        atomic_write_json(metrics_path, metrics)
        write_report(metrics, decision, decision_reason)
        return 0 if e2e_succeeded(metrics) else 1
    except (FreezeDriftError, OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Cannot report existing run; immutable evidence verification failed: {exc}", file=sys.stderr)
        return 2
    finally:
        _RUN_FREEZE = previous_freeze


def _write_freeze_drift_artifact(error: FreezeDriftError) -> None:
    atomic_write_json(
        OUT / "freeze_drift.json",
        {
            "status": error.category,
            "category": error.category,
            "phase": error.phase,
            "stage": error.stage,
            "mismatches": list(error.mismatches),
            "detail": str(error),
            "freeze_manifest_path": _relative_path(error.manifest_path),
            "quality_acceptance_rate": None,
        },
    )


def run_generator_probe() -> int:
    """Run exactly one frozen Generator call and no Reviewer/Solver calls."""

    global _RUN_FREEZE
    for directory in (FORMAL, PROVENANCE, INPUTS, LOGS):
        directory.mkdir(parents=True, exist_ok=True)
    batch_id = "we-v2.1.3-hardened-generator-probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runtime = configure_runtime(provider_override="codex", model_override="gpt-5.6-luna")
    _RUN_FREEZE = _create_run_freeze(
        runtime,
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        sandbox="read-only",
        timeout_seconds=300,
    )
    item_id = f"{batch_id}-001"
    invocation: InvocationResult | None = None
    canonical_errors: list[str] = []
    finalization_errors: list[str] = []
    generated: dict | None = None
    error: LiveInvocationError | None = None
    try:
        invocation = invoke(
            GENERATOR_AGENT,
            "generator",
            generator_prompt(item_id, 1, batch_id),
            [],
            "Read,Glob,Grep",
            GENERATOR_SCHEMA_PATH,
            system_directive=generator_system_directive(),
            reasoning_effort_override="medium",
            sandbox_override="read-only",
            timeout_override=300,
        )
        generated = get_single_item(invocation.parsed, "generator")
        schema_ok, canonical_errors = validate_schema_only(
            generated,
            _RUN_FREEZE.schema_snapshots["generator"],
            "generator",
        )
        if schema_ok:
            final_ok, finalization_errors = validate_generator_finalization(generated)
            if not final_ok:
                canonical_errors.extend(finalization_errors)
        if generated.get("item_id") != item_id:
            canonical_errors.append(
                f"generator: item_id mismatch; expected {item_id!r}, got {generated.get('item_id')!r}"
            )
        atomic_write_json(FORMAL / "generator_outputs.json", {"items": [generated]})
    except LiveInvocationError as exc:
        error = exc
        invocation = exc.invocation
    except FreezeDriftError as exc:
        _write_freeze_drift_artifact(exc)
        print(json.dumps({"status": exc.category, "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    if invocation is None:
        invocation = InvocationResult(
            "generator",
            GENERATOR_AGENT,
            str(uuid.uuid4()),
            now_iso(),
            provider=runtime.provider,
            model="gpt-5.6-luna",
            cli_version=runtime.cli_version,
            requested_timeout_seconds=300,
        )
    record = sidecar(
        invocation,
        input_payload={},
        contract_validated=not canonical_errors and error is None,
        formal_output_exists=generated is not None and not canonical_errors,
        leakage=[],
        error=error,
    )
    atomic_write_json(PROVENANCE / "runtime_provenance.json", {"items": [record]})
    result = {
        "status": "SUCCESS" if generated is not None and not canonical_errors and error is None else "PROBE_FAILURE",
        "category": None if error is None else error.category,
        "detail": None if error is None else error.detail,
        "batch_id": batch_id,
        "live_generator_invocation_count": 1,
        "reviewer_invocation_count": 0,
        "solver_invocation_count": 0,
        "canonical_validation": {
            "passed": not canonical_errors,
            "errors": canonical_errors,
            "schema_snapshot": _relative_path(_RUN_FREEZE.schema_snapshots["generator"]),
            "schema_hash": _RUN_FREEZE.manifest["canonical_schema_hashes"]["generator"],
        },
        "finalization_validation": {"passed": not finalization_errors, "errors": finalization_errors},
        "freeze_manifest": {
            "path": _relative_path(_RUN_FREEZE.manifest_path),
            "sha256": _RUN_FREEZE.manifest_sha256,
        },
        "quality_acceptance_rate": None,
        "note": "Infrastructure probe only; no Reviewer/Solver calls and no quality acceptance rate calculated.",
    }
    atomic_write_json(OUT / "generator_probe.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SUCCESS" else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--generator-probe" in argv:
        try:
            return run_generator_probe()
        except FreezeDriftError as exc:
            _write_freeze_drift_artifact(exc)
            print(json.dumps({"status": exc.category, "detail": str(exc)}, ensure_ascii=False, indent=2))
            return 2
    if os.environ.get("WE_E2E_REPORT_ONLY") == "1":
        return report_existing_run()
    _final_quality_pilot_preflight()
    for directory in (FORMAL, PROVENANCE, INPUTS, LOGS):
        directory.mkdir(parents=True, exist_ok=True)
    batch_id = "we-v2.1.3-live-e2e-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    config = live_config()
    runtime = configure_runtime()
    global _RUN_FREEZE
    _RUN_FREEZE = _create_run_freeze(
        runtime,
        model=MODEL if runtime.provider == "claude-code-cli" else (_RUNTIME_MODEL_OVERRIDE or os.environ.get("WE_E2E_CODEX_MODEL", "default")),
        reasoning_effort=os.environ.get("WE_E2E_CODEX_REASONING_EFFORT", "unset"),
        sandbox="read-only" if runtime.provider == "codex" else "native",
        timeout_seconds=CLI_TIMEOUT_SECONDS,
    )
    print(f"runtime provider: {runtime.provider} ({runtime.cli_version})", flush=True)
    generator_items: list = []
    reviewer_items: list = []
    solver_items: list = []
    provenance_records: list = []
    outcomes: list = []
    try:
        for order in range(1, 11):
            process_one(order, batch_id, config, generator_items, reviewer_items, solver_items, provenance_records, outcomes)
            atomic_write_json(FORMAL / "generator_outputs.json", {"items": generator_items})
            atomic_write_json(FORMAL / "reviewer_outputs.json", {"items": reviewer_items})
            atomic_write_json(FORMAL / "solver_outputs.json", {"items": solver_items})
            atomic_write_json(PROVENANCE / "runtime_provenance.json", {"items": provenance_records})
            atomic_write_json(_outcomes_path(), {"batch_id": batch_id, "outcomes": outcomes})
            latest = outcomes[-1] if outcomes else {"state": "UNKNOWN"}
            print(f"completed microbatch {order}/10: {latest.get('item_id')} -> {latest.get('state')}", flush=True)
    except FreezeDriftError as exc:
        _write_freeze_drift_artifact(exc)
        print(json.dumps({"status": exc.category, "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    tests = run_existing_tests()
    atomic_write_json(_outcomes_path(), {"batch_id": batch_id, "outcomes": outcomes})
    atomic_write_json(_test_result_path(), tests)
    _verify_freeze("before", "final_metrics")
    metrics = build_metrics(generator_items, reviewer_items, solver_items, provenance_records, outcomes, tests, batch_id)
    _verify_freeze("after", "final_metrics")
    decision, decision_reason = final_decision(metrics)
    metrics["final_decision"] = {"code": decision, "label": {"A": "Live Reviewer/Solver pipeline ready", "B": "Reviewer issue", "C": "Solver issue", "D": "Orchestrator issue", "E": "Runtime infrastructure unavailable"}[decision], "reason": decision_reason}
    atomic_write_json(OUT / "we_v2_1_3_live_e2e.json", metrics)
    write_report(metrics, decision, decision_reason)
    if _RUN_FREEZE is None:  # pragma: no cover - main always creates a freeze first
        raise RuntimeError("cannot publish evidence without a run freeze")
    write_artifact_manifest(_RUN_FREEZE)
    print(json.dumps({"batch_id": batch_id, "gates": metrics["gates"], "existing_tests": tests}, ensure_ascii=False, indent=2))
    return 0 if e2e_succeeded(metrics) else 1


if __name__ == "__main__":
    raise SystemExit(main())
