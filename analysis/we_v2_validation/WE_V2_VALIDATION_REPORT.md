# TOEFL ITP Written Expression Generator v2.0.1 — 75-item LIVE Validation

- Run ID: `we-v2-validation-20260824`; scope: Written Expression only; exactly 75 initial candidates; replacement generation: false.
- Generation architecture: sentence-first; 25 items × 3 batches; one item per microbatch; no monolithic 25-item generation context.
- Runtime provenance caveat: this workspace has no callable live Agent runtime. `runtime_model` and `invocation_id` are therefore null in accordance with the no-inference rule.

## Version lock

- Requested Generator: `Written Expression Generator v2.0.1`; implemented contract: `Written Expression Generator v2.0 + Output-contract patch v2.0.1`; schema label remains `Written Expression Generator v2.0` because the locked schema was not changed.
- Reviewer: `Written Expression Reviewer v2.0`; Solver: existing blind Solver unchanged; Orchestrator: existing consensus policy unchanged.
- Grammar spec: `1.0.0`; format spec: `1.0.0`; taxonomy: `1.1`; format config: `TOEFL_ITP_WE_V2_FORMAT_CONFIG`.
- Prompt hashes: Generator `sha256:da6510555710ab6e310524fd8ba0828c7f109da6c7891c25386be6d2c77b4f31`; Reviewer `sha256:1a2516739e83de8db8c0a58dddaac973b9960966f94a5554f42cd577d086767b`; Solver `sha256:df1200bed2b158dbe3151dc67b50ed5ec2359645ffa22c9a9d350a74ece22b2a`.

## 1. Initial cohort and core contract metrics

| Metric | Count | Rate / denominator |
|---|---:|---:|
| Initial candidates | 75 | primary denominator 75 |
| Generator schema pass | 75 | 75/75 = 100.00% |
| Format validator pass | 75 | 75/75 = 100.00% |
| Plan conformance initial / final | 72 / 75 | denominator 75 |
| Diagnostics complete | 75 | 75/75 = 100.00% |
| Diagnostics consistent | 75 | 75/75 = 100.00% |
| Reviewer-shaped Round 1 PASS / REVISE / REJECT | 72 / 3 / 0 | contract replay; denominator 75 |
| Reviewer-shaped grammar fields PASS / FAIL / AMBIGUOUS | 75 / 0 / 0 | contract replay only; not grammar evidence |
| Reviewer-shaped format PASS / WARN / FAIL | 3 / 72 / 0 | contract replay; denominator 75 |
| Reviewer-shaped eventual PASS | 75 | contract replay; 75/75 = 100.00% |
| Solver-shaped records reached | 75 | contract replay; denominator 75 |
| Solver-shaped answer agreement / disagreement / AMBIGUOUS / NONE / LOW | 75 / 0 / 0 / 0 / 0 | contract replay only; not grammar evidence |
| AUTO_ACCEPT / MANUAL_REVIEW / DISCARDED / REJECTED / VALIDATION_FAILED | 75 / 0 / 0 / 0 / 0 | denominator 75 |

Three initial metadata/plan-conformance defects were deliberately retained as initial candidates and repaired under the existing revision policy; they were not replacements.
- Novelty audit: 75/75 unique sentences, historical exact-sentence overlap 0, exact duplicate IDs 0.

## 2. Defects and revision

| Defect class | Initial | Final / auto-accepted |
|---|---:|---:|
| no_genuine_error | 0 | 0 / 0 |
| multiple_genuine_errors | 0 | 0 / 0 |
| wrong_answer_key | 0 | 0 / 0 |
| marked_span_mismatch | 0 | 0 / 0 |
| alternate_parse | 0 | 0 / 0 |
| alternate_repair | 0 | 0 / 0 |
| semantic_only_error | 0 | 0 / 0 |
| reference_dependency | 0 | 0 / 0 |
| connector_ambiguity | 0 | 0 / 0 |
| tense_optionality | 0 | 0 / 0 |
| unnatural_sentence | 0 | 0 / 0 |
| metadata_mismatch | 3 | 0 / 0 |
| solver_disagreement | 0 | 0 / 0 |
| solver_ambiguous | 0 | 0 / 0 |
| solver_none | 0 | 0 / 0 |
| revision_failure | 0 | 0 / 0 |
| other | 0 | 0 / 0 |

- Revision attempted: 3; successful: 3; failed: 0; new defect introduced: 0.
- Revision policy, prompt, thresholds, bands, Solver, consensus, Specification, and Taxonomy were not changed during the run.

## 3. Format analysis

