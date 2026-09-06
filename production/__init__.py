"""Deterministic Production Assembly: read/validate/normalize/export only.

No model calls occur in this package. See production/cli.py for the CLI
entrypoint and production/assembly.py for the public assembly API.
"""

from __future__ import annotations

from .assembly import ProductionAssemblyError, assemble_problem_bank, write_problem_bank

__all__ = ["ProductionAssemblyError", "assemble_problem_bank", "write_problem_bank"]
