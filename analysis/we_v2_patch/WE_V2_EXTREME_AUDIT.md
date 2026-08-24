# WE v2.0.1 Live Re-smoke EXTREME Audit

Audit target: the ten-item live re-smoke `we-v2-live-resmoke-20260824-patch-01`.
The audited commit `9620834` changes Generator code (canonical diagnostics emission and
validation). It does not change generation policy, Reviewer, Solver, Orchestrator,
Specification, Taxonomy, or band thresholds.

## Decision

**A_CONDITIONAL: complete human review of all six live EXTREME items before proceeding
to 75-item Validation.** The pilot blind sample is not a substitute for review of the
live outliers. Do not proceed until all six reviews and the required ratings are recorded,
and block progression if any review has a blocking finding.

Required live EXTREME reviews:

`001`, `002`, `003`, `004`, `006`, and `007`.

All six currently have `format_validity: FAIL` and `human_review_required: true`.

## Distance correction

The official source contains max-span values 1 through 4 with counts 39, 69, 14, and 3.
Using the same sample-standard-deviation convention as the other configured statistics:

- `max_span_length` mean: `1.848`
- `max_span_length` sample standard deviation: `0.7077`

Therefore `max_span_length` is included in the five-metric
`root_mean_square_standardized_distance`. Only the three gap dimensions remain excluded
from numeric distance. This correction changes diagnostic distances and contribution
rankings, not the eight-dimensional band assignment.

| item | band | distance | official distance percentile |
|---|---|---:|---:|
| 001 | EXTREME | 0.7898 | 0.376 |
| 002 | EXTREME | 0.2603 | 0.052 |
| 003 | EXTREME | 0.3127 | 0.072 |
| 004 | EXTREME | 1.6196 | 0.928 |
| 005 | WARNING | 0.9560 | 0.616 |
| 006 | EXTREME | 0.3877 | 0.108 |
| 007 | EXTREME | 0.6025 | 0.256 |
| 008 | PREFERRED | 0.4743 | 0.200 |
| 009 | PREFERRED | 0.3877 | 0.108 |
| 010 | WARNING | 0.4743 | 0.200 |

## Band decomposition

The six EXTREME items are caused by the existing worst-of-eight band rule:

- `gap_A_B` below/above threshold: items 001 and 007
- `gap_B_C` below q05: items 002, 004, 006, and 007
- `gap_C_D` above q95: item 003
- `marked_coverage_ratio` above q95: item 004
- `mean_span_length` above q95: item 004

Distance is diagnostic only and is not a direct band-assignment input.

## Canonical-injection audit

The patch adds canonical diagnostics injection and fail-closed emission validation.
Classification semantics and band thresholds remain unchanged. The distance report now
uses the observed official max-span variance rather than the stale zero-stdev omission.

Regression evidence remains:

- missing-diagnostics fixtures: 3/3 reject before injection and pass after injection;
- live diagnostics completeness: 10/10;
- live diagnostics consistency: 10/10;
- classification drift from canonical injection: none observed.

## Artifacts

- `we_v2_extreme_audit.json`
- `live_resmoke_items.json`
- `live_resmoke_metrics.json`
- `live_resmoke_review.json`
- `human_targeted_sample.json` (pilot blind sample; not live-outlier review)
- `human_targeted_sample_key.json`
