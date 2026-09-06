"""WE grammar evidence producer.

This module is the only implementation of the external grammar-evidence
sidecar required by the frozen WE v2.1.3 production validator
(``agents/toefl_itp_we_generator_v2/scripts/validate_output.py``). It does
not reimplement, weaken, or bypass that validator, its mutation-safety
module, or the WE Generator/Reviewer/Solver contracts; it only produces the
one artifact those frozen components already expect: a per-item independent
grammar judgment, deterministically bound to the exact item content and
carrying immutable, wrapper-attached provenance.

Pipeline shape::

    Generator output
      -> deterministic audit-input projection (this module)
      -> one independent grammar-auditor model invocation per item
      -> strict model-output contract (schemas/grammar_audit_output.schema.json)
      -> deterministic content-hash binding (reusing the WE validator's own hash)
      -> deterministic provenance attachment
      -> grammar_evidence.schema.json validation
      -> the existing WE v2.1.3 production validator (subprocess, no model call)
      -> PASS / QUARANTINE / INFRASTRUCTURE_FAILURE

There are no retries, no repair, and no evidence synthesis from any other
stage's output: every invariant not confidently established by the
independent auditor is treated as unresolved, and any single item failure
quarantines the run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from runtime.adapters import (
    AgentRuntime,
    ClaudeRuntime,
    CodexRuntime,
    InvocationRequest,
    InvocationResult,
    RuntimeInvocationError,
)
from shared.json_io import atomic_write_json
from shared.schema_validation import load_schema, schema_errors

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent

STAGE = "we_grammar_evidence"
AGENT_NAME = "we-grammar-auditor-v1"
EVIDENCE_PRODUCER = "we-grammar-auditor"
EVIDENCE_PRODUCER_VERSION = "v1"
EVIDENCE_METHOD = "independent_model_grammar_audit"

PROMPT_PATH = PACKAGE_DIR / "prompts" / "grammar_auditor.md"
AUDIT_OUTPUT_SCHEMA_PATH = PACKAGE_DIR / "schemas" / "grammar_audit_output.schema.json"

GENERATOR_VALIDATOR_PATH = (
    ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts" / "validate_output.py"
)
EVIDENCE_SCHEMA_PATH = (
    ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "grammar_evidence.schema.json"
)

STRONG_INVARIANT_NAMES = (
    "clean_sentence_grammatical",
    "mutated_sentence_ungrammatical",
    "exactly_one_grammatical_defect",
    "declared_marked_span_contains_defect",
    "minimal_repair_restores_grammaticality",
    "no_plausible_alternate_parse",
    "defect_is_grammatical_not_semantic",
)

AUDIT_PROJECTION_KEYS = (
    "item_id",
    "sentence",
    "marked_parts",
    "declared_error_label",
    "clean_form",
    "error_form",
    "minimal_correction",
    "mutation_type",
    "primary_target",
    "tested_error_type",
    "error_explanation",
)

# Invocation-layer failures that are infrastructure/transport problems, not a
# grammar judgment. Anything not in this set (parsing failures, schema
# rejections, and unrecognized categories) is treated as a semantic/contract
# failure so it is never silently downgraded to a retryable infrastructure
# excuse.
INFRASTRUCTURE_ERROR_CATEGORIES = frozenset(
    {
        "infrastructure",
        "CLI",
        "auth",
        "HARNESS_TIMEOUT",
        "CODEX_AUTH_ERROR",
        "CODEX_NETWORK_ERROR",
        "CODEX_PROCESS_ERROR",
    }
)


class GrammarEvidenceError(RuntimeError):
    """A producer-side content/configuration failure (not a model failure)."""


_VALIDATE_OUTPUT_MODULE: Any | None = None


def _validate_output_module() -> Any:
    """Load the frozen WE v2.1.3 validator module for its hash function only.

    ``validate_output.py`` imports sibling scripts (``validate_format``,
    ``mutation_safety``) as top-level modules, which only resolves once its
    own directory is on ``sys.path``. This loader is the single place that
    dependency is set up so the exact authoritative hash implementation is
    reused rather than re-derived.
    """
    global _VALIDATE_OUTPUT_MODULE
    if _VALIDATE_OUTPUT_MODULE is None:
        scripts_dir = str(GENERATOR_VALIDATOR_PATH.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        spec = importlib.util.spec_from_file_location(
            "we_evidence_validate_output", GENERATOR_VALIDATOR_PATH
        )
        if spec is None or spec.loader is None:
            raise GrammarEvidenceError(
                f"cannot load WE production validator module {GENERATOR_VALIDATOR_PATH}"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATE_OUTPUT_MODULE = module
    return _VALIDATE_OUTPUT_MODULE


def content_hash_for_item(item: Mapping[str, Any]) -> str:
    """Return the exact item-binding hash defined by the WE validator.

    This delegates to
    ``validate_output.grammar_evidence_content_hash`` verbatim; it is never
    reimplemented here.
    """
    return str(_validate_output_module().grammar_evidence_content_hash(item))


def _safe_filename(item_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]", "_", item_id)
    return normalized or "item"


def load_generator_items(path: Path) -> list[dict[str, Any]]:
    """Load exactly the caller-supplied Generator output file.

    This never scans ``runs/`` or infers a run; the caller always supplies
    the explicit Generator formal-output path. Shape acceptance mirrors the
    existing WE validator's own loader (an items array, a bare array, or a
    single item object) rather than inventing another WE item parser.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GrammarEvidenceError(f"cannot read Generator output {path}: {exc}") from exc
    if isinstance(document, dict) and isinstance(document.get("items"), list):
        items = document["items"]
    elif isinstance(document, list):
        items = document
    elif isinstance(document, dict):
        items = [document]
    else:
        raise GrammarEvidenceError(
            "Generator output must be an item array or an object with an items array"
        )
    if not all(isinstance(item, dict) for item in items):
        raise GrammarEvidenceError("every Generator output item must be a JSON object")
    return items


