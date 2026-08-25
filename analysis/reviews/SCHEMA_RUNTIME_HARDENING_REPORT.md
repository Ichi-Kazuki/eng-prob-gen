# Schema runtime hardening report

Scope: the two **High severity** findings from the implementation review. No
change to Generator architecture, the mutation integrity model, format tuning,
Specification content, or the taxonomy.

---

## 1. What was wrong

### High #1 — committed JSON Schemas were not connected to runtime validation

Six JSON Schema documents were committed under `agents/*/schema/`, but only the
WE v2 *emission* boundary (`emit_output.py`) ever loaded one. Every
`validate_output.py` hand-enumerated a handful of known fields in Python
instead. Consequences:

- A Generator item missing `subtype`, `secondary_features`,
  `vocabulary_domain`, or `answer_explanation` passed validation, because none
  of those fields were enumerated.
- Such an item then reached `orchestrator.build_accepted_item()`, which indexes
  `g["subtype"]` and `g["answer_explanation"]` directly — an uncaught
  `KeyError` in the accept path.
- `additionalProperties: false` was declared in every schema and enforced
  nowhere, so unknown keys were silently accepted.

### High #2 — Solver leakage validation was a denylist

`validate_output.py` for the Solver checked a fixed set of 14 known
Generator/Reviewer field names. Any leaked field under a name not on that list
— `correct_answer_leak_via_new_name`, `internal_chain_of_thought`,
`debug_generator_target` — passed the security gate untouched.

---

## 2. What changed

### Shared schema validator

`schema_errors()` was extracted out of
`agents/toefl_itp_we_generator_v2/scripts/validate_format.py` into:

```
shared/schema_validation.py
```

`validate_format.py` now imports and re-exports it, so all existing callers
(`emit_output.py`, `run_validation.py`, `run_integrity_reaudit.py`, the WE v2
contract-boundary tests) keep working unchanged. Behaviour is identical: the
function body was moved verbatim.

**Enforced keywords:** `type`, `enum`, `const`, `required`, `properties`,
`additionalProperties` (`false` and subschema forms), `minLength`, `minimum`,
`maximum`, `minItems`, `items`, `propertyNames`.

**Not enforced:** `allOf`, `anyOf`, `oneOf`, `not`, `if`, `then`, `else`,
`maxLength`, `maxItems`, `uniqueItems`, `pattern`, `format`, `$ref`,
`dependentRequired`, `dependentSchemas`.

### Conditionals are deliberately not implemented

`solver_output.schema.json` and `reviewer_output.schema.json` use
`allOf`/`if`/`then`. Rather than build a general conditional engine, those
conditions stay in the existing Python semantic checks. The contract is
explicitly two-stage:

> basic structural schema **+** existing Python semantic condition checks

| Conditional | Enforced by |
| --- | --- |
| WE ⇒ `suggested_correction` required | Solver semantic stage |
| answer ∈ {AMBIGUOUS, NONE} ⇒ `ambiguity_detected: true` | Solver semantic stage |
| answer ∈ {A,B,C,D} ⇒ `ambiguity_detected: false` | Solver semantic stage |
| WE ⇒ four WE-only reviewer fields required | Reviewer semantic stage |
| `critical_failure: true` ⇒ verdict ≠ PASS | Reviewer semantic stage |

### Every agent validator now runs the schema first

All five `validate_output.py` scripts follow the same order:

```
schema path → schema load → schema_errors() → structural failure ⇒ exit 1 → semantic checks
```

| Agent | Schema loaded |
| --- | --- |
| Grammar Generator | `structure_item.schema.json` / `written_expression_item.schema.json` (by `section`) |
| Grammar Reviewer | `reviewer_output.schema.json` |
| Grammar Solver | `solver_output.schema.json` |
| WE v2 Generator | `written_expression_item_v2.schema.json` |
| WE v2 Reviewer | `reviewer_output_v2.schema.json` |

No existing semantic check was deleted.

### Solver leakage: denylist → allowlist

```python
ALLOWED_TOP_KEYS = REQUIRED_TOP_KEYS | {"suggested_correction"}
```

`set(item) - ALLOWED_TOP_KEYS` non-empty ⇒ ERROR. The old denylist survives
only as `KNOWN_LEAKAGE_FIELD_NAMES`, used purely to make the error message more
explanatory when a rejected key happens to be a recognised Generator/Reviewer
field. It is no longer the gate.

Unknown keys are therefore rejected twice over: by `additionalProperties:
false` in stage 1, and by the allowlist in stage 2.

---

## 3. Regression fixtures

### Structure adversarial fixture

`tests/fixtures/adversarial_structure_item.json` — a valid Structure item with
`subtype`, `secondary_features`, `vocabulary_domain`, and `answer_explanation`
removed and `totally_unexpected_field` added.

```
$ python agents/toefl_itp_grammar_generator/scripts/validate_output.py \
      tests/fixtures/adversarial_structure_item.json
5 structural schema error(s):
  - ...: <root>: missing required property 'subtype'
  - ...: <root>: missing required property 'secondary_features'
  - ...: <root>: missing required property 'vocabulary_domain'
  - ...: <root>: missing required property 'answer_explanation'
  - ...: <root>: additional property 'totally_unexpected_field' is not allowed
exit 1
```

### Solver leakage fixture

