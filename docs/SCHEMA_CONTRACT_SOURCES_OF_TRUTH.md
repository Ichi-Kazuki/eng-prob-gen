# Schema, validator, specification: three different sources of truth

Three artefacts in this repo look like "the rules". They are not
interchangeable, and conflating them is how the runtime schema gap (High #1)
happened in the first place.

| Artefact | Question it answers | Location |
| --- | --- | --- |
| **JSON Schema** | Is this output the right *shape*? | `agents/*/schema/*.schema.json` |
| **`validate_output.py`** | Does this output satisfy the shape **and** the domain rules? | `agents/*/scripts/validate_output.py` |
| **Specification** | What should the *content* be, and why? | `specs/`, `analysis/GRAMMAR_TAXONOMY.md`, agent definitions |

## 1. JSON Schema = structural output contract

Each agent's committed schema is the single source of truth for the structure
of that agent's output: which fields exist, which are required, their types
and enum ranges, and — via `additionalProperties: false` — that no other field
may appear.

The schema is loaded and enforced at runtime. It is not documentation of an
intended shape; it is the shape. Do **not** re-enumerate known field names in
Python as a substitute for the schema, and do not relax `required` or
`additionalProperties` to make a historical artifact pass. If a real artifact
conflicts with the schema, that is a finding to triage, not a schema to loosen.

## 2. `validate_output.py` = schema enforcement + semantic checks

### The public validation API

Every agent validator exposes exactly one supported entry point:

| Function | Meaning | Who may call it |
| --- | --- | --- |
| `validate_contract(...)` | **schema validation + semantic validation** | everyone: CLI, internal imports, tests, orchestrator |
| `validate_semantics(...)` | only the checks a schema cannot express | the validator itself; tests that introspect it |
| `validate(...)` / `validate_item(...)` | backwards-compatible **aliases of `validate_contract`** | existing callers |

`validate_contract` runs two stages, in this order:

1. **Structural** — load its own committed schema and run
   `shared.schema_validation.schema_errors()`. Structural errors
   short-circuit: the semantic stage never sees a malformed record, so
   semantic checks may assume the fields they read exist.
2. **Semantic / domain** — taxonomy membership, spec footnote exclusions,
   cross-field consistency, deterministic geometry, leakage allowlists.

### Why the CLI has no validation logic of its own

The original design ran the schema *inside `main()`*. That created two
different validation paths: the CLI got `schema + semantics`, while an
internal caller doing `validator.validate(record)` got semantics only and
silently skipped the structural gate. A Reviewer record carrying
`judgment_mode` — a property the committed Reviewer schema forbids — passed on
the import path and failed on the CLI path.

The `main()` of every validator is now a thin wrapper that calls
`validate_contract` per record and formats the result. There is no
CLI-only check, and therefore no second validation path to drift.

### The enforcement invariant

> Every public agent-output validation path must enforce the structural schema
> before semantic validation, and the CLI and import paths must agree on every
> fixture.

This is locked down by `tests/test_validation_public_api.py`, which also
asserts that the legacy aliases really are `validate_contract`, that no caller
in the repository reaches a validator's semantic stage directly, and that the
Reviewer schema still forbids the replay annotations.

### Replay annotations live outside the contract

Validation-harness annotations — `judgment_mode`, `grammar_quality_evaluable`
— describe *how a run produced* a record, not what an agent decided. They are
never members of a formal agent output contract. They are emitted in the
artifact-level `replay_metadata` sidecar (see
`analysis/we_v2_validation/run_validation.py::replay_annotations`) and in the
run's metrics/state. The correct fix for "my record fails the schema because
it carries an annotation" is to move the annotation out, never to widen the
schema.

### Runtime Draft 2020-12 implementation

`shared/schema_validation.py` delegates to the standard
`jsonschema.Draft202012Validator`. The committed schemas are meta-validated
before use, and applicable Draft 2020-12 keywords—including `allOf`,
`if`/`then`/`else`, and `$ref`—are enforced directly by the schema engine.
The dependency and its transitive runtime set are pinned in
`requirements.lock`.

Python semantic checks remain only for relationships that the current schemas
do not express conveniently, such as equality between reported Reviewer
fields and the full PASS consistency rules. Structural errors short-circuit
before those checks. Do not duplicate `required`, enum, type, or
`additionalProperties` rules in Python, and do not add a manual keyword subset
in front of the standard validator.

## 3. Specification = content / design requirements

The specification governs what a good item *is*: grammar targets, difficulty
calibration, TOEFL-ITP-likeness, error taxonomy, format bands. None of that is
decidable by a schema, and `validate_output.py` deliberately does not judge it
— that is the Reviewer's independent audit.

A schema change is a structural contract change. A specification change is a
content/design change. They are reviewed separately and should not be bundled.

## Adding a new agent

1. Commit `agents/<agent>/schema/<output>.schema.json` with
   `"additionalProperties": false` and a complete `required` list.
2. In `validate_output.py`, `sys.path.insert(0, REPO_ROOT)` and import
   `load_schema` / `schema_errors` from `shared.schema_validation`.
3. Put the checks a schema cannot express in `validate_semantics(...)`, and
   expose `validate_contract(...)` = structural gate (short-circuiting) then
   `validate_semantics`. Alias any legacy name to `validate_contract`.
4. Make `main()` call `validate_contract` and nothing else, so the CLI and
   import paths cannot diverge.
5. If the schema relies on optional assertion behavior such as `format`, add
   the appropriate standard checker and a regression test before treating it
   as a safety gate.
