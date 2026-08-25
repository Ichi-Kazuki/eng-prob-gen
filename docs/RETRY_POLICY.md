# Retry policy boundary

`max_revision_cycles` is enforced by the replay state machine.

`max_generation_validation_retries` and `max_system_failure_retries` remain
configuration for a future live Generator/Reviewer/Solver integration. The
current pilot and validation drivers replay JSON produced outside the process,
so they do not synthesize retries for unavailable live agents. Stage failures
are surfaced and leave the candidate non-finalizable until corrected external
output is supplied.

This is recorded in `orchestrator/config.json` as
`stage_failure_policy: live_agent_integration_only`.
