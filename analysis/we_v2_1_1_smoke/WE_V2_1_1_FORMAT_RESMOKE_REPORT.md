# WE Generator v2.1.1 Format Re-smoke Report

Date: 2026-08-25  
Scope: fresh 15-item format-only re-smoke  
Version: **WE Generator v2.1.1**  
Grammar quality: **NOT_EVALUATED** — no independent Reviewer/Solver runtime was available; no synthetic consensus was created.

## Change

`distractor span syntactic-coherence scoring only`

The planner now gives distractor candidates a local `syntactic_coherence`
score. Complete short units are preferred and incomplete cuts are penalized.
The grammar-selected correct locus remains authoritative and is not moved by
this score. Sentence-length sampling, geometry, grammar mutation, Reviewer,
Solver, Schema, Specification, and Format band thresholds are unchanged.

The two pilot regressions are covered directly:

| Candidate | Coherence |
|---|---:|
| `soil` | 0.95 |
| `soil during` | 0.00 |
| `independent checks` | 1.38 |
| `after independent` | 0.00 |

## Re-smoke result

The cohort contains 15 newly authored sentences. Historical exact-match count
is **0**. All 60 marked spans were audited in the JSON artifact.

| Audit | Result | Gate |
|---|---:|---|
| Clearly incoherent spans | **0** | PASS |
| Borderline spans | **1** (`When`, 0.12) | PASS, <=2 |
| Coherent spans | 59 | — |

## Existing format gates

| Gate | Observed | Status |
|---|---:|---|
| Sentence median | 21 | PASS, 17–23 |
| Coverage median | 23.81% | PASS, 20–35% |
| Coverage >=60% | 0 | PASS |
| Unmarked median | 16 | PASS, >=12 |
| Zero-gap rate | 0% | PASS, <=20% |
| 5+ word spans | 0 | PASS |
| SINGLE_WORD correct > SHORT_PHRASE correct | 10 > 2 | PASS |
| EXTREME items | 2/15 | PASS, not majority |

Additional format telemetry: sentence range 18–26, coverage >=60% count 0,
zero unmarked-context count 0, and format bands PREFERRED 12 / WARNING 1 /
EXTREME 2.

## Final decision

**A. Freeze v2.1.1.**

This freezes the format-only patch. The 75-item Validation remains unexecuted.
Grammar quality remains `NOT_EVALUATED` until independent Reviewer/Solver
runtime is available.
