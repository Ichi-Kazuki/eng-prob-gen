# WE Generator v2.1 Format Re-smoke Report

Date: 2026-08-25  
Scope: fresh 15-item format-only re-smoke, one item per microbatch  
Grammar quality: **NOT_EVALUATED** — no independent Agent runtime was available

## Result

The v2.1 format smoke gate passes. The sample is not a replacement for the
Official distribution and does not authorize a new 75-item Validation run.

The fresh sample has sentence median **23 words**, coverage median **22.73%**,
unmarked-context median **17**, zero zero-gap items, zero 5+ word spans, and a
correct-span word-count median of **1**. `SINGLE_WORD` correct spans (8/15)
outnumber `SHORT_PHRASE` spans (3/15).

## Official / v2 Validation / v2.1 comparison

| Metric | Official 125 | WE v2 Validation 75 | WE v2.1 re-smoke 15 |
|---|---:|---:|---:|
| Sentence median | 20 | 14 | 23 |
| Coverage median | 26.32% | 40.00% | 22.73% |
| Unmarked median | 15 | 8 | 17 |
| Span word-count distribution | 1:375, 2:106, 3:16, 4:3, 5+:0 | 1:205, 2:79, 3:7, 5:8, 6:1 | 1:44, 2:16, 3+:0, 5+:0 |
| Correct-span type | SINGLE 98 / SHORT 12 / CLAUSE 15 | SINGLE 22 / SHORT 44 / CLAUSE 9 | SINGLE 8 / SHORT 3 / CLAUSE 4 |
| Correct answer position A / B / C / D | 24 / 37 / 31 / 33 | 14 / 26 / 30 / 5 | 5 / 6 / 2 / 2 |
| Gap medians A–B / B–C / C–D | 4 / 4 / 4 | 1 / 2 / 3 | 3 / 3 / 4 |
| Zero-gap item rate | 0% | 53.33% | 0% |
| PREFERRED / WARNING / EXTREME | N/A | 0 / 3 / 72 | 6 / 6 / 3 |
| Multi-tail count | N/A | 62 | 3 |

The v2 Validation band and multi-tail values are read from
`tmp/we_validation_run_2/we_v2_validation_format_analysis.json`; multi-tail
means at least two EXTREME metric dimensions. v2.1 uses the same definition.

## Planning change

- Sentence targets are sampled from the 125 observed
  `items[].sentence_word_count` values, not fixed at 13 or 20.
- A sampled target creates a deterministic target ±2 conformance range.
  Realized clean-sentence length outside that range is rejected before
  emission; no padding or post-hoc prose inflation is used.
- Correct-span type and conditional correct-span length are sampled from the
  Official observed counts. The planner derives probabilities at runtime from
  the artifact rather than using hand-tuned probabilities.
- Correct-span grammar locality remains authoritative. A sampled type cannot
  force a grammatical locus to be shortened or expanded.

## Span-selection change

- Distractors are enumerated over the whole clean sentence.
- One-word and natural two-word units are preferred; normal candidates stop at
  four words.
- Candidate combinations are softly scored on marked words, coverage,
  unmarked context, three gaps, maximum span, correct-span type, and answer
  position. Bands remain diagnostics, not an optimizer target.
- Gap targets are sampled from Official observations; normal selection requires
  at least one unmarked token between consecutive spans.
- A/B/C/D labels are assigned after sentence-order selection, so the correct
  answer is not fixed to one label.
- The 15-item answer-position draw is A/B/C/D = 5/6/2/2; the small sample is
  not expected to reproduce Official placement counts exactly.
- Pre-emission checks recalculate sentence length, span lengths, coverage,
  unmarked context, gaps, and correct-span type. Span reselection is preferred
  when the sentence plan still conforms; a short sentence plan returns to clean
  sentence generation.

## Smoke gate

| Criterion | Result | Status |
|---|---:|---|
| Sentence median 17–23 | 23 | PASS |
| Sentence <15 words is a minority | 2/15 | PASS |
| Coverage median 20–35% | 22.73% | PASS |
| Coverage ≥60% | 0/15 | PASS |
| Coverage =100% | 0/15 | PASS |
| Unmarked median ≥12 | 17 | PASS |
| Zero unmarked context | 0/15 | PASS |
| Correct-span median =1 preferred | 1 | PASS |
| 5+ word spans | 0 | PASS |
| SINGLE_WORD correct > SHORT_PHRASE | 8 > 3 | PASS |
| Gap medians roughly 2–5 | 3 / 3 / 4 | PASS |
| EXTREME is not a majority | 3/15 | PASS |
| Multi-tail EXTREME is a minority | 3/15 | PASS |

Three EXTREME items are official-tail sentence-length draws (one <=10-word
draw and one 31+ draw, plus a second short-tail item); this is diagnostic
telemetry and not a threshold change.

## Regression and isolation evidence

- New v2.1 planner tests: **8/8 PASS**.
- Existing deterministic test suite: **48/48 PASS**.
- Historical v2.0 item validator: **10/10 PASS**; fresh v2.1 format diagnostics:
  **15/15 PASS** before the format-only artifact was emitted.
- Existing P0 hardening regression: **7/7 PASS**; existing WE v2 regression:
  **6/6 PASS with 0 PASS-prohibited violations**; historical WE v2 acceptance
  artifact remains PASS.
- Historical v2 smoke, v2 regression, schema, public validator, P0, and
  acceptance artifacts were not overwritten. v2.0 literals remain accepted by
  the compatible schema while v2.1 output uses the v2.1 literal.
- No Reviewer, Solver, Orchestrator, Grammar Specification, taxonomy, or
  mutation implementation file is part of the v2.1 change.
- No fake Reviewer/Solver consensus is included in the fresh re-smoke.

The explicit v2.1 scope statement is:

> grammar generation logic unchanged, format planner + span-selection policy only

## Remaining drift

The 15-item sample is intentionally small. Its sentence median is three words
above Official, its `CLAUSE_OR_CLAUSE_LIKE` correct-span share is higher than
Official, and seven items remain WARNING-band. Those are monitoring findings,
not evidence to loosen bands. The main v2 drift signatures have nevertheless
disappeared from this sample: the plan is no longer fixed near 13, zero-gap
clustering is 0%, 5+ spans are 0%, and SINGLE_WORD is again the leading
correct-span type.

## 25-item pilot decision

**Conditionally justified.** The format-only smoke gate passes and supports a
25-item pilot using one-item microbatches and the same v2.1 planner. The pilot
must still run the independent Reviewer and Solver contracts; grammar quality
cannot be inferred from this report because it is `NOT_EVALUATED`. Stop or
re-review if correct-span type drift, WARNING/EXTREME concentration, or
grammar-review disagreement increases.
