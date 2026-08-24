# TOEFL ITP Grammar Pipeline — Pilot Batch Report

> Scope: isolated Pilot Batch only (15 Structure + 25 Written Expression). No production DB insert, site connection, production merge, or mass generation was performed.

## 1. Executive summary

The initial cohort contained **40** candidates. **37** reached AUTO_ACCEPTED (92.5%); 1 went to MANUAL_REVIEW, 2 were DISCARDED, and 0 were REJECTED. This is a small n=40 pilot: rates are operational estimates for finding pipeline and quality failures, not stable category-level conclusions.

## 2. Pipeline totals

| Metric | Count | Denominator / definition |
|---|---:|---|
| Initial generated | 40 | initial cohort |
| Generator schema validation pass | 40 | / 40 initial candidates |
| Reviewer PASS (round 1) | 36 | / 40 |
| Reviewer REVISE (round 1) | 4 | / 40 |
| Reviewer REJECT (round 1) | 0 | / 40 |
| Solver reached | 40 | candidates after Reviewer PASS |
| Solver consensus | 37 | / 40 solver outputs; answer agrees with Generator and Reviewer |
| Solver disagreement | 0 | answer A-D but not all three-way agreement |
| Solver AMBIGUOUS / NONE | 1 / 2 | solver outputs |
| Solver LOW confidence | 0 | solver outputs |
| AUTO_ACCEPTED | 37 | / 40 initial candidates |
| MANUAL_REVIEW | 1 | final state |
| DISCARDED | 2 | final state |

Rates (all denominators are explicit):

- Generator schema pass: 100.0% (40/40).
- Reviewer first-pass: 90.0%; REVISE 10.0%; REJECT 0.0% — each / 40 initial candidates.
- Solver consensus: 92.5% (37/40 solver-reached).
- Final auto-accept: 92.5% (37/40 initial candidates).

## 3. Structure results

Structure: first-pass 93.3% (14/15); final acceptance 100.0% (15/15).

## 4. Written Expression results

Written Expression: first-pass 88.0% (22/25); final acceptance 88.0% (22/25).

## 5. Reviewer failure reasons

Counts below are failure events across Reviewer submissions, including repaired REVISE items; one item can contribute secondary reasons. The primary reason is retained per failure item in provenance.

Final non-accepted candidate taxonomy:

| Primary failure reason | Final candidate count |
|---|---:|
| no_valid_answer | 2 |
| solver_ambiguous | 1 |

Reviewer failure events:

| Reason | Failure events | Affected items |
|---|---:|---:|
| multiple_valid_answers | 2 | 2 |
| difficulty_mismatch | 1 | 1 |
| no_genuine_error | 1 | 1 |
| target_mismatch | 1 | 1 |

## 6. Solver disagreement results

Solver outputs: consensus 37, answer disagreement 0, AMBIGUOUS 1, NONE 2, LOW confidence 0. AMBIGUOUS/NONE were not forced into an answer; the existing Orchestrator routing was used.

## 7. Revision effectiveness

4 initial items were revised. Revision success was 4/4 (100.0%), defined as a later Reviewer PASS. Failed-after-revision count: 0.

| Item | Revision attempts | After-revision PASS | Final verdict |
|---|---:|---|---|
| pilot-struct-012 | 1 | yes | PASS |
| pilot-we-006 | 1 | yes | PASS |
| pilot-we-014 | 1 | yes | PASS |
| pilot-we-021 | 1 | yes | PASS |

## 8. Grammar-target analysis

| Primary target | Generated | Reviewer PASS | Final accepted | Failure count | Acceptance rate |
|---|---:|---:|---:|---:|---:|
| CLAUSE_STRUCTURE | 4 | 3 | 4 | 0 | 100.0% |
| COMPARATIVES_DEGREE | 1 | 1 | 1 | 0 | 100.0% |
| CONNECTORS_CONJUNCTIONS | 2 | 2 | 1 | 1 | 50.0% |
| INVERSION | 1 | 1 | 1 | 0 | 100.0% |
| NONFINITE_VERB_PHRASES | 5 | 4 | 5 | 0 | 100.0% |
| NOUN_CLAUSES | 1 | 1 | 1 | 0 | 100.0% |
| PARALLEL_STRUCTURE | 4 | 4 | 3 | 1 | 75.0% |
| REFERENCE_AND_DETERMINERS | 5 | 5 | 4 | 1 | 80.0% |
| RELATIVE_CLAUSES | 4 | 4 | 4 | 0 | 100.0% |
| VERB_COMPLEMENTATION | 5 | 3 | 5 | 0 | 100.0% |
| VERB_FORM_VOICE | 2 | 2 | 2 | 0 | 100.0% |
| WORD_CLASS_FORM | 3 | 3 | 3 | 0 | 100.0% |
| WORD_ORDER_MODIFICATION | 3 | 3 | 3 | 0 | 100.0% |

