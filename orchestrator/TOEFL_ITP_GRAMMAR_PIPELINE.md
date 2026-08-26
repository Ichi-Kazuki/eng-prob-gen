# TOEFL ITP Grammar Item Generation Orchestrator

Connects the three completed agents -

- **Generator** — `.claude/agents/toefl-itp-grammar-generator.md`, `agents/toefl_itp_grammar_generator/`
- **Reviewer** — `.claude/agents/toefl-itp-grammar-reviewer.md`, `agents/toefl_itp_grammar_reviewer/`
- **Solver** — `.claude/agents/toefl-itp-grammar-solver.md`, `agents/toefl_itp_grammar_solver/`

into a single state-transition pipeline that only lets a candidate item become
`ACCEPTED` when Generator, Reviewer, and Solver independently agree, per
`specs/TOEFL_ITP_GRAMMAR_SPEC.md` / `specs/toefl_itp_grammar_spec.json`.

## 0. What the Orchestrator is and is not

The Orchestrator **never**:

- writes or rewrites a TOEFL item
- judges grammar
- judges quality in place of the Reviewer
- solves an item in place of the Solver
- decides "the Generator is probably right" by majority vote or guesswork

The Orchestrator **only**:

- calls agents in the correct order and gates each call on the previous
  stage's verdict
- validates each agent's output shape by shelling out to that agent's own
  existing `validate_output.py` (never re-implementing schema checks)
- blinds candidates for the Solver by shelling out to the existing
  `agents/toefl_itp_grammar_solver/scripts/create_solver_input.py`
  (never re-implementing metadata stripping) and then re-checks the result
  with its own leakage guard
- enforces retry/revision limits
- computes the `AUTO_ACCEPT` rule mechanically from fields the three agents
  already reported
- records provenance, split into a public `accepted_item` and an internal
  `qa_audit` record
- queues disagreements to a human review queue

Implementation: `orchestrator/scripts/orchestrator.py` (engine) plus three
replay/test scripts and an acceptance-test suite (section 10 below).

**Scope of this delivery.** This implementation does not call the live
Generator/Reviewer/Solver agents in bulk, does not write to a Question DB,
and does not connect to a site. The engine is exercised by *replaying* the
project's existing fixture outputs (`analysis/generator_smoke_test.json`,
`analysis/reviewer_smoke_test.json`, `analysis/solver_smoke_test.json`, the
adversarial fixtures, and the REJECT fixtures) through the same code path a
live run would use. A live run wires the same `orchestrator.py` functions to
real Agent-tool calls at the three call sites documented in section 6.

## 1. States

| State | Meaning |
|---|---|
| `GENERATED` | Generator produced an item; not yet schema-checked. |
| `GENERATION_FAILED` | System failure invoking or parsing an agent's output (any stage) — transient, not a quality judgement. |
| `VALIDATION_FAILED` | An agent's output parsed as JSON but failed its own `validate_output.py` schema check (any stage) — a content-shape failure, still not a quality judgement. |
| `REVIEWING` | Reviewer is evaluating (or has been asked to evaluate) the candidate. |
| `REVISE_REQUIRED` | Reviewer returned `REVISE`; candidate is queued for regeneration with a limited retry budget. |
| `REJECTED` | Reviewer returned `REJECT`; candidate is terminated — never patched. |
| `SOLVING` | Reviewer returned `PASS`; candidate has been blinded and handed to the Solver. |
| `ACCEPTED` | All `AUTO_ACCEPT` conditions held; item is ready for the (future, out of scope) Question DB. |
| `MANUAL_REVIEW` | Reviewer/Solver disagreed in a way the Orchestrator is not allowed to resolve itself. |
| `DISCARDED` | Retry budget exhausted, or Solver returned `NONE`; a brand-new item must be generated from scratch. |

`GENERATION_FAILED` / `VALIDATION_FAILED` are stage-agnostic in this
implementation (a `failure.stage` field on the record records which of
generator/reviewer/solver actually failed) rather than one dedicated state
per stage, to keep the state list the size the spec asked for while still
letting `run_acceptance_tests.py` #14 tell system failures and content-shape
failures apart.

