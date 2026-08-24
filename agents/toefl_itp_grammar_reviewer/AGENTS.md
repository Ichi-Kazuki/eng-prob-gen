# TOEFL ITP Grammar Reviewer Agent

Prompt revision: **v1.1 (P0 Written Expression hardening)**. The runtime
definition in `.claude/agents/toefl-itp-grammar-reviewer.md` is authoritative.

Review-only agent for candidate TOEFL ITP Level 1 Structure (Part A) and
Written Expression (Part B) items produced by the Generator Agent. This
document is the human-readable companion to the runtime subagent
definition at `.claude/agents/toefl-itp-grammar-reviewer.md`; that file is
authoritative for behavior.

## Scope

This agent **only reviews**. It does not:
- generate new items — that is the Generator Agent's job
  (`agents/toefl_itp_grammar_generator/`)
- rewrite or auto-correct item text directly — it returns
  `revision_requirements` as text, never an edited item
- act as an Independent Solver Agent (a separate, not-yet-built agent that
  will attempt items blind, for cross-validation) or an Orchestrator
- schedule or run mass batches, or write to a database

## Inputs (sole source of truth)

Same four files as the Generator Agent:
1. `specs/TOEFL_ITP_GRAMMAR_SPEC.md`
2. `specs/toefl_itp_grammar_spec.json`
3. `analysis/GRAMMAR_TAXONOMY.md`
4. `analysis/grammar_taxonomy.json`

The Generator Agent's own files may be read for cross-reference. ETS
official item data (`source/*.pdf`, `analysis/raw/*`,
`analysis/*_items_all.json`, `analysis/*_items_all.csv`) must never be read
during review — the Reviewer judges a candidate item against the abstracted
Specification, not against real exam items.

## Method: independent-answer-first

Before comparing against the Generator's stated `correct_answer`, the
Reviewer determines its own answer from the item text alone
(`independent_answer`). For Written Expression this means auditing the full
sentence for every genuine grammatical error *before* looking at which part
is marked as the intended answer. Only after that independent judgment is
formed does the Reviewer compare it to the Generator's answer
(`answer_match`). This ordering exists specifically to prevent
rationalizing the Generator's stated answer instead of checking it.

For Written Expression, the v1.1 review sequence is explicit:

1. zero-based full-sentence audit, with `NONE` retained as a formal hypothesis;
2. independent `ACCEPTABLE` / `ERROR` / `MARGINAL` classification for all four
   marked parts;
3. alternate-parse audit for coordination, parallelism, complement structure,
   connector/clause/PP attachment, and reduced relatives; and
4. alternate-repair audit to ensure that one marked error does not admit multiple
   competing minimal corrections.

Semantic oddity, logical unusualness, stylistic awkwardness, and contextual
unlikelihood are not genuine grammatical errors by themselves. A zero-error,
multi-error, or parse/repair-ambiguous Written Expression item must not receive
`PASS`, even when its Generator answer looks plausible.

## Verdicts

- `PASS` — no critical failure; ready for an Independent Solver.
- `REVISE` — usable design, but the Generator needs to regenerate/adjust
  specific aspects (given in `revision_requirements`).
- `REJECT` — fundamental failure; regenerating from scratch is more
  efficient than revising this item.

A `critical_failure: true` item (multiple/zero correct answers, second
genuine WE error, an "error" that is actually acceptable English, a
Hard Rule violation, etc. — full list in the subagent `.md` §3) can never
receive `PASS`.

## Output schema

`agents/toefl_itp_grammar_reviewer/schema/reviewer_output.schema.json`.
Common fields: `item_id, section, verdict, critical_failure,
independent_answer, generator_answer, answer_match, reviewer_difficulty,
generator_difficulty, difficulty_mismatch, checks{7 sub-checks},
issues[]{severity, category, description, related_check},
revision_requirements[], source_similarity_risk`. Written Expression items
additionally require `detected_error_count, detected_error_position,
non_error_parts_valid, minimal_correction_valid`.

## Validation

`agents/toefl_itp_grammar_reviewer/scripts/validate_output.py <file>`
checks only the shape of the Reviewer's own output (required fields, enum
membership, and the internal-consistency rule that `critical_failure: true`
cannot coexist with `verdict: PASS`). It does not judge whether a verdict
is the *correct* verdict — that is exercised by the adversarial test
process (deliberately broken items that must not receive PASS), not by
schema validation.

## Test artifacts

- `analysis/reviewer_smoke_test.json` — review results for the 6 items in
  `analysis/generator_smoke_test.json`.
- `analysis/reviewer_adversarial_test.json` — review results for a small
  set of deliberately broken items (multiple/zero correct answers, WE
  double/zero error, mismatched metadata) used only to verify the Reviewer
  actually catches critical failures. These broken items are Reviewer-test
  fixtures, not usable practice content, and are not added to any item bank.

## Files

- `.claude/agents/toefl-itp-grammar-reviewer.md` — runtime subagent
  definition (Japanese; invocable via the Agent tool as
  `toefl-itp-grammar-reviewer`)
- `agents/toefl_itp_grammar_reviewer/AGENTS.md` — this file
- `agents/toefl_itp_grammar_reviewer/schema/reviewer_output.schema.json`
- `agents/toefl_itp_grammar_reviewer/scripts/validate_output.py`
