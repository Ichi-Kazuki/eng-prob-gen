"""Provider-neutral invocation adapters for live agent validation.

The pipeline's Generator, Reviewer, Solver, contracts, and decision engine
are deliberately outside this module.  An adapter only turns one invocation
request into one isolated CLI process, persists raw process artifacts, and
returns the last agent message for the caller's existing contract validator.

The checked-in ``.claude/agents/*.md`` files remain the only agent
instructions.  Claude receives them through its native ``--agent`` option;
Codex receives the exact file contents in its initial prompt because Codex
does not have Claude's named-agent option.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from runtime.codex_schema import (  # noqa: E402
    build_codex_transport_artifact,
    normalize_codex_output_for_canonical,
)


SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
Runner = Callable[..., subprocess.CompletedProcess[str]]


class RuntimeInvocationError(RuntimeError):
    """A runtime process could not produce a usable agent message."""

    def __init__(self, category: str, detail: str, result: "InvocationResult"):
        super().__init__(detail)
        self.category = category
        self.detail = detail
        self.result = result


@dataclass(frozen=True)
class InvocationRequest:
    """One stateless agent invocation.

    ``formal_output_schema`` is the canonical schema used by the caller's
    validator.  ``transport_output_schema`` is an optional runtime-only
    projection, needed only where a post-stage orchestrator field is not
    available to a blinded agent.  The projection is generated from the
    canonical schema and is never persisted as a formal contract.
    """

    stage: str
    agent_name: str
    agent_definition: Path
    prompt: str
    input_keys: tuple[str, ...] = ()
    formal_output_schema: Path | None = None
    transport_output_schema: dict[str, Any] | None = None
    system_directive: str | None = None
    model: str | None = None
    cwd: Path | None = None
    sandbox: SandboxMode | None = None
    tools: str = ""
    max_budget_usd: str | None = None
    timeout_seconds: int = 300
    artifact_dir: Path = Path(".")
    isolate_workspace: bool = False


@dataclass
class InvocationResult:
    """Persisted process facts and the parsed last agent message."""

    stage: str
    agent_name: str
    invocation_id: str
    started_at: str
    completed_at: str | None = None
    provider: str = "unknown"
    model: str = "unknown"
    cli_version: str = "unknown"
    exit_code: int | None = None
    raw_stdout_path: Path | None = None
    raw_stderr_path: Path | None = None
    output_last_message_path: Path | None = None
    command: tuple[str, ...] = ()
    raw_stdout: str = ""
    raw_stderr: str = ""
    raw_output: str = ""
    parsed: Any = None
    error_category: str | None = None
    error_detail: str | None = None
    input_keys: list[str] = field(default_factory=list)
    workspace_path: Path | None = None
    transport_schema_path: Path | None = None
    transport_schema_provenance_path: Path | None = None
    transport_schema_provenance: dict[str, Any] | None = None


class AgentRuntime(Protocol):
    """Common interface used by Generator, Reviewer, and Solver callers."""

    provider: str
    cli_version: str

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        ...


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def parse_json_text(raw: str, stage: str) -> Any:
    """Parse a JSON object/array without repairing model output."""

    text = raw.strip()
    if not text:
        raise ValueError(f"{stage}: CLI returned empty output")

    candidates: list[str] = [text]
    for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL):
        candidates.append(match.group(1).strip())

    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("result"), str):
            try:
                return parse_json_text(value["result"], stage)
            except ValueError:
                pass
        if isinstance(value, dict) and "structured_output" in value:
            return value["structured_output"]
        return value

    decoder = json.JSONDecoder()
    for offset, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, end = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if end == len(text[offset:].rstrip()):
            return value
    raise ValueError(f"{stage}: CLI output was not a JSON object/array")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


_FORBIDDEN_ISOLATION_BASENAMES = {
    "candidates_state.json",
    "validation_candidates_state.json",
    "manual_review_queue.json",
    "human_review_calibration_key.json",
    "human_review_results.json",
    "provenance.json",
    "pilot_provenance.json",
    "validation_provenance.json",
    "accepted_items.json",
    "pilot_accepted_items.json",
    "validation_accepted_items.json",
}


def _assert_isolated_workspace_clean(workspace: Path) -> None:
    """Defense-in-depth check that no answer-bearing artifact was staged."""
    forbidden: list[str] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if (
            name in _FORBIDDEN_ISOLATION_BASENAMES
            or name.endswith("_sealed_key.json")
            or name.endswith("_calibration_key.json")
            or ("reviewer_output" in name and path.parent.name.lower() != "schemas")
        ):
            forbidden.append(str(path.relative_to(workspace)))
    if forbidden:
        raise ValueError(
            "isolated Solver workspace contains forbidden artifact(s): "
            + ", ".join(sorted(forbidden))
        )


def _configured_codex_model() -> str:
    explicit = os.environ.get("WE_E2E_CODEX_MODEL")
    if explicit:
        return explicit
    codex_home = os.environ.get("CODEX_HOME")
    config_path = Path(codex_home) / "config.toml" if codex_home else Path.home() / ".codex" / "config.toml"
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*model\s*=\s*['\"]([^'\"]+)['\"]\s*$", line)
            if match:
                return match.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return "default"


def _configured_codex_executable() -> str | None:
    explicit = os.environ.get("CODEX_CLI_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    codex_home = os.environ.get("CODEX_HOME")
    config_path = Path(codex_home) / "config.toml" if codex_home else Path.home() / ".codex" / "config.toml"
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r"^\s*CODEX_CLI_PATH\s*=\s*['\"]([^'\"]+)['\"]\s*$", config_text, flags=re.MULTILINE)
    if match and Path(match.group(1)).exists():
        return match.group(1)
    return None


class _SubprocessRuntime:
    provider = "unknown"
    launch_failure_category = "infrastructure"

    def __init__(
        self,
        *,
        executable: str | None = None,
        model: str | None = None,
        runner: Runner | None = None,
        cli_version: str | None = None,
    ) -> None:
        self.executable = executable or self._find_executable()
        self.model = model or "default"
        self._runner = runner or subprocess.run
        self._cli_version = cli_version or self._detect_cli_version()

    def _find_executable(self) -> str:
        raise NotImplementedError

    def _detect_cli_version(self) -> str:
        try:
            proc = self._runner(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        output = (_text(proc.stdout) or _text(proc.stderr)).strip()
        return output.splitlines()[0][:200] if output else "unknown"

    @property
    def cli_version(self) -> str:
        return self._cli_version

    def _artifact_paths(self, request: InvocationRequest, invocation_id: str) -> tuple[Path, Path, Path | None]:
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = request.artifact_dir / f"{request.stage}-{invocation_id}.stdout.txt"
        stderr_path = request.artifact_dir / f"{request.stage}-{invocation_id}.stderr.txt"
        return stdout_path, stderr_path, None

    def _write_process_artifacts(self, result: InvocationResult) -> None:
        if result.raw_stdout_path is not None:
            result.raw_stdout_path.parent.mkdir(parents=True, exist_ok=True)
            result.raw_stdout_path.write_text(result.raw_stdout, encoding="utf-8")
        if result.raw_stderr_path is not None:
            result.raw_stderr_path.parent.mkdir(parents=True, exist_ok=True)
            result.raw_stderr_path.write_text(result.raw_stderr, encoding="utf-8")

    def _new_result(self, request: InvocationRequest) -> InvocationResult:
        invocation_id = str(uuid.uuid4())
        stdout_path, stderr_path, last_message_path = self._artifact_paths(request, invocation_id)
        return InvocationResult(
            stage=request.stage,
            agent_name=request.agent_name,
            invocation_id=invocation_id,
            started_at=_now_iso(),
            provider=self.provider,
            model=request.model or self.model,
            cli_version=self.cli_version,
            raw_stdout_path=stdout_path,
            raw_stderr_path=stderr_path,
            output_last_message_path=last_message_path,
            input_keys=list(request.input_keys),
        )

    @staticmethod
    def _prepare_isolated_workspace(
        request: InvocationRequest, result: InvocationResult
    ) -> tuple[InvocationRequest, Path | None]:
        """Create a clean, disposable workspace for an isolated invocation.

        The workspace is deliberately created by ``tempfile`` outside the
        repository and receives only the named agent definition and the
        schema used for this invocation. It never receives Candidate state,
        reviewer/generator outputs, provenance, or evaluation keys.
        """
        if not request.isolate_workspace:
            return request, request.formal_output_schema

        workspace = Path(tempfile.mkdtemp(prefix="itp-solver-"))
        result.workspace_path = workspace
        agent_path = workspace / ".claude" / "agents" / f"{request.agent_name}.md"
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(request.agent_definition, agent_path)

        schema_path: Path | None = None
        if request.formal_output_schema is not None:
            schema_path = workspace / "schemas" / request.formal_output_schema.name
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(request.formal_output_schema, schema_path)
        return replace(request, cwd=workspace), schema_path

    def _run(self, request: InvocationRequest, result: InvocationResult, command: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        result.command = tuple(command)
        try:
            if self._runner is subprocess.run:
                return self._run_process_group(request, result, command, stdin=stdin)
            return self._runner(
                command,
                cwd=str(request.cwd) if request.cwd is not None else None,
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            result.raw_stdout = _text(exc.stdout) or self._read_artifact(result.raw_stdout_path)
            result.raw_stderr = _text(exc.stderr) or self._read_artifact(result.raw_stderr_path)
            result.exit_code = None
            result.completed_at = _now_iso()
            result.error_category = "infrastructure"
            diagnostic = (result.raw_stderr or result.raw_stdout).strip()
            suffix = f"; last diagnostic: {diagnostic[-800:]}" if diagnostic else ""
            result.error_detail = f"{request.stage}: CLI timeout after {request.timeout_seconds}s{suffix}"
            self._write_process_artifacts(result)
            raise RuntimeInvocationError(result.error_category, result.error_detail, result) from exc
        except OSError as exc:
            result.exit_code = None
            result.completed_at = _now_iso()
            result.error_category = self.launch_failure_category
            result.error_detail = f"{request.stage}: failed to launch {self.provider} CLI: {exc}"
            self._write_process_artifacts(result)
            raise RuntimeInvocationError(result.error_category, result.error_detail, result) from exc

    @staticmethod
    def _read_artifact(path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _terminate_process_tree(pid: int) -> None:
        """Terminate only the process tree created for this invocation."""
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            return
        try:
            os.killpg(pid, 15)
        except (OSError, ProcessLookupError):
            pass

    def _run_process_group(self, request: InvocationRequest, result: InvocationResult, command: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        """Run real CLIs without leaving shim children holding capture pipes."""
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        start_new_session = os.name != "nt"
        stdout_path = result.raw_stdout_path
        stderr_path = result.raw_stderr_path
        try:
            if stdout_path is None or stderr_path is None:
                raise OSError("runtime artifact paths were not allocated")
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
                process = subprocess.Popen(
                    command,
                    cwd=str(request.cwd) if request.cwd is not None else None,
                    stdin=subprocess.PIPE if stdin is not None else None,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                    start_new_session=start_new_session,
                )
                try:
                    process.communicate(input=stdin, timeout=request.timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    self._terminate_process_tree(process.pid)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise subprocess.TimeoutExpired(command, request.timeout_seconds) from exc
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            raise
        except OSError:
            raise

    def _complete(self, request: InvocationRequest, result: InvocationResult, proc: subprocess.CompletedProcess[str]) -> InvocationResult:
        result.raw_stdout = _text(proc.stdout)
        result.raw_stderr = _text(proc.stderr)
        result.raw_output = result.raw_stdout or result.raw_stderr
        result.exit_code = proc.returncode
        result.completed_at = _now_iso()
        self._write_process_artifacts(result)
        if proc.returncode != 0:
            # Codex writes the full prompt and tool transcript to stderr.  The
            # actionable process error is normally at the end; using the
            # prefix would misclassify prompt words such as "network" as a
            # transport failure.
            diagnostic = (result.raw_stderr or result.raw_stdout).strip()[-2000:]
            result.error_category = self._process_error_category(diagnostic)
            result.error_detail = f"{request.stage}: {self.provider} CLI exit {proc.returncode}: {diagnostic}"
            raise RuntimeInvocationError(result.error_category, result.error_detail, result)
        return result

    def _process_error_category(self, diagnostic: str) -> str:
        return "infrastructure"


class ClaudeRuntime(_SubprocessRuntime):
    """Claude Code CLI adapter retaining the existing invocation behavior."""

    provider = "claude-code-cli"
    launch_failure_category = "CLI"

    def _process_error_category(self, diagnostic: str) -> str:
        lowered = diagnostic.lower()
        if any(token in lowered for token in ('"api_error_status":429', "rate limit", "session limit", "too many requests")):
            return "infrastructure"
        if any(token in lowered for token in ("unauthorized", "authentication", "api key", "login", "invalid token")):
            return "auth"
        if any(token in lowered for token in ("timeout", "timed out", "network", "dns", "connection", "econn")):
            return "infrastructure"
        return "agent invocation"

    def _find_executable(self) -> str:
        found = shutil.which("claude")
        if not found:
            # Keep the missing executable as a normal invocation failure so
            # the caller can persist the required infrastructure sidecar.
            return "claude"
        return found

    @staticmethod
    def _claude_schema(schema: dict[str, Any]) -> dict[str, Any]:
        projected = json.loads(json.dumps(schema))
        projected.pop("$schema", None)
        projected.pop("$id", None)
        for clause in projected.get("allOf", []):
            then_properties = clause.get("then", {}).get("properties", {})
            for property_schema in then_properties.values():
                if isinstance(property_schema, dict) and "properties" in property_schema:
                    property_schema.setdefault("type", "object")
        return projected

    def _artifact_paths(self, request: InvocationRequest, invocation_id: str) -> tuple[Path, Path, Path | None]:
        stdout_path, stderr_path, _ = super()._artifact_paths(request, invocation_id)
        return stdout_path, stderr_path, None

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = self._new_result(request)
        if request.formal_output_schema is None:
            raise ValueError(f"{request.stage}: Claude invocation requires an output schema")
        effective_request, isolated_schema = self._prepare_isolated_workspace(request, result)
        if result.workspace_path is not None:
            _assert_isolated_workspace_clean(result.workspace_path)
        schema = request.transport_output_schema
        if schema is None:
            schema_source = isolated_schema or request.formal_output_schema
            schema = json.loads(schema_source.read_text(encoding="utf-8"))
        command = [
            self.executable,
            "-p",
            "--agent",
            request.agent_name,
            "--tools",
            request.tools,
            "--output-format",
            "json",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--model",
            request.model or self.model,
        ]
        if request.max_budget_usd is not None:
            command.extend(["--max-budget-usd", request.max_budget_usd])
        command.extend(["--json-schema", json.dumps(self._claude_schema(schema), ensure_ascii=False, separators=(",", ":"))])
        if request.system_directive is not None:
            command.extend(["--append-system-prompt", request.system_directive])
        command.append(request.prompt)
        proc = self._run(effective_request, result, command)
        self._complete(effective_request, result, proc)
        try:
            envelope = json.loads(result.raw_stdout)
            model_usage = envelope.get("modelUsage") if isinstance(envelope, dict) else None
            if isinstance(model_usage, dict) and model_usage:
                first_model = next(iter(model_usage.values()))
                if isinstance(first_model, dict) and first_model.get("canonicalModel"):
                    result.model = str(first_model["canonicalModel"])
                else:
                    result.model = str(next(iter(model_usage)))
        except (json.JSONDecodeError, StopIteration, TypeError):
            pass
        try:
            result.parsed = parse_json_text(result.raw_stdout, request.stage)
        except ValueError as exc:
            result.error_category = "parsing"
            result.error_detail = str(exc)
            raise RuntimeInvocationError(result.error_category, result.error_detail, result) from exc
        return result


class CodexRuntime(_SubprocessRuntime):
    """Codex CLI adapter using one ephemeral ``codex exec`` per item."""

    provider = "codex"

    def __init__(self, *, executable: str | None = None, model: str | None = None, runner: Runner | None = None, cli_version: str | None = None) -> None:
        super().__init__(executable=executable, model=model or _configured_codex_model(), runner=runner, cli_version=cli_version)

    def _find_executable(self) -> str:
        # Windows often exposes both a PowerShell shim (blocked by execution
        # policy) and a .cmd shim. Prefer the direct binary from CODEX_HOME so
        # timeout cleanup does not leave a Node child holding a pipe.
        configured = _configured_codex_executable()
        if configured:
            return configured
        for name in ("codex.exe", "codex", "codex.cmd"):
            found = shutil.which(name)
            if found:
                return found
        # Keep the missing executable as a normal invocation failure so the
        # caller can persist the required infrastructure sidecar.
        return "codex"

    def _process_error_category(self, diagnostic: str) -> str:
        lowered = diagnostic.lower()
        if "invalid_json_schema" in lowered or "invalid json schema" in lowered:
            return "CODEX_SCHEMA_COMPATIBILITY_ERROR"
        if any(token in lowered for token in ("unauthorized", "authentication", "api key", "invalid token", "login")):
            return "CODEX_AUTH_ERROR"
        if any(
            token in lowered
            for token in (
                "socket",
                "websocket",
                "dns",
                "econn",
                "connection refused",
                "connection reset",
                "failed to connect",
                "network is unreachable",
                "network error",
                "error sending request",
            )
        ):
            return "CODEX_NETWORK_ERROR"
        if any(token in lowered for token in ("rate limit", "session limit", "too many requests", "usage limit")):
            return "infrastructure"
        return "CODEX_PROCESS_ERROR"

    def _artifact_paths(self, request: InvocationRequest, invocation_id: str) -> tuple[Path, Path, Path | None]:
        stdout_path, stderr_path, _ = super()._artifact_paths(request, invocation_id)
        last_message_path = request.artifact_dir / f"{request.stage}-{invocation_id}.last-message.json"
        return stdout_path, stderr_path, last_message_path

    @staticmethod
    def _prompt(request: InvocationRequest) -> str:
        instructions = request.agent_definition.read_text(encoding="utf-8")
        system = request.system_directive or ""
        return (
            "AUTHORITATIVE AGENT INSTRUCTIONS (use this checked-in file as the "
            "single source of truth; do not invent or copy grammar rules):\n"
            "<agent-instructions>\n"
            f"{instructions}\n"
            "</agent-instructions>\n\n"
            "RUNTIME INVOCATION CONSTRAINTS:\n"
            f"{system}\n\n"
            "TASK-SPECIFIC INVOCATION:\n"
            f"{request.prompt}"
        )

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = self._new_result(request)
        if request.formal_output_schema is None:
            raise ValueError(f"{request.stage}: Codex invocation requires an output schema")

        effective_request, isolated_schema = self._prepare_isolated_workspace(request, result)
        if result.workspace_path is not None:
            _assert_isolated_workspace_clean(result.workspace_path)

        # Codex receives only a derived transport schema. The canonical file
        # remains the formal contract and is never rewritten or passed to the
        # Codex Structured Outputs endpoint. A caller-supplied transport shape
        # is a pre-projection (used for blinded post-stage records); it is
        # still normalized by the same Codex adapter and tied to the original
        # canonical file in provenance.
        try:
            canonical_schema = request.formal_output_schema
            source_schema: dict[str, Any] | Path = (
                request.transport_output_schema
                if request.transport_output_schema is not None
                else canonical_schema
            )
            transport_build = build_codex_transport_artifact(
                source_schema,
                canonical_schema_path=canonical_schema,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            result.completed_at = _now_iso()
            result.error_category = "CODEX_SCHEMA_COMPATIBILITY_ERROR"
            result.error_detail = f"{request.stage}: could not build Codex transport schema: {exc}"
            self._write_process_artifacts(result)
            raise RuntimeInvocationError(result.error_category, result.error_detail, result) from exc

        schema_dir = request.artifact_dir / "transport-schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        transport_schema_path = schema_dir / f"{request.stage}-{result.invocation_id}.json"
        transport_provenance_path = schema_dir / f"{request.stage}-{result.invocation_id}.provenance.json"
        transport_schema_path.write_text(
            json.dumps(transport_build.schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        transport_provenance_path.write_text(
            json.dumps(transport_build.provenance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result.transport_schema_path = transport_schema_path
        result.transport_schema_provenance_path = transport_provenance_path
        result.transport_schema_provenance = transport_build.provenance

        output_schema_path: Path = transport_schema_path
        if result.workspace_path is not None:
            output_schema_path = result.workspace_path / "schemas" / transport_schema_path.name
            output_schema_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(transport_schema_path, output_schema_path)

        if result.output_last_message_path is None:
            raise RuntimeError("Codex adapter failed to allocate --output-last-message path")
        result.output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
        result.output_last_message_path.touch()

        command = [
            self.executable,
            "exec",
            "--ephemeral",
            "--output-schema",
            str(output_schema_path.resolve()),
            "--output-last-message",
            str(result.output_last_message_path.resolve()),
        ]
        if request.sandbox is not None:
            command.extend(["--sandbox", request.sandbox])
        if request.model and request.model != "default":
            command.extend(["--model", request.model])
        elif self.model and self.model != "default":
            command.extend(["--model", self.model])
        reasoning_effort = os.environ.get("WE_E2E_CODEX_REASONING_EFFORT")
        if reasoning_effort:
            command.extend(["--config", f'model_reasoning_effort="{reasoning_effort}"'])
        cwd = effective_request.cwd
        if request.isolate_workspace:
            command.extend(["--skip-git-repo-check"])
        if cwd is not None:
            command.extend(["--cd", str(cwd.resolve())])
        command.append("-")

        proc = self._run(effective_request, result, command, stdin=self._prompt(request))
        self._complete(effective_request, result, proc)

        try:
            last_message = result.output_last_message_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result.error_category = "infrastructure"
            result.error_detail = f"{request.stage}: Codex --output-last-message could not be read: {exc}"
            raise RuntimeInvocationError(result.error_category, result.error_detail, result) from exc
        try:
            result.parsed = parse_json_text(last_message, request.stage)
        except ValueError as exc:
            result.error_category = "parsing"
            result.error_detail = str(exc)
            raise RuntimeInvocationError(result.error_category, result.error_detail, result) from exc
        try:
            result.parsed = normalize_codex_output_for_canonical(result.parsed, request.formal_output_schema)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            result.error_category = "CODEX_SCHEMA_COMPATIBILITY_ERROR"
            result.error_detail = f"{request.stage}: could not normalize Codex output for canonical validation: {exc}"
            raise RuntimeInvocationError(result.error_category, result.error_detail, result) from exc
        return result