## 2. State diagram

```
GENERATED --(schema OK)--> REVIEWING --(verdict PASS)--> SOLVING --(consensus)--> ACCEPTED
   |            |                |                                     |
   | (schema     | (schema        |--(verdict REVISE, cycles<max)-->    |--(mismatch)--> MANUAL_REVIEW
   |  fail)      |  fail)         |        REVISE_REQUIRED              |--(NONE)-------> DISCARDED
   v            v                |        (loop: Generator sees          
VALIDATION_    VALIDATION_       |         issues/revision_requirements  
FAILED         FAILED            |         only, regenerates, re-enters
   |                             |         REVIEWING)
   | (retry <= max_generation_   |
   |  validation_retries)        |--(verdict REVISE, cycles>=max)--> DISCARDED
   v                             |
GENERATED (retry)                |--(verdict REJECT)----------------> REJECTED
                                            (never patched; new item_id
                                             required for a fresh attempt)

any agent-call/JSON-parse failure at any stage --> GENERATION_FAILED
  --(retry <= max_system_failure_retries)--> re-attempt same stage
  --(retries exhausted)--> MANUAL_REVIEW (infra issue, not a content judgement)
```

`SOLVING` is only ever entered from `REVIEWING` on verdict `PASS`. There is
no code path that calls the Solver from `REVISE_REQUIRED` or `REJECTED`
(`orchestrator.process_solver_stage()` raises if called on a candidate not
in state `SOLVING`).

## 3. Generator → Reviewer (spec section 4)

1. Generator produces a candidate item.
2. Orchestrator validates it via `agents/toefl_itp_grammar_generator/scripts/validate_output.py`
   (shelled out to, not re-implemented).
   - Fails to parse / script can't run → `GENERATION_FAILED` (system failure, retryable).
   - Parses but fails schema → `VALIDATION_FAILED` (content-shape failure,
     retry regeneration up to `max_generation_validation_retries`).
   - Passes → `REVIEWING`.
3. Reviewer evaluates the candidate.

## 4. Reviewer routing (spec section 5)

- **PASS** → `SOLVING`.
- **REVISE** → `REVISE_REQUIRED`. The Orchestrator builds Generator feedback
  via `build_generator_feedback()`, which allowlists exactly
  `{item_id, issues, revision_requirements}` — **never**
  `independent_answer`, `checks`, `verdict`, `generator_answer`,
  `answer_match`, or `source_similarity_risk`. The revised candidate is
  re-submitted to the Reviewer; it is never sent to the Solver directly.
- **REJECT** → `REJECTED` immediately, regardless of revision count. The
  candidate is not patched; a brand-new item_id must be generated from
  scratch (see `derive_slot_requirements()` / section 9 below for carrying
  forward the batch slot).

## 5. Retry limits (spec section 6, configurable — `orchestrator/config.json`)

```json
{
  "max_revision_cycles": 2,
  "max_generation_validation_retries": 2,
  "max_system_failure_retries": 3
}
```

- REVISE cycles are counted per candidate (`revision_count`). After a 2nd
  consecutive REVISE without a PASS, the candidate is `DISCARDED`
  (`process_review_output()`).
- REJECT ends the candidate immediately, independent of `revision_count`.
- Schema-validation retries and system-failure retries are tracked
  separately from `revision_count`, because neither is a content-quality
  judgement (spec section 16 / this doc section 8).

## 6. Solver blinding (spec section 7)

`orchestrator.blind_for_solver()` uses the shared pure function in
`shared/solver_blinding.py`; the existing CLI remains a compatibility
wrapper. The Orchestrator does not duplicate metadata stripping.
On top of that,
`orchestrator.leakage_guard()` re-checks the blinded item's keys are
*exactly* the section's allowlist (`item_id, section, stem, options` for
Structure; `item_id, section, sentence, marked_parts` for Written
Expression) before the item is ever handed to the Solver. A leakage-guard
failure routes to `MANUAL_REVIEW` rather than silently proceeding.

