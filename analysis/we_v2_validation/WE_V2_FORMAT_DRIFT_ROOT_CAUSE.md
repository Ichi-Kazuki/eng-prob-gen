# WE v2 Format Drift Root-Cause Audit

> Scope: existing 75-item WE v2 Validation cohort only. No new 75-item generation was run. Generator, Reviewer, Solver, Orchestrator, Schema, format band, Specification, and grammar mutation logic were not changed.
> Grammar quality remains `NOT_EVALUATED`; Reviewer/Solver historical judgments are excluded from Format analysis.

## Executive conclusion

The dominant cause is upstream of realization: the format plan sampled short sentence regions and over-selected `SHORT_PHRASE` correct spans. Placement was then allowed to cluster because the plan recorded no numeric desired gaps and only a qualitative coverage/context instruction. Final mutation did not create the main sentence-shortness drift. Band sensitivity explains only the one-axis tail label, not the underlying multi-axis geometry.

Recommended minimal modification: **F — planning + span selection**. A later implementation should first correct the sampled planning distribution and make span/gap selection distribution-aware; do not relax bands to improve PASS rate.
Recommended fresh re-smoke: **25 items**.

## 1. Data and integrity boundary

| Source | Use |
|---|---|
| `tmp/we_validation_run_2/we_v2_validation_accepted.json` | canonical final cohort geometry and clean/error forms |
| `tmp/we_validation_run_2/we_v2_validation_plans.json` | per-item format plans |
| `analysis/we_format/written_expression_format_official.json` | Official 125-item comparison baseline |
| `agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json` | existing sampling guidance and thresholds, read-only |

Corrected answer location was re-derived from the clean/error lexical diff and aligned to final `span_token_indices`: 75/75 resolved to one location and 75/75 matched the stored key. The stored key was not used as the Format-analysis source. No Reviewer/Solver judgment was used. The 3 historical deletion cases are handled by mapping the diff boundary to the final marked span.

## 2. Official vs WE v2 corrected metrics

| Metric | Official 125 median (mean) | WE v2 75 median (mean) |
|---|---:|---:|
| Sentence words | 20 (20.048) | 14 (13.9467) |
| Total marked words | 5 (5.176) | 5 (5.7333) |
| Mean marked span length | 1.25 (1.294) | 1.25 (1.4333) |
| Max marked span length | 2 (1.848) | 2 (2.2267) |
| Coverage | 0.2632 (0.2705) | 0.4 (0.4186) |
| Unmarked context | 15 (14.872) | 8 (8.2133) |
| Gaps A-B / B-C / C-D | 4 / 4 / 4 | 1 / 2 / 3 |

## 3. Planned vs actual sentence length

Plan regions: `{'16-20': 10, '11-15': 60, '21-25': 2, '<=10': 3}`. The plan midpoint proxy median is 13; clean actual median is 14; final actual median is 14.
Clean sentence: 71/75 in plan range, 3 shorter, 1 longer. Final sentence: 75/75 in plan range, 0 shorter, 0 longer.

This is `PLAN_SAMPLING_DRIFT`, not primary `SENTENCE_REALIZATION_TOO_SHORT`: 63/75 plans are <=15 words, while Official has only 16/125 <=15. Clean and final outputs follow the short plan, and the mutation-stage clean→final delta has median 0.

## 4. Coverage and unmarked-context decomposition

Observed WE v2 coverage median is 0.4. Holding v2 spans and replacing sentence length with 20 gives 0.25; holding v2 sentence length and replacing spans with a rank-matched Official span distribution gives 0.375; replacing both gives 0.25.
Median Shapley-style contribution estimate: denominator/sentence length 0.1375 coverage points (about 91.67% of the observed-to-both counterfactual change); numerator/span length 0.0125 points (about 8.33%). The denominator effect is dominant; the numerator effect is secondary but real because the v2 tail has 9/300 5+ word spans.

The composite geometry proxy (including gaps; not the canonical stored distance) is 1.6739 observed, 1.4463 after sentence-only replacement, 1.6832 after span-only replacement, and 1.3516 after both. Gap-only Official replacement gives 1.5122 / 1.5581 / 1.5645 for A-B / B-C / C-D. Correct-span-type replacement changes the categorical type distance from 0.4907 to 0, while the numeric canonical distance is unchanged because type is not one of its axes.

