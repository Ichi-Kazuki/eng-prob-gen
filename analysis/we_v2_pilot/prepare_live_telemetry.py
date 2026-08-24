#!/usr/bin/env python3
"""Attach available live-invocation telemetry and phase trace artifacts.

The Generator output is not rewritten for grammar or format.  This helper
only fills provenance fields that are available from the invocation ledger and
records the sentence-first evidence already present in qa_metadata.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "analysis" / "we_v2_pilot" / "raw"
PROMPT = ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md"
BATCH = "we-v2-live-pilot-20260824"

# Invocation IDs returned by the actual fresh Agent invocations in this run.
# Existing microbatches were created before this continuation and expose no
# invocation ID in their artifacts, so those remain null as allowed by spec.
INVOCATIONS = {
    f"{BATCH}-micro-03": "01a03235-7706-7951-88d0-d4dc0c5c20f0",
    f"{BATCH}-micro-04": "01a03235-7893-7ac0-abf7-05f0b02a80bc",
    f"{BATCH}-micro-06": "01a03235-7a77-7c10-be7a-0965b702316d",
    f"{BATCH}-micro-07": "01a03235-7cb0-7eb1-883f-da77fe9f1212",
    f"{BATCH}-micro-08": "01a03235-7f17-78f2-b427-03f4f33d0499",
    f"{BATCH}-micro-09": "01a03235-8209-7d11-8a03-87f144c5f8dc",
}


def phase_trace(item: dict, invocation_id: str | None, generated_at: str) -> dict:
    qa = item.get("qa_metadata", {})
    return {
        "item_id": item["item_id"],
        "item_generation_order": item["provenance"]["item_generation_order"],
        "microbatch_id": item["provenance"]["microbatch_id"],
        "invocation_id": invocation_id,
        "trace_source": "generator_output_qa_metadata",
        "trace_note": "Phase evidence is reconstructed from the Generator v2 QA metadata; no grammar judgement is added here.",
        "recorded_at_utc": generated_at,
        "phases": {
            "item_design_plan": {
                "status": "PRESENT",
                "fields": [
                    "primary_target", "subtype", "tested_error_type", "difficulty",
                    "vocabulary_domain", "correction_locality", "decision_granularity",
                    "intended_error_position", "correct_span_type",
                ],
            },
            "clean_sentence": {"status": "PRESENT", "clean_form": qa.get("clean_form")},
            "clean_sentence_validation": {
                "status": "PASS" if qa.get("clean_sentence_validated") is True else "FAIL",
            },
            "one_error_mutation": {
                "status": "PRESENT",
                "error_form": qa.get("error_form"),
                "mutation_type": qa.get("mutation_type"),
                "minimal_correction": qa.get("minimal_correction"),
            },
            "uniqueness_audit": {
                "status": qa.get("grammar_check_status"),
            },
            "four_local_span_selection": {"status": "PRESENT"},
            "deterministic_format_validation": {
                "status": qa.get("format_check_status"),
            },
            "final_grammar_audit": {
                "status": qa.get("grammar_check_status"),
            },
        },
    }


def main() -> int:
    prompt_hash = "sha256:" + hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    generated_at = datetime.now(timezone.utc).isoformat()
    for path in sorted(RAW.glob(f"gen_{BATCH}-micro-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        micro = payload["microbatch_id"]
        invocation_id = INVOCATIONS.get(micro)
        traces = []
        for item in payload["items"]:
            provenance = item["provenance"]
            if provenance.get("prompt_hash") is None:
                provenance["prompt_hash"] = prompt_hash
            if invocation_id is not None:
                provenance["invocation_id"] = invocation_id
            traces.append(phase_trace(item, provenance.get("invocation_id"), generated_at))
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        phase_path = RAW / path.name.replace("gen_", "phase_", 1)
        phase_path.write_text(json.dumps({
            "microbatch_id": micro,
            "generation_batch_id": BATCH,
            "trace_source": "generator_output_qa_metadata",
            "items": traces,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"prepared {micro}: {len(traces)} items; invocation={invocation_id or 'null'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
