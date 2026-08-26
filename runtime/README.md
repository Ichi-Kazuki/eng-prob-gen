# Live runtime adapters

`runtime/adapters.py` exposes the common `AgentRuntime` interface with
`ClaudeRuntime` and `CodexRuntime` implementations. The E2E harness keeps the
checked-in `.claude/agents/*.md` files as the instruction source for both
providers.

The existing Claude path remains the default. Run the Codex path with:

```powershell
$env:WE_E2E_RUNTIME = "codex"
python analysis/we_v2_1_2_live_e2e/run_live_e2e.py
```

Codex calls use one `codex exec --ephemeral` process per item. Reviewer and
Solver calls use `--sandbox read-only`, an isolated workspace, and the
allowlisted input projection. The Solver and Reviewer final messages are
validated by their existing `validate_contract()` implementations after the
last-message file is read. Runtime facts and raw stdout/stderr paths are
stored in the separate provenance sidecar.
