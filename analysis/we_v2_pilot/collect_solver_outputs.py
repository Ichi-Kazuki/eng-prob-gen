#!/usr/bin/env python3
"""Collect the nine live blind Solver outputs without altering answers."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "analysis" / "we_v2_pilot"
RAW = PILOT / "raw"
BATCH = "we-v2-live-pilot-20260824"
INVOCATIONS = {
    "01": "01a03253-4017-72d3-a99c-a71f82633d53",
    "02": "01a03253-41eb-7f70-b405-84a24e87c5bf",
    "03": "01a03253-4474-7621-ab39-5c1c1bc51c1a",
    "04": "01a03253-46d2-7812-a1bb-cc133288221f",
    "05": "01a03253-4a60-7272-a6c7-fc9c8fe408d3",
    "06": "01a03253-4e0a-7030-9aac-6e384762dfa7",
    "07": "01a03254-86ed-7911-8e88-2f77cff53aa8",
    "08": "01a03254-8815-71a0-a9ad-35d4b2babab1",
    "09": "01a03254-89b6-72e1-a416-6bf1944c1e30",
}


def main() -> int:
    items = []
    microbatches = []
    for micro, invocation_id in INVOCATIONS.items():
        path = RAW / f"solver_{BATCH}-micro-{micro}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        micro_items = payload["items"]
        items.extend(micro_items)
        microbatches.append({
            "microbatch_id": f"{BATCH}-micro-{micro}",
            "solver_file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "invocation_id": invocation_id,
            "item_count": len(micro_items),
        })
    items.sort(key=lambda x: int(x["item_id"].rsplit("-", 1)[1]))
    ids = [x["item_id"] for x in items]
    if len(items) != 25 or len(set(ids)) != 25:
        raise ValueError(f"expected 25 unique Solver results, got {len(items)} / {len(set(ids))}")
    (PILOT / "we_v2_pilot_solver.json").write_text(json.dumps({
        "run": {
            "run_id": BATCH,
            "solver_version": "existing blind Solver (unchanged)",
            "live_solver": True,
            "blind_input_source": "analysis/we_v2_pilot/we_v2_pilot_solver_input.json",
            "allowlist": ["item_id", "section", "sentence", "marked_parts"],
            "microbatches": microbatches,
        },
        "items": items,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"collected {len(items)} live blind Solver results from {len(microbatches)} microbatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
