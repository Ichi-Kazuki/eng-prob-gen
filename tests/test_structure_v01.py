"""Offline contract and integration tests for isolated Structure v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from runtime.adapters import InvocationRequest, InvocationResult
from structure.blinding import blind_input_errors, build_blind_input
from structure.contracts import (
    LETTERS,
    normalized_option_surface,
    validate_generator_contract,
    validate_plan,
    validate_reviewer_contract,
    validate_solver_contract,
)
from structure.permutation import PERMUTATION_VERSION, permute_generator_output
from structure.pipeline import AGENT_PATHS, GENERATOR_AGENT, REVIEWER_AGENT, SOLVER_AGENT, StructurePipeline
from structure.planner import CLAUSE_COUNT_WEIGHTS, LENGTH_BINS, PRIMARY_TARGET_WEIGHTS, build_plan, load_profile
from runtime.codex_schema import build_codex_transport_schema
from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_ITEM_SCHEMA = ROOT / "structure" / "schemas" / "generator_item.schema.json"
STRUCTURE_OUTPUT_SCHEMA = ROOT / "structure" / "schemas" / "generator_output.schema.json"


def generator_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    return {"items": [{
        "item_id": planned["item_id"], "section": "Structure", "primary_target": planned["primary_target"],
        "subtype": planned["subtype"], "secondary_features": ["academic register"],
        "difficulty": planned["difficulty"], "vocabulary_domain": f"generator-owned domain {index + 1}",
        "stem": "The researcher ____ the documented pattern in the archive.",
        "options": {"A": "is", "B": "are", "C": "be", "D": "being"}, "correct_answer": "A",
        "answer_explanation": "The singular subject requires the finite form is.",
        "distractor_rationales": {
            "A": "Correct singular finite completion.", "B": "Plural agreement is incorrect.",
            "C": "The base form cannot fill this finite slot.", "D": "The participle cannot fill this finite slot.",
        },
    } for index, planned in enumerate(plan["items"])]}


def reviewer_fixture(blind: dict[str, Any], *, first_best: str | None = None, natural: bool = True, serious: bool = False) -> dict[str, Any]:
    items = []
    for index, item in enumerate(blind["items"]):
        correct = next(letter for letter in LETTERS if item["options"][letter] == "is")
        items.append({
            "item_id": item["item_id"],
            "option_judgments": {letter: ("VALID" if letter == correct else "INVALID") for letter in LETTERS},
            "best_answer": first_best if index == 0 and first_best is not None else correct,
            "natural_wording": natural, "serious_defect": serious,
            "comment": "Only one option forms the intended sentence.",
        })
    return {"items": items}


def solver_fixture(blind: dict[str, Any], *, first_answer: str | None = None, confidence: str = "HIGH") -> dict[str, Any]:
    items = []
    for index, item in enumerate(blind["items"]):
        correct = next(letter for letter in LETTERS if item["options"][letter] == "is")
        items.append({
            "item_id": item["item_id"],
            "answer": first_answer if index == 0 and first_answer is not None else correct,
            "confidence": confidence, "reason": "The singular finite completion is the only acceptable choice.",
        })
    return {"items": items}


class FixtureRuntime:
    provider = "offline-fixture"
    cli_version = "offline-fixture"
    model = "offline-fixture"

    def __init__(self, *, reviewer: dict[str, Any] | None = None, solver: dict[str, Any] | None = None) -> None:
        self.reviewer_override = reviewer
        self.solver_override = solver
        self.requests: list[InvocationRequest] = []

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
        if request.stage == "structure_generator":
            parsed = generator_fixture(payload)
        elif request.stage == "structure_reviewer":
            parsed = self.reviewer_override or reviewer_fixture(payload)
        elif request.stage == "structure_solver":
            parsed = self.solver_override or solver_fixture(payload)
        else:  # pragma: no cover
            raise AssertionError(f"unexpected stage: {request.stage}")
        return InvocationResult(
            stage=request.stage, agent_name=request.agent_name, invocation_id=f"offline-{len(self.requests)}",
            started_at="2026-01-01T00:00:00+00:00", completed_at="2026-01-01T00:00:01+00:00",
            provider=self.provider, model=self.model, cli_version=self.cli_version, parsed=parsed,
            input_keys=list(request.input_keys),
        )


class StructurePlannerTests(unittest.TestCase):
    def test_replay_and_different_seed(self) -> None:
        self.assertEqual(build_plan(17), build_plan(17))
        self.assertNotEqual(build_plan(17), build_plan(18))

    def test_plan_size_profile_and_boundaries(self) -> None:
        plan = build_plan(91)
        self.assertEqual(len(plan["items"]), 15)
        self.assertEqual(validate_plan(plan), [])
        self.assertNotIn("vocabulary_domains", load_profile())
        self.assertTrue(all("vocabulary_domain" not in item for item in plan["items"]))
        self.assertTrue(all(item["primary_target"] in PRIMARY_TARGET_WEIGHTS for item in plan["items"]))
        self.assertNotIn("WORD_CLASS_FORM", {item["primary_target"] for item in plan["items"]})
        self.assertTrue(all(item["clause_count"] in CLAUSE_COUNT_WEIGHTS for item in plan["items"]))
        self.assertEqual(CLAUSE_COUNT_WEIGHTS, {1: 27, 2: 37, 3: 10, 4: 1})
        for item in plan["items"]:
            self.assertGreaterEqual(item["target_word_count"], item["sentence_length_bin"]["minimum"])
            self.assertLessEqual(item["target_word_count"], item["sentence_length_bin"]["maximum"])
        self.assertEqual([(entry["minimum"], entry["maximum"]) for entry in LENGTH_BINS], [(10, 14), (15, 19), (20, 24), (25, 27)])

    def test_plan_schema_does_not_own_vocabulary_domain(self) -> None:
        schema = json.loads(Path("structure/schemas/plan.schema.json").read_text(encoding="utf-8"))
        item_schema = schema["properties"]["items"]["items"]
        self.assertNotIn("vocabulary_domain", item_schema["required"])
        self.assertNotIn("vocabulary_domain", item_schema["properties"])


class StructurePromptTests(unittest.TestCase):
    @staticmethod
    def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0] != "---":
            raise AssertionError(f"{path} does not start with YAML frontmatter")
        try:
            closing = lines.index("---", 1)
        except ValueError as exc:
            raise AssertionError(f"{path} does not close its YAML frontmatter") from exc

        metadata: dict[str, str] = {}
        for line in lines[1:closing]:
            key, separator, value = line.partition(":")
            if not separator or not key or not value.strip():
                raise AssertionError(f"invalid scalar YAML frontmatter line in {path}: {line!r}")
            value = value.strip()
            if value.startswith('"') or value.endswith('"'):
                if not (value.startswith('"') and value.endswith('"')):
                    raise AssertionError(f"invalid quoted YAML frontmatter value in {path}: {line!r}")
                value = json.loads(value)
            metadata[key] = value
        return metadata, "\n".join(lines[closing + 1:])

    def test_structure_agent_definitions_have_matching_toolless_frontmatter(self) -> None:
        expected = {
            GENERATOR_AGENT: (AGENT_PATHS[GENERATOR_AGENT], "# Structure v0.1 Generator"),
            REVIEWER_AGENT: (AGENT_PATHS[REVIEWER_AGENT], "# Structure v0.1 Blind Reviewer"),
            SOLVER_AGENT: (AGENT_PATHS[SOLVER_AGENT], "# Structure v0.1 Blind Solver"),
        }
        for agent_name, (path, content_marker) in expected.items():
            with self.subTest(agent=agent_name):
                frontmatter, content = self.parse_frontmatter(path)
                self.assertEqual(set(frontmatter), {"name", "description", "tools"})
                self.assertEqual(frontmatter["name"], agent_name)
                self.assertTrue(frontmatter["description"])
                self.assertEqual(frontmatter["tools"], "")
                self.assertIn(content_marker, content)

    def test_generator_prompt_uses_all_planner_construction_targets(self) -> None:
        prompt = Path("structure/prompts/generator.md").read_text(encoding="utf-8")
        for field in ("primary_target", "difficulty", "clause_count", "sentence_length_bin", "target_word_count"):
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", prompt)
        self.assertIn("choose `vocabulary_domain` while authoring", prompt)
        self.assertIn("not a\n  value selected from a closed Structure domain enum or pool", prompt)
        self.assertIn("missing_required_element", prompt)
        self.assertIn("extraneous_element", prompt)
        self.assertIn("wrong_word_order", prompt)
        self.assertIn("fragment", prompt)
        self.assertIn("Do not review, score, self-review,", prompt)

    def test_generator_prompt_distinguishes_invalidity_from_rescuable_variation(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "clearly unacceptable in the",
            "less likely",
            "less idiomatic",
            "less formal",
            "more informal",
            "semantically different",
            "contextually less expected",
            "tense or temporal reference",
            "definiteness",
            "attachment",
            "possession",
            "modern standard usage",
            "concrete grammatical or structural defect",
            '"less natural", "different meaning", "less common", or "more formal"',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_has_target_specific_semantic_guardrails(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Conditionals / tense",
            "another reasonable timeline",
            "structurally decisive",
            "**Inversion:**",
            "`if`, `unless`, or",
            "independently grammatical conditional clause",
            "**Articles / determiners:**",
            "unspecified prior context",
            "`a` versus `an`",
            "**Relative pronoun case:**",
            "bare object position",
            "fronted-preposition environment",
            "clear subject-relative position",
            "following noun",
            "**NONFINITE_VERB_PHRASES: ordinal/superlative noun + infinitive:**",
            "the first/second/only/best ... to ...",
            "`-ing` participial form as a distractor",
            "grammatical reduced relative/participial modifier",
            "past participle",
            "another grammatical reduced relative",
            "alternative nonfinite form is invalid",
            "ordinal/superlative infinitive relationship",
            "local morphology or syntax creates a definite structural defect",
            "another valid modifier analysis",
            "**Appositive / word order:**",
            "structurally defective",
            "**Noun-clause subjects:**",
            "semantically natural for a fact",
            "implausible physical agent",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_reviewer_prompt_is_blind_and_covers_ambiguity_and_naturalness(self) -> None:
        prompt = " ".join(Path("structure/prompts/reviewer.md").read_text(encoding="utf-8").split())
        self.assertIn(
            "The input contains only `item_id`, `section`, `stem`, and `options`.",
            prompt,
        )
        self.assertIn("ordinary modern standard written English", prompt)
        for phrase in (
            "reasonable alternative reading",
            "do NOT mark it `INVALID`",
            "more textbook-like",
            "more formal",
            "different plausible tense interpretation",
            "definiteness",
            "attachment or possession",
            "Treat any such defensible alternative reading as a threat to uniqueness",
            "object-position `who`",
            "traditional prescriptive grammar prefers `whom`",
            "Apply the who/whom distinction by structural position",
            "Bare object position",
            "bare object relative position",
            "`who` may be acceptable in modern standard written English",
            "purely prescriptive `whom` rule",
            "Immediately after a fronted preposition",
            "fronted-preposition relative position",
            "a human antecedent requires the objective relative form `whom`",
            "for a human antecedent, `whom` is the standard written-English form",
            "`preposition + who`",
            "Do not mark `preposition + who`",
            "not an equally valid standard-written-English alternative",
            "colloquial speech may contain it",
            "pronoun immediately governed by the fronted preposition",
            "not a general style preference",
            "Do not globally prohibit stranded-preposition constructions",
            "`the researcher who I collaborated with`",
            "not invalid solely because a fronted-preposition construction is available",
            "semantically and logically coherent",
            "implausible or incoherent cause/effect relationship",
            "incompatible subject-predicate semantic roles",
            "unnatural proposition/fact predicate",
            "contradictory or incoherent temporal relations",
            "high-quality TOEFL-style item",
            "Do not fail merely for stylistic preference",
            "serious_defect=true",
            "substantial semantic/naturalness defect",
            "do not rewrite the item",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_solver_prompt_and_contract_remain_unchanged(self) -> None:
        solver_prompt = Path("structure/prompts/solver.md").read_bytes()
        self.assertEqual(
            hashlib.sha256(solver_prompt).hexdigest(),
            "c3a67804621efef18fa706845959921afd95725f12157d6bfed249c273e54593",
        )
        for schema_name, expected_hash in {
            "solver_input.schema.json": "2a511be9e2192f45b8928c3612eb5083af29abc2b05ab31aa4d231d7f4b958e8",
            "solver_output.schema.json": "1e791bb296e808bff2fe25d6d94db22602aa3f68211b3691b967b26be43f4937",
        }.items():
            with self.subTest(schema=schema_name):
                actual_hash = hashlib.sha256((Path("structure/schemas") / schema_name).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

    def test_planner_validation_and_pipeline_boundaries_remain_unchanged(self) -> None:
        expected_hashes = {
            "structure/planner.py": "14dfb5e994df7cd1396710d543f0397eef9bd8c67e00a282e891be50ca7003ca",
            "structure/profile.json": "f72612c4aa64b22d1910b812d598839f069cb50c43805354448e4d8af1fb8671",
            "structure/contracts.py": "1ee03109636d96d332c39b640786fdaaa6651350e87bebc0af3c3c2d95729f70",
            "structure/pipeline.py": "9dcd003d6279f8240b476de9bc2c59d36c7846760c85479de8edcf88389ccc2b",
            "structure/blinding.py": "b39dcdad846adda25d46784c5d75b75e49f5b01d44df75a011bfe2c96546b351",
            "structure/permutation.py": "1efdba8054a14540ba838e31c2b57401faf97770c6da3ea14ea9850cc8c31b42",
        }
        for relative_path, expected_hash in expected_hashes.items():
            with self.subTest(path=relative_path):
                actual_hash = hashlib.sha256(Path(relative_path).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)


class StructurePermutationTests(unittest.TestCase):
    def test_exact_answer_distribution_and_replay(self) -> None:
        source = generator_fixture(build_plan(31))
        first, record = permute_generator_output(source, 31)
        second, record_again = permute_generator_output(source, 31)
        self.assertEqual(first, second)
        self.assertEqual(record, record_again)
        self.assertEqual(record["version"], PERMUTATION_VERSION)
        self.assertEqual(sorted(record["final_answer_position_distribution"].values()), [3, 4, 4, 4])
        self.assertEqual(sum(record["final_answer_position_distribution"].values()), 15)

    def test_distractor_rationales_follow_the_option_mapping(self) -> None:
        source = generator_fixture(build_plan(32))
        permuted, record = permute_generator_output(source, 32)
        for source_item, output_item, mapping in zip(source["items"], permuted["items"], record["items"]):
            for canonical, original in mapping["canonical_to_original"].items():
                self.assertEqual(output_item["options"][canonical], source_item["options"][original])
                self.assertEqual(output_item["distractor_rationales"][canonical], source_item["distractor_rationales"][original])


class StructureContractTests(unittest.TestCase):
    def test_structure_stem_pattern_survives_codex_transport(self) -> None:
        item_schema = load_schema(STRUCTURE_ITEM_SCHEMA)
        output_schema = load_schema(STRUCTURE_OUTPUT_SCHEMA)
        self.assertEqual(item_schema["properties"]["stem"]["pattern"], "____")
        self.assertEqual(output_schema["$defs"]["item"]["properties"]["stem"]["pattern"], "____")

        transport_schema = build_codex_transport_schema(STRUCTURE_OUTPUT_SCHEMA)
        self.assertEqual(transport_schema["$defs"]["item"]["properties"]["stem"]["pattern"], "____")
        self.assertEqual(schema_errors(generator_fixture(build_plan(39)), output_schema), [])

    def test_structure_stem_requires_exactly_one_blank_marker(self) -> None:
        plan = build_plan(46)
        cases = (
            ("The researcher examined the documented pattern.", False),
            ("The researcher ____ examined the ____ pattern.", False),
            ("The researcher ____ examined the documented pattern.", True),
        )
        for stem, valid in cases:
            with self.subTest(stem=stem):
                output = generator_fixture(plan)
                output["items"][0]["stem"] = stem
                errors = validate_generator_contract(output, plan)
                self.assertEqual(not errors, valid)
                if not valid:
                    self.assertTrue(any("stem must contain exactly one '____' blank marker" in error for error in errors))

    def test_generator_owns_nonempty_free_form_vocabulary_domain(self) -> None:
        plan = build_plan(40)
        output = generator_fixture(plan)
        output["items"][0]["vocabulary_domain"] = "quantum textile conservation and civic data"
        self.assertEqual(validate_generator_contract(output, plan), [])

        missing = copy.deepcopy(output)
        del missing["items"][0]["vocabulary_domain"]
        self.assertTrue(any("vocabulary_domain" in error for error in validate_generator_contract(missing, plan)))

        blank = copy.deepcopy(output)
        blank["items"][0]["vocabulary_domain"] = ""
        self.assertTrue(any("vocabulary_domain" in error for error in validate_generator_contract(blank, plan)))

    def test_duplicate_option_and_unicode_surface_detection(self) -> None:
        self.assertEqual(normalized_option_surface("  Cafe" + chr(0x301) + "  "), normalized_option_surface("cafe" + chr(0x301)))
        output = generator_fixture(build_plan(41))
        output["items"][0]["options"]["B"] = "  IS  "
        self.assertTrue(any("duplicates option A" in error for error in validate_generator_contract(output, build_plan(41))))

    def test_missing_duplicate_ids_metadata_and_blank_are_rejected(self) -> None:
        plan = build_plan(42)
        output = generator_fixture(plan)
        output["items"][0]["item_id"] = output["items"][1]["item_id"]
        output["items"][1]["primary_target"] = "WORD_CLASS_FORM"
        output["items"][2]["stem"] = "The researcher examined the archive."
        errors = validate_generator_contract(output, plan)
        self.assertTrue(any("duplicate item_id" in error for error in errors))
        self.assertTrue(any("primary_target does not match" in error for error in errors))
        self.assertTrue(any("blank marker" in error for error in errors))

    def test_missing_or_malformed_item_ids_are_rejected(self) -> None:
        plan = build_plan(45)
        missing = generator_fixture(plan)
        missing["items"] = missing["items"][:-1]
        self.assertTrue(any("exactly 15" in error for error in validate_generator_contract(missing, plan)))
        malformed = generator_fixture(plan)
        malformed["items"][0] = "not an item"
        self.assertTrue(validate_generator_contract(malformed, plan))

    def test_blind_inputs_are_allowlisted_and_leakage_is_rejected(self) -> None:
        plan = build_plan(43)
        generator = generator_fixture(plan)
        blind = build_blind_input(generator)
        self.assertEqual(set(blind["items"][0]), {"item_id", "section", "stem", "options"})
        self.assertEqual(blind_input_errors(generator, blind, plan), [])
        leaked = copy.deepcopy(blind)
        leaked["items"][0]["correct_answer"] = "A"
        self.assertTrue(blind_input_errors(generator, leaked, plan))

    def test_reviewer_and_solver_contracts_reject_leakage(self) -> None:
        plan = build_plan(44)
        blind = build_blind_input(generator_fixture(plan))
        reviewer = reviewer_fixture(blind)
        reviewer["items"][0]["correct_answer"] = "A"
        solver = solver_fixture(blind)
        solver["items"][0]["primary_target"] = "CLAUSE_STRUCTURE"
        self.assertTrue(validate_reviewer_contract(reviewer, blind, plan))
        self.assertTrue(validate_solver_contract(solver, blind, plan))


class StructurePipelineTests(unittest.TestCase):
    def run_fixture(self, runtime: FixtureRuntime) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as directory:
            result = StructurePipeline(runtime).run(51, output_dir=Path(directory))
            for filename in ("plan.json", "generator_raw.json", "generator.json", "reviewer_input.json", "reviewer.json", "solver_input.json", "solver.json", "result.json"):
                self.assertTrue((Path(directory) / filename).is_file())
            self.assertTrue((Path(directory) / "provenance" / "provenance.json").is_file())
            return result

    def test_clean_fixture_accepts_with_exactly_three_logical_calls(self) -> None:
        runtime = FixtureRuntime()
        result = self.run_fixture(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(result["live_invocation_count"], 3)
        self.assertEqual([request.stage for request in runtime.requests], ["structure_generator", "structure_reviewer", "structure_solver"])
        self.assertEqual([request.agent_name for request in runtime.requests], [GENERATOR_AGENT, REVIEWER_AGENT, SOLVER_AGENT])
        self.assertEqual(sorted(result["final_answer_position_distribution"].values()), [3, 4, 4, 4])

    def test_one_defective_item_quarantines_the_whole_set(self) -> None:
        plan = build_plan(51)
        permuted, _ = permute_generator_output(generator_fixture(plan), 51)
        blind = build_blind_input(permuted)
        correct = next(letter for letter in LETTERS if blind["items"][0]["options"][letter] == "is")
        bad_best = next(letter for letter in LETTERS if letter != correct)
        result = self.run_fixture(FixtureRuntime(reviewer=reviewer_fixture(blind, first_best=bad_best)))
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(sum(item["accepted"] for item in result["item_results"]), 14)
        self.assertTrue(result["item_results"][0]["rejection_reasons"])

    def test_each_final_gate_blocks_accept(self) -> None:
        plan = build_plan(51)
        permuted, _ = permute_generator_output(generator_fixture(plan), 51)
        blind = build_blind_input(permuted)
        correct = next(letter for letter in LETTERS if blind["items"][0]["options"][letter] == "is")
        wrong = next(letter for letter in LETTERS if letter != correct)
        marginal = reviewer_fixture(blind)
        marginal["items"][0]["option_judgments"][wrong] = "MARGINAL"
        cases = {
            "reviewer_ambiguous": (reviewer_fixture(blind, first_best="AMBIGUOUS"), None),
            "reviewer_none": (reviewer_fixture(blind, first_best="NONE"), None),
            "solver_ambiguous": (None, solver_fixture(blind, first_answer="AMBIGUOUS")),
            "solver_none": (None, solver_fixture(blind, first_answer="NONE")),
            "reviewer_key_disagreement": (reviewer_fixture(blind, first_best=wrong), None),
            "solver_key_disagreement": (None, solver_fixture(blind, first_answer=wrong)),
            "low_confidence": (None, solver_fixture(blind, confidence="LOW")),
            "serious_defect": (reviewer_fixture(blind, serious=True), None),
            "unnatural_wording": (reviewer_fixture(blind, natural=False), None),
            "marginal_uniqueness": (marginal, None),
        }
        for name, (reviewer, solver) in cases.items():
            with self.subTest(case=name):
                result = self.run_fixture(FixtureRuntime(reviewer=reviewer, solver=solver))
                self.assertEqual(result["decision"], "QUARANTINE")

    def test_blind_payloads_have_no_private_fields(self) -> None:
        runtime = FixtureRuntime()
        result = self.run_fixture(runtime)
        for request in runtime.requests[1:]:
            payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
            self.assertEqual(set(payload), {"items"})
            self.assertEqual(set(payload["items"][0]), {"item_id", "section", "stem", "options"})
            self.assertNotIn("correct_answer", request.prompt)
            self.assertNotIn("primary_target", request.prompt)
            self.assertNotIn("distractor_rationales", request.prompt)
        self.assertEqual(result["infrastructure"]["invocation_counts"], {"generator": 1, "reviewer": 1, "solver": 1})


if __name__ == "__main__":
    unittest.main()
