"""TOEFL ITP Grammar Item Generation Orchestrator - core engine.

This module contains NO TOEFL grammar judgement of its own. It never
generates a question, never decides whether a distractor is good, never
picks an answer, and never overrides a PASS/REVISE/REJECT verdict or a
solver_answer with its own guess. Its only job is to:

  - sequence Generator -> Reviewer -> Solver calls in the right order
  - validate each agent's output shape by SHELLING OUT to that agent's own
    existing validate_output.py (never re-implementing schema checks)
  - blind candidate items for the Solver by shelling out to the existing
    agents/toefl_itp_grammar_solver/scripts/create_solver_input.py
    (never re-implementing metadata stripping)
  - enforce retry/revision limits and state transitions
  - compute the AUTO_ACCEPT consensus rule mechanically from the three
    agents' own reported fields (no majority vote, no "probably right")
  - record provenance and split it into a public accepted_item vs an
    internal qa_audit record
  - queue disagreements for human decision (analysis/manual_review_queue.json)

See orchestrator/TOEFL_ITP_GRAMMAR_PIPELINE.md for the full protocol this
module implements.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

__all__ = [
    "State",
    "TERMINAL_STATES",
    "Candidate",
    "ConsensusResult",
    "FailureInfo",
    "SystemCallError",
    "BatchIntegrityTracker",
    "REPO_ROOT",
    "load_config",
    "load_versions",
    "load_items_by_id",
    "strip_internal_test_keys",
    "run_schema_validator",
    "blind_for_solver",
    "leakage_guard",
    "build_generator_feedback",
    "derive_slot_requirements",
    "evaluate_consensus",
    "process_generation_output",
    "process_review_output",
    "process_solver_stage",
    "build_accepted_item",
    "build_qa_audit",
    "build_provenance_record",
    "build_manual_review_entry",
    "append_manual_review_queue",
    "parse_agent_json",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class State:
    GENERATED = "GENERATED"
    GENERATION_FAILED = "GENERATION_FAILED"    # system failure calling/parsing Generator/Reviewer/Solver
    VALIDATION_FAILED = "VALIDATION_FAILED"    # an agent's output failed its own schema validator
    REVIEWING = "REVIEWING"
    REVISE_REQUIRED = "REVISE_REQUIRED"
    REJECTED = "REJECTED"
    SOLVING = "SOLVING"
    ACCEPTED = "ACCEPTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DISCARDED = "DISCARDED"


TERMINAL_STATES = {State.REJECTED, State.ACCEPTED, State.MANUAL_REVIEW, State.DISCARDED}

STRUCTURE_ALLOWLIST = ["item_id", "section", "stem", "options"]
WE_ALLOWLIST = ["item_id", "section", "sentence", "marked_parts"]

# Fields the Generator revision loop may see. Deliberately excludes
# independent_answer / checks / verdict / generator_answer / answer_match /
# source_similarity_risk / detected_error_position and anything else that
# would tell the Generator "here is the answer the Reviewer thinks is
# correct" rather than "here is what to fix" (spec section 5).
GENERATOR_FEEDBACK_ALLOWLIST = ["item_id", "issues", "revision_requirements"]

INTERNAL_TEST_KEY_PREFIX = "_"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_spec_versions(config: dict) -> dict:
    spec_path = REPO_ROOT / config["paths"]["spec_json"]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    return {
        "spec_version": spec.get("spec_version", "unknown"),
        "taxonomy_version": spec.get("taxonomy_version", "unknown"),
    }


def compute_agent_version(config: dict, key: str) -> str:
    """Content-hash the agent's prompt file so the recorded version changes
    automatically whenever the agent's instructions change, with no manual
    version bump to forget (spec section 13)."""
    path = REPO_ROOT / config["paths"][key]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return f"sha256:{digest}"


def load_versions(config: dict) -> dict:
    v = load_spec_versions(config)
    v["generator_version"] = compute_agent_version(config, "generator_agent_md")
    v["reviewer_version"] = compute_agent_version(config, "reviewer_agent_md")
    v["solver_version"] = compute_agent_version(config, "solver_agent_md")
    return v


def load_items_by_id(path: Path, label: str = "") -> dict[str, dict]:
    """Load a fixture/agent-output JSON file ({"items": [...]}) into a dict
    keyed by item_id. This is the ONLY sanctioned way replay scripts should
    load Generator/Reviewer/Solver records - callers must then join across
    files by looking up this dict with an item_id key, never by pairing up
    list positions from separately-loaded files (list order between two
    JSON files is not a contract, even if it happens to coincide today).

    Raises ValueError if:
      - an item is missing 'item_id'
      - two items in the same file share an item_id (silent dict-overwrite
        would otherwise hide the collision)
      - an item's own 'item_id' field doesn't match... (defensive; can't
        actually happen given how the dict is built, kept for clarity when
        this function is refactored)
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    by_id: dict[str, dict] = {}
    for idx, item in enumerate(items):
        item_id = item.get("item_id")
        if not item_id:
            raise ValueError(f"{label or path}: item at position {idx} has no item_id")
        if item_id in by_id:
            raise ValueError(f"{label or path}: duplicate item_id {item_id!r} - cannot join unambiguously")
        by_id[item_id] = item
    return by_id


