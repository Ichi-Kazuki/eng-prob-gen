"""Command-line entry point for Structure v0.3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import STRUCTURE_VERSION, run_structure_v03


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"seed must be a non-negative integer, got {value!r}")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate one TOEFL ITP Structure Part A v0.3 set")
    parser.add_argument("--version", action="version", version=STRUCTURE_VERSION)
    parser.add_argument("--provider", choices=("claude", "codex"))
    parser.add_argument("--model")
    parser.add_argument("--seed", type=_nonnegative_int, help="replayable non-negative Planner seed")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_structure_v03(
        seed=args.seed,
        provider=args.provider,
        model=args.model,
        output_dir=args.output_dir,
    )
    summary = {
        "run_id": result["run_id"],
        "version": result["version"],
        "seed": result["seed"],
        "decision": result["decision"],
        "question_count": result["question_count"],
        "live_invocation_count": result["live_invocation_count"],
        "generator_shard_calls_completed": result["generator_shard_calls_completed"],
        "generator_shard_contract_pass_count": result["generator_shard_contract_pass_count"],
        "merged_candidate_batch_constructed": result["merged_candidate_batch_constructed"],
        "deterministic_hard_failure_count": result["deterministic_hard_failure_count"],
        "candidate_selection_pass_count": result["candidate_selection_pass_count"],
        "candidate_selection_failure_count": result["candidate_selection_failure_count"],
        "solver_key_agreement_count": result["solver_key_agreement_count"],
        "solver_ambiguous_none_count": result["solver_ambiguous_none_count"],
        "final_answer_position_distribution": result["final_answer_position_distribution"],
        "output_dir": result["output_dir"],
    }
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["decision"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
