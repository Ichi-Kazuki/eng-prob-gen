"""Blind human review runner for the Human Calibration set.

This tool does NOT grade, score, or judge any question. It only:
  1. Displays the blind (pipeline-answer-free) payload for one item at a time.
  2. Collects a human reviewer's own independent judgment.
  3. Saves that judgment to disk after every single answered item, so the
     session can be interrupted and resumed at any point.

It must never read analysis/validation/human_review_calibration_key.json,
and it must never display any pipeline/AI metadata (generator answer,
reviewer verdict, reviewer answer, solver answer, failure reason, pipeline
final state, source group, or any other field not explicitly listed as
displayable below).

Run:
    python analysis/validation/run_human_calibration_review.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
VAL = ROOT / "analysis" / "validation"

from shared.json_io import atomic_write_json  # noqa: E402

BLIND_PATH = VAL / "human_review_calibration_blind.json"
RESULTS_PATH = VAL / "human_review_results.json"

# Never open this file from this script, at any point, for any reason.
FORBIDDEN_KEY_PATH = VAL / "human_review_calibration_key.json"

# The ONLY fields of a blind item this tool is allowed to show a reviewer.
DISPLAYABLE_FIELDS = ("calibration_id", "section", "question", "options", "marked_parts")

VALIDITY_CHOICES = ["VALID", "INVALID", "AMBIGUOUS"]
UNIQUE_ANSWER_CHOICES = ["YES", "NO"]
HUMAN_ANSWER_CHOICES = ["A", "B", "C", "D", "NONE", "AMBIGUOUS"]
DIFFICULTY_CHOICES = ["TOO_EASY", "APPROPRIATE", "TOO_HARD"]
MAIN_PROBLEM_CHOICES = [
    "NONE",
    "grammar",
    "ambiguity",
    "semantics",
    "unnatural_english",
    "distractor_quality",
    "multiple_errors",
    "no_error",
    "metadata_not_applicable",
    "other",
]
DECISION_CHOICES = ["KEEP", "REVISE", "DISCARD"]


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_results(results: dict) -> None:
    atomic_write_json(RESULTS_PATH, results)


def load_results() -> dict:
    existing = load_json(RESULTS_PATH, default=None)
    if existing is None:
        return {
            "title": "Human Review Calibration Results",
            "source": "human_review_calibration_blind.json",
            "answers": {},
        }
    existing.setdefault("answers", {})
    return existing


def prompt_choice(label: str, choices: list[str]) -> str:
    choice_map = {str(i + 1): c for i, c in enumerate(choices)}
    while True:
        print(f"\n{label}")
        for num, c in choice_map.items():
            print(f"  {num}) {c}")
        raw = input("> ").strip()
        if raw in choice_map:
            return choice_map[raw]
        canonical_by_input = {choice.casefold(): choice for choice in choices}
        canonical = canonical_by_input.get(raw.casefold())
        if canonical is not None:
            return canonical
        print("Invalid input. Enter the number or the exact label shown above.")


def prompt_int_scale(label: str, lo: int, hi: int) -> int:
    while True:
        raw = input(f"\n{label} ({lo}-{hi})\n> ").strip()
        if raw.isdigit() and lo <= int(raw) <= hi:
            return int(raw)
        print(f"Invalid input. Enter an integer from {lo} to {hi}.")


def prompt_text(label: str) -> str:
    print(f"\n{label} (free text, Enter for empty)")
    return input("> ").strip()


def display_item(item: dict, index: int, total: int) -> None:
    print("\n" + "=" * 70)
    print(f"Question {index} / {total}")
    print("=" * 70)
    print(f"calibration_id: {item.get('calibration_id')}")
    print(f"section: {item.get('section')}")
    print()
    print(item.get("question", ""))

    if "options" in item:
        print()
        for key in ("A", "B", "C", "D"):
            if key in item["options"]:
                print(f"  {key}. {item['options'][key]}")

    if "marked_parts" in item:
        print()
        for key in ("A", "B", "C", "D"):
            if key in item["marked_parts"]:
                print(f"  {key}. {item['marked_parts'][key]}")


def review_one_item(item: dict, index: int, total: int) -> dict:
    display_item(item, index, total)

    validity = prompt_choice("validity:", VALIDITY_CHOICES)
    unique_answer = prompt_choice("unique_answer:", UNIQUE_ANSWER_CHOICES)
    human_answer = prompt_choice("human_answer:", HUMAN_ANSWER_CHOICES)
    naturalness = prompt_int_scale("naturalness:", 1, 5)
    toefl_itp_style = prompt_int_scale("toefl_itp_style:", 1, 5)
    difficulty = prompt_choice("difficulty:", DIFFICULTY_CHOICES)
    main_problem = prompt_choice("main_problem:", MAIN_PROBLEM_CHOICES)
    decision = prompt_choice("decision:", DECISION_CHOICES)
    comment = prompt_text("comment:")

    return {
        "calibration_id": item.get("calibration_id"),
        "validity": validity,
        "unique_answer": unique_answer,
        "human_answer": human_answer,
        "naturalness": naturalness,
        "toefl_itp_style": toefl_itp_style,
        "difficulty": difficulty,
        "main_problem": main_problem,
        "decision": decision,
        "comment": comment,
    }


def main() -> int:
    # Blindness guard: this script must never open FORBIDDEN_KEY_PATH anywhere
    # in this file. It is referenced above only to name what must stay untouched.

    if not BLIND_PATH.exists():
        print(f"Blind payload not found: {BLIND_PATH}")
        return 1

    blind = load_json(BLIND_PATH)
    items = blind.get("items", [])
    total = len(items)

    results = load_results()
    answers = results["answers"]

    remaining_items = [it for it in items if it.get("calibration_id") not in answers]

    if not remaining_items:
        print(f"Completed {len(answers)} / {total}")
        return 0

    for item in remaining_items:
        completed = len(answers)
        remaining = total - completed
        current_index = completed + 1

        print(f"\nCompleted: {completed}")
        print(f"Remaining: {remaining}")

        answer = review_one_item(item, current_index, total)
        answers[item["calibration_id"]] = answer
        save_results(results)

        if len(answers) >= total:
            break

    print(f"\nCompleted {len(answers)} / {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