The live drivers commit the Candidate state containing the canonical payload
before publishing `solver_input_batch.json`. The batch retains the historical
`items` array and adds an artifact version plus a fingerprint of the committed
state. Solver application refuses a missing, stale, or tampered batch, so the
artifact is a rebuildable projection rather than a second source of truth.

**Live call sites** (where a future live run wires in real Agent-tool
calls, replacing the fixture lookups used by the replay scripts in this
delivery):

1. after `process_generation_output()` reaches `REVIEWING` → call the
   Reviewer agent with the raw Generator item, feed its JSON output to
   `process_review_output()`.
2. after `process_review_output()` reaches `SOLVING` → call
   `blind_for_solver()`, then call the Solver agent with the canonical
   blinded item, feed its JSON output to `process_solver_stage()`. The stage
   boundary re-derives and compares the canonical payload before consensus.
3. on `REVISE_REQUIRED` → call the Generator agent again with
   `build_generator_feedback(reviewer_item)`, feed the new candidate back
   into `process_generation_output()`.

## 7. Consensus rule — `AUTO_ACCEPT` (spec section 8)

`orchestrator.evaluate_consensus()` checks, mechanically, in this exact
form (no majority vote):

```
reviewer.verdict == "PASS"
AND reviewer.critical_failure == false
AND reviewer.independent_answer == generator.correct_answer
AND solver.solver_answer in ["A","B","C","D"]
AND solver.solver_answer == generator.correct_answer
AND solver.solver_answer == reviewer.independent_answer
AND solver.ambiguity_detected == false
AND solver.confidence in ["HIGH","MEDIUM"]
AND reviewer.source_similarity_risk != "HIGH"
```

All nine hold → `ACCEPTED`. Any single failure blocks `ACCEPTED`; which
condition(s) failed is recorded in `qa_audit.consensus.failed_conditions`.

## 8. Non-consensus routing (spec section 9)

| Condition | Routing |
|---|---|
| `solver.solver_answer == "AMBIGUOUS"` | `MANUAL_REVIEW` |
| `solver.solver_answer == "NONE"` | `DISCARDED` |
| `solver.solver_answer` in A–D but ≠ `generator.correct_answer` | `MANUAL_REVIEW` |
| `solver.solver_answer` in A–D but ≠ `reviewer.independent_answer` | `MANUAL_REVIEW` |
| `solver.confidence == "LOW"` | `MANUAL_REVIEW` |
| `reviewer.source_similarity_risk == "HIGH"` | `MANUAL_REVIEW` |

The Orchestrator does not resolve any of these itself ("probably the
Generator is right" reasoning is explicitly out of bounds per spec
section 9). All routes end in a human decision (`MANUAL_REVIEW` →
`analysis/manual_review_queue.json`) or a fresh-generation decision
(`DISCARDED`).

## 9. Regression case: `gen-struct-003`

Reviewer: `REVISE` (distractor C rated `MARGINAL`). Solver (tested
standalone against all 6 smoke items): `AMBIGUOUS`. A correct pipeline
must **never** call the Solver on a REVISE item in the first place — so
`run_smoke_test.py` intentionally does not feed `gen-struct-003`'s
existing Solver fixture record into the Orchestrator, and asserts the
candidate:

- never enters `SOLVING`
- final state is `REVISE_REQUIRED` (revision_count=1 of 2), never `ACCEPTED`

This is a permanent regression fixture — see `run_smoke_test.py` and
`run_acceptance_tests.py` (`#2`, `#9`).

## 10. Provenance (spec section 11)

`orchestrator.build_provenance_record()` produces, per candidate:

```json
{
  "item_id": "...", "concept_id": "...", "section": "...",
  "state": "ACCEPTED",
  "state_history": ["GENERATED","REVIEWING","SOLVING","ACCEPTED"],
  "generation_attempt": 1, "revision_count": 0,
  "generator": {"answer": "C"},
  "reviewer": {"verdict": "PASS", "independent_answer": "C", "difficulty": "MEDIUM"},
  "solver": {"answer": "C", "confidence": "HIGH"},
  "consensus": true,
  "batch_slot": {"...": "..."},
  "planned_slot": {"...": "..."},
  "final_slot": {"...": "..."},
  "versions": {"spec_version": "...", "taxonomy_version": "...", "generator_version": "...", ...},
  "accepted_item": { "...": "public-facing fields only, see section 11 below" },
  "qa_audit": { "...": "full internal detail, see section 11 below" }
}
```

