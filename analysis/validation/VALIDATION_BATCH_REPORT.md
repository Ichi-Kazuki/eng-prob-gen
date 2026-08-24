# TOEFL ITP Grammar Pipeline v1.1 — Validation Batch Report

> Scope: isolated new validation cohort only. No production Question DB insertion, website connection, production merge, Specification/taxonomy/Solver/consensus-policy changes, or mid-run Generator/Reviewer tuning was performed.

## 1. Executive summary

The validation cohort contained exactly **120 initial candidates**: 45 Structure and 75 Written Expression. Final routing was **83 AUTO_ACCEPTED (69.2%)**, 5 MANUAL_REVIEW, 2 DISCARDED, and 30 REJECTED. The pipeline and regression suite completed, but the internal 90% acceptance gates did not.

**Readiness classification: C. Another hardening cycle recommended.** The main reasons are overall and Written Expression AUTO_ACCEPT below the internal 90% gates, four Reviewer false negatives, and marked batch-to-batch instability despite zero P0 same-type AUTO_ACCEPT recurrence and a passing regression suite.

## 2. Version lock

- Generator v1.1: `sha256:3567f2b6e246`
- Reviewer v1.1: `sha256:e4142013a3cb`
- Solver unchanged: `sha256:df1200bed2b1`
- Specification: `1.0.0` current TOEFL_ITP_GRAMMAR_SPEC
- Taxonomy: `1.1` current version
- Orchestrator: current config/consensus policy; `max_revision_cycles = 2`.
- Initial candidate principle: exactly 120 IDs were tracked; replacement candidates included: 0.

## 3. Overall pipeline results

| Metric | Count | Denominator / definition |
|---|---:|---|
| initial_generated | 120 | initial candidate cohort |
| generator_schema_pass | 120 | / 120 initial candidates |
| reviewer_round1_PASS | 80 | / 120 |
| reviewer_round1_REVISE | 10 | / 120 |
| reviewer_round1_REJECT | 30 | / 120 |
| reviewer_eventual_PASS | 89 | / 120; PASS in any later allowed round |
| solver_reached | 89 | candidates after Reviewer PASS |
| solver_consensus | 83 | / 89 solver outputs; three-way A-D agreement |
| solver_disagreement | 2 | A-D output but not three-way agreement |
| solver_AMBIGUOUS | 3 | / 89 solver outputs |
| solver_NONE | 1 | / 89 solver outputs |
| solver_LOW_confidence | 1 | / 89 solver outputs |
| AUTO_ACCEPTED | 83 | / 120 initial candidates |
| MANUAL_REVIEW | 5 | final state / 120 |
| DISCARDED | 2 | final state / 120 |
| REJECTED | 30 | final state / 120 |

Rates: Generator schema 100.0%; Reviewer round-1 PASS 66.7%; eventual Reviewer PASS 74.2%; Solver consensus 93.3%; final AUTO_ACCEPT 69.2%.

## 4. Batch 1 / 2 / 3

| Batch | Reviewer round-1 PASS | Revision rate | Solver reached | NONE | AMBIGUOUS | Final AUTO_ACCEPT |
|---|---:|---:|---:|---:|---:|---:|
| batch1 | 38/40 (95.0%) | 2/40 (5.0%) | 40 | 1 | 0 | 37/40 (92.5%) |
| batch2 | 11/40 (27.5%) | 2/40 (5.0%) | 13 | 0 | 3 | 10/40 (25.0%) |
| batch3 | 31/40 (77.5%) | 6/40 (15.0%) | 36 | 0 | 0 | 36/40 (90.0%) |

Batch 2 is materially worse than Batches 1 and 3: it has a high round-1 REJECT count and lower final acceptance. The overall average would hide this instability.

## 5. Structure results

Structure: first-pass Reviewer 39/45 (86.7%); eventual Reviewer PASS 41/45; Solver consensus 38 / 41 reached; AMBIGUOUS 3; NONE 0; final AUTO_ACCEPT 38/45 (84.4%); MANUAL_REVIEW 3; discard 0.

