"""The public validation API of every agent must gate on the committed schema.

Root cause this file locks down
-------------------------------
Each ``agents/*/scripts/validate_output.py`` used to run the committed JSON
Schema inside ``main()`` only. The semantic-check functions were importable on
their own, so an internal caller doing ``validator.validate(record)`` or
``validator.validate_item(record, errors)`` got the semantic checks *without*
the structural schema gate. A Reviewer record carrying ``judgment_mode`` or
``grammar_quality_evaluable`` - properties the committed Reviewer schema does
not allow - therefore passed validation on the import path while failing on
the CLI path.

The invariant enforced here:

    Every public Agent-output validation path must enforce the structural
    schema before semantic validation, and the CLI and import paths must
    agree on every fixture.

The committed schemas are NOT relaxed to accommodate replay annotations;
those annotations live outside the formal agent contracts.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

WE_REVIEWER = "agents/toefl_itp_we_reviewer_v2/scripts/validate_output.py"
GRAMMAR_GENERATOR = "agents/toefl_itp_grammar_generator/scripts/validate_output.py"
GRAMMAR_REVIEWER = "agents/toefl_itp_grammar_reviewer/scripts/validate_output.py"
GRAMMAR_SOLVER = "agents/toefl_itp_grammar_solver/scripts/validate_output.py"
WE_GENERATOR = "agents/toefl_itp_we_generator_v2/scripts/validate_output.py"

ALL_VALIDATORS = (
    GRAMMAR_GENERATOR,
    GRAMMAR_REVIEWER,
    GRAMMAR_SOLVER,
    WE_GENERATOR,
    WE_REVIEWER,
)

# The two replay annotations that must never be admitted into a formal agent
# output contract, whichever path does the validating.
REPLAY_ANNOTATIONS = {
    "judgment_mode": "CONTRACT_REPLAY_ONLY",
    "grammar_quality_evaluable": False,
}


def load_validator(relpath: str):
    """Import an agent validator the way an internal caller would."""
    name = "pubapi_" + relpath.replace("/", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(relpath: str, payload) -> subprocess.CompletedProcess:
    """Run a validator CLI over a payload. Temporary output only."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "payload.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(ROOT / relpath), str(path)],
            capture_output=True, text=True, cwd=ROOT,
        )


def valid_we_reviewer_record() -> dict:
    data = json.loads((FIXTURES / "we_reviewer_v2_valid_record.json").read_text(encoding="utf-8"))
    return copy.deepcopy(data["items"][0])


class PublicApiSurfaceTests(unittest.TestCase):
    """Every validator exposes the same gated public entry point."""

    def test_every_validator_exposes_validate_contract(self) -> None:
        for relpath in ALL_VALIDATORS:
            with self.subTest(validator=relpath):
                module = load_validator(relpath)
                self.assertTrue(
                    callable(getattr(module, "validate_contract", None)),
                    f"{relpath} has no public validate_contract()",
                )

    def test_legacy_names_are_aliases_of_validate_contract(self) -> None:
        """A caller using the historical name must still hit the schema gate."""
        for relpath in ALL_VALIDATORS:
            module = load_validator(relpath)
            for legacy in ("validate", "validate_item"):
                alias = getattr(module, legacy, None)
                if alias is None:
                    continue
                with self.subTest(validator=relpath, name=legacy):
                    self.assertIs(
                        alias, module.validate_contract,
                        f"{relpath}.{legacy} is not validate_contract; it can bypass the schema gate",
                    )

    def test_semantic_stage_is_a_separate_named_function(self) -> None:
        """validate_semantics must exist and must NOT be the public gate."""
        for relpath in ALL_VALIDATORS:
            with self.subTest(validator=relpath):
                module = load_validator(relpath)
                semantics = getattr(module, "validate_semantics", None)
                self.assertTrue(callable(semantics), f"{relpath} has no validate_semantics()")
                self.assertIsNot(semantics, module.validate_contract)


