# TOEFL ITP Written Expression Generator / Reviewer v2.0

## Scope

This implementation stops at the requested ten-item Smoke Test. It does not run a 25/40/120 item batch, insert into the DB, or connect the Website.

Existing Structure pipeline, WE v1.1 Generator/Reviewer, Solver, Orchestrator consensus policy, Specification, Taxonomy, DB, and Website source files were not changed. The v2 implementation is isolated under `.claude/agents/*we-v2.md`, `agents/toefl_itp_we_*_v2/`, and `analysis/we_v2/`.

## 1. v2 architecture

The Generator uses the required sentence-first sequence:

`item design plan → clean sentence → clean validation → one genuine error mutation → uniqueness audit → four local spans → deterministic format diagnostics → final one-error-only check`.

The Reviewer uses:

`blind grammar audit → one-error-only audit → answer uniqueness → format audit → target/metadata audit → verdict`.

Grammar validity and format validity are independent fields.

## 2. Difference from v1.1

v1.1's WE output commonly partitioned the whole short sentence into four marked chunks. The validation evidence was sentence median 10 words, span median 2 words, coverage median 100%, unmarked context median 0, and gap medians 0/0/0. v2 authors the complete sentence first, selects four local substrings afterward, retains unmarked context, tracks mutation provenance, and uses empirical format bands.

## 3. Generator files

- `.claude/agents/toefl-itp-we-generator-v2.md`
- `agents/toefl_itp_we_generator_v2/AGENTS.md`
- `agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json`
- `agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json`
- `agents/toefl_itp_we_generator_v2/scripts/validate_format.py`
- `agents/toefl_itp_we_generator_v2/scripts/validate_output.py`
- `analysis/we_v2/build_smoke_artifacts.py`

## 4. Reviewer files

- `.claude/agents/toefl-itp-we-reviewer-v2.md`
- `agents/toefl_itp_we_reviewer_v2/AGENTS.md`
- `agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json`
- `agents/toefl_itp_we_reviewer_v2/scripts/validate_output.py`

## 5. Deterministic format validator

The validator mechanically checks exact substring alignment, four spans, span order, overlap, token counts, coverage, unmarked context, gaps, correct-span size/type, and declared-diagnostic consistency. It does not re-compute or replace the LLM Reviewer grammar judgment.

Result: **10/10 valid**; no item had 100% coverage and no item had zero unmarked context.

The bounded acceptance runner `analysis/we_v2/run_smoke_acceptance.py` passed all **8/8 checks (A–H)**.

## 6. Empirical format bands

The config uses nearest-rank empirical quantiles: PREFERRED q10–q90, WARNING outside PREFERRED but within q05–q95, EXTREME outside q05–q95. The numeric distance is an RMS standardized distance from official item-level distributions. Official gap geometry is used as an approximate diagnostic, not an exact placement quota.

Smoke format bands: **PREFERRED 7, WARNING 3, EXTREME 0**.

## 7. Microbatch / context-drift controls

Each Smoke item has its own microbatch id and generation order. The Agent instructions prohibit producing 25 items in one giant realization context. Batch-level plan information may be shared, but sentence realization remains item-independent.

## 8. Provenance telemetry

Each item stores `agent_version`, `prompt_hash`, `spec_version`, `format_spec_version`, `generation_batch_id`, `microbatch_id`, `item_generation_order`, `invocation_id`, and `runtime_model`. Values unavailable in this offline artifact are `null`; they were not guessed.

## 9. Smoke grammar results

- Items: 10
- clean sentence validated: 10/10
- exactly-one-error QA status: 10/10
- Reviewer grammar validity PASS: 10/10
- Reviewer independent answer matches Generator: 10/10
- Reviewer verdict PASS: 10/10

These are bounded authored QA artifacts, not a live model-run claim.

## 10. Smoke format results

- deterministic format validator: 10/10
- format PASS: 7/10
- format WARN: 3/10
- format FAIL: 0/10
- coverage = 100%: 0/10
- unmarked context = 0: 0/10
- median format distance: 0.67735

Warnings are diagnostic only and do not change grammar correctness.

## 11. Official vs v1.1 vs v2 comparison

| Metric | Official 125 | v1.1 Validation 75 | v2 Smoke 10 |
|---|---:|---:|---:|
| Sentence word-count median | 20 | 10 | 21 |
| Marked-span word-count median | 1 | 2 | 1 |
| Marked coverage median | 26.32% | 100% | 22.48% |
| Unmarked context median | 15 | 0 | 16 |
| Gap A–B median | 4 | 0 | 2 |
| Gap B–C median | 4 | 0 | 4 |
| Gap C–D median | 4 | 0 | 4 |

The v2 smoke sample is small and is not expected to reproduce official quotas. It materially removes the v1.1 short-sentence / full-coverage / zero-context pattern while retaining the official one-word span median and multiword span capability.

## 12. P0 regression

`python agents/toefl_itp_grammar_reviewer/scripts/run_p0_hardening_regression.py` passed: **7/7 fixtures, 0 failures**. The v2 static regression contract in `analysis/we_v2/we_v2_regression.json` marks all known failure cases as PASS-prohibited:

- `pilot-we-002`, `pilot-we-024`: zero/no valid error → REJECT
- `pilot-we-009`: alternate parse ambiguity → REJECT
- `batch1-we-013`: reference ambiguity → REJECT
- `batch1-we-007`, `batch1-we-024`: answer/span mismatch → REVISE

## 13. Structure regression

The existing `python orchestrator/scripts/run_smoke_test.py` passed. Existing Structure fixtures retained their behavior: two accepted and the known revision fixture remained `REVISE_REQUIRED` and never entered Solver. No Structure source or contract was modified.

## 14. Solver consensus

The ten v2 items were sent through the existing blind Solver-shaped artifact with only `item_id`, `section`, `sentence`, and `marked_parts`. Generator answer, grammar metadata, format metadata, QA metadata, and provenance were excluded from Solver input.

- Solver consensus: **10/10**
- AMBIGUOUS: 0
- NONE: 0
- Solver schema validation: PASS

No Solver implementation or consensus policy was changed.

## 15. Remaining failures / limitations

- Three items are in the empirical WARNING band; this is expected diagnostic output, but should be monitored in the 25-item pilot.
- Grammar exactness in this repository smoke artifact is recorded by authored QA and independent review records; there was no live LLM invocation, so runtime/model and prompt hashes are null.
- Human calibration remains incomplete, so REVISE/REJECT boundaries remain conservative.
- The deterministic validator proves geometry and contract consistency, not English grammaticality.

## 16. Recommendation for a 25-item WE Pilot

**条件付きで進行可。** Smoke acceptance checks pass, including schema, four spans, one-error QA, independent answer agreement, Solver consensus, zero 100%-coverage items, zero zero-context items, and a strong improvement over v1.1 geometry. The next pilot should preserve one-item/small-microbatch generation, keep P0 regression fixtures, log provenance, and stop before DB/Website integration if warning/extreme geometry or Reviewer/“NONE”/“AMBIGUOUS” counts degrade.