## 6. Written Expression results

Written Expression: first-pass Reviewer 41/75 (54.7%); eventual Reviewer PASS 48/75; Solver consensus 45 / 48 reached; AMBIGUOUS 0; NONE 1; final AUTO_ACCEPT 45/75 (60.0%); MANUAL_REVIEW 2; discard 2.

Sentence-level and semantic-dependent cases require continued attention. The validation NONE case `batch1-we-013` was a reference-resolution design with no antecedent context; the Solver correctly refused to infer context, while Reviewer round 1 had passed it.

## 7. Pilot vs Validation

| Metric | Pilot | Validation |
|---|---:|---:|
| Overall AUTO_ACCEPT | 37/40 (92.5%) | 83/120 (69.2%) |
| Structure AUTO_ACCEPT | 15/15 (100.0%) | 38/45 (84.4%) |
| Written Expression AUTO_ACCEPT | 22/25 (88.0%) | 45/75 (60.0%) |
| Reviewer false negatives | 3/40 (7.5%) | 4/120 (3.3%); WE 1/75 |
| Solver AMBIGUOUS/NONE | 3/40 (7.5%) | 4/120 (3.3%) |

Pilot comparison uses the supplied Pilot baseline. Validation denominators are the full initial cohort unless explicitly marked solver-reached.

## 8. P0 failure recurrence

| Root cause | Recurrence | Detected by Generator self-prevention | Detected by Reviewer | Detected only by Solver | Final AUTO_ACCEPT |
|---|---:|---|---:|---:|---:|
| A semantic reference resolution mistaken for grammar | 1 | not instrumented | 0 | 1 | 0 |
| B parallel / coordination alternate parse | 0 | not applicable | 0 | 0 | 0 |
| C semantic connector oddity mistaken for grammar | 0 | not applicable | 0 | 0 | 0 |

No same-type P0 defect entered AUTO_ACCEPT. The only classified same-type recurrence was A (`batch1-we-013`), detected only by Solver as NONE; Generator self-prevention is not machine-instrumented, so no positive self-detection claim is made.

## 9. Reviewer false negatives

Reviewer false-negative candidates are defined as Reviewer round-1 PASS followed by Solver AMBIGUOUS or NONE: 4/120 (3.3%); WE 1/75 (1.3%).

| Item | Section | Target | Tested error type | Root cause |
|---|---|---|---|---|
| batch1-we-013 | Written Expression | REFERENCE_AND_DETERMINERS | incorrect_reference | semantic/context-dependent reference resolution presented as a grammatical error |
| batch2-struct-003 | Structure | RELATIVE_CLAUSES | N/A for Structure | alternate relative-clause parse makes a second option grammatical |
| batch2-struct-004 | Structure | ADVERBIAL_CLAUSES | N/A for Structure | multiple syntactically licensed connectors; semantic relation is underspecified |
| batch2-struct-006 | Structure | VERB_FORM_VOICE | N/A for Structure | temporal context does not force the intended verb form |

Full Reviewer checks/issues and Solver reasoning for every item are preserved in `validation_provenance.json` and the batch-level round artifacts.

## 10. Solver disagreement

A-D answer mismatches: 2; AMBIGUOUS: 3; NONE: 1. These are kept as separate categories.

| Item | Generator | Reviewer | Solver | Solver reason |
|---|---|---|---|---|
| batch1-we-007 | C | C | B | A person as the antecedent of the relative clause takes who, not which. |
| batch1-we-024 | C | C | B | Responses is countable plural, so it takes many rather than much. |

AMBIGUOUS IDs: `['batch2-struct-003', 'batch2-struct-004', 'batch2-struct-006']`.
NONE IDs: `['batch1-we-013']`.

## 11. Revision effectiveness