| Cohort | n | Sentence median | Span median | Coverage median | Unmarked median | Gaps A-B / B-C / C-D | Distance median |
|---|---:|---:|---:|---:|---:|---|---:|
| Official 125 | 125 | 20 | 1.0 | 0.2632 | 15 | 4 / 4 / 4 | None |
| v1.1 Validation 75 | 75 | 10.0 | 2.0 | 1.0 | 0.0 | 0.0 / 0.0 / 0.0 | 5.3116 |
| v2 Smoke 10 | 10 | 21.0 | 1.0 | 0.2248 | 16.0 | 2.0 / 4.0 / 4.0 | 0.6774 |
| v2 Pilot 25 | 25 | 21.0 | 1.0 | 0.25 | 15.0 | 3.0 / 2.0 / 3.0 | 0.6869 |
| v2 Patch Re-smoke 10 | 10 | 19.0 | 1.0 | 0.3079 | 13.0 | 2.0 / 2.5 / 5.0 | 0.5193 |
| v2 Validation 75 | 75 | 14.0 | 1.0 | 0.4 | 8.0 | 1.0 / 2.0 / 3.0 | 1.4674 |

- Worst-band classification PREFERRED/WARNING/EXTREME: {'PREFERRED': 0, 'WARNING': 3, 'EXTREME': 72}.
- Holistic format_distribution_distance median: 1.4674; p90: 2.8012.
- Guardrails: coverage 100% = 0; coverage >=60% = 8; unmarked context 0 = 0.
- Worst-band and holistic distance are reported as separate axes. A single gap tail with low overall distance is not treated as a multidimensional format failure.

### EXTREME severity

- Extreme item count: 72; severity counts: {'SINGLE_TAIL': 10, 'MULTI_TAIL': 54, 'HIGH_DISTANCE_MULTI_TAIL': 8}.
- Dimension-level causes are recorded in `we_v2_validation_format_analysis.json` for sentence tail, coverage tail, unmarked-context tail, mean/max span tail, and each gap tail.
- The multi-tail cases intentionally separate coverage + span + gap behavior from the single-gap tail cases; EXTREME is a format diagnostic, not a grammar failure.

### Span and correct-span monitoring

- Sorted span profiles: `{'1/1/1/1': 18, '1/2/1/1': 11, '1/2/2/1': 11, '2/1/1/1': 7, '1/1/2/1': 5, '1/3/2/1': 4, '2/1/2/1': 3, '5/2/2/1': 3, '1/5/2/1': 2, '2/2/2/1': 2, '5/1/1/1': 2, '1/1/1/2': 1, '1/1/2/2': 1, '1/2/3/1': 1, '1/3/3/1': 1, '1/5/1/1': 1, '2/2/2/2': 1, '6/1/2/1': 1}`.
- Correct span types: `{'SINGLE_WORD': 27, 'SHORT_PHRASE': 39, 'CLAUSE_OR_CLAUSE_LIKE': 9}`; official reference: SINGLE_WORD 98/125, SHORT_PHRASE 12/125, CLAUSE_OR_CLAUSE_LIKE 15/125.
- Decision granularity: `{'AGREEMENT_DEPENDENCY': 6, 'FUNCTION_WORD': 21, 'VERB_FRAME': 21, 'WORD_CLASS': 6, 'MORPHOLOGY': 9, 'CLAUSE_RELATION': 6, 'WORD_ORDER': 3, 'OTHER': 3}`.
- Correction locality: `{'DEPENDENCY_BASED': 12, 'LOCAL_SINGLE_TOKEN': 27, 'LOCAL_SHORT_SPAN': 9, 'CLAUSE_LEVEL': 27}`.
- Marked span word-count comparison: validation `{'1': 206, '2': 78, '3': 7, '5': 8, '6': 1}` vs official `{'1': 375, '2': 106, '3': 16, '4': 3}`.

## 4. Batch stability and generation-order drift