Schemas: `orchestrator/schemas/provenance.schema.json`,
`accepted_item.schema.json`, `qa_audit.schema.json`. Shape-checked by
`orchestrator/scripts/validate_provenance.py` (same pattern as the other
agents' `validate_output.py`).

Written Expression v2.1 grammar evidence is supplied out of band through
`agents/toefl_itp_we_generator_v2/schema/grammar_evidence.schema.json`.
Each record stores `content_hash` and audit provenance (`evidence_producer`,
producer version, `invocation_id`, `created_at`, method, and model identifier).
The content hash and complete invariant booleans participate in the binding
check; provenance fields make the record attributable and replayable but are
not cryptographic authentication. This repository does not hold signing keys
or HMAC secrets, so missing or malformed provenance/evidence fails closed.

## 10.1 Run-level finalization

Pilot and Validation preserve the historical four JSON output filenames and
their `items` arrays, adding a `finalize_id` metadata field. They first publish
the files from a private staging directory with an `IN_PROGRESS` manifest,
then update the manual-review queue when applicable, and finally atomically
publish `pilot_finalize_manifest.json` or `validation_finalize_manifest.json`
with status `COMPLETE`. Consumers should accept a bundle only after checking
that marker and its recorded file hashes. Re-running the same state is safe;
the manual-review queue is de-duplicated by `item_id`.

## 11. Accepted item vs. QA audit separation (spec section 12)

- `orchestrator.build_accepted_item()` — only set when `state == ACCEPTED`.
  Contains `stem`/`sentence`, `options`/`marked_parts`, `correct_answer`,
  `explanation` (Generator's `answer_explanation` +
  `distractor_rationales`/`minimal_correction`), `taxonomy` metadata, and
  `difficulty`. **`difficulty` here is `reviewer_difficulty`** (the
  Reviewer's independently re-assessed value), not the Generator's
  self-declared one — spec section 8 explicitly says the Generator's own
  claim is not trusted as final, so the QA-vetted value is what ships.
  No Reviewer verdict, Solver answer, confidence, or issue text ever
  appears here.
- `orchestrator.build_qa_audit()` — always set. Contains the full Reviewer
  output, full Solver output, leakage-check result, consensus detail,
  failure detail, `state_history`, timestamps, and agent/spec versions.
  This is what a future internal QA dashboard would read; it is never
  shipped to end users.

These two are built by two independent functions from two disjoint field
sets — there is no shared mutable dict that could accidentally leak a
Reviewer/Solver field into `accepted_item`.

## 12. Version tracking (spec section 13)

- `spec_version` / `taxonomy_version` — read directly from
  `specs/toefl_itp_grammar_spec.json` (`"spec_version": "1.0.0"`,
  `"taxonomy_version": "1.1"` at time of writing).
- `generator_version` / `reviewer_version` / `solver_version` — a
  `sha256:`-prefixed 12-hex-char content hash of the corresponding
  `.claude/agents/toefl-itp-grammar-*.md` prompt file
  (`orchestrator.compute_agent_version()`). This changes automatically the
  moment an agent's prompt is edited, with no manual version bump to
  remember or forget.

## 13. Batch integrity (spec section 14)

`orchestrator.BatchIntegrityTracker` records planned vs. actually-`ACCEPTED`
distribution across a batch run, by `primary_target`, `difficulty`,
`correct_answer_position`, `vocabulary_domain`, and (Written Expression)
`tested_error_type` — written to `batch_summary` in each replay script's
output file. It is purely descriptive; it never blocks an
`ACCEPT`/`DISCARD` decision (quality takes priority over distribution, per
spec section 14's closing line).

The `planned` side means the original slot assigned at the first Generator
attempt. It is captured on `Candidate` before any revision, so a revision that
changes target, difficulty, or answer position cannot rewrite the batch's
planned distribution. The current item remains the source for `actual_accepted`
and for `batch_slot`, which is retained as a backward-compatible alias for
`planned_slot`. `final_slot` is derived from the final Generator item after
revisions and is the latest slot to carry forward to a fresh Generator call.

`orchestrator.derive_slot_requirements(generator_item)` produces the slot a
fresh Generator call should target when a candidate is `DISCARDED` or
`REJECTED` — e.g. `{"primary_target": "RELATIVE_CLAUSES", "difficulty":
"HARD", "correct_answer_position": "B", "vocabulary_domain": "..."}` — and
is attached as `final_slot` on every provenance record; `batch_slot` and
`planned_slot` preserve the original allocation.

## 14. Human review queue (spec section 15)

`orchestrator.append_manual_review_queue()` appends
(de-duplicated by `item_id`) to `analysis/manual_review_queue.json`:

```json
{
  "item_id": "...", "section": "...", "item": { "...": "the full candidate, for a human to read" },
  "disagreement_reasons": ["solver_generator_mismatch", "..."],
  "generator_answer": "C", "reviewer_answer": "C", "solver_answer": "D",
  "solver_confidence": "HIGH",
  "issues": [ "...Reviewer issues..." ],
  "state_history": ["GENERATED","REVIEWING","SOLVING","MANUAL_REVIEW"],
  "possible_actions": ["ACCEPT", "REGENERATE", "DISCARD"]
}
```

No UI is built (out of scope this round, per instructions); a human
chooses one of the three `possible_actions` out of band.

## 15. Failure handling (spec section 16)

`orchestrator.SystemCallError` is raised for **system** failures: an agent
script can't be invoked at all, or its output isn't valid JSON
(`orchestrator.parse_agent_json()`). These map to state
`GENERATION_FAILED` and are retried up to `max_system_failure_retries`
without touching `revision_count` — a transient failure is never treated
as evidence of poor item quality.

A **content**-shape failure — output parses as JSON but fails the
relevant `validate_output.py` schema check — maps to `VALIDATION_FAILED`
and is retried up to `max_generation_validation_retries`, again without
touching `revision_count` (this is a structural mistake, not the
Reviewer's quality judgement).

Only an actual Reviewer `REVISE`/`REJECT` verdict touches
`revision_count` / ends the candidate on quality grounds.

See `run_acceptance_tests.py` `#14` for a direct test of this
distinction (missing validator script / unparsable JSON → `SystemCallError`;
a syntactically valid but incomplete item → ordinary schema-validation
failure, no exception).

## 16. Testing (spec sections 17–21)

| Script | Purpose | Output |
|---|---|---|
| `orchestrator/scripts/run_smoke_test.py` | Replays the 6 existing Generator/Reviewer/Solver smoke fixtures. | `analysis/orchestrator_smoke_test.json` |
| `orchestrator/scripts/run_adversarial_test.py` | Replays the 5 deliberately-broken Reviewer adversarial fixtures. | `analysis/orchestrator_adversarial_test.json` |
| `orchestrator/scripts/run_reject_path_test.py` | Replays the 2 existing Reviewer REJECT fixtures. | `analysis/orchestrator_reject_path_test.json` |
| `orchestrator/scripts/run_acceptance_tests.py` | Runs the three scripts above plus direct unit tests of `evaluate_consensus`, retry limits, leakage guard, and failure classification; prints a pass/fail table against the 14 acceptance criteria (spec section 21). | console + populates `analysis/manual_review_queue.json` |
| `orchestrator/scripts/validate_provenance.py` | Shape-checks the Orchestrator's own output (same pattern as the other agents' `validate_output.py`). | console |

Run order: `run_smoke_test.py`, `run_adversarial_test.py`,
`run_reject_path_test.py`, then `run_acceptance_tests.py` (which also
re-runs the first three as subprocesses so it always reflects current
code).

## 17. Current live-run storage

The live pilot and validation drivers persist state and derived outputs under
`runs/pilot/` and `runs/validation/`. Historical replay outputs listed above
remain under `analysis/` and are not live runtime inputs. New runs include an
immutable version manifest in the state document and are complete only after
their atomic completion manifest is published.
