# WE v2.1 — 25-item Independent Pilot

Run: `we-v2.1-25-item-pilot-20260825`  
Status: **CONTRACT_REPLAY_ONLY**  
Grammar quality: **NOT_EVALUATED** (no independent Reviewer/Solver runtime; synthetic consensus prohibited)  
75-item Validation: **not run**

## Final decision

**D. Reviewer/Solver/infrastructure issue.**

- Format: `PASS`; 15/15 requested format gates passed.
- Grammar: not evaluated. Reviewer PASS, genuine-error, alternate-parse/repair, naturalness, Solver answer/confidence/agreement, and declared-vs-independent answer metrics are `NOT_EVALUATED`, not zero.
- Infrastructure: 25 Generator microbatches completed and the strict Solver blind payload was produced, but distinct current Reviewer and Solver runtime invocations were unavailable after the Agent thread limit. No Reviewer/Solver output or consensus was synthesized; full Orchestrator acceptance for this pilot therefore remains unexecuted. The existing regression acceptance suite passed separately.

## Fresh generation and version lock

- 25 fresh items; one item per microbatch; sentence-first generation preserved.
- Historical sentence exact-match audit: `0`.
- Format bands and v2.1 planner were not changed.
- Locked component hashes are recorded in the JSON artifact under `run.version_lock`.

## Format metrics

| Cohort | Sentence median | Coverage median | Unmarked median | Gaps A-B/B-C/C-D |
|---|---:|---:|---:|---:|
| Official 125 | 20 | 26.32% | 15 | 4/4/4 |
| WE v2 Validation 75 | 14 | 40.00% | 8 | 1/2/3 |
| WE v2.1 smoke 15 | 23 | 22.73% | 17 | 3/3/4 |
| WE v2.1 pilot 25 | 21 | 22.73% | 15 | 3/3/3 |

Pilot distributions: sentence `{'median': 21, 'min': 16, 'max': 24, 'under_15_count': 0, 'under_15_rate': 0.0}`, span words `{'1': 77, '2': 22, '3': 1}`, correct span types `{'SINGLE_WORD': 24, 'SHORT_PHRASE': 1}`, answer positions `{'B': 6, 'D': 9, 'C': 10}`, bands `{'PREFERRED': 20, 'WARNING': 4, 'EXTREME': 1}`.

Zero-gap item rate: **0.00%**; 5+ correct spans: **0**; SINGLE_TAIL: **1**; MULTI_TAIL: **0**; HIGH_DISTANCE_MULTI_TAIL: **0**.

### Format gates

| Gate | Observed | Requirement | Status |
|---|---:|---|---|
| sentence_median | `21` | 17-23 preferred | **PASS** |
| sentence_under_15 | `0.0` | <15 words <=20% | **PASS** |
| coverage_median | `0.2273` | 20-35% | **PASS** |
| coverage_ge_0_60 | `0` | =0 | **PASS** |
| coverage_100 | `0` | =0 | **PASS** |
| unmarked_median | `15` | >=12 | **PASS** |
| unmarked_zero | `0` | =0 | **PASS** |
| correct_span_median | `1` | =1 preferred | **PASS** |
| five_plus_spans | `0` | =0 | **PASS** |
| single_word_correct_gt_short_phrase | `{'SINGLE_WORD': 24, 'SHORT_PHRASE': 1}` | SINGLE_WORD > SHORT_PHRASE | **PASS** |
| gap_medians | `{'gap_A_B': 3, 'gap_B_C': 3, 'gap_C_D': 3}` | roughly 2-5 | **PASS** |
| zero_gap_items | `0.0` | <=20% | **PASS** |
| extreme_share | `0.04` | <40% | **PASS** |
| multi_tail_extreme_share | `0.0` | <25% | **PASS** |
| high_distance_multi_tail_rare | `0.0` | <=10% diagnostic rarity threshold | **PASS** |

No band threshold or format policy was tuned to improve this result.

## Independent Reviewer / blind Solver

Reviewer input contract was prepared with only `item_id`, `section`, `sentence`, and `marked_parts`; Generator answer, target position, rationale, internal plan, and QA metadata were excluded. Reviewer runtime was unavailable, so no verdicts were produced.

Solver input was created through the current deterministic blinding script and leakage guard. All `25/25` items passed the strict allowlist. Solver runtime was unavailable, so A/B/C/D, AMBIGUOUS, NONE, confidence, and agreement are not evaluated.

Explicit grammar counters are all `NOT_EVALUATED`: Reviewer PASS/REVISE/REJECT and eventual PASS; genuine-error, multiple-error, alternate-parse/repair, and unnaturalness failures; Solver A/B/C/D, AMBIGUOUS, NONE, LOW confidence; Reviewer/Solver agreement; declared-vs-independent answer; and final accepted/manual/rejected routing.

## Answer-key integrity

The deterministic clean/error lexical-diff checker reports **PASS**: `25/25` surface edits accounted for, `25/25` intended loci aligned, `25/25` deterministic answer-integrity passes, and `0` external-mutation mismatches. These are reported separately from independent Reviewer/Solver disagreement.

## Human blind sample

Created `8` blind items in `analysis/we_v2_1_pilot/we_v2_1_human_blind_sample.json`. The file contains only sentence and A/B/C/D marked parts; Generator, Reviewer, Solver, and QA answers are hidden. It is prepared but not human-reviewed.

## Regression status

All requested deterministic regression gates passed: schema/runtime and validation public API unittest suite **50/50**, P0 **7/7**, WE v2 regression **6/6**, v2.1 format tests **10/10**, Solver blinding **25/25**, and Orchestrator acceptance **18/18** with smoke/adversarial/reject replay PASS. The 75-item Validation was not executed.

## Recommendation rationale

The v2.1 format result is independently measurable and compared with Official / WE v2 Validation / v2.1 15-item smoke, but grammar quality cannot support A, B, or C. Because the missing independent Reviewer/Solver runtime is an infrastructure/contract-execution failure, the recommendation is D. After runtime recovery, rerun this same locked 25-item pilot or obtain human review before considering 75-item Validation.
