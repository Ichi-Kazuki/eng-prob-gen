"""Command-line entry point for historical v0.1 and current v0.2.4 Reading."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import run_reading, run_reading_batch
from .planner import ALLOWED_DOMAINS
from .contracts import split_paragraphs, word_count


CURRENT_READING_VERSION = "v0.2.4"
HISTORICAL_READING_VERSION = "v0.1"
V02_ONLY_OPTIONS = ("--count", "--parallel", "--mode")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate TOEFL ITP Reading passage sets")
    parser.add_argument(
        "--version",
        choices=(CURRENT_READING_VERSION, HISTORICAL_READING_VERSION),
        default=CURRENT_READING_VERSION,
        help="Reading pipeline version (default: v0.2.4; v0.1 requires an explicit compatibility choice)",
    )
    parser.add_argument("--seed", type=int, help="replayable non-negative planner seed")
    parser.add_argument("--count", type=int, help="v0.2 number of independent passage sets")
    parser.add_argument("--parallel", type=int, default=1, help="v0.2 maximum concurrently active passage pipelines")
    parser.add_argument("--mode", choices=("validated", "draft"), default="validated", help="v0.2 validated review or Generator-only UNVALIDATED_DRAFT mode")
    parser.add_argument("--domain", choices=ALLOWED_DOMAINS)
    parser.add_argument("--provider", choices=("claude", "codex"))
    parser.add_argument("--model")
    parser.add_argument("--output-dir", type=Path, help="directory for this first-pass run artifacts")
    return parser


def _explicit_v02_options(argv: list[str]) -> list[str]:
    options: list[str] = []
    for token in argv:
        option = token.split("=", 1)[0]
        if option in V02_ONLY_OPTIONS:
            options.append(token)
    return options


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    args = parser.parse_args(raw_argv)

    if args.version == HISTORICAL_READING_VERSION:
        incompatible = _explicit_v02_options(raw_argv)
        if incompatible:
            parser.error(
                "v0.1 compatibility mode does not accept current Reading options: "
                + ", ".join(incompatible)
            )
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

    # Current/default Reading is always the v0.2.4 calibration patch.  Even a single
    # passage uses the batch wrapper so current draft/batch controls cannot
    # accidentally enter the historical v0.1 path.
    batch = run_reading_batch(
        args.seed,
        count=args.count if args.count is not None else 1,
        parallel=args.parallel,
        mode=args.mode,
        domain=args.domain,
        output_dir=args.output_dir,
        provider=args.provider,
        model=args.model,
    )
    print(json.dumps(batch, ensure_ascii=False, indent=2))
    # A batch is intentionally not all-or-nothing: per-passage quality and
    # infrastructure outcomes are recorded in batch_result.json.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
