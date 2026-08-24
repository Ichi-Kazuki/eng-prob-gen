# TOEFL ITP Written Expression Format Specification Changelog

## 1.0.0 — 2026-08-24

Added the Written Expression format-layer specification as an additive companion to the existing grammar specification.

### Added

- Official 125-item sentence-length observations.
- Official 500-span word-count and syntactic-span-type observations.
- Marked coverage and unmarked-context observations.
- Approximate PDF span-gap observations with confidence limitation.
- Correct-span length/type observations.
- `correction_locality` and `decision_granularity` dimensions.
- Official-versus-AI Validation v1.1 format mismatch evidence.
- Explicit OBSERVED / DERIVED RULE / HEURISTIC classification contract.
- Sentence-first construction sequence for future Generator v1.2 design.
- Distribution-aware coverage policy with deferred numeric thresholds.
- Machine-readable future diagnostics and separate format/grammar review requirements.

### Explicitly unchanged

- Generator v1.1
- Reviewer v1.1
- Solver
- Orchestrator
- grammar taxonomy
- database
- Website
- existing `TOEFL_ITP_GRAMMAR_SPEC`

