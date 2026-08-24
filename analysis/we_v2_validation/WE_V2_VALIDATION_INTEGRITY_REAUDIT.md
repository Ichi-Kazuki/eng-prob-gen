# WE v2 Validation Integrity Re-audit

- Status: **SUPERSEDES** `WE_V2_VALIDATION_REPORT.md`; the old report is retained.
- Run ID: `we-v2-validation-integrity-reaudit-20260824`; source cohort: existing `we_v2_validation_initial_items.json` only.
- New 75-item generation: **NOT RUN**. No replacement candidates were generated.
- Runtime mode: **CONTRACT_REPLAY_ONLY**; grammar-quality metrics are excluded.

## Executive result

- Wrong-key count: old stored declaration **10/75** mismatched actual mutation; corrected deterministic derivation resolves **75/75** locations.
- False-error fixture count: old artifact **2**; corrected source fixture scan **0**.
- Known bases 15, 17, 20, 22, 23: actual error span equals stored `correct_answer` **15/15**.
- Answer-key integrity of the stored old artifact: **65/75**; recomputed answer-key integrity: **75/75**.
- Diagnostics key integrity: required/calc key shape **75/75**; complete **75/75**; consistent after deterministic re-key **71/75**.
- Regression integrity: **PASS**; WE/P0 artifact-presence gate **PASS**.
- Gate I integrity: **FAIL**. Format drift conclusion is maintained.

## Integrity checks

### Mutation and answer-key integrity

`correct_answer` is now derived from a clean/error token-and-separator diff plus error-side marked-span alignment. The hand-written position map was removed from the validation generator path.

| Check | Result |
|---|---:|
| Stored key equals actual mutation | 65/75 |
| Actual mutation resolves to one marked span | 75/75 |
| Structural mutation validity | 75/75 |
| Known bases 15, 17, 20, 22, 23 | 15/15 |

Known-base records were checked individually in `we_v2_validation_integrity_reaudit.json`.

### Diagnostics and format geometry

Required diagnostic keys are read from `REQUIRED_DIAGNOSTIC_KEYS` at runtime (18 keys); actual calculated keys are compared as sets. No diagnostic-key list is hard-coded in the re-audit completeness calculation.

- Key shape: 75/75.
- Complete: 75/75.
- Stored diagnostics consistent with old declared key: 75/75.
- Recomputed diagnostics consistent after actual-key re-derivation: 71/75.

Gate I required axes:

| Axis | Result |
|---|---|
| sentence_word_count | FAIL |
| marked_coverage_ratio | FAIL |
| unmarked_word_count | FAIL |
| gap_A_B | FAIL |
| gap_B_C | PASS |
| gap_C_D | PASS |
| format_distance_median | PASS |
| worst_band_status | FAIL |

- Recomputed worst-band distribution: `{'PREFERRED': 0, 'WARNING': 3, 'EXTREME': 72}`.
- Recomputed correct-span distribution: `{'SINGLE_WORD': 23, 'SHORT_PHRASE': 43, 'CLAUSE_OR_CLAUSE_LIKE': 9}`; old declared distribution: `{'SINGLE_WORD': 27, 'SHORT_PHRASE': 39, 'CLAUSE_OR_CLAUSE_LIKE': 9}`.
- Sentence length, coverage, unmarked context, A-B/B-C/C-D gaps, holistic format distance, and worst-band share are all Gate I inputs.

### Reviewer/Solver independence

- Solver blind allowlist boundary: **PASS** (75 items).
- Harness source controls: `{'position_map_removed': True, 'intended_answer_path_removed': True, 'deterministic_answer_utility_used': True}`.
- Runtime available: **False**.
- The existing Reviewer/Solver files are contract-shaped replay outputs. Their answer agreement is not treated as independent judgment evidence.

### False-error fixture correction