Unmarked context tells the same story: fixed 20-word sentence with v2 spans gives median 15; Official span lengths with v2 sentence length gives 9; both gives 15. Span closeness does not change the total unmarked count, but it removes between-span context: v2 gap-sum median is 6 versus Official 11.

## 5. Marked-span length and correct-span bias

All A-D spans: Official `{'1': 375, '2': 106, '3': 16, '4': 3}`; WE v2 `{'1': 205, '2': 79, '3': 7, '5': 8, '6': 1}`. WE v2 has 9/300 5+ word spans and no 4-word spans; Official has no 5+ word spans and 3/500 4-word spans.

Correct span type: Official `{'SINGLE_WORD': 98, 'SHORT_PHRASE': 12, 'CLAUSE_OR_CLAUSE_LIKE': 15}`; WE v2 corrected `{'SINGLE_WORD': 22, 'SHORT_PHRASE': 44, 'CLAUSE_OR_CLAUSE_LIKE': 9}`. `SHORT_PHRASE` is 44/75 (58.7%) in v2 versus 12/125 (9.6%) Official; `SINGLE_WORD` is 22/75 versus 98/125. Type total-variation distance is 0.4907.

The bias is present at plan time: intended correct-span type equals realized correct-span type for 75/75, so late placement did not create the category imbalance. It is consistent with format-plan/target-selection design, while a separate candidate-pool selector trace is unavailable.

### All 5+ word spans

The complete audit of all 9 long spans is in the JSON artifact under `span_selection.long_spans`. Every one was explicitly requested by its intended span profile, so the long-span cause is planned phrase selection, not a random post-mutation expansion. For correct spans, a more local 1–2 word expression is likely in the 6/5-word reduced-relative and 5-word connector/word-order cases where the actual correction is smaller than the marked phrase; for distractors, whether a 1-word candidate existed cannot be established because candidate pools were not logged.

## 6. Distractor selection and clustering

Zero-gap rates A-B/B-C/C-D are {'A-B': 0.3067, 'B-C': 0.2667, 'C-D': 0.1333} in v2 versus {'A-B': 0.0, 'B-C': 0.0, 'C-D': 0.0} Official. v2 gap<=1 rates are {'A-B': 0.64, 'B-C': 0.4933, 'C-D': 0.2533} versus Official {'A-B': 0.072, 'B-C': 0.04, 'C-D': 0.048}.

This is consistent with selecting spans from a narrow local neighborhood or using contiguous phrase segments. At least one zero-gap pair occurs in 53.3% of v2 items versus 0% Official, and the nearest distractor to the corrected span has median gap 1 versus 4 Official. The output cannot prove the internal search range or whether a 1-word candidate was rejected, but the absent numeric gap plan plus frequent zero/one-word gaps is sufficient evidence for `SPAN_CLUSTERING=HIGH`. A is not front-biased relative to the Official anchor; D is later in normalized position (median 0.923 vs 0.800) but its absolute C-D gap is smaller (3 vs 4), so this is sentence-shortness/placement interaction rather than a distinct D-tail cause.

## 7. Batch/order and target interactions

The JSON contains all 5-item windows and 25-item blocks. There is no stable monotonic order effect: the 51–60 window partially rebounds (sentence median 15, context median 10), while 71–75 is short (11, 6). This is not a progressive collapse or the prior Batch2 failure pattern.

Target/error/locality group tables are in JSON. The long spans concentrate in `NONFINITE_VERB_PHRASES`, `CONNECTORS_CONJUNCTIONS`, and `WORD_ORDER_MODIFICATION`; this is a grammar/target interaction with the plan's explicit long profiles, not evidence that Grammar quality was evaluated.

## 8. Band sensitivity separated from geometry

Worst-band counts are {'PREFERRED': 0, 'WARNING': 3, 'EXTREME': 72}. Of 75 items, 10 are SINGLE_TAIL (13.3%), 54 MULTI_TAIL (72.0%), and 8 HIGH_DISTANCE_MULTI_TAIL (10.7%); 62/75 (82.7%) are multi-axis geometry departures. Thus, at most the 10 single-tail items are band-sensitivity candidates; the core median drift remains if band labels are removed.

## 9. Root-cause ranking

