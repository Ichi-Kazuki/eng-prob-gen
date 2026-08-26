# Live runtime adapters

`runtime/adapters.py` exposes the common `AgentRuntime` interface with
`ClaudeRuntime` and `CodexRuntime` implementations. The E2E harness keeps the
checked-in `.claude/agents/*.md` files as the instruction source for both
providers.

The existing Claude path remains the default. Run the Codex path with:

```powershell
$env:WE_E2E_RUNTIME = "codex"
python scripts/run_live_e2e.py
```

Codex calls use one `codex exec --ephemeral` process per item. Reviewer and
Solver calls use `--sandbox read-only`, an isolated workspace, and the
allowlisted input projection. The Solver and Reviewer final messages are
validated by their existing `validate_contract()` implementations after the
last-message file is read. Before a Codex call, `runtime.codex_schema` builds a
deterministic transport-only projection from the canonical schema: structural
`allOf` branches are flattened, unsupported conditional/semantic keywords are
recorded as relaxed, and the original canonical schema remains untouched.
Transport-schema provenance records both schema hashes and explicitly requires
canonical validation. Runtime facts, raw stdout/stderr paths, and the
transport provenance are stored in the separate provenance sidecar.

An isolated workspace is owned by the adapter that creates it and is removed
after every invocation, including launch, timeout, parsing, and validation
failures. `InvocationRequest.retain_workspace_on_failure` is an explicit
debug-only opt-in for retaining a failed workspace; it is disabled by default.
