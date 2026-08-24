#!/usr/bin/env python3
"""Materialize the four permitted revision results and telemetry."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "analysis" / "we_v2_pilot"
RAW = PILOT / "raw"
BATCH = "we-v2-live-pilot-20260824"
sys.path.insert(0, str(PILOT))
from pilot_validation import build_validation_report, load_json  # noqa: E402

CONFIG_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "config" / "we_v2_format_config.json"
GRAMMAR_SPEC_PATH = ROOT / "specs" / "toefl_itp_grammar_spec.json"
TAXONOMY_PATH = ROOT / "analysis" / "grammar_taxonomy.json"
ITEM_SCHEMA_PATH = ROOT / "agents" / "toefl_itp_we_generator_v2" / "schema" / "written_expression_item_v2.schema.json"
GEN_PROMPT = ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md"
REV_PROMPT = ROOT / ".claude" / "agents" / "toefl-itp-we-reviewer-v2.md"
GEN_INVOCATIONS = {
    "we-v2-pilot-001": "01a0324a-9ac5-7fc3-b0c9-c475fb395203",
    "we-v2-pilot-006": "01a0324a-9dbf-7e53-94e8-514d014e5b5e",
    "we-v2-pilot-009": "01a0324a-a137-7e51-9d68-2d327f33ea77",
    "we-v2-pilot-019": "01a0324a-a5a5-7bb2-8d88-787971ca9af2",
}
REV_INVOCATIONS = {
    "we-v2-pilot-001": "01a0324e-17b6-79b3-b680-a5bc1b57c174",
    "we-v2-pilot-006": "01a0324e-1924-7e11-9dd1-29d8c715fa25",
    "we-v2-pilot-009": "01a0324e-1ba9-7622-83b1-2970f4f72103",
    "we-v2-pilot-019": "01a0324e-1dfa-7fe3-bb6b-f32a1ec01aa7",
}


def main() -> int:
    initial_path = PILOT / "we_v2_pilot_initial_items.json"
    initial = json.loads(initial_path.read_text(encoding="utf-8"))
    items = {item["item_id"]: item for item in initial["items"]}
    gen_hash = "sha256:" + hashlib.sha256(GEN_PROMPT.read_bytes()).hexdigest()
    reviewer_hash = "sha256:" + hashlib.sha256(REV_PROMPT.read_bytes()).hexdigest()
    revision_records = []

    for item_id, gen_invocation in GEN_INVOCATIONS.items():
        path = RAW / f"revision_gen_{item_id}.json"
        source_errors: list[str] = []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            payload = {}
            source_errors.append(f"could not load revision: {type(exc).__name__}: {exc}")
        revision_items = payload.get("items") if isinstance(payload, dict) else None
        revised = revision_items[0] if isinstance(revision_items, list) and revision_items else {}
        if not isinstance(revised, dict) or revised.get("item_id") != item_id:
            actual_id = revised.get("item_id") if isinstance(revised, dict) else None
            source_errors.append(f"revision item_id mismatch: expected {item_id}, got {actual_id}")
            # Replace the slot with a deliberately invalid, keyed record so a
            # stale prior final cohort can never remain eligible downstream.
            revised = {"item_id": item_id}
        # Preserve the revised record even when its contract is malformed;
        # the recorded validation result below will keep it out of Solver and
        # consensus instead of allowing the initial pass to survive.
        provenance = revised.setdefault("provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}
            revised["provenance"] = provenance
        provenance["prompt_hash"] = gen_hash
        provenance["invocation_id"] = gen_invocation
        items[item_id] = revised
        revision_records.append({
            "item_id": item_id,
            "generator_revision_file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "generator_revision_invocation_id": gen_invocation,
            "reviewer_revision_file": f"analysis/we_v2_pilot/raw/review_r2_{item_id}.json",
            "reviewer_revision_invocation_id": REV_INVOCATIONS[item_id],
            "reviewer_revision_prompt_hash": reviewer_hash,
            "revision_cycle": 1,
            "source_errors": source_errors,
        })

    plan = load_json(PILOT / "we_v2_pilot_plan.json")
    item_schema = load_json(ITEM_SCHEMA_PATH)
    config = load_json(CONFIG_PATH)
    grammar = load_json(GRAMMAR_SPEC_PATH)
    taxonomy = load_json(TAXONOMY_PATH)
    targets = {entry["id"] for entry in taxonomy["primary_targets"]}
    error_types = {
        entry["id"] for entry in grammar["tested_error_types"]
        if entry["id"] not in {"fragment", "wrong_complementation"}
    }
    final_items = [
        items[item_id]
        for item_id in sorted(
            items,
            key=lambda item_key: items[item_key].get("provenance", {}).get("item_generation_order", 0),
        )
    ]
    validation = build_validation_report(
        final_items,
        plan,
        item_schema,
        config,
        targets,
        error_types,
        run_id=BATCH,
        stage="final_after_revisions",
        source_items="analysis/we_v2_pilot/we_v2_pilot_final_items.json",
    )
    validation_by_id = {record["item_id"]: record for record in validation["items"]}
    for record in revision_records:
        result = validation_by_id[record["item_id"]]
        record["generator_schema_pass"] = result["generator_schema_pass"]
        record["format_validator_pass"] = result["format_validator_pass"]
        record["plan_conformance_pass"] = result["plan_conformance_pass"]
        record["generator_schema_errors"] = result["generator_schema_errors"]
        record["format_validator_errors"] = result["format_validator_errors"]
        record["plan_mismatches"] = result["plan_mismatches"]
    (PILOT / "we_v2_pilot_final_items.json").write_text(json.dumps({
        "run": {
            "run_id": BATCH,
            "source_initial_items": "analysis/we_v2_pilot/we_v2_pilot_initial_items.json",
            "initial_candidate_count": len(initial["items"]),
            "revised_item_ids": [x["item_id"] for x in revision_records],
            "replacement_generation": False,
            "validation_file": "analysis/we_v2_pilot/we_v2_pilot_final_format_validation.json",
        },
        "items": final_items,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    (PILOT / "we_v2_pilot_final_format_validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    provenance_path = PILOT / "we_v2_pilot_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    by_id = {x["item_id"]: x for x in provenance["items"]}
    for record in revision_records:
        by_id[record["item_id"]]["revision"] = record
        by_id[record["item_id"]]["revision_generator_provenance"] = items[record["item_id"]]["provenance"]
    provenance["run"]["revision_records"] = revision_records
    provenance_path.write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    invalid_revisions = [
        record["item_id"] for record in revision_records
        if not record["generator_schema_pass"] or not record["format_validator_pass"]
    ]
    print(f"materialized {len(revision_records)} revised items; final cohort remains {len(final_items)}")
    print(
        f"final Generator validation: schema={validation['generator_schema_pass']}/{len(final_items)} "
        f"format={validation['format_validator_pass']}/{len(final_items)} "
        f"plan={validation['plan_conformance_pass']}/{len(final_items)}"
    )
    if invalid_revisions:
        print(f"invalid revised Generator items: {invalid_revisions}")
    return 1 if invalid_revisions else 0


if __name__ == "__main__":
    raise SystemExit(main())
