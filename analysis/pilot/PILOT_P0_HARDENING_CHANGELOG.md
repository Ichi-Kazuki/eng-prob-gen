# Pilot P0 Hardening Changelog

Date: 2026-08-23

## v1.1 — Written Expression hardening

Scope is limited to the Generator Agent, Reviewer Agent, and regression tests/fixtures.

### Generator

- Added a construction-safety gate separating genuine grammatical/ syntactic/
  morphological/established-usage violations from semantic oddity.
- Added explicit connector caution for `because` / `although`-type designs.
- Added internal alternate-parse checks for coordination, parallelism,
  reduced relatives, PP/clause attachment, and complement frames.
- Added unique minimal-repair requirements.
- Added lexical complement-frame caution, including the `feel`-style noun-object
  reading that caused `pilot-we-006`.
- Preserved the Generator boundary: it does not emit PASS/REVISE/REJECT or add
  internal audit fields to item JSON.

### Reviewer

- Added an explicit four-phase Written Expression audit:
  zero-based full sentence, marked-part classification, alternate parse, and
  alternate repair.
- Made `NONE` a formal hypothesis and made zero-error, multi-error, and
  parse/repair ambiguity PASS blockers.
- Explicitly separated semantic oddity from genuine grammatical error.
- Added focused hard gates for coordination, parallelism, complement structure,
  connector attachment, and clause/PP attachment.

### Regression assets

- Added `analysis/pilot/pilot_p0_hardening_regression.json`, a seven-case manifest
  that references the existing Pilot provenance without copying item text into
  a generation template.
- Added `agents/toefl_itp_grammar_reviewer/scripts/run_p0_hardening_regression.py`.
- Added generated test result artifact
  `analysis/pilot/pilot_p0_hardening_regression_results.json` after running the
  static contract test.

### Explicitly unchanged

- `specs/TOEFL_ITP_GRAMMAR_SPEC.md`
- `specs/toefl_itp_grammar_spec.json`
- grammar taxonomy files
- Solver Agent and Solver schemas/scripts
- Orchestrator code and consensus policy
- DB and Web site
- No 120-question validation batch was generated.

### Runtime content hashes after v1.1

- Generator: `sha256:3567f2b6e246`
- Reviewer: `sha256:e4142013a3cb`
- Solver (unchanged): `sha256:df1200bed2b1`
