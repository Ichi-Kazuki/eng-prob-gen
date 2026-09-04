"""Offline contract and integration tests for isolated Structure v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from runtime.adapters import InvocationRequest, InvocationResult
from structure.blinding import blind_input_errors, build_blind_input
from structure.contracts import (
    BLANK_MARKER,
    LETTERS,
    build_completed_sentence,
    canonicalize_reviewer_output,
    canonicalize_solver_output,
    count_words,
    normalized_option_surface,
    post_blind_comparison,
    REVIEWER_ANSWER_SENTINELS,
    reviewer_difficulty_diagnostic_reasons,
    reviewer_difficulty_diagnostics,
    reviewer_difficulty_summary,
    validate_generator_contract,
    validate_plan,
    validate_reviewer_contract,
    validate_solver_contract,
)
from structure.permutation import PERMUTATION_VERSION, permute_generator_output
from structure.pipeline import AGENT_PATHS, GENERATOR_AGENT, REVIEWER_AGENT, SOLVER_AGENT, StructurePipeline
from structure.planner import (
    CLAUSE_COUNT_WEIGHTS,
    DIFFICULTY_WEIGHTS,
    JOINT_STRUCTURAL_WEIGHTS,
    LENGTH_BINS,
    PRIMARY_TARGET_WEIGHTS,
    SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY,
    build_plan,
    load_profile,
    _sample_length,
)
from runtime.codex_schema import build_codex_transport_schema
from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_ITEM_SCHEMA = ROOT / "structure" / "schemas" / "generator_item.schema.json"
STRUCTURE_OUTPUT_SCHEMA = ROOT / "structure" / "schemas" / "generator_output.schema.json"


_STEM_FILLER_WORDS = (
    "in", "the", "archive", "during", "the", "extended", "review", "process",
    "for", "the", "ongoing", "study", "across", "multiple", "sessions", "before",
    "the", "final", "report", "was", "submitted", "to", "the", "committee",
)


def stem_for_word_count(word_count: int) -> str:
    """Build a fixture stem whose completed (blank -> 'is') word count is exact."""

    words = ["The", "researcher", BLANK_MARKER, "the", "documented", "pattern"]
    index = 0
    while len(words) < word_count:
        words.append(_STEM_FILLER_WORDS[index % len(_STEM_FILLER_WORDS)])
        index += 1
    words = words[:word_count]
    words[-1] = f"{words[-1]}."
    return " ".join(words)


def generator_fixture(plan: dict[str, Any]) -> dict[str, Any]:
    return {"items": [{
        "item_id": planned["item_id"], "section": "Structure", "primary_target": planned["primary_target"],
        "subtype": f"{planned['primary_target']} generator-authored construction {index + 1}",
        "secondary_features": ["academic register"],
        "difficulty": planned["difficulty"], "vocabulary_domain": f"generator-owned domain {index + 1}",
        "stem": stem_for_word_count(planned["target_word_count"]),
        "options": {"A": "is", "B": "are", "C": "be", "D": "being"}, "correct_answer": "A",
        "answer_explanation": "The singular subject requires the finite form is.",
        "distractor_rationales": {
            "A": "Correct singular finite completion.", "B": "Plural agreement is incorrect.",
            "C": "The base form cannot fill this finite slot.", "D": "The participle cannot fill this finite slot.",
        },
    } for index, planned in enumerate(plan["items"])]}


_UNSET = object()


def reviewer_fixture(
    blind: dict[str, Any],
    *,
    first_best: str | None = None,
    natural: bool = True,
    serious: bool = False,
    observed_difficulty: str | None = None,
    difficulty_confidence: str = "HIGH",
    first_observed_clause_count: Any = _UNSET,
) -> dict[str, Any]:
    planned_difficulties: dict[str, str] = {}
    if observed_difficulty is None and blind.get("items"):
        item_id = blind["items"][0].get("item_id", "")
        try:
            seed = int(item_id.split("-")[-2], 16)
            planned_difficulties = {
                item["item_id"]: item["difficulty"] for item in build_plan(seed)["items"]
            }
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            planned_difficulties = {}
    items = []
    for index, item in enumerate(blind["items"]):
        correct = next(letter for letter in LETTERS if item["options"][letter] == "is")
        best_answer = first_best if index == 0 and first_best is not None else correct
        if best_answer in LETTERS:
            best_answer_text = item["options"][best_answer]
        else:
            best_answer_text = best_answer
        if index == 0 and first_observed_clause_count is not _UNSET:
            observed_clause_count = first_observed_clause_count
        else:
            observed_clause_count = None if best_answer_text in REVIEWER_ANSWER_SENTINELS else 1
        items.append({
            "item_id": item["item_id"],
            "option_judgments": [
                {"option_text": item["options"][letter], "judgment": "VALID" if letter == correct else "INVALID"}
                for letter in LETTERS
            ],
            "best_answer_text": best_answer_text,
            "natural_wording": natural, "serious_defect": serious,
            "comment": "Only one option forms the intended sentence.",
            "observed_difficulty": observed_difficulty or planned_difficulties.get(item["item_id"], "EASY"),
            "difficulty_confidence": difficulty_confidence,
            "observed_clause_count": observed_clause_count,
        })
    return {"items": items}


def solver_fixture(
    blind: dict[str, Any], *, first_answer_text: str | None = None, confidence: str = "HIGH"
) -> dict[str, Any]:
    items = []
    for index, item in enumerate(blind["items"]):
        correct = next(letter for letter in LETTERS if item["options"][letter] == "is")
        items.append({
            "item_id": item["item_id"],
            "answer_text": (
                first_answer_text if index == 0 and first_answer_text is not None else item["options"][correct]
            ),
            "confidence": confidence, "reason": "The singular finite completion is the only acceptable choice.",
        })
    return {"items": items}


class FixtureRuntime:
    provider = "offline-fixture"
    cli_version = "offline-fixture"
    model = "offline-fixture"

    def __init__(
        self,
        *,
        generator: dict[str, Any] | None = None,
        reviewer: dict[str, Any] | None = None,
        solver: dict[str, Any] | None = None,
    ) -> None:
        self.generator_override = generator
        self.reviewer_override = reviewer
        self.solver_override = solver
        self.requests: list[InvocationRequest] = []

    def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        payload = json.loads(request.prompt.split("INPUT_JSON:\n", 1)[1])
        if request.stage == "structure_generator":
            parsed = self.generator_override or generator_fixture(payload)
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
        first = build_plan(17)
        second = build_plan(17)
        self.assertEqual(first, second)
        owned_fields = (
            "item_id", "order", "section", "primary_target", "difficulty", "clause_count",
            "sentence_length_bin", "target_word_count",
        )
        self.assertEqual(
            [{field: item[field] for field in owned_fields} for item in first["items"]],
            [{field: item[field] for field in owned_fields} for item in second["items"]],
        )
        self.assertNotEqual(build_plan(17), build_plan(18))

    def test_joint_structural_profile_has_exact_total_and_marginals(self) -> None:
        profile = load_profile()
        self.assertEqual(sum(JOINT_STRUCTURAL_WEIGHTS.values()), 75)

        target_marginal = {
            target: sum(
                weight for (item_target, _difficulty, _clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                if item_target == target
            )
            for target in profile["primary_target_weights"]
        }
        self.assertEqual(target_marginal, profile["primary_target_weights"])

        difficulty_marginal = {
            difficulty: sum(
                weight for (_target, item_difficulty, _clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                if item_difficulty == difficulty
            )
            for difficulty in DIFFICULTY_WEIGHTS
        }
        self.assertEqual(difficulty_marginal, {"EASY": 18, "MEDIUM": 42, "HARD": 15})

        clause_marginal = {
            clause_count: sum(
                weight for (_target, _difficulty, item_clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                if item_clause_count == clause_count
            )
            for clause_count in CLAUSE_COUNT_WEIGHTS
        }
        self.assertEqual(clause_marginal, {1: 27, 2: 37, 3: 10, 4: 1})

    def test_joint_structural_sampling_uses_only_empirical_support(self) -> None:
        unsupported = (
            ("VERB_COMPLEMENTATION", "HARD"),
            ("CONNECTORS_CONJUNCTIONS", "HARD"),
            ("EXISTENTIAL_EXPLETIVE", "HARD"),
            ("REFERENCE_AND_DETERMINERS", "MEDIUM"),
            ("REFERENCE_AND_DETERMINERS", "HARD"),
        )
        for target, difficulty in unsupported:
            with self.subTest(target=target, difficulty=difficulty):
                self.assertEqual(
                    sum(
                        weight
                        for (item_target, item_difficulty, _clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                        if item_target == target and item_difficulty == difficulty
                    ),
                    0,
                )

        inversion_support = {
            difficulty: sum(
                weight for (target, item_difficulty, _clause_count), weight in JOINT_STRUCTURAL_WEIGHTS.items()
                if target == "INVERSION" and item_difficulty == difficulty
            )
            for difficulty in ("EASY", "MEDIUM", "HARD")
        }
        self.assertEqual(inversion_support, {"EASY": 0, "MEDIUM": 0, "HARD": 4})

        supported = {key for key, weight in JOINT_STRUCTURAL_WEIGHTS.items() if weight > 0}
        for seed in range(20):
            with self.subTest(seed=seed):
                self.assertTrue(
                    all(
                        (item["primary_target"], item["difficulty"], item["clause_count"]) in supported
                        for item in build_plan(seed)["items"]
                    )
                )

    def test_structural_fields_use_one_joint_draw_per_item(self) -> None:
        calls: list[object] = []
        from structure.planner import weighted_choice as real_weighted_choice

        def record_call(rng: random.Random, weighted_values: Mapping[Any, int]) -> Any:
            calls.append(weighted_values)
            return real_weighted_choice(rng, weighted_values)

        with patch("structure.planner.weighted_choice", side_effect=record_call):
            build_plan(2026)

        self.assertEqual(len(calls), 30)
        self.assertTrue(all(calls[index] is JOINT_STRUCTURAL_WEIGHTS for index in range(0, 30, 2)))
        self.assertTrue(all(calls[index] is SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY["EASY"] or
                            calls[index] is SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY["MEDIUM"] or
                            calls[index] is SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY["HARD"]
                            for index in range(1, 30, 2)))

    def test_difficulty_conditional_length_profile_preserves_marginals(self) -> None:
        self.assertEqual(
            {difficulty: sum(weights.values()) for difficulty, weights in SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY.items()},
            {"EASY": 18, "MEDIUM": 42, "HARD": 15},
        )
        self.assertEqual(
            {
                label: sum(weights[label] for weights in SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY.values())
                for label in (entry["label"] for entry in LENGTH_BINS)
            },
            {"10-14": 11, "15-19": 22, "20-24": 27, "25-27": 15},
        )
        self.assertEqual(SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY["EASY"]["25-27"], 0)

    def test_target_word_count_varies_uniformly_within_selected_bin(self) -> None:
        for difficulty in ("EASY", "MEDIUM", "HARD"):
            observed: dict[str, set[int]] = {}
            rng = random.Random(2026)
            for _ in range(5000):
                length_bin, word_count = _sample_length(rng, difficulty)
                observed.setdefault(length_bin["label"], set()).add(word_count)
            for entry in LENGTH_BINS:
                if SENTENCE_LENGTH_WEIGHTS_BY_DIFFICULTY[difficulty][entry["label"]] > 0:
                    with self.subTest(difficulty=difficulty, length_bin=entry["label"]):
                        self.assertEqual(
                            observed[entry["label"]],
                            set(range(entry["minimum"], entry["maximum"] + 1)),
                        )

    def test_plan_size_profile_and_boundaries(self) -> None:
        plan = build_plan(91)
        expected_fields = {
            "item_id", "order", "section", "primary_target", "difficulty", "clause_count",
            "sentence_length_bin", "target_word_count",
        }
        self.assertEqual(len(plan["items"]), 15)
        self.assertEqual(validate_plan(plan), [])
        self.assertNotIn("vocabulary_domains", load_profile())
        self.assertNotIn("target_subtypes", load_profile())
        self.assertTrue(all("vocabulary_domain" not in item for item in plan["items"]))
        self.assertTrue(all("subtype" not in item for item in plan["items"]))
        self.assertTrue(all(item["primary_target"] in PRIMARY_TARGET_WEIGHTS for item in plan["items"]))
        self.assertNotIn("WORD_CLASS_FORM", {item["primary_target"] for item in plan["items"]})
        self.assertTrue(all(item["clause_count"] in CLAUSE_COUNT_WEIGHTS for item in plan["items"]))
        self.assertEqual(CLAUSE_COUNT_WEIGHTS, {1: 27, 2: 37, 3: 10, 4: 1})
        self.assertTrue(all(set(item) == expected_fields for item in plan["items"]))
        for item in plan["items"]:
            self.assertGreaterEqual(item["target_word_count"], item["sentence_length_bin"]["minimum"])
            self.assertLessEqual(item["target_word_count"], item["sentence_length_bin"]["maximum"])
        self.assertEqual([(entry["minimum"], entry["maximum"]) for entry in LENGTH_BINS], [(10, 14), (15, 19), (20, 24), (25, 27)])

    def test_plan_schema_does_not_own_vocabulary_domain(self) -> None:
        schema = json.loads(Path("structure/schemas/plan.schema.json").read_text(encoding="utf-8"))
        item_schema = schema["properties"]["items"]["items"]
        self.assertNotIn("vocabulary_domain", item_schema["required"])
        self.assertNotIn("vocabulary_domain", item_schema["properties"])

    def test_plan_schema_does_not_own_subtype(self) -> None:
        schema = json.loads(Path("structure/schemas/plan.schema.json").read_text(encoding="utf-8"))
        item_schema = schema["properties"]["items"]["items"]
        self.assertNotIn("subtype", item_schema["required"])
        self.assertNotIn("subtype", item_schema["properties"])
        self.assertFalse(item_schema["additionalProperties"])

        invalid = copy.deepcopy(build_plan(91))
        invalid["items"][0]["subtype"] = "legacy planner subtype"
        self.assertTrue(schema_errors(invalid, schema))

    def test_planner_has_no_runtime_subtype_pool(self) -> None:
        import structure.planner as planner

        self.assertNotIn("target_subtypes", load_profile())
        self.assertFalse(hasattr(planner, "TARGET_SUBTYPES"))


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

    def test_generator_prompt_owns_subtype_and_selects_it_for_target_and_difficulty(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Because the Planner no longer supplies `subtype`",
            "choose the concrete grammatical construction as part of satisfying BOTH the planned `primary_target` and planned `difficulty`",
            "Before writing the stem/options, choose a construction within the planned `primary_target` that can naturally realize the planned difficulty",
            "The `subtype` in Generator output must describe the actual construction authored",
            "If a broad `primary_target` contains both simpler and more structurally demanding constructions",
            "Do not introduce a closed subtype enum or historical subtype list",
            "Keep the planned `primary_target` fixed",
            "MUST NOT switch to a different primary target to increase difficulty",
            "The chosen subtype must be a genuine member/instance of the planned `primary_target`",
            "planned primary target must remain the construction principally tested by the blank/options",
            "Do not choose a trivially local subtype for HARD and then artificially lengthen the sentence",
            "If the chosen subtype cannot naturally support HARD while maintaining uniqueness and naturalness, choose a different subtype/construction within the SAME `primary_target`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)
        for forbidden in (
            "preserve the planned `subtype` when it is supplied",
            "Planner-owned subtype",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)

    def test_generator_prompt_requires_whole_completion_coherence(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Before authoring each item, ensure that literal insertion of the intended correct option into the blank produces one coherent complete sentence.",
            "must not duplicate or substantially repeat material already present elsewhere in the stem",
            "Do not repeat the same list, phrase, complement, subject, predicate, or modifier both inside the option and after/before the blank.",
            "Account for punctuation and continuation after the blank",
            "colons, semicolons, commas, appositives, lists, relative clauses, complements",
            "locally grammatical is not sufficient if its insertion creates redundancy",
            "structural collision, duplicated content, or an unnatural complete sentence",
            "Evaluate distractors likewise as insertions into the entire stem, not as isolated strings.",
            "This is an authoring rule only, not a self-review stage.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_requires_position_agnostic_explanations_and_rationales(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "All natural-language explanation and rationale prose must be answer-position agnostic.",
            "`answer_explanation` MUST never identify an option by A/B/C/D.",
            '"A is correct", "option B", "choice C", or "answer D"',
            "actual word, phrase, form, or grammatical role",
            "prose values of `distractor_rationales`",
            "rationale object keys remain the schema-required A-D option labels",
            "only their prose values must avoid embedded answer-position references",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

        item_schema = load_schema(STRUCTURE_ITEM_SCHEMA)
        rationale_schema = item_schema["properties"]["distractor_rationales"]
        self.assertEqual(set(rationale_schema["required"]), set(LETTERS))
        self.assertEqual(set(rationale_schema["properties"]), set(LETTERS))

    def test_generator_prompt_requires_relative_preposition_licensing(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "fronted `preposition + whom/which` sequence",
            "lexically and syntactically licensed",
            "governing predicate, adjective, noun, or other construction",
            "`collaborate with` requires `with whom`",
            "`rely on` requires `on whom`",
            "`refer to` requires `to which` or `to whom`",
            "not choose a preposition merely to create a `preposition + whom` surface form",
            "completed relative clause is grammatical independently of the pronoun-case contrast",
            "do not introduce a separate fixed-preposition defect in the stem",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_requires_connector_whole_complement_compatibility(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "CONNECTORS_CONJUNCTIONS: connector complement type",
            "`because` / `because of`",
            "`although` / `despite` / `in spite of`",
            "syntactic category of ALL material governed by it",
            "complete finite clause",
            "nominal or gerund-type complement",
            "must not leave a following finite predicate stranded",
            "Do not stop at the first noun phrase",
            "full remainder after `of` is a finite clause, not a nominal complement",
            "splitting a multiword expression across stem and option",
            "complete remainder is structurally compatible",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_requires_distractor_stem_duplication_avoidance(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "For every option, including the intended answer and each distractor",
            "Before emitting any distractor",
            "lexical and structural content",
            "material immediately before and after the blank",
            "same phrase is already supplied by the stem",
            "`[X available] + X`",
            "`[list X] + list X`",
            "`[prepositional phrase X] + X`",
            "repeated complements or modifiers that remain grammatically rescuable",
            "definite grammar or structure defect, not merely awkward or redundant wording",
            "deterministic text-overlap checking",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_requires_difficulty_fidelity(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Planned `difficulty` is a genuine Generator construction target, not metadata only.",
            "Interpret EASY / MEDIUM / HARD RELATIVE TO THE DISTRIBUTION OF TOEFL ITP Structure Part A items",
            "absolute judgments of whether a fully competent test taker knows the underlying grammar rule",
            "complete authored item's structural demand",
            "overall syntactic complexity",
            "clause embedding and organization",
            "marked/noncanonical word order",
            "distance between grammatical dependencies",
            "interaction between the blank and surrounding sentence structure",
            "structural similarity/plausibility of distractors",
            "amount of whole-sentence parsing required",
            "Vocabulary difficulty and world knowledge must not create grammatical difficulty",
            "**EASY:**",
            "The lower end of normal TOEFL ITP Structure Part A difficulty",
            "comparatively simple sentence structure",
            "local/direct grammatical relation",
            "low embedding",
            "straightforward structural distinction",
            "distractors distinguishable with a relatively local structural check",
            "EASY may use one clear grammar point",
            "Do not unnecessarily increase complexity merely because the sentence-length target is longer",
            "**MEDIUM:**",
            "The broad central/typical band of TOEFL ITP Structure Part A",
            "MEDIUM does NOT require two grammar rules",
            "A single primary construction may yield MEDIUM",
            "meaningful sentence-level structural processing",
            "distinguishing reduced/nonfinite structure from finite structure",
            "parsing relative or subordinate-clause relationships",
            "tracking the grammatical relationship beyond the immediate blank",
            "resolving structurally similar alternatives",
            "meaningful but not upper-tail embedding or organization",
            "Do NOT automatically downgrade an otherwise typical Structure item to EASY",
            "governing grammar rule can be stated succinctly",
            "purely trivial local form-selection item as MEDIUM solely because the stem is long",
            "**HARD:**",
            "The upper end of TOEFL ITP Structure Part A relative structural difficulty",
            "HARD does NOT require two separate grammar rules",
            "two interacting cues",
            "a mandatory non-local cue",
            "a minimum clause count",
            "a fixed number of locally plausible distractors",
            "A single sufficiently demanding construction can be HARD",
            "marked or noncanonical inversion",
            "complex/nested noun, relative, or adverbial clauses",
            "free-relative or similarly demanding clause structures",
            "cleft-like structural organization",
            "structurally demanding comparative/correlative constructions",
            "long-distance grammatical dependency",
            "demanding coordination",
            "difficult modifier/attachment structure",
            "highly similar but structurally distinct distractors",
            "another upper-tail construction within the planned `primary_target`",
            "One-clause HARD items are possible",
            "adding unrelated clauses",
            "using rare vocabulary",
            "relying on world knowledge",
            "adding semantic tricks",
            "ambiguity",
            "unnatural wording",
            "Historical 75-item difficulty distribution",
            "EASY 18/75 = 24%",
            "MEDIUM 42/75 = 56%",
            "HARD 15/75 = 20%",
            "calibration guidance only, not deterministic rules, quotas, or targets",
            "do not force a 15-item batch to match these percentages",
            "syntactic complexity 2: EASY 16, MEDIUM 14, HARD 0",
            "syntactic complexity 3: EASY 2, MEDIUM 23, HARD 7",
            "syntactic complexity 4: EASY 0, MEDIUM 5, HARD 8",
            "historical HARD clause counts",
            "Do not add `syntactic_complexity` to the plan or output schema",
            "turn `clause_count` into a difficulty rule",
            "exactly one grammatical answer",
            "planned difficulty fidelity",
            "Difficulty must NEVER override answer uniqueness, grammaticality, or naturalness",
            "HARD does not require exactly two or any fixed number of locally plausible distractors",
            "Every distractor must still be definitely invalid in the complete sentence",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_requires_difficulty_realization_fidelity(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "smallest visible span a competent test taker actually needs",
            "generally at the EASY end of Structure Part A difficulty",
            "Do NOT call such an item MEDIUM or HARD merely because",
            "the full sentence is long; clause_count",
            "This is an authorship calibration rule, NOT deterministic post-generation classification",
            "the surrounding sentence structure must materially contribute to distinguishing the answer",
            "Do not add clauses or modifiers that are grammatically irrelevant to the tested decision",
            "those targets do NOT by themselves satisfy planned difficulty",
            "Do not create ornamental complexity",
            "The broad central/typical band of TOEFL ITP Structure Part A",
            "MEDIUM does NOT require two grammar rules",
            'The requirement is NOT "two rules"',
            "rather than collapsing into a one-step local lexical/morphological choice",
            "trivial immediate lookup",
            "usually EASY rather than MEDIUM/HARD",
            "`because` versus `because of` when a complete finite clause immediately follows",
            "`less` versus `fewer` directly before an obviously uncountable/countable noun",
            "a familiar verb followed immediately by its standard `to-infinitive` or gerund complement",
            "These are examples of REALIZATION, not permanent subtype labels",
            "Do NOT declare these constructions always EASY",
            "The upper end of TOEFL ITP Structure Part A relative structural difficulty",
            "HARD does NOT require two separate grammar rules",
            "One-clause HARD items are possible",
            "A one-clause item whose answer is determined immediately by a simple local agreement or lexical-form check is NOT made HARD merely because its subtype is called inversion or another advanced label",
            "Do NOT treat `INVERSION` automatically as HARD merely because all historical sampled inversion items happened to receive historical HARD labels",
            "Rarely ____ the singular noun receive",
            "Do not add tense ambiguity to make inversion harder",
            "Difficulty depends partly on the option set as well as the stem",
            "do not create an option set where every distractor is immediately eliminated by the same obvious local defect",
            'Do NOT reintroduce the old "at least two plausible distractors" HARD gate',
            "Never introduce ambiguity to raise difficulty",
            "ask whether that construction can NATURALLY realize the planned difficulty",
            "choose a different subtype/construction within the SAME primary_target",
            "Do NOT choose the easy subtype first and then attempt to manufacture difficulty",
            "Do NOT ignore or change clause_count, sentence_length_bin, or target_word_count",
            "they do not certify its difficulty",
            "A 27-word / 3-clause item can still be EASY if the correct answer is determined by a two-word local pattern",
            "A shorter or one-clause item can still be HARD if the tested structure itself creates upper-tail processing demand",
            "an emitted difficulty self-score; PASS/FAIL; a second pass; a second Generator invocation; hidden repair; regeneration; or revision",
            "The Generator still authors all 15 items in one invocation",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

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

    def test_generator_prompt_hardens_live_distractor_rescue_classes(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Complete-sentence rescue test",
            "Before emitting every distractor",
            "exact visible stem",
            "ordinary standard-written-English reader",
            "lexical valency",
            "voice interpretation",
            "semantic-role assignment",
            "clause boundary",
            "omitted-complementizer analysis",
            "attachment",
            "nonfinite modifier analysis",
            "If YES, do not use that distractor",
            "definite grammatical or structural failure in the complete sentence",
            "These are authorship rules only, not a self-review stage",
            "another Generator call",
            "invalid merely because the intended lexical use is more frequent",
            "ordinary transitive, intransitive, and causative lexical uses",
            "anticausative/labile alternation",
            "ordinary lexical valency",
            "`normally intransitive`",
            "`usually transitive`",
            "`not normally passive`",
            "sole basis for invalidity",
            "definite structural defect",
            "deterministic verb-valency lexicon",
            "Active / passive / reflexive semantic roles",
            "inanimate subject cannot be an agent",
            "device or system cannot perform an action automatically",
            "abstract or institutional subject cannot cause or perform an action",
            "reflexive reading is impossible",
            "device/system self-action or reflexive readings",
            "grammatically and semantically plausible",
            "reasonably coherent in the complete standalone sentence",
            "Active/passive/reflexive distractors require a definite",
            "not merely a semantic role different from the intended one",
            "Object-control vs. mandative clause rescue",
            "verb + object + to-infinitive",
            "bare-form distractor after the apparent object",
            "zero/omitted complementizer",
            "mandative/base-form clause",
            "`urge + object + to-infinitive`",
            "`urge + that-clause`",
            "borderline zero-complementizer reanalysis",
            "independently decisive grammatical defect",
            "broad verb-complementation taxonomy or lexicon",
            "Abstract noun + to-infinitive vs. `-ing` modifier",
            "to-infinitive complement or modifier after an abstract noun",
            "`-ing` form as a distractor",
            "participial postmodifier",
            "another grammatical nonfinite modifier",
            "another defensible attachment to the noun phrase",
            "understood semantic subject, cause, or source",
            "grammatical alternative attachment makes the distractor unsafe",
            "`-ing` option",
            "not a closed abstract-noun list",
            "Do not prohibit passive voice generally",
            "Do not prohibit reflexives generally",
            "Do not prohibit bare forms generally",
            "Do not prohibit `-ing` modifiers generally",
            "Do not prohibit abstract-noun infinitives generally",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

        for forbidden in (
            "self-review stage that emits a PASS/FAIL result",
            "second Generator call for rescue",
            "broad new verb-valency lexicon",
            "closed abstract-noun list of allowed nouns",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)

    def test_generator_prompt_checks_alternative_constituent_roles(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Do not judge a distractor only by whether it can perform the grammatical role apparently intended by the blank",
            "differ in grammatical category or internal structure",
            "form a different grammatical constituent with material immediately before or after the blank",
            "combine with following material",
            "combine with preceding material",
            "change constituent boundaries or attachment",
            "take another ordinary part-of-speech role",
            "intended adverb being read as an adjective modifying a following noun",
            "intended adjective being read as an adverb attaching to a verb or adjective",
            "intended complement being read as a noun-phrase modifier",
            "intended modifier being read as an argument/complement",
            "intended clause marker creating another constituent boundary",
            "distractor's own best ordinary parse",
            "If that parse is grammatical or defensible, do not use the distractor",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_licenses_content_clause_alternatives(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Content-clause lexical licensing",
            "content clause after a noun, adjective, or predicate",
            "alternative complementizer or wh-form",
            "declarative versus interrogative content",
            "proposition versus question interpretation",
            "`that`, `whether`, `if`, a wh-word",
            "governing noun, adjective, or verb can license that alternative clause type",
            "ordinary or defensible formal English",
            "less idiomatic, less common, semantically different",
            "not the intended content type",
            "missing preposition or other definite structure",
            "decisive in the exact sentence",
            "closed lexical-complementation dictionary or deterministic lexicon",
            "Generator authorship guidance only",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_requires_visible_tense_forcing(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "tense or an auxiliary is the contrast",
            "`do` / `does` / `did`",
            "present versus past",
            "present perfect versus past",
            "Generator-authored intended timeline is not sufficient",
            "visible sentence material must grammatically or temporally force the tested tense",
            "different tense auxiliaries independently create grammatical inverted sentences",
            "inconsistent with the intended general statement",
            "the intended timeline is present",
            "past is not intended",
            "exact sentence allows that timeline",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_preserves_primary_target_fidelity(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Primary-target fidelity and giveaway avoidance",
            "multiple defects naturally",
            "same unrelated surface error that bypasses the planned `primary_target`",
            "planned primary target must remain materially relevant",
            "article error",
            "obvious agreement error",
            "spelling-like form error",
            "obviously impossible morphology",
            "duplicated token",
            "other trivial surface defect",
            "Do not require every distractor to instantiate exactly the same target-specific error type",
            "do not impose a fixed number of target-specific distractors",
            "do not add a deterministic target classifier",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

        for forbidden in (
            "prohibit adjective/adverb alternations generally",
            "prohibit content-clause contrasts generally",
            "prohibit tense alternatives generally",
            "prohibit article errors generally",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)

    def test_generator_prompt_removes_obsolete_absolute_hard_requirements(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for forbidden in (
            "stronger operational gate",
            "at least two interacting structural or grammatical cues",
            "at least one required cue must depend on non-local sentence structure",
            "outside the immediate blank-local phrase",
            "At least two distractors should be locally plausible English forms",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)

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

    def test_generator_prompt_guards_reference_and_determiner_ambiguity(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Reference / determiner antecedents",
            "unclear or missing antecedent",
            "do not assume that `this`, `that`, or `it` is invalid",
            "no immediately preceding noun phrase exactly matches it",
            "discourse-deictic or propositional reference",
            "preceding event, fact, proposition, or situation",
            "ordinary anaphoric readings of `it`",
            "any plausible singular antecedent already present",
            "no reasonable standard-English referential interpretation",
            "explicit noun being clearer or stylistically preferable",
            "multiple references are grammatical and differ mainly in clarity",
            "An explicit noun is not automatically correct merely because it is clearer",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_guards_locative_inversion_alternatives(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "fronted place adverbial",
            "complete inversion construction",
            "another grammatical inversion analysis",
            "active locative-inversion target",
            "passive auxiliary plus participle distractor",
            "can license postposed-subject inversion",
            "Passive locative inversion may be grammatical",
            "marked, formal, or literary",
            "definite structural defect rather than instantiate another legitimate inversion type",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_generator_prompt_guards_subject_position_nonfinite_clauses(self) -> None:
        prompt = " ".join(Path("structure/prompts/generator.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Subject-position nonfinite phrases",
            "blank is in subject position immediately before an existing finite predicate",
            "gerund-participial clause is invalid",
            "Gerund-participial clauses can function as grammatical subjects",
            "infinitival clauses can also function as subjects where the construction licenses them",
            "full subject of the following finite predicate",
            "syntax and a reasonable semantic interpretation make it defensible",
            "complete sentence gives a definite structural or semantic failure",
            "only to subject-position constructions",
            "not a broad new nonfinite grammar manual",
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
            "including all text before AND after the blank",
            "duplicated or repeated material",
            "repeated lists or complements",
            "redundantly reproduces material already present later or earlier in the stem",
            "structural collisions caused by punctuation or continuation after the blank",
            "locally grammatical option that makes the full completed sentence materially unnatural or redundant",
            "`natural_wording=false` and `serious_defect=true`",
            "full syntactic complement after insertion",
            "`because of + NP` VALID merely because",
            "following finite predicate makes the completed construction invalid",
            "subordinating conjunction plus a complete finite clause",
            "preposition or prepositional connector plus an appropriate nominal or gerund complement",
            "Do not stop the analysis at the initial noun phrase",
            "Judge the COMPLETE inserted sentence through the end",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

        for phrase in (
            "classify the ACTUAL presented question independently",
            "RELATIVE TO THE DISTRIBUTION OF TOEFL ITP STRUCTURE PART A ITEMS",
            "Do NOT interpret EASY / MEDIUM / HARD as absolute labels",
            "fully competent test taker",
            "complete visible item's structural difficulty",
            "not merely the minimum local cue needed to identify the answer",
            "overall syntactic complexity",
            "clause embedding and organization",
            "marked/noncanonical word order",
            "distance between grammatical dependencies",
            "interaction between the blank and the rest of the sentence",
            "structural similarity and plausibility of distractors",
            "amount of whole-sentence parsing needed",
            "Vocabulary difficulty or world knowledge must NOT make an item grammatically HARD",
            "lower end of normal TOEFL ITP Structure Part A difficulty",
            "A short/simple local item is normally EASY",
            "broad central/typical band of TOEFL ITP Structure Part A",
            "MEDIUM does NOT require two interacting grammar rules",
            "one primary construction determines the answer",
            "COMPLETE item requires meaningful structural parsing",
            "Do NOT downgrade an otherwise typical official-style Structure item to EASY",
            "upper end of TOEFL ITP Structure Part A relative difficulty",
            "HARD does NOT require two separate grammar rules",
            "two interacting cues",
            "a minimum number of clauses",
            "a mandatory non-local cue",
            "multiple locally plausible distractors",
            "A single construction can be HARD",
            "marked or noncanonical inversion",
            "complex or nested noun, relative, or adverbial clauses",
            "free-relative structures",
            "cleft structures",
            "correlative comparative structures",
            "long-distance dependencies",
            "One-clause items CAN be HARD",
            "underlying grammar rule can be named locally",
            "EASY 18/75 (24%), MEDIUM 42/75 (56%), and HARD 15/75 (20%)",
            "calibration guidance only, not deterministic rules, quotas, or targets",
            "do not force any 15-item batch to match these proportions",
            "middle band is intentionally broad",
            "Clause count alone must not determine difficulty",
            "one-clause HARD items are possible",
            "judge the actual visible realization",
            "Sentence length alone does not make an item HARD",
            "Academic vocabulary or world knowledge alone does not make an item HARD",
            "Ambiguity or unnaturalness is a quality defect",
            "Confidence refers to certainty about the item's RELATIVE TOEFL ITP Structure difficulty band",
            "HIGH",
            "MEDIUM",
            "LOW",
            "Do not force HIGH confidence",
            "Every result must include `observed_difficulty`, `difficulty_confidence`, and `observed_clause_count`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_reviewer_prompt_checks_alternative_constituent_roles_without_metadata(self) -> None:
        prompt = " ".join(Path("structure/prompts/reviewer.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Do not test only whether an option fills the grammatical role apparently intended by the blank",
            "its own best ordinary parse in the exact complete sentence",
            "combine with material immediately following the blank",
            "combine with material immediately preceding the blank",
            "change constituent boundaries or attachment",
            "take another ordinary part-of-speech role",
            "create another grammatical phrase or clause structure",
            "an adjective may modify a following noun even when the intended answer is an adverb",
            "changing the boundary between a modifier and an argument/complement",
            "must be `VALID` or `MARGINAL` as appropriate",
            "do not mark it `INVALID` merely because it does not fill the apparently intended role",
            "Treat that alternative parse as a threat to uniqueness",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

        self.assertIn("The input contains only `item_id`, `section`, `stem`, and `options`.", prompt)
        self.assertIn("Do not ask for or infer Generator metadata", prompt)
        self.assertNotIn("primary_target", prompt)

    def test_reviewer_prompt_recalibration_removes_absolute_hard_requirements(self) -> None:
        prompt = " ".join(Path("structure/prompts/reviewer.md").read_text(encoding="utf-8").split())
        self.assertNotIn("minimum grammatical reasoning burden required", prompt)
        self.assertNotIn("at least two interacting grammatical/structural cues", prompt)
        self.assertNotIn("at least one important cue depends on non-local sentence structure", prompt)
        self.assertNotIn("multiple distractors remain locally plausible and require whole-sentence analysis", prompt)
        self.assertNotIn("basic `avoid + gerund`", prompt)
        self.assertNotIn("ordinary `who/whom`", prompt)

    def test_reviewer_prompt_requires_option_text_letter_alignment_and_consistency(self) -> None:
        prompt = " ".join(Path("structure/prompts/reviewer.md").read_text(encoding="utf-8").split())
        for phrase in (
            "Final output format and text identity",
            "ordered list of exactly four objects",
            "Copy each visible option string exactly as provided in the input",
            "including case, punctuation, and whitespace",
            "Include every visible option text exactly once",
            "do not omit, duplicate, invent, rewrite, normalize, or fuzzy-match an option",
            "option text itself is the identity used for every judgment",
            "`best_answer_text`",
            "exact text of the best visible option",
            "Do not return A/B/C/D letters",
            "comment remains natural-language and position-agnostic",
            "alternative is grammatically defensible enough to threaten uniqueness",
            "represent that same option as `VALID` or `MARGINAL`, never `INVALID`",
            "exact sentinel `AMBIGUOUS` or `NONE`",
            "same blind invocation",
            "not a new model call, revision loop, or metadata lookup",
            "comment and judgments must be semantically consistent",
            "described as grammatical, acceptable, valid, or defensible cannot be labeled `INVALID`",
            "described as clearly unacceptable cannot be labeled `VALID`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_solver_prompt_has_only_narrow_whole_sentence_clarification(self) -> None:
        solver_prompt = " ".join(Path("structure/prompts/solver.md").read_text(encoding="utf-8").split())
        for phrase in (
            "literally insert it into the `____` blank",
            "judge the resulting complete sentence, including all text before AND after the blank",
            "Do not select an option merely because the option itself or the local phrase around the blank is grammatical.",
            "Reject an interpretation when insertion creates an obvious structural collision, duplicated required material, or a completion that is not a coherent complete sentence.",
            "Return `AMBIGUOUS` for two or more acceptable completions",
            "and `NONE` when no acceptable completion exists",
            "Report `HIGH`, `MEDIUM`, or `LOW` confidence",
            "Do not force a guess.",
            "`answer_text` containing the exact visible option",
            "Copy that option string exactly, including case, punctuation, and whitespace.",
            "Do not return an A/B/C/D letter as the answer",
            "do not derive the answer from the reason",
            "refer to the selected visible construction in the reason rather than to an answer position",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, solver_prompt)
        for forbidden in (
            "noun clause",
            "That-clause",
            "finite-predicate",
            "finite predicate",
            "complementizer",
            "target-specific",
            "adjacent or competing finite predicates",
            "missing complementizer or coordinator",
            "Before concluding that an inserted phrase or clause functions as",
            "nominalized finite clause",
            "bare independent clause followed immediately by another finite predicate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, solver_prompt)

    def test_solver_contract_hash_regression(self) -> None:
        solver_prompt_hash = hashlib.sha256(Path("structure/prompts/solver.md").read_bytes()).hexdigest()
        self.assertEqual(solver_prompt_hash, "e83c1a95cf4a098f43733101a63751ac151993cfbd02e25b9f9af0e238b862f3")
        for schema_name, expected_hash in {
            "solver_input.schema.json": "2a511be9e2192f45b8928c3612eb5083af29abc2b05ab31aa4d231d7f4b958e8",
            "solver_output.schema.json": "90588686793f16f5ff2aefd6c19a834eb444e1bda9a0c1aff73de74e3506d031",
        }.items():
            with self.subTest(schema=schema_name):
                actual_hash = hashlib.sha256((Path("structure/schemas") / schema_name).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

    def test_planner_validation_and_pipeline_boundaries_are_protected(self) -> None:
        expected_hashes = {
            "structure/contracts.py": "c6fae71840a4d4a840f2c455ef97c39181ea8d7d4320b054f5d6face0eea313a",
            "structure/pipeline.py": "bfa2775767c86d9bc0b5c7777a6edfdce449827c1f2ed161b3976a27b7634eaf",
            "structure/planner.py": "d50e130a7c05fb79ba399c552322130aa4b5833eb6aff39144c3f6449748a7ee",
            "structure/profile.json": "66f9ad0cc2a7323ae396ab8c5f9766204327b0ecb4f5b275ec6a5b2e6295c6c5",
            "structure/blinding.py": "b39dcdad846adda25d46784c5d75b75e49f5b01d44df75a011bfe2c96546b351",
            "structure/permutation.py": "1efdba8054a14540ba838e31c2b57401faf97770c6da3ea14ea9850cc8c31b42",
        }
        for relative_path, expected_hash in expected_hashes.items():
            with self.subTest(path=relative_path):
                actual_hash = hashlib.sha256(Path(relative_path).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

    def test_structure_frozen_prompt_surface_hash_regressions(self) -> None:
        expected_hashes = {
            "structure/prompts/generator.md": "1415612033d0408eff52bf7c243003680d795601dfbb6eda3e0f67f089847727",
            "structure/prompts/reviewer.md": "0359e7f5dc3103a05082163bfb225b049923cffc72e2e5b373c6c8c5e88e70ae",
            "structure/prompts/solver.md": "e83c1a95cf4a098f43733101a63751ac151993cfbd02e25b9f9af0e238b862f3",
        }
        for relative_path, expected_hash in expected_hashes.items():
            with self.subTest(path=relative_path):
                actual_hash = hashlib.sha256(Path(relative_path).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

    def test_structure_schema_hash_regressions(self) -> None:
        expected_hashes = {
            "generator_item.schema.json": "229a8c39ca0daa2e79e516b0cc362eb740204fd5369252c478c79facaf857fff",
            "generator_output.schema.json": "78ad5e758052928bf51f973cdc009ab103c4f535e243e6bd17b0631fb361b2dd",
            "plan.schema.json": "ecfe3f6714e72fd6ac7282c8adb6356eb0678e77bcc039290e728b3908840807",
            "provenance.schema.json": "2979c3520cb79c5bdc96933f812f751be2c62db47cd2fea6c7294b30159904f2",
            "result.schema.json": "9f049f94ec8a819bf228bd59845eb64deddd6f974f523a64abccbaae69bfb5c5",
            "reviewer_input.schema.json": "8e5181664253967064a4c415377f5bc9f75a55e69984e54c01148d413d9e8b19",
            "reviewer_output.schema.json": "9f47df07f99acfc34a6da22c6bdaa0f383246d2c090c2841598a7e8de0aa599e",
            "solver_input.schema.json": "2a511be9e2192f45b8928c3612eb5083af29abc2b05ab31aa4d231d7f4b958e8",
            "solver_output.schema.json": "90588686793f16f5ff2aefd6c19a834eb444e1bda9a0c1aff73de74e3506d031",
        }
        for schema_name, expected_hash in expected_hashes.items():
            with self.subTest(schema=schema_name):
                actual_hash = hashlib.sha256((Path("structure/schemas") / schema_name).read_bytes()).hexdigest()
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
            (stem_for_word_count(plan["items"][0]["target_word_count"]), True),
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

    def test_generator_owns_nonempty_subtype_without_plan_comparison(self) -> None:
        plan = build_plan(40)
        output = generator_fixture(plan)
        self.assertEqual(validate_generator_contract(output, plan), [])

        changed = copy.deepcopy(output)
        changed["items"][0]["subtype"] = "different generator-authored construction"
        self.assertEqual(validate_generator_contract(changed, plan), [])

        missing = copy.deepcopy(output)
        del missing["items"][0]["subtype"]
        self.assertTrue(any("subtype" in error for error in validate_generator_contract(missing, plan)))

        blank = copy.deepcopy(output)
        blank["items"][0]["subtype"] = ""
        self.assertTrue(any("subtype" in error for error in validate_generator_contract(blank, plan)))

    def test_generator_primary_target_and_difficulty_match_plan(self) -> None:
        plan = build_plan(40)
        output = generator_fixture(plan)

        output["items"][0]["primary_target"] = "WORD_CLASS_FORM"
        output["items"][1]["difficulty"] = next(
            difficulty for difficulty in ("EASY", "MEDIUM", "HARD")
            if difficulty != plan["items"][1]["difficulty"]
        )
        errors = validate_generator_contract(output, plan)
        self.assertTrue(any("primary_target does not match" in error for error in errors))
        self.assertTrue(any("difficulty does not match" in error for error in errors))

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

    def test_reviewer_input_allowlist_and_output_difficulty_contract(self) -> None:
        input_schema = load_schema(Path("structure/schemas/reviewer_input.schema.json"))
        output_schema = load_schema(Path("structure/schemas/reviewer_output.schema.json"))
        self.assertEqual(
            set(input_schema["properties"]["items"]["items"]["required"]),
            {"item_id", "section", "stem", "options"},
        )
        self.assertEqual(
            set(input_schema["properties"]["items"]["items"]["properties"]),
            {"item_id", "section", "stem", "options"},
        )
        self.assertFalse(input_schema["properties"]["items"]["items"]["additionalProperties"])
        required = set(output_schema["properties"]["items"]["items"]["required"])
        self.assertIn("best_answer_text", required)
        self.assertNotIn("best_answer", required)
        option_judgments = output_schema["properties"]["items"]["items"]["properties"]["option_judgments"]
        self.assertEqual(option_judgments["type"], "array")
        self.assertEqual((option_judgments["minItems"], option_judgments["maxItems"]), (4, 4))
        self.assertFalse(option_judgments["items"]["additionalProperties"])
        self.assertEqual(
            set(option_judgments["items"]["required"]),
            {"option_text", "judgment"},
        )
        self.assertEqual(
            option_judgments["items"]["properties"]["judgment"]["enum"],
            ["VALID", "INVALID", "MARGINAL"],
        )
        self.assertIn("observed_difficulty", required)
        self.assertIn("difficulty_confidence", required)
        self.assertEqual(
            output_schema["properties"]["items"]["items"]["properties"]["observed_difficulty"]["enum"],
            ["EASY", "MEDIUM", "HARD"],
        )
        self.assertEqual(
            output_schema["properties"]["items"]["items"]["properties"]["difficulty_confidence"]["enum"],
            ["HIGH", "MEDIUM", "LOW"],
        )
        valid = reviewer_fixture(build_blind_input(generator_fixture(build_plan(52))))
        short = copy.deepcopy(valid)
        short["items"][0]["option_judgments"] = short["items"][0]["option_judgments"][:3]
        long = copy.deepcopy(valid)
        long["items"][0]["option_judgments"].append(copy.deepcopy(long["items"][0]["option_judgments"][0]))
        self.assertTrue(schema_errors(short, output_schema))
        self.assertTrue(schema_errors(long, output_schema))
        missing_observed = copy.deepcopy(valid)
        del missing_observed["items"][0]["observed_difficulty"]
        self.assertTrue(
            validate_reviewer_contract(
                missing_observed,
                build_blind_input(generator_fixture(build_plan(52))),
                build_plan(52),
            )
        )


class StructureObservedClauseCountDiagnosticTests(unittest.TestCase):
    """Narrow diagnostic: Reviewer reports observed_clause_count with zero acceptance effect."""

    def setUp(self) -> None:
        self.plan = build_plan(60)
        self.generator = generator_fixture(self.plan)
        self.blind = build_blind_input(self.generator)

    def test_reviewer_input_allowlist_is_unchanged(self) -> None:
        schema = load_schema(Path("structure/schemas/reviewer_input.schema.json"))
        item_schema = schema["properties"]["items"]["items"]
        self.assertEqual(set(item_schema["required"]), {"item_id", "section", "stem", "options"})
        self.assertEqual(set(item_schema["properties"]), {"item_id", "section", "stem", "options"})

    def test_raw_schema_requires_observed_clause_count(self) -> None:
        schema = load_schema(Path("structure/schemas/reviewer_output.schema.json"))
        required = schema["properties"]["items"]["items"]["required"]
        self.assertIn("observed_clause_count", required)
        prop = schema["properties"]["items"]["items"]["properties"]["observed_clause_count"]
        self.assertEqual(set(prop["type"]), {"integer", "null"})
        self.assertEqual(prop["minimum"], 1)

    def test_unique_best_answer_accepts_integer_ge_one(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=1)
        self.assertEqual(validate_reviewer_contract(raw, self.blind, self.plan), [])

    def test_values_above_four_remain_schema_valid(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=7)
        self.assertEqual(validate_reviewer_contract(raw, self.blind, self.plan), [])

    def test_zero_is_invalid(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=0)
        self.assertTrue(validate_reviewer_contract(raw, self.blind, self.plan))

    def test_negative_is_invalid(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=-1)
        self.assertTrue(validate_reviewer_contract(raw, self.blind, self.plan))

    def test_ambiguous_uses_null(self) -> None:
        raw = reviewer_fixture(self.blind, first_best="AMBIGUOUS")
        self.assertIsNone(raw["items"][0]["observed_clause_count"])
        self.assertEqual(validate_reviewer_contract(raw, self.blind, self.plan), [])

    def test_none_uses_null(self) -> None:
        raw = reviewer_fixture(self.blind, first_best="NONE")
        self.assertIsNone(raw["items"][0]["observed_clause_count"])
        self.assertEqual(validate_reviewer_contract(raw, self.blind, self.plan), [])

    def test_unique_best_answer_with_null_is_rejected(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=None)
        errors = validate_reviewer_contract(raw, self.blind, self.plan)
        self.assertTrue(errors)
        self.assertTrue(any("observed_clause_count" in error for error in errors))

    def test_ambiguous_or_none_with_integer_is_rejected(self) -> None:
        for sentinel in ("AMBIGUOUS", "NONE"):
            with self.subTest(sentinel=sentinel):
                raw = reviewer_fixture(self.blind, first_best=sentinel)
                raw["items"][0]["observed_clause_count"] = 2
                errors = validate_reviewer_contract(raw, self.blind, self.plan)
                self.assertTrue(errors)
                self.assertTrue(any("observed_clause_count" in error for error in errors))

    def test_canonicalization_preserves_observed_clause_count_unchanged(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=3)
        canonical = canonicalize_reviewer_output(raw, self.blind)
        self.assertEqual(canonical["items"][0]["observed_clause_count"], 3)
        for sentinel in ("AMBIGUOUS", "NONE"):
            with self.subTest(sentinel=sentinel):
                sentinel_raw = reviewer_fixture(self.blind, first_best=sentinel)
                sentinel_canonical = canonicalize_reviewer_output(sentinel_raw, self.blind)
                self.assertIsNone(sentinel_canonical["items"][0]["observed_clause_count"])

    def test_option_text_binding_unaffected(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=2)
        canonical = canonicalize_reviewer_output(raw, self.blind)
        self.assertEqual(set(canonical["items"][0]["option_judgments"]), set(LETTERS))
        self.assertEqual(canonical["items"][0]["best_answer"], "A")

    def test_difficulty_fields_unaffected(self) -> None:
        raw = reviewer_fixture(self.blind, first_observed_clause_count=4, observed_difficulty="HARD", difficulty_confidence="MEDIUM")
        canonical = canonicalize_reviewer_output(raw, self.blind)
        self.assertEqual(canonical["items"][0]["observed_difficulty"], "HARD")
        self.assertEqual(canonical["items"][0]["difficulty_confidence"], "MEDIUM")

    def test_mismatched_observed_clause_count_has_zero_acceptance_effect(self) -> None:
        planned_clause_count = self.plan["items"][0]["clause_count"]
        mismatched_observed_clause_count = planned_clause_count + 5
        reviewer = reviewer_fixture(self.blind, first_observed_clause_count=mismatched_observed_clause_count)
        solver = solver_fixture(self.blind)
        result = self.run_result(reviewer, solver)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertTrue(all(item["accepted"] for item in result["item_results"]))

    def test_no_clause_count_rejection_reason_reference_or_reason_string(self) -> None:
        planned_clause_count = self.plan["items"][0]["clause_count"]
        reviewer = reviewer_fixture(self.blind, first_observed_clause_count=planned_clause_count + 5)
        solver = solver_fixture(self.blind)
        result = self.run_result(reviewer, solver)
        for item in result["item_results"]:
            for reason in item["rejection_reasons"]:
                self.assertNotIn("clause_count", reason)
                self.assertNotIn("clause count", reason)

    def test_no_clause_count_retry_repair_or_regeneration(self) -> None:
        reviewer = reviewer_fixture(self.blind, first_observed_clause_count=self.plan["items"][0]["clause_count"] + 5)
        solver = solver_fixture(self.blind)
        result = self.run_result(reviewer, solver)
        self.assertTrue(result["checks"]["no_repair_or_revision_stage"])
        self.assertEqual(
            result["infrastructure"]["invocation_counts"],
            {"generator": 1, "reviewer": 1, "solver": 1},
        )

    def test_raw_reviewer_json_contains_observed_clause_count(self) -> None:
        reviewer = reviewer_fixture(self.blind, first_observed_clause_count=2)
        solver = solver_fixture(self.blind)
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = StructurePipeline(
                runtime=FixtureRuntime(
                    generator=self.generator, reviewer=reviewer, solver=solver
                )
            )
            pipeline.run(seed=60, output_dir=Path(tmp_dir) / "run")
            reviewer_json_path = Path(tmp_dir) / "run" / "reviewer.json"
            persisted = json.loads(reviewer_json_path.read_text(encoding="utf-8"))
        self.assertIn("observed_clause_count", persisted["items"][0])
        self.assertEqual(persisted["items"][0]["observed_clause_count"], 2)

    def run_result(self, reviewer: dict[str, Any], solver: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = StructurePipeline(
                runtime=FixtureRuntime(
                    generator=self.generator, reviewer=reviewer, solver=solver
                )
            )
            return pipeline.run(seed=60, output_dir=Path(tmp_dir) / "run")

    def test_generator_solver_planner_profile_and_gates_unaffected(self) -> None:
        # Structural confirmation that this diagnostic touches only Reviewer surfaces:
        # Generator/Solver/Planner/profile files and the deterministic sentence-length
        # gate are covered by the protected hash regression tests elsewhere in this
        # module; this test only confirms clause-count diagnostics never feed the
        # deterministic sentence-length fidelity gate's own error path.
        plan = build_plan(61)
        output = generator_fixture(plan)
        self.assertEqual(validate_generator_contract(output, plan), [])


class StructureSentenceLengthFidelityTests(unittest.TestCase):
    def test_count_words_splits_on_unicode_whitespace_deterministically(self) -> None:
        self.assertEqual(count_words("The researcher is here."), 4)
        self.assertEqual(count_words("The\tresearcher\nis   here."), 4)

    def test_count_words_treats_punctuation_as_part_of_the_word(self) -> None:
        self.assertEqual(count_words("The pattern, however, held."), 4)

    def test_count_words_treats_hyphenated_form_as_one_token(self) -> None:
        self.assertEqual(count_words("The well-documented pattern held."), 4)

    def test_count_words_treats_possessive_apostrophe_as_one_token(self) -> None:
        self.assertEqual(count_words("The team's pattern held."), 4)

    def test_build_completed_sentence_replaces_the_single_blank_exactly_once(self) -> None:
        stem = "The researcher ____ the documented pattern."
        self.assertEqual(
            build_completed_sentence(stem, "is"),
            "The researcher is the documented pattern.",
        )

    def test_completed_sentence_uses_canonical_pre_permutation_correct_option(self) -> None:
        plan = build_plan(60)
        output = generator_fixture(plan)
        target = plan["items"][0]["target_word_count"]
        output["items"][0]["stem"] = stem_for_word_count(target)
        output["items"][0]["options"]["A"] = "is"
        output["items"][0]["options"]["B"] = "are indeed a well documented and thoroughly cross referenced pattern"
        output["items"][0]["correct_answer"] = "A"
        self.assertEqual(validate_generator_contract(output, plan), [])

        wrong_key = copy.deepcopy(output)
        wrong_key["items"][0]["correct_answer"] = "B"
        errors = validate_generator_contract(wrong_key, plan)
        self.assertTrue(any("completed sentence word count" in error for error in errors))

    def test_word_count_equal_to_bin_minimum_passes(self) -> None:
        plan = build_plan(61)
        minimum = plan["items"][0]["sentence_length_bin"]["minimum"]
        output = generator_fixture(plan)
        output["items"][0]["stem"] = stem_for_word_count(minimum)
        self.assertEqual(validate_generator_contract(output, plan), [])

    def test_word_count_equal_to_bin_maximum_passes(self) -> None:
        plan = build_plan(61)
        maximum = plan["items"][0]["sentence_length_bin"]["maximum"]
        output = generator_fixture(plan)
        output["items"][0]["stem"] = stem_for_word_count(maximum)
        self.assertEqual(validate_generator_contract(output, plan), [])

    def test_word_count_below_bin_minimum_fails(self) -> None:
        plan = build_plan(61)
        minimum = plan["items"][0]["sentence_length_bin"]["minimum"]
        output = generator_fixture(plan)
        output["items"][0]["stem"] = stem_for_word_count(minimum - 1)
        errors = validate_generator_contract(output, plan)
        self.assertTrue(any("completed sentence word count" in error for error in errors))

    def test_word_count_above_bin_maximum_fails(self) -> None:
        plan = build_plan(61)
        maximum = plan["items"][0]["sentence_length_bin"]["maximum"]
        output = generator_fixture(plan)
        output["items"][0]["stem"] = stem_for_word_count(maximum + 1)
        errors = validate_generator_contract(output, plan)
        self.assertTrue(any("completed sentence word count" in error for error in errors))

    def test_length_failure_message_identifies_all_required_fields(self) -> None:
        plan = build_plan(61)
        item = plan["items"][0]
        bin_info = item["sentence_length_bin"]
        output = generator_fixture(plan)
        output["items"][0]["stem"] = stem_for_word_count(bin_info["minimum"] - 1)
        errors = validate_generator_contract(output, plan)
        message = next(error for error in errors if "completed sentence word count" in error)
        self.assertIn(item["item_id"], message)
        self.assertIn(str(bin_info["minimum"] - 1), message)
        self.assertIn(bin_info["label"], message)
        self.assertIn(str(bin_info["minimum"]), message)
        self.assertIn(str(bin_info["maximum"]), message)
        self.assertIn(f"target_word_count={item['target_word_count']}", message)

    def test_target_word_count_exact_equality_is_not_required(self) -> None:
        plan = build_plan(62)
        item = plan["items"][0]
        bin_info = item["sentence_length_bin"]
        alternate = next(
            count for count in range(bin_info["minimum"], bin_info["maximum"] + 1)
            if count != item["target_word_count"]
        )
        output = generator_fixture(plan)
        output["items"][0]["stem"] = stem_for_word_count(alternate)
        self.assertEqual(validate_generator_contract(output, plan), [])

    def test_stem_with_wrong_blank_count_skips_length_check(self) -> None:
        plan = build_plan(61)
        minimum = plan["items"][0]["sentence_length_bin"]["minimum"]
        output = generator_fixture(plan)
        short_no_blank = stem_for_word_count(minimum - 1).replace(BLANK_MARKER, "is")
        output["items"][0]["stem"] = short_no_blank
        errors = validate_generator_contract(output, plan)
        self.assertTrue(any("blank marker" in error for error in errors))
        self.assertFalse(any("completed sentence word count" in error for error in errors))

    def test_length_failure_prevents_downstream_invocation_and_quarantines(self) -> None:
        plan = build_plan(61)
        minimum = plan["items"][0]["sentence_length_bin"]["minimum"]
        bad_generator = generator_fixture(plan)
        bad_generator["items"][0]["stem"] = stem_for_word_count(minimum - 1)
        runtime = FixtureRuntime(generator=bad_generator)
        with tempfile.TemporaryDirectory() as directory:
            result = StructurePipeline(runtime).run(61, output_dir=Path(directory))
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertTrue(any("completed sentence word count" in error for error in result["checks"]["generator_errors"]))
        self.assertEqual([request.stage for request in runtime.requests], ["structure_generator"])
        self.assertEqual(result["live_invocation_count"], 1)


class StructureReviewerCanonicalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = build_plan(52)
        self.blind = build_blind_input(generator_fixture(self.plan))

    def test_raw_reviewer_schema_and_contract_use_exact_option_text(self) -> None:
        schema = load_schema(Path("structure/schemas/reviewer_output.schema.json"))
        item_schema = schema["properties"]["items"]["items"]
        self.assertIn("best_answer_text", item_schema["required"])
        self.assertNotIn("best_answer", item_schema["required"])
        self.assertEqual(item_schema["properties"]["option_judgments"]["type"], "array")
        self.assertEqual(
            set(item_schema["properties"]["option_judgments"]["items"]["properties"]),
            {"option_text", "judgment"},
        )
        raw = reviewer_fixture(self.blind)
        self.assertEqual(schema_errors(raw, schema), [])
        self.assertEqual(validate_reviewer_contract(raw, self.blind, self.plan), [])
        for entry in raw["items"][0]["option_judgments"]:
            self.assertEqual(set(entry), {"option_text", "judgment"})

        for best_answer_text in (self.blind["items"][0]["options"]["A"], "AMBIGUOUS", "NONE"):
            candidate = copy.deepcopy(raw)
            candidate["items"][0]["best_answer_text"] = best_answer_text
            candidate["items"][0]["observed_clause_count"] = None if best_answer_text in REVIEWER_ANSWER_SENTINELS else 1
            self.assertEqual(validate_reviewer_contract(candidate, self.blind, self.plan), [])

    def test_exact_option_multiset_failures_fail_closed_without_fuzzy_matching(self) -> None:
        cases = {
            "missing": lambda judgments: judgments.pop(),
            "duplicate": lambda judgments: judgments.__setitem__(1, copy.deepcopy(judgments[0])),
            "invented": lambda judgments: judgments.__setitem__(0, {"option_text": "invented", "judgment": "VALID"}),
            "modified": lambda judgments: judgments.__setitem__(0, {"option_text": "is ", "judgment": "VALID"}),
            "case_changed": lambda judgments: judgments.__setitem__(0, {"option_text": "IS", "judgment": "VALID"}),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                candidate = copy.deepcopy(reviewer_fixture(self.blind))
                mutate(candidate["items"][0]["option_judgments"])
                self.assertTrue(validate_reviewer_contract(candidate, self.blind, self.plan))

        invalid_best = copy.deepcopy(reviewer_fixture(self.blind))
        invalid_best["items"][0]["best_answer_text"] = " is"
        self.assertTrue(validate_reviewer_contract(invalid_best, self.blind, self.plan))

    def test_canonicalization_restores_existing_letter_keyed_shape_and_preserves_fields(self) -> None:
        raw = reviewer_fixture(self.blind)
        raw["items"][0]["comment"] = "The visible option text identifies the grammatical completion."
        canonical = canonicalize_reviewer_output(raw, self.blind)
        item = canonical["items"][0]
        self.assertEqual(set(item["option_judgments"]), set(LETTERS))
        self.assertEqual(item["best_answer"], "A")
        for field in ("natural_wording", "serious_defect", "comment", "observed_difficulty", "difficulty_confidence"):
            self.assertEqual(item[field], raw["items"][0][field])

    def test_canonical_answers_feed_existing_blind_agreement_comparison(self) -> None:
        generator = generator_fixture(self.plan)
        blind = build_blind_input(generator)
        canonical = canonicalize_reviewer_output(reviewer_fixture(blind), blind)
        canonical_solver = canonicalize_solver_output(solver_fixture(blind), blind)
        agreements, count = post_blind_comparison(generator, canonical, canonical_solver)
        self.assertEqual(count, 15)
        self.assertTrue(all(agreement["agree"] for agreement in agreements))

    def test_live_regression_text_binding_maps_to_current_letter(self) -> None:
        cases = (
            ({"A": "useful representing", "B": "representing useful", "C": "usefully representing", "D": "a useful representation"}, "a useful representation", "D"),
            ({"A": "online available", "B": "availablely online", "C": "available online", "D": "online availability"}, "available online", "C"),
        )
        for options, best_answer_text, expected_letter in cases:
            with self.subTest(expected_letter=expected_letter):
                blind = copy.deepcopy(self.blind)
                blind["items"][0]["options"] = options
                raw = reviewer_fixture(self.blind)
                raw["items"][0]["option_judgments"] = [
                    {"option_text": options[letter], "judgment": "VALID" if options[letter] == best_answer_text else "INVALID"}
                    for letter in LETTERS
                ]
                raw["items"][0]["best_answer_text"] = best_answer_text
                canonical = canonicalize_reviewer_output(raw, blind)
                self.assertEqual(canonical["items"][0]["best_answer"], expected_letter)
                self.assertEqual(canonical["items"][0]["option_judgments"][expected_letter], "VALID")

    def test_sentinels_survive_canonicalization(self) -> None:
        for sentinel in ("AMBIGUOUS", "NONE"):
            with self.subTest(sentinel=sentinel):
                raw = reviewer_fixture(self.blind, first_best=sentinel)
                self.assertEqual(canonicalize_reviewer_output(raw, self.blind)["items"][0]["best_answer"], sentinel)

    def test_reviewer_difficulty_diagnostics_are_independent_of_acceptance(self) -> None:
        self.assertEqual(
            reviewer_difficulty_diagnostic_reasons(
                "HARD", {"observed_difficulty": "MEDIUM", "difficulty_confidence": "HIGH"}
            ),
            ["reviewer_difficulty_mismatch: planned=HARD, observed=MEDIUM"],
        )
        self.assertEqual(
            reviewer_difficulty_diagnostic_reasons(
                "EASY", {"observed_difficulty": "MEDIUM", "difficulty_confidence": "HIGH"}
            ),
            ["reviewer_difficulty_mismatch: planned=EASY, observed=MEDIUM"],
        )
        self.assertEqual(
            reviewer_difficulty_diagnostic_reasons(
                "HARD", {"observed_difficulty": "HARD", "difficulty_confidence": "HIGH"}
            ),
            [],
        )
        self.assertEqual(
            reviewer_difficulty_diagnostic_reasons(
                "HARD", {"observed_difficulty": "HARD", "difficulty_confidence": "MEDIUM"}
            ),
            [],
        )
        self.assertEqual(
            reviewer_difficulty_diagnostic_reasons(
                "HARD", {"observed_difficulty": "HARD", "difficulty_confidence": "LOW"}
            ),
            ["reviewer_difficulty_confidence_low"],
        )
        plan = build_plan(51)
        reviewer = reviewer_fixture(build_blind_input(generator_fixture(plan)))
        self.assertEqual(reviewer_difficulty_summary(plan, reviewer), (15, 0))
        reviewer["items"][0]["difficulty_confidence"] = "LOW"
        self.assertEqual(reviewer_difficulty_summary(plan, reviewer), (15, 1))
        diagnostics = reviewer_difficulty_diagnostics(plan, reviewer)
        self.assertEqual(len(diagnostics), 15)
        self.assertIn("reviewer_difficulty_confidence_low", diagnostics[0]["reasons"])


class StructureSolverCanonicalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = build_plan(52)
        self.blind = build_blind_input(generator_fixture(self.plan))

    def test_solver_input_allowlist_and_raw_schema_use_answer_text(self) -> None:
        input_schema = load_schema(Path("structure/schemas/solver_input.schema.json"))
        output_schema = load_schema(Path("structure/schemas/solver_output.schema.json"))
        item_input_schema = input_schema["$defs"]["item"]
        self.assertEqual(
            set(item_input_schema["required"]),
            {"item_id", "section", "stem", "options"},
        )
        self.assertEqual(set(item_input_schema["properties"]), {"item_id", "section", "stem", "options"})
        self.assertFalse(item_input_schema["additionalProperties"])

        item_output_schema = output_schema["properties"]["items"]["items"]
        self.assertIn("answer_text", item_output_schema["required"])
        self.assertNotIn("answer", item_output_schema["required"])
        self.assertEqual(set(item_output_schema["properties"]), {"item_id", "answer_text", "confidence", "reason"})
        raw = solver_fixture(self.blind)
        self.assertEqual(schema_errors(raw, output_schema), [])
        self.assertEqual(validate_solver_contract(raw, self.blind, self.plan), [])
        self.assertTrue(all("answer_text" in item and "answer" not in item for item in raw["items"]))
        legacy = copy.deepcopy(raw)
        del legacy["items"][0]["answer_text"]
        legacy["items"][0]["answer"] = "A"
        self.assertTrue(schema_errors(legacy, output_schema))
        self.assertTrue(validate_solver_contract(legacy, self.blind, self.plan))

    def test_exact_visible_option_text_maps_to_current_position(self) -> None:
        options = {
            "A": "a significant disparity regional",
            "B": "a disparity significant regional",
            "C": "a regional significant disparity",
            "D": "a significant regional disparity",
        }
        raw = solver_fixture(self.blind)
        blind = copy.deepcopy(self.blind)
        blind["items"][0]["options"] = options
        for answer_text, expected_answer in ((options[letter], letter) for letter in LETTERS):
            with self.subTest(expected_answer=expected_answer):
                candidate = copy.deepcopy(raw)
                candidate["items"][0]["answer_text"] = answer_text
                canonical = canonicalize_solver_output(candidate, blind)
                self.assertEqual(canonical["items"][0]["answer"], expected_answer)

    def test_sentinels_remain_sentinels(self) -> None:
        raw = solver_fixture(self.blind)
        for sentinel in ("AMBIGUOUS", "NONE"):
            with self.subTest(sentinel=sentinel):
                candidate = copy.deepcopy(raw)
                candidate["items"][0]["answer_text"] = sentinel
                canonical = canonicalize_solver_output(candidate, self.blind)
                self.assertEqual(canonical["items"][0]["answer"], sentinel)

    def test_canonical_solver_shape_preserves_only_existing_downstream_fields(self) -> None:
        raw = solver_fixture(self.blind, confidence="MEDIUM")
        raw["items"][0]["reason"] = "The visible completion fits the full sentence."
        canonical_item = canonicalize_solver_output(raw, self.blind)["items"][0]
        self.assertEqual(set(canonical_item), {"item_id", "answer", "confidence", "reason"})
        self.assertEqual(canonical_item["item_id"], raw["items"][0]["item_id"])
        self.assertEqual(canonical_item["confidence"], "MEDIUM")
        self.assertEqual(canonical_item["reason"], raw["items"][0]["reason"])

    def test_non_exact_answer_text_fails_closed_without_reason_parsing(self) -> None:
        invalid_cases = (
            ("modified", self.blind, "i"),
            ("typo", self.blind, "izz"),
            ("case_changed", self.blind, "IS"),
            ("added_whitespace", self.blind, "is "),
            ("non_option", self.blind, "was"),
        )
        removed_whitespace_blind = copy.deepcopy(self.blind)
        removed_whitespace_blind["items"][0]["options"] = {
            "A": " is", "B": "are", "C": "be", "D": "being"
        }
        invalid_cases += (("removed_whitespace", removed_whitespace_blind, "is"),)
        for name, blind, answer_text in invalid_cases:
            with self.subTest(case=name):
                candidate = solver_fixture(self.blind)
                candidate["items"][0]["answer_text"] = answer_text
                candidate["items"][0]["reason"] = "'The singular finite completion is the only acceptable choice.'"
                self.assertTrue(validate_solver_contract(candidate, blind, self.plan))
                with self.assertRaises(ValueError):
                    canonicalize_solver_output(candidate, blind)

        regression_options = {
            "A": "a significant disparity regional",
            "B": "a disparity significant regional",
            "C": "a regional significant disparity",
            "D": "a significant regional disparity",
        }
        blind = copy.deepcopy(self.blind)
        blind["items"][0]["options"] = regression_options
        candidate = solver_fixture(self.blind)
        candidate["items"][0]["answer_text"] = regression_options["D"]
        candidate["items"][0]["reason"] = f"'{regression_options['C']}' has the correct noun phrase structure."
        canonical = canonicalize_solver_output(candidate, blind)
        self.assertEqual(canonical["items"][0]["answer"], "D")

    def test_canonical_solver_answers_feed_existing_reviewer_solver_agreement(self) -> None:
        generator = generator_fixture(self.plan)
        canonical_solver = canonicalize_solver_output(solver_fixture(self.blind), self.blind)
        canonical_reviewer = canonicalize_reviewer_output(reviewer_fixture(self.blind), self.blind)
        agreements, count = post_blind_comparison(generator, canonical_reviewer, canonical_solver)
        self.assertEqual(count, 15)
        self.assertTrue(all(agreement["agree"] for agreement in agreements))


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
        self.assertEqual(result["reviewer_difficulty_agreement_count"], 15)
        self.assertEqual(result["reviewer_difficulty_low_confidence_count"], 0)

    def test_difficulty_mismatch_is_diagnostic_only(self) -> None:
        plan = build_plan(51)
        permuted, _ = permute_generator_output(generator_fixture(plan), 51)
        blind = build_blind_input(permuted)
        reviewer = reviewer_fixture(blind)
        planned = plan["items"][0]["difficulty"]
        reviewer["items"][0]["observed_difficulty"] = next(
            difficulty for difficulty in ("EASY", "MEDIUM", "HARD") if difficulty != planned
        )
        runtime = FixtureRuntime(reviewer=reviewer)
        result = self.run_fixture(runtime)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(sum(item["accepted"] for item in result["item_results"]), 15)
        self.assertEqual(result["reviewer_difficulty_agreement_count"], 14)
        self.assertNotIn(
            f"reviewer_difficulty_mismatch: planned={planned}, observed={reviewer['items'][0]['observed_difficulty']}",
            result["item_results"][0]["rejection_reasons"],
        )
        self.assertIn(
            f"reviewer_difficulty_mismatch: planned={planned}, observed={reviewer['items'][0]['observed_difficulty']}",
            result["checks"]["reviewer_difficulty"]["per_item"][0]["reasons"],
        )
        self.assertEqual(result["checks"]["reviewer_difficulty"]["policy"], "diagnostic_only")
        self.assertEqual(result["live_invocation_count"], 3)
        self.assertEqual([request.stage for request in runtime.requests], [
            "structure_generator", "structure_reviewer", "structure_solver"
        ])

    def test_low_difficulty_confidence_is_diagnostic_only(self) -> None:
        plan = build_plan(51)
        blind = build_blind_input(permute_generator_output(generator_fixture(plan), 51)[0])
        reviewer = reviewer_fixture(blind)
        reviewer["items"][0]["difficulty_confidence"] = "LOW"
        result = self.run_fixture(FixtureRuntime(reviewer=reviewer))
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(sum(item["accepted"] for item in result["item_results"]), 15)
        self.assertEqual(result["reviewer_difficulty_agreement_count"], 15)
        self.assertEqual(result["reviewer_difficulty_low_confidence_count"], 1)
        self.assertNotIn(
            "reviewer_difficulty_confidence_low",
            result["item_results"][0]["rejection_reasons"],
        )
        self.assertIn(
            "reviewer_difficulty_confidence_low",
            result["checks"]["reviewer_difficulty"]["per_item"][0]["reasons"],
        )

    def test_multiple_difficulty_mismatches_do_not_quarantine(self) -> None:
        plan = build_plan(51)
        blind = build_blind_input(permute_generator_output(generator_fixture(plan), 51)[0])
        reviewer = reviewer_fixture(blind)
        for index in range(3):
            planned = plan["items"][index]["difficulty"]
            reviewer["items"][index]["observed_difficulty"] = next(
                difficulty for difficulty in ("EASY", "MEDIUM", "HARD") if difficulty != planned
            )
        result = self.run_fixture(FixtureRuntime(reviewer=reviewer))
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(sum(item["accepted"] for item in result["item_results"]), 15)
        self.assertEqual(result["reviewer_difficulty_agreement_count"], 12)
        self.assertEqual(
            sum(bool(item["reasons"]) for item in result["checks"]["reviewer_difficulty"]["per_item"]),
            3,
        )

    def test_reviewer_artifact_persists_difficulty_fields_for_every_item(self) -> None:
        runtime = FixtureRuntime()
        with tempfile.TemporaryDirectory() as directory:
            StructurePipeline(runtime).run(51, output_dir=Path(directory))
            reviewer = json.loads((Path(directory) / "reviewer.json").read_text(encoding="utf-8"))
            provenance = json.loads(
                (Path(directory) / "provenance" / "provenance.json").read_text(encoding="utf-8")
            )
        self.assertEqual(len(reviewer["items"]), 15)
        self.assertTrue(all("observed_difficulty" in item for item in reviewer["items"]))
        self.assertTrue(all("difficulty_confidence" in item for item in reviewer["items"]))
        self.assertTrue(all("best_answer_text" in item for item in reviewer["items"]))
        self.assertTrue(all("best_answer" not in item for item in reviewer["items"]))
        self.assertEqual(
            provenance["reviewer_canonicalization"],
            {
                "applied": True,
                "strategy": "exact_option_text_identity",
                "raw_artifact": "reviewer.json",
                "canonical_internal_shape": "option_judgments keyed A-D; best_answer letter or sentinel",
            },
        )

    def test_solver_artifact_persists_raw_text_and_provenance_records_canonicalization(self) -> None:
        runtime = FixtureRuntime()
        with tempfile.TemporaryDirectory() as directory:
            StructurePipeline(runtime).run(51, output_dir=Path(directory))
            solver = json.loads((Path(directory) / "solver.json").read_text(encoding="utf-8"))
            provenance = json.loads(
                (Path(directory) / "provenance" / "provenance.json").read_text(encoding="utf-8")
            )
        self.assertEqual(len(solver["items"]), 15)
        self.assertTrue(all("answer_text" in item for item in solver["items"]))
        self.assertTrue(all("answer" not in item for item in solver["items"]))
        self.assertEqual(
            provenance["solver_canonicalization"],
            {
                "applied": True,
                "strategy": "exact_option_text_identity",
                "raw_artifact": "solver.json",
                "canonical_internal_shape": "answer letter or sentinel; item_id, confidence, reason",
            },
        )

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

    def test_invalid_raw_option_text_quarantines_the_whole_set_without_extra_calls(self) -> None:
        plan = build_plan(51)
        blind = build_blind_input(permute_generator_output(generator_fixture(plan), 51)[0])
        reviewer = reviewer_fixture(blind)
        reviewer["items"][0]["option_judgments"][0]["option_text"] = "is "
        runtime = FixtureRuntime(reviewer=reviewer)
        result = self.run_fixture(runtime)
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(result["live_invocation_count"], 3)
        self.assertEqual([request.stage for request in runtime.requests], [
            "structure_generator", "structure_reviewer", "structure_solver"
        ])

    def test_invalid_solver_answer_text_quarantines_the_whole_set_without_extra_calls(self) -> None:
        plan = build_plan(51)
        blind = build_blind_input(permute_generator_output(generator_fixture(plan), 51)[0])
        solver = solver_fixture(blind)
        solver["items"][0]["answer_text"] = "is "
        runtime = FixtureRuntime(solver=solver)
        result = self.run_fixture(runtime)
        self.assertEqual(result["decision"], "QUARANTINE")
        self.assertEqual(result["live_invocation_count"], 3)
        self.assertTrue(result["checks"]["solver_errors"])
        self.assertEqual([request.stage for request in runtime.requests], [
            "structure_generator", "structure_reviewer", "structure_solver"
        ])

    def test_each_final_gate_blocks_accept(self) -> None:
        plan = build_plan(51)
        permuted, _ = permute_generator_output(generator_fixture(plan), 51)
        blind = build_blind_input(permuted)
        correct = next(letter for letter in LETTERS if blind["items"][0]["options"][letter] == "is")
        wrong = next(letter for letter in LETTERS if letter != correct)
        marginal = reviewer_fixture(blind)
        next(
            judgment for judgment in marginal["items"][0]["option_judgments"]
            if judgment["option_text"] == blind["items"][0]["options"][wrong]
        )["judgment"] = "MARGINAL"
        cases = {
            "reviewer_ambiguous": (reviewer_fixture(blind, first_best="AMBIGUOUS"), None),
            "reviewer_none": (reviewer_fixture(blind, first_best="NONE"), None),
            "solver_ambiguous": (None, solver_fixture(blind, first_answer_text="AMBIGUOUS")),
            "solver_none": (None, solver_fixture(blind, first_answer_text="NONE")),
            "reviewer_key_disagreement": (reviewer_fixture(blind, first_best=wrong), None),
            "solver_key_disagreement": (None, solver_fixture(blind, first_answer_text=blind["items"][0]["options"][wrong])),
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
            self.assertNotIn("difficulty", payload["items"][0])
            self.assertNotIn("correct_answer", request.prompt)
            self.assertNotIn("primary_target", request.prompt)
            self.assertNotIn("distractor_rationales", request.prompt)
        self.assertEqual(result["infrastructure"]["invocation_counts"], {"generator": 1, "reviewer": 1, "solver": 1})


if __name__ == "__main__":
    unittest.main()