class ImportedReviewerPathTests(unittest.TestCase):
    """Cases A-E from the audit, exercised through the Python import path.

    These deliberately do NOT shell out: the defect was that the import path
    skipped the structural schema, so the import path is what must be tested.
    """

    def setUp(self) -> None:
        self.module = load_validator(WE_REVIEWER)
        self.record = valid_we_reviewer_record()

    def test_a_schema_valid_record_passes(self) -> None:
        self.assertEqual(self.module.validate_contract(self.record), [])

    def test_b_judgment_mode_fails(self) -> None:
        record = dict(self.record, judgment_mode="CONTRACT_REPLAY_ONLY")
        errors = self.module.validate_contract(record)
        self.assertTrue(any("judgment_mode" in error for error in errors), errors)

    def test_c_grammar_quality_evaluable_fails(self) -> None:
        record = dict(self.record, grammar_quality_evaluable=False)
        errors = self.module.validate_contract(record)
        self.assertTrue(any("grammar_quality_evaluable" in error for error in errors), errors)

    def test_d_missing_required_field_fails(self) -> None:
        record = dict(self.record)
        del record["provenance"]
        errors = self.module.validate_contract(record)
        self.assertTrue(any("provenance" in error for error in errors), errors)

    def test_e_unknown_field_fails(self) -> None:
        record = dict(self.record, a_field_nobody_enumerated="leak")
        errors = self.module.validate_contract(record)
        self.assertTrue(any("a_field_nobody_enumerated" in error for error in errors), errors)

    def test_legacy_validate_alias_rejects_the_same_records(self) -> None:
        """The exact call shape that used to bypass the gate."""
        for name, mutate in (
            ("judgment_mode", lambda r: dict(r, judgment_mode="CONTRACT_REPLAY_ONLY")),
            ("grammar_quality_evaluable", lambda r: dict(r, grammar_quality_evaluable=False)),
        ):
            with self.subTest(field=name):
                self.assertTrue(self.module.validate(mutate(self.record)))

    def test_reviewer_schema_still_forbids_the_replay_annotations(self) -> None:
        """Guard against 'fixing' this by widening the committed schema."""
        schema = json.loads(
            (ROOT / "agents/toefl_itp_we_reviewer_v2/schema/reviewer_output_v2.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertIs(schema.get("additionalProperties"), False)
        for field in REPLAY_ANNOTATIONS:
            self.assertNotIn(field, schema.get("properties", {}))
            self.assertNotIn(field, schema.get("required", []))


class CliAndImportAgreeTests(unittest.TestCase):
    """The enforcement invariant: both public paths reach the same verdict."""

    def _cases(self) -> dict[str, dict]:
        record = valid_we_reviewer_record()
        missing_provenance = dict(record)
        del missing_provenance["provenance"]
        return {
            "A_valid": record,
            "B_judgment_mode": dict(record, judgment_mode="CONTRACT_REPLAY_ONLY"),
            "C_grammar_quality_evaluable": dict(record, grammar_quality_evaluable=False),
            "D_missing_required": missing_provenance,
            "E_unknown_field": dict(record, a_field_nobody_enumerated="leak"),
        }

    def test_cli_and_import_agree_on_every_fixture(self) -> None:
        module = load_validator(WE_REVIEWER)
        for name, record in self._cases().items():
            with self.subTest(case=name):
                import_failed = bool(module.validate_contract(record))
                cli_failed = run_cli(WE_REVIEWER, {"items": [record]}).returncode != 0
                self.assertEqual(
                    import_failed, cli_failed,
                    f"{name}: import path and CLI path disagree "
                    f"(import_failed={import_failed}, cli_failed={cli_failed})",
                )
                self.assertEqual(import_failed, name != "A_valid")

    def test_structural_failure_short_circuits_before_semantics(self) -> None:
        """A schema-invalid record must never reach the semantic stage."""
        module = load_validator(WE_REVIEWER)
        record = dict(valid_we_reviewer_record(), judgment_mode="CONTRACT_REPLAY_ONLY")
        errors = module.validate_contract(record)
        self.assertTrue(all("reviewer_output_v2.schema.json" in error for error in errors), errors)


class ReplayAnnotationsStayOutsideTheContractTests(unittest.TestCase):
    """Replay annotations are kept, but never inside a formal agent record."""

    def _runner(self):
        sys.path.insert(0, str(ROOT / "analysis" / "we_v2_validation"))
        spec = importlib.util.spec_from_file_location(
            "pubapi_run_validation", ROOT / "analysis" / "we_v2_validation" / "run_validation.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_replay_annotations_helper_carries_the_explicit_values(self) -> None:
        runner = self._runner()
        annotations = runner.replay_annotations("reviewer_records", ["x"])
        self.assertEqual(annotations["judgment_mode"], runner.JUDGMENT_MODE)
        self.assertIs(annotations["grammar_quality_evaluable"], False)
        self.assertEqual(annotations["grammar_quality_conclusion"], "NOT_EVALUATED")

    def test_reviewer_record_source_does_not_emit_the_annotations(self) -> None:
        source = (ROOT / "analysis" / "we_v2_validation" / "run_validation.py").read_text(encoding="utf-8")
        start = source.index("def reviewer_record(")
        body = source[start:source.index("\ndef ", start + 1)]
        for field in REPLAY_ANNOTATIONS:
            self.assertNotIn(f'"{field}":', body, f"reviewer_record still emits {field}")

    def test_solver_record_source_does_not_emit_the_annotations(self) -> None:
        source = (ROOT / "analysis" / "we_v2_validation" / "run_validation.py").read_text(encoding="utf-8")
        start = source.index("def solver_record(")
        body = source[start:source.index("\ndef ", start + 1)]
        for field in REPLAY_ANNOTATIONS:
            self.assertNotIn(f'"{field}":', body, f"solver_record still emits {field}")


class NoBypassCallersTests(unittest.TestCase):
    """No caller in the repo may reach an agent validator's semantic stage."""

    def test_no_caller_invokes_validate_semantics_on_an_agent_validator(self) -> None:
        offenders = []
        for path in ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.parent.name == "scripts" and path.name.startswith("validate_"):
                continue  # the validator defining it
            if path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "VALIDATOR.validate_semantics" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"bypass callers found: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