def projection_errors(item: Any) -> list[str]:
    """Return why one item cannot be projected into an audit payload.

    Only the deterministic field-presence/type/consistency checks needed to
    construct a safe audit payload live here; this intentionally does not
    duplicate the full mutation-safety validator.
    """
    errors: list[str] = []
    if not isinstance(item, Mapping):
        return ["item must be an object"]

    item_id = item.get("item_id")
    if not isinstance(item_id, str) or not item_id.strip():
        errors.append("item_id must be a nonempty string")

    sentence = item.get("sentence")
    if not isinstance(sentence, str) or not sentence.strip():
        errors.append("sentence must be a nonempty string")

    marked_parts = item.get("marked_parts")
    if (
        not isinstance(marked_parts, Mapping)
        or set(marked_parts) != {"A", "B", "C", "D"}
        or not all(isinstance(value, str) and value.strip() for value in marked_parts.values())
    ):
        errors.append("marked_parts must contain nonempty A/B/C/D strings")

    correct_answer = item.get("correct_answer")
    if correct_answer not in {"A", "B", "C", "D"}:
        errors.append("correct_answer must be one of A/B/C/D")

    qa = item.get("qa_metadata")
    if not isinstance(qa, Mapping):
        errors.append("qa_metadata must be an object")
        qa = {}

    clean_form = qa.get("clean_form")
    if not isinstance(clean_form, str) or not clean_form.strip():
        errors.append("qa_metadata.clean_form must be a nonempty string")

    error_form = qa.get("error_form")
    if not isinstance(error_form, str) or not error_form.strip():
        errors.append("qa_metadata.error_form must be a nonempty string")

    mutation_type = qa.get("mutation_type")
    if not isinstance(mutation_type, str) or not mutation_type.strip():
        errors.append("qa_metadata.mutation_type must be a nonempty string")

    minimal_correction = qa.get("minimal_correction", item.get("minimal_correction"))
    if not isinstance(minimal_correction, str) or not minimal_correction.strip():
        errors.append("minimal_correction must be a nonempty string")

    primary_target = item.get("primary_target")
    if not isinstance(primary_target, str) or not primary_target.strip():
        errors.append("primary_target must be a nonempty string")

    tested_error_type = item.get("tested_error_type")
    if not isinstance(tested_error_type, str) or not tested_error_type.strip():
        errors.append("tested_error_type must be a nonempty string")

    error_explanation = item.get("error_explanation", item.get("answer_explanation"))
    if not isinstance(error_explanation, str) or not error_explanation.strip():
        errors.append("error_explanation must be a nonempty string")

    if isinstance(sentence, str) and isinstance(error_form, str) and sentence != error_form:
        errors.append("sentence must exactly match qa_metadata.error_form")

    return errors


