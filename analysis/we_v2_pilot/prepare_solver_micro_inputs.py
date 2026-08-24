#!/usr/bin/env python3
"""Split the already-blinded Solver input into independent microbatches."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "analysis" / "we_v2_pilot"
RAW = PILOT / "raw"
BATCH = "we-v2-live-pilot-20260824"
ALLOWLIST = {"item_id", "section", "sentence", "marked_parts"}


def main() -> int:
    source = json.loads((PILOT / "we_v2_pilot_solver_input.json").read_text(encoding="utf-8"))
    by_micro: dict[str, list[dict]] = {}
    for item in source["items"]:
        if set(item) != ALLOWLIST:
            raise ValueError(f"Solver leakage in {item.get('item_id')}: {sorted(set(item) - ALLOWLIST)}")
        suffix = (int(item["item_id"].rsplit("-", 1)[1]) - 1) // 3 + 1
        micro = f"{BATCH}-micro-{suffix:02d}"
        by_micro.setdefault(micro, []).append(item)
    for micro, items in sorted(by_micro.items()):
        path = RAW / f"solver_input_{micro}.json"
        path.write_text(json.dumps({
            "microbatch_id": micro,
            "generation_batch_id": BATCH,
            "blinding": "allowlist: item_id, section, sentence, marked_parts",
            "items": items,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"prepared {micro}: {len(items)} blind items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