`tests/fixtures/adversarial_solver_output.json` — a contract-valid Solver item
plus three novel leak fields.

```
$ python agents/toefl_itp_grammar_solver/scripts/validate_output.py \
      tests/fixtures/adversarial_solver_output.json
3 structural schema error(s):
  - ...: additional property 'correct_answer_leak_via_new_name' is not allowed
  - ...: additional property 'debug_generator_target' is not allowed
  - ...: additional property 'internal_chain_of_thought' is not allowed
exit 1
```

All three are rejected as unknown properties.

---

## 4. Orchestrator crash-path

`tests/test_schema_runtime_gate.py::OrchestratorCrashPathTests` drives the real
`process_generation_output()` with the real `orchestrator/config.json`:

- item missing `answer_explanation` ⇒ `VALIDATION_FAILED`
- item missing `subtype` ⇒ `VALIDATION_FAILED`
- item missing both ⇒ never `ACCEPTED`, and `build_accepted_item()` returns
  `None` (it short-circuits on any non-`ACCEPTED` candidate), so the `KeyError`
  path is unreachable
- a fully valid item still advances past generation

The `KeyError` path is now blocked at the validator, one stage before
`build_accepted_item()` is ever called.

---

## 5. Historical artifact compatibility audit

Read-only audit: `analysis/reviews/run_schema_compatibility_audit.py`
Machine-readable result: `analysis/reviews/schema_runtime_compatibility.json`

**Artifacts: 22 PASS / 1 FAIL / 0 MISSING (of 23)**
**Items: 437 PASS / 3 FAIL (of 440)**

| Group | Artifacts | Items | PASS | FAIL |
| --- | ---: | ---: | ---: | ---: |
| pilot accepted items | 1 | 37 | 37 | 0 |
| validation artifacts | 6 | 90 | 90 | 0 |
| reviewer artifacts | 7 | 57 | 57 | 0 |
| solver artifacts | 3 | 51 | 51 | 0 |
| WE v2 smoke | 3 | 30 | 30 | 0 |
| WE v2 pilot | 1 | 25 | 22 | **3** |
| WE v2 validation | 2 | 150 | 150 | 0 |

### The three incompatible items

`analysis/we_v2_pilot/we_v2_pilot_final_items.json`:
`we-v2-pilot-013`, `we-v2-pilot-014`, `we-v2-pilot-015`.

Each has `format_metadata.diagnostics == {}` — all 18 required diagnostic keys
missing.

**Classification: (A) the historical artifact genuinely violates the contract.**

Not (B): the schema is not too strict. `written_expression_item_v2.schema.json`
has always required those 18 diagnostic keys, and the other 22 items in the
same file carry all of them.

Not (C): all three declare `agent_version = "Written Expression Generator
v2.0"`, `spec_version = 1.0.0`, `format_spec_version = 1.0.0` — the same
versions as the 22 passing items in the same batch.

Blast radius is nil: all three are already recorded in
`analysis/we_v2_pilot/we_v2_pilot_failures.json` with `final_state =
MANUAL_REVIEW` and `primary_failure_reason = "other"`. They were never
accepted, and they are not in any accepted-items artifact. The new gate simply
gives that pre-existing failure a precise diagnosis instead of "other".

**No schema was weakened to make them pass.** Per the review constraint, the
mismatch is reported rather than accommodated; whether to backfill diagnostics
for these three or leave them failed is a separate design decision, out of
scope for this change.

---

## 6. Test results

| Suite | Before | After |
| --- | --- | --- |
| `python -m unittest discover -s tests -p "test_*.py"` | 19 PASS | **36 PASS** (19 existing + 17 new) |
| `orchestrator/scripts/run_acceptance_tests.py` | 18/18 | **18/18** |
| `run_p0_hardening_regression.py` | PASS (7 contracts) | **PASS (7 contracts)** |
| `analysis/we_v2/run_regression_contract.py` | PASS (6 cases) | **PASS (6 cases)** |
| Solver blinding (acceptance #4) | PASS | **PASS** |

New tests (17) cover: the shared engine per enforced keyword, the
boolean-is-not-an-integer edge, the documented enforced/unenforced keyword
split, every committed schema loading with `additionalProperties: false`, every
validator referencing its schema, unknown-key rejection end-to-end, the
Structure adversarial fixture, the Solver leakage fixture and allowlist
semantics, legitimate `suggested_correction` still passing, and the four
orchestrator crash-path cases.

## 7. Side-effect safety

All test and regression runs used temporary output directories. No tracked
analysis artifact, manual review queue, or orchestrator test artifact was
rewritten; `git status --short` shows only the intended source changes plus
this report and its JSON. (The repo tracks `__pycache__/*.pyc` files, which any
Python run touches; those are restored, not committed as part of this change.)

## 8. Out of scope

Not addressed here, per the review constraints: package restructuring, the
`analysis/` directory relocation, the `run_validation.py` refactor, the README
overhaul, `output_dir` roll-out, repair-anchor architecture, format-band
tuning, and `.gitignore` (a separate commit). The later Schema Runtime
Hardening follow-up removed the two remaining private `schema_errors()`
implementations under `analysis/we_v2_pilot/`; repository-wide search now
finds only `shared/schema_validation.py`, so that duplication finding is
closed. No P1/High finding remains open in this hardening scope.
