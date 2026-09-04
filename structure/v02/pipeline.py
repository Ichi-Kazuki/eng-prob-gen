"""Isolated Structure v0.2 Generator -> Reviewer -> Selection -> Solver pipeline.

Implements exactly the approved v0.2 orchestration:

  v0.2 Planner
  -> Generator (logical call 1)
  -> deterministic Generator contract
  -> blind seven-candidate Reviewer projection
  -> Reviewer (logical call 2)
  -> Reviewer exact-text contract/canonicalization
  -> deterministic private candidate selection
  -> whole-set selection gate
  -> pre-permutation four-option assembly
  -> frozen deterministic A-D permutation
  -> blind final-four Solver projection
  -> Solver (logical call 3)
  -> frozen Solver exact-text contract/canonicalization
  -> Solver-vs-final-key check
  -> whole-set ACCEPT / QUARANTINE.

No semantic retry, repair, revision, regeneration, or item replacement
happens anywhere in this module. A later stage is never invoked unless its
prerequisite deterministic input was already produced and validated.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from runtime.adapters import AgentRuntime, InvocationRequest, InvocationResult, RuntimeInvocationError
from shared.json_io import atomic_write_json
from shared.schema_validation import load_schema, schema_errors

from structure.contracts import SCHEMA_PATHS as V01_SCHEMA_PATHS
from structure.permutation import permute_generator_output
from structure.provenance import artifact_hashes, invocation_record, logical_invocation_counts
from structure.runtime import configured_runtime
from structure.v02 import blinding as v02_blinding
from structure.v02 import contracts as v02_contracts
from structure.v02 import selection as v02_selection
from structure.v02 import solver as v02_solver
from structure.v02.planner import build_plan


ROOT = Path(__file__).resolve().parents[2]
STRUCTURE_VERSION = "v0.2"

GENERATOR_AGENT = "structure-generator-v0.2"
REVIEWER_AGENT = "structure-reviewer-v0.2"
SOLVER_AGENT = "structure-solver-v0.2"

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
AGENT_PATHS = {
    GENERATOR_AGENT: _PROMPT_DIR / "generator.md",
    REVIEWER_AGENT: _PROMPT_DIR / "reviewer.md",
    SOLVER_AGENT: _PROMPT_DIR / "solver.md",
}

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_PATHS = {
    "generator": _SCHEMA_DIR / "generator_output.schema.json",
    "reviewer": _SCHEMA_DIR / "reviewer_output.schema.json",
    "solver": V01_SCHEMA_PATHS["solver"],
}
RESULT_SCHEMA_PATH = _SCHEMA_DIR / "result.schema.json"
PROVENANCE_SCHEMA_PATH = _SCHEMA_DIR / "provenance.schema.json"

GENERATOR_STAGE = "structure_v02_generator"
REVIEWER_STAGE = "structure_v02_reviewer"
SOLVER_STAGE = "structure_v02_solver"

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("STRUCTURE_TIMEOUT_SECONDS", "300"))
DEFAULT_MAX_BUDGET_USD = os.environ.get("STRUCTURE_MAX_BUDGET_USD", "0.60")

GENERATOR_INSTRUCTION = (
    "Generate the complete Structure v0.2 candidate pool exactly from this "
    "Planner-owned plan. Return JSON only. Do not self-review or self-PASS."
)
REVIEWER_INSTRUCTION = (
    "Review all 15 Structure candidate pools independently and blindly using "
    "only the visible input. Return JSON only."
)
SOLVER_INSTRUCTION = (
    "Solve all 15 final Structure items independently and blindly using only "
    "the visible input. Return JSON only."
)

LETTERS = ("A", "B", "C", "D")
ACCEPTED_CONFIDENCES = frozenset({"HIGH", "MEDIUM"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_runtime_value(value: Any) -> str:
    return str(value) if value is not None else "unknown"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


class StructureV02Pipeline:
    """Run one complete Structure v0.2 set with no semantic retry or repair."""

    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_budget_usd: str | None = DEFAULT_MAX_BUDGET_USD,
    ) -> None:
        self.runtime = runtime or configured_runtime(provider, model)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_budget_usd = max_budget_usd
        self.invocations: list[InvocationResult] = []
        self.runtime_failures: list[dict[str, Any]] = []

    def _invoke(
        self,
        *,
        stage: str,
        agent: str,
        instruction: str,
        payload: Mapping[str, Any],
        output_schema: str,
        output_dir: Path,
    ) -> InvocationResult:
        request = InvocationRequest(
            stage=stage,
            agent_name=agent,
            agent_definition=AGENT_PATHS[agent],
            prompt=instruction + "\n\nINPUT_JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2),
            input_keys=("items",),
            formal_output_schema=SCHEMA_PATHS[output_schema],
            model=self.model,
            cwd=ROOT,
            sandbox="read-only" if getattr(self.runtime, "provider", "") == "codex" else None,
            tools="",
            max_budget_usd=self.max_budget_usd if getattr(self.runtime, "provider", "") == "claude-code-cli" else None,
            timeout_seconds=self.timeout_seconds,
            artifact_dir=output_dir / "runtime" / "logs",
            isolate_workspace=True,
        )
        try:
            result = self.runtime.invoke(request)
        except RuntimeInvocationError as exc:
            self.invocations.append(exc.result)
            self.runtime_failures.append({"stage": stage, "category": exc.category, "detail": exc.detail})
            raise
        self.invocations.append(result)
        return result

    def run(self, seed: int | None = None, *, output_dir: Path | None = None) -> dict[str, Any]:
        self.invocations = []
        self.runtime_failures = []
        actual_seed = secrets.randbits(32) if seed is None else seed
        plan = build_plan(actual_seed)
        run_id = f"structure-v02-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        run_dir = (output_dir or ROOT / "runs" / "structure_v0_2" / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "plan.json", plan)

        # Eleven pipeline artifact variables (Commit 6 semantics).
        generator_raw: Any = None
        generator_candidates: dict[str, Any] | None = None
        reviewer_input: dict[str, Any] | None = None
        reviewer_raw: Any = None
        candidate_selection: dict[str, Any] | None = None
        generator_final: dict[str, Any] | None = None
        permutation: dict[str, Any] | None = None
        generator: dict[str, Any] | None = None
        solver_input: dict[str, Any] | None = None
        solver_raw: Any = None

        # In-memory-only canonical forms (never persisted as separate artifacts).
        canonical_reviewer: dict[str, Any] | None = None
        canonical_solver: dict[str, Any] | None = None

        generator_errors: list[str] = []
        reviewer_input_errors: list[str] = []
        reviewer_contract_errors: list[str] = []
        candidate_selection_integrity_errors: list[str] = []
        final_assembly_errors: list[str] = []
        permutation_errors: list[str] = []
        solver_input_errors: list[str] = []
        solver_contract_errors: list[str] = []

        generator_contract_ok = False
        reviewer_input_contract_ok = False
        reviewer_contract_ok = False
        reviewer_canonicalization_ok = False
        candidate_selection_integrity_ok = False
        candidate_selection_all_passed = False
        final_assembly_ok = False
        permutation_ok = False
        solver_input_contract_ok = False
        solver_contract_ok = False
        solver_canonicalization_ok = False

        proceed = True

        try:
            generator_result = self._invoke(
                stage=GENERATOR_STAGE,
                agent=GENERATOR_AGENT,
                instruction=GENERATOR_INSTRUCTION,
                payload=plan,
                output_schema="generator",
                output_dir=run_dir,
            )
            generator_raw = generator_result.parsed
            generator_errors = v02_contracts.validate_generator_contract(generator_raw, plan)
            generator_contract_ok = not generator_errors
            if generator_contract_ok:
                generator_candidates = copy.deepcopy(generator_raw)
            else:
                proceed = False

            if proceed:
                try:
                    reviewer_input = v02_blinding.build_reviewer_candidate_input(generator_candidates, actual_seed)
                except (TypeError, ValueError) as exc:
                    reviewer_input = None
                    reviewer_input_errors = [f"reviewer_input: construction failed: {exc}"]
                else:
                    reviewer_input_errors = v02_blinding.reviewer_candidate_input_errors(
                        generator_candidates, reviewer_input, actual_seed
                    )
                reviewer_input_contract_ok = not reviewer_input_errors
                if not reviewer_input_contract_ok:
                    proceed = False

            if proceed:
                assert reviewer_input is not None
                reviewer_result = self._invoke(
                    stage=REVIEWER_STAGE,
                    agent=REVIEWER_AGENT,
                    instruction=REVIEWER_INSTRUCTION,
                    payload=reviewer_input,
                    output_schema="reviewer",
                    output_dir=run_dir,
                )
                reviewer_raw = reviewer_result.parsed
                reviewer_contract_errors = v02_contracts.validate_reviewer_contract(reviewer_raw, reviewer_input)
                reviewer_contract_ok = not reviewer_contract_errors
                if not reviewer_contract_ok:
                    proceed = False
                else:
                    try:
                        canonical_reviewer = v02_contracts.canonicalize_reviewer_output(reviewer_raw, reviewer_input)
                        reviewer_canonicalization_ok = True
                    except ValueError as exc:
                        reviewer_contract_errors = [f"reviewer: canonicalization failed: {exc}"]
                        proceed = False

            if proceed:
                try:
                    candidate_selection = v02_selection.build_candidate_selection(
                        generator_candidates, canonical_reviewer, actual_seed
                    )
                    candidate_selection_integrity_errors = v02_selection.candidate_selection_errors(
                        generator_candidates, canonical_reviewer, candidate_selection, actual_seed
                    )
                except ValueError as exc:
                    candidate_selection = None
                    candidate_selection_integrity_errors = [f"candidate_selection: construction failed: {exc}"]
                candidate_selection_integrity_ok = not candidate_selection_integrity_errors
                if not candidate_selection_integrity_ok:
                    proceed = False
                else:
                    assert candidate_selection is not None
                    candidate_selection_all_passed = all(
                        item["passed"] for item in candidate_selection["items"]
                    )
                    if not candidate_selection_all_passed:
                        proceed = False

            if proceed:
                try:
                    generator_final = v02_selection.assemble_final_generator_output(
                        generator_candidates, candidate_selection
                    )
                    final_assembly_ok = True
                except ValueError as exc:
                    final_assembly_errors = [f"final_assembly: {exc}"]
                    proceed = False

            if proceed:
                try:
                    permuted, permutation_obj = permute_generator_output(generator_final, actual_seed)
                    replay_permuted, replay_permutation_obj = permute_generator_output(generator_final, actual_seed)
                except ValueError as exc:
                    permutation_errors = [f"permutation: {exc}"]
                    proceed = False
                else:
                    errors: list[str] = []
                    items = permuted.get("items")
                    if not isinstance(items, list) or len(items) != 15:
                        errors.append("permutation: expected exactly 15 items")
                    distribution = permutation_obj.get("final_answer_position_distribution")
                    if not isinstance(distribution, dict) or sum(distribution.values()) != 15:
                        errors.append("permutation: distribution does not sum to 15")
                    elif sorted(distribution.values()) != [3, 4, 4, 4]:
                        errors.append("permutation: distribution is not 3/4/4/4")
                    if permuted != replay_permuted or permutation_obj != replay_permutation_obj:
                        errors.append("permutation: replay is not exactly equal to the first call")
                    permutation_errors = errors
                    permutation_ok = not permutation_errors
                    if permutation_ok:
                        permutation = permutation_obj
                        generator = permuted
                    else:
                        proceed = False

            if proceed:
                try:
                    solver_input = v02_solver.build_solver_input(generator)
                except (TypeError, ValueError) as exc:
                    solver_input = None
                    solver_input_errors = [f"solver_input: construction failed: {exc}"]
                else:
                    solver_input_errors = v02_solver.solver_input_errors(generator, solver_input)
                solver_input_contract_ok = not solver_input_errors
                if not solver_input_contract_ok:
                    proceed = False

            if proceed:
                assert solver_input is not None
                solver_result = self._invoke(
                    stage=SOLVER_STAGE,
                    agent=SOLVER_AGENT,
                    instruction=SOLVER_INSTRUCTION,
                    payload=solver_input,
                    output_schema="solver",
                    output_dir=run_dir,
                )
                solver_raw = solver_result.parsed
                solver_contract_errors = v02_solver.validate_solver_contract(solver_raw, solver_input)
                solver_contract_ok = not solver_contract_errors
                if not solver_contract_ok:
                    proceed = False
                else:
                    try:
                        canonical_solver = v02_solver.canonicalize_solver_output(solver_raw, solver_input)
                        solver_canonicalization_ok = True
                    except ValueError as exc:
                        solver_contract_errors = [f"solver: canonicalization failed: {exc}"]
                        proceed = False
        except RuntimeInvocationError:
            # Runtime failures are persisted and quarantine the whole set. No
            # semantic retry, repair, revision, or item replacement is made.
            pass

        runtime_failure_detail = self.runtime_failures[-1] if self.runtime_failures else None

        if isinstance(candidate_selection, dict) and isinstance(candidate_selection.get("items"), list):
            selection_items = candidate_selection["items"]
            candidate_selection_pass_count = sum(1 for item in selection_items if item.get("passed") is True)
            candidate_selection_failure_count = sum(1 for item in selection_items if item.get("passed") is False)
            selection_by_id = {item["item_id"]: item for item in selection_items}
        else:
            candidate_selection_pass_count = 0
            candidate_selection_failure_count = 0
            selection_by_id = {}

        # Determine the single stable global stop reason, if any.
        global_reason: str | None
        if runtime_failure_detail is not None:
            global_reason = f"runtime_failure:{runtime_failure_detail['stage']}:{runtime_failure_detail['category']}"
        elif not generator_contract_ok:
            global_reason = "generator_contract_failed"
        elif not reviewer_input_contract_ok:
            global_reason = "reviewer_input_contract_failed"
        elif not reviewer_contract_ok:
            global_reason = "reviewer_contract_failed"
        elif not reviewer_canonicalization_ok:
            global_reason = "reviewer_canonicalization_failed"
        elif not candidate_selection_integrity_ok:
            global_reason = "candidate_selection_integrity_failed"
        elif not candidate_selection_all_passed:
            global_reason = None  # per-item candidate-selection reasons apply instead
        elif not final_assembly_ok:
            global_reason = "final_assembly_failed"
        elif not permutation_ok:
            global_reason = "permutation_failed"
        elif not solver_input_contract_ok:
            global_reason = "solver_input_contract_failed"
        elif not solver_contract_ok:
            global_reason = "solver_contract_failed"
        elif not solver_canonicalization_ok:
            global_reason = "solver_canonicalization_failed"
        else:
            global_reason = None  # canonical Solver reached; use the final solver-vs-key check

        selection_stop_active = (
            global_reason is None
            and candidate_selection_integrity_ok
            and not candidate_selection_all_passed
        )

        # Final Solver-vs-assembled-key check.
        solver_key_agreement_count = 0
        solver_ambiguous_none_count = 0
        solver_key_check_per_item: list[dict[str, Any]] = []
        solver_key_check_by_id: dict[str, dict[str, Any]] = {}
        if canonical_solver is not None and isinstance(generator, dict):
            key_by_id = {item["item_id"]: item["correct_answer"] for item in generator["items"]}
            for solver_item in canonical_solver["items"]:
                item_id = solver_item["item_id"]
                expected_answer = key_by_id.get(item_id)
                solver_answer = solver_item["answer"]
                confidence = solver_item["confidence"]
                rejection_reasons: list[str] = []
                if solver_answer not in LETTERS:
                    rejection_reasons.append(f"solver_answer_not_unique_letter:{solver_answer}")
                elif solver_answer != expected_answer:
                    rejection_reasons.append(f"solver_key_disagreement:solver={solver_answer},key={expected_answer}")
                confidence_accepted = confidence in ACCEPTED_CONFIDENCES
                if not confidence_accepted:
                    rejection_reasons.append(f"solver_confidence_not_accepted:{confidence}")
                agrees = solver_answer == expected_answer
                if agrees:
                    solver_key_agreement_count += 1
                if solver_answer in {"AMBIGUOUS", "NONE"}:
                    solver_ambiguous_none_count += 1
                entry = {
                    "item_id": item_id,
                    "expected_answer": expected_answer,
                    "solver_answer": solver_answer,
                    "confidence": confidence,
                    "agrees": agrees,
                    "confidence_accepted": confidence_accepted,
                    "rejection_reasons": rejection_reasons,
                }
                solver_key_check_per_item.append(entry)
                solver_key_check_by_id[item_id] = entry

        # Reviewer diagnostics (intended-correct only; diagnostic-only, never gating).
        generator_candidates_by_id = (
            {item["item_id"]: item for item in generator_candidates["items"]}
            if isinstance(generator_candidates, dict)
            else {}
        )
        canonical_reviewer_by_id = (
            {item["item_id"]: item for item in canonical_reviewer["items"]}
            if isinstance(canonical_reviewer, dict)
            else {}
        )
        reviewer_clause_count_per_item: list[dict[str, Any]] = []
        candidate_pool_difficulty_per_item: list[dict[str, Any]] = []
        for planned in plan["items"]:
            item_id = planned["item_id"]
            observed_clause_count = None
            observed_difficulty = None
            difficulty_confidence = None
            gen_item = generator_candidates_by_id.get(item_id)
            rev_item = canonical_reviewer_by_id.get(item_id)
            if gen_item is not None and rev_item is not None:
                correct_text = gen_item.get("correct_option", {}).get("text")
                diagnostic = rev_item.get("candidate_diagnostics", {}).get(correct_text)
                if isinstance(diagnostic, dict):
                    observed_clause_count = diagnostic.get("observed_clause_count")
                    observed_difficulty = diagnostic.get("candidate_pool_observed_difficulty")
                    difficulty_confidence = diagnostic.get("difficulty_confidence")
            reviewer_clause_count_per_item.append({"item_id": item_id, "observed_clause_count": observed_clause_count})
            candidate_pool_difficulty_per_item.append({
                "item_id": item_id,
                "candidate_pool_observed_difficulty": observed_difficulty,
                "difficulty_confidence": difficulty_confidence,
            })

        # Deterministic hard-failure count: structural/integrity boundaries only.
        deterministic_errors = _dedupe(
            generator_errors
            + reviewer_input_errors
            + candidate_selection_integrity_errors
            + final_assembly_errors
            + permutation_errors
            + solver_input_errors
        )

        # Item results: exactly 15, plan order, never accepted without the
        # final Solver safeguard having actually run.
        item_results: list[dict[str, Any]] = []
        for planned in plan["items"]:
            item_id = planned["item_id"]
            if global_reason is not None:
                item_results.append({"item_id": item_id, "accepted": False, "rejection_reasons": [global_reason]})
            elif selection_stop_active:
                selection_item = selection_by_id.get(item_id)
                reasons: list[str] = []
                if selection_item is not None:
                    reasons.extend(f"candidate_selection:{reason}" for reason in selection_item.get("failure_reasons", []))
                reasons.append("solver_not_run_due_to_candidate_selection_failure")
                item_results.append({"item_id": item_id, "accepted": False, "rejection_reasons": reasons})
            else:
                check = solver_key_check_by_id.get(item_id)
                reasons = list(check["rejection_reasons"]) if check is not None else ["solver_key_check_missing"]
                item_results.append({"item_id": item_id, "accepted": not reasons, "rejection_reasons": reasons})

        all_15_items_pass = len(item_results) == 15 and all(item["accepted"] for item in item_results)
        decision = "ACCEPT" if all_15_items_pass else "QUARANTINE"

        final_distribution = {"A": 0, "B": 0, "C": 0, "D": 0}
        if permutation_ok and isinstance(permutation, dict):
            final_distribution = dict(permutation["final_answer_position_distribution"])

        values = {
            "plan.json": plan,
            "generator_raw.json": generator_raw,
            "generator_candidates.json": generator_candidates,
            "reviewer_input.json": reviewer_input,
            "reviewer.json": reviewer_raw,
            "candidate_selection.json": candidate_selection,
            "generator_final.json": generator_final,
            "permutation.json": permutation,
            "generator.json": generator,
            "solver_input.json": solver_input,
            "solver.json": solver_raw,
        }
        hashes = artifact_hashes(values)
        for name, value in values.items():
            atomic_write_json(run_dir / name, value)

        provider = _safe_runtime_value(getattr(self.runtime, "provider", "unknown"))
        model = _safe_runtime_value(
            self.invocations[0].model if self.invocations else getattr(self.runtime, "model", "unknown")
        )

        candidate_selection_check = {
            "constructed": candidate_selection is not None,
            "integrity_passed": candidate_selection_integrity_ok,
            "errors": candidate_selection_integrity_errors,
            "pass_count": candidate_selection_pass_count,
            "failure_count": candidate_selection_failure_count,
            "all_passed": candidate_selection_all_passed,
            "per_item": [
                {
                    "item_id": item["item_id"],
                    "passed": item["passed"],
                    "failure_reasons": item["failure_reasons"],
                }
                for item in (candidate_selection["items"] if isinstance(candidate_selection, dict) else [])
            ],
        }
        reviewer_canonicalization_check = {
            "applied": reviewer_canonicalization_ok,
            "strategy": "exact_option_text_identity",
            "raw_artifact": "reviewer.json",
        }
        solver_canonicalization_check = {
            "applied": solver_canonicalization_ok,
            "strategy": "exact_option_text_identity",
            "raw_artifact": "solver.json",
        }
        solver_key_check = {
            "performed": canonical_solver is not None,
            "agreement_count": solver_key_agreement_count,
            "ambiguous_none_count": solver_ambiguous_none_count,
            "per_item": solver_key_check_per_item,
        }
        reviewer_clause_count_check = {
            "policy": "diagnostic_only",
            "source": "intended_correct_candidate_diagnostic",
            "available_count": sum(
                1 for entry in reviewer_clause_count_per_item if entry["observed_clause_count"] is not None
            ),
            "per_item": reviewer_clause_count_per_item,
        }
        candidate_pool_difficulty_check = {
            "policy": "diagnostic_only",
            "source": "intended_correct_candidate_diagnostic",
            "planner_comparison": "disabled",
            "available_count": sum(
                1 for entry in candidate_pool_difficulty_per_item
                if entry["candidate_pool_observed_difficulty"] is not None
            ),
            "per_item": candidate_pool_difficulty_per_item,
        }

        result = {
            "schema_version": "structure-result-v0.2",
            "version": STRUCTURE_VERSION,
            "run_id": run_id,
            "seed": actual_seed,
            "decision": decision,
            "question_count": 15,
            "live_invocation_count": len(self.invocations),
            "deterministic_hard_failure_count": len(deterministic_errors),
            "candidate_selection_pass_count": candidate_selection_pass_count,
            "candidate_selection_failure_count": candidate_selection_failure_count,
            "solver_key_agreement_count": solver_key_agreement_count,
            "solver_ambiguous_none_count": solver_ambiguous_none_count,
            "final_answer_position_distribution": final_distribution,
            "item_results": item_results,
            "checks": {
                "generator_contract": generator_contract_ok,
                "generator_errors": generator_errors,
                "reviewer_input_contract": reviewer_input_contract_ok,
                "reviewer_input_errors": reviewer_input_errors,
                "reviewer_contract": reviewer_contract_ok,
                "reviewer_errors": reviewer_contract_errors,
                "reviewer_canonicalization": reviewer_canonicalization_check,
                "candidate_selection": candidate_selection_check,
                "final_assembly": {
                    "applied": final_assembly_ok,
                    "passed": final_assembly_ok,
                    "errors": final_assembly_errors,
                },
                "permutation": {
                    "applied": permutation_ok,
                    "passed": permutation_ok,
                    "errors": permutation_errors,
                    "final_answer_position_distribution": final_distribution,
                },
                "solver_input_contract": solver_input_contract_ok,
                "solver_input_errors": solver_input_errors,
                "solver_contract": solver_contract_ok,
                "solver_errors": solver_contract_errors,
                "solver_canonicalization": solver_canonicalization_check,
                "solver_key_check": solver_key_check,
                "reviewer_clause_count": reviewer_clause_count_check,
                "candidate_pool_difficulty": candidate_pool_difficulty_check,
                "all_15_items_pass": all_15_items_pass,
            },
            "infrastructure": {
                "runtime_failures": self.runtime_failures,
            },
            "artifact_hashes": hashes,
            "output_dir": str(run_dir),
        }
        result_errors = schema_errors(result, load_schema(RESULT_SCHEMA_PATH))
        if result_errors:
            raise ValueError("internal Structure v0.2 result failed schema validation: " + "; ".join(result_errors))
        atomic_write_json(run_dir / "result.json", result)

        provenance = {
            "schema_version": "structure-provenance-v0.2",
            "version": STRUCTURE_VERSION,
            "run_id": run_id,
            "seed": actual_seed,
            "provider": provider,
            "model": model,
            "invocations": [invocation_record(item) for item in self.invocations],
            "invocation_ids": [item.invocation_id for item in self.invocations],
            "invocation_count": len(self.invocations),
            "logical_invocation_counts": logical_invocation_counts(self.invocations),
            "deterministic_validation": {
                "generator": {"passed": generator_contract_ok, "errors": generator_errors},
                "reviewer_input": {"passed": reviewer_input_contract_ok, "errors": reviewer_input_errors},
                "reviewer_output_contract": {"passed": reviewer_contract_ok, "errors": reviewer_contract_errors},
                "candidate_selection_integrity": {
                    "passed": candidate_selection_integrity_ok,
                    "errors": candidate_selection_integrity_errors,
                },
                "final_assembly": {"passed": final_assembly_ok, "errors": final_assembly_errors},
                "permutation": {"passed": permutation_ok, "errors": permutation_errors},
                "solver_input": {"passed": solver_input_contract_ok, "errors": solver_input_errors},
                "solver_output_contract": {"passed": solver_contract_ok, "errors": solver_contract_errors},
            },
            "candidate_selection": {
                "artifact": "candidate_selection.json",
                "constructed": candidate_selection is not None,
                "integrity_passed": candidate_selection_integrity_ok,
                "pass_count": candidate_selection_pass_count,
                "failure_count": candidate_selection_failure_count,
                "all_passed": candidate_selection_all_passed,
            },
            "answer_position_permutation": permutation if permutation_ok else None,
            "blind_inputs": {
                "reviewer": {
                    "artifact": "reviewer_input.json",
                    "allowlist": list(v02_blinding.REVIEWER_INPUT_KEYS),
                    "constructed": reviewer_input is not None,
                    "contract_passed": reviewer_input_contract_ok,
                },
                "solver": {
                    "artifact": "solver_input.json",
                    "allowlist": ["item_id", "section", "stem", "options"],
                    "constructed": solver_input is not None,
                    "contract_passed": solver_input_contract_ok,
                },
            },
            "reviewer_canonicalization": reviewer_canonicalization_check,
            "solver_canonicalization": solver_canonicalization_check,
            "solver_key_check": solver_key_check,
            "leakage": {
                "reviewer_input_allowlist_only": reviewer_input is not None and reviewer_input_contract_ok,
                "solver_input_allowlist_only": solver_input is not None and solver_input_contract_ok,
            },
            "fallback": {"used": False, "policy": "no_semantic_fallback"},
            "runtime_failures": self.runtime_failures,
            "artifact_hashes": hashes,
        }
        provenance_errors = schema_errors(provenance, load_schema(PROVENANCE_SCHEMA_PATH))
        if provenance_errors:
            raise ValueError(
                "internal Structure v0.2 provenance failed schema validation: " + "; ".join(provenance_errors)
            )
        atomic_write_json(run_dir / "provenance.json", provenance)
        return result


def run_structure_v02(
    seed: int | None = None, *, provider: str | None = None, model: str | None = None, output_dir: Path | None = None
) -> dict[str, Any]:
    return StructureV02Pipeline(provider=provider, model=model).run(seed, output_dir=output_dir)
