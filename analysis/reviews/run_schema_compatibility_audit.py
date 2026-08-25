"""Run every committed artifact through the new runtime schema gate.

Read-only audit. It never rewrites an artifact and never relaxes a schema; a
FAIL here is a finding to be triaged, not something to be patched away by
loosening `required` or `additionalProperties`.

Usage:
    python analysis/reviews/run_schema_compatibility_audit.py [output.json]

Default output: analysis/reviews/schema_runtime_compatibility.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.schema_validation import load_schema, schema_errors  # noqa: E402

SCHEMAS = {
    "structure_item": ROOT / "agents/toefl_itp_grammar_generator/schema/structure_item.schema.json",
    "written_expression_item": ROOT / "agents/toefl_itp_grammar_generator/schema/written_expression_item.schema.json",
    "reviewer_output": ROOT / "agents/toefl_itp_grammar_reviewer/schema/reviewer_output.schema.json",
    "solver_output": ROOT / "agents/toefl_itp_grammar_solver/schema/solver_output.schema.json",
    "written_expression_item_v2": ROOT / "agents/toefl_itp_we_generator_v2/schema/written_expression_item_v2.schema.json",
    "reviewer_output_v2": ROOT / "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json",
    "accepted_item": ROOT / "orchestrator/schemas/accepted_item.schema.json",
}

# (group, relative path, schema key). "generator_by_section" picks the
# Structure or Written Expression schema from each item's own `section`.
TARGETS: list[tuple[str, str, str]] = [
    # -- pilot accepted items ------------------------------------------------
    ("pilot accepted items", "analysis/pilot/pilot_accepted_items.json", "accepted_item"),
    # -- validation artifacts ------------------------------------------------
    ("validation artifacts", "analysis/pilot/pilot_initial_items.json", "generator_by_section"),
    ("validation artifacts", "analysis/pilot/round1_generator_structure.json", "generator_by_section"),
    ("validation artifacts", "analysis/pilot/round1_generator_we.json", "generator_by_section"),
    ("validation artifacts", "analysis/pilot/revision_round2_structure.json", "generator_by_section"),
    ("validation artifacts", "analysis/pilot/revision_round2_we.json", "generator_by_section"),
    ("validation artifacts", "analysis/generator_smoke_test.json", "generator_by_section"),
    # -- reviewer artifacts (v1) --------------------------------------------
    ("reviewer artifacts", "analysis/reviewer_smoke_test.json", "reviewer_output"),
    ("reviewer artifacts", "analysis/reviewer_adversarial_test_results.json", "reviewer_output"),
    ("reviewer artifacts", "analysis/reviewer_reject_test_results.json", "reviewer_output"),
    ("reviewer artifacts", "analysis/pilot/round1_reviewer_structure.json", "reviewer_output"),
    ("reviewer artifacts", "analysis/pilot/round1_reviewer_we.json", "reviewer_output"),
    ("reviewer artifacts", "analysis/pilot/round2_reviewer_structure.json", "reviewer_output"),
    ("reviewer artifacts", "analysis/pilot/round2_reviewer_we.json", "reviewer_output"),
    # -- solver artifacts ----------------------------------------------------
    ("solver artifacts", "analysis/solver_smoke_test.json", "solver_output"),
    ("solver artifacts", "analysis/solver_adversarial_test.json", "solver_output"),
    ("solver artifacts", "analysis/pilot/solver_output_round1.json", "solver_output"),
    # -- WE v2 smoke ---------------------------------------------------------
    ("WE v2 smoke", "analysis/we_v2/we_v2_smoke_items.json", "written_expression_item_v2"),
    ("WE v2 smoke", "analysis/we_v2/we_v2_smoke_review.json", "reviewer_output_v2"),
    ("WE v2 smoke", "analysis/we_v2/we_v2_smoke_solver.json", "solver_output"),
    # -- WE v2 pilot ---------------------------------------------------------
    ("WE v2 pilot", "analysis/we_v2_pilot/we_v2_pilot_final_items.json", "written_expression_item_v2"),
    # -- WE v2 validation ----------------------------------------------------
    ("WE v2 validation", "analysis/we_v2_validation/we_v2_validation_initial_items.json", "written_expression_item_v2"),
    ("WE v2 validation", "analysis/we_v2_validation/we_v2_validation_accepted.json", "written_expression_item_v2"),
]


def load_items(path: Path) -> list[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"unrecognised top-level shape: {path}")


def schema_for(item: Any, schema_key: str) -> tuple[str, dict[str, Any]] | tuple[str, None]:
    if schema_key != "generator_by_section":
        return schema_key, load_schema(SCHEMAS[schema_key])
    section = item.get("section") if isinstance(item, dict) else None
    if section == "Structure":
        return "structure_item", load_schema(SCHEMAS["structure_item"])
    if section == "Written Expression":
        return "written_expression_item", load_schema(SCHEMAS["written_expression_item"])
    return "unknown_section", None


def audit() -> dict[str, Any]:
    records = []
    for group, relpath, schema_key in TARGETS:
        path = ROOT / relpath
        if not path.exists():
            records.append({
                "group": group, "artifact": relpath, "schema": schema_key,
                "status": "MISSING", "item_count": 0, "pass_count": 0, "fail_count": 0,
                "failures": [],
            })
            continue
        items = load_items(path)
        failures = []
        for index, item in enumerate(items):
            resolved_key, schema = schema_for(item, schema_key)
            item_id = item.get("item_id", f"#{index}") if isinstance(item, dict) else f"#{index}"
            if schema is None:
                failures.append({
                    "item_id": item_id, "schema": resolved_key,
                    "errors": ["item has no recognisable `section`, so no schema applies"],
                })
                continue
            errors = schema_errors(item, schema)
            if errors:
                failures.append({"item_id": item_id, "schema": resolved_key, "errors": errors})
        records.append({
            "group": group, "artifact": relpath, "schema": schema_key,
            "status": "PASS" if not failures else "FAIL",
            "item_count": len(items),
            "pass_count": len(items) - len(failures),
            "fail_count": len(failures),
            "failures": failures,
        })

    groups: dict[str, dict[str, int]] = {}
    for record in records:
        bucket = groups.setdefault(record["group"], {"artifacts": 0, "items": 0, "pass": 0, "fail": 0})
        bucket["artifacts"] += 1
        bucket["items"] += record["item_count"]
        bucket["pass"] += record["pass_count"]
        bucket["fail"] += record["fail_count"]

    return {
        "audit": "historical artifact compatibility with the runtime schema gate",
        "read_only": True,
        "schema_subset": "shared/schema_validation.py",
        "artifact_count": len(records),
        "artifact_pass_count": sum(r["status"] == "PASS" for r in records),
        "artifact_fail_count": sum(r["status"] == "FAIL" for r in records),
        "artifact_missing_count": sum(r["status"] == "MISSING" for r in records),
        "item_count": sum(r["item_count"] for r in records),
        "item_pass_count": sum(r["pass_count"] for r in records),
        "item_fail_count": sum(r["fail_count"] for r in records),
        "by_group": groups,
        "artifacts": records,
    }


def main() -> int:
    report = audit()
    out = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parent / "schema_runtime_compatibility.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Artifacts: {report['artifact_pass_count']} PASS / {report['artifact_fail_count']} FAIL "
          f"/ {report['artifact_missing_count']} MISSING (of {report['artifact_count']})")
    print(f"Items:     {report['item_pass_count']} PASS / {report['item_fail_count']} FAIL "
          f"(of {report['item_count']})")
    for record in report["artifacts"]:
        if record["status"] != "PASS":
            print(f"  [{record['status']}] {record['artifact']} "
                  f"({record['fail_count']}/{record['item_count']} items failed)")
            for failure in record["failures"][:5]:
                print(f"      {failure['item_id']}: {failure['errors'][0]}"
                      + (f" (+{len(failure['errors']) - 1} more)" if len(failure["errors"]) > 1 else ""))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