def build_audit_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    """Project one Generator item onto the auditor's explicit allowlist.

    Only the fields required to audit the declared mutation are included.
    Reviewer/Solver output, prior quality flags (``grammar_check_status``),
    ``format_metadata``, and provenance are never on the allowlist, so they
    cannot enter the payload regardless of what the source item contains.
    """
    errors = projection_errors(item)
    if errors:
        item_id = item.get("item_id", "?") if isinstance(item, Mapping) else "?"
        raise GrammarEvidenceError(
            f"item {item_id!r} failed audit input projection: " + "; ".join(errors)
        )

    qa = item["qa_metadata"]
    minimal_correction = qa.get("minimal_correction", item.get("minimal_correction"))
    error_explanation = item.get("error_explanation", item.get("answer_explanation"))
    payload = {
        "item_id": item["item_id"],
        "sentence": item["sentence"],
        "marked_parts": dict(item["marked_parts"]),
        "declared_error_label": item["correct_answer"],
        "clean_form": qa["clean_form"],
        "error_form": qa["error_form"],
        "minimal_correction": minimal_correction,
        "mutation_type": qa["mutation_type"],
        "primary_target": item["primary_target"],
        "tested_error_type": item["tested_error_type"],
        "error_explanation": error_explanation,
    }
    assert set(payload) == set(AUDIT_PROJECTION_KEYS)
    return payload


_AUDIT_OUTPUT_SCHEMA: dict[str, Any] | None = None


def audit_output_schema() -> dict[str, Any]:
    global _AUDIT_OUTPUT_SCHEMA
    if _AUDIT_OUTPUT_SCHEMA is None:
        _AUDIT_OUTPUT_SCHEMA = load_schema(AUDIT_OUTPUT_SCHEMA_PATH)
    return _AUDIT_OUTPUT_SCHEMA


def audit_output_errors(raw: Any, expected_item_id: str) -> list[str]:
    """Validate one raw auditor response against the strict model contract."""
    errors = schema_errors(raw, audit_output_schema())
    if errors:
        return errors
    if raw.get("item_id") != expected_item_id:
        return [
            f"auditor item_id {raw.get('item_id')!r} does not match the audited item "
            f"{expected_item_id!r}"
        ]
    return []


def configure_runtime(*, provider: str | None = None, model: str | None = None) -> AgentRuntime:
    """Select a provider-neutral runtime without a Structure-specific factory."""
    requested = (
        provider
        or os.environ.get("WE_EVIDENCE_RUNTIME")
        or os.environ.get("WE_E2E_RUNTIME")
        or "claude"
    ).strip().lower()
    if requested in {"codex", "codex-cli"}:
        return CodexRuntime(model=model or os.environ.get("WE_EVIDENCE_CODEX_MODEL"))
    if requested in {"claude", "claude-code", "claude-code-cli"}:
        return ClaudeRuntime(model=model or os.environ.get("WE_EVIDENCE_MODEL") or "sonnet")
    raise GrammarEvidenceError(f"unsupported WE evidence runtime provider: {requested!r}")