The old artifact contains 2 `before/by the time/when + simple past` false-error cases. The source fixture was changed to unambiguous non-finite/tense errors; corrected source scan reports 0. The old JSON artifact remains historical evidence and was not silently regenerated.

### Regression replay integrity

- Replay output directory: temporary (`analysis\we_v2_validation\.integrity-replay-mkfm6pq4`).
- WE regression artifact present: **True**.
- P0 regression artifact present: **True**.
- Tracked fixture hashes unchanged: **True**.
- Missing WE/P0 artifact would make Gate B FAIL.

## Old-report metric disposition

| Old metric/conclusion | Status | Re-audit disposition |
|---|---|---|
| generator schema (75/75) | **VALID** | Stored items and deterministic schema recheck both pass for the current 75-item cohort. |
| diagnostics completeness (75/75) | **RECOMPUTED** | Required key set is sourced dynamically from REQUIRED_DIAGNOSTIC_KEYS and compared with calculated keys. |
| diagnostics consistency (75/75) | **RECOMPUTED** | Stored-key consistency is 75/75; after deterministic re-key it is 71/75. |
| format geometry (Gate I FAIL) | **RECOMPUTED** | Recomputed from actual spans; Gate I is FAIL with the distance axis included. |
| format bands (72 EXTREME / 3 WARNING) | **RECOMPUTED** | Current corrected-cohort worst-band distribution is 72 EXTREME / 3 WARNING. |
| correct-span distribution (27 / 39 / 9) | **RECOMPUTED** | Correct span is selected from actual mutation location; current recomputed distribution is 23 / 43 / 9. |
| answer-key integrity (0 wrong keys) | **INVALID** | Deterministic audit finds 10 stored-key mismatches in the current cohort; the previous zero count is invalidated. |
| mutation validity (75/75 implied) | **RECOMPUTED** | Structural clean/error mutation and single marked location pass 75/75. |
| Reviewer grammar quality (75 PASS) | **NOT_EVALUATED** | No callable live Agent runtime is present; Reviewer/Solver contract replay cannot establish independent grammar quality, consensus quality, or AUTO_ACCEPT quality. |
| Solver consensus / AUTO_ACCEPT quality (75 agreement / 75 AUTO_ACCEPT) | **NOT_EVALUATED** | No callable live Agent runtime is present; Reviewer/Solver contract replay cannot establish independent grammar quality, consensus quality, or AUTO_ACCEPT quality. |
| regression integrity (PASS) | **VALID** | WE/P0 artifacts are required temporary gate outputs; tracked fixtures are hash-unchanged. |
| format drift conclusion (Recalibration required) | **VALID** | Current Gate I result is FAIL; sentence length, coverage, unmarked context, gaps, worst-band share, and distance are evaluated from the current cohort. |
| human blind-review quality conclusion (pending) | **NOT_EVALUATED** | No human labels or live Agent grammar judgments were added by this re-audit. |

Status meanings: `VALID` = still supported; `INVALID` = contradicted; `RECOMPUTED` = numerical conclusion must be replaced by this audit; `NOT_EVALUATED` = no defensible conclusion under CONTRACT_REPLAY_ONLY.

## Final decisions

- Grammar-quality metrics evaluable: **False**. Reviewer grammar quality, Solver consensus quality, and AUTO_ACCEPT quality are excluded.
- Format drift conclusion maintained: **YES** — Gate I is FAIL, with the recalibrated geometry check explicitly including holistic format distance.
- New 75-item Validation should be re-run now: **NO**. First correct/re-key the historical cohort or regenerate only after the fixture fix, and provide an actual Agent runtime for grammar-quality evidence; the current format drift gate also remains unresolved.

## Retained artifacts

- Historical report retained with superseded/invalidated status: `WE_V2_VALIDATION_REPORT.md`.
- Re-audit data: `we_v2_validation_integrity_reaudit.json`.
- This report: `WE_V2_VALIDATION_INTEGRITY_REAUDIT.md`.