Category samples are small (often 1–3 items); no category-level difficulty conclusion is warranted.

## 9. Difficulty analysis

| Difficulty | Generated | Reviewer PASS | Solver consensus | Final accepted |
|---|---:|---:|---:|---:|
| EASY | 20 | 17 | 18 | 18 |
| MEDIUM | 15 | 14 | 14 | 14 |
| HARD | 5 | 5 | 5 | 5 |

The HARD row is descriptive only; this pilot does not support a general claim about hard-item generation difficulty.

## 10. Answer-position distribution

### Structure

- Planned/generated positions: `{'A': 4, 'B': 4, 'C': 4, 'D': 3}`; generated actual positions: `{'A': 4, 'B': 4, 'C': 4, 'D': 3}`; accepted positions: `{'D': 3, 'C': 4, 'B': 4, 'A': 4}`.

### Written Expression

- Planned/generated positions: `{'A': 7, 'B': 6, 'C': 6, 'D': 6}`; generated actual positions: `{'A': 7, 'B': 6, 'C': 6, 'D': 6}`; accepted positions: `{'C': 6, 'A': 6, 'D': 5, 'B': 5}`.

Accepted-position skew is reported against the initial planned/generated distribution; with n=15 and n=25, small changes are not statistically meaningful.

## 11. Vocabulary-domain diversity

35 vocabulary domains were used. Counts: `{'botany': 3, 'ornithology': 1, 'archaeology': 1, 'art history': 2, 'economics': 1, 'linguistics': 1, 'geology': 2, 'meteorology': 1, 'oceanography': 1, 'anthropology': 1, 'musicology': 1, 'urban planning': 1, 'ancient history': 1, 'astronomy': 2, 'marine biology': 1, 'paleontology': 1, 'sociology': 1, 'political science': 1, 'philosophy': 1, 'chemistry': 1, 'physics': 1, 'zoology': 1, 'climatology': 1, 'volcanology': 1, 'cartography': 1, 'epidemiology': 1, 'nutrition science': 1, 'forestry': 1, 'mycology': 1, 'entomology': 1, 'ethnomusicology': 1, 'textile history': 1, 'cryptography': 1, 'horticulture': 1, 'seismology': 1}`. Repeated domains: `{'botany': 3, 'art history': 2, 'geology': 2, 'astronomy': 2}`. Non-accepted candidates by domain: `{'astronomy': 1, 'chemistry': 1, 'horticulture': 1}`. These are descriptive diagnostics, not evidence of domain-specific quality differences.

## 12. Manual review items

Final MANUAL_REVIEW count: 1. See `pilot_manual_review.json` and the existing `analysis/manual_review_queue.json`; no manual decision was auto-resolved.

## 13. Representative failure patterns

Observed patterns are recorded from Reviewer issue text and Orchestrator outcomes. Typical pilot signals include ambiguous alternate parses, non-genuine Written Expression errors, target/metadata mismatch, and solver disagreement. The exact item-level evidence is preserved in `pilot_provenance.json` and `pilot_failure_items.json`.

## 14. Recommended Generator improvements

- Add a pre-generation ambiguity check for alternate constituent bracketing and reduced-relative parses, especially for distractors and ordinal + infinitive constructions.
- Strengthen the Written Expression rule that the marked span must be unambiguously ungrammatical under ordinary edited-English readings; avoid complement choices with legitimate noun-object readings.
- Add a taxonomy-alignment gate for fronted-negative inversion (for example, `Not only ...`) so it is not labeled as `CLAUSE_STRUCTURE`.
- Use a second-error audit for Written Expression items before submission, while preserving the Reviewer as the independent quality authority.
- Do not automatically change Generator prompts/specification from this report; these are recommendations for the next engineering decision.

## 15. Larger-scale generation readiness

**Not ready for unbounded larger-scale generation yet.** The pipeline mechanics completed a real isolated end-to-end path, but the pilot is small and any non-trivial REVISE/manual/discard rate, solver disagreement, or taxonomy/ambiguity pattern should be addressed and re-piloted before scaling. No production deployment was performed.

## Artifact and provenance notes

All initial candidates remain in `pilot_initial_items.json`. `pilot_provenance.json` retains original item text, revisions, every available Reviewer/Solver output, state history, final state, slot plan, and the Orchestrator QA record. Failed candidates were not deleted.

Generated by `analysis/pilot/build_pilot_artifacts.py` after the existing Orchestrator finalized the batch.
