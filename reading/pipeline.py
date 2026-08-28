"""Three-call Reading v0.1 orchestration.

The live path is deliberately small: one Generator call, one blind Reviewer
call, and one blind Solver call.  A failed gate quarantines the first result;
there is no quality retry or answer repair.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runtime.adapters import (
    AgentRuntime,
    ClaudeRuntime,
    CodexRuntime,
    InvocationRequest,
    InvocationResult,
    RuntimeInvocationError,
)
from shared.json_io import atomic_write_json

from .contracts import (
    SCHEMA_PATHS,
    SCHEMA_PATHS_V02,
    blind_input,
    blind_input_errors,
    deterministic_diagnostics,
    payload_sha256,
    post_blind_comparison,
    solver_input_errors,
    validate_deterministic,
    validate_generator_contract,
    validate_result_contract,
    validate_draft_result_contract,
    validate_batch_result_contract,
    validate_reviewer_contract,
    validate_solver_contract,
)
from .diagnostics import aggregate_diagnostics, diagnostics_for_result
from .planner import build_plan_v01, build_plan_v02


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_AGENT = "toefl-itp-reading-generator"
REVIEWER_AGENT = "toefl-itp-reading-reviewer"
SOLVER_AGENT = "toefl-itp-reading-solver"
AGENT_PATHS = {
    GENERATOR_AGENT: ROOT / ".claude" / "agents" / f"{GENERATOR_AGENT}.md",
    REVIEWER_AGENT: ROOT / ".claude" / "agents" / f"{REVIEWER_AGENT}.md",
    SOLVER_AGENT: ROOT / ".claude" / "agents" / f"{SOLVER_AGENT}.md",
}
AGENT_PATHS_V02 = {
    GENERATOR_AGENT: ROOT / ".claude" / "agents" / f"{GENERATOR_AGENT}-v0.2.md",
    REVIEWER_AGENT: ROOT / ".claude" / "agents" / f"{REVIEWER_AGENT}-v0.2.md",
    SOLVER_AGENT: ROOT / ".claude" / "agents" / f"{SOLVER_AGENT}-v0.2.md",
}
DEFAULT_MODEL = os.environ.get("READING_MODEL", "sonnet")
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("READING_TIMEOUT_SECONDS", "300"))
DEFAULT_MAX_BUDGET_USD = os.environ.get("READING_MAX_BUDGET_USD", "0.60")
DEFAULT_PARALLELISM = 1


def configured_runtime(provider: str | None = None, model: str | None = None) -> AgentRuntime:
    """Create an existing provider-neutral runtime adapter."""

    selected = (provider or os.environ.get("READING_RUNTIME") or os.environ.get("WE_E2E_RUNTIME") or "claude").lower()
    if selected in {"codex", "codex-cli"}:
        return CodexRuntime(model=model or os.environ.get("READING_CODEX_MODEL"))
    if selected in {"claude", "claude-code", "claude-code-cli"}:
        return ClaudeRuntime(model=model or DEFAULT_MODEL)
    raise ValueError(f"unsupported Reading runtime provider: {selected!r}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe_invocation(invocation: InvocationResult) -> dict[str, Any]:
    def path(value: Path | None) -> str | None:
        return None if value is None else str(value)

    return {
        "stage": invocation.stage,
        "agent_name": invocation.agent_name,
        "invocation_id": invocation.invocation_id,
        "provider": invocation.provider,
        "model": invocation.model,
        "cli_version": invocation.cli_version,
        "started_at": invocation.started_at,
        "completed_at": invocation.completed_at,
        "exit_code": invocation.exit_code,
        "error_category": invocation.error_category,
        "error_detail": invocation.error_detail,
        "input_keys": list(invocation.input_keys),
        "raw_stdout_path": path(invocation.raw_stdout_path),
        "raw_stderr_path": path(invocation.raw_stderr_path),
        "output_last_message_path": path(invocation.output_last_message_path),
        "transport_schema_path": path(invocation.transport_schema_path),
        "transport_schema_provenance_path": path(invocation.transport_schema_provenance_path),
        "disabled_mcp_servers": list(invocation.disabled_mcp_servers),
        "requested_timeout_seconds": invocation.requested_timeout_seconds,
        "timeout_triggered_at": invocation.timeout_triggered_at,
        "termination_started_at": invocation.termination_started_at,
        "termination_completed_at": invocation.termination_completed_at,
        "termination_method": invocation.termination_method,
        "cleanup_duration_seconds": invocation.cleanup_duration_seconds,
    }


class ReadingPipeline:
    """Run one independent Reading v0.1 passage set."""

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
        prompt: str,
        input_keys: tuple[str, ...],
        schema_key: str,
        output_dir: Path,
        isolate_workspace: bool,
    ) -> InvocationResult:
        request = InvocationRequest(
            stage=stage,
            agent_name=agent,
            agent_definition=AGENT_PATHS[agent],
            prompt=prompt,
            input_keys=input_keys,
            formal_output_schema=SCHEMA_PATHS[schema_key],
            model=self.model,
            cwd=ROOT,
            sandbox="read-only" if getattr(self.runtime, "provider", "") == "codex" else None,
            tools="",
            max_budget_usd=self.max_budget_usd if getattr(self.runtime, "provider", "") == "claude-code-cli" else None,
            timeout_seconds=self.timeout_seconds,
            artifact_dir=output_dir / "runtime" / "logs",
            isolate_workspace=isolate_workspace,
            reasoning_effort=(
                os.environ.get("READING_CODEX_REASONING_EFFORT", "medium")
                if getattr(self.runtime, "provider", "") == "codex"
                else None
            ),
        )
        try:
            result = self.runtime.invoke(request)
        except RuntimeInvocationError as exc:
            self.invocations.append(exc.result)
            self.runtime_failures.append({
                "stage": stage,
                "category": exc.category,
                "detail": exc.detail,
            })
            raise
        self.invocations.append(result)
        return result

    @staticmethod
    def _prompt(instruction: str, payload: dict[str, Any]) -> str:
        return instruction + "\n\nINPUT_JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    def run(
        self,
        seed: int | None = None,
        *,
        domain: str | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Run exactly one first-pass set and persist every available artifact."""

        self.invocations = []
        self.runtime_failures = []
        actual_seed = secrets.randbits(32) if seed is None else seed
        plan = build_plan_v01(actual_seed, domain)
        run_id = f"reading-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        run_dir = (output_dir or ROOT / "runs" / "reading_v0_1" / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "plan.json", plan)

        expected_passage_id = f"rc-{actual_seed:08x}"
        generator: Any = None
        reviewer: Any = None
        solver: Any = None
        blind: dict[str, Any] | None = None
        generator_errors: list[str] = []
        deterministic_errors: list[str] = []
        reviewer_errors: list[str] = []
        solver_errors: list[str] = []
        post_blind_metadata_errors: list[str] = []
        blind_errors: list[str] = []
        agreements: list[dict[str, Any]] = []
        agreement_errors: list[str] = []

        try:
            generator_result = self._invoke(
                stage="reading_generator",
                agent=GENERATOR_AGENT,
                prompt=self._prompt(
                    "Generate one original TOEFL ITP-style Reading Comprehension set. Follow the supplied deterministic plan exactly. Return JSON only. Include the passage, exactly five questions, four choices per question, the Generator correct answer, and internal evidence/rationale metadata required by the schema. Never quote, paraphrase, or imitate any official ETS passage or question.",
                    plan,
                ),
                input_keys=("plan",),
                schema_key="generator",
                output_dir=run_dir,
                isolate_workspace=False,
            )
            generator = generator_result.parsed
            atomic_write_json(run_dir / "generator_output.json", generator)
            generator_errors = validate_generator_contract(generator, plan)
            if not generator_errors:
                deterministic_errors = validate_deterministic(generator, plan)
            if not generator_errors and not deterministic_errors:
                try:
                    blind = blind_input(generator)
                    blind_errors = blind_input_errors(generator, blind) + solver_input_errors(generator, blind)
                except (KeyError, TypeError, ValueError) as exc:
                    blind_errors = [str(exc)]
            if blind is not None:
                atomic_write_json(run_dir / "reviewer_input.json", blind)
                atomic_write_json(run_dir / "solver_input.json", blind)

            if blind is not None and not blind_errors:
                reviewer_result = self._invoke(
                    stage="reading_reviewer",
                    agent=REVIEWER_AGENT,
                    prompt=self._prompt(
                        "Independently audit this Reading set as a blind Reviewer. Use only the visible passage, stems, and A/B/C/D choices in INPUT_JSON. For every question choose the best answer, or AMBIGUOUS/NONE, and assess uniqueness, distractors, answerability, wording, and serious defects. Return JSON only. Do not request or infer hidden Generator metadata.",
                        blind,
                    ),
                    input_keys=("passage_id", "section", "title", "passage", "questions"),
                    schema_key="reviewer",
                    output_dir=run_dir,
                    isolate_workspace=True,
                )
                reviewer = reviewer_result.parsed
                atomic_write_json(run_dir / "reviewer_output.json", reviewer)
                reviewer_errors = validate_reviewer_contract(reviewer, blind)

                solver_result = self._invoke(
                    stage="reading_solver",
                    agent=SOLVER_AGENT,
                    prompt=self._prompt(
                        "Solve this Reading set independently as a test-taker. Use only INPUT_JSON. Return exactly one answer for each question: A, B, C, D, AMBIGUOUS, or NONE, with confidence and a concise reason. Do not use or request Generator or Reviewer metadata. Return JSON only.",
                        blind,
                    ),
                    input_keys=("passage_id", "section", "title", "passage", "questions"),
                    schema_key="solver",
                    output_dir=run_dir,
                    isolate_workspace=True,
                )
                solver = solver_result.parsed
                atomic_write_json(run_dir / "solver_output.json", solver)
                solver_errors = validate_solver_contract(solver, blind)

                if not reviewer_errors and not solver_errors:
                    agreements, agreement_errors = post_blind_comparison(generator, reviewer, solver)
                post_blind_metadata_errors = validate_generator_contract(generator, plan)
        except RuntimeInvocationError:
            # The first-pass result is retained and finalized as QUARANTINE.
            pass

        if blind is not None and not (run_dir / "reviewer_input.json").exists():
            atomic_write_json(run_dir / "reviewer_input.json", blind)
            atomic_write_json(run_dir / "solver_input.json", blind)
        if reviewer is not None and not (run_dir / "reviewer_output.json").exists():
            atomic_write_json(run_dir / "reviewer_output.json", reviewer)
        if solver is not None and not (run_dir / "solver_output.json").exists():
            atomic_write_json(run_dir / "solver_output.json", solver)

        reviewer_questions = reviewer.get("questions", []) if isinstance(reviewer, dict) else []
        solver_answers = solver.get("answers", []) if isinstance(solver, dict) else []
        reviewer_no_ambiguous_none = bool(reviewer_questions) and all(
            item.get("best_answer") not in {"AMBIGUOUS", "NONE"} for item in reviewer_questions
        ) and all(
            item.get("unique_answer") is True
            and item.get("distractors_incorrect") is True
            and item.get("answerable") is True
            and item.get("natural_wording") is True
            and item.get("serious_defect") is False
            for item in reviewer_questions
        )
        solver_no_ambiguous_none = bool(solver_answers) and all(
            item.get("answer") not in {"AMBIGUOUS", "NONE"} for item in solver_answers
        )
        all_answers_agree = bool(agreements) and not agreement_errors and all(item["agree"] for item in agreements)
        leakage_ok = not blind_errors and blind is not None
        checks: dict[str, Any] = {
            "generator_canonical": not generator_errors,
            "deterministic": not deterministic_errors and not generator_errors,
            "reviewer_contract": not reviewer_errors and reviewer is not None,
            "reviewer_set_pass": isinstance(reviewer, dict) and reviewer.get("set_judgment") == "PASS",
            "reviewer_no_ambiguous_none": reviewer_no_ambiguous_none,
            "solver_contract": not solver_errors and solver is not None,
            "solver_no_ambiguous_none": solver_no_ambiguous_none,
            "all_answers_agree": all_answers_agree,
            "post_blind_metadata": not post_blind_metadata_errors and generator is not None,
            "no_leakage": leakage_ok,
            "no_synthetic_fallback": True,
            "generator_errors": generator_errors,
            "deterministic_errors": deterministic_errors,
            "blind_errors": blind_errors,
            "reviewer_errors": reviewer_errors,
            "solver_errors": solver_errors,
            "answer_agreement": agreements,
            "answer_disagreement_errors": agreement_errors,
            "post_blind_metadata_errors": post_blind_metadata_errors,
        }
        accept = all(
            checks[key] is True
            for key in (
                "generator_canonical",
                "deterministic",
                "reviewer_contract",
                "reviewer_set_pass",
                "reviewer_no_ambiguous_none",
                "solver_contract",
                "solver_no_ambiguous_none",
                "all_answers_agree",
                "post_blind_metadata",
                "no_leakage",
                "no_synthetic_fallback",
            )
        ) and not self.runtime_failures
        result: dict[str, Any] = {
            "schema_version": "reading-result-v0.1",
            "run_id": run_id,
            "decision": "ACCEPT" if accept else "QUARANTINE",
            "passage_id": expected_passage_id,
            "section": "READING_COMPREHENSION",
            "plan": copy.deepcopy(plan),
            "generator": generator if isinstance(generator, dict) else None,
            "reviewer": reviewer if isinstance(reviewer, dict) else None,
            "solver": solver if isinstance(solver, dict) else None,
            "checks": checks,
            "infrastructure": {
                "live_invocations": len(self.invocations),
                "provider": getattr(self.runtime, "provider", "unknown"),
                "runtime_failures": self.runtime_failures,
                "synthetic_fallback": False,
            },
        }
        result_contract_errors = validate_result_contract(result)
        if result_contract_errors:
            result["decision"] = "QUARANTINE"
        result["checks"]["final_result_contract"] = not result_contract_errors
        result["checks"]["final_result_errors"] = result_contract_errors
        atomic_write_json(run_dir / "invocations.json", {
            "live_invocations": len(self.invocations),
            "invocations": [_json_safe_invocation(item) for item in self.invocations],
        })
        atomic_write_json(run_dir / "provenance.json", {
            "schema_version": "reading-provenance-v0.1",
            "run_id": run_id,
            "created_at": _now_iso(),
            "provider": getattr(self.runtime, "provider", "unknown"),
            "model": self.model or "runtime-default",
            "plan_sha256": payload_sha256(plan),
            "blind_input_sha256": payload_sha256(blind) if blind is not None else None,
            "canonical_schema_paths": {key: str(path) for key, path in SCHEMA_PATHS.items()},
            "invocation_ids": [item.invocation_id for item in self.invocations],
            "answer_bearing_prompt_fields": ["plan"],
            "blind_prompt_fields": ["passage_id", "section", "title", "passage", "questions"],
        })
        atomic_write_json(run_dir / "result.json", result)
        return result