def strip_internal_test_keys(item: dict) -> dict:
    """Fixtures under analysis/ (adversarial/reject test files) carry
    '_purpose' / '_intended_flaw' annotations for human readers. Those are
    not part of any agent's real output schema, so strip them before
    treating the fixture as a live candidate item."""
    return {k: v for k, v in item.items() if not k.startswith(INTERNAL_TEST_KEY_PREFIX)}


# ---------------------------------------------------------------------------
# Failure classification (spec section 16)
# ---------------------------------------------------------------------------

@dataclass
class FailureInfo:
    kind: str          # "system" (retryable, not a quality judgement) or "content" (schema-shape failure)
    stage: str          # "generator" | "reviewer" | "solver"
    detail: str


class SystemCallError(Exception):
    """Raised when an agent could not be invoked at all, or its output
    could not even be parsed as JSON. This is a transient/system failure,
    never evidence of poor item quality."""


def parse_agent_json(raw_text: str, stage: str) -> dict:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise SystemCallError(f"{stage}: output was not valid JSON: {e}") from e


def run_schema_validator(script_relpath: str, items: list[dict]) -> tuple[bool, str]:
    """Shell out to an agent's own validate_output.py (never reimplement
    schema checks in the Orchestrator itself). Returns (ok, combined_output).
    Raises SystemCallError if the validator script itself cannot be run
    (missing file, interpreter crash) - that is a system failure, distinct
    from the validator reporting content-shape errors with exit code 1."""
    script_path = REPO_ROOT / script_relpath
    if not script_path.exists():
        raise SystemCallError(f"validator script not found: {script_relpath}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump({"items": items}, tmp, ensure_ascii=False)
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except OSError as e:
        raise SystemCallError(f"failed to invoke validator {script_relpath}: {e}") from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    ok = proc.returncode == 0
    return ok, (proc.stdout + proc.stderr)


def blind_for_solver(config: dict, item: dict) -> dict:
    """Blind a single candidate item using the EXISTING
    create_solver_input.py script (spec section 7: 'Orchestratorが独自に
    metadata削除処理を再実装しない'). Returns the blinded dict."""
    script_path = REPO_ROOT / config["paths"]["solver_blinding_script"]
    if not script_path.exists():
        raise SystemCallError("solver blinding script not found")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp_in:
        json.dump({"items": [item]}, tmp_in, ensure_ascii=False)
        in_path = tmp_in.name
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    Path(out_path).unlink()  # let the script create it fresh

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), in_path, out_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise SystemCallError(f"blinding script failed: {proc.stdout}{proc.stderr}")
        blinded = json.loads(Path(out_path).read_text(encoding="utf-8"))
    except OSError as e:
        raise SystemCallError(f"failed to invoke blinding script: {e}") from e
    finally:
        Path(in_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)

    items = blinded.get("items", [])
    if len(items) != 1:
        raise SystemCallError("blinding script returned unexpected item count")
    return items[0]


def leakage_guard(blinded_item: dict, section: str) -> tuple[bool, list[str]]:
    """Defense-in-depth check on top of create_solver_input.py's own
    allowlist: verify the blinded item carries ONLY the allowlisted keys
    for its section before it is ever handed to the Solver."""
    allowlist = set(STRUCTURE_ALLOWLIST if section == "Structure" else WE_ALLOWLIST)
    actual = set(blinded_item.keys())
    leaked = sorted(actual - allowlist)
    missing = sorted(allowlist - actual)
    ok = not leaked and not missing
    problems = [f"unexpected key: {k}" for k in leaked] + [f"missing key: {k}" for k in missing]
    return ok, problems


