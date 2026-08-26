"""Create blinded Solver input from Generator/Reviewer-test candidate items.

Strips every field down to an ALLOWLIST per section, rather than trying to
remove a blacklist of "forbidden" fields. This is deliberate: an allowlist
stays safe even if the Generator's output schema grows new metadata fields
in the future (a blacklist would silently leak any new field it doesn't
yet know to remove).

Structure items keep only:   item_id, section, stem, options
Written Expression items keep only: item_id, section, sentence, marked_parts

Any other field on the source item (correct_answer, answer_explanation,
distractor_rationales, primary_target, subtype, secondary_features,
tested_error_type, difficulty, error_scope, minimal_correction, internal
"_"-prefixed test-fixture annotations, etc.) is dropped, unread.

Usage:
    python create_solver_input.py <input.json> <output.json>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shared.solver_blinding import canonical_solver_input  # noqa: E402


def load_items(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("Unrecognized top-level JSON shape")


def blind_item(item: dict) -> dict:
    # Keep this public wrapper for callers that imported the historical CLI
    # helper; the canonical implementation lives in shared code.
    return canonical_solver_input(item)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    items = load_items(in_path)
    blinded = [blind_item(item) for item in items]

    out_path.write_text(
        json.dumps({"items": blinded}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(blinded)} blinded item(s) to {out_path}")


if __name__ == "__main__":
    main()