class ReadingV02Pipeline(ReadingPipeline):
    """Run one isolated variable-length Reading v0.2 passage set.

    This class intentionally does not call the parent ``run`` method: the
    parent is the historical v0.1 smoke path.  It reuses the same runtime
    adapter and workspace cleanup behavior, but selects v0.2 schemas, agents,
    artifact names, and the variable question plan.
    """

    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_budget_usd: str | None = DEFAULT_MAX_BUDGET_USD,
    ) -> None:
        super().__init__(
            runtime,
            provider=provider,
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
        self.schema_paths = SCHEMA_PATHS_V02
        self.agent_paths = AGENT_PATHS_V02
        self.blind_schema_version = "reading-blind-input-v0.2"
        self.result_schema_version = "reading-result-v0.2"
        self.artifact_root = ROOT / "runs" / "reading_v0_2"

    def _invoke(
        self,
        *,
        stage: str,
        agent: str,
        prompt: str,
        input_keys: tuple[str, ...],
        schema_key: str,
        output_dir: Path,
        isolate_workspace: bool,
    ) -> InvocationResult:
        request = InvocationRequest(
            stage=stage,
            agent_name=agent,
            agent_definition=self.agent_paths[agent],
            prompt=prompt,
            input_keys=input_keys,
            formal_output_schema=self.schema_paths[schema_key],
            model=self.model,
            cwd=ROOT,
            sandbox="read-only" if getattr(self.runtime, "provider", "") == "codex" else None,
            tools="",
            max_budget_usd=self.max_budget_usd if getattr(self.runtime, "provider", "") == "claude-code-cli" else None,
            timeout_seconds=self.timeout_seconds,
            artifact_dir=output_dir / "runtime" / "logs",
            isolate_workspace=isolate_workspace,
            reasoning_effort=(
                os.environ.get("READING_CODEX_REASONING_EFFORT", "medium")
                if getattr(self.runtime, "provider", "") == "codex"
                else None
            ),
        )
        try:
            result = self.runtime.invoke(request)
        except RuntimeInvocationError as exc:
            self.invocations.append(exc.result)
            self.runtime_failures.append({
                "stage": stage,
                "category": exc.category,
                "detail": exc.detail,
            })
            raise
        self.invocations.append(result)
        return result

    def _run_metadata(self) -> dict[str, Any]:
        counts = Counter(item.stage for item in self.invocations)
        return {
            "live_invocations": len(self.invocations),
            "invocation_counts": {
                "generator": counts["reading_generator"],
                "reviewer": counts["reading_reviewer"],
                "solver": counts["reading_solver"],
            },
            "provider": getattr(self.runtime, "provider", "unknown"),
            "runtime_failures": self.runtime_failures,
            "synthetic_fallback": False,
        }

    def _write_invocations_and_provenance(
        self,
        run_dir: Path,
        run_id: str,
        plan: dict[str, Any],
        blind: dict[str, Any] | None,
    ) -> None:
        atomic_write_json(run_dir / "invocations.json", {
            "live_invocations": len(self.invocations),
            "invocations": [_json_safe_invocation(item) for item in self.invocations],
        })
        atomic_write_json(run_dir / "provenance" / "provenance.json", {
            "schema_version": "reading-provenance-v0.2",
            "run_id": run_id,
            "created_at": _now_iso(),
            "provider": getattr(self.runtime, "provider", "unknown"),
            "model": self.model or "runtime-default",
            "plan_sha256": payload_sha256(plan),
            "blind_input_sha256": payload_sha256(blind) if blind is not None else None,
            "canonical_schema_paths": {key: str(path) for key, path in self.schema_paths.items()},
            "invocation_ids": [item.invocation_id for item in self.invocations],
            "answer_bearing_prompt_fields": ["plan"],
            "blind_prompt_fields": ["passage_id", "section", "title", "passage", "questions"],
        })

    def run(
        self,
        seed: int | None = None,
        *,
        domain: str | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Run one first-pass variable-length set with exactly three stages."""

        started = time.perf_counter()
        self.invocations = []
        self.runtime_failures = []
        actual_seed = secrets.randbits(32) if seed is None else seed
        plan = build_plan_v02(actual_seed, domain)
        run_id = f"reading-v02-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
        run_dir = (output_dir or self.artifact_root / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "plan.json", plan)

        expected_passage_id = f"rc-{actual_seed:08x}"
        generator: Any = None
        reviewer: Any = None
        solver: Any = None
        blind: dict[str, Any] | None = None
        generator_errors: list[str] = []
        deterministic_errors: list[str] = []
        empirical_warnings: list[str] = []
        deterministic_classification = "HARD_VALIDITY"
        reviewer_errors: list[str] = []
        solver_errors: list[str] = []
        post_blind_metadata_errors: list[str] = []
        blind_errors: list[str] = []
        agreements: list[dict[str, Any]] = []
        agreement_errors: list[str] = []

        try:
            generator_result = self._invoke(
                stage="reading_generator",
                agent=GENERATOR_AGENT,
                prompt=self._prompt(
                    "Generate one original TOEFL ITP-style Reading Comprehension set. Follow the supplied deterministic plan exactly. Return JSON only. The passage_id must be exactly rc- followed by the plan seed as eight lowercase hexadecimal digits (for example, seed 1002 means rc-000003ea); every item_id must be that exact passage_id followed by -q1, -q2, and so on. Generate exactly the planned question_count questions, and make the count of every question type exactly match question_type_counts. The legacy question_plan order is compatibility guidance only; ordering of the generated questions is free. Include four A/B/C/D choices per question and the Generator correct answer plus private evidence/rationale metadata required by the schema. Process the whole passage set in this one invocation. Never quote, paraphrase, or imitate any official ETS passage or question.",
                    plan,
                ),
                input_keys=("plan",),
                schema_key="generator",
                output_dir=run_dir,
                isolate_workspace=False,
            )
            generator = generator_result.parsed
            atomic_write_json(run_dir / "generator.json", generator)
            generator_errors = validate_generator_contract(generator, plan, self.schema_paths)
            validation = deterministic_diagnostics(generator, plan, self.schema_paths)
            empirical_warnings = validation["empirical_warnings"]
            deterministic_classification = validation["classification"]
            if not generator_errors:
                deterministic_errors = validation["hard_failures"]
                post_blind_metadata_errors = validate_generator_contract(generator, plan, self.schema_paths)
            if not generator_errors and not deterministic_errors:
                try:
                    blind = blind_input(generator, schema_version=self.blind_schema_version)
                    blind_errors = (
                        blind_input_errors(generator, blind, self.schema_paths, self.blind_schema_version)
                        + solver_input_errors(generator, blind, self.schema_paths, self.blind_schema_version)
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    blind_errors = [str(exc)]
            if blind is not None:
                atomic_write_json(run_dir / "reviewer_input.json", blind)
                atomic_write_json(run_dir / "solver_input.json", blind)

            if blind is not None and not blind_errors:
                reviewer_result = self._invoke(
                    stage="reading_reviewer",
                    agent=REVIEWER_AGENT,
                    prompt=self._prompt(
                        "Independently audit this entire Reading set as a blind Reviewer. Use only the visible passage, stems, and A/B/C/D choices in INPUT_JSON. Process every question in this one invocation. For every question choose the best answer, or AMBIGUOUS/NONE, and assess uniqueness, distractors, answerability, wording, and serious defects. Return JSON only. Do not request or infer hidden Generator metadata.",
                        blind,
                    ),
                    input_keys=("passage_id", "section", "title", "passage", "questions"),
                    schema_key="reviewer",
                    output_dir=run_dir,
                    isolate_workspace=True,
                )
                reviewer = reviewer_result.parsed
                atomic_write_json(run_dir / "reviewer.json", reviewer)
                reviewer_errors = validate_reviewer_contract(reviewer, blind, self.schema_paths)

                solver_result = self._invoke(
                    stage="reading_solver",
                    agent=SOLVER_AGENT,
                    prompt=self._prompt(
                        "Solve this entire Reading set independently as a test-taker. Use only INPUT_JSON and process every visible question in this one invocation. Return exactly one answer for each question: A, B, C, D, AMBIGUOUS, or NONE, with confidence and a concise reason. Do not use or request Generator or Reviewer metadata. Return JSON only.",
                        blind,
                    ),
                    input_keys=("passage_id", "section", "title", "passage", "questions"),
                    schema_key="solver",
                    output_dir=run_dir,
                    isolate_workspace=True,
                )
                solver = solver_result.parsed
                atomic_write_json(run_dir / "solver.json", solver)
                solver_errors = validate_solver_contract(solver, blind, self.schema_paths)

                if not reviewer_errors and not solver_errors:
                    agreements, agreement_errors = post_blind_comparison(generator, reviewer, solver)
        except RuntimeInvocationError:
            # Preserve the first pass. Infrastructure failure is distinct from
            # quality quarantine and never triggers replacement generation.
            pass

        if blind is not None and not (run_dir / "reviewer_input.json").exists():
            atomic_write_json(run_dir / "reviewer_input.json", blind)
            atomic_write_json(run_dir / "solver_input.json", blind)
        if reviewer is not None and not (run_dir / "reviewer.json").exists():
            atomic_write_json(run_dir / "reviewer.json", reviewer)
        if solver is not None and not (run_dir / "solver.json").exists():
            atomic_write_json(run_dir / "solver.json", solver)

        reviewer_questions = reviewer.get("questions", []) if isinstance(reviewer, dict) else []
        solver_answers = solver.get("answers", []) if isinstance(solver, dict) else []
        reviewer_no_ambiguous_none = bool(reviewer_questions) and all(
            item.get("best_answer") not in {"AMBIGUOUS", "NONE"} for item in reviewer_questions
        ) and all(
            item.get("unique_answer") is True
            and item.get("distractors_incorrect") is True
            and item.get("answerable") is True
            and item.get("natural_wording") is True
            and item.get("serious_defect") is False
            for item in reviewer_questions
        )
        solver_no_ambiguous_none = bool(solver_answers) and all(
            item.get("answer") not in {"AMBIGUOUS", "NONE"} for item in solver_answers
        )
        all_answers_agree = bool(agreements) and not agreement_errors and all(item["agree"] for item in agreements)
        leakage_ok = not blind_errors and blind is not None
        checks: dict[str, Any] = {
            "generator_canonical": not generator_errors,
            "deterministic": not deterministic_errors and not generator_errors,
            "reviewer_contract": not reviewer_errors and reviewer is not None,
            "reviewer_set_pass": isinstance(reviewer, dict) and reviewer.get("set_judgment") == "PASS",
            "reviewer_no_ambiguous_none": reviewer_no_ambiguous_none,
            "solver_contract": not solver_errors and solver is not None,
            "solver_no_ambiguous_none": solver_no_ambiguous_none,
            "all_answers_agree": all_answers_agree,
            "post_blind_metadata": not post_blind_metadata_errors and generator is not None,
            "no_leakage": leakage_ok,
            "no_synthetic_fallback": True,
            "deterministic_classification": deterministic_classification,
            "empirical_warnings": empirical_warnings,
            "generator_errors": generator_errors,
            "deterministic_errors": deterministic_errors,
            "blind_errors": blind_errors,
            "reviewer_errors": reviewer_errors,
            "solver_errors": solver_errors,
            "answer_agreement": agreements,
            "answer_disagreement_errors": agreement_errors,
            "post_blind_metadata_errors": post_blind_metadata_errors,
        }
        accept = all(
            checks[key] is True
            for key in (
                "generator_canonical",
                "deterministic",
                "reviewer_contract",
                "reviewer_set_pass",
                "reviewer_no_ambiguous_none",
                "solver_contract",
                "solver_no_ambiguous_none",
                "all_answers_agree",
                "post_blind_metadata",
                "no_leakage",
                "no_synthetic_fallback",
            )
        ) and not self.runtime_failures
        infrastructure = self._run_metadata()
        infrastructure["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        result: dict[str, Any] = {
            "schema_version": self.result_schema_version,
            "run_id": run_id,
            "decision": "INFRASTRUCTURE_FAILURE" if self.runtime_failures else ("ACCEPT" if accept else "QUARANTINE"),
            "passage_id": expected_passage_id,
            "section": "READING_COMPREHENSION",
            "plan": copy.deepcopy(plan),
            "generator": generator if isinstance(generator, dict) else None,
            "reviewer": reviewer if isinstance(reviewer, dict) else None,
            "solver": solver if isinstance(solver, dict) else None,
            "checks": checks,
            "infrastructure": infrastructure,
        }
        result["diagnostics"] = diagnostics_for_result(result)
        result_contract_errors = validate_result_contract(result, self.schema_paths)
        if result_contract_errors:
            result["decision"] = "INFRASTRUCTURE_FAILURE" if self.runtime_failures else "QUARANTINE"
        result["checks"]["final_result_contract"] = not result_contract_errors
        result["checks"]["final_result_errors"] = result_contract_errors
        self._write_invocations_and_provenance(run_dir, run_id, plan, blind)
        atomic_write_json(run_dir / "result.json", result)
        return result

    def run_draft(
        self,
        seed: int | None = None,
        *,
        domain: str | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Generate one explicitly non-production Generator-only draft."""

        started = time.perf_counter()
        self.invocations = []
        self.runtime_failures = []
        actual_seed = secrets.randbits(32) if seed is None else seed
        plan = build_plan_v02(actual_seed, domain)
        run_id = f"reading-v02-draft-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
        run_dir = (output_dir or self.artifact_root / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "plan.json", plan)
        generator: Any = None
        generator_errors: list[str] = []
        deterministic_errors: list[str] = []
        empirical_warnings: list[str] = []
        deterministic_classification = "HARD_VALIDITY"
        try:
            generator_result = self._invoke(
                stage="reading_generator",
                agent=GENERATOR_AGENT,
                prompt=self._prompt(
                    "Generate one original TOEFL ITP-style Reading Comprehension draft. Follow the supplied deterministic plan exactly. Return JSON only. The passage_id must be exactly rc- followed by the plan seed as eight lowercase hexadecimal digits; every item_id must be that exact passage_id followed by -q1, -q2, and so on. Generate exactly the planned question_count questions, and make the count of every question type exactly match question_type_counts. The legacy question_plan order is compatibility guidance only; ordering of the generated questions is free. Include four A/B/C/D choices per question and the Generator correct answer plus private evidence/rationale metadata required by the schema. This is an UNVALIDATED_DRAFT for development inspection only. Never quote, paraphrase, or imitate any official ETS passage or question.",
                    plan,
                ),
                input_keys=("plan",),
                schema_key="generator",
                output_dir=run_dir,
                isolate_workspace=False,
            )
            generator = generator_result.parsed
            atomic_write_json(run_dir / "generator.json", generator)
            generator_errors = validate_generator_contract(generator, plan, self.schema_paths)
            validation = deterministic_diagnostics(generator, plan, self.schema_paths)
            empirical_warnings = validation["empirical_warnings"]
            deterministic_classification = validation["classification"]
            if not generator_errors:
                deterministic_errors = validation["hard_failures"]
        except RuntimeInvocationError:
            pass

        status = "INFRASTRUCTURE_FAILURE" if self.runtime_failures else (
            "VALIDATED_SHAPE" if generator is not None and not generator_errors and not deterministic_errors else "QUARANTINE"
        )
        infrastructure = self._run_metadata()
        infrastructure["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        result: dict[str, Any] = {
            "schema_version": "reading-draft-result-v0.2",
            "run_id": run_id,
            "decision": "UNVALIDATED_DRAFT",
            "draft_status": status,
            "production_eligible": False,
            "passage_id": f"rc-{actual_seed:08x}",
            "section": "READING_COMPREHENSION",
            "plan": copy.deepcopy(plan),
            "generator": generator if isinstance(generator, dict) else None,
            "reviewer": None,
            "solver": None,
            "checks": {
                "generator_canonical": not generator_errors,
                "deterministic": not deterministic_errors and not generator_errors,
                "draft_only": True,
                "production_eligible": False,
                "deterministic_classification": deterministic_classification,
                "empirical_warnings": empirical_warnings,
                "generator_errors": generator_errors,
                "deterministic_errors": deterministic_errors,
            },
            "infrastructure": infrastructure,
        }
        result["diagnostics"] = diagnostics_for_result(result)
        result_contract_errors = validate_draft_result_contract(result)
        result["checks"]["final_result_contract"] = not result_contract_errors
        result["checks"]["final_result_errors"] = result_contract_errors
        self._write_invocations_and_provenance(run_dir, run_id, plan, None)
        atomic_write_json(run_dir / "result.json", result)
        return result


def derive_passage_seed(base_seed: int, passage_index: int) -> int:
    """Derive stable one-based passage seeds without shared mutable state."""

    if not isinstance(base_seed, int) or isinstance(base_seed, bool) or base_seed < 0:
        raise ValueError("base_seed must be a non-negative integer")
    if not isinstance(passage_index, int) or isinstance(passage_index, bool) or passage_index < 1:
        raise ValueError("passage_index must be a positive integer")
    return base_seed + passage_index - 1


def _unexpected_failure_result(
    *,
    seed: int,
    passage_dir: Path,
    exc: Exception,
    provider: str | None,
    domain: str | None = None,
) -> dict[str, Any]:
    """Persist an isolated failure record when setup or persistence aborts a worker."""

    passage_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"reading-v02-failure-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
    plan = build_plan_v02(seed, domain) if isinstance(seed, int) and seed >= 0 else {}
    result = {
        "schema_version": "reading-result-v0.2",
        "run_id": run_id,
        "decision": "INFRASTRUCTURE_FAILURE",
        "passage_id": f"rc-{seed:08x}",
        "section": "READING_COMPREHENSION",
        "plan": plan,
        "generator": None,
        "reviewer": None,
        "solver": None,
        "checks": {
            "generator_canonical": False,
            "deterministic": False,
            "reviewer_contract": False,
            "reviewer_set_pass": False,
            "reviewer_no_ambiguous_none": False,
            "solver_contract": False,
            "solver_no_ambiguous_none": False,
            "all_answers_agree": False,
            "post_blind_metadata": False,
            "no_leakage": True,
            "no_synthetic_fallback": True,
            "generator_errors": [f"worker setup failure: {type(exc).__name__}: {exc}"],
            "deterministic_errors": [],
            "blind_errors": [],
            "reviewer_errors": [],
            "solver_errors": [],
            "answer_agreement": [],
            "answer_disagreement_errors": [],
            "post_blind_metadata_errors": [],
        },
        "infrastructure": {
            "live_invocations": 0,
            "invocation_counts": {"generator": 0, "reviewer": 0, "solver": 0},
            "provider": provider or "unknown",
            "runtime_failures": [{"stage": "worker", "category": "infrastructure", "detail": str(exc)}],
            "synthetic_fallback": False,
            "elapsed_seconds": 0.0,
        },
    }
    result["diagnostics"] = diagnostics_for_result(result)
    result["checks"]["final_result_contract"] = not validate_result_contract(result, SCHEMA_PATHS_V02)
    result["checks"]["final_result_errors"] = validate_result_contract(result, SCHEMA_PATHS_V02)
    try:
        atomic_write_json(passage_dir / "plan.json", plan)
        atomic_write_json(passage_dir / "result.json", result)
        atomic_write_json(passage_dir / "invocations.json", {"live_invocations": 0, "invocations": []})
        atomic_write_json(passage_dir / "provenance" / "provenance.json", {
            "schema_version": "reading-provenance-v0.2",
            "run_id": run_id,
            "provider": provider or "unknown",
            "invocation_ids": [],
            "failure": str(exc),
        })
    except Exception:
        # The batch still carries this failure in memory even if the directory
        # itself is unavailable; never let it cancel other futures.
        pass
    return result


def run_reading_batch(
    seed: int | None = None,
    *,
    count: int = 1,
    parallel: int = DEFAULT_PARALLELISM,
    domain: str | None = None,
    output_dir: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    mode: str = "validated",
    runtime_factory: Callable[[int], AgentRuntime] | None = None,
) -> dict[str, Any]:
    """Run independent passage pipelines with bounded worker concurrency."""

    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("count must be a positive integer")
    if not isinstance(parallel, int) or isinstance(parallel, bool) or parallel < 1:
        raise ValueError("parallel must be a positive integer")
    if mode not in {"validated", "draft"}:
        raise ValueError("mode must be 'validated' or 'draft'")
    base_seed = secrets.randbits(32) if seed is None else seed
    if not isinstance(base_seed, int) or isinstance(base_seed, bool) or base_seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if domain is not None and domain not in {
        "biology", "geology", "astronomy", "anthropology", "history", "ecology", "technology", "earth science"
    }:
        raise ValueError(f"unsupported Reading domain: {domain!r}")

    batch_started = time.perf_counter()
    batch_id = f"reading-v02-batch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
    batch_dir = (output_dir or ROOT / "runs" / "reading_v0_2" / batch_id).resolve()
    batch_dir.mkdir(parents=True, exist_ok=True)
    worker_count = min(parallel, count)

    def run_one(passage_index: int) -> tuple[int, int, dict[str, Any]]:
        passage_seed = derive_passage_seed(base_seed, passage_index)
        passage_dir = batch_dir / f"passage-{passage_index:03d}"
        started = time.perf_counter()
        try:
            runtime = runtime_factory(passage_index) if runtime_factory is not None else configured_runtime(provider, model)
            pipeline = ReadingV02Pipeline(
                runtime,
                model=model,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_budget_usd=DEFAULT_MAX_BUDGET_USD,
            )
            result = pipeline.run_draft(passage_seed, domain=domain, output_dir=passage_dir) if mode == "draft" else pipeline.run(passage_seed, domain=domain, output_dir=passage_dir)
            result["infrastructure"]["elapsed_seconds"] = round(time.perf_counter() - started, 6)
            # Rewrite the completed result atomically because the batch wrapper
            # measures the full worker lifetime, including runtime setup.
            atomic_write_json(passage_dir / "result.json", result)
            return passage_index, passage_seed, result
        except Exception as exc:
            return passage_index, passage_seed, _unexpected_failure_result(
                seed=passage_seed,
                passage_dir=passage_dir,
                exc=exc,
                provider=provider,
                domain=domain,
            )

    outputs: list[tuple[int, int, dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="reading-v02") as executor:
        futures = {executor.submit(run_one, index): index for index in range(1, count + 1)}
        for future in as_completed(futures):
            # A worker-level exception is converted to an isolated result;
            # this guard also protects against an unexpected executor error.
            index = futures[future]
            passage_seed = derive_passage_seed(base_seed, index)
            try:
                outputs.append(future.result())
            except Exception as exc:
                outputs.append((index, passage_seed, _unexpected_failure_result(
                    seed=passage_seed,
                    passage_dir=batch_dir / f"passage-{index:03d}",
                    exc=exc,
                    provider=provider,
                    domain=domain,
                )))
    outputs.sort(key=lambda item: item[0])
    results = [item[2] for item in outputs]

    accept_count = sum(result.get("decision") == "ACCEPT" for result in results)
    quarantine_count = sum(result.get("decision") == "QUARANTINE" for result in results)
    infrastructure_failure_count = sum(result.get("decision") == "INFRASTRUCTURE_FAILURE" for result in results)
    invocation_counts = {
        "generator": sum(result.get("infrastructure", {}).get("invocation_counts", {}).get("generator", 0) for result in results),
        "reviewer": sum(result.get("infrastructure", {}).get("invocation_counts", {}).get("reviewer", 0) for result in results),
        "solver": sum(result.get("infrastructure", {}).get("invocation_counts", {}).get("solver", 0) for result in results),
    }
    passage_artifacts = []
    for (index, passage_seed, result) in outputs:
        generator = result.get("generator") if isinstance(result.get("generator"), dict) else {}
        passage_artifacts.append({
            "passage_index": index,
            "seed": passage_seed,
            "run_id": result.get("run_id"),
            "decision": result.get("decision"),
            "artifact_dir": str(batch_dir / f"passage-{index:03d}"),
            "elapsed_seconds": result.get("infrastructure", {}).get("elapsed_seconds", 0.0),
            "question_count": len(generator.get("questions", [])),
            "planned_type_counts": result.get("plan", {}).get("question_type_counts", {}),
            "actual_type_counts": result.get("diagnostics", {}).get("question_type_distribution", {}),
            "deterministic_hard_failures": (
                result.get("checks", {}).get("generator_errors", [])
                + result.get("checks", {}).get("deterministic_errors", [])
            ),
            "empirical_warnings": result.get("checks", {}).get("empirical_warnings", []),
            "invocation_counts": result.get("infrastructure", {}).get("invocation_counts", {}),
        })
    batch_result = {
        "schema_version": "reading-batch-result-v0.2",
        "batch_id": batch_id,
        "output_dir": str(batch_dir),
        "mode": mode,
        "base_seed": base_seed,
        "seed_derivation": "passage_index is one-based; passage_seed = base_seed + passage_index - 1",
        "requested_passage_count": count,
        "completed_passage_count": len(results),
        "parallelism_requested": parallel,
        "parallelism_effective": worker_count,
        "accept_count": accept_count,
        "quarantine_count": quarantine_count,
        "infrastructure_failure_count": infrastructure_failure_count,
        "draft_count": sum(result.get("decision") == "UNVALIDATED_DRAFT" for result in results),
        "total_questions_generated": sum(item["question_count"] for item in passage_artifacts),
        "total_live_invocation_count": sum(result.get("infrastructure", {}).get("live_invocations", 0) for result in results),
        "generator_invocation_count": invocation_counts["generator"],
        "reviewer_invocation_count": invocation_counts["reviewer"],
        "solver_invocation_count": invocation_counts["solver"],
        "leakage_count": sum(len(result.get("checks", {}).get("blind_errors", [])) for result in results),
        "synthetic_fallback_count": sum(bool(result.get("infrastructure", {}).get("synthetic_fallback")) for result in results),
        "elapsed_wall_clock_seconds": round(time.perf_counter() - batch_started, 6),
        "passage_artifacts": passage_artifacts,
        "passage_decisions": [
            {"passage_index": index, "seed": passage_seed, "decision": result.get("decision"), "run_id": result.get("run_id")}
            for index, passage_seed, result in outputs
        ],
        "diagnostics": aggregate_diagnostics(results),
    }
    batch_result_errors = validate_batch_result_contract(batch_result)
    if batch_result_errors:
        raise ValueError("internal batch result failed schema validation: " + "; ".join(batch_result_errors))
    atomic_write_json(batch_dir / "batch_result.json", batch_result)
    return batch_result


def run_reading(
    seed: int | None = None,
    *,
    domain: str | None = None,
    output_dir: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    return ReadingPipeline(provider=provider, model=model).run(seed, domain=domain, output_dir=output_dir)
