# TOEFL ITP Grammar Generator Agent

Prompt revision: **v1.1 (P0 Written Expression hardening)**. The runtime
definition in `.claude/agents/toefl-itp-grammar-generator.md` is authoritative.

Generator-only agent for TOEFL ITP Level 1 **Structure (Part A)** and
**Written Expression (Part B)** practice items. This document is the
human-readable companion to the runtime subagent definition at
`.claude/agents/toefl-itp-grammar-generator.md`. If the two ever disagree,
the subagent `.md` file is authoritative for behavior (it is what actually
gets loaded when the agent runs); this file exists for engineers/reviewers
who want the shape of the system without reading the full prompt.

## Scope

This agent **only generates**. It does not:
- grade, review, or self-approve ("PASS") its own output — that is a future
  Reviewer Agent's job
- solve items — that is a future Solver Agent's job
- orchestrate a multi-agent pipeline — that is a future Orchestrator's job
- mass-produce large batches — batch size is caller-specified, no default
  bulk generation
- write to a database — output is JSON only

## Inputs (sole source of truth)

The agent reads exactly these four files before generating anything, and
must not invent format or taxonomy rules beyond what they contain:

1. `specs/TOEFL_ITP_GRAMMAR_SPEC.md` — human-readable generation spec
   (format rules, distribution guidance, hard rules, anti-patterns,
   copyright constraints)
2. `specs/toefl_itp_grammar_spec.json` — machine-readable companion; the
   authoritative source for enum values (`primary_target` ids,
   `tested_error_type` ids, distribution guidance ranges, etc.)
3. `analysis/GRAMMAR_TAXONOMY.md` — human-readable taxonomy
4. `analysis/grammar_taxonomy.json` — machine-readable taxonomy (v1.1)

**Explicitly excluded from generation context** (analyzed ETS official
items — copying/paraphrase risk):
`analysis/structure_items_all.json`, `analysis/written_expression_items_all.json`,
`analysis/*.csv`, `analysis/raw/*`, `source/*.pdf`. The agent must never read
these files as inspiration for item content.

## Method: plan-before-generate

Per item, the agent fixes an internal plan (primary_target, subtype,
secondary_features, difficulty, vocabulary_domain, sentence/clause targets,
correct_answer_position, and — for Structure — distractor error types, or
— for Written Expression — tested_error_type/error_span_type/error_location/
error_scope) **before** writing any sentence text. Post-hoc labeling of
already-written text is prohibited. The internal plan is not included in
the final output JSON.

For multi-item requests, a batch-level plan is fixed first, controlling:
primary_target distribution, difficulty distribution, correct-answer-position
distribution, sentence-length diversity, clause-count diversity,
vocabulary-domain diversity, and distractor/error-type diversity — per the
guidance ranges in the spec (heuristic targets, not hard quotas). No more
than 2 consecutive items share the same construct, topic, or answer
position.

## Written Expression P0 hardening

The Generator must not turn semantic oddity, logical unusualness, stylistic
awkwardness, or contextual unlikelihood into a grammatical error. This is
especially important for connector choices such as `because` / `although`:
if both are syntactically licensed and only one is semantically preferred, the
design must be abandoned or reframed.

Before emitting a Written Expression item, the Generator must internally:

1. distinguish a genuine standard-English grammatical/syntactic/morphological/
   established-usage violation from a semantic or stylistic problem;
2. test an intended parse and at least one plausible alternate parse, with
   special attention to coordination, parallelism, reduced relatives, PP/clause
   attachment, connectors, and lexical complement frames;
3. verify that one marked error has one clear minimal repair; and
4. switch away from a lexical complement/connector/collocation realization when
   the frame permits another standard-English reading.

If an alternate parse creates a different marked error, a second marginal
reading, or a different valid repair, the item must not be emitted. These are
construction-safety checks, not a Generator PASS/REVISE/REJECT verdict.

## Output schema

Two item shapes, JSON Schema (draft 2020-12) definitions at:
- `agents/toefl_itp_grammar_generator/schema/structure_item.schema.json`
- `agents/toefl_itp_grammar_generator/schema/written_expression_item.schema.json`

Structure fields: `item_id, section, primary_target, subtype,
secondary_features, difficulty, vocabulary_domain, stem, options{A-D},
correct_answer, answer_explanation, distractor_rationales{A-D}`.

Written Expression fields: `item_id, section, primary_target, subtype,
secondary_features, tested_error_type, error_scope, difficulty,
vocabulary_domain, sentence, marked_parts{A-D}, correct_answer,
minimal_correction, answer_explanation`.

Note: `tested_error_type` for Written Expression excludes `fragment` and
`wrong_complementation` (structurally impossible / superseded by
`wrong_preposition_collocation` for this section — spec footnotes 1 & 2).
The WE schema enum reflects this (13 of the 15 taxonomy values).

Multiple items may be wrapped as `{"items": [...]}`.

## Validation

`agents/toefl_itp_grammar_generator/scripts/validate_output.py <file>` runs
schema-level checks only (option/marked-part counts, `correct_answer` in
A-D and pointing at a real entry, `primary_target`/`tested_error_type`
membership in the taxonomy, `error_scope` in the closed set,
`difficulty` in EASY/MEDIUM/HARD). It does **not** judge grammatical
correctness, distractor quality, or "TOEFL-ITP-likeness" — that judgment is
out of scope for this agent and is deferred to a future Reviewer Agent.
Dependency-free (stdlib `json` only); reads the enum source-of-truth
directly from `specs/toefl_itp_grammar_spec.json` at runtime.

## Copyright / source separation

No copying or light paraphrase of the 200 analyzed ETS items (Practice
Tests B-F). No reuse of distinctive phrases, proper nouns, dates, statistics,
or "person + fact + number" combinations from source items, even reworded.
Every generated sentence must be independently authored from the spec's
abstracted design features, not derived from a specific source item. See
spec §11 for the full binding constraints.

## Files

- `.claude/agents/toefl-itp-grammar-generator.md` — runtime subagent
  definition (Japanese; invocable via the Agent tool as
  `toefl-itp-grammar-generator`)
- `agents/toefl_itp_grammar_generator/AGENTS.md` — this file
- `agents/toefl_itp_grammar_generator/schema/structure_item.schema.json`
- `agents/toefl_itp_grammar_generator/schema/written_expression_item.schema.json`
- `agents/toefl_itp_grammar_generator/scripts/validate_output.py`
