#!/usr/bin/env python3
"""CLI for the WE grammar evidence producer.

Usage:
    python -m we_evidence.cli --generator-output PATH --output-dir PATH \\
        [--provider claude|codex] [--model NAME]

Exit codes:
    0  PASS
    1  QUARANTINE (semantic/contract failure)
    2  invalid arguments, or a system/infrastructure failure
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from we_evidence.pipeline import GrammarEvidenceError, produce_grammar_evidence


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produce the WE grammar-evidence sidecar.")
    parser.add_argument("--generator-output", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--provider", choices=("claude", "codex"), default=None)
    parser.add_argument("--model", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if not args.generator_output.is_file():
        print(f"CONTENT ERROR: Generator output not found: {args.generator_output}", file=sys.stderr)
        return 2

    try:
        result = produce_grammar_evidence(
            args.generator_output,
            output_dir=args.output_dir,
            provider=args.provider,
            model=args.model,
        )
    except GrammarEvidenceError as exc:
        print(f"CONTENT ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # infrastructure/system failure boundary
        print(f"SYSTEM ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    summary = {
        "decision": result["decision"],
        "item_count": result["item_count"],
        "auditor_invocation_count": result["auditor_invocation_count"],
        "production_validator_pass": result["production_validator_pass"],
        "grammar_evidence_path": result["evidence_output_path"],
    }
    print(json.dumps(summary, ensure_ascii=False))

    if result["decision"] == "PASS":
        return 0
    if result["decision"] == "INFRASTRUCTURE_FAILURE":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
