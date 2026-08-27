#!/usr/bin/env python3
"""Prepare an external detached worktree for the final quality pilot.

This is a preparation command only.  It does not invoke a model or start a
pilot.  The caller must pass the exact commit that should be evaluated, then
run ``scripts/run_live_e2e.py`` from the printed worktree with an external
``WE_E2E_OUTPUT_DIR``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.freeze import create_detached_worktree  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="exact commit to evaluate")
    parser.add_argument(
        "--worktree",
        required=True,
        type=Path,
        help="new worktree path outside the development checkout",
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path.cwd(),
        help="development checkout containing the commit (default: current directory)",
    )
    args = parser.parse_args(argv)
    repository = args.repository.resolve()
    worktree = args.worktree.resolve()
    try:
        worktree.relative_to(repository)
    except ValueError:
        pass
    else:
        parser.error("--worktree must be outside --repository")

    resolved_commit = create_detached_worktree(
        repository,
        worktree,
        commit=args.commit,
    )
    print(
        json.dumps(
            {
                "source_worktree": str(worktree),
                "exact_commit": resolved_commit,
                "detached": True,
                "model_invocations": 0,
                "next_step": (
                    "Run scripts/run_live_e2e.py from this worktree with "
                    "WE_E2E_OUTPUT_DIR set to an external output directory."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
