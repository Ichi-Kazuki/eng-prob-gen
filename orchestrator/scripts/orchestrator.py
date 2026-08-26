"""TOEFL ITP Grammar Item Generation Orchestrator - core engine.

This module contains NO TOEFL grammar judgement of its own. It never
generates a question, never decides whether a distractor is good, never
picks an answer, and never overrides a PASS/REVISE/REJECT verdict or a
solver_answer with its own guess. Its only job is to:

  - sequence Generator -> Reviewer -> Solver calls in the right order
  - validate each agent's output shape by SHELLING OUT to that agent's own
    existing validate_output.py (never re-implementing schema checks)
  - blind candidate items for the Solver through the shared, pure
    allowlist projection also used by the compatibility CLI
  - enforce retry/revision limits and state transitions
  - compute the AUTO_ACCEPT consensus rule mechanically from the three
    agents' own reported fields (no majority vote, no "probably right")
  - record provenance and split it into a public accepted_item vs an
    internal qa_audit record
  - queue disagreements for human decision (runs/manual_review_queue.json)

See orchestrator/TOEFL_ITP_GRAMMAR_PIPELINE.md for the full protocol this
module implements.
"""

from __future__ import annotations

import hashlib
import json
import copy
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.json_io import (  # noqa: E402
    JsonPersistenceError,
    atomic_write_json,
    canonical_json_sha256,
    exclusive_file_lock,
    read_json,
)
from shared.schema_validation import (  # noqa: E402
    SchemaValidationRuntimeError,
    load_schema,
    schema_errors,
)
from shared.solver_blinding import (  # noqa: E402
    STRUCTURE_ALLOWLIST,
    WRITTEN_EXPRESSION_ALLOWLIST,
    canonical_solver_input as _canonical_solver_input,
)

