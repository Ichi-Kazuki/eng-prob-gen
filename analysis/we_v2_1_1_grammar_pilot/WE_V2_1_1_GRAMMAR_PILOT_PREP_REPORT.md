# WE v2.1.1 Grammar Pilot Preparation Report

Date: 2026-08-25  
Batch: `we-v2.1.1-grammar-pilot-20260825`  
Generator lock: **Written Expression Generator v2.1.1**  
Grammar quality: **NOT_EVALUATED**  
75-item Validation: **NOT_RUN**

## Scope and freeze compliance

This artifact is a fresh 25-item blind pilot. The Generator prompt is locked
at v2.1.1. The Generator, format planner, grammar logic, Reviewer, Solver,
Schema, Specification, taxonomy, and format-band thresholds were not edited.
The frozen item Schema still names the item-level literal
`Written Expression Generator v2.1`; that literal is preserved to keep the existing
Schema contract unchanged, while the v2.1.1 Generator version and prompt hash
are recorded in the sealed key's version lock.

- Generation unit: one item per microbatch.
- Sentence-first: clean sentence and single mutation were authored before A/B/C/D span placement.
- Historical exact sentence matches: **0**.
- Initial generation attempts: **25**.
- Initial generation failures: **0**; initial failure rate: **0/25 = 0.00%**.
- Regenerated count: **0**.

## Deterministic gates

Only existing deterministic checks were used. No independent Reviewer/Solver
judgment was run or synthesized.

| Gate | Result |
|---|---:|
| Schema validity | **25/25** |
| Format validity | **25/25** |
| Mutation integrity | **25/25** |
| All surface edits accounted for | **25/25** |
| One intended marked locus | **25/25** |
| No external mutation | **25/25** |
| Deterministic answer integrity | **25/25** |

Overall deterministic integrity: **25/25 PASS**.

## Format regression only

No format re-optimization or threshold change was performed. The comparison
below is telemetry against the existing v2.1.1 15-item smoke; it is not a new
acceptance policy.

| Metric | v2.1.1 smoke 15 | Fresh grammar pilot 25 |
|---|---:|---:|
| Sentence median | 21 | 21 |
| Coverage median | 23.81% | 25.00% |
| Unmarked median | 16 | 15 |
| Gap medians A-B / B-C / C-D | 3 / 4 / 4 | 3 / 3 / 4 |
| Zero-gap items | 0.00% | 0.00% |
| 5+ word spans | 0 | 0 |
| PREFERRED / WARNING / EXTREME | 12 / 1 / 2 | 19 / 3 / 3 |

Format regression result: **PASS; no material regression observed**
on the requested telemetry. Existing bands remain diagnostics only.

## Blind artifact and sealed key

Blind artifact: `analysis/we_v2_1_1_grammar_pilot/we_v2_1_1_grammar_pilot_blind.json`  
Sealed key: `analysis/we_v2_1_1_grammar_pilot/we_v2_1_1_grammar_pilot_sealed_key.json`

The blind artifact has exactly `blind_id`, `sentence`, and `marked_parts`
(`A`, `B`, `C`, `D`) per item. It contains no correct answer, intended
answer, target, error type, mutation metadata, generation plan, explanation,
Reviewer output, Solver output, or QA verdict. Generator-side answers and
metadata are stored only in the separate sealed key. The sealed key is marked
`sealed_until_blind_review_complete: true`.

## Grammar quality

**NOT_EVALUATED.** Independent Reviewer and Solver runtimes are unavailable.
No fake consensus, AUTO_ACCEPT quality, Reviewer output, or Solver output was
generated.

## Final report

- Fresh generated count: **25**
- Regenerated count: **0**
- Deterministic integrity: **25/25**
- Format regression: **none observed**
- Blind artifact answer leakage: **none**
- Grammar quality: **NOT_EVALUATED**
- 75-item Validation: **not executed**

Version lock hashes are recorded in the sealed key. Output hashes:

- Blind: `sha256:55bac561f0abb4a956f4b16d9cc5004fdeaddffcc4f6f682effdca2da54e58ac`
- Sealed key: `sha256:4684415dadcfd6bd34f518f4be308725d65003651d9b8ece662de711d37b4ffa`
