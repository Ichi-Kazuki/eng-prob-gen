# TOEFL ITP Grammar Problem Generator

This repository implements a fail-closed pipeline for generating and quality-gating TOEFL ITP Structure and Written Expression items. It stores stage state and replayable artifacts as JSON; it does not silently repair items or replace an agent's grammar/quality judgment. Reading v0.2.11's bounded inference repair is explicit and audited.

## Reading Comprehension v0.2.11 (historical v0.1 compatibility)

Reading is a separate contract family. v0.2.11 is the current/default CLI
route: each independent passage plan samples a
realistic variable question count and ordered type mix from the lightweight
derived profile in `analysis/reading_v0_2_empirical_profile.json`. Repeated
question types are allowed, and Generator, Reviewer, and Solver each process
the complete question set in one invocation. Passage-length and question-count
sampling remain independent Planner draws.

Run one fresh current v0.2.11 passage set with Claude Code (the default provider):

```powershell
python -m reading.cli --seed 1001
```

The historical v0.1 one-set route is available only through an explicit
compatibility choice:

```powershell
python -m reading.cli --version v0.1 --seed 1001
```

Use the existing Codex adapter with its read-only/medium-reasoning settings:

```powershell
python -m reading.cli --provider codex --seed 1001
```

Generate an independent v0.2 batch with conservative bounded parallelism:

```powershell
python -m reading.cli --provider codex --seed 1001 --count 4 --parallel 2
```

Use Generator-only development drafts when needed:

```powershell
python -m reading.cli --provider codex --seed 1001 --count 5 --mode draft
```

Validated v0.2 artifacts are written under
`runs/reading_v0_2/<batch-id>/passage-001/` (and so on), with isolated plan,
Generator, blind inputs, Reviewer, Solver, result, runtime, and provenance
artifacts plus the batch-level `batch_result.json`. A draft is always marked
`UNVALIDATED_DRAFT` and `production_eligible: false`; it cannot be accepted.
Quality rejection is `QUARANTINE`, infrastructure failure is
`INFRASTRUCTURE_FAILURE`. Whole-passage and whole-set replacement remains
prohibited; v0.2.11 preserves one Repair invocation producing two candidates per
flagged inference, deterministic candidate validation, one blind candidate
verification, deterministic selection, then the existing Final Reviewer and
Solver. Candidate Verifier semantics are kept at parity with the Initial
Inference Verifier: a direct restatement cannot become valid merely by citing
additional related passage propositions. Offline tests are run with:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Architecture

`Generator → Initial Inference Verifier → Initial Reviewer → one Repair (two candidates) → deterministic candidate validation → one blind Candidate Verifier → deterministic selection → Final Reviewer → Solver`

The Generator proposes the set. When inference items are present, the blind
Initial Inference Verifier and Initial Reviewer may flag them for one Repair
invocation. Repair returns two candidates per flagged inference; deterministic
validation, one blind Candidate Verifier, and deterministic selection precede
the existing Final Reviewer and Solver. The Orchestrator owns sequencing,
schema boundaries,
repair/state invariants, consensus, provenance, and human-review routing.

The Verifier, Reviewer, and Solver receive only canonical allowlisted visible
projections (`item_id`, section, and question content). The canonical payload
is deep-copied, persisted in candidate state, and re-derived at each blind
boundary. Live blind calls use a disposable workspace outside the repository
containing only the named agent definition and output schema. `ACCEPTED`
requires the full Generator/Verifier/Reviewer/Solver invariant; any
disagreement fails closed.

The production Orchestrator and the Written Expression v2 live E2E are
separate contract families. Production finalization consumes the legacy
Generator/Reviewer records and publishes `answer_explanation` plus the
Reviewer's `reviewer_difficulty`. WE v2 uses its own `error_explanation` and
v2 Reviewer schema, and its live `ACCEPTED` metric is compatibility-harness
evidence only; the harness does not call `build_accepted_item()` or publish a
production accepted item. Passing a WE v2 record to the production finalizer
is rejected explicitly.

