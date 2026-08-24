# TOEFL ITP Written Expression v2.0 — 25-item LIVE Pilot Report

- Run ID: `we-v2-live-pilot-20260824`
- Scope: Written Expression only; exactly 25 initial candidates; Structure 0; replacement generation false.
- Generation unit: nine independent microbatches (3/3/3/3/3/3/3/3/1), no 25-item monolithic realization.
- Existing Smoke JSON and handwritten items were not used as the pilot cohort.

## 1. Live invocation and version lock

All 25 candidates, 25 Reviewer results, and 25 Solver results were processed through fresh live Agent invocations. Invocation IDs are stored in the raw microbatch artifacts and provenance. The three pre-existing generator microbatches retain `invocation_id: null` because that ID was unavailable when this continuation began; the six newly completed generator microbatches have IDs. Reviewer and Solver have nine recorded invocation IDs each.

| Component | Fixed version | Prompt hash (sha256) |

| Generator | Written Expression Generator v2.0 | `sha256:cf6e11db022eea60ae91daadeaed2b0bf7fbe317d80d6661fe08fbd62b06515a` |

| Reviewer | Written Expression Reviewer v2.0 | `sha256:1a2516739e83de8db8c0a58dddaac973b9960966f94a5554f42cd577d086767b` |

| Solver | existing blind Solver (unchanged) | `sha256:df1200bed2b158dbe3151dc67b50ed5ec2359645ffa22c9a9d350a74ece22b2a` |

| Orchestrator | existing consensus policy | unchanged; no relaxation |


## 2. Core pilot metrics

| Metric | Result |

| Initial generated | 25 |

| Generator schema pass | 22/25 |

| Format validator pass | 25/25 |

| Plan conformance (final cohort) | 21/25 |

| Final AUTO_ACCEPT | 22/25 (88.00%) |

| MANUAL_REVIEW / DISCARDED / REJECTED | 3 / 0 / 0 |


Generator schema was 22/25 because items 013–015 from the pre-existing micro-05 artifact lacked the required `format_metadata.diagnostics` fields. The deterministic validator still passed all 25, and these three were explicitly blocked from AUTO_ACCEPT and routed to MANUAL_REVIEW.

## 3. Reviewer and revision

| Round | PASS | REVISE | REJECT |

| Round 1 | 21 | 4 | 0 |

| Eventual | 25 | 0 | 0 |


| Validity split | Count |

| grammar PASS / FAIL / AMBIGUOUS | 25 / 0 / 0 |

| format PASS / WARN / FAIL | 21 / 4 / 0 |

| grammar PASS + format WARN | 4 |


Revision success: 4/4 (derived from the recorded Round-2 Reviewer results).

## 4. Solver and Orchestrator

| Solver metric | Result |

| Reached | 25/25 |

| A–D consensus with Generator answer | 25/25 |

| A–D disagreement | 0 |

| AMBIGUOUS / NONE | 0 / 0 |

| LOW confidence | 0 |

| Confidence | {'HIGH': 24, 'MEDIUM': 1} |


Solver consensus was 25/25, but AUTO_ACCEPT was 22/25 because the three Generator schema-invalid items were blocked independently of downstream agreement.

## 5. Format guardrails

| Guardrail / band | Count |

| PREFERRED | 21 |

| WARNING band | 1 |

| EXTREME band | 3 |

| Coverage = 100% | 0 |

| Unmarked context = 0 | 0 |

| Coverage ≥ 60% | 0 |


The four Reviewer `format WARN` results include format-band warnings/extremes; they were not treated as grammar failures. Coverage 100% and zero unmarked context did not recur.

## 6. Geometry comparison

| Cohort | n | Sentence median | Span median | Coverage median | Unmarked median | Gaps A–B / B–C / C–D |

| Official | 125 | 20 | 1.0 | 26.32% | 15 | 4 / 4 / 4 |

| v1.1 Validation | 75 | 10 | 2.0 | 100.00% | 0 | 0 / 0 / 0 |

