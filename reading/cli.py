"""Command-line entry point for one Reading v0.1 generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import run_reading
from .planner import ALLOWED_DOMAINS
from .contracts import split_paragraphs, word_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and quality-gate one TOEFL ITP Reading v0.1 set")
    parser.add_argument("--seed", type=int, help="replayable non-negative planner seed")
    parser.add_argument("--domain", choices=ALLOWED_DOMAINS)
    parser.add_argument("--provider", choices=("claude", "codex"))
    parser.add_argument("--model")
    parser.add_argument("--output-dir", type=Path, help="directory for this first-pass run artifacts")
    args = parser.parse_args()

    result = run_reading(
        args.seed,
        domain=args.domain,
        output_dir=args.output_dir,
        provider=args.provider,
        model=args.model,
    )
    generator = result.get("generator") or {}
    passage = generator.get("passage", "") if isinstance(generator, dict) else ""
    questions = generator.get("questions", []) if isinstance(generator, dict) else []
    reviewer = result.get("reviewer") or {}
    solver = result.get("solver") or {}
    checks = result["checks"]
    print(json.dumps({
        "run_id": result["run_id"],
        "output_dir": str((args.output_dir or Path("runs") / "reading_v0_1" / result["run_id"]).resolve()),
        "generation": {
            "passage_word_count": word_count(passage) if passage else 0,
            "paragraph_count": len(split_paragraphs(passage)) if passage else 0,
            "question_types": [item.get("question_type") for item in questions],
            "generator_canonical_validation": checks["generator_canonical"],
            "deterministic_validation": checks["deterministic"],
        },
        "reviewer": {
            "contract_valid": checks["reviewer_contract"],
            "answers": [item.get("best_answer") for item in reviewer.get("questions", [])],
            "judgment": reviewer.get("set_judgment"),
            "ambiguous_none_count": sum(
                item.get("best_answer") in {"AMBIGUOUS", "NONE"}
                for item in reviewer.get("questions", [])
            ),
        },
        "solver": {
            "contract_valid": checks["solver_contract"],
            "answers": [item.get("answer") for item in solver.get("answers", [])],
            "ambiguous_none_count": sum(
                item.get("answer") in {"AMBIGUOUS", "NONE"}
                for item in solver.get("answers", [])
            ),
        },
        "consensus": {
            "per_question": checks["answer_agreement"],
            "accepted_question_count": sum(item.get("agree") is True for item in checks["answer_agreement"]),
            "whole_set_decision": result["decision"],
        },
        "infrastructure": {
            "live_invocations": result["infrastructure"]["live_invocations"],
            "leakage": checks["blind_errors"],
            "synthetic_fallback": result["infrastructure"]["synthetic_fallback"],
            "runtime_failures": result["infrastructure"]["runtime_failures"],
        },
    }, ensure_ascii=False, indent=2))
    return 0 if result["decision"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