def build_generator_feedback(reviewer_item: dict) -> dict:
    """What the Generator is allowed to see on a REVISE cycle: issues and
    revision_requirements only. Never independent_answer, checks, verdict,
    generator_answer, answer_match, or source_similarity_risk (spec
    section 5)."""
    return {
        "item_id": reviewer_item["item_id"],
        "issues": reviewer_item.get("issues", []),
        "revision_requirements": reviewer_item.get("revision_requirements", []),
    }


def derive_slot_requirements(generator_item: dict) -> dict:
    """Slot requirements to hand to a fresh Generator call if this
    candidate is discarded/rejected, so batch distribution (spec section
    14) is preserved where possible. Quality still takes priority over
    matching this exactly - see pipeline doc section 9."""
    slot = {
        "section": generator_item.get("section"),
        "primary_target": generator_item.get("primary_target"),
        "difficulty": generator_item.get("difficulty"),
        "correct_answer_position": generator_item.get("correct_answer"),
        "vocabulary_domain": generator_item.get("vocabulary_domain"),
    }
    if generator_item.get("section") == "Written Expression":
        slot["tested_error_type"] = generator_item.get("tested_error_type")
        slot["error_scope"] = generator_item.get("error_scope")
    return slot


# ---------------------------------------------------------------------------
# Consensus rule (spec sections 8-9)
# ---------------------------------------------------------------------------

@dataclass
class ConsensusResult:
    auto_accept: bool
    routing: str                 # ACCEPTED | MANUAL_REVIEW | DISCARDED
    failed_conditions: list[str] = field(default_factory=list)
    disagreement_reasons: list[str] = field(default_factory=list)