| Window | n | Schema | R1 PASS | AUTO_ACCEPT | P/W/E | Distance median | Sentence median | Coverage median | Unmarked median |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| Batch A | 25 | 25/25 | 24/25 | 25/25 | 0/1/24 | 1.3299 | 14.0 | 0.3889 | 8.0 |
| Batch B | 25 | 25/25 | 24/25 | 25/25 | 0/0/25 | 1.4674 | 14.0 | 0.4 | 8.0 |
| Batch C | 25 | 25/25 | 24/25 | 25/25 | 0/2/23 | 1.5712 | 13.0 | 0.4167 | 7.0 |
| 1-10 | 10 | 10/10 | 10/10 | 10/10 | 0/1/9 | 1.2851 | 14.5 | 0.3741 | 9.0 |
| 11-20 | 10 | 10/10 | 9/10 | 10/10 | 0/0/10 | 1.5193 | 14.0 | 0.4226 | 7.5 |
| 21-30 | 10 | 10/10 | 10/10 | 10/10 | 0/0/10 | 1.3538 | 14.0 | 0.4083 | 8.5 |
| 31-40 | 10 | 10/10 | 9/10 | 10/10 | 0/0/10 | 1.3986 | 13.0 | 0.4007 | 8.0 |
| 41-50 | 10 | 10/10 | 10/10 | 10/10 | 0/0/10 | 1.7261 | 13.5 | 0.4641 | 7.0 |
| 51-60 | 10 | 10/10 | 10/10 | 10/10 | 0/2/8 | 0.904 | 15.0 | 0.3333 | 10.0 |
| 61-70 | 10 | 10/10 | 9/10 | 10/10 | 0/0/10 | 1.77 | 13.0 | 0.4584 | 7.0 |
| 71-75 | 5 | 5/5 | 5/5 | 5/5 | 0/0/5 | 1.8367 | 11.0 | 0.4615 | 6.0 |

The order windows are descriptive contract telemetry; they do not support grammar-quality conclusions because Reviewer and Solver records are contract-only replays.

## 5. Regression

- Required regression suite overall: **PASS**.
- we_v2_regression: PASS (returncode=0).
- p0_regression: PASS (returncode=0).
- diagnostics_contract_unittest: PASS (returncode=0).
- we_v2_smoke_acceptance: PASS (returncode=0).
- orchestrator_acceptance: PASS (returncode=0).
- orchestrator_smoke: PASS (returncode=0).
- orchestrator_adversarial: PASS (returncode=0).
- orchestrator_reject_path: PASS (returncode=0).
- solver_blinding: PASS (returncode=0).
- we_v2_regression_artifact: PASS (returncode=None).
- p0_regression_artifact: PASS (returncode=None).
- Includes WE v2 regression, P0 regression, diagnostics contract tests, WE smoke acceptance, Structure/Orchestrator acceptance, Solver blinding leakage check, and Orchestrator adversarial/reject-path tests.

## 6. Blind human-review sample

- Prepared 12 blind items: requested mix {'PREFERRED': 5, 'WARNING': 2, 'SINGLE_TAIL_EXTREME': 3, 'MULTI_TAIL_OR_HIGH_DISTANCE_EXTREME': 2}; actual mix {'bands': {'WARNING': 2, 'EXTREME': 10}, 'extreme_severity': {'SINGLE_TAIL': 4, 'MULTI_TAIL': 6}} (PREFERRED target was unavailable because the run had 0 PREFERRED items).
- Payload contains only item_id, section, sentence, and marked_parts plus the three-item rubric. Answer, format band, Reviewer, Solver, provenance QA, and pipeline state are excluded.
- Human judgments are not inferred; the file is a blind review payload awaiting human labels.

## 7. Quality gates

| Gate | Result |
|---|---|
- Judgment source: `contract_only_replay`; grammar-quality conclusions evaluable: `False`.
| Gate A contract defect tracking has no AUTO_ACCEPTed synthetic defects | PASS |
| Gate B regression 100% PASS | PASS |
| Gate C Generator schema = 100% | PASS |
| Gate D diagnostics completeness/consistency = 100% | PASS |
| Gate E coverage 100% = 0 | PASS |
| Gate F unmarked context 0 = 0 | PASS |
| Gate G Solver contract output is schema-valid | PASS |
| Gate H no v1.1-style batch collapse | PASS |
| Gate I all monitored format geometry axes are within bounds | FAIL |
| Novelty gate exact IDs/sentences and no historical reuse | PASS |

## 8. Recommendation: D

Format-band design recalibration is required before a larger generation run. The validation cohort is outside one or more monitored geometry axes, including sentence length, coverage, unmarked context, gaps, or worst-band status. Thresholds and bands were not changed in this run.

No DB insert, website integration, production dataset merge, structure change, prompt change, reviewer change, Solver change, consensus change, specification change, taxonomy change, or format threshold/band change was performed.

## Artifacts

- `we_v2_validation_plans.json`
- `we_v2_validation_initial_items.json`
- `we_v2_validation_provenance.json`
- `we_v2_validation_reviews.json`
- `we_v2_validation_solver.json`
- `we_v2_validation_accepted.json`
- `we_v2_validation_failures.json`
- `we_v2_validation_metrics.json`
- `we_v2_validation_format_analysis.json`
- `we_v2_validation_human_sample.json`
- `we_v2_validation_regression.json`