def audit_prompt(payload: Mapping[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"""INDEPENDENT GRAMMAR AUDIT INVOCATION.

Follow the authoritative grammar-auditor instruction supplied by the
runtime. Judge only the declared mutation in the JSON object below. Do not
read files, inspect other artifacts, or assume this item already passed any
prior review. Return one JSON object only, matching the supplied grammar
audit output schema; do not use markdown or an items wrapper.

AUDIT INPUT:
{payload_json}
"""


def audit_system_directive() -> str:
    return (
        "The final response for this invocation MUST be exactly one JSON object "
        "matching the supplied output schema: item_id, evidence (the seven boolean "
        "invariants), and rationale (the seven matching non-empty explanations). "
        "FALSE is the correct output whenever an invariant is not securely "
        "established; do not assume the item is expected to pass and do not "
        "optimize toward seven true values. Do not return analysis, phase notes, "
        "prose, markdown fences, or any extra keys."
    )


def invoke_auditor(
    runtime: AgentRuntime,
    payload: Mapping[str, Any],
    *,
    artifact_dir: Path,
    model: str | None,
    timeout_seconds: float,
) -> InvocationResult:
    sandbox = "read-only" if runtime.provider == "codex" else None
    request = InvocationRequest(
        stage=STAGE,
        agent_name=AGENT_NAME,
        agent_definition=PROMPT_PATH,
        prompt=audit_prompt(payload),
        input_keys=tuple(AUDIT_PROJECTION_KEYS),
        formal_output_schema=AUDIT_OUTPUT_SCHEMA_PATH,
        system_directive=audit_system_directive(),
        model=model,
        cwd=ROOT,
        sandbox=sandbox,  # type: ignore[arg-type]
        tools="",
        timeout_seconds=timeout_seconds,
        artifact_dir=artifact_dir,
        isolate_workspace=True,
    )
    return runtime.invoke(request)


def build_evidence_record(
    item: Mapping[str, Any],
    audit_output: Mapping[str, Any],
    invocation: InvocationResult,
) -> dict[str, Any]:
    """Attach immutable, wrapper-owned provenance to one auditor judgment.

    The model never supplies ``content_hash`` or any provenance field; those
    come only from the authoritative hash function and the actual
    ``InvocationResult``.
    """
    evidence = audit_output["evidence"]
    return {
        "item_id": str(item["item_id"]),
        "content_hash": content_hash_for_item(item),
        "evidence": {name: bool(evidence[name]) for name in STRONG_INVARIANT_NAMES},
        "evidence_producer": EVIDENCE_PRODUCER,
        "evidence_producer_version": EVIDENCE_PRODUCER_VERSION,
        "invocation_id": invocation.invocation_id,
        "created_at": invocation.completed_at or invocation.started_at,
        "evidence_method": EVIDENCE_METHOD,
        "model_identifier": invocation.model,
    }


def run_production_validator(generator_output_path: Path, evidence_path: Path) -> bool:
    """Run the frozen WE v2.1.3 validator as a local subprocess (no model call)."""
    proc = subprocess.run(
        [sys.executable, str(GENERATOR_VALIDATOR_PATH), str(generator_output_path), str(evidence_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode == 0


def _invocation_failure_kind(category: str | None) -> str:
    if category in INFRASTRUCTURE_ERROR_CATEGORIES:
        return "infrastructure"
    return "semantic"


@dataclass
class ItemOutcome:
    item_id: str
    auditor_invoked: bool
    auditor_contract_pass: bool
    all_strong_invariants_pass: bool
    production_validator_eligible: bool
    failure_kind: str | None
    evidence_record: dict[str, Any] | None


def audit_item(
    item: Any,
    *,
    runtime: AgentRuntime,
    artifact_dir: Path,
    model: str | None,
    timeout_seconds: float,
) -> ItemOutcome:
    """Run exactly one grammar-auditor invocation for one item; never retry."""
    raw_item_id = item.get("item_id") if isinstance(item, Mapping) else None
    item_id = raw_item_id if isinstance(raw_item_id, str) and raw_item_id.strip() else "unknown-item"

    try:
        payload = build_audit_payload(item)
    except GrammarEvidenceError:
        return ItemOutcome(item_id, False, False, False, False, "semantic", None)

    atomic_write_json(artifact_dir / f"auditor_input_{_safe_filename(item_id)}.json", payload)

    try:
        invocation = invoke_auditor(
            runtime,
            payload,
            artifact_dir=artifact_dir,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except RuntimeInvocationError as exc:
        return ItemOutcome(
            item_id, False, False, False, False, _invocation_failure_kind(exc.category), None
        )

    raw = invocation.parsed
    atomic_write_json(artifact_dir / f"auditor_raw_{_safe_filename(item_id)}.json", raw)

    contract_errors = audit_output_errors(raw, item_id)
    if contract_errors:
        return ItemOutcome(item_id, True, False, False, False, "semantic", None)

    all_true = all(raw["evidence"][name] is True for name in STRONG_INVARIANT_NAMES)
    record = build_evidence_record(item, raw, invocation)
    record_errors = schema_errors(record, load_schema(EVIDENCE_SCHEMA_PATH))
    if record_errors:
        return ItemOutcome(item_id, True, True, all_true, False, "semantic", None)

    failure_kind = None if all_true else "semantic"
    return ItemOutcome(item_id, True, True, all_true, all_true, failure_kind, record)


def produce_grammar_evidence(
    generator_output_path: Path,
    *,
    output_dir: Path,
    runtime: AgentRuntime | None = None,
    provider: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 300,
) -> dict[str, Any]:
    """Produce the external grammar-evidence sidecar for one Generator run.

    ``generator_output_path`` is the exact caller-supplied Generator formal
    output file; it is never discovered by scanning ``runs/``. Returns the
    same document written to ``result.json``.
    """
    generator_output_path = Path(generator_output_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "runtime" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    items = load_generator_items(generator_output_path)
    atomic_write_json(output_dir / "input.json", {"items": items})

    active_runtime = runtime if runtime is not None else configure_runtime(provider=provider, model=model)

    outcomes = [
        audit_item(
            item,
            runtime=active_runtime,
            artifact_dir=logs_dir,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        for item in items
    ]

    evidence_records = [outcome.evidence_record for outcome in outcomes if outcome.evidence_record is not None]
    evidence_path = output_dir / "grammar_evidence.json"
    atomic_write_json(evidence_path, {"items": evidence_records})

    semantic_failure = any(outcome.failure_kind == "semantic" for outcome in outcomes)
    infrastructure_failure = any(outcome.failure_kind == "infrastructure" for outcome in outcomes)

    production_validator_pass = False
    if not semantic_failure and not infrastructure_failure:
        production_validator_pass = run_production_validator(generator_output_path, evidence_path)

    if semantic_failure:
        decision = "QUARANTINE"
    elif infrastructure_failure:
        decision = "INFRASTRUCTURE_FAILURE"
    elif production_validator_pass:
        decision = "PASS"
    else:
        decision = "QUARANTINE"

    result = {
        "schema_version": "we-grammar-evidence-result-v1",
        "decision": decision,
        "item_count": len(items),
        "auditor_invocation_count": sum(1 for outcome in outcomes if outcome.auditor_invoked),
        "auditor_contract_pass_count": sum(1 for outcome in outcomes if outcome.auditor_contract_pass),
        "all_strong_invariants_pass": bool(outcomes) and all(
            outcome.all_strong_invariants_pass for outcome in outcomes
        ),
        "production_validator_pass": production_validator_pass,
        "evidence_output_path": str(evidence_path),
        "items": [
            {
                "item_id": outcome.item_id,
                "auditor_invoked": outcome.auditor_invoked,
                "auditor_contract_pass": outcome.auditor_contract_pass,
                "all_strong_invariants_pass": outcome.all_strong_invariants_pass,
                "production_validator_eligible": outcome.production_validator_eligible,
            }
            for outcome in outcomes
        ],
    }
    atomic_write_json(output_dir / "result.json", result)
    return result
