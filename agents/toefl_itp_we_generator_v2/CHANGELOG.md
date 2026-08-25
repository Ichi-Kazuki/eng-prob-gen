# WE Generator v2 changelog

## v2.1 — 2026-08-25

Root cause addressed: `PLAN_SAMPLING_DRIFT` in sentence-length, correct-span
type, and span-placement planning. `SENTENCE_REALIZATION_TOO_SHORT` remains a
low-risk conformance check; prose generation is not padded or otherwise
rewritten after planning.

### Changed

- sentence targets are empirical draws from the official 125-item artifact,
  with deterministic planned-range conformance checks;
- correct-span types and conditional correct-span lengths are sampled from
  official observed counts;
- the grammar-required correct locus remains minimal and is never shortened
  merely to satisfy a sampled type;
- distractor candidates are enumerated across the whole sentence, with
  one-word and natural two-word units preferred;
- normal span candidates stop at four words, with explicit exception rationale
  required for any 5+ word span;
- gap targets are sampled from official gap observations and normal selection
  rejects zero-gap adjacency;
- candidate combinations are scored using marked words, coverage, unmarked
  context, gaps, maximum span, correct-span type, and answer position as soft
  geometry preferences;
- pre-emission checks reject plan-conformance failures before output and prefer
  span reselection before regenerating a sentence.

### Scope boundary

`grammar generation logic unchanged, format planner + span-selection policy only`

Unchanged: grammar target taxonomy, error-generation/mutation logic, Reviewer,
Solver, Orchestrator, JSON Schema field meaning, Grammar Specification, Format
Specification observed values, and Format band thresholds. v2.0/v2.0.1
historical artifacts remain in their original locations and are not rewritten.