Initial round-1 REVISE candidates: 10; later Reviewer PASS: 9; failed after the allowed cycles: 1; success rate 90.0%.

| Item | Final revision count | Later verdicts | Success | Final state |
|---|---:|---|---|---|
| batch1-we-003 | 1 | ['PASS'] | True | ACCEPTED |
| batch1-we-023 | 1 | ['PASS'] | True | ACCEPTED |
| batch2-struct-001 | 1 | ['PASS'] | True | ACCEPTED |
| batch2-struct-009 | 1 | ['PASS'] | True | ACCEPTED |
| batch3-we-005 | 1 | ['PASS'] | True | ACCEPTED |
| batch3-we-006 | 1 | ['PASS'] | True | ACCEPTED |
| batch3-we-013 | 1 | ['PASS'] | True | ACCEPTED |
| batch3-we-017 | 1 | ['PASS'] | True | ACCEPTED |
| batch3-we-024 | 3 | ['REVISE', 'REVISE'] | False | DISCARDED |
| batch3-we-025 | 1 | ['PASS'] | True | ACCEPTED |

The failed item `batch3-we-024` reached the second revision limit and was DISCARDED by policy; no replacement was generated.

## 12. Difficulty analysis

| Difficulty | Generated | Reviewer first-pass PASS | Eventual PASS | Solver consensus | Final accepted |
|---|---:|---:|---:|---:|---:|
| EASY | 60 | 40 | 45 | 42 | 42 |
| MEDIUM | 44 | 33 | 34 | 31 | 31 |
| HARD | 16 | 7 | 10 | 10 | 10 |

Difficulty rows are descriptive. HARD-specific claims are not generalized beyond this cohort.

## 13. Grammar target analysis

### Structure

| Target | Generated | Reviewer first-pass PASS | Eventual PASS | Final accepted | Failure count | Acceptance rate |
|---|---:|---:|---:|---:|---:|---:|
| ADVERBIAL_CLAUSES | 3 | 3 | 3 | 2 | 1 | 66.7% |
| CLAUSE_STRUCTURE | 3 | 2 | 3 | 3 | 0 | 100.0% |
| COMPARATIVES_DEGREE | 3 | 1 | 2 | 2 | 1 | 66.7% |
| CONNECTORS_CONJUNCTIONS | 3 | 3 | 3 | 3 | 0 | 100.0% |
| EXISTENTIAL_EXPLETIVE | 3 | 3 | 3 | 3 | 0 | 100.0% |
| INVERSION | 3 | 2 | 2 | 2 | 1 | 66.7% |
| NONFINITE_VERB_PHRASES | 3 | 2 | 2 | 2 | 1 | 66.7% |
| NOUN_CLAUSES | 3 | 3 | 3 | 3 | 0 | 100.0% |
| PARALLEL_STRUCTURE | 3 | 3 | 3 | 3 | 0 | 100.0% |
| REFERENCE_AND_DETERMINERS | 3 | 3 | 3 | 3 | 0 | 100.0% |
| RELATIVE_CLAUSES | 3 | 3 | 3 | 2 | 1 | 66.7% |
| VERB_COMPLEMENTATION | 3 | 3 | 3 | 3 | 0 | 100.0% |
| VERB_FORM_VOICE | 3 | 3 | 3 | 2 | 1 | 66.7% |
| WORD_CLASS_FORM | 3 | 3 | 3 | 3 | 0 | 100.0% |
| WORD_ORDER_MODIFICATION | 3 | 2 | 2 | 2 | 1 | 66.7% |

Small category counts should not be treated as stable category-level estimates.

### Written Expression

