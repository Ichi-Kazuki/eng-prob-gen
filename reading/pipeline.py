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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    blind_input,
    blind_input_errors,
    payload_sha256,
    post_blind_comparison,
    solver_input_errors,
    validate_deterministic,
    validate_generator_contract,
    validate_result_contract,
    validate_reviewer_contract,
    validate_solver_contract,
)
from .planner import build_plan


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_AGENT = "toefl-itp-reading-generator"
REVIEWER_AGENT = "toefl-itp-reading-reviewer"
SOLVER_AGENT = "toefl-itp-reading-solver"
AGENT_PATHS = {
    GENERATOR_AGENT: ROOT / ".claude" / "agents" / f"{GENERATOR_AGENT}.md",
    REVIEWER_AGENT: ROOT / ".claude" / "agents" / f"{REVIEWER_AGENT}.md",
    SOLVER_AGENT: ROOT / ".claude" / "agents" / f"{SOLVER_AGENT}.md",
}
DEFAULT_MODEL = os.environ.get("READING_MODEL", "sonnet")
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("READING_TIMEOUT_SECONDS", "300"))
DEFAULT_MAX_BUDGET_USD = os.environ.get("READING_MAX_BUDGET_USD", "0.60")


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
        plan = build_plan(actual_seed, domain)
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


def run_reading(
    seed: int | None = None,
    *,
    domain: str | None = None,
    output_dir: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    return ReadingPipeline(provider=provider, model=model).run(seed, domain=domain, output_dir=output_dir)
