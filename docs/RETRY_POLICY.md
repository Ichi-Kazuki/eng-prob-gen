# Retry policy boundary

`max_revision_cycles` remains the quality-driven Reviewer `REVISE` budget and
is kept separate from transient stage retries.

`Candidate` persists stage-specific `system_failure_retries` and
`validation_failure_retries`. `pilot_driver.py` and `validation_driver.py`
re-arm the failed Generator, Reviewer, or Solver stage while its configured
budget remains. A successful retry clears the active `failure` metadata. Once
the relevant retry limit is exceeded, the candidate is routed to
`MANUAL_REVIEW`.

Transient retries do not change `revision_count` or `generation_attempt`.
