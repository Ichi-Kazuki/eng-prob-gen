"""Structure-specific construction of the repository's provider-neutral runtime."""

from __future__ import annotations

import os

from runtime.adapters import AgentRuntime, ClaudeRuntime, CodexRuntime


def configured_runtime(provider: str | None = None, model: str | None = None) -> AgentRuntime:
    selected = (provider or os.environ.get("STRUCTURE_RUNTIME") or os.environ.get("WE_E2E_RUNTIME") or "claude").lower()
    if selected in {"codex", "codex-cli"}:
        return CodexRuntime(model=model or os.environ.get("STRUCTURE_CODEX_MODEL"))
    if selected in {"claude", "claude-code", "claude-code-cli"}:
        return ClaudeRuntime(model=model or os.environ.get("STRUCTURE_MODEL", "sonnet"))
    raise ValueError(f"unsupported Structure runtime provider: {selected!r}")