| Target | Generated | Reviewer first-pass PASS | Eventual PASS | Final accepted | Failure count | Acceptance rate |
|---|---:|---:|---:|---:|---:|---:|
| ADVERBIAL_CLAUSES | 1 | 1 | 1 | 1 | 0 | 100.0% |
| CLAUSE_STRUCTURE | 2 | 2 | 2 | 2 | 0 | 100.0% |
| COMPARATIVES_DEGREE | 3 | 2 | 2 | 2 | 1 | 66.7% |
| CONNECTORS_CONJUNCTIONS | 6 | 4 | 4 | 4 | 2 | 66.7% |
| EXISTENTIAL_EXPLETIVE | 1 | 1 | 1 | 1 | 0 | 100.0% |
| NONFINITE_VERB_PHRASES | 8 | 4 | 5 | 5 | 3 | 62.5% |
| NOUN_CLAUSES | 1 | 1 | 1 | 1 | 0 | 100.0% |
| PARALLEL_STRUCTURE | 8 | 4 | 5 | 5 | 3 | 62.5% |
| REFERENCE_AND_DETERMINERS | 12 | 6 | 7 | 5 | 7 | 41.7% |
| RELATIVE_CLAUSES | 4 | 2 | 2 | 1 | 3 | 25.0% |
| VERB_COMPLEMENTATION | 6 | 3 | 4 | 4 | 2 | 66.7% |
| VERB_FORM_VOICE | 9 | 3 | 5 | 5 | 4 | 55.6% |
| WORD_CLASS_FORM | 10 | 7 | 7 | 7 | 3 | 70.0% |
| WORD_ORDER_MODIFICATION | 4 | 1 | 2 | 2 | 2 | 50.0% |

Small category counts should not be treated as stable category-level estimates.

## 14. WE error-type / error-scope analysis

### Tested error type

| Error type | Generated | Reviewer first-pass PASS | Solver consensus | Final accepted | NONE | AMBIGUOUS |
|---|---:|---:|---:|---:|---:|---:|
| agreement_error | 10 | 7 | 6 | 6 | 0 | 0 |
| extraneous_element | 1 | 1 | 1 | 1 | 0 | 0 |
| incorrect_part_of_speech | 15 | 8 | 8 | 8 | 0 | 0 |
| incorrect_reference | 2 | 1 | 1 | 1 | 1 | 0 |
| incorrect_relative_marker | 4 | 2 | 1 | 1 | 0 | 0 |
| incorrect_subordinator | 3 | 2 | 2 | 2 | 0 | 0 |
| missing_required_element | 3 | 1 | 1 | 1 | 0 | 0 |
| wrong_degree_form | 3 | 2 | 2 | 2 | 0 | 0 |
| wrong_preposition_collocation | 8 | 5 | 6 | 6 | 0 | 0 |
| wrong_verb_form | 16 | 7 | 10 | 10 | 0 | 0 |
| wrong_voice | 4 | 3 | 3 | 3 | 0 | 0 |
| wrong_word_order | 6 | 2 | 4 | 4 | 0 | 0 |

### Error scope

| Scope | Generated | Reviewer first-pass PASS | Solver consensus | Final accepted | NONE | AMBIGUOUS |
|---|---:|---:|---:|---:|---:|---:|
| clause_level | 27 | 16 | 18 | 18 | 0 | 0 |
| cross_clause | 6 | 1 | 2 | 2 | 0 | 0 |
| local | 39 | 23 | 24 | 24 | 0 | 0 |
| sentence_level | 3 | 1 | 1 | 1 | 1 | 0 |

The sentence-level semantic/reference case noted above was not AUTO_ACCEPTED. The evidence supports continued scrutiny of sentence-level and context-dependent constructions.

## 15. Answer-position analysis

### Structure

- planned: `{'A': 11, 'B': 12, 'C': 12, 'D': 10}`
- initial generated: `{'A': 11, 'B': 13, 'C': 12, 'D': 9}`
- accepted final items: `{'C': 12, 'B': 10, 'A': 11, 'D': 5}`

### Written Expression

- planned: `{'A': 21, 'B': 20, 'C': 18, 'D': 16}`
- initial generated: `{'A': 18, 'B': 21, 'C': 24, 'D': 12}`
- accepted final items: `{'D': 6, 'B': 16, 'A': 10, 'C': 13}`

