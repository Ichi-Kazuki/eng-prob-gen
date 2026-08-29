"""Fail-closed Reading v0.1 and bounded v0.2 orchestration.

The historical v0.1 path remains a three-call Generator/Reviewer/Solver
sequence. The current v0.2.8 path adds at most one bounded INFERENCE-only
Verifier/Repair stage before the existing blind Reviewer/Solver stages.
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
    apply_choice_permutation_to_question,
    blind_input,
    blind_input_errors,
    canonicalize_generator_output,
    CANONICAL_QUESTION_ORDER_VERSION,
    permute_generator_choices,
    deterministic_diagnostics,
    generator_model_schema_for_plan,
    INFERENCE_VERIFIER_VALID_STATUSES,
    inference_repair_input_errors,
    inference_repair_model_schema_for_item_ids,
    inference_verifier_input,
    inference_verifier_input_errors,
    normalize_target_line_metadata,
    payload_sha256,
    post_blind_comparison,
    solver_input_errors,
    validate_deterministic,
    validate_generator_contract,
    validate_inference_repair_contract,
    validate_inference_verifier_contract,
    validate_result_contract,
    validate_draft_result_contract,
    validate_batch_result_contract,
    validate_reviewer_contract,
    validate_solver_contract,
)
from .diagnostics import aggregate_diagnostics, diagnostics_for_result
from .planner import ALLOWED_DOMAINS, build_plan_v01, build_plan_v02, passage_id_for_seed


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_AGENT = "toefl-itp-reading-generator"
REVIEWER_AGENT = "toefl-itp-reading-reviewer"
SOLVER_AGENT = "toefl-itp-reading-solver"
INFERENCE_VERIFIER_AGENT = "toefl-itp-reading-inference-verifier"
INFERENCE_REPAIR_AGENT = "toefl-itp-reading-inference-repair"
AGENT_PATHS = {
    GENERATOR_AGENT: ROOT / ".claude" / "agents" / f"{GENERATOR_AGENT}.md",
    REVIEWER_AGENT: ROOT / ".claude" / "agents" / f"{REVIEWER_AGENT}.md",
    SOLVER_AGENT: ROOT / ".claude" / "agents" / f"{SOLVER_AGENT}.md",
}
AGENT_PATHS_V02 = {
    GENERATOR_AGENT: ROOT / ".claude" / "agents" / f"{GENERATOR_AGENT}-v0.2.md",
    REVIEWER_AGENT: ROOT / ".claude" / "agents" / f"{REVIEWER_AGENT}-v0.2.md",
    SOLVER_AGENT: ROOT / ".claude" / "agents" / f"{SOLVER_AGENT}-v0.2.md",
    INFERENCE_VERIFIER_AGENT: ROOT / ".claude" / "agents" / f"{INFERENCE_VERIFIER_AGENT}-v0.2.md",
    INFERENCE_REPAIR_AGENT: ROOT / ".claude" / "agents" / f"{INFERENCE_REPAIR_AGENT}-v0.2.md",
}
DEFAULT_MODEL = os.environ.get("READING_MODEL", "sonnet")
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("READING_TIMEOUT_SECONDS", "300"))
DEFAULT_MAX_BUDGET_USD = os.environ.get("READING_MAX_BUDGET_USD", "0.60")
DEFAULT_PARALLELISM = 1
READING_CURRENT_VERSION = "v0.2.8"


READING_DIFFICULTY_GUIDANCE = (
    "If the plan contains difficulty_profile, treat it as a structural calibration target, not a request for arbitrary " 
    "hardness. Keep lexical and syntactic load at moderate academic levels; do not manufacture difficulty with obscure " 
    "terminology, unnecessary sentence embedding, or trick logic. Create difficulty primarily through meaning-preserving " 
    "paraphrase, appropriate evidence integration, genuine supported inference when the planned type calls for it, and " 
    "plausible text-grounded distractors. Distributed evidence should be used only when naturally supported. The profile is " 
    "a provisional structural proxy and never implies TOEFL ITP score equivalence."
)
READING_INFERENCE_GUIDANCE = (
    "For every INFERENCE question, conceptually construct the evidence chain internally before writing the stem or answer choices: "
    "Fact A, Fact B, and an unstated conclusion. Fact A and Fact B must be two distinct textual propositions from the passage. "
    "They may be in the same paragraph, in adjacent sentences, or in separated sentences or ideas. The final keyed option must "
    "express the unstated conclusion, not Fact A or Fact B themselves. The private rationale must identify both facts and demonstrate "
    "why both facts are needed to derive the answer. Keep these labels internal; do not expose Fact A, Fact B, or this construction "
    "process in learner-facing question text. The keyed answer must not be explicitly stated in the passage; this prohibition applies "
    "anywhere in the passage, and it must not be obtainable merely by replacing words in one passage sentence with synonyms or a "
    "close paraphrase. Before finalizing each item, apply an ordinary synonym substitution check; if one sentence still directly "
    "states the answer, rewrite the inference item rather than labeling the paraphrase as INFERENCE. Reject or rewrite a candidate "
    "if its keyed answer is explicitly stated anywhere in the passage; is merely a synonym substitution or close paraphrase of one "
    "passage sentence; one single passage proposition is sufficient to obtain the answer; or the rationale cannot identify at least "
    "two distinct textual facts that jointly support the answer. A valid inference must require at least one reasoning step from the "
    "passage that combines both facts to derive an unstated conclusion. Local inference is allowed when one sentence or adjacent "
    "sentences support a genuinely unstated implication, provided that the support contains two distinct textual propositions rather "
    "than a one-sentence restatement. Two adjacent textual propositions can support a valid local inference. Cross-idea inference is allowed when separated or multiple passage ideas naturally support the "
    "conclusion. Cross-paragraph evidence is allowed when naturally supported, but it is not required; neither are multiple paragraphs, "
    "distant evidence, or cross-idea reasoning. Use the evidence arrangement the passage naturally supports; do not set a target mix "
    "of local, cross-idea, or cross-paragraph items. Do not manufacture unnecessary multi-sentence complexity or force cross-idea reasoning. "
    "Each keyed inference must remain fully supported by the passage and fully entailed by the text, with one unique defensible answer; "
    "it must be uniquely answerable, conservative, and free of outside knowledge; unsupported or ambiguous inference is worse than a "
    "shallow inference. Do not create difficulty through simple negation/reversal or artificial logical tricks. Distractors should be "
    "plausible but not entailed."
)
READING_REVIEWER_INFERENCE_GUIDANCE = (
    "For INFERENCE items only, treat an item as a serious defect if its keyed answer is directly stated or paraphrased from one "
    "passage sentence, or if one textual proposition alone fully supports the keyed answer. A valid inference should require at "
    "least two distinct textual propositions to derive an unstated conclusion. Local evidence may be adjacent within one paragraph; "
    "cross-idea and cross-paragraph evidence are allowed when supported but are not required. Also reject an INFERENCE item when "
    "more than one inference is defensible or when the answer requires unstated outside knowledge. Do not apply this criterion to "
    "other question types."
)
READING_LENGTH_GUIDANCE = (
    "For passage realization, treat target_words as a real writing target, not a loose suggestion. Normally remain close to "
    "target_words, using a soft tolerance on the order of a few dozen words calibrated to observed realization error; this is "
    "not an exact hard count, and slight differences do not by themselves invalidate the passage. Avoid adding extra examples, "
    "background, concluding exposition, or paragraph padding merely to make the passage richer or fill space. Preserve "
    "completeness and naturalness. Never truncate a sentence unnaturally just to hit target_words. Existing validity behavior "
    "is unchanged: below 160 words is hard-invalid, 160-300 words is the empirical preferred band, and above 300 words is an "
    "empirical warning rather than a hard rejection."
)
READING_PARAGRAPH_GUIDANCE = (
    "Separate distinct passage paragraphs with a blank line (`\\n\\n`), and do not treat a single LF as a canonical paragraph "
    "break. Evidence paragraph numbers must correspond exactly to the canonical paragraphs separated by blank lines. Treat "
    "paragraph count as guidance only, not as a new hard quota; do not introduce a fixed paragraph-count quota."
)
READING_VOCABULARY_GUIDANCE = (
    "For VOCABULARY_IN_CONTEXT questions, both ordinary dictionary senses and context-clarified senses are acceptable, but "
    "prefer a word whose actual local sentence disambiguates among multiple plausible general-English senses. Do not require "
    "strong context dependence for every item and do not choose obscure vocabulary merely to increase difficulty. The tested "
    "word must occur naturally in the passage, not look inserted solely for the item. The keyed synonym must match the word's "
    "actual sense in its local sentence. When a target word is polysemous, distinguish between legitimate senses using "
    "grammatical construction, collocation, and local context. Distractors may use other legitimate senses when those senses "
    "are wrong in the sentence. The rationale must explain why the keyed sense fits the local usage."
)
READING_TARGET_GUIDANCE = (
    "For VOCABULARY_IN_CONTEXT and REFERENCE questions, use conventional TOEFL ITP line-based wording such as "
    "The word 'X' in line N is closest in meaning to or The word 'it' in line N refers to. Include private target_text "
    "and 1-based target_line metadata. The trusted display representation uses Unicode NFC, whitespace normalization, "
    "and a fixed 72-character word wrap; never insert line numbers into the passage text."
)
READING_CHOICE_GUIDANCE = (
    "Keep correct options from being systematically longest or most specific; use comparable grammatical form and approximate "
    "information density for distractors without padding for exact character-length equality."
)
READING_TAXONOMY_GUIDANCE = (
    "Treat question_type as the empirical primary planning category and include a secondary subtype for every question. "
    "Use DIRECT_FACTUAL_DETAIL, PARAPHRASED_FACTUAL_DETAIL, or NEGATIVE_EXCEPT_DETAIL for DETAIL; "
    "LOCAL_INFERENCE, CROSS_IDEA_INFERENCE, or RHETORICAL_PURPOSE for INFERENCE; "
    "VOCABULARY_CONTEXT_MEANING for VOCABULARY_IN_CONTEXT; PASSAGE_MAIN_IDEA for MAIN_IDEA; and "
    "ANTECEDENT_REFERENCE for REFERENCE. These subtypes describe item behavior only; do not infer or invent subtype "
    "frequencies that are not measured in the empirical profile. Rhetorical-purpose stems may ask why the author "
    "mentions or discusses something, or the purpose of an example."
)
READING_DISTRACTOR_GUIDANCE = (
    "For every question include private distractor_metadata for A/B/C/D. Mark the keyed choice CORRECT_OPTION and "
    "give each wrong choice one plausible error mechanism plus a short rationale. Use mechanisms such as "
    "TEXT_TRUE_BUT_NOT_ANSWER, WRONG_REFERENT, SCOPE_SHIFT, CAUSE_EFFECT_REVERSAL, OVERGENERALIZATION, "
    "UNDERGENERALIZATION, LEXICAL_SENSE_TRAP, UNSUPPORTED_INFERENCE, NEARBY_DETAIL_CONFUSION, or "
    "CONTRADICTED_BY_PASSAGE. Use only mechanisms that fit the item; do not force a category, use outside knowledge, "
    "or make distractors silly. This metadata is private QA information and must never appear in blind inputs."
)
READING_DOMAIN_GUIDANCE = (
    "Use the selected academic domain as a topic anchor for a self-contained expository passage, with enough definitions, "
    "examples, contrasts, causal links, chronology, and references to support the planned questions. Keep the register like "
    "compact academic textbook prose, avoid unsupported specialist jargon, do not make every passage STEM-oriented, and do "
    "not write controversial current-affairs or opinion commentary."
)


def reading_v02_generator_instruction(*, draft: bool = False) -> str:
    """Return the shared v0.2.8 Generator contract used by production and draft modes."""

    instruction = (
        "Generate one original TOEFL ITP-style Reading Comprehension set. Follow the supplied semantic plan exactly. "
        "The model-facing schema contains one required question collection for each type: detail_questions, "
        "vocabulary_in_context_questions, inference_questions, main_idea_questions, and reference_questions. Create exactly "
        "the requested number in each collection, including an empty array when a quota is zero; together these collections "
        "must exactly match question_type_counts and question_count. ordering of the generated questions is free; do not create "
        "a flat questions array or attempt to reproduce an exact cross-type order. Return JSON only using the supplied v0.2.2 "
        "grouped semantic Generator schema: include the passage, question types, four choices, intended answers, and private "
        "evidence/rationale metadata. Do not include passage_id or question item_id; trusted pipeline code attaches those "
        "deterministic identity fields after generation. "
        f"{READING_DIFFICULTY_GUIDANCE} {READING_INFERENCE_GUIDANCE} {READING_LENGTH_GUIDANCE} "
        f"{READING_PARAGRAPH_GUIDANCE} "
        f"{READING_VOCABULARY_GUIDANCE} {READING_TARGET_GUIDANCE} {READING_CHOICE_GUIDANCE} "
        f"{READING_TAXONOMY_GUIDANCE} {READING_DISTRACTOR_GUIDANCE} {READING_DOMAIN_GUIDANCE} "
        "Process the whole passage set in this one invocation."
    )
    if draft:
        instruction += " This is an UNVALIDATED_DRAFT for development inspection only."
    return instruction + " Never quote, paraphrase, or imitate any official ETS passage or question."


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
        "config_isolation_mode": invocation.config_isolation_mode,
        "mcp_servers_exposed": list(invocation.mcp_servers_exposed),
        "mcp_servers_loaded": list(invocation.mcp_servers_loaded),
        "mcp_configuration_source": invocation.mcp_configuration_source,
        "user_config_loaded": invocation.user_config_loaded,
        "global_codex_config_bypassed": invocation.global_codex_config_bypassed,
        "auth_material_source": invocation.auth_material_source,
        "codex_home_source": invocation.codex_home_source,
        "codex_home_disposable": invocation.codex_home_disposable,
        "codex_home_cleaned": invocation.codex_home_cleaned,
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
        transport_schema_path: Path | None = None,
        transport_output_schema: dict[str, Any] | None = None,
    ) -> InvocationResult:
        if transport_schema_path is not None and transport_output_schema is not None:
            raise ValueError("provide either transport_schema_path or transport_output_schema, not both")
        if transport_schema_path is not None:
            transport_output_schema = json.loads(transport_schema_path.read_text(encoding="utf-8"))
        request = InvocationRequest(
            stage=stage,
            agent_name=agent,
            agent_definition=AGENT_PATHS[agent],
            prompt=prompt,
            input_keys=input_keys,
            formal_output_schema=SCHEMA_PATHS[schema_key],
            transport_output_schema=transport_output_schema,
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

        expected_passage_id = plan["passage_id"]
        raw_generator: Any = None
        generator: Any = None
        envelope_errors: list[str] = []
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
            raw_generator = generator_result.parsed
            atomic_write_json(run_dir / "generator_raw.json", raw_generator)
            try:
                generator = canonicalize_generator_output(raw_generator, plan)
            except (TypeError, ValueError) as exc:
                envelope_errors = [f"generator envelope: {exc}"]
                generator = None
            if generator is not None:
                atomic_write_json(run_dir / "generator_output.json", generator)
            generator_errors = envelope_errors + validate_generator_contract(generator, plan)
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
        transport_schema_path: Path | None = None,
        transport_output_schema: dict[str, Any] | None = None,
    ) -> InvocationResult:
        if transport_schema_path is not None and transport_output_schema is not None:
            raise ValueError("provide either transport_schema_path or transport_output_schema, not both")
        if transport_schema_path is not None:
            transport_output_schema = json.loads(transport_schema_path.read_text(encoding="utf-8"))
        request = InvocationRequest(
            stage=stage,
            agent_name=agent,
            agent_definition=self.agent_paths[agent],
            prompt=prompt,
            input_keys=input_keys,
            formal_output_schema=self.schema_paths[schema_key],
            transport_output_schema=transport_output_schema,
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
                "inference_verifier": counts["reading_inference_verifier"],
                "inference_repair": counts["reading_inference_repair"],
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
        raw_generator: Any = None,
        choice_permutation: dict[str, Any] | None = None,
        target_line_normalization: dict[str, Any] | None = None,
        inference_provenance: dict[str, Any] | None = None,
    ) -> None:
        atomic_write_json(run_dir / "invocations.json", {
            "live_invocations": len(self.invocations),
            "invocations": [_json_safe_invocation(item) for item in self.invocations],
        })
        provenance: dict[str, Any] = {
            "schema_version": "reading-provenance-v0.2",
            "run_id": run_id,
            "created_at": _now_iso(),
            "provider": getattr(self.runtime, "provider", "unknown"),
            "model": self.model or "runtime-default",
            "plan_sha256": payload_sha256(plan),
            "blind_input_sha256": payload_sha256(blind) if blind is not None else None,
            "generator_raw_artifact": "generator_raw.json" if (run_dir / "generator_raw.json").is_file() else None,
            "generator_raw_sha256": payload_sha256(raw_generator) if raw_generator is not None else None,
            "canonical_generator_artifact": "generator.json" if (run_dir / "generator.json").is_file() else None,
            "reading_version": READING_CURRENT_VERSION,
            "choice_permutation": choice_permutation,
            "target_line_normalization": target_line_normalization,
            "canonical_schema_paths": {key: str(path) for key, path in self.schema_paths.items()},
            "invocation_ids": [item.invocation_id for item in self.invocations],
            "answer_bearing_prompt_fields": ["plan"],
            "blind_prompt_fields": ["passage_id", "section", "passage", "questions"],
            "generator_model_transport": {
                "schema_version": "reading-generator-model-v0.2.2",
                "representation": "grouped_question_type_arrays",
                "question_type_fields": {
                    "DETAIL": "detail_questions",
                    "VOCABULARY_IN_CONTEXT": "vocabulary_in_context_questions",
                    "INFERENCE": "inference_questions",
                    "MAIN_IDEA": "main_idea_questions",
                    "REFERENCE": "reference_questions",
                },
                "canonical_ordering_version": CANONICAL_QUESTION_ORDER_VERSION,
                "canonical_validation_still_required": True,
            },
        }
        if inference_provenance is not None:
            provenance.update(inference_provenance)
        atomic_write_json(run_dir / "provenance" / "provenance.json", provenance)

    @staticmethod
    def _inference_gate_evaluation(
        generator: dict[str, Any],
        verifier: Any,
        verifier_input: dict[str, Any],
        verifier_errors: list[str],
    ) -> tuple[list[str], dict[str, list[str]], list[dict[str, Any]]]:
        """Privately compare a blind verifier with the trusted Generator key."""

        generator_by_id = {
            question["item_id"]: question
            for question in generator.get("questions", [])
            if isinstance(question, dict) and question.get("question_type") == "INFERENCE"
        }
        verifier_by_id = {
            question.get("item_id"): question
            for question in verifier.get("questions", [])
            if isinstance(question, dict)
        } if isinstance(verifier, dict) else {}
        flagged: list[str] = []
        reasons_by_id: dict[str, list[str]] = {}
        results: list[dict[str, Any]] = []
        contract_reason = "inference verifier contract error: " + "; ".join(verifier_errors)
        for input_question in verifier_input.get("questions", []):
            item_id = input_question.get("item_id")
            trusted_question = generator_by_id.get(item_id)
            verifier_question = verifier_by_id.get(item_id)
            reasons: list[str] = []
            if verifier_errors:
                reasons.append(contract_reason)
            if trusted_question is None:
                reasons.append("system could not locate the canonical inference item")
            if not isinstance(verifier_question, dict):
                reasons.append("inference verifier did not return a judgment for this item")
                status = None
                best_answer = None
            else:
                status = verifier_question.get("status")
                best_answer = verifier_question.get("best_answer")
                if status not in INFERENCE_VERIFIER_VALID_STATUSES:
                    reasons.append(f"verifier status {status!r} is not a valid inference status")
                if best_answer not in {"A", "B", "C", "D"}:
                    reasons.append(f"verifier best_answer {best_answer!r} is not a unique answer choice")
                elif isinstance(trusted_question, dict) and best_answer != trusted_question.get("correct_answer"):
                    reasons.append("verifier best_answer disagrees with the trusted Generator answer")
            passed = not reasons
            if not passed and isinstance(item_id, str):
                flagged.append(item_id)
                reasons_by_id[item_id] = reasons
            results.append({
                "item_id": item_id,
                "status": status,
                "best_answer": best_answer,
                "pass": passed,
                "reasons": reasons,
            })
        return flagged, reasons_by_id, results

    @staticmethod
    def _build_inference_repair_input(
        generator: dict[str, Any],
        verifier: Any,
        flagged_item_ids: list[str],
        reasons_by_id: dict[str, list[str]],
    ) -> dict[str, Any]:
        generator_by_id = {
            question["item_id"]: question
            for question in generator["questions"]
            if isinstance(question, dict)
        }
        verifier_by_id = {
            question.get("item_id"): question
            for question in verifier.get("questions", [])
            if isinstance(question, dict)
        } if isinstance(verifier, dict) else {}
        items: list[dict[str, Any]] = []
        for item_id in flagged_item_ids:
            question = generator_by_id[item_id]
            judgment = verifier_by_id.get(item_id, {})
            supporting = judgment.get("supporting_propositions", [])
            if not isinstance(supporting, list) or not all(isinstance(value, str) for value in supporting):
                supporting = []
            best_answer = judgment.get("best_answer")
            if best_answer not in {"A", "B", "C", "D", "AMBIGUOUS", "NONE"}:
                best_answer = "NONE"
            conclusion = judgment.get("conclusion")
            if not isinstance(conclusion, str) or not conclusion.strip():
                conclusion = "The verifier did not provide a usable conclusion."
            comment = judgment.get("comment")
            if not isinstance(comment, str) or not comment.strip():
                comment = "The verifier did not provide a usable comment."
            status = judgment.get("status")
            if status not in {
                "VALID_SHALLOW_INFERENCE",
                "VALID_GENUINE_INFERENCE",
                "VALID_CROSS_IDEA_INFERENCE",
                "INVALID_DIRECT_RESTATEMENT",
                "INVALID_UNSUPPORTED",
                "INVALID_AMBIGUOUS",
            }:
                status = "INVALID_UNSUPPORTED"
            items.append({
                "item_id": item_id,
                "stem": question["stem"],
                "choices": copy.deepcopy(question["choices"]),
                "verifier_status": status,
                "verifier_best_answer": best_answer,
                "supporting_propositions": supporting,
                "conclusion": conclusion,
                "verifier_comment": comment,
                "defect_reasons": reasons_by_id.get(item_id, ["inference verifier failed this item"]),
            })
        return {"passage": generator["passage"], "items": items}

    def run(
        self,
        seed: int | None = None,
        *,
        domain: str | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Run one current Reading set with one bounded inference repair at most."""

        started = time.perf_counter()
        self.invocations = []
        self.runtime_failures = []
        actual_seed = secrets.randbits(32) if seed is None else seed
        plan = build_plan_v02(actual_seed, domain)
        run_id = f"reading-v02-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
        run_dir = (output_dir or self.artifact_root / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "plan.json", plan)

        expected_passage_id = plan["passage_id"]
        raw_generator: Any = None
        generator: Any = None
        pre_repair_generator: Any = None
        reviewer: Any = None
        solver: Any = None
        inference_verifier: Any = None
        inference_repair: Any = None
        inference_reverify: Any = None
        blind: dict[str, Any] | None = None
        initial_verifier_input: dict[str, Any] | None = None
        repair_input: dict[str, Any] | None = None
        reverify_input: dict[str, Any] | None = None
        envelope_errors: list[str] = []
        generator_errors: list[str] = []
        deterministic_errors: list[str] = []
        empirical_warnings: list[str] = []
        deterministic_classification = "HARD_VALIDITY"
        choice_permutation: dict[str, Any] | None = None
        target_line_normalization: dict[str, Any] | None = None
        final_target_line_normalization: dict[str, Any] | None = None
        reviewer_errors: list[str] = []
        solver_errors: list[str] = []
        post_blind_metadata_errors: list[str] = []
        blind_errors: list[str] = []
        agreements: list[dict[str, Any]] = []
        agreement_errors: list[str] = []
        inference_verifier_errors: list[str] = []
        inference_repair_errors: list[str] = []
        inference_gate_required = False
        inference_gate_pass = False
        inference_repair_attempted = False
        inference_repair_succeeded = False
        flagged_item_ids: list[str] = []
        repaired_item_ids: list[str] = []
        repair_reasons: dict[str, list[str]] = {}
        initial_gate_results: list[dict[str, Any]] = []
        reverify_gate_results: list[dict[str, Any]] = []

        try:
            generator_result = self._invoke(
                stage="reading_generator",
                agent=GENERATOR_AGENT,
                prompt=self._prompt(
                    reading_v02_generator_instruction(),
                    {key: value for key, value in plan.items() if key not in {"passage_id", "plan_id", "question_plan"}},
                ),
                input_keys=("plan",),
                schema_key="generator",
                output_dir=run_dir,
                isolate_workspace=False,
                transport_output_schema=generator_model_schema_for_plan(plan),
            )
            raw_generator = generator_result.parsed
            atomic_write_json(run_dir / "generator_raw.json", raw_generator)
            try:
                permuted_raw, choice_permutation = permute_generator_choices(raw_generator, plan)
                generator = canonicalize_generator_output(permuted_raw, plan)
                generator, target_line_normalization = normalize_target_line_metadata(generator)
            except (TypeError, ValueError) as exc:
                envelope_errors = [f"generator envelope: {exc}"]
                generator = None
                choice_permutation = None
            if generator is not None:
                atomic_write_json(run_dir / "generator.json", generator)
            generator_errors = envelope_errors + validate_generator_contract(generator, plan, self.schema_paths)
            validation = deterministic_diagnostics(generator, plan, self.schema_paths)
            empirical_warnings = validation["empirical_warnings"]
            deterministic_classification = validation["classification"]
            if not generator_errors:
                deterministic_errors = validation["hard_failures"]
                post_blind_metadata_errors = validate_generator_contract(generator, plan, self.schema_paths)

            if generator is not None and not generator_errors and not deterministic_errors:
                inference_items = [
                    question for question in generator["questions"]
                    if question.get("question_type") == "INFERENCE"
                ]
                inference_gate_required = bool(inference_items)
                if not inference_items:
                    inference_gate_pass = True
                else:
                    inference_ids = [question["item_id"] for question in inference_items]
                    initial_verifier_input = inference_verifier_input(generator)
                    verifier_input_errors = inference_verifier_input_errors(
                        generator,
                        initial_verifier_input,
                        self.schema_paths,
                        expected_item_ids=set(inference_ids),
                    )
                    atomic_write_json(run_dir / "inference_verifier_input.json", initial_verifier_input)
                    if verifier_input_errors:
                        inference_verifier_errors.extend(verifier_input_errors)
                        flagged_item_ids = list(inference_ids)
                        repair_reasons = {
                            item_id: list(verifier_input_errors)
                            for item_id in inference_ids
                        }
                    else:
                        verifier_result = self._invoke(
                            stage="reading_inference_verifier",
                            agent=INFERENCE_VERIFIER_AGENT,
                            prompt=self._prompt(
                                "Independently verify only the supplied INFERENCE items. Use only INPUT_JSON. "
                                "Solve each item, classify direct restatement, supported inference, unsupportedness, "
                                "or ambiguity, and return one judgment per item. Do not request or infer hidden "
                                "Generator metadata. Return JSON only.",
                                initial_verifier_input,
                            ),
                            input_keys=("passage_id", "section", "passage", "questions"),
                            schema_key="inference_verifier",
                            output_dir=run_dir,
                            isolate_workspace=True,
                        )
                        inference_verifier = verifier_result.parsed
                        atomic_write_json(run_dir / "inference_verifier.json", inference_verifier)
                        inference_verifier_errors = validate_inference_verifier_contract(
                            inference_verifier,
                            initial_verifier_input,
                            self.schema_paths,
                        )
                        flagged_item_ids, repair_reasons, initial_gate_results = self._inference_gate_evaluation(
                            generator,
                            inference_verifier,
                            initial_verifier_input,
                            inference_verifier_errors,
                        )
                    if not flagged_item_ids and not inference_verifier_errors:
                        inference_gate_pass = True
                    else:
                        inference_repair_attempted = True
                        pre_repair_generator = copy.deepcopy(generator)
                        atomic_write_json(run_dir / "generator_pre_repair.json", pre_repair_generator)
                        repair_input = self._build_inference_repair_input(
                            generator,
                            inference_verifier,
                            flagged_item_ids,
                            repair_reasons,
                        )
                        repair_input_errors = inference_repair_input_errors(repair_input, self.schema_paths)
                        atomic_write_json(run_dir / "inference_repair_input.json", repair_input)
                        if repair_input_errors:
                            inference_repair_errors.extend(repair_input_errors)
                        else:
                            repair_result = self._invoke(
                                stage="reading_inference_repair",
                                agent=INFERENCE_REPAIR_AGENT,
                                prompt=self._prompt(
                                    "Repair every flagged INFERENCE item in INPUT_JSON in one response. Use only the "
                                    "passage, visible item content, blind Verifier feedback, and system-derived defect "
                                    "reasons. Return exactly one replacement per requested item_id. Do not use the "
                                    "original Generator key or rationale. Return fresh semantic A/B/C/D choices and a "
                                    "fresh raw answer label; the trusted pipeline applies the existing answer-position "
                                    "mapping. Return JSON only.",
                                    repair_input,
                                ),
                                input_keys=("passage", "items"),
                                schema_key="inference_repair",
                                output_dir=run_dir,
                                isolate_workspace=True,
                                transport_output_schema=inference_repair_model_schema_for_item_ids(flagged_item_ids),
                            )
                            inference_repair = repair_result.parsed
                            atomic_write_json(run_dir / "inference_repair.json", inference_repair)
                            inference_repair_errors = validate_inference_repair_contract(
                                inference_repair,
                                flagged_item_ids,
                                self.schema_paths,
                            )
                            if not inference_repair_errors:
                                records_by_id = {
                                    record["item_id"]: record
                                    for record in choice_permutation["questions"]
                                } if isinstance(choice_permutation, dict) else {}
                                replacement_by_id = {
                                    replacement["item_id"]: replacement
                                    for replacement in inference_repair["replacements"]
                                }
                                candidate = copy.deepcopy(generator)
                                slots_by_id = {
                                    question["item_id"]: index
                                    for index, question in enumerate(candidate["questions"])
                                }
                                merge_errors: list[str] = []
                                for item_id in flagged_item_ids:
                                    record = records_by_id.get(item_id)
                                    replacement = replacement_by_id.get(item_id)
                                    slot = slots_by_id.get(item_id)
                                    if record is None or replacement is None or slot is None:
                                        merge_errors.append(f"could not merge repaired item {item_id}")
                                        continue
                                    try:
                                        remapped = apply_choice_permutation_to_question(
                                            replacement,
                                            original_to_canonical=record["original_to_canonical"],
                                            canonical_to_original=record["canonical_to_original"],
                                        )
                                    except (TypeError, ValueError, KeyError) as exc:
                                        merge_errors.append(f"could not remap repaired item {item_id}: {exc}")
                                        continue
                                    if remapped.get("item_id") != item_id or remapped.get("question_type") != "INFERENCE":
                                        merge_errors.append(f"repaired item {item_id} changed trusted identity or type")
                                        continue
                                    candidate["questions"][slot] = remapped
                                if merge_errors:
                                    inference_repair_errors.extend(merge_errors)
                                else:
                                    candidate, final_target_line_normalization = normalize_target_line_metadata(candidate)
                                    generator = candidate
                                    repaired_item_ids = list(flagged_item_ids)
                                    atomic_write_json(run_dir / "generator.json", generator)
                                    final_generator_errors = validate_generator_contract(generator, plan, self.schema_paths)
                                    final_validation = deterministic_diagnostics(generator, plan, self.schema_paths)
                                    generator_errors = final_generator_errors
                                    deterministic_errors = final_validation["hard_failures"]
                                    empirical_warnings = final_validation["empirical_warnings"]
                                    deterministic_classification = final_validation["classification"]
                                    if generator_errors or deterministic_errors:
                                        inference_repair_errors.extend(
                                            ["final repaired Generator validation failed", *generator_errors, *deterministic_errors]
                                        )
                                    else:
                                        reverify_input = inference_verifier_input(
                                            generator,
                                            item_ids=set(repaired_item_ids),
                                        )
                                        reverify_input_errors = inference_verifier_input_errors(
                                            generator,
                                            reverify_input,
                                            self.schema_paths,
                                            expected_item_ids=set(repaired_item_ids),
                                        )
                                        atomic_write_json(run_dir / "inference_reverify_input.json", reverify_input)
                                        if reverify_input_errors:
                                            inference_verifier_errors.extend(reverify_input_errors)
                                            inference_repair_errors.extend(reverify_input_errors)
                                        else:
                                            reverify_result = self._invoke(
                                                stage="reading_inference_verifier",
                                                agent=INFERENCE_VERIFIER_AGENT,
                                                prompt=self._prompt(
                                                    "Re-verify only the repaired INFERENCE items in INPUT_JSON using "
                                                    "the same blind inference-verification rules. Return one judgment "
                                                    "per item and no set-level result. Do not request or infer hidden "
                                                    "Generator metadata. Return JSON only.",
                                                    reverify_input,
                                                ),
                                                input_keys=("passage_id", "section", "passage", "questions"),
                                                schema_key="inference_verifier",
                                                output_dir=run_dir,
                                                isolate_workspace=True,
                                            )
                                            inference_reverify = reverify_result.parsed
                                            atomic_write_json(run_dir / "inference_reverify.json", inference_reverify)
                                            reverify_errors = validate_inference_verifier_contract(
                                                inference_reverify,
                                                reverify_input,
                                                self.schema_paths,
                                            )
                                            inference_verifier_errors.extend(reverify_errors)
                                            reverify_flagged, _reverify_reasons, reverify_gate_results = self._inference_gate_evaluation(
                                                generator,
                                                inference_reverify,
                                                reverify_input,
                                                reverify_errors,
                                            )
                                            inference_gate_pass = not reverify_errors and not reverify_flagged
                                            inference_repair_succeeded = inference_gate_pass

        except RuntimeInvocationError:
            # Runtime failures are recorded by _invoke and remain distinct from
            # quality quarantine; no later stage is invoked after one occurs.
            pass

        for failure in self.runtime_failures:
            stage = failure.get("stage")
            detail = str(failure.get("detail", "runtime invocation failed"))
            if stage == "reading_inference_verifier":
                inference_verifier_errors.append(detail)
            elif stage == "reading_inference_repair":
                inference_repair_errors.append(detail)

        if generator is not None:
            post_blind_metadata_errors = validate_generator_contract(generator, plan, self.schema_paths)
        if blind is None and generator is not None and not generator_errors and not deterministic_errors and inference_gate_pass:
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

        if blind is not None and not blind_errors and not self.runtime_failures:
            try:
                reviewer_result = self._invoke(
                    stage="reading_reviewer",
                    agent=REVIEWER_AGENT,
                    prompt=self._prompt(
                        f"Independently audit this entire Reading set as a blind Reviewer. Use only the visible passage, stems, and A/B/C/D choices in INPUT_JSON. Process every question in this one invocation. For every question choose the best answer, or AMBIGUOUS/NONE, and assess uniqueness, distractors, answerability, wording, and serious defects. {READING_REVIEWER_INFERENCE_GUIDANCE} For VOCABULARY_IN_CONTEXT, judge the actual local sense rather than a dictionary-only synonym. Check author-purpose questions for a passage-supported rhetorical role and check distractors for plausible text-grounded error mechanisms, parallel grammar, and comparable information density. Return JSON only. Do not request or infer hidden Generator metadata.",
                        blind,
                    ),
                    input_keys=("passage_id", "section", "passage", "questions"),
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
                        "Solve this entire Reading set independently as a test-taker. Use only INPUT_JSON and process every visible question in this one invocation. Return exactly one answer for each question: A, B, C, D, AMBIGUOUS, or NONE, with confidence and a concise reason. Treat inference questions as passage-supported reasoning only; use AMBIGUOUS or NONE when outside knowledge is required or two choices are equally defensible. For vocabulary questions use the tested word's local context. Do not use or request Generator or Reviewer metadata. Return JSON only.",
                        blind,
                    ),
                    input_keys=("passage_id", "section", "passage", "questions"),
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
                pass

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
            "inference_gate_required": inference_gate_required,
            "inference_gate_pass": inference_gate_pass,
            "inference_repair_attempted": inference_repair_attempted,
            "inference_repair_succeeded": inference_repair_succeeded,
            "inference_verifier_errors": inference_verifier_errors,
            "inference_repair_errors": inference_repair_errors,
            "inference_gate_results": {
                "initial": initial_gate_results,
                "reverify": reverify_gate_results,
            },
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
                "inference_gate_pass",
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
        inference_provenance = {
            "generator_pre_repair_artifact": "generator_pre_repair.json" if pre_repair_generator is not None else None,
            "generator_pre_repair_sha256": payload_sha256(pre_repair_generator) if pre_repair_generator is not None else None,
            "final_generator_sha256": payload_sha256(generator) if isinstance(generator, dict) else None,
            "inference_verifier_input_artifact": "inference_verifier_input.json" if initial_verifier_input is not None else None,
            "inference_verifier_input_sha256": payload_sha256(initial_verifier_input) if initial_verifier_input is not None else None,
            "inference_verifier_output_artifact": "inference_verifier.json" if inference_verifier is not None else None,
            "inference_verifier_output_sha256": payload_sha256(inference_verifier) if inference_verifier is not None else None,
            "flagged_inference_item_ids": flagged_item_ids,
            "deterministic_repair_reasons": repair_reasons,
            "repair_attempt_count": 1 if inference_repair_attempted else 0,
            "repaired_item_ids": repaired_item_ids,
            "inference_repair_input_artifact": "inference_repair_input.json" if repair_input is not None else None,
            "inference_repair_input_sha256": payload_sha256(repair_input) if repair_input is not None else None,
            "inference_repair_output_artifact": "inference_repair.json" if inference_repair is not None else None,
            "inference_repair_output_sha256": payload_sha256(inference_repair) if inference_repair is not None else None,
            "inference_reverify_input_artifact": "inference_reverify_input.json" if reverify_input is not None else None,
            "inference_reverify_input_sha256": payload_sha256(reverify_input) if reverify_input is not None else None,
            "inference_reverify_output_artifact": "inference_reverify.json" if inference_reverify is not None else None,
            "inference_reverify_output_sha256": payload_sha256(inference_reverify) if inference_reverify is not None else None,
            "final_specialized_inference_gate_result": inference_gate_pass,
            "final_blind_input_sha256": payload_sha256(blind) if blind is not None else None,
            "final_target_line_normalization": final_target_line_normalization,
            "initial_inference_gate_results": initial_gate_results,
            "reverify_inference_gate_results": reverify_gate_results,
        }
        self._write_invocations_and_provenance(
            run_dir,
            run_id,
            plan,
            blind,
            raw_generator,
            choice_permutation,
            target_line_normalization,
            inference_provenance,
        )
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
        raw_generator: Any = None
        generator: Any = None
        envelope_errors: list[str] = []
        generator_errors: list[str] = []
        deterministic_errors: list[str] = []
        empirical_warnings: list[str] = []
        deterministic_classification = "HARD_VALIDITY"
        choice_permutation: dict[str, Any] | None = None
        target_line_normalization: dict[str, Any] | None = None
        try:
            generator_result = self._invoke(
                stage="reading_generator",
                agent=GENERATOR_AGENT,
                prompt=self._prompt(
                    reading_v02_generator_instruction(draft=True),
                    {key: value for key, value in plan.items() if key not in {"passage_id", "plan_id", "question_plan"}},
                ),
                input_keys=("plan",),
                schema_key="generator",
                output_dir=run_dir,
                isolate_workspace=False,
                transport_output_schema=generator_model_schema_for_plan(plan),
            )
            raw_generator = generator_result.parsed
            atomic_write_json(run_dir / "generator_raw.json", raw_generator)
            try:
                permuted_raw, choice_permutation = permute_generator_choices(raw_generator, plan)
                generator = canonicalize_generator_output(permuted_raw, plan)
                generator, target_line_normalization = normalize_target_line_metadata(generator)
            except (TypeError, ValueError) as exc:
                envelope_errors = [f"generator envelope: {exc}"]
                generator = None
                choice_permutation = None
            if generator is not None:
                atomic_write_json(run_dir / "generator.json", generator)
            generator_errors = envelope_errors + validate_generator_contract(generator, plan, self.schema_paths)
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
            "passage_id": passage_id_for_seed(actual_seed),
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
        self._write_invocations_and_provenance(
            run_dir,
            run_id,
            plan,
            None,
            raw_generator,
            choice_permutation,
            target_line_normalization,
        )
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
    result: dict[str, Any] = {
        "schema_version": "reading-result-v0.2",
        "run_id": run_id,
        "decision": "INFRASTRUCTURE_FAILURE",
        "passage_id": passage_id_for_seed(seed),
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
            "inference_gate_required": False,
            "inference_gate_pass": False,
            "inference_repair_attempted": False,
            "inference_repair_succeeded": False,
            "inference_verifier_errors": [],
            "inference_repair_errors": [],
        },
        "infrastructure": {
            "live_invocations": 0,
            "invocation_counts": {
                "generator": 0,
                "reviewer": 0,
                "solver": 0,
                "inference_verifier": 0,
                "inference_repair": 0,
            },
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
    if domain is not None and domain not in ALLOWED_DOMAINS:
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
        "inference_verifier": sum(result.get("infrastructure", {}).get("invocation_counts", {}).get("inference_verifier", 0) for result in results),
        "inference_repair": sum(result.get("infrastructure", {}).get("invocation_counts", {}).get("inference_repair", 0) for result in results),
    }
    passage_artifacts = []
    for (index, passage_seed, result) in outputs:
        generator_value = result.get("generator")
        generator = generator_value if isinstance(generator_value, dict) else {}
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
        "inference_verifier_invocation_count": invocation_counts["inference_verifier"],
        "inference_repair_invocation_count": invocation_counts["inference_repair"],
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
