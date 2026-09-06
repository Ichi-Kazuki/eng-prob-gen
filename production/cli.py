"""CLI entrypoint for deterministic Production Assembly.

Reads only explicitly supplied source paths; performs no auto-discovery, no
"latest run" selection, and no generation. See production/assembly.py for the
underlying read/validate/normalize/export contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .assembly import ProductionAssemblyError, write_problem_bank


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m production.cli",
        description="Assemble explicitly supplied production-eligible sources into one problem_bank.json.",
    )
    parser.add_argument("--structure-run", action="append", default=[], type=Path, dest="structure_runs")
    parser.add_argument("--we-run", action="append", default=[], type=Path, dest="we_runs")
    parser.add_argument("--we-evidence", action="append", default=[], type=Path, dest="we_evidence")
    parser.add_argument("--reading-run", action="append", default=[], type=Path, dest="reading_runs")
    parser.add_argument("--output", required=True, type=Path, dest="output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if len(args.we_runs) != len(args.we_evidence):
        print(
            "error: --we-run and --we-evidence must be supplied the same number of times "
            f"(got {len(args.we_runs)} run(s) and {len(args.we_evidence)} evidence file(s))",
            file=sys.stderr,
        )
        return 2
    if not args.structure_runs and not args.we_runs and not args.reading_runs:
        print(
            "error: at least one of --structure-run, --we-run, or --reading-run is required",
            file=sys.stderr,
        )
        return 2

    written_expression_sources = list(zip(args.we_runs, args.we_evidence))

    try:
        bank = write_problem_bank(
            args.output,
            structure_runs=args.structure_runs,
            written_expression_sources=written_expression_sources,
            reading_runs=args.reading_runs,
        )
    except ProductionAssemblyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = {
        "schema_version": bank["schema_version"],
        "source_count": bank["source_count"],
        "counts": bank["counts"],
        "output": str(args.output),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
