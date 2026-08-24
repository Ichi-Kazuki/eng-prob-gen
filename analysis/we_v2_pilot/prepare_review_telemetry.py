#!/usr/bin/env python3
"""Attach available invocation telemetry to live Reviewer artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "analysis" / "we_v2_pilot" / "raw"
BATCH = "we-v2-live-pilot-20260824"
PROMPT = ROOT / ".claude" / "agents" / "toefl-itp-we-reviewer-v2.md"
INVOCATIONS = {
    "01": "01a0323f-c885-7493-b769-85e8a967cca0",
    "02": "01a0323f-c9df-76f0-934c-62543b87e4eb",
    "03": "01a0323f-cbd4-77c3-9c3b-1090e8537f8b",
    "04": "01a0323f-cde2-78e3-b9db-ddf9f7bf86e5",
    "05": "01a0323f-cfe4-7dc0-8d09-2bb27edb67e3",
    "06": "01a0323f-d237-7491-ba2e-30ee44ea5600",
    "07": "01a03244-7e8c-7c72-a775-df7e370cbba1",
    "08": "01a03244-8092-7d51-83ca-b59c55cb5b95",
    "09": "01a03244-8331-7c72-a7f0-3707d42dab95",
}


def main() -> int:
    prompt_hash = "sha256:" + hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    for micro, invocation_id in INVOCATIONS.items():
        path = RAW / f"review_r1_{BATCH}-micro-{micro}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for review in payload["items"]:
            provenance = review["provenance"]
            provenance["prompt_hash"] = prompt_hash
            provenance["invocation_id"] = invocation_id
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"prepared reviewer micro-{micro}: {len(payload['items'])} items; invocation={invocation_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