## Pilot and validation workflows

The pilot driver operates under `runs/pilot`:

```text
init → apply_review → apply_revision (when needed) → prepare_solver_batch → apply_solver → finalize
```

The validation driver uses the same state machine under `runs/validation` and accepts three initial batch files. Both drivers persist an immutable run manifest with the candidate state, commit candidate state before publishing a derived Solver batch, and use the manifest snapshot for final provenance and accepted-state validation. Solver batch artifacts carry a state fingerprint and are refused when missing, stale, or tampered. Final output files are published through a staging directory and a completion manifest; an `IN_PROGRESS` manifest is never a complete run.

If an artifact write fails, rerun the same command. `rebuild_feedback` reconstructs Reviewer feedback from persisted history, and `prepare_solver_batch` reconstructs Solver input from persisted state.

## Installation and tests

Use Python 3.11 or later:

```bash
python -m pip install -r requirements.txt -c requirements.lock
python -m unittest discover -s tests -p "test_*.py" -v
```

`requirements.lock` pins the runtime dependency closure used for replay
diagnostics. The immutable run manifest records the Python/platform snapshot
and SHA-256 digests of both dependency files; environment differences are
reported separately from the executable pipeline fingerprint. CI installs
that same locked closure into an isolated audit environment and runs
`python -m pip_audit --path <locked-runtime-site-packages>`, so the
audit target is the installed runtime environment rather than a fresh
resolution of `requirements.txt` or the CI tooling environment.

CI also runs `pip check`, Ruff, a scoped mypy check, pip-audit, coverage measurement, and Python bytecode compilation on Ubuntu and Windows.

The live E2E harness accepts an absolute `WE_E2E_OUTPUT_DIR`. Protected source
identity remains repository-relative, while freeze snapshots and generated
evidence retain their external absolute path identity. Completed live runs
also publish `runtime/artifact_manifest_v1.json`, a deterministic SHA-256
sidecar for the formal outputs, provenance, outcomes, test result, and freeze
manifest used by report-only mode.

The final quality pilot must be prepared with
`scripts/prepare_final_pilot_worktree.py --commit <exact-commit> --worktree
<external-path>`. Run the live harness from that detached worktree with
`WE_E2E_FINAL_PILOT=1`, `WE_E2E_EXPECTED_COMMIT=<exact-commit>`, and an
absolute `WE_E2E_OUTPUT_DIR` outside the worktree. The development checkout
is never a pilot source tree. Protected freeze drift stops the cohort as
`PROTECTED_FREEZE_DRIFT`; allowlisted caches and outputs are reported as
`NONPROTECTED_WORKSPACE_DIRTY` and are not cohort-invalidating by themselves.

The image crop/underline utilities are analysis-only tools. Install their
optional dependency when using them:

```bash
python -m pip install ".[analysis]"
```

## External grammar evidence

Written Expression Generator v2.1 uses an external grammar-evidence sidecar for strong one-error invariants. Each record must include a content hash bound to the exact item plus audit provenance: producer/version, invocation ID, timestamp, method, and model identifier. Provenance makes evidence attributable and replay-auditable; it is not cryptographic authentication. This repository does not manage signing keys or HMAC secrets, so callers must provide a trusted orchestrator/runtime boundary if authenticity beyond content binding is required. Missing, malformed, stale, or incomplete evidence is rejected.

## Source and generated artifacts

`source/` contains the source PDFs used by the analysis fixtures. `analysis/` contains reviewed fixtures, reports, and historical generated/replay artifacts. New runtime output belongs under ignored `runs/` (or `artifacts/`), and disposable scratch files belong in ignored `tmp/`, `render/`, or `ocr/` locations. See [docs/repository-layout.md](docs/repository-layout.md) for the source, fixture, reference, runtime, and answer-key policy. Do not commit credentials, local locks, bytecode, or temporary output.

Before publishing this repository or redistributing anything under `source/`, confirm that the relevant copyright and redistribution rights permit publication. The code cannot determine those rights.