Position filtering effects are reported descriptively; the batch plans were heuristic near-even spreads, not hard quotas.

## 16. Regression suite

Regression suite status: **PASS (9/9)**.

| Test | Status |
|---|---|
| P0 regression (7 fixtures) | PASS |
| Generator smoke schema | PASS |
| Reviewer adversarial output schema | PASS |
| Solver adversarial schema | PASS |
| Orchestrator smoke / gen-struct-003 | PASS |
| Orchestrator adversarial | PASS |
| Reject path | PASS |
| Orchestrator acceptance (18/18) | PASS |
| Validation provenance schema | PASS |

The suite includes the P0 regression 7-item contract, Generator smoke, Reviewer adversarial, Solver adversarial, Orchestrator smoke/gen-struct-003 guard, reject path, acceptance 18/18, and validation provenance shape.

## 17. Human review sample

A deterministic stratified sample of 20 AUTO_ACCEPTED items was isolated in `human_review_sample.json`: Structure 8, Written Expression 12. No human scoring was performed.

## 18. Quality gate results

| Gate | Status | Value |
|---|---|---|
| Gate A critical defect AUTO_ACCEPTED == 0 | **PASS** | `0` |
| Gate B regression suite 100% PASS | **PASS** | `9/9` |
| Gate C overall AUTO_ACCEPT >= 90% | **FAIL** | `{'n': 83, 'd': 120, 'percent': 69.17}` |
| Gate D WE AUTO_ACCEPT >= 90% | **FAIL** | `{'n': 45, 'd': 75, 'percent': 60.0}` |
| Gate E Reviewer false negative lower than Pilot | **PASS** | `{'overall': {'n': 4, 'd': 120, 'percent': 3.33}, 'WE': {'n': 1, 'd': 75, 'percent': 1.33}}` |
| Gate F Solver NONE/AMBIGUOUS absolute rate lower than Pilot | **PASS** | `{'n': 4, 'd': 120, 'percent': 3.33}` |
| Gate G P0 same-type AUTO_ACCEPT == 0 | **PASS** | `0` |

Gate C and Gate D fail the provisional internal >=90% thresholds. Gate A, B, F, and G pass; Gate E passes under both the full-cohort and WE-denominator comparison used here.

## 19. Remaining risks

- Batch 2 has substantially lower acceptance and a high round-1 REJECT count; the cause should be investigated before larger generation.
- Four Reviewer false negatives remain, including three Structure ambiguity cases and one WE reference-resolution NONE case.
- The Generator self-prevention gate is not emitted as structured telemetry, so recurrence analysis cannot prove that the Generator caught a risk internally.
- Category-level target/difficulty/error-type rates with small cells are descriptive only.
- Human review has not yet scored the sample.

## 20. Production-readiness recommendation

**C. Another hardening cycle recommended.** The regression suite is green and no same-type P0 defect was AUTO_ACCEPTED, but overall AUTO_ACCEPT is below 90%, Written Expression is below 90%, and batch stability is insufficient for larger generation without another hardening/validation cycle.

## Final report summary

- total AUTO_ACCEPT: 83
- AUTO_ACCEPT rate: 69.2%
- Structure rate: 38/45 (84.4%)
- WE rate: 45/75 (60.0%)
- Reviewer round1 PASS/REVISE/REJECT: 80/10/30
- Reviewer false negative: 4/120; WE 1/75
- Solver AMBIGUOUS/NONE: 3/1
- P0 recurrence: A 1, B 0, C 0; P0 AUTO_ACCEPT 0
- Revision success: 9/10
- Regression status: PASS (9/9)
- Quality gates: see section 18; Gates C/D FAIL, Gates A/B/F/G PASS, Gate E PASS
- Readiness: C — Another hardening cycle recommended

Artifacts are isolated under `analysis/validation/`; no production dataset was changed.
