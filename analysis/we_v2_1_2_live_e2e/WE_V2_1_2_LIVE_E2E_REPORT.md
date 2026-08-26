# WE v2.1.2 Live E2E Report

- Batch: `we-v2.1.2-live-e2e-20260826T062547Z`
- Scope: 10 fresh items, one item per microbatch
- Pipeline: Generator -> live Reviewer v2 -> live Grammar Solver -> existing Orchestrator
- Generator/Format/Mutation safety/Schema/Specification/Taxonomy source files: unchanged

## Final decision: E

The runtime could not provide the required complete live pipeline; see classified invocation failures.

## Gate results

| Gate | Result | Requirement | Status |
|---|---:|---:|---|
| `generator_schema` | `0` | `10` | FAIL |
| `reviewer_contract` | `0` | `10` | FAIL |
| `solver_contract` | `0` | `10` | FAIL |
| `reviewer_live_invocation` | `0` | `10` | FAIL |
| `solver_live_invocation` | `0` | `10` | FAIL |
| `answer_leakage` | `0` | `0` | PASS |
| `reviewer_genuine_error_failure` | `0` | `0` | PASS |
| `reviewer_multiple_error` | `0` | `0` | PASS |
| `solver_none` | `0` | `0` | PASS |
| `solver_ambiguous` | `0` | `1` | PASS |
| `generator_solver_agreement` | `0` | `9` | FAIL |
| `reviewer_solver_structural_conflict` | `0` | `1` | PASS |
| `orchestrator_acceptance_logic` | `[]` | `-` | PASS |

## Runtime and provenance

Reviewer and Solver were invoked through the Claude Code CLI with the checked-in custom Agents. Reviewer input was projected only to `item_id`, `section`, `sentence`, and `marked_parts`; Solver input used the existing canonical blinding projection. No Generator answer, mutation metadata, generation plan, explanation, Generator key, or Reviewer judgment was sent to either runtime.

Formal records contain only their existing contracts. Runtime provider, agent/model identifier, timestamps, live flag, validation flag, input hash, and raw-output log path are stored in the separate provenance sidecar.

The Reviewer adapter only maps explicit fields/enums from the live response into the frozen formal record and attaches comparison fields after the blind invocation; it does not synthesize a grammar judgment or use Generator answer metadata to decide the answer.

Final formal record counts: Generator `0`, Reviewer `0`, Solver `0`. Reviewer/Solver were not invoked in this final run because the upstream Generator live call was blocked by the runtime session limit; their zero gates are therefore not treated as validation success.

## Failure classification

| Stage | Category | Detail |
|---|---|---|
| `generator` | `infrastructure` | generator: CLI exit 1: api_error_status=429; terminal_reason=api_error; result=You've hit your session limit · resets 5:40pm (Asia/Tokyo) |

## Existing tests

Command: `C:\Users\soted\AppData\Local\Python\pythoncore-3.14-64\python.exe -m unittest discover -s tests -p test_*.py`
Result: PASS

## Artifacts

- Formal Generator output: `runtime/formal/generator_outputs.json`
- Formal Reviewer output: `runtime/formal/reviewer_outputs.json`
- Formal Solver output: `runtime/formal/solver_outputs.json`
- Runtime provenance sidecar: `runtime/provenance/runtime_provenance.json`
- Machine-readable report: `we_v2_1_2_live_e2e.json`
