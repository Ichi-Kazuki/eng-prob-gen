# TOEFL ITP Independent Solver Agent

Blind-solve-only agent for candidate TOEFL ITP Level 1 Structure (Part A)
and Written Expression (Part B) items. This document is the human-readable
companion to the runtime subagent definition at
`.claude/agents/toefl-itp-grammar-solver.md`; that file is authoritative
for behavior.

## Scope

This agent **only solves**. It does not:
- generate items — that is the Generator Agent's job
  (`agents/toefl_itp_grammar_generator/`)
- judge item quality or return PASS/REVISE/REJECT — that is the Reviewer
  Agent's job (`agents/toefl_itp_grammar_reviewer/`)
- assess distractor quality, naturalness, TOEFL style, source similarity,
  metadata alignment, or batch distribution — all out of scope for a
  Solver, which just answers the question in front of it
- act as an Orchestrator, an auto-correction agent, or perform mass
  generation / DB writes

## Why a Solver exists

Generator and Reviewer both work with full knowledge of the intended
answer and metadata. The Solver is the check on whether an item is
actually *solvable* by someone who has none of that — the closest
approximation available to an actual test-taker. Its independence from
`correct_answer` is the entire point.

## Blinding mechanism

`agents/toefl_itp_grammar_solver/scripts/create_solver_input.py` converts
a Generator-shaped (or Reviewer-test fixture) item into Solver input via an
**allowlist**, not a blacklist:

- Structure keeps only: `item_id, section, stem, options`
- Written Expression keeps only: `item_id, section, sentence, marked_parts`

Every other field — `correct_answer`, `answer_explanation`,
`distractor_rationales`, `primary_target`, `subtype`, `secondary_features`,
`tested_error_type`, `difficulty`, `error_scope`, `minimal_correction`, any
internal test-fixture annotation (e.g. `_intended_flaw`) — is dropped
without being read. An allowlist was chosen specifically so that new
metadata fields added to the Generator's schema in the future can't leak
to the Solver by omission; only fields explicitly named here ever pass
through.

The Solver never reads Generator or Reviewer output files directly —
only the blinded file produced by this script.

## Solving method

- **Structure**: insert each of A-D into the stem independently and rate
  each `VALID` / `INVALID` / `MARGINAL`. Exactly one `VALID` → answer that
  position. Two or more `VALID` → `AMBIGUOUS`. Zero `VALID` → `NONE`. A
  `MARGINAL` that threatens uniqueness → `AMBIGUOUS`.
- **Written Expression**: audit the full sentence first, ignoring the A-D
  labels, then rate each marked part `ACCEPTABLE` / `ERROR` / `MARGINAL`.
  Exactly one `ERROR` → answer that position. Two or more → `AMBIGUOUS`.
  Zero → `NONE`. A `MARGINAL` that threatens uniqueness → `AMBIGUOUS`.

Forced guessing is prohibited: `AMBIGUOUS` and `NONE` are first-class,
expected answers when the item itself is flawed — the Solver never
back-infers what the Generator "must have intended."

## Output schema

`agents/toefl_itp_grammar_solver/schema/solver_output.schema.json`.
Common fields: `item_id, section, solver_answer (A/B/C/D/AMBIGUOUS/NONE),
confidence (HIGH/MEDIUM/LOW), reason, ambiguity_detected`. Written
Expression items additionally require `suggested_correction`.
`ambiguity_detected` must be `true` iff `solver_answer` is `AMBIGUOUS` or
`NONE`.

## Validation

`agents/toefl_itp_grammar_solver/scripts/validate_output.py <file>` enforces
the committed Draft 2020-12 schema. Its `additionalProperties:false` rule is
the Solver-output allowlist, and its conditionals enforce
`ambiguity_detected` consistency. Exit codes are 0 valid, 1 output validation
failure, and 2 runtime failure.

## Test artifacts

- `analysis/solver_smoke_test_input.json` — blinded version of
  `analysis/generator_smoke_test.json`, produced by
  `create_solver_input.py`.
- `analysis/solver_smoke_test.json` — Solver's answers for those 6 items.
- `analysis/solver_adversarial_test_input.json` — blinded version of the
  Reviewer's `analysis/reviewer_adversarial_test.json` fixtures.
- `analysis/solver_adversarial_test.json` — Solver's answers for those 5
  deliberately-broken fixtures (used only to confirm the Solver reports
  `AMBIGUOUS`/`NONE` rather than guessing).

## Files

- `.claude/agents/toefl-itp-grammar-solver.md` — runtime subagent
  definition (Japanese; invocable via the Agent tool as
  `toefl-itp-grammar-solver`)
- `agents/toefl_itp_grammar_solver/AGENTS.md` — this file
- `agents/toefl_itp_grammar_solver/schema/solver_output.schema.json`
- `agents/toefl_itp_grammar_solver/scripts/create_solver_input.py`
- `agents/toefl_itp_grammar_solver/scripts/validate_output.py`
