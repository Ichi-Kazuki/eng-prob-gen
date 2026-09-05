"""Isolated Structure v0.3 sharded Generator -> Reviewer -> Selection -> Solver pipeline.

Implements exactly the approved v0.3 orchestration:

  v0.3 Planner
  -> Generator shard 1 (plan items 1-5, logical call 1)
  -> Generator shard 2 (plan items 6-10, logical call 2)
  -> Generator shard 3 (plan items 11-15, logical call 3)
  -> deterministic merge into one 15-item candidate batch
  -> frozen v0.2 blind seven-candidate Reviewer projection
  -> Reviewer (logical call 4)
  -> frozen v0.2 Reviewer exact-text contract/canonicalization
  -> frozen v0.2 deterministic private candidate selection
  -> whole-set selection gate
  -> frozen v0.2 pre-permutation four-option assembly
  -> frozen deterministic A-D permutation
  -> frozen blind final-four Solver projection
  -> Solver (logical call 5)
  -> frozen v0.1 Solver exact-text contract/canonicalization
  -> Solver-vs-final-key check
  -> whole-set ACCEPT / QUARANTINE.

Generator sharding is FAIL-FAST: if a shard invocation or contract fails, no
later shard, Reviewer, or Solver is invoked, and the whole set is
QUARANTINE. No semantic retry, repair, revision, regeneration, or item
replacement happens anywhere in this module.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from runtime.adapters import AgentRuntime, InvocationRequest, InvocationResult, RuntimeInvocationError
from shared.json_io import atomic_write_json
from shared.schema_validation import load_schema, schema_errors

from structure.contracts import SCHEMA_PATHS as V01_SCHEMA_PATHS
from structure.permutation import permute_generator_output
from structure.provenance import artifact_hashes, invocation_record
from structure.runtime import configured_runtime
from structure.v02 import blinding as v02_blinding
from structure.v02 import contracts as v02_contracts
from structure.v02 import selection as v02_selection
from structure.v02 import solver as v02_solver
from structure.v03 import contracts as v03_contracts
from structure.v03.planner import build_plan


ROOT = Path(__file__).resolve().parents[2]
STRUCTURE_VERSION = "v0.3"

GENERATOR_AGENT = "structure-generator-v0.3"
REVIEWER_AGENT = "structure-reviewer-v0.2"
SOLVER_AGENT = "structure-solver-v0.2"

_V02_PROMPT_DIR = Path(__file__).resolve().parents[1] / "v02" / "prompts"
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
AGENT_PATHS = {
    GENERATOR_AGENT: _PROMPT_DIR / "generator.md",
    REVIEWER_AGENT: _V02_PROMPT_DIR / "reviewer.md",
    SOLVER_AGENT: _V02_PROMPT_DIR / "solver.md",
}

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
_V02_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "v02" / "schemas"
SCHEMA_PATHS = {
    "generator_shard": _SCHEMA_DIR / "generator_shard_output.schema.json",
    "reviewer": _V02_SCHEMA_DIR / "reviewer_output.schema.json",
    "solver": V01_SCHEMA_PATHS["solver"],
}
RESULT_SCHEMA_PATH = _SCHEMA_DIR / "result.schema.json"
PROVENANCE_SCHEMA_PATH = _SCHEMA_DIR / "provenance.schema.json"

GENERATOR_SHARD_STAGES: dict[int, str] = {
    1: "structure_v03_generator_shard_1",
    2: "structure_v03_generator_shard_2",
    3: "structure_v03_generator_shard_3",
}
REVIEWER_STAGE = "structure_v03_reviewer"
SOLVER_STAGE = "structure_v03_solver"

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("STRUCTURE_TIMEOUT_SECONDS", "300"))
DEFAULT_MAX_BUDGET_USD = os.environ.get("STRUCTURE_MAX_BUDGET_USD", "0.60")

GENERATOR_INSTRUCTION = (
    "Generate exactly the five supplied Structure v0.3 plan items and no others. "
    "For every item, sentence_length_bin is a hard pre-output condition: silently "
    "compose/count/adjust/recount the completed correct sentence before emission. "
    "This local check is authorship, not a second review stage or second call. "
    "Return JSON only."
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


def _shard_payload(plan: Mapping[str, Any], shard: int) -> dict[str, Any]:
    start, end = v03_contracts.SHARD_ORDER_RANGES[shard]
    return {"items": copy.deepcopy(plan["items"][start - 1:end])}


def _v03_logical_invocation_counts(invocations: Iterable[InvocationResult]) -> dict[str, int]:
    """v0.3-specific logical invocation counter, keyed by exact stage-name equality.

    Deliberately does not use structure.provenance.logical_invocation_counts,
    which classifies by the final underscore suffix and therefore cannot
    distinguish structure_v03_generator_shard_1/2/3 from one another.
    """

    counts = {
        "generator_shard_1": 0,
        "generator_shard_2": 0,
        "generator_shard_3": 0,
        "reviewer": 0,
        "solver": 0,
    }
    stage_to_key = {
        GENERATOR_SHARD_STAGES[1]: "generator_shard_1",
        GENERATOR_SHARD_STAGES[2]: "generator_shard_2",
        GENERATOR_SHARD_STAGES[3]: "generator_shard_3",
        REVIEWER_STAGE: "reviewer",
        SOLVER_STAGE: "solver",
    }
    for invocation in invocations:
        key = stage_to_key.get(invocation.stage)
        if key is not None:
            counts[key] += 1
    return counts


class StructureV03Pipeline:
    """Run one complete Structure v0.3 set with no semantic retry or repair."""

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
        run_id = f"structure-v03-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        run_dir = (output_dir or ROOT / "runs" / "structure_v0_3" / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "plan.json", plan)

        # Generator-shard state (Section 16).
        shard_raw: dict[int, Any] = {1: None, 2: None, 3: None}
        shard_candidates: dict[int, Any] = {1: None, 2: None, 3: None}
        shard_errors: dict[int, list[str]] = {1: [], 2: [], 3: []}
        shard_invoked: dict[int, bool] = {1: False, 2: False, 3: False}
        shard_contract_passed: dict[int, bool] = {1: False, 2: False, 3: False}

        generator_candidates: dict[str, Any] | None = None
        merged_generator_errors: list[str] = []
        merged_constructed = False

        reviewer_input: dict[str, Any] | None = None
        reviewer_raw: Any = None
        candidate_selection: dict[str, Any] | None = None
        generator_final: dict[str, Any] | None = None
        permutation: dict[str, Any] | None = None
        generator: dict[str, Any] | None = None
        solver_input: dict[str, Any] | None = None
        solver_raw: Any = None

        canonical_reviewer: dict[str, Any] | None = None
        canonical_solver: dict[str, Any] | None = None

        reviewer_input_errors: list[str] = []
        reviewer_contract_errors: list[str] = []
        candidate_selection_integrity_errors: list[str] = []
        final_assembly_errors: list[str] = []
        permutation_errors: list[str] = []
        solver_input_errors: list[str] = []
        solver_contract_errors: list[str] = []

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
            for shard in (1, 2, 3):
                if not proceed:
                    break
                payload = _shard_payload(plan, shard)
                shard_invoked[shard] = True
                shard_result = self._invoke(
                    stage=GENERATOR_SHARD_STAGES[shard],
                    agent=GENERATOR_AGENT,
                    instruction=GENERATOR_INSTRUCTION,
                    payload=payload,
                    output_schema="generator_shard",
                    output_dir=run_dir,
                )
                shard_raw[shard] = shard_result.parsed
                shard_errors[shard] = v03_contracts.validate_generator_shard_contract(
                    shard_raw[shard], plan, shard
                )
                shard_contract_passed[shard] = not shard_errors[shard]
                if shard_contract_passed[shard]:
                    shard_candidates[shard] = copy.deepcopy(shard_raw[shard])
                else:
                    proceed = False

            all_shards_passed = all(shard_contract_passed[shard] for shard in (1, 2, 3))
            if proceed and all_shards_passed:
                try:
                    generator_candidates = v03_contracts.merge_generator_shards(
                        {shard: shard_candidates[shard] for shard in (1, 2, 3)}, plan
                    )
                    merged_constructed = True
                except ValueError as exc:
                    merged_generator_errors = [f"merged_generator: {exc}"]
                    proceed = False
            else:
                proceed = False

            if proceed:
                assert generator_candidates is not None
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

        first_shard_contract_failure = next(
            (shard for shard in (1, 2, 3) if shard_invoked[shard] and not shard_contract_passed[shard]),
            None,
        )

        # Determine the single stable global stop reason, if any.
        global_reason: str | None
        if runtime_failure_detail is not None:
            global_reason = f"runtime_failure:{runtime_failure_detail['stage']}:{runtime_failure_detail['category']}"
        elif first_shard_contract_failure is not None:
            global_reason = f"generator_shard_{first_shard_contract_failure}_contract_failed"
        elif not merged_constructed:
            global_reason = "merged_generator_contract_failed"
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
            shard_errors[1] + shard_errors[2] + shard_errors[3]
            + merged_generator_errors
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
            "generator_shard_1_raw.json": shard_raw[1],
            "generator_shard_1_candidates.json": shard_candidates[1],
            "generator_shard_2_raw.json": shard_raw[2],
            "generator_shard_2_candidates.json": shard_candidates[2],
            "generator_shard_3_raw.json": shard_raw[3],
            "generator_shard_3_candidates.json": shard_candidates[3],
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

        generator_shard_calls_completed = sum(1 for shard in (1, 2, 3) if shard_invoked[shard])
        generator_shard_contract_pass_count = sum(1 for shard in (1, 2, 3) if shard_contract_passed[shard])

        generator_shards_result_items = [
            {
                "shard": shard,
                "stage": GENERATOR_SHARD_STAGES[shard],
                "invoked": shard_invoked[shard],
                "contract_passed": shard_contract_passed[shard],
                "errors": shard_errors[shard],
            }
            for shard in (1, 2, 3)
        ]
        generator_shards_provenance_items = [
            {
                "shard": shard,
                "stage": GENERATOR_SHARD_STAGES[shard],
                "raw_artifact": f"generator_shard_{shard}_raw.json",
                "validated_artifact": f"generator_shard_{shard}_candidates.json",
                "invoked": shard_invoked[shard],
                "contract_passed": shard_contract_passed[shard],
            }
            for shard in (1, 2, 3)
        ]

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
            "schema_version": "structure-result-v0.3",
            "version": STRUCTURE_VERSION,
            "run_id": run_id,
            "seed": actual_seed,
            "decision": decision,
            "question_count": 15,
            "live_invocation_count": len(self.invocations),
            "generator_shard_calls_completed": generator_shard_calls_completed,
            "generator_shard_contract_pass_count": generator_shard_contract_pass_count,
            "merged_candidate_batch_constructed": merged_constructed,
            "deterministic_hard_failure_count": len(deterministic_errors),
            "candidate_selection_pass_count": candidate_selection_pass_count,
            "candidate_selection_failure_count": candidate_selection_failure_count,
            "solver_key_agreement_count": solver_key_agreement_count,
            "solver_ambiguous_none_count": solver_ambiguous_none_count,
            "final_answer_position_distribution": final_distribution,
            "item_results": item_results,
            "checks": {
                "generator_shards": {"items": generator_shards_result_items},
                "merged_generator_contract": {
                    "constructed": merged_constructed,
                    "passed": merged_constructed,
                    "errors": merged_generator_errors,
                },
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
            raise ValueError("internal Structure v0.3 result failed schema validation: " + "; ".join(result_errors))
        atomic_write_json(run_dir / "result.json", result)

        logical_invocation_counts = _v03_logical_invocation_counts(self.invocations)

        provenance = {
            "schema_version": "structure-provenance-v0.3",
            "version": STRUCTURE_VERSION,
            "run_id": run_id,
            "seed": actual_seed,
            "provider": provider,
            "model": model,
            "invocations": [invocation_record(item) for item in self.invocations],
            "invocation_ids": [item.invocation_id for item in self.invocations],
            "invocation_count": len(self.invocations),
            "logical_invocation_counts": logical_invocation_counts,
            "deterministic_validation": {
                "generator_shard_1": {"passed": shard_contract_passed[1], "errors": shard_errors[1]},
                "generator_shard_2": {"passed": shard_contract_passed[2], "errors": shard_errors[2]},
                "generator_shard_3": {"passed": shard_contract_passed[3], "errors": shard_errors[3]},
                "merged_generator": {"passed": merged_constructed, "errors": merged_generator_errors},
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
            "generator_shards": {
                "completed_calls": generator_shard_calls_completed,
                "contract_pass_count": generator_shard_contract_pass_count,
                "all_three_contracts_passed": all(shard_contract_passed[shard] for shard in (1, 2, 3)),
                "merged_candidate_batch_constructed": merged_constructed,
                "items": generator_shards_provenance_items,
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
                "internal Structure v0.3 provenance failed schema validation: " + "; ".join(provenance_errors)
            )
        atomic_write_json(run_dir / "provenance.json", provenance)
        return result


def run_structure_v03(
    seed: int | None = None, *, provider: str | None = None, model: str | None = None, output_dir: Path | None = None
) -> dict[str, Any]:
    return StructureV03Pipeline(provider=provider, model=model).run(seed, output_dir=output_dir)
