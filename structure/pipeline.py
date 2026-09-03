"""Isolated Structure v0.1 Generator -> Reviewer -> Solver pipeline."""

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

from .blinding import blind_input_errors, blind_input_sha256, build_blind_input
from .contracts import (
    SCHEMA_PATHS,
    post_blind_comparison,
    canonicalize_reviewer_output,
    reviewer_difficulty_diagnostics,
    reviewer_difficulty_summary,
    validate_generator_contract,
    validate_reviewer_contract,
    validate_solver_contract,
)
from .permutation import permute_generator_output
from .planner import STRUCTURE_VERSION, build_plan
from .provenance import artifact_hashes, invocation_record, logical_invocation_counts
from .runtime import configured_runtime


ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_CURRENT_VERSION = STRUCTURE_VERSION
GENERATOR_AGENT = "structure-generator-v0.1"
REVIEWER_AGENT = "structure-reviewer-v0.1"
SOLVER_AGENT = "structure-solver-v0.1"
AGENT_PATHS = {
    GENERATOR_AGENT: Path(__file__).resolve().parent / "prompts" / "generator.md",
    REVIEWER_AGENT: Path(__file__).resolve().parent / "prompts" / "reviewer.md",
    SOLVER_AGENT: Path(__file__).resolve().parent / "prompts" / "solver.md",
}
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("STRUCTURE_TIMEOUT_SECONDS", "300"))
DEFAULT_MAX_BUDGET_USD = os.environ.get("STRUCTURE_MAX_BUDGET_USD", "0.60")
RESULT_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "result.schema.json"
PROVENANCE_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "provenance.schema.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_runtime_value(value: Any) -> str:
    return str(value) if value is not None else "unknown"


