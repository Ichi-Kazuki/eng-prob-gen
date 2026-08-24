"""Hard schema validation for TOEFL ITP Grammar Generator Agent output.

Spec section 9 scope only: structural/schema checks (option counts, correct_answer
range, taxonomy membership of enum-like fields). This does NOT judge grammatical
correctness, distractor quality, or "TOEFL-ITP-likeness" - that is Reviewer Agent's
job, not this script's.

Usage:
    python validate_output.py <path-to-generated-items.json>

Exit code 0 if every item passes; 1 if any item fails.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_JSON = REPO_ROOT / "specs" / "toefl_itp_grammar_spec.json"

DIFFICULTY_TIERS = {"EASY", "MEDIUM", "HARD"}
ERROR_SCOPES = {"local", "clause_level", "sentence_level", "cross_clause"}


def load_taxonomy_values():
    spec = json.loads(SPEC_JSON.read_text(encoding="utf-8"))
    primary_targets = {pt["id"] for pt in spec["primary_targets"]}
    tested_error_types = {t["id"] for t in spec["tested_error_types"]}
    return primary_targets, tested_error_types


def load_items(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("Unrecognized top-level JSON shape")


def validate_structure_item(item, primary_targets, errors):
    prefix = f"[{item.get('item_id', '?')}] "

    options = item.get("options")
    if not isinstance(options, dict) or set(options.keys()) != {"A", "B", "C", "D"}:
        errors.append(prefix + "options must have exactly keys A, B, C, D")
    else:
        for k, v in options.items():
            if not isinstance(v, str) or not v.strip():
                errors.append(prefix + f"options.{k} must be a non-empty string")

    correct = item.get("correct_answer")
    if correct not in {"A", "B", "C", "D"}:
        errors.append(prefix + "correct_answer must be one of A/B/C/D")
    elif isinstance(options, dict) and correct not in options:
        errors.append(prefix + "correct_answer does not point to an existing option")

    rationales = item.get("distractor_rationales")
    if not isinstance(rationales, dict) or set(rationales.keys()) != {"A", "B", "C", "D"}:
        errors.append(prefix + "distractor_rationales must have exactly keys A, B, C, D")

    pt = item.get("primary_target")
    if pt not in primary_targets:
        errors.append(prefix + f"primary_target '{pt}' is not one of the 15 taxonomy values")

    if item.get("difficulty") not in DIFFICULTY_TIERS:
        errors.append(prefix + "difficulty must be EASY/MEDIUM/HARD")

    if not isinstance(item.get("stem"), str) or not item["stem"].strip():
        errors.append(prefix + "stem must be a non-empty string")


def validate_written_expression_item(item, primary_targets, tested_error_types, errors):
    prefix = f"[{item.get('item_id', '?')}] "

    marked = item.get("marked_parts")
    if not isinstance(marked, dict) or set(marked.keys()) != {"A", "B", "C", "D"}:
        errors.append(prefix + "marked_parts must have exactly keys A, B, C, D")
    else:
        for k, v in marked.items():
            if not isinstance(v, str) or not v.strip():
                errors.append(prefix + f"marked_parts.{k} must be a non-empty string")

    correct = item.get("correct_answer")
    if correct not in {"A", "B", "C", "D"}:
        errors.append(prefix + "correct_answer must be one of A/B/C/D")
    elif isinstance(marked, dict) and correct not in marked:
        errors.append(prefix + "correct_answer does not point to an existing marked_parts entry")

    pt = item.get("primary_target")
    if pt not in primary_targets:
        errors.append(prefix + f"primary_target '{pt}' is not one of the 15 taxonomy values")

    tet = item.get("tested_error_type")
    if tet not in tested_error_types:
        errors.append(prefix + f"tested_error_type '{tet}' is not a valid taxonomy value")
    if tet == "fragment":
        errors.append(prefix + "tested_error_type 'fragment' is not possible for Written Expression (spec footnote 1)")
    if tet == "wrong_complementation":
        errors.append(prefix + "tested_error_type 'wrong_complementation' was superseded by wrong_preposition_collocation for this section (spec footnote 2)")

    if item.get("error_scope") not in ERROR_SCOPES:
        errors.append(prefix + "error_scope must be one of local/clause_level/sentence_level/cross_clause")

    if item.get("difficulty") not in DIFFICULTY_TIERS:
        errors.append(prefix + "difficulty must be EASY/MEDIUM/HARD")

    if not isinstance(item.get("sentence"), str) or not item["sentence"].strip():
        errors.append(prefix + "sentence must be a non-empty string")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)

    path = Path(sys.argv[1])
    primary_targets, tested_error_types = load_taxonomy_values()
    items = load_items(path)

    errors = []
    section_counts = {"Structure": 0, "Written Expression": 0}

    for item in items:
        section = item.get("section")
        if section == "Structure":
            section_counts["Structure"] += 1
            validate_structure_item(item, primary_targets, errors)
        elif section == "Written Expression":
            section_counts["Written Expression"] += 1
            validate_written_expression_item(item, primary_targets, tested_error_types, errors)
        else:
            errors.append(f"[{item.get('item_id', '?')}] section must be 'Structure' or 'Written Expression', got {section!r}")

    print(f"Checked {len(items)} item(s): {section_counts}")
    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("All items passed hard schema validation (section 9 scope only).")
    sys.exit(0)


if __name__ == "__main__":
    main()