| Root cause | Rating | Evidence summary |
|---|---|---|
| `PLAN_SAMPLING_DRIFT` | **HIGH** | Plan regions: 60/75=80.0% in 11-15 and 3/75=4.0% <=10; only 12/75 are >=16. Official has 16/125 <=15 and 109/125 >=16. Plan midpoint proxy median is short and clean/final outputs conform to it. |
| `SENTENCE_REALIZATION_TOO_SHORT` | **LOW** | Clean sentence actual is already short; final-clean mutation deltas are small and final output is generally within the short plan range. It is not the dominant root once plan drift is controlled. |
| `SPAN_SELECTION_TOO_LONG` | **MEDIUM** | V2 has 9/300 5+ word spans and no 4-word spans versus Official 0/500 5+ and 3/500 4-word; all 9 long spans were explicitly planned, so origin is plan/selection design rather than incidental realization. |
| `SPAN_CLUSTERING` | **HIGH** | Gap medians 1/2/3 versus Official 4/4/4, with frequent zero gaps and lower between-span context. The plan contains no numeric gap target. |
| `CORRECT_SPAN_TYPE_BIAS` | **HIGH** | SHORT_PHRASE is 44/75=58.7% versus Official 12/125=9.6%; SINGLE_WORD is 22/75=29.3% versus 78.4%. Intended correct type equals realized type for 75/75. |
| `FORMAT_BAND_OVER_SENSITIVITY` | **LOW** | 10/75 are SINGLE_TAIL, but 62/75 are MULTI_TAIL or HIGH_DISTANCE_MULTI_TAIL. Band labels do not create the observed geometry drift. |
| `FORMAT_PLAN_UNDERSPECIFICATION` | **HIGH** | Coverage is qualitative only and desired gaps are not logged; therefore placement/context loss has no numeric plan control. This is a contributing mechanism under planning/placement, not a separate requested code change. |

## 10. Minimal change recommendation

**F — planning + span selection.** Rebalance the format plan's sentence-length and correct-span-type draws toward the Official empirical guidance, add numeric/observable gap and coverage objectives to planning, and make span selection prefer local grammar-relevant spans with distributed placement. Do not change grammar mutation logic and do not loosen bands merely to raise PASS rate.

## 11. Next re-smoke

Choose **25 fresh items** after implementation. Success should require: sentence median in the Official-like central region (target 18–22, with no more than 25% at <=15); coverage median 0.22–0.32 and no normal-pattern >=60% tail; unmarked context median 12–18 and zero-context count 0; span distribution close to the Official 1/2/3/4 profile with no planned 5+ spans unless explicitly justified; gap medians within approximately 3–5 for A-B/B-C/C-D and zero gaps rare; correct span types approximately Official-like (not a majority SHORT_PHRASE); and PREFERRED/WARNING/EXTREME with PREFERRED as the modal/majority status, no more than 25% EXTREME, plus separate reporting of SINGLE_TAIL versus multi-tail. Grammar remains a separate NOT_EVALUATED gate unless a live independent grammar review is available.

## 12. Final concise report

- Official vs WE v2: sentence 20 vs 14; coverage 0.2632 vs 0.4; unmarked 15 vs 8; gaps 4/4/4 vs 1/2/3.
- Planned vs actual sentence: plan midpoint median 13; clean 14; final 14; plan shortness is primary.
- Coverage: denominator/sentence length is the dominant contribution (0.1375 median coverage points); span numerator is secondary (0.0125).
- Correct-span bias: SHORT_PHRASE overrepresented at plan time and realized 44/75.
- Long spans: 9/300 5+ word spans, all explicitly planned; correct-span alternatives are often locally reducible, distractor candidate availability is not observable.
- Clustering: zero/one-word gaps and low gap medians show local clustering; missing numeric gap planning is a contributor.
- Unmarked context: primarily lost to short planned sentences; span length adds a smaller numerator effect, clustering removes between-span context.
- Band sensitivity: 10/75 single-tail candidates; 62/75 multi-axis geometry departures, so band oversensitivity is not dominant.
- Dominant roots: PLAN_SAMPLING_DRIFT, CORRECT_SPAN_TYPE_BIAS, SPAN_CLUSTERING, and FORMAT_PLAN_UNDERSPECIFICATION.
- Minimal modification: F (planning + span selection).
- Re-smoke: 25 fresh items.

## Artifact contents

Per-item planned/clean/final sentence lengths, span lengths, corrected answer locations, starts, gaps, and marked text are in `we_v2_format_drift_root_cause.json`; the nine long-span audits and all 5-item windows are included there.