class StructurePipeline:
    """Run one complete Structure set with no semantic retry or repair stage."""

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

    def _invoke(self, *, stage: str, agent: str, instruction: str, payload: Mapping[str, Any], output_schema: str, output_dir: Path, isolate_workspace: bool) -> InvocationResult:
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
            isolate_workspace=isolate_workspace,
        )
        try:
            result = self.runtime.invoke(request)
        except RuntimeInvocationError as exc:
            self.invocations.append(exc.result)
            self.runtime_failures.append({"stage": stage, "category": exc.category, "detail": exc.detail})
            raise
        self.invocations.append(result)
        return result

    @staticmethod
    def _item_results(
        plan: Mapping[str, Any],
        generator: Mapping[str, Any] | None,
        reviewer: Mapping[str, Any] | None,
        solver: Mapping[str, Any] | None,
        deterministic_errors: list[str],
        reviewer_errors: list[str],
        solver_errors: list[str],
    ) -> list[dict[str, Any]]:
        planned_items = [item for item in plan.get("items", []) if isinstance(item, dict)]
        generator_by_id = {
            item.get("item_id"): item for item in (generator or {}).get("items", []) if isinstance(item, dict)
        }
        reviewer_by_id = {
            item.get("item_id"): item for item in (reviewer or {}).get("items", []) if isinstance(item, dict)
        }
        solver_by_id = {
            item.get("item_id"): item for item in (solver or {}).get("items", []) if isinstance(item, dict)
        }
        results: list[dict[str, Any]] = []
        for planned in planned_items:
            item_id = planned["item_id"]
            reasons: list[str] = []
            if deterministic_errors:
                reasons.extend(f"deterministic_validation: {error}" for error in deterministic_errors)
            generator_item = generator_by_id.get(item_id)
            reviewer_item = reviewer_by_id.get(item_id)
            solver_item = solver_by_id.get(item_id)
            if not generator_item:
                reasons.append("generator_item_missing")
            if reviewer_errors:
                reasons.extend(f"reviewer_contract: {error}" for error in reviewer_errors)
            if solver_errors:
                reasons.extend(f"solver_contract: {error}" for error in solver_errors)

            if reviewer_item is None:
                reasons.append("reviewer_item_missing")
            else:
                if reviewer_item.get("serious_defect") is not False:
                    reasons.append("reviewer_serious_defect_true_or_missing")
                if reviewer_item.get("natural_wording") is not True:
                    reasons.append("reviewer_natural_wording_false_or_missing")
                best_answer = reviewer_item.get("best_answer")
                if best_answer not in {"A", "B", "C", "D"}:
                    reasons.append(f"reviewer_best_answer_not_unique_letter: {best_answer}")
                expected_answer = generator_item.get("correct_answer") if generator_item else None
                if best_answer != expected_answer:
                    reasons.append(f"reviewer_key_disagreement: reviewer={best_answer}, key={expected_answer}")
                judgments = reviewer_item.get("option_judgments")
                if isinstance(judgments, dict):
                    valid_count = sum(judgments.get(letter) == "VALID" for letter in ("A", "B", "C", "D"))
                    if valid_count != 1:
                        reasons.append(f"reviewer_valid_option_count: {valid_count}")
                    if any(judgments.get(letter) == "MARGINAL" for letter in ("A", "B", "C", "D")):
                        reasons.append("reviewer_marginal_threatens_uniqueness")
            if solver_item is None:
                reasons.append("solver_item_missing")
            else:
                solver_answer = solver_item.get("answer")
                expected_answer = generator_item.get("correct_answer") if generator_item else None
                if solver_answer not in {"A", "B", "C", "D"}:
                    reasons.append(f"solver_answer_not_unique_letter: {solver_answer}")
                if solver_answer != expected_answer:
                    reasons.append(f"solver_key_disagreement: solver={solver_answer}, key={expected_answer}")
                if solver_answer != (reviewer_item or {}).get("best_answer"):
                    reasons.append(
                        f"solver_reviewer_disagreement: solver={solver_answer}, reviewer={(reviewer_item or {}).get('best_answer')}"
                    )
                if solver_item.get("confidence") not in {"HIGH", "MEDIUM"}:
                    reasons.append(f"solver_confidence_not_accepted: {solver_item.get('confidence')}")
            results.append({"item_id": item_id, "accepted": not reasons, "rejection_reasons": list(dict.fromkeys(reasons))})
        return results

    def run(self, seed: int | None = None, *, output_dir: Path | None = None) -> dict[str, Any]:
        self.invocations = []
        self.runtime_failures = []
        actual_seed = secrets.randbits(32) if seed is None else seed
        plan = build_plan(actual_seed)
        run_id = f"structure-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        run_dir = (output_dir or ROOT / "runs" / "structure_v0_1" / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "plan.json", plan)

        raw_generator: Any = None
        generator_original: dict[str, Any] | None = None
        generator: dict[str, Any] | None = None
        permutation: dict[str, Any] | None = None
        blind: dict[str, Any] | None = None
        reviewer_raw: dict[str, Any] | None = None
        reviewer: dict[str, Any] | None = None
        solver: dict[str, Any] | None = None
        generator_errors: list[str] = []
        blind_errors: list[str] = []
        reviewer_errors: list[str] = []
        solver_errors: list[str] = []

        try:
            generator_result = self._invoke(
                stage="structure_generator",
                agent=GENERATOR_AGENT,
                instruction="Generate the complete Structure v0.1 set exactly from this Planner-owned plan. Return JSON only. Do not self-review or self-PASS.",
                payload=plan,
                output_schema="generator",
                output_dir=run_dir,
                isolate_workspace=True,
            )
            raw_generator = generator_result.parsed
            generator_errors = validate_generator_contract(raw_generator, plan)
            if not generator_errors:
                generator_original = copy.deepcopy(raw_generator)
                generator, permutation = permute_generator_output(raw_generator, actual_seed)
                blind = build_blind_input(generator)
                blind_errors = blind_input_errors(generator, blind, plan)
                if not blind_errors:
                    reviewer_result = self._invoke(
                        stage="structure_reviewer",
                        agent=REVIEWER_AGENT,
                        instruction="Review all 15 Structure items independently and blindly using only the visible input. Return JSON only.",
                        payload=blind,
                        output_schema="reviewer",
                        output_dir=run_dir,
                        isolate_workspace=True,
                    )
                    reviewer_raw = reviewer_result.parsed
                    reviewer_errors = validate_reviewer_contract(reviewer_raw, blind, plan)
                    if not reviewer_errors:
                        try:
                            reviewer = canonicalize_reviewer_output(reviewer_raw, blind)
                        except ValueError as exc:
                            reviewer_errors = [f"reviewer: canonicalization failed: {exc}"]
                    solver_result = self._invoke(
                        stage="structure_solver",
                        agent=SOLVER_AGENT,
                        instruction="Solve all 15 Structure items independently and blindly using only the visible input. Return JSON only.",
                        payload=blind,
                        output_schema="solver",
                        output_dir=run_dir,
                        isolate_workspace=True,
                    )
                    solver = solver_result.parsed
                    solver_errors = validate_solver_contract(solver, blind, plan)
        except RuntimeInvocationError:
            # Runtime failures are persisted and quarantine the whole set. No
            # semantic retry, repair, revision, or item replacement is made.
            pass

        deterministic_errors = list(dict.fromkeys(generator_errors + blind_errors))
        item_results = self._item_results(plan, generator, reviewer, solver, deterministic_errors, reviewer_errors, solver_errors)
        agreements: list[dict[str, Any]] = []
        agreement_count = 0
        if isinstance(generator, dict) and isinstance(reviewer, dict) and isinstance(solver, dict):
            agreements, agreement_count = post_blind_comparison(generator, reviewer, solver)
        reviewer_difficulty_agreement_count, reviewer_difficulty_low_confidence_count = reviewer_difficulty_summary(
            plan, reviewer
        )
        difficulty_diagnostics = reviewer_difficulty_diagnostics(plan, reviewer)

        reviewer_items = reviewer.get("items", []) if isinstance(reviewer, dict) else []
        solver_items = solver.get("items", []) if isinstance(solver, dict) else []
        reviewer_ambiguous_none_count = sum(
            isinstance(item, dict) and item.get("best_answer") in {"AMBIGUOUS", "NONE"} for item in reviewer_items
        )
        solver_ambiguous_none_count = sum(
            isinstance(item, dict) and item.get("answer") in {"AMBIGUOUS", "NONE"} for item in solver_items
        )
        final_distribution = {letter: 0 for letter in ("A", "B", "C", "D")}
        if permutation is not None:
            final_distribution.update(permutation["final_answer_position_distribution"])
        decision = "ACCEPT" if len(item_results) == 15 and all(item["accepted"] for item in item_results) else "QUARANTINE"

        values = {
            "plan.json": plan,
            "generator_raw.json": raw_generator,
            "generator_original.json": generator_original,
            "generator.json": generator,
            "permutation.json": permutation,
            "reviewer_input.json": blind,
            "reviewer.json": reviewer_raw,
            "solver_input.json": blind,
            "solver.json": solver,
        }
        hashes = artifact_hashes(values)
        atomic_write_json(run_dir / "generator_raw.json", raw_generator)
        atomic_write_json(run_dir / "generator_original.json", generator_original)
        atomic_write_json(run_dir / "generator.json", generator)
        atomic_write_json(run_dir / "permutation.json", permutation)
        atomic_write_json(run_dir / "reviewer_input.json", blind)
        atomic_write_json(run_dir / "reviewer.json", reviewer_raw)
        atomic_write_json(run_dir / "solver_input.json", blind)
        atomic_write_json(run_dir / "solver.json", solver)

        provider = _safe_runtime_value(getattr(self.runtime, "provider", "unknown"))
        model = _safe_runtime_value(self.invocations[0].model if self.invocations else getattr(self.runtime, "model", "unknown"))
        result = {
            "schema_version": "structure-result-v0.1",
            "version": STRUCTURE_VERSION,
            "run_id": run_id,
            "seed": actual_seed,
            "decision": decision,
            "question_count": 15,
            "live_invocation_count": len(self.invocations),
            "deterministic_hard_failure_count": len(deterministic_errors),
            "reviewer_solver_agreement": agreement_count,
            "reviewer_difficulty_agreement_count": reviewer_difficulty_agreement_count,
            "reviewer_difficulty_low_confidence_count": reviewer_difficulty_low_confidence_count,
            "reviewer_ambiguous_none_count": reviewer_ambiguous_none_count,
            "solver_ambiguous_none_count": solver_ambiguous_none_count,
            "final_answer_position_distribution": final_distribution,
            "item_results": item_results,
            "checks": {
                "deterministic_validation": not deterministic_errors,
                "generator_errors": generator_errors,
                "blind_errors": blind_errors,
                "reviewer_contract": not reviewer_errors and reviewer is not None,
                "reviewer_errors": reviewer_errors,
                "reviewer_canonicalization": {
                    "applied": reviewer is not None and not reviewer_errors,
                    "strategy": "exact_option_text_identity",
                    "raw_artifact": "reviewer.json",
                },
                "reviewer_difficulty": {
                    "policy": "diagnostic_only",
                    "agreement_count": reviewer_difficulty_agreement_count,
                    "low_confidence_count": reviewer_difficulty_low_confidence_count,
                    "per_item": difficulty_diagnostics,
                },
                "solver_contract": not solver_errors and solver is not None,
                "solver_errors": solver_errors,
                "reviewer_solver_agreement": agreements,
                "all_15_items_pass": len(item_results) == 15 and all(item["accepted"] for item in item_results),
                "no_repair_or_revision_stage": all(item.stage in {"structure_generator", "structure_reviewer", "structure_solver"} for item in self.invocations),
            },
            "infrastructure": {
                "provider": provider,
                "model": model,
                "runtime_failures": self.runtime_failures,
                "fallback_used": False,
                "invocation_counts": logical_invocation_counts(self.invocations),
                "invocation_ids": [item.invocation_id for item in self.invocations],
            },
            "artifact_hashes": hashes,
            "output_dir": str(run_dir),
        }
        result_errors = schema_errors(result, load_schema(RESULT_SCHEMA_PATH))
        if result_errors:
            raise ValueError("internal Structure result failed schema validation: " + "; ".join(result_errors))
        atomic_write_json(run_dir / "result.json", result)

        provenance = {
            "schema_version": "structure-provenance-v0.1",
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
                "passed": not deterministic_errors,
                "hard_failure_count": len(deterministic_errors),
                "errors": deterministic_errors,
            },
            "answer_position_permutation": permutation,
            "blind_inputs": {
                "allowlist": ["item_id", "section", "stem", "options"],
                "reviewer_input_sha256": blind_input_sha256(blind) if isinstance(blind, dict) else None,
                "solver_input_sha256": blind_input_sha256(blind) if isinstance(blind, dict) else None,
                "reviewer_solver_inputs_identical": isinstance(blind, dict),
            },
            "reviewer_canonicalization": {
                "applied": reviewer is not None and not reviewer_errors,
                "strategy": "exact_option_text_identity",
                "raw_artifact": "reviewer.json",
                "canonical_internal_shape": "option_judgments keyed A-D; best_answer letter or sentinel",
            },
            "reviewer_solver_agreement": {
                "count": agreement_count,
                "per_item": agreements,
            },
            "leakage": {
                "errors": blind_errors,
                "reviewer_contract_errors": reviewer_errors,
                "solver_contract_errors": solver_errors,
            },
            "fallback": {"used": False, "semantic_retry": False, "repair_stage": False, "revision_stage": False},
            "runtime_failures": self.runtime_failures,
            "artifact_hashes": {**hashes, "result.json": artifact_hashes({"result.json": result})["result.json"]},
        }
        provenance_errors = schema_errors(provenance, load_schema(PROVENANCE_SCHEMA_PATH))
        if provenance_errors:
            raise ValueError("internal Structure provenance failed schema validation: " + "; ".join(provenance_errors))
        atomic_write_json(run_dir / "provenance" / "provenance.json", provenance)
        return result


def run_structure(seed: int | None = None, *, provider: str | None = None, model: str | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    return StructurePipeline(provider=provider, model=model).run(seed, output_dir=output_dir)
