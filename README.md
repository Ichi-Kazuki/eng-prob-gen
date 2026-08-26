# TOEFL ITP Grammar Problem Generator

This repository implements a fail-closed pipeline for generating and quality-gating TOEFL ITP Structure and Written Expression items. It stores stage state and replayable artifacts as JSON; it does not silently repair an item or replace an agent's grammar/quality judgment.

## Architecture

`Generator → Reviewer → Solver → Orchestrator`

The Generator proposes an item, the Reviewer independently returns `PASS`, `REVISE`, or `REJECT`, and the blinded Solver independently selects an answer. The Orchestrator owns sequencing, schema boundaries, retry/state invariants, consensus, provenance, and human-review routing.

The Solver receives only the canonical allowlisted projection (`item_id`, section, and question content). The canonical payload is deep-copied, persisted in candidate state, and re-derived and compared again at the Solver boundary. Live Reviewer/Solver calls use a disposable workspace outside the repository containing only the named agent definition and output schema. `ACCEPTED` requires the full Generator/Reviewer/Solver consensus invariant; any disagreement fails closed.

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
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
```

CI also runs `pip check`, Ruff, a scoped mypy check, pip-audit, coverage measurement, and Python bytecode compilation on Ubuntu and Windows.

## External grammar evidence

Written Expression Generator v2.1 uses an external grammar-evidence sidecar for strong one-error invariants. Each record must include a content hash bound to the exact item plus audit provenance: producer/version, invocation ID, timestamp, method, and model identifier. Provenance makes evidence attributable and replay-auditable; it is not cryptographic authentication. This repository does not manage signing keys or HMAC secrets, so callers must provide a trusted orchestrator/runtime boundary if authenticity beyond content binding is required. Missing, malformed, stale, or incomplete evidence is rejected.

## Source and generated artifacts

`source/` contains the source PDFs used by the analysis fixtures. `analysis/` contains reviewed fixtures, reports, and historical generated/replay artifacts. New runtime output belongs under ignored `runs/` (or `artifacts/`), and disposable scratch files belong in ignored `tmp/`, `render/`, or `ocr/` locations. See [docs/repository-layout.md](docs/repository-layout.md) for the source, fixture, reference, runtime, and answer-key policy. Do not commit credentials, local locks, bytecode, or temporary output.

Before publishing this repository or redistributing anything under `source/`, confirm that the relevant copyright and redistribution rights permit publication. The code cannot determine those rights.
