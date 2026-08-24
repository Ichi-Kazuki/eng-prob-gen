# WE Generator v2.0.1 Diagnostics Emission Patch Report

- Run: `we-v2-fixture-smoke-20260824-patch-01`
- Scope: output-contract bug fix and deterministic fixture contract replay
- Not run: 75-item Validation, DB insert, Website integration

## 1. Root cause

Pilot items we-v2-pilot-013 through -015 emitted an empty format_metadata.diagnostics object. Deterministic geometry validation, eventual Reviewer PASS, and Solver consensus were positive; this was a Generator output-contract emission failure, not a content failure. The strict 22/25 schema gate was correct.

## 2. Fix

Added inject_canonical_diagnostics() and emit_output.py. The completed sentence, marked spans, and grammar metadata now pass through deterministic format_diagnostics() before schema validation. The schema gate and AUTO_ACCEPT policy remain strict and unchanged.

## 3. Deterministic diagnostics ownership

All mechanically derivable values are owned by deterministic code: word counts, span counts, mean/max, coverage, unmarked context, gaps, correct span values, percentile profile, distance, bands, and token indices. If computation fails, no placeholder is emitted; the candidate is routed to VALIDATION_FAILED.

## 4. Regression results

- Missing-diagnostics fixtures: 3/3 rejected before injection and accepted after canonical injection.
- Fail-closed malformed candidate: PASS.
- Existing suites: we_v2=PASS, p0=PASS, structure=PASS, solver_blinding=PASS, orchestrator=PASS.

## 5. Fixture contract-replay schema pass

Fixture items: Generator schema 10/10; format validator 10/10. This is not a live generation or independent Reviewer/Solver quality gate.

## 6. Reviewer results

Reviewer contract 10/10; grammar PASS 10/10.

## 7. Solver results

Solver fixture contract 10/10; fixture consensus 10/10; Orchestrator AUTO_ACCEPT 10/10. These results do not measure independent live solving.

## 8. Format P/W/E

PREFERRED=2, WARNING=2, EXTREME=6. Existing bands and thresholds were fixed; the Generator was not tuned to force EXTREME to zero.

| item | band |
|---|---|
| we-v2-fixture-smoke-20260824-patch-01-001 | EXTREME |
| we-v2-fixture-smoke-20260824-patch-01-002 | EXTREME |
| we-v2-fixture-smoke-20260824-patch-01-003 | EXTREME |
| we-v2-fixture-smoke-20260824-patch-01-004 | EXTREME |
| we-v2-fixture-smoke-20260824-patch-01-005 | WARNING |
| we-v2-fixture-smoke-20260824-patch-01-006 | EXTREME |
| we-v2-fixture-smoke-20260824-patch-01-007 | EXTREME |
| we-v2-fixture-smoke-20260824-patch-01-008 | PREFERRED |
| we-v2-fixture-smoke-20260824-patch-01-009 | PREFERRED |
| we-v2-fixture-smoke-20260824-patch-01-010 | WARNING |

## 9. Geometry

Diagnostics completeness 10/10; consistency 10/10; coverage=100% count 0; unmarked context=0 count 0.

## 10. Targeted human sample

Eight items were blind-extracted from the 25-item Pilot with strata EXTREME=3, WARNING=1, PREFERRED=4. human_targeted_sample.json displays only sentence and marked_parts A-D. Answers, band, and pipeline state are in the separate human_targeted_sample_key.json.

## 11. Proceed to 75-item Validation?

Yes, the patch smoke gate is PASS and the next stage may proceed under separate approval. This run did not start 75-item Validation, DB insert, or Website integration.

## Versioning

Output-contract-only patch recorded as WE Generator v2.0.1. Item agent_version remains Written Expression Generator v2.0 for schema compatibility. Reviewer v2.0 is unchanged.

## Artifacts

schema_bug_regression.json; fixture_smoke_items.json; fixture_smoke_review.json; fixture_smoke_solver.json; fixture_smoke_metrics.json; human_targeted_sample.json; human_targeted_sample_key.json; WE_V2_PATCH_REPORT.md.
