# Repository layout and artifact policy

This repository contains the TOEFL ITP grammar-generation source, the checked-in
contracts used by the agents, historical analysis, and reproducible test data.
The layout deliberately separates code and static inputs from run output and
answer-bearing material.

## Responsibilities

| Path | Responsibility | Git policy |
| --- | --- | --- |
| `agents/` | Agent definitions, prompts, schemas, and validators | Source-controlled |
| `.claude/` | Claude agent entry points | Source-controlled; never copied wholesale to a Solver workspace |
| `orchestrator/` | State machine, live drivers, configs, schemas, and developer test runners | Source-controlled |
| `scripts/` | Reusable developer utilities and the live E2E harness | Source-controlled; runtime output goes to `runs/` |
| `shared/` | Shared persistence, validation, tokenization, and Solver blinding code | Source-controlled |
| `runtime/` | Provider-neutral Claude/Codex adapters | Source-controlled |
| `tests/` | Unit/integration/regression tests and intentionally small fixtures | Source-controlled |
| `specs/` | Pipeline specifications and policy snapshots | Source-controlled |
| `source/` | Original/reference PDFs used for analysis and calibration | Source-controlled reference material |
| `analysis/` | Historical reports, derived profiles, experiment results, and replay fixtures | Source-controlled only when needed for reproducibility/history |
| `runs/` | Live pilot/validation state and final bundles | Generated; gitignored |
| `artifacts/` | Optional generated artifact staging area | Generated; gitignored |
| `tmp/` | Disposable local scratch, OCR/intermediate images, and debug output | Disposable; gitignored |

The pre-cleanup inventory found 285 tracked files (about 25.66 MiB): production
source and shared code (A), agent definitions/prompts (B), schemas/configuration
(C), tests/fixtures (D), development runners (E), reference PDFs and source
material (F), historical generated/evaluation artifacts (G/H), documentation
(K), and no tracked files under `tmp/`. The remaining categories were represented
by state/provenance, reviewer, solver, calibration, or sealed-key artifacts in
historical `analysis/` trees (I/J); they were not mass-deleted because their
historical/replay value was not established file-by-file.

## Runs and persistence

The live drivers write to `runs/pilot/` and `runs/validation/`. A run contains a
state document with an immutable `run_manifest`, derived Solver batches, stage
sidecars, and a final bundle. The final bundle is complete only when its atomic
completion manifest says so. New output must not be written to the repository
root, `source/`, or a historical `analysis/` directory.

The run manifest snapshots the relevant config, prompt, schema, validator,
orchestrator, and shared-module hashes at `init`. Final provenance references
that snapshot; it does not re-hash the current checkout. Legacy state files that
predate manifests remain readable through the compatibility path and are treated
as unsnapshotted legacy runs.

## Solver isolation and answer-bearing data

Reviewer/Solver calls request a disposable temporary workspace outside the
repository. The runtime copies only the named agent definition and the output
schema needed for that invocation. Candidate state, generator/reviewer output,
provenance, accepted items, calibration data, and sealed keys are never staged
there, and the leakage guard remains an independent boundary check.

This is repository-level isolation: the adapter controls its working directory
and staged files, but cannot override permissions or filesystem visibility granted
by an external Claude/Codex host. Deployments should therefore provide a
process/container sandbox with access restricted to the temporary workspace.

Active evaluation keys, human gold labels, and answer-bearing outputs should be
kept outside the public checkout. Test-only answer keys may live under
`tests/fixtures/` with an explicit test name and must never be used as live
runtime input. Historical answer-bearing artifacts currently retained under
`analysis/` are archives/replay evidence, not Solver inputs.

The reusable OCR/crop utilities formerly found in `tmp/` now live in
`scripts/`; their input images and OCR outputs remain disposable local data.

## Reference material and copyright review

The PDFs under `source/` are development/reference inputs; production runtime
does not require reading them. Their contents were not changed by the cleanup.
Before redistributing this repository or adding third-party material, contributors
must verify the applicable license/permission and whether the material should be
kept private. This document does not make a copyright or redistribution
determination.

## Contributor policy

- Put reusable code in the relevant package or `scripts/`, not in `tmp/`.
- Put small deterministic test inputs in `tests/fixtures/`; do not promote live
  run output to fixtures without documenting why.
- Put new generated output under `runs/<run-id>/` or `artifacts/` and keep it out
  of Git.
- Keep historical analysis immutable unless a report or fixture itself is being
  corrected intentionally.
- Use `pathlib.Path` and repository-root/configured-root resolution rather than
  relying on the current working directory.