| v2 Smoke | 10 | 21.0 | 1.0 | 22.48% | 16.0 | 2.0 / 4.0 / 4.0 |

| v2 Live Pilot | 25 | 21 | 1.0 | 25.00% | 15 | 3 / 2 / 3 |


Live Pilot is close to the Official reference on sentence length, span size, coverage, and unmarked context. Its gap medians are 3/2/3 versus the Official 4/4/4; this is a small geometry difference, not the v1.1 full-sentence partition pattern.

## 7. Failure taxonomy

| Primary reason | Count | Detail |

| other | 3 | Generator schema failure: missing diagnostics in items 013–015; blocked from AUTO_ACCEPT |


No live candidate was classified as no_genuine_error, multiple_genuine_errors, wrong_answer_key, marked_span_mismatch, alternate_parse, semantic_only_error, solver_disagreement, solver_ambiguous, solver_none, or revision_failure.

## 8. Context-drift telemetry

| Window | Grammar PASS | Reviewer PASS | AUTO_ACCEPT | Bands P/W/E | Sentence median | Coverage median | Unmarked median |

| items 1-5 | 5/5 | 5/5 | 5/5 | 5/0/0 | 20 | 23.53% | 15 |

| items 6-10 | 5/5 | 5/5 | 5/5 | 4/0/1 | 23 | 25.00% | 17 |

| items 11-15 | 5/5 | 5/5 | 2/5 | 3/0/2 | 21 | 23.53% | 15 |

| items 16-20 | 5/5 | 5/5 | 5/5 | 4/1/0 | 22 | 25.00% | 17 |

| items 21-25 | 5/5 | 5/5 | 5/5 | 5/0/0 | 20 | 30.00% | 14 |


There is no clear monotonic generation-order drift: grammar PASS stayed 5/5 in every window, and sentence/coverage/context medians oscillate rather than degrade. EXTREME format results are localized to the 6–15 region (1 + 2), so they remain a follow-up risk rather than a broad context collapse.

## 9. P0 regression

- WE v2 regression contract: PASS (6 cases, 0 recorded failures).
- Reviewer P0 hardening regression: PASS (7 cases, 0 recorded failures).
- Internal gate result: PASS; statuses are derived from the recorded regression artifacts.

## 10. Blind human-review sample

A blind payload of 12 AUTO_ACCEPT candidates was extracted. It contains only `item_id`, `section`, `sentence`, and `marked_parts`, plus the rubric; it excludes Generator answer, clean sentence, mutation record, Reviewer result, Solver result, and format diagnostics. Human responses have not been filled in yet.

File: `analysis/we_v2_pilot/we_v2_pilot_human_sample.json`

## 11. Remaining risks and recommendation

- Fix the Generator v2 emission bug that omitted required deterministic diagnostics for items 013–015 before any larger run; keep the schema gate hard.
- Review the three EXTREME-format items and the one WARNING-band item during human calibration; format warnings alone are not grammar failures.
- Complete the 12-item blind human review before production use; the current human sample is a payload, not a human quality verdict.

Recommendation for 75-item WE Validation: **proceed conditionally, not immediately**. The recorded P0 and WE v2 regression artifacts pass. The live pilot still requires the Generator schema pass rate to be corrected and re-smoked before larger generation. No 75-item generation, DB insert, or website integration was performed in this run.

## 12. Required output artifacts

- `we_v2_pilot_plan.json`
- `we_v2_pilot_initial_items.json`
- `we_v2_pilot_final_format_validation.json`
- `we_v2_pilot_provenance.json`
- `we_v2_pilot_review.json`
- `we_v2_pilot_solver.json`
- `we_v2_pilot_accepted.json`
- `we_v2_pilot_failures.json`
- `we_v2_pilot_metrics.json`
- `we_v2_pilot_human_sample.json`
- `WE_V2_PILOT_REPORT.md`

Generated from `analysis/we_v2_pilot/we_v2_pilot_metrics.json`.
