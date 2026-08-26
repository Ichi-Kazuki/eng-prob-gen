# WE v2.1.2 Live E2E Report

- Batch: `we-v2.1.2-live-e2e-20260826T091038Z`
- Scope: 10 requested fresh items, one item per microbatch; recorded outcomes: 10
- Pipeline: Generator -> live Reviewer v2 -> live Grammar Solver -> existing Orchestrator
- The 75-item Validation was not re-run.
- Generator/Format/Mutation safety/Schema/Specification/Taxonomy source files: unchanged

## Final decision: B

Reviewer contract, blinded invocation, or independent grammar gates failed.

## Gate results

| Gate | Result | Requirement | Status |
|---|---:|---:|---|
| `generator_schema` | `10` | `10` | PASS |
| `reviewer_contract` | `10` | `10` | PASS |
| `solver_contract` | `9` | `10` | FAIL |
| `reviewer_live_invocation` | `10` | `10` | PASS |
| `solver_live_invocation` | `9` | `10` | FAIL |
| `answer_leakage` | `0` | `0` | PASS |
| `reviewer_genuine_error_failure` | `1` | `0` | FAIL |
| `reviewer_multiple_error` | `1` | `0` | FAIL |
| `solver_none` | `0` | `0` | PASS |
| `solver_ambiguous` | `0` | `1` | PASS |
| `generator_solver_agreement` | `9` | `9` | PASS |
| `reviewer_solver_structural_conflict` | `0` | `1` | PASS |
| `orchestrator_acceptance_logic` | `[]` | `-` | PASS |

## Runtime and provenance

The configured live paths use the `codex` runtime with the checked-in agent instructions. Reviewer input is projected only to `item_id`, `section`, `sentence`, and `marked_parts`; Solver input uses the existing canonical blinding projection. No Generator answer, mutation metadata, generation plan, explanation, Generator key, or Reviewer judgment was sent to either runtime.

Formal records contain only their existing contracts. Runtime provider, agent/model identifier, exact Codex command, start/end timestamps, elapsed seconds, process exit code, timeout-vs-CLI source, formal-output existence, validation flag, input hash, and raw stdout/stderr paths are stored per invocation in the separate provenance sidecar.

The Reviewer adapter only maps explicit fields/enums from the live response into the frozen formal record and attaches comparison fields after the blind invocation; it does not synthesize a grammar judgment or use Generator answer metadata to decide the answer.

Final formal record counts: Generator `10`, Reviewer `10`, Solver `9`. Codex live invocation count: `29`.

## Requested final metrics

- Reviewer/Solver contract validity: `{"generator": {"valid": 10, "invalid": 0}, "reviewer": {"valid": 10, "invalid": 0}, "solver": {"valid": 9, "invalid": 0}}`
- Blinding: `{"reviewer_allowlist": ["item_id", "section", "sentence", "marked_parts"], "solver_allowlist": ["item_id", "section", "sentence", "marked_parts"], "reviewer_invocation_count": 10, "solver_invocation_count": 9, "forbidden_fields_present": 0, "ok": true}`
- Generator/Solver agreement: `{"passed": 9, "denominator": 9, "ok": false}`
- Reviewer findings: `10` record(s); no finding is available when Reviewer was not reached.
- Orchestrator decisions: `{"ACCEPTED": 9, "REJECTED": 1}`

## Failure classification

No live invocation failures were recorded.

## Existing tests

Command: `C:\Users\soted\AppData\Local\Python\pythoncore-3.14-64\python.exe -m unittest discover -s tests -p test_*.py`
Result: PASS

## Artifacts

- Formal Generator output: `runtime/formal/generator_outputs.json`
- Formal Reviewer output: `runtime/formal/reviewer_outputs.json`
- Formal Solver output: `runtime/formal/solver_outputs.json`
- Runtime provenance sidecar: `runtime/provenance/runtime_provenance.json`
- Machine-readable report: `we_v2_1_2_live_e2e.json`
