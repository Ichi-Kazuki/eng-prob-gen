# WE Generator v2.1.2 — 75-item Validation Report

Run: `we-v2.1.2-75-item-validation-20260826`  
Generator lock: **v2.1.2**  
Format logic lock: **v2.1.1**  
Status: **DETERMINISTIC/FORMAT GATES PASS**  
Grammar mode: **CONTRACT_REPLAY_ONLY**  
Grammar quality: **NOT_EVALUATED**  

## Final decision

**E. Infrastructure prevents final quality conclusion.**

Deterministic and format findings are reported independently from grammar quality. No Generator, format planner, mutation safety, Schema, Specification, Reviewer, Solver, or band-threshold file was modified during this run.

## Generation

- Fresh items: **75/75**; one item per microbatch: **yes**
- Historical exact sentence reuse: **0**
- Initial generation failures: **6/75 (8.00%)**
- Replacement/regeneration count: **6**
- Sentence-first: **yes**

## Deterministic gates

- Schema: **75/75**
- Format validator: **75/75**
- Mutation safety (local deterministic layer): **75/75**
- Metadata consistency: **75/75**
- Surface edits accounted: **75/75**
- One intended marked locus: **75/75**
- External mutation mismatches: **0**
- Deterministic answer integrity: **75/75**
- Strong grammar evidence: **{'REQUIRES_EXTERNAL_REVIEW': 75}**

## Format comparison

| Cohort | n | sentence median | coverage median | unmarked median | gaps A-B/B-C/C-D | zero-gap | 5+ spans |
|---|---:|---:|---:|---:|---|---:|---:|
| Official_125 | 125 | 20 | 0.2632 | 15 | 4/4/4 | 0.0 | 0 |
| WE_v2_old_Validation_75 | 75 | 14 | 0.4 | 8 | 1/2/3 | 0.5333 | 9 |
| WE_v2_1_1_locked_reference_15 | 15 | 23 | 0.2273 | 17 | 3/3/4 | 0.0 | 0 |
| WE_v2_1_1_pilot_25_reference | 25 | 21 | 0.2273 | 15 | 3/3/3 | 0.0 | 0 |
| WE_v2_1_2_Validation_75 | 75 | 17 | 0.2778 | 13 | 3/3/3 | 0.0 | 0 |

The v2.1.1 format improvement is maintained in the 75-item cohort: zero-gap remains 0%, 5+ spans remain 0, coverage median remains within 20–35%, and unmarked-context median remains at least 12. The 5 EXTREME and 5 WARNING items are diagnostic tails only; they do not breach the quality gates.

Additional v2.1.2 format telemetry:

- Span word-count distribution: `{'1': 259, '2': 31, '3': 10}`
- Correct span distribution: `{'1': 60, '2': 5, '3': 10}`; types `{'SINGLE_WORD': 60, 'CLAUSE_OR_CLAUSE_LIKE': 10, 'SHORT_PHRASE': 5}`
- Bands: `{'EXTREME': 5, 'WARNING': 5, 'PREFERRED': 65}`
- SINGLE_TAIL: `0`; MULTI_TAIL: `5`; HIGH_DISTANCE_MULTI_TAIL: `0`

## Grammar evaluation boundary

No live independent Reviewer/Solver runtime was available. Therefore the 75-item grammar quality and accuracy are **NOT_EVALUATED**. No synthetic verdict, synthetic consensus, synthetic AUTO_ACCEPT quality, or 75-item accuracy claim was created. The explicit mode is **CONTRACT_REPLAY_ONLY**.

## Blind validation sample

A 12-item blind sample was extracted with only `sentence` and `A/B/C/D` fields. The sealed key is a separate artifact and is not embedded in the blind file.

- Blind artifact: `analysis/we_v2_1_2_validation/we_v2_1_2_validation_blind_sample.json`
- Sealed key: `analysis/we_v2_1_2_validation/we_v2_1_2_validation_blind_sample_sealed_key.json`

## Regressions

Existing tests/regressions: **PASS**. This includes the v2.1.2 mutation-safety regression suite and orchestrator smoke/adversarial/reject/acceptance replays.

## Artifacts

- Full validation JSON: `analysis/we_v2_1_2_validation/we_v2_1_2_75_item_validation.json`
- Hash lock and before/after lock equality are embedded in the full validation JSON; locked inputs unchanged: **True**