def evaluate_consensus(
    generator_item: dict, reviewer_item: dict, solver_item: dict, config: dict
) -> ConsensusResult:
    """Mechanically apply the exact AUTO_ACCEPT condition list from spec
    section 8. No majority vote, no 'the Generator is probably right'.
    Any single failed condition routes away from ACCEPTED."""
    allowed_confidence = set(config["auto_accept"]["allowed_solver_confidence"])
    blocked_risk = set(config["auto_accept"]["block_source_similarity_risk"])

    generator_answer = generator_item.get("correct_answer")
    reviewer_answer = reviewer_item.get("independent_answer")
    solver_answer = solver_item.get("solver_answer")

    failed: list[str] = []

    if reviewer_item.get("verdict") != "PASS":
        failed.append("reviewer.verdict != PASS")
    if reviewer_item.get("critical_failure") is not False:
        failed.append("reviewer.critical_failure != false")
    if reviewer_answer != generator_answer:
        failed.append("reviewer.independent_answer != generator.correct_answer")
    if solver_answer not in {"A", "B", "C", "D"}:
        failed.append("solver.solver_answer not in [A,B,C,D]")
    if solver_answer != generator_answer:
        failed.append("solver.solver_answer != generator.correct_answer")
    if solver_answer != reviewer_answer:
        failed.append("solver.solver_answer != reviewer.independent_answer")
    if solver_item.get("ambiguity_detected") is not False:
        failed.append("solver.ambiguity_detected != false")
    if solver_item.get("confidence") not in allowed_confidence:
        failed.append(f"solver.confidence not in {sorted(allowed_confidence)}")
    if reviewer_item.get("source_similarity_risk") in blocked_risk:
        failed.append("reviewer.source_similarity_risk == HIGH")

    if not failed:
        return ConsensusResult(auto_accept=True, routing=State.ACCEPTED)

    # Non-consensus routing (spec section 9). solver AMBIGUOUS/NONE take
    # precedence as dedicated routes; everything else (answer mismatches,
    # low confidence, high source-similarity risk) goes to MANUAL_REVIEW.
    if solver_answer == "AMBIGUOUS":
        return ConsensusResult(
            auto_accept=False, routing=State.MANUAL_REVIEW,
            failed_conditions=failed, disagreement_reasons=["solver_ambiguous"],
        )
    if solver_answer == "NONE":
        return ConsensusResult(
            auto_accept=False, routing=State.DISCARDED,
            failed_conditions=failed, disagreement_reasons=["solver_none"],
        )

    reasons = []
    if "solver.solver_answer != generator.correct_answer" in failed:
        reasons.append("solver_generator_mismatch")
    if "solver.solver_answer != reviewer.independent_answer" in failed:
        reasons.append("solver_reviewer_mismatch")
    if any(c.startswith("solver.confidence") for c in failed):
        reasons.append("solver_confidence_low")
    if "reviewer.source_similarity_risk == HIGH" in failed:
        reasons.append("source_similarity_high")
    if "reviewer.independent_answer != generator.correct_answer" in failed:
        reasons.append("reviewer_generator_mismatch")
    if "reviewer.critical_failure != false" in failed or "reviewer.verdict != PASS" in failed:
        reasons.append("reviewer_state_inconsistent")
    if not reasons:
        reasons.append("unspecified_condition_failure")

    return ConsensusResult(
        auto_accept=False, routing=State.MANUAL_REVIEW,
        failed_conditions=failed, disagreement_reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Candidate: one item's journey through the pipeline
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    item_id: str
    concept_id: str
    section: str
    state: str = State.GENERATED
    state_history: list[str] = field(default_factory=lambda: [State.GENERATED])
    generation_attempt: int = 1
    revision_count: int = 0
    generator_item: Optional[dict] = None
    reviewer_item: Optional[dict] = None
    solver_item: Optional[dict] = None
    solver_input: Optional[dict] = None
    leakage_check: Optional[dict] = None
    consensus: Optional[ConsensusResult] = None
    failure: Optional[FailureInfo] = None
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def transition(self, new_state: str, note: Optional[str] = None) -> None:
        self.state = new_state
        self.state_history.append(new_state)
        self.updated_at = now_iso()
        if note:
            self.notes.append(note)


def process_generation_output(candidate: Candidate, config: dict) -> Candidate:
    """Validate the Generator's candidate item against its own schema
    validator. Schema-shape failure -> VALIDATION_FAILED (content-shape,
    not quality). Cannot invoke the validator at all -> GENERATION_FAILED
    (system failure)."""
    assert candidate.generator_item is not None
    try:
        ok, output = run_schema_validator(
            config["paths"]["generator_validate_script"], [candidate.generator_item]
        )
    except SystemCallError as e:
        candidate.failure = FailureInfo(kind="system", stage="generator", detail=str(e))
        candidate.transition(State.GENERATION_FAILED, f"system failure: {e}")
        return candidate

    if not ok:
        candidate.failure = FailureInfo(kind="content", stage="generator", detail=output.strip())
        candidate.transition(State.VALIDATION_FAILED, "generator output failed schema validation")
        return candidate

    candidate.transition(State.REVIEWING, "generator output passed schema validation")
    return candidate


def process_review_output(candidate: Candidate, config: dict) -> Candidate:
    """Route on Reviewer verdict. REVISE loops back for regeneration up to
    max_revision_cycles, then DISCARDED. REJECT ends this candidate
    immediately - it is never patched, only replaced by a fresh item_id
    (spec section 5/9)."""
    assert candidate.reviewer_item is not None
    max_cycles = config["retry_policy"]["max_revision_cycles"]

    try:
        ok, output = run_schema_validator(
            config["paths"]["reviewer_validate_script"], [candidate.reviewer_item]
        )
    except SystemCallError as e:
        candidate.failure = FailureInfo(kind="system", stage="reviewer", detail=str(e))
        candidate.transition(State.GENERATION_FAILED, f"system failure: {e}")
        return candidate
    if not ok:
        candidate.failure = FailureInfo(kind="content", stage="reviewer", detail=output.strip())
        candidate.transition(State.VALIDATION_FAILED, "reviewer output failed schema validation")
        return candidate

    verdict = candidate.reviewer_item["verdict"]

    if verdict == "PASS":
        candidate.transition(State.SOLVING, "reviewer PASS -> proceeding to Solver")
        return candidate

    if verdict == "REJECT":
        candidate.transition(
            State.REJECTED,
            "reviewer REJECT -> candidate terminated; a fresh item_id must be generated from scratch, "
            "this candidate is never patched",
        )
        return candidate

    # REVISE
    candidate.revision_count += 1
    if candidate.revision_count > max_cycles:
        candidate.transition(
            State.DISCARDED,
            f"exceeded max_revision_cycles={max_cycles} without a PASS; discarding, "
            "a new item must be generated from scratch",
        )
    else:
        candidate.transition(
            State.REVISE_REQUIRED,
            f"reviewer REVISE (cycle {candidate.revision_count}/{max_cycles}); "
            "revision_requirements handed back to Generator, independent_answer withheld",
        )
    return candidate


def process_solver_stage(
    candidate: Candidate, config: dict, solver_item: Optional[dict]
) -> Candidate:
    """Only reachable from state SOLVING (i.e. only after Reviewer PASS).
    Blinds the item via the real create_solver_input.py, runs the leakage
    guard, validates the (caller-supplied) solver_item against its schema,
    then applies the mechanical consensus rule."""
    if candidate.state != State.SOLVING:
        raise ValueError(
            f"process_solver_stage called on candidate in state {candidate.state}, "
            "not SOLVING - refusing to call Solver on a non-PASS item"
        )

    try:
        blinded = blind_for_solver(config, candidate.generator_item)
    except SystemCallError as e:
        candidate.failure = FailureInfo(kind="system", stage="solver", detail=str(e))
        candidate.transition(State.GENERATION_FAILED, f"system failure during blinding: {e}")
        return candidate

    candidate.solver_input = blinded
    ok, problems = leakage_guard(blinded, candidate.section)
    candidate.leakage_check = {"ok": ok, "problems": problems, "blinded_keys": sorted(blinded.keys())}
    if not ok:
        candidate.transition(State.MANUAL_REVIEW, f"leakage guard failed: {problems}")
        return candidate

    if solver_item is None:
        raise ValueError("solver_item must be supplied once a candidate reaches SOLVING")

    try:
        val_ok, output = run_schema_validator(
            config["paths"]["solver_validate_script"], [solver_item]
        )
    except SystemCallError as e:
        candidate.failure = FailureInfo(kind="system", stage="solver", detail=str(e))
        candidate.transition(State.GENERATION_FAILED, f"system failure: {e}")
        return candidate
    if not val_ok:
        candidate.failure = FailureInfo(kind="content", stage="solver", detail=output.strip())
        candidate.transition(State.VALIDATION_FAILED, "solver output failed schema validation")
        return candidate

    candidate.solver_item = solver_item
    result = evaluate_consensus(candidate.generator_item, candidate.reviewer_item, solver_item, config)
    candidate.consensus = result
    candidate.transition(result.routing, f"consensus routing: {result.disagreement_reasons or 'auto_accept'}")
    return candidate


# ---------------------------------------------------------------------------
# Output separation (spec section 12)
# ---------------------------------------------------------------------------

def build_accepted_item(candidate: Candidate, versions: dict) -> Optional[dict]:
    """Public-facing item destined for the Question DB. Never includes
    Reviewer verdicts, Solver answers, confidence, or any other internal
    QA signal - only what a site user would need."""
    if candidate.state != State.ACCEPTED:
        return None
    g = candidate.generator_item
    r = candidate.reviewer_item
    base = {
        "item_id": g["item_id"],
        "section": g["section"],
        "difficulty": r["reviewer_difficulty"],
        "vocabulary_domain": g["vocabulary_domain"],
        "spec_version": versions["spec_version"],
        "taxonomy_version": versions["taxonomy_version"],
    }
    if g["section"] == "Structure":
        base.update({
            "stem": g["stem"],
            "options": g["options"],
            "correct_answer": g["correct_answer"],
            "explanation": {
                "answer_explanation": g["answer_explanation"],
                "distractor_rationales": g["distractor_rationales"],
            },
            "taxonomy": {
                "primary_target": g["primary_target"],
                "subtype": g["subtype"],
                "secondary_features": g["secondary_features"],
            },
        })
    else:
        base.update({
            "sentence": g["sentence"],
            "marked_parts": g["marked_parts"],
            "correct_answer": g["correct_answer"],
            "explanation": {
                "answer_explanation": g["answer_explanation"],
                "minimal_correction": g["minimal_correction"],
            },
            "taxonomy": {
                "primary_target": g["primary_target"],
                "subtype": g["subtype"],
                "secondary_features": g["secondary_features"],
                "tested_error_type": g["tested_error_type"],
                "error_scope": g["error_scope"],
            },
        })
    return base


def build_qa_audit(candidate: Candidate, versions: dict) -> dict:
    """Internal-only record. Never shipped to the site / Question DB."""
    return {
        "item_id": candidate.item_id,
        "concept_id": candidate.concept_id,
        "state": candidate.state,
        "state_history": candidate.state_history,
        "generation_attempt": candidate.generation_attempt,
        "revision_count": candidate.revision_count,
        "reviewer": candidate.reviewer_item,
        "solver": candidate.solver_item,
        "leakage_check": candidate.leakage_check,
        "consensus": None if candidate.consensus is None else {
            "auto_accept": candidate.consensus.auto_accept,
            "routing": candidate.consensus.routing,
            "failed_conditions": candidate.consensus.failed_conditions,
            "disagreement_reasons": candidate.consensus.disagreement_reasons,
        },
        "failure": None if candidate.failure is None else {
            "kind": candidate.failure.kind,
            "stage": candidate.failure.stage,
            "detail": candidate.failure.detail,
        },
        "notes": candidate.notes,
        "versions": versions,
        "timestamps": {"created": candidate.created_at, "updated": candidate.updated_at},
    }


def build_provenance_record(candidate: Candidate, versions: dict) -> dict:
    accepted = build_accepted_item(candidate, versions)
    audit = build_qa_audit(candidate, versions)
    slot = derive_slot_requirements(candidate.generator_item) if candidate.generator_item else None
    return {
        "item_id": candidate.item_id,
        "concept_id": candidate.concept_id,
        "section": candidate.section,
        "state": candidate.state,
        "state_history": candidate.state_history,
        "generation_attempt": candidate.generation_attempt,
        "revision_count": candidate.revision_count,
        "generator": None if not candidate.generator_item else {
            "answer": candidate.generator_item.get("correct_answer"),
        },
        "reviewer": None if not candidate.reviewer_item else {
            "verdict": candidate.reviewer_item.get("verdict"),
            "independent_answer": candidate.reviewer_item.get("independent_answer"),
            "difficulty": candidate.reviewer_item.get("reviewer_difficulty"),
        },
        "solver": None if not candidate.solver_item else {
            "answer": candidate.solver_item.get("solver_answer"),
            "confidence": candidate.solver_item.get("confidence"),
        },
        "consensus": candidate.state == State.ACCEPTED,
        "batch_slot": slot,
        "versions": versions,
        "accepted_item": accepted,
        "qa_audit": audit,
    }


# ---------------------------------------------------------------------------
# Manual review queue (spec section 15)
# ---------------------------------------------------------------------------

def build_manual_review_entry(candidate: Candidate) -> dict:
    g = candidate.generator_item or {}
    r = candidate.reviewer_item or {}
    s = candidate.solver_item or {}
    return {
        "item_id": candidate.item_id,
        "section": candidate.section,
        "item": g,
        "disagreement_reasons": [] if candidate.consensus is None else candidate.consensus.disagreement_reasons,
        "generator_answer": g.get("correct_answer"),
        "reviewer_answer": r.get("independent_answer"),
        "solver_answer": s.get("solver_answer"),
        "solver_confidence": s.get("confidence"),
        "issues": r.get("issues", []),
        "state_history": candidate.state_history,
        "possible_actions": ["ACCEPT", "REGENERATE", "DISCARD"],
    }


def append_manual_review_queue(config: dict, entries: list[dict]) -> Path:
    path = REPO_ROOT / config["paths"]["manual_review_queue"]
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")).get("items", [])
        except json.JSONDecodeError:
            existing = []
    existing_ids = {e["item_id"] for e in existing}
    for entry in entries:
        if entry["item_id"] not in existing_ids:
            existing.append(entry)
    path.write_text(
        json.dumps({"items": existing}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# Batch integrity tracking (spec section 14)
# ---------------------------------------------------------------------------

class BatchIntegrityTracker:
    """Tracks planned vs. actual (ACCEPTED-only) distribution across a
    batch, purely descriptively - it never blocks an ACCEPT/DISCARD
    decision itself (quality takes priority over distribution)."""

    def __init__(self) -> None:
        self.planned: dict[str, dict[str, int]] = {}
        self.actual: dict[str, dict[str, int]] = {}

    @staticmethod
    def _dims(generator_item: dict) -> dict[str, str]:
        dims = {
            "primary_target": generator_item.get("primary_target"),
            "difficulty": generator_item.get("difficulty"),
            "correct_answer_position": generator_item.get("correct_answer"),
            "vocabulary_domain": generator_item.get("vocabulary_domain"),
        }
        if generator_item.get("section") == "Written Expression":
            dims["tested_error_type"] = generator_item.get("tested_error_type")
        return dims

    def record_planned(self, generator_item: dict) -> None:
        self._bump(self.planned, self._dims(generator_item))

    def record_accepted(self, generator_item: dict) -> None:
        self._bump(self.actual, self._dims(generator_item))

    @staticmethod
    def _bump(target: dict[str, dict[str, int]], dims: dict[str, str]) -> None:
        for dim, value in dims.items():
            if value is None:
                continue
            target.setdefault(dim, {})
            target[dim][value] = target[dim].get(value, 0) + 1

    def summary(self) -> dict:
        return {"planned": self.planned, "actual_accepted": self.actual}
