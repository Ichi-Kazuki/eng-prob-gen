"""Command-line entry point for Structure v0.1."""

from __future__ import annotations

import argparse
import json

from .pipeline import STRUCTURE_VERSION, run_structure


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate one TOEFL ITP Structure Part A set")
    parser.add_argument("--version", action="version", version=STRUCTURE_VERSION)
    parser.add_argument("--provider", choices=("claude", "codex"))
    parser.add_argument("--seed", type=int, help="replayable non-negative Planner seed")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_structure(seed=args.seed, provider=args.provider)
    summary = {
        "run_id": result["run_id"],
        "version": result["version"],
        "seed": result["seed"],
        "decision": result["decision"],
        "question_count": result["question_count"],
        "live_invocation_count": result["live_invocation_count"],
        "deterministic_hard_failure_count": result["deterministic_hard_failure_count"],
        "reviewer_solver_agreement": result["reviewer_solver_agreement"],
        "reviewer_ambiguous_none_count": result["reviewer_ambiguous_none_count"],
        "solver_ambiguous_none_count": result["solver_ambiguous_none_count"],
        "final_answer_position_distribution": result["final_answer_position_distribution"],
        "output_dir": result["output_dir"],
    }
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["decision"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