__all__ = [
    "State",
    "VALID_STATES",
    "TERMINAL_STATES",
    "ALLOWED_TRANSITIONS",
    "Candidate",
    "candidate_to_dict",
    "dict_to_candidate",
    "validate_candidate_invariants",
    "load_candidate_state",
    "save_candidate_state",
    "solver_batch_state_fingerprint",
    "build_solver_batch_artifact",
    "validate_solver_batch_artifact",
    "finalization_id",
    "ConsensusResult",
    "FailureInfo",
    "SystemCallError",
    "BatchIntegrityTracker",
    "REPO_ROOT",
    "load_config",
    "configured_runtime_root",
    "load_versions",
    "build_run_manifest",
    "validate_run_manifest",
    "load_state_bundle",
    "load_state_manifest",
    "config_from_run_manifest",
    "manifest_versions",
    "current_version_mismatches",
    "load_items_by_id",
    "strip_internal_test_keys",
    "run_schema_validator",
    "blind_for_solver",
    "canonicalize_solver_input",
    "canonical_solver_input_errors",
    "leakage_guard",
    "build_generator_feedback",
    "build_review_feedback_from_state",
    "derive_slot_requirements",
    "evaluate_consensus",
    "process_generation_output",
    "process_review_output",
    "process_solver_stage",
    "record_stage_failure",
    "retry_failed_stage",
    "build_retry_summary",
    "build_accepted_item",
    "build_qa_audit",
    "build_provenance_record",
    "build_manual_review_entry",
    "append_manual_review_queue",
    "parse_agent_json",
    "validate_final_record",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"
SOLVER_BATCH_SCHEMA_PATH = REPO_ROOT / "orchestrator" / "schemas" / "solver_input_batch.schema.json"
STATE_SCHEMA_VERSION = 2
RUN_MANIFEST_SCHEMA_VERSION = 1
STATE_MANIFEST_KEY = "run_manifest"


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


VALID_STATES = frozenset({
    State.GENERATED,
    State.GENERATION_FAILED,
    State.VALIDATION_FAILED,
    State.REVIEWING,
    State.REVISE_REQUIRED,
    State.REJECTED,
    State.SOLVING,
    State.ACCEPTED,
    State.MANUAL_REVIEW,
    State.DISCARDED,
})

TERMINAL_STATES = {State.REJECTED, State.ACCEPTED, State.MANUAL_REVIEW, State.DISCARDED}

RETRY_STAGES = ("generator", "reviewer", "solver")
STAGE_RETRY_STATES = {
    "generator": State.GENERATED,
    "reviewer": State.REVIEWING,
    "solver": State.SOLVING,
}

ALLOWED_TRANSITIONS = {
    State.GENERATED: {State.REVIEWING, State.VALIDATION_FAILED, State.GENERATION_FAILED},
    State.GENERATION_FAILED: {
        State.GENERATED, State.REVIEWING, State.SOLVING, State.MANUAL_REVIEW,
    },
    State.VALIDATION_FAILED: {
        State.GENERATED, State.REVIEWING, State.SOLVING, State.DISCARDED, State.MANUAL_REVIEW,
    },
    State.REVIEWING: {
        State.SOLVING, State.REVISE_REQUIRED, State.REJECTED, State.DISCARDED,
        State.VALIDATION_FAILED, State.GENERATION_FAILED,
    },
    # REVIEWING is retained for compatibility with older persisted replay
    # states that recorded the regenerated output without the intermediate
    # GENERATED marker. New drivers use GENERATED explicitly.
    State.REVISE_REQUIRED: {State.GENERATED, State.REVIEWING, State.DISCARDED},
    State.SOLVING: {
        State.ACCEPTED, State.MANUAL_REVIEW, State.DISCARDED,
        State.VALIDATION_FAILED, State.GENERATION_FAILED,
    },
    State.REJECTED: set(),
    State.ACCEPTED: set(),
    State.MANUAL_REVIEW: set(),
    State.DISCARDED: set(),
}

# These names are retained for the leakage guard's existing API.  The
# canonical field lists themselves are owned by shared.solver_blinding.
WE_ALLOWLIST = WRITTEN_EXPRESSION_ALLOWLIST

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


def configured_runtime_root(config: dict | None = None) -> Path:
    """Resolve the configured generated-output root below the repository.

    Runtime output is intentionally constrained to a repository-relative
    directory so a malformed config cannot redirect persistence to an arbitrary
    location. Tests and callers may still replace their driver-specific output
    constants when using temporary directories.
    """
    config = load_config() if config is None else config
    raw_root = config.get("runtime_root", "runs")
    if not isinstance(raw_root, str) or not raw_root.strip():
        raise ValueError("runtime_root must be a non-empty relative path")
    root = Path(raw_root)
    if root.is_absolute() or ".." in root.parts:
        raise ValueError("runtime_root must remain below the repository root")
    return REPO_ROOT / root


def _git_commit_sha() -> str | None:
    """Return the checked-out commit when the source tree is a Git checkout."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and len(sha) == 40 else None


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
    v["validator_versions"] = {
        "generator": _hash_repo_file(config["paths"]["generator_validate_script"]),
        "reviewer": _hash_repo_file(config["paths"]["reviewer_validate_script"]),
        "solver": _hash_repo_file(config["paths"]["solver_validate_script"]),
        "we_generator_v2": _hash_repo_file(
            "agents/toefl_itp_we_generator_v2/scripts/validate_output.py"
        ),
        "we_reviewer_v2": _hash_repo_file(
            "agents/toefl_itp_we_reviewer_v2/scripts/validate_output.py"
        ),
    }
    v["schema_versions"] = {
        "generator_structure": _hash_repo_file(
            "agents/toefl_itp_grammar_generator/schema/structure_item.schema.json"
        ),
        "generator_written_expression": _hash_repo_file(
            "agents/toefl_itp_grammar_generator/schema/written_expression_item.schema.json"
        ),
        "we_generator_v2": _hash_repo_file(
            "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json"
        ),
        "reviewer": _hash_repo_file(
            "agents/toefl_itp_grammar_reviewer/schema/reviewer_output.schema.json"
        ),
        "we_reviewer_v2": _hash_repo_file(
            "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json"
        ),
        "solver": _hash_repo_file(
            "agents/toefl_itp_grammar_solver/schema/solver_output.schema.json"
        ),
        "grammar_evidence": _hash_repo_file(
            "agents/toefl_itp_we_generator_v2/schema/grammar_evidence.schema.json"
        ),
        "solver_input_batch": _hash_repo_file(
            "orchestrator/schemas/solver_input_batch.schema.json"
        ),
    }
    v["orchestrator_version"] = _hash_repo_file("orchestrator/scripts/orchestrator.py")
    # The policy now lives in shared code; keep a separate CLI hash so the
    # audit trail can distinguish policy changes from wrapper changes.
    v["solver_blinding_version"] = _hash_repo_file("shared/solver_blinding.py")
    v["solver_blinding_cli_version"] = _hash_repo_file(
        config["paths"]["solver_blinding_script"]
    )
    v["config_version"] = _hash_repo_file("orchestrator/config.json")
    return v


def _hash_repo_file(path: str) -> str:
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = REPO_ROOT / file_path
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _manifest_file_hashes(config: dict) -> dict:
    """Hash every executable contract that can affect a run.

    The short legacy fields in ``load_versions`` remain unchanged for old
    artifact compatibility. The manifest stores full SHA-256 values under
    explicit categories so a new run has an unambiguous immutable snapshot.
    """
    prompt_paths = {
        "generator": config["paths"]["generator_agent_md"],
        "reviewer": config["paths"]["reviewer_agent_md"],
        "solver": config["paths"]["solver_agent_md"],
    }
    schema_paths = {
        "generator_structure": "agents/toefl_itp_grammar_generator/schema/structure_item.schema.json",
        "generator_written_expression": "agents/toefl_itp_grammar_generator/schema/written_expression_item.schema.json",
        "we_generator_v2": "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json",
        "reviewer": "agents/toefl_itp_grammar_reviewer/schema/reviewer_output.schema.json",
        "we_reviewer_v2": "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json",
        "solver": "agents/toefl_itp_grammar_solver/schema/solver_output.schema.json",
        "grammar_evidence": "agents/toefl_itp_we_generator_v2/schema/grammar_evidence.schema.json",
        "solver_input_batch": "orchestrator/schemas/solver_input_batch.schema.json",
        "run_manifest": "orchestrator/schemas/run_manifest.schema.json",
    }
    validator_paths = {
        "generator": config["paths"]["generator_validate_script"],
        "reviewer": config["paths"]["reviewer_validate_script"],
        "solver": config["paths"]["solver_validate_script"],
        "we_generator_v2": "agents/toefl_itp_we_generator_v2/scripts/validate_output.py",
        "we_reviewer_v2": "agents/toefl_itp_we_reviewer_v2/scripts/validate_output.py",
    }
    shared_paths = {
        "driver_helpers": "orchestrator/scripts/driver_helpers.py",
        "json_io": "shared/json_io.py",
        "schema_validation": "shared/schema_validation.py",
        "solver_blinding": "shared/solver_blinding.py",
        "tokenization": "shared/tokenization.py",
    }
    runtime_paths = {
        "adapters": "runtime/adapters.py",
        "codex_schema": "runtime/codex_schema.py",
    }
    policy_input_paths = {
        "specification": config["paths"]["spec_json"],
        "we_format_spec": "specs/toefl_itp_we_format_spec_addendum.json",
        "we_format_config": "agents/toefl_itp_we_generator_v2/config/we_v2_format_config.json",
        "we_format_planner": "agents/toefl_itp_we_generator_v2/scripts/format_planner.py",
        "we_official_profile": "analysis/we_format/written_expression_format_official.json",
    }

    def hash_group(paths: dict[str, str]) -> dict[str, str]:
        return {name: _hash_repo_file(path) for name, path in paths.items()}

    return {
        "config": _hash_repo_file("orchestrator/config.json"),
        "prompts": hash_group(prompt_paths),
        "schemas": hash_group(schema_paths),
        "validators": hash_group(validator_paths),
        "orchestrator_source": _hash_repo_file("orchestrator/scripts/orchestrator.py"),
        "shared_modules": hash_group(shared_paths),
        "runtime_modules": hash_group(runtime_paths),
        "policy_inputs": hash_group(policy_input_paths),
    }


def _manifest_payload(manifest: dict) -> dict:
    payload = copy.deepcopy(manifest)
    payload.pop("manifest_id", None)
    payload.pop("manifest_sha256", None)
    return payload


def _finalize_run_manifest(manifest: dict) -> dict:
    payload = _manifest_payload(manifest)
    digest = canonical_json_sha256(payload)
    finalized = copy.deepcopy(payload)
    finalized["manifest_sha256"] = digest
    finalized["manifest_id"] = "run-manifest-" + digest.split(":", 1)[1][:24]
    return finalized


def build_run_manifest(config: dict) -> dict:
    """Create the immutable run snapshot persisted at ``init`` time."""
    if not isinstance(config, dict):
        raise ValueError("run manifest config must be an object")
    manifest = {
        "manifest_schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "created_at": now_iso(),
        "git_commit_sha": _git_commit_sha(),
        "pipeline_version": config.get("pipeline_version"),
        "versions": load_versions(config),
        "hashes": _manifest_file_hashes(config),
        # This is non-secret policy/config input used for replay validation.
        "config_snapshot": copy.deepcopy(config),
    }
    return _finalize_run_manifest(manifest)


def validate_run_manifest(manifest: object) -> dict:
    """Validate manifest structure and its self-authenticating ID/hash."""
    if not isinstance(manifest, dict):
        raise ValueError("run manifest must be an object")
    required = {
        "manifest_schema_version", "created_at", "git_commit_sha", "pipeline_version",
        "versions", "hashes", "config_snapshot", "manifest_sha256", "manifest_id",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"run manifest is missing required field(s): {', '.join(missing)}")
    if manifest["manifest_schema_version"] != RUN_MANIFEST_SCHEMA_VERSION:
        raise ValueError("run manifest schema version is unsupported")
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"].strip():
        raise ValueError("run manifest created_at must be a non-empty string")
    if manifest["git_commit_sha"] is not None and (
        not isinstance(manifest["git_commit_sha"], str)
        or len(manifest["git_commit_sha"]) != 40
        or any(c not in "0123456789abcdef" for c in manifest["git_commit_sha"])
    ):
        raise ValueError("run manifest git_commit_sha is malformed")
    if not isinstance(manifest["pipeline_version"], str) or not manifest["pipeline_version"].strip():
        raise ValueError("run manifest pipeline_version must be a non-empty string")
    if not isinstance(manifest["versions"], dict) or not isinstance(manifest["hashes"], dict):
        raise ValueError("run manifest versions and hashes must be objects")
    if not isinstance(manifest["config_snapshot"], dict):
        raise ValueError("run manifest config_snapshot must be an object")
    try:
        manifest_schema = load_schema(REPO_ROOT / "orchestrator" / "schemas" / "run_manifest.schema.json")
        structural_errors = schema_errors(manifest, manifest_schema)
    except SchemaValidationRuntimeError as exc:
        raise ValueError(f"run manifest schema could not be validated: {exc}") from exc
    if structural_errors:
        raise ValueError("run manifest schema validation failed: " + "; ".join(structural_errors))
    expected = _finalize_run_manifest(manifest)
    if manifest.get("manifest_sha256") != expected["manifest_sha256"]:
        raise ValueError("run manifest hash mismatch")
    if manifest.get("manifest_id") != expected["manifest_id"]:
        raise ValueError("run manifest ID mismatch")
    return copy.deepcopy(manifest)


def manifest_versions(manifest: dict) -> dict:
    return copy.deepcopy(validate_run_manifest(manifest)["versions"])


def config_from_run_manifest(manifest: dict) -> dict:
    return copy.deepcopy(validate_run_manifest(manifest)["config_snapshot"])


def current_version_mismatches(manifest: dict, config: dict | None = None) -> list[str]:
    """Report drift for diagnostics without changing the persisted snapshot."""
    config = load_config() if config is None else config
    expected = _manifest_file_hashes(config)
    actual = manifest.get("hashes", {})
    mismatches: list[str] = []
    for group, values in expected.items():
        if group in {"config", "orchestrator_source"}:
            if actual.get(group) != values:
                mismatches.append(group)
            continue
        for name, value in values.items():
            if actual.get(group, {}).get(name) != value:
                mismatches.append(f"{group}.{name}")
    return mismatches


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
    source = label or str(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source}: could not load JSON: {exc}") from exc

    if isinstance(data, dict):
        if "items" not in data:
            raise ValueError(f"{source}: top-level object must contain an 'items' array")
        items = data["items"]
        if not isinstance(items, list):
            raise ValueError(f"{source}: top-level 'items' must be a list")
    elif isinstance(data, list):
        # Bare lists are retained for compatibility with the replay fixtures
        # that have historically used that form.
        items = data
    else:
        raise ValueError(
            f"{source}: top-level JSON must be an object containing an 'items' array or a list"
        )

    by_id: dict[str, dict] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{source}: item at position {idx} must be an object")
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(
                f"{source}: item at position {idx} must have a non-empty string item_id"
            )
        if item_id in by_id:
            raise ValueError(f"{source}: duplicate item_id {item_id!r} - cannot join unambiguously")
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


def run_schema_validator(
    script_relpath: str, items: list[dict], timeout_seconds: float = 60
) -> tuple[bool, str]:
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
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        raise SystemCallError(
            f"validator {script_relpath} timed out after {timeout_seconds}s; "
            f"stdout={e.stdout or ''}; stderr={e.stderr or ''}"
        ) from e
    except OSError as e:
        raise SystemCallError(f"failed to invoke validator {script_relpath}: {e}") from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    output = proc.stdout + proc.stderr
    if proc.returncode == 0:
        return True, output
    if proc.returncode == 1:
        return False, output
    raise SystemCallError(
        f"validator {script_relpath} exited unexpectedly with code "
        f"{proc.returncode}: {output}"
    )


def blind_for_solver(config: dict, item: dict, timeout_seconds: float = 60) -> dict:
    """Return a single candidate's canonical Solver payload.

    The compatibility signature is retained, but production logic is the
    shared pure projection rather than the CLI wrapper.
    """
    del config, timeout_seconds
    try:
        return _canonical_solver_input(item)
    except (TypeError, ValueError, KeyError) as exc:
        raise SystemCallError(f"solver blinding failed: {exc}") from exc


def canonicalize_solver_input(config: dict, item: dict) -> dict:
    """Return the canonical blind payload using the shared pure function.

    The historical ``config`` argument is retained for API compatibility;
    canonicalization itself has no external dependency or mutable state.
    """
    del config
    return _canonical_solver_input(item)


def canonical_solver_input_errors(
    config: dict, generator_item: object, solver_input: object
) -> list[str]:
    """Return invariant errors for a selected Solver payload.

    Drivers use this shared check before writing a Solver batch. It returns
    errors instead of treating a mismatch as a usable fallback; callers must
    route the Candidate away from Solver.
    """
    if not isinstance(generator_item, dict):
        return ["canonical Solver input could not be derived: generator item must be an object"]
    try:
        expected = canonicalize_solver_input(config, generator_item)
    except (TypeError, ValueError, KeyError) as exc:
        return [f"canonical Solver input could not be derived: {exc}"]
    if solver_input != expected:
        return [
            "solver input does not match the canonical blinded payload "
            "derived from the current generator_item"
        ]
    return []


def leakage_guard(blinded_item: dict, section: str) -> tuple[bool, list[str]]:
    """Defense-in-depth check on top of create_solver_input.py's own
    allowlist: verify the blinded item carries ONLY the allowlisted keys
    for its section before it is ever handed to the Solver."""
    if section not in {"Structure", "Written Expression"}:
        return False, [f"unsupported section: {section!r}"]
    if not isinstance(blinded_item, dict):
        return False, ["Solver input must be an object"]
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


def build_review_feedback_from_state(
    candidates: dict[str, "Candidate"], round_label: str
) -> dict:
    """Rebuild one Reviewer round's Generator feedback from Candidate state.

    Reviewer history is the durable source of truth.  Only records explicitly
    routed to ``REVISE_REQUIRED`` are emitted, so rebuilding a round does not
    accidentally include a stale candidate that was already in that state.
    Older state files did not record the routed state; for those records the
    validated Reviewer verdict is used as a compatibility fallback.
    """
    if not isinstance(round_label, str) or not round_label.strip():
        raise ValueError("round_label must be a non-empty string")

    feedback: list[dict] = []
    for candidate in candidates.values():
        for history_entry in reversed(candidate.review_history):
            if not isinstance(history_entry, dict) or history_entry.get("round") != round_label:
                continue
            reviewer_item = history_entry.get("output")
            if not isinstance(reviewer_item, dict):
                raise ValueError(
                    f"candidate {candidate.item_id!r} has malformed Reviewer history "
                    f"for round {round_label!r}"
                )
            if (
                reviewer_item.get("item_id") != candidate.item_id
                or reviewer_item.get("section") != candidate.section
            ):
                raise ValueError(
                    f"candidate {candidate.item_id!r} has mismatched Reviewer history "
                    f"for round {round_label!r}"
                )
            routed_state = history_entry.get("routed_state")
            is_revision = routed_state == State.REVISE_REQUIRED
            if routed_state is None:
                # State files written before routed_state was introduced are
                # still readable.  A Reviewer REVISE verdict is the only
                # safe legacy signal for reconstructing this artifact.
                is_revision = reviewer_item.get("verdict") == "REVISE"
            if is_revision:
                feedback.append(build_generator_feedback(reviewer_item))
            break
    return {"items": feedback}


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
    # Transient retries are kept separate from revision_count.  The keys are
    # stage names so a Reviewer failure cannot consume the Solver budget.
    system_failure_retries: dict[str, int] = field(default_factory=dict)
    validation_failure_retries: dict[str, int] = field(default_factory=dict)
    generator_item: Optional[dict] = None
    reviewer_item: Optional[dict] = None
    solver_item: Optional[dict] = None
    solver_input: Optional[dict] = None
    leakage_check: Optional[dict] = None
    # The first Generator output's slot is retained for batch accounting even
    # when a later revision changes the current item's metadata.
    planned_slot: Optional[dict] = None
    consensus: Optional[ConsensusResult] = None
    failure: Optional[FailureInfo] = None
    notes: list[str] = field(default_factory=list)
    review_history: list[dict] = field(default_factory=list)
    generation_history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def transition(self, new_state: str, note: Optional[str] = None) -> None:
        if new_state not in ALLOWED_TRANSITIONS:
            raise ValueError(f"unknown candidate state: {new_state}")
        allowed = ALLOWED_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise ValueError(
                f"invalid Candidate transition {self.state} -> {new_state}; "
                f"allowed={sorted(allowed)}"
            )
        self.state = new_state
        self.state_history.append(new_state)
        self.updated_at = now_iso()
        if note:
            self.notes.append(note)


def candidate_to_dict(candidate: Candidate) -> dict:
    """Serialize a Candidate for both live drivers' state files.

    Keeping this beside Candidate prevents Pilot and Validation state from
    drifting as fields are added to the pipeline state machine.
    """
    return {
        "item_id": candidate.item_id,
        "concept_id": candidate.concept_id,
        "section": candidate.section,
        "state": candidate.state,
        "state_history": candidate.state_history,
        "generation_attempt": candidate.generation_attempt,
        "revision_count": candidate.revision_count,
        "system_failure_retries": candidate.system_failure_retries,
        "validation_failure_retries": candidate.validation_failure_retries,
        "generator_item": candidate.generator_item,
        "reviewer_item": candidate.reviewer_item,
        "solver_item": candidate.solver_item,
        "solver_input": candidate.solver_input,
        "leakage_check": candidate.leakage_check,
        "planned_slot": candidate.planned_slot,
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
        "review_history": candidate.review_history,
        "generation_history": candidate.generation_history,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }


def dict_to_candidate(
    data: dict,
    config: dict | None = None,
    *,
    legacy_mode: bool = False,
) -> Candidate:
    """Restore a Candidate, accepting state files written before hardening."""
    if not isinstance(data, dict):
        raise ValueError("candidate state entry must be an object")
    required = ("item_id", "concept_id", "section", "state")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"candidate state entry is missing required field(s): {', '.join(missing)}")
    candidate = Candidate(
        item_id=data["item_id"],
        concept_id=data["concept_id"],
        section=data["section"],
    )
    candidate.state = data["state"]
    candidate.state_history = data.get("state_history", [candidate.state])
    candidate.generation_attempt = data.get("generation_attempt", 1)
    candidate.revision_count = data.get("revision_count", 0)
    candidate.system_failure_retries = data.get("system_failure_retries", {})
    candidate.validation_failure_retries = data.get("validation_failure_retries", {})
    candidate.generator_item = data.get("generator_item")
    candidate.reviewer_item = data.get("reviewer_item")
    candidate.solver_item = data.get("solver_item")
    candidate.solver_input = data.get("solver_input")
    candidate.leakage_check = data.get("leakage_check")
    candidate.planned_slot = data.get("planned_slot")
    if candidate.planned_slot is None and candidate.generator_item is not None:
        # Backward-compatible fallback for state files created before the
        # original-slot field existed. New runs capture it at initialization.
        candidate.planned_slot = derive_slot_requirements(candidate.generator_item)
    consensus = data.get("consensus")
    if consensus is not None:
        candidate.consensus = ConsensusResult(
            auto_accept=consensus["auto_accept"],
            routing=consensus["routing"],
            failed_conditions=consensus.get("failed_conditions", []),
            disagreement_reasons=consensus.get("disagreement_reasons", []),
        )
    failure = data.get("failure")
    if failure is not None:
        candidate.failure = FailureInfo(
            kind=failure["kind"], stage=failure["stage"], detail=failure["detail"]
        )
    candidate.notes = data.get("notes", [])
    candidate.review_history = data.get("review_history", [])
    candidate.generation_history = data.get("generation_history", [])
    candidate.created_at = data.get("created_at", candidate.created_at)
    candidate.updated_at = data.get("updated_at", candidate.updated_at)
    validate_candidate_invariants(candidate, config=config, legacy_mode=legacy_mode)
    return candidate


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_candidate_invariants(
    candidate: Candidate,
    config: dict | None = None,
    *,
    legacy_mode: bool = False,
) -> None:
    """Fail closed when a persisted Candidate is internally inconsistent.

    This intentionally validates pipeline-state invariants only. Agent output
    schema validation remains delegated to each agent's validator at the
    stage boundary, while persisted cross-stage identity and routing rules
    are checked here before a driver can continue from disk.
    """
    errors: list[str] = []
    config = load_config() if config is None else config

    if not isinstance(candidate.item_id, str) or not candidate.item_id:
        errors.append("item_id must be a non-empty string")
    if not isinstance(candidate.concept_id, str) or not candidate.concept_id:
        errors.append("concept_id must be a non-empty string")
    if not isinstance(candidate.section, str) or not candidate.section:
        errors.append("section must be a non-empty string")

    if candidate.state not in VALID_STATES:
        errors.append(f"state {candidate.state!r} is not a valid State value")

    history = candidate.state_history
    if not isinstance(history, list) or not history:
        errors.append("state_history must be a non-empty list")
    else:
        invalid_history_states = [state for state in history if state not in VALID_STATES]
        if invalid_history_states:
            errors.append(f"state_history contains invalid state(s): {invalid_history_states!r}")
        if history[-1] != candidate.state:
            errors.append(
                f"state_history last state {history[-1]!r} does not match current state {candidate.state!r}"
            )
        if history[0] != State.GENERATED:
            errors.append("state_history must start with GENERATED")
        for previous, current in zip(history, history[1:]):
            if previous in VALID_STATES and current not in ALLOWED_TRANSITIONS[previous]:
                errors.append(f"invalid state transition in state_history: {previous} -> {current}")

    if not _is_nonnegative_int(candidate.generation_attempt) or candidate.generation_attempt < 1:
        errors.append("generation_attempt must be an integer >= 1")
    if not _is_nonnegative_int(candidate.revision_count):
        errors.append("revision_count must be an integer >= 0")

    for field_name in ("system_failure_retries", "validation_failure_retries"):
        counters = getattr(candidate, field_name)
        if not isinstance(counters, dict):
            errors.append(f"{field_name} must be an object keyed by stage")
            continue
        for stage, count in counters.items():
            if stage not in RETRY_STAGES:
                errors.append(f"{field_name} contains unknown stage {stage!r}")
            if not _is_nonnegative_int(count):
                errors.append(f"{field_name}[{stage!r}] must be an integer >= 0")

    review_history = candidate.review_history
    if not isinstance(review_history, list):
        errors.append("review_history must be a list")
    else:
        for index, history_entry in enumerate(review_history):
            if not isinstance(history_entry, dict):
                errors.append(f"review_history[{index}] must be an object")
                continue
            if not isinstance(history_entry.get("round"), str) or not history_entry["round"].strip():
                errors.append(f"review_history[{index}].round must be a non-empty string")
            reviewer_output = history_entry.get("output")
            if not isinstance(reviewer_output, dict):
                errors.append(f"review_history[{index}].output must be an object")
            else:
                if reviewer_output.get("item_id") != candidate.item_id:
                    errors.append(
                        f"review_history[{index}].output.item_id does not match candidate.item_id"
                    )
                if reviewer_output.get("section") != candidate.section:
                    errors.append(
                        f"review_history[{index}].output.section does not match candidate.section"
                    )
            routed_state = history_entry.get("routed_state")
            if routed_state is not None and routed_state not in VALID_STATES:
                errors.append(f"review_history[{index}].routed_state is invalid")

    for stage, item in (
        ("generator", candidate.generator_item),
        ("reviewer", candidate.reviewer_item),
        ("solver", candidate.solver_item),
        ("solver_input", candidate.solver_input),
    ):
        if item is not None:
            if not isinstance(item, dict):
                errors.append(f"{stage} item must be an object")
                continue
            if item.get("item_id") != candidate.item_id:
                errors.append(
                    f"{stage}.item_id={item.get('item_id')!r} does not match candidate.item_id={candidate.item_id!r}"
                )
            if item.get("section") != candidate.section:
                errors.append(
                    f"{stage}.section={item.get('section')!r} does not match candidate.section={candidate.section!r}"
                )

    failure = candidate.failure
    if failure is not None:
        if failure.kind not in {"system", "content"}:
            errors.append(f"failure.kind {failure.kind!r} is invalid")
        if failure.stage not in RETRY_STAGES:
            errors.append(f"failure.stage {failure.stage!r} is invalid")
        if not isinstance(failure.detail, str):
            errors.append("failure.detail must be a string")
        if candidate.state not in {State.GENERATION_FAILED, State.VALIDATION_FAILED, State.MANUAL_REVIEW}:
            errors.append(f"failure is not allowed in state {candidate.state}")
        if candidate.state == State.GENERATION_FAILED and failure.kind != "system":
            errors.append("GENERATION_FAILED requires a system failure")
        if candidate.state == State.VALIDATION_FAILED and failure.kind != "content":
            errors.append("VALIDATION_FAILED requires a content/validation failure")
    elif candidate.state in {State.GENERATION_FAILED, State.VALIDATION_FAILED}:
        errors.append(f"{candidate.state} requires failure metadata")

    if candidate.state in {State.GENERATED, State.REVIEWING, State.SOLVING, State.REVISE_REQUIRED}:
        if candidate.generator_item is None and not (legacy_mode and candidate.state == State.GENERATED):
            errors.append(f"{candidate.state} requires generator_item")

    if candidate.state == State.REVISE_REQUIRED:
        if candidate.reviewer_item is None or candidate.reviewer_item.get("verdict") != "REVISE":
            errors.append("REVISE_REQUIRED requires reviewer verdict REVISE")
        requirements = None if candidate.reviewer_item is None else candidate.reviewer_item.get("revision_requirements")
        if not isinstance(requirements, list) or not requirements:
            errors.append("REVISE_REQUIRED requires non-empty revision_requirements")
        if candidate.consensus is not None and candidate.consensus.auto_accept:
            errors.append("REVISE_REQUIRED cannot contain an auto-accepted consensus")

    if candidate.state == State.SOLVING:
        if candidate.generator_item is None:
            errors.append("SOLVING requires generator_item")
        if candidate.reviewer_item is None:
            errors.append("SOLVING requires reviewer_item")
        elif candidate.reviewer_item.get("verdict") != "PASS":
            errors.append("SOLVING requires reviewer verdict PASS")

    if candidate.solver_input is not None:
        if not isinstance(candidate.solver_input, dict):
            errors.append("solver_input must be an object")
        else:
            ok, problems = leakage_guard(candidate.solver_input, candidate.section)
            if not ok:
                errors.append("solver_input leakage/shape invariant failed: " + "; ".join(problems))
            if candidate.generator_item is None:
                errors.append("solver_input requires generator_item for canonical validation")
            elif isinstance(candidate.generator_item, dict):
                try:
                    expected_solver_input = canonicalize_solver_input(
                        config, candidate.generator_item
                    )
                except Exception as exc:  # fail closed if the production blinder is unavailable
                    errors.append(f"solver_input canonicalization failed: {type(exc).__name__}: {exc}")
                else:
                    if candidate.solver_input != expected_solver_input:
                        errors.append(
                            "solver_input does not match the canonical blinded payload "
                            "derived from generator_item"
                        )

    if candidate.state == State.ACCEPTED:
        if candidate.generator_item is None or candidate.reviewer_item is None or candidate.solver_item is None:
            errors.append("ACCEPTED requires generator_item, reviewer_item, and solver_item")
        if candidate.solver_input is None:
            errors.append("ACCEPTED requires solver_input")
        if not isinstance(candidate.leakage_check, dict) or candidate.leakage_check.get("ok") is not True:
            errors.append("ACCEPTED requires a successful leakage_check")
        if candidate.consensus is None:
            errors.append("ACCEPTED requires consensus metadata")
        if candidate.reviewer_item is not None and candidate.reviewer_item.get("verdict") != "PASS":
            errors.append("ACCEPTED requires reviewer verdict PASS")

        if (
            isinstance(candidate.generator_item, dict)
            and isinstance(candidate.reviewer_item, dict)
            and isinstance(candidate.solver_item, dict)
            and isinstance(candidate.consensus, ConsensusResult)
        ):
            try:
                recomputed = evaluate_consensus(
                    candidate.generator_item,
                    candidate.reviewer_item,
                    candidate.solver_item,
                    config,
                )
            except Exception as exc:  # persisted state must never fail open
                errors.append(
                    f"ACCEPTED consensus recomputation failed: {type(exc).__name__}: {exc}"
                )
            else:
                if recomputed.auto_accept is not True or recomputed.routing != State.ACCEPTED:
                    errors.append(
                        "ACCEPTED consensus recomputation did not produce "
                        "auto_accept=True and routing=ACCEPTED"
                    )
                stored = {
                    "auto_accept": candidate.consensus.auto_accept,
                    "routing": candidate.consensus.routing,
                    "failed_conditions": candidate.consensus.failed_conditions,
                    "disagreement_reasons": candidate.consensus.disagreement_reasons,
                }
                expected = {
                    "auto_accept": recomputed.auto_accept,
                    "routing": recomputed.routing,
                    "failed_conditions": recomputed.failed_conditions,
                    "disagreement_reasons": recomputed.disagreement_reasons,
                }
                if stored != expected:
                    errors.append(
                        "persisted consensus metadata does not match recomputed consensus"
                    )

    if candidate.state == State.REJECTED:
        reviewer_rejected = (
            isinstance(candidate.reviewer_item, dict)
            and candidate.reviewer_item.get("verdict") == "REJECT"
        )
        consensus_rejected = (
            isinstance(candidate.consensus, ConsensusResult)
            and candidate.consensus.routing == State.REJECTED
        )
        failure_evidence = candidate.failure is not None and bool(candidate.failure.detail.strip())
        if not (reviewer_rejected or consensus_rejected or failure_evidence):
            errors.append("REJECTED requires reviewer, consensus, or failure evidence")

    if candidate.state == State.MANUAL_REVIEW:
        has_consensus = isinstance(candidate.consensus, ConsensusResult)
        has_failure = candidate.failure is not None
        has_leakage = isinstance(candidate.leakage_check, dict)
        has_routing_note = any(
            isinstance(note, str) and ("MANUAL_REVIEW" in note or "manual review" in note.lower())
            for note in candidate.notes
        )
        if not (has_consensus or has_failure or has_leakage or has_routing_note):
            errors.append(
                "MANUAL_REVIEW requires routing evidence in consensus, failure, leakage_check, or notes"
            )

    if candidate.state == State.DISCARDED:
        consensus_discarded = (
            isinstance(candidate.consensus, ConsensusResult)
            and candidate.consensus.routing == State.DISCARDED
        )
        discard_note = any(
            isinstance(note, str) and "discard" in note.lower() for note in candidate.notes
        )
        if not (consensus_discarded or discard_note):
            errors.append("DISCARDED requires discard consensus or discard reason")

    if candidate.consensus is not None:
        if candidate.consensus.routing not in {State.ACCEPTED, State.MANUAL_REVIEW, State.DISCARDED}:
            errors.append(f"consensus.routing {candidate.consensus.routing!r} is invalid")
        if not isinstance(candidate.consensus.auto_accept, bool):
            errors.append("consensus.auto_accept must be boolean")

    if errors:
        raise ValueError(
            f"Candidate {candidate.item_id!r} invariant validation failed: "
            + "; ".join(errors)
        )


def load_state_bundle(path: Path) -> tuple[dict[str, Candidate], dict | None]:
    """Load a state document and its immutable run manifest.

    Version 2 state uses ``{state_schema_version, run_manifest, candidates}``.
    A legacy root object keyed by item_id remains readable and is explicitly
    treated as a legacy run without a snapshot.
    """
    document = read_json(path)
    if not isinstance(document, dict):
        raise JsonPersistenceError(f"candidate state {path} must be an object")
    if "candidates" in document or STATE_MANIFEST_KEY in document or "state_schema_version" in document:
        if document.get("state_schema_version") != STATE_SCHEMA_VERSION:
            raise JsonPersistenceError(f"candidate state {path} has an unsupported schema version")
        if STATE_MANIFEST_KEY not in document:
            raise JsonPersistenceError(f"candidate state {path} is missing its run manifest")
        try:
            manifest = validate_run_manifest(document[STATE_MANIFEST_KEY])
        except (KeyError, TypeError, ValueError) as exc:
            raise JsonPersistenceError(f"candidate state {path} has an invalid run manifest: {exc}") from exc
        document = document.get("candidates")
        if not isinstance(document, dict):
            raise JsonPersistenceError(f"candidate state {path}.candidates must be an object keyed by item_id")
        config = config_from_run_manifest(manifest)
        legacy_mode = False
    else:
        # Historical state files are intentionally supported without rewriting
        # them. Their ACCEPTED validation uses the current legacy policy.
        manifest = None
        config = load_config()
        legacy_mode = True
    candidates: dict[str, Candidate] = {}
    for item_id, data in document.items():
        if not isinstance(data, dict):
            raise JsonPersistenceError(f"candidate state {path} entry {item_id!r} must be an object")
        try:
            candidate = dict_to_candidate(data, config=config, legacy_mode=legacy_mode)
        except (KeyError, TypeError, ValueError) as exc:
            raise JsonPersistenceError(
                f"candidate state {path} entry {item_id!r} failed invariant validation: {exc}"
            ) from exc
        if candidate.item_id != item_id:
            raise JsonPersistenceError(
                f"candidate state {path} key {item_id!r} does not match item_id {candidate.item_id!r}"
            )
        candidates[item_id] = candidate
    return candidates, manifest


def load_candidate_state(path: Path) -> dict[str, Candidate]:
    return load_state_bundle(path)[0]


def save_candidate_state(
    path: Path,
    candidates: dict[str, Candidate],
    run_manifest: dict | None = None,
) -> None:
    serialized = {item_id: candidate_to_dict(candidate) for item_id, candidate in candidates.items()}
    if run_manifest is None:
        # Direct library callers and historical fixture builders retain the
        # old root-object format. Live drivers always pass a manifest.
        atomic_write_json(path, serialized)
        return
    validated = validate_run_manifest(run_manifest)
    atomic_write_json(
        path,
        {
            "state_schema_version": STATE_SCHEMA_VERSION,
            STATE_MANIFEST_KEY: validated,
            "candidates": serialized,
        },
    )


def load_state_manifest(path: Path) -> dict | None:
    """Return a validated run manifest, or None for a legacy state file."""
    return load_state_bundle(path)[1]


def solver_batch_state_fingerprint(candidates: dict[str, Candidate]) -> str:
    """Fingerprint the persisted candidate document used to build a batch.

    The complete Candidate projection is intentional: a batch must become
    stale when any state, current Generator item, reviewer gate, or persisted
    Solver input changes.  The state file remains the source of truth; this is
    only a binding for the derived artifact.
    """
    state_projection = {
        item_id: candidate_to_dict(candidates[item_id])
        for item_id in sorted(candidates)
    }
    return canonical_json_sha256(state_projection)


def build_solver_batch_artifact(
    candidates: dict[str, Candidate], config: Optional[dict] = None
) -> dict:
    """Rebuild the Solver input artifact from already-persisted state.

    This function never uses a previous batch file.  Every SOLVING candidate
    must have a canonical, leak-free persisted payload, otherwise rebuilding
    fails closed and the caller must not invoke the Solver.
    """
    config = load_config() if config is None else config
    items: list[dict] = []
    for item_id in sorted(candidates):
        candidate = candidates[item_id]
        if candidate.state != State.SOLVING:
            continue
        if candidate.solver_input is None:
            raise ValueError(f"SOLVING candidate {item_id!r} has no persisted solver_input")
        canonical_errors = canonical_solver_input_errors(
            config, candidate.generator_item, candidate.solver_input
        )
        if canonical_errors:
            raise ValueError(f"{item_id}: {'; '.join(canonical_errors)}")
        ok, problems = leakage_guard(candidate.solver_input, candidate.section)
        if not ok:
            raise ValueError(f"{item_id}: solver_input leakage/shape invariant failed: {problems}")
        items.append(copy.deepcopy(candidate.solver_input))

    return {
        "artifact_version": 1,
        "state_fingerprint": solver_batch_state_fingerprint(candidates),
        "items": items,
    }


def validate_solver_batch_artifact(
    artifact: object, candidates: dict[str, Candidate], config: Optional[dict] = None
) -> list[str]:
    """Return errors if a Solver batch is absent, stale, or tampered."""
    if not isinstance(artifact, dict):
        return ["solver batch artifact must be an object"]
    try:
        structural_errors = schema_errors(artifact, load_schema(SOLVER_BATCH_SCHEMA_PATH))
    except SchemaValidationRuntimeError:
        raise
    if structural_errors:
        return [f"solver_input_batch.schema.json: {error}" for error in structural_errors]
    if artifact.get("artifact_version") != 1:
        return ["solver batch artifact has an unsupported or missing artifact_version"]
    if not isinstance(artifact.get("state_fingerprint"), str):
        return ["solver batch artifact is missing state_fingerprint"]
    if not isinstance(artifact.get("items"), list):
        return ["solver batch artifact is missing an items array"]
    try:
        expected = build_solver_batch_artifact(candidates, config)
    except (TypeError, ValueError, KeyError) as exc:
        return [f"current persisted state cannot produce a Solver batch: {exc}"]
    errors: list[str] = []
    if artifact["state_fingerprint"] != expected["state_fingerprint"]:
        errors.append("solver batch artifact is stale relative to persisted candidate state")
    if artifact["items"] != expected["items"]:
        errors.append("solver batch artifact items do not match persisted canonical Solver inputs")
    return errors


def finalization_id(candidates: dict[str, Candidate], versions: dict) -> str:
    """Return a repeatable identity for one finalized state/version snapshot."""
    digest = canonical_json_sha256({
        "versions": versions,
        "candidates": {
            item_id: candidate_to_dict(candidates[item_id])
            for item_id in sorted(candidates)
        },
    })
    return "finalize-" + digest.split(":", 1)[1][:24]


def build_retry_summary(candidate: Candidate) -> dict[str, dict[str, int]]:
    """Expose cumulative transient retry counters in final artifacts."""
    return {
        "system": {
            stage: candidate.system_failure_retries.get(stage, 0)
            for stage in RETRY_STAGES
        },
        "validation": {
            stage: candidate.validation_failure_retries.get(stage, 0)
            for stage in RETRY_STAGES
        },
    }


def _identity_errors(candidate: Candidate, item: object, stage: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{stage} item must be an object"]
    errors = []
    if item.get("item_id") != candidate.item_id:
        errors.append(
            f"{stage}.item_id={item.get('item_id')!r} does not match candidate.item_id={candidate.item_id!r}"
        )
    if item.get("section") != candidate.section:
        errors.append(
            f"{stage}.section={item.get('section')!r} does not match candidate.section={candidate.section!r}"
        )
    return errors


def _retry_limit(config: dict, kind: str) -> int:
    policy = config.get("retry_policy", {})
    key = (
        "max_system_failure_retries"
        if kind == "system"
        else "max_generation_validation_retries"
    )
    limit = policy.get(key)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError(f"retry_policy.{key} must be an integer >= 0")
    return limit


def record_stage_failure(
    candidate: Candidate,
    config: dict,
    *,
    kind: str,
    stage: str,
    detail: str,
) -> Candidate:
    """Record a stage failure and route it according to the shared retry policy.

    The first ``max_*`` failures leave the candidate in the stage-agnostic
    failure state. Once that budget is consumed, the candidate is routed to
    MANUAL_REVIEW. The counters are cumulative per stage and are deliberately
    independent of revision_count and generation_attempt.
    """
    if kind not in {"system", "content"}:
        raise ValueError(f"unknown failure kind: {kind!r}")
    if stage not in RETRY_STAGES:
        raise ValueError(f"unknown failure stage: {stage!r}")

    counters = (
        candidate.system_failure_retries
        if kind == "system"
        else candidate.validation_failure_retries
    )
    count = counters.get(stage, 0) + 1
    counters[stage] = count
    candidate.failure = FailureInfo(kind=kind, stage=stage, detail=str(detail))
    failed_state = State.GENERATION_FAILED if kind == "system" else State.VALIDATION_FAILED
    candidate.transition(failed_state, f"{stage} {kind} failure ({count}/{_retry_limit(config, kind)}): {detail}")

    if count > _retry_limit(config, kind):
        candidate.transition(
            State.MANUAL_REVIEW,
            f"{stage} {kind} retry limit exceeded; routed to MANUAL_REVIEW",
        )
    return candidate


def retry_failed_stage(candidate: Candidate, config: dict) -> Candidate:
    """Re-arm a retryable failed Candidate for the exact failed stage.

    Drivers call this immediately before supplying the next external agent
    output. It is safe to call only for a failure state whose retry budget is
    still available. Successful stage processing clears ``failure``; this
    helper clears it before the rerun so stale failure metadata cannot survive
    a successful retry.
    """
    if candidate.state not in {State.GENERATION_FAILED, State.VALIDATION_FAILED}:
        raise ValueError(
            f"retry_failed_stage requires a retryable failure state, got {candidate.state}"
        )
    if candidate.failure is None:
        raise ValueError("retry_failed_stage requires failure metadata")

    stage = candidate.failure.stage
    kind = candidate.failure.kind
    counters = (
        candidate.system_failure_retries
        if kind == "system"
        else candidate.validation_failure_retries
    )
    count = counters.get(stage, 0)
    limit = _retry_limit(config, kind)
    if count > limit:
        candidate.transition(
            State.MANUAL_REVIEW,
            f"{stage} {kind} retry limit exceeded; routed to MANUAL_REVIEW",
        )
        return candidate

    target = STAGE_RETRY_STATES[stage]
    candidate.transition(target, f"retrying {stage} after {kind} failure ({count}/{limit})")
    candidate.failure = None

    # A generator retry invalidates all downstream artifacts. A Reviewer
    # retry invalidates Solver/consensus artifacts. Solver retries may reuse
    # the already-blinded input, but never reuse a stale Solver verdict.
    if stage == "generator":
        candidate.reviewer_item = None
        candidate.solver_item = None
        candidate.solver_input = None
        candidate.leakage_check = None
        candidate.consensus = None
    elif stage == "reviewer":
        candidate.solver_item = None
        candidate.solver_input = None
        candidate.leakage_check = None
        candidate.consensus = None
    else:
        candidate.solver_item = None
        candidate.consensus = None
    return candidate


def _reject_identity(
    candidate: Candidate,
    config: dict,
    stage: str,
    item: object,
    errors: list[str],
) -> Candidate:
    detail = "; ".join(errors)
    return record_stage_failure(
        candidate,
        config,
        kind="content",
        stage=stage,
        detail=f"{stage} identity invariant failed: {detail}",
    )


def process_generation_output(candidate: Candidate, config: dict) -> Candidate:
    """Validate the Generator's candidate item against its own schema
    validator. Schema-shape failure -> VALIDATION_FAILED (content-shape,
    not quality). Cannot invoke the validator at all -> GENERATION_FAILED
    (system failure)."""
    if candidate.state != State.GENERATED:
        raise ValueError(
            f"process_generation_output requires state GENERATED, got {candidate.state}"
        )
    if candidate.generator_item is None:
        raise ValueError("process_generation_output requires generator_item")
    identity_errors = _identity_errors(candidate, candidate.generator_item, "generator")
    if identity_errors:
        return _reject_identity(candidate, config, "generator", candidate.generator_item, identity_errors)
    try:
        ok, output = run_schema_validator(
            config["paths"]["generator_validate_script"], [candidate.generator_item]
        )
    except SystemCallError as e:
        return record_stage_failure(
            candidate, config, kind="system", stage="generator", detail=str(e)
        )

    if not ok:
        return record_stage_failure(
            candidate,
            config,
            kind="content",
            stage="generator",
            detail=output.strip(),
        )

    candidate.failure = None
    candidate.transition(State.REVIEWING, "generator output passed schema validation")
    return candidate


def process_review_output(candidate: Candidate, config: dict) -> Candidate:
    """Route on Reviewer verdict. REVISE loops back for regeneration up to
    max_revision_cycles, then DISCARDED. REJECT ends this candidate
    immediately - it is never patched, only replaced by a fresh item_id
    (spec section 5/9)."""
    if candidate.state != State.REVIEWING:
        raise ValueError(
            f"process_review_output requires state REVIEWING, got {candidate.state}"
        )
    if candidate.reviewer_item is None:
        raise ValueError("process_review_output requires reviewer_item")
    identity_errors = _identity_errors(candidate, candidate.reviewer_item, "reviewer")
    if identity_errors:
        return _reject_identity(candidate, config, "reviewer", candidate.reviewer_item, identity_errors)
    max_cycles = config["retry_policy"]["max_revision_cycles"]

    try:
        ok, output = run_schema_validator(
            config["paths"]["reviewer_validate_script"], [candidate.reviewer_item]
        )
    except SystemCallError as e:
        return record_stage_failure(
            candidate, config, kind="system", stage="reviewer", detail=str(e)
        )
    if not ok:
        return record_stage_failure(
            candidate,
            config,
            kind="content",
            stage="reviewer",
            detail=output.strip(),
        )

    verdict = candidate.reviewer_item["verdict"]
    candidate.failure = None

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
    candidate: Candidate,
    config: dict,
    solver_item: Optional[dict],
    precomputed_solver_input: Optional[dict] = None,
) -> Candidate:
    """Only reachable from state SOLVING (i.e. only after Reviewer PASS).
    Derives the canonical allowlisted payload, runs the leakage guard,
    validates the (caller-supplied) solver_item against its schema, then
    applies the mechanical consensus rule.  Any caller-supplied or persisted
    payload that differs from the current Generator item is rejected before
    Solver validation or consensus."""
    if candidate.state != State.SOLVING:
        raise ValueError(
            f"process_solver_stage called on candidate in state {candidate.state}, "
            "not SOLVING - refusing to call Solver on a non-PASS item"
        )

    for stage, item in (("generator", candidate.generator_item), ("reviewer", candidate.reviewer_item)):
        if item is None:
            return _reject_identity(
                candidate,
                config,
                stage,
                item,
                [f"{stage} item is required before Solver"],
            )
        identity_errors = _identity_errors(candidate, item, stage)
        if identity_errors:
            return _reject_identity(candidate, config, stage, item, identity_errors)

    # Compute the canonical payload at this boundary for every path: a
    # caller-supplied precomputed payload, a persisted retry payload, and a
    # fresh blind.  Equality is checked before storing the selected payload so
    # a tampered payload cannot make a VALIDATION_FAILED state itself
    # impossible to persist on the next process boundary.
    try:
        expected_solver_input = canonicalize_solver_input(config, candidate.generator_item)
    except (TypeError, ValueError, KeyError) as exc:
        candidate.solver_input = None
        return record_stage_failure(
            candidate,
            config,
            kind="content",
            stage="solver",
            detail=f"canonical Solver input could not be derived: {exc}",
        )

    if precomputed_solver_input is not None:
        blinded = precomputed_solver_input
    elif candidate.solver_input is not None:
        # A transient Solver retry may reuse the exact persisted payload, but
        # only after it is compared with the current Generator item above.
        blinded = candidate.solver_input
    else:
        try:
            blinded = blind_for_solver(config, candidate.generator_item)
        except SystemCallError as exc:
            candidate.solver_input = None
            return record_stage_failure(
                candidate,
                config,
                kind="system",
                stage="solver",
                detail=f"during blinding: {exc}",
            )

    if blinded != expected_solver_input:
        candidate.solver_input = None
        return _reject_identity(
            candidate,
            config,
            "solver",
            blinded,
            [
                "solver input does not match the canonical blinded payload "
                "derived from the current generator_item"
            ],
        )

    input_identity_errors = _identity_errors(candidate, blinded, "solver_input")
    if input_identity_errors:
        candidate.solver_input = None
        return _reject_identity(candidate, config, "solver", blinded, input_identity_errors)
    ok, problems = leakage_guard(blinded, candidate.section)
    candidate.leakage_check = {"ok": ok, "problems": problems, "blinded_keys": sorted(blinded.keys())}
    if not ok:
        candidate.solver_input = None
        candidate.transition(State.MANUAL_REVIEW, f"leakage guard failed: {problems}")
        return candidate

    candidate.solver_input = blinded

    if solver_item is None:
        raise ValueError("solver_item must be supplied once a candidate reaches SOLVING")

    identity_errors = _identity_errors(candidate, solver_item, "solver")
    if identity_errors:
        return _reject_identity(candidate, config, "solver", solver_item, identity_errors)

    try:
        val_ok, output = run_schema_validator(
            config["paths"]["solver_validate_script"], [solver_item]
        )
    except SystemCallError as e:
        return record_stage_failure(
            candidate, config, kind="system", stage="solver", detail=str(e)
        )
    if not val_ok:
        return record_stage_failure(
            candidate,
            config,
            kind="content",
            stage="solver",
            detail=output.strip(),
        )

    candidate.solver_item = solver_item
    candidate.failure = None
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
    solver_input_hash = None
    if candidate.solver_input is not None:
        canonical = json.dumps(
            candidate.solver_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        solver_input_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    retry_summary = build_retry_summary(candidate)
    return {
        "item_id": candidate.item_id,
        "concept_id": candidate.concept_id,
        "state": candidate.state,
        "state_history": candidate.state_history,
        "generation_attempt": candidate.generation_attempt,
        "revision_count": candidate.revision_count,
        "retry_summary": retry_summary,
        "reviewer": candidate.reviewer_item,
        "solver": candidate.solver_item,
        "solver_input_sha256": solver_input_hash,
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


def build_provenance_record(
    candidate: Candidate,
    versions: dict,
    run_manifest: dict | None = None,
) -> dict:
    accepted = build_accepted_item(candidate, versions)
    audit = build_qa_audit(candidate, versions)
    planned_slot = candidate.planned_slot
    if planned_slot is None and candidate.generator_item is not None:
        # Direct replay callers from before planned_slot was introduced did
        # not populate the field.  Treat their first/current item as the
        # initial slot while keeping persisted revised Candidates explicit.
        planned_slot = derive_slot_requirements(candidate.generator_item)
    final_slot = derive_slot_requirements(candidate.generator_item) if candidate.generator_item else None
    record = {
        "item_id": candidate.item_id,
        "concept_id": candidate.concept_id,
        "section": candidate.section,
        "state": candidate.state,
        "state_history": candidate.state_history,
        "generation_attempt": candidate.generation_attempt,
        "revision_count": candidate.revision_count,
        "retry_summary": build_retry_summary(candidate),
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
        # ``batch_slot`` is retained as the compatibility name and now has a
        # stable, explicit meaning: the slot assigned at initial generation.
        "batch_slot": planned_slot,
        "planned_slot": planned_slot,
        "final_slot": final_slot,
        "versions": versions,
        "accepted_item": accepted,
        "qa_audit": audit,
    }
    if run_manifest is not None:
        validated_manifest = validate_run_manifest(run_manifest)
        record["run_manifest_id"] = validated_manifest["manifest_id"]
        record["run_manifest_sha256"] = validated_manifest["manifest_sha256"]
    return record


# ---------------------------------------------------------------------------
# Manual review queue (spec section 15)
# ---------------------------------------------------------------------------

def _manual_review_routing_reason(candidate: Candidate) -> str:
    """Classify why a candidate reached MANUAL_REVIEW for internal QA."""

    if candidate.leakage_check is not None and candidate.leakage_check.get("ok") is not True:
        return "leakage_guard_failure"
    if candidate.failure is not None:
        if any("retry limit exceeded" in note for note in candidate.notes):
            return "retry_exhaustion"
        return f"{candidate.failure.kind}_failure"
    if candidate.consensus is not None:
        if candidate.consensus.disagreement_reasons or candidate.consensus.failed_conditions:
            return "consensus_disagreement"
        return "consensus_non_accept"
    return "manual_review_routing"


def build_manual_review_entry(candidate: Candidate) -> dict:
    g = candidate.generator_item or {}
    r = candidate.reviewer_item or {}
    s = candidate.solver_item or {}
    consensus = None if candidate.consensus is None else {
        "auto_accept": candidate.consensus.auto_accept,
        "routing": candidate.consensus.routing,
        "failed_conditions": candidate.consensus.failed_conditions,
        "disagreement_reasons": candidate.consensus.disagreement_reasons,
    }
    failure = None if candidate.failure is None else {
        "kind": candidate.failure.kind,
        "stage": candidate.failure.stage,
        "detail": candidate.failure.detail,
    }
    return {
        "item_id": candidate.item_id,
        "section": candidate.section,
        "item": g,
        "routing_reason": _manual_review_routing_reason(candidate),
        "consensus": consensus,
        "failed_conditions": [] if consensus is None else consensus["failed_conditions"],
        "disagreement_reasons": [] if consensus is None else consensus["disagreement_reasons"],
        "failure": failure,
        "leakage_check": candidate.leakage_check,
        "notes": list(candidate.notes),
        "generator_answer": g.get("correct_answer"),
        "reviewer_answer": r.get("independent_answer"),
        "solver_answer": s.get("solver_answer"),
        "solver_confidence": s.get("confidence"),
        "issues": r.get("issues", []),
        "state_history": candidate.state_history,
        "possible_actions": ["ACCEPT", "REGENERATE", "DISCARD"],
    }


FINAL_SCHEMA_PATHS = {
    "accepted_item": REPO_ROOT / "orchestrator" / "schemas" / "accepted_item.schema.json",
    "qa_audit": REPO_ROOT / "orchestrator" / "schemas" / "qa_audit.schema.json",
    "provenance": REPO_ROOT / "orchestrator" / "schemas" / "provenance.schema.json",
}


def validate_final_record(record: dict) -> list[str]:
    """Validate the complete final artifact at the finalization boundary."""
    errors: list[str] = []
    if "planned_slot" in record and record.get("batch_slot") != record.get("planned_slot"):
        errors.append("batch_slot must equal planned_slot when both are present")
    try:
        provenance_schema = load_schema(FINAL_SCHEMA_PATHS["provenance"])
        qa_schema = load_schema(FINAL_SCHEMA_PATHS["qa_audit"])
        accepted_schema = load_schema(FINAL_SCHEMA_PATHS["accepted_item"])
        errors.extend(f"provenance.schema.json: {error}" for error in schema_errors(record, provenance_schema))
        if isinstance(record.get("qa_audit"), dict):
            errors.extend(f"qa_audit.schema.json: {error}" for error in schema_errors(record["qa_audit"], qa_schema))
        if record.get("accepted_item") is not None:
            errors.extend(
                f"accepted_item.schema.json: {error}"
                for error in schema_errors(record["accepted_item"], accepted_schema)
            )
    except SchemaValidationRuntimeError:
        raise
    return errors


def append_manual_review_queue(config: dict, entries: list[dict]) -> Path:
    configured = Path(config["paths"]["manual_review_queue"])
    path = configured if configured.is_absolute() else REPO_ROOT / configured
    with exclusive_file_lock(path):
        if path.exists():
            document = read_json(path)
            if not isinstance(document, dict) or not isinstance(document.get("items"), list):
                raise JsonPersistenceError(
                    f"manual review queue {path} must be an object containing an items array"
                )
            existing = document["items"]
        else:
            existing = []
        existing_ids: set[str] = set()
        for entry in existing:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_id"), str):
                raise JsonPersistenceError(
                    f"manual review queue {path} contains an entry without a valid item_id"
                )
            if entry["item_id"] in existing_ids:
                raise JsonPersistenceError(
                    f"manual review queue {path} contains duplicate item_id {entry['item_id']!r}"
                )
            existing_ids.add(entry["item_id"])
        incoming_by_id: dict[str, dict] = {}
        incoming_order: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_id"), str):
                raise JsonPersistenceError("new manual review entry has no valid item_id")
            item_id = entry["item_id"]
            if item_id not in incoming_by_id:
                incoming_order.append(item_id)
            # Last entry for an item in one append operation is the newest
            # snapshot and must win deterministically.
            incoming_by_id[item_id] = entry

        merged: list[dict] = []
        replaced_ids: set[str] = set()
        for entry in existing:
            item_id = entry["item_id"]
            if item_id in incoming_by_id:
                merged.append(incoming_by_id[item_id])
                replaced_ids.add(item_id)
            else:
                merged.append(entry)
        for item_id in incoming_order:
            if item_id not in replaced_ids and item_id not in existing_ids:
                merged.append(incoming_by_id[item_id])
        atomic_write_json(path, {"items": merged})
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

    @staticmethod
    def _dims_from_slot(slot: dict) -> dict[str, str]:
        dims = {
            "primary_target": slot.get("primary_target"),
            "difficulty": slot.get("difficulty"),
            "correct_answer_position": slot.get("correct_answer_position"),
            "vocabulary_domain": slot.get("vocabulary_domain"),
        }
        if slot.get("section") == "Written Expression":
            dims["tested_error_type"] = slot.get("tested_error_type")
        return dims

    def record_planned(self, generator_item: dict, planned_slot: Optional[dict] = None) -> None:
        self._bump(
            self.planned,
            self._dims_from_slot(planned_slot) if planned_slot is not None else self._dims(generator_item),
        )

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
