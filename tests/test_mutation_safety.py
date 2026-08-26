"""Regression fixtures for the WE v2.1.2 grammar-mutation safety patch."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts"))

from mutation_safety import (  # noqa: E402
    STRONG_INVARIANT_NAMES,
    TemplateClass,
    audit_mutation,
    template_audit_records,
    validate_item as validate_mutation_item,
)


def check(
    clean: str,
    error: str,
    mutation: str,
    correction: str,
    explanation: str,
    *,
    error_type: str,
    target: str,
    item: dict | None = None,
    external_evidence: dict[str, bool] | None = None,
):
    return audit_mutation(
        clean_form=clean,
        error_form=error,
        mutation_type=mutation,
        minimal_correction=correction,
        answer_explanation=explanation,
        tested_error_type=error_type,
        primary_target=target,
        item=item,
        external_evidence=external_evidence,
    )


class MutationSafetyFixtures(unittest.TestCase):
    def test_A_clear_comet_antecedent_rejects_pronoun_substitution(self) -> None:
        result = check(
            "The telescope photographed the comet after the comet crossed the horizon.",
            "The telescope photographed the comet after it crossed the horizon.",
            "ambiguous-pronoun substitution: the comet -> it",
            "Replace it with the comet.",
            "The pronoun it is not a safe mutation when the comet is a clear antecedent.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertEqual(result.template_class, TemplateClass.QUARANTINE.value)

    def test_B_clear_artifact_antecedent_rejects_pronoun_substitution(self) -> None:
        result = check(
            "After the curator labeled the artifact, the artifact was returned to storage.",
            "After the curator labeled the artifact, it was returned to storage.",
            "ambiguous-pronoun substitution: the artifact -> it",
            "Replace it with the artifact.",
            "The pronoun it has a clear artifact antecedent and is not a grammatical defect.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("quarantined", " ".join(result.reasons))

    def test_reference_and_determiners_articles_are_not_reference_quarantined(self) -> None:
        result = check(
            "An ancient observatory preserves fragile star charts.",
            "A ancient observatory preserves fragile star charts.",
            "article substitution: An -> A",
            "Change A to An.",
            "The vowel sound at the start of ancient requires An, not A.",
            error_type="incorrect_part_of_speech",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "PASS", result.reasons)
        self.assertNotEqual(result.template_id, "reference.ambiguous_pronoun_substitution")

    def test_reference_and_determiners_count_quantifiers_are_not_reference_quarantined(self) -> None:
        result = check(
            "The laboratory compared many samples from the upper valley.",
            "The laboratory compared much samples from the upper valley.",
            "count quantifier substitution: many -> much",
            "Change much to many.",
            "Samples is a plural count noun, so many rather than much is required.",
            error_type="agreement_error",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "PASS", result.reasons)
        self.assertNotEqual(result.template_id, "reference.ambiguous_pronoun_substitution")

    def test_C_semantic_only_degree_substitution_rejects(self) -> None:
        result = check(
            "The planning model is sufficiently flexible to incorporate revised estimates.",
            "The planning model is too flexible to incorporate revised estimates.",
            "degree-marker substitution: sufficiently flexible -> too flexible",
            "Change too flexible to sufficiently flexible.",
            "The substitution from sufficiently flexible to too flexible changes the intended meaning but does not create a grammar error.",
            error_type="wrong_degree_form",
            target="COMPARATIVES_DEGREE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("meaning", " ".join(result.reasons))

    def test_D_explicit_comparative_trigger_is_valid(self) -> None:
        result = check(
            "The revised filter is more reliable than the earlier procedure.",
            "The revised filter is most reliable than the earlier procedure.",
            "comparative/superlative substitution: more reliable -> most reliable",
            "Change most reliable to more reliable.",
            "The explicit than comparison requires comparative more reliable, not superlative most reliable.",
            error_type="wrong_degree_form",
            target="COMPARATIVES_DEGREE",
        )
        self.assertEqual(result.status, "PASS", result.reasons)

    def test_person_guard_does_not_treat_first_person_number_as_person_mismatch(self) -> None:
        result = check(
            "The report stated that I participated.",
            "The report stated that we participated.",
            "person mismatch: I -> we",
            "Change we to I.",
            "I is appropriate here, not we, but this change does not establish an objective reference defect.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("objective", " ".join(result.reasons))

    def test_demonstrative_guard_resolves_adjective_before_noun_head(self) -> None:
        result = check(
            "These large instruments detect faint signals.",
            "Those large instruments detect faint signals.",
            "demonstrative number substitution: These -> Those",
            "Change Those to These.",
            "These and those have the same plural form before the plural noun instruments.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("objective", " ".join(result.reasons))

    def test_E_comma_ing_alternate_parse_rejects_parallel_mutation(self) -> None:
        result = check(
            "The vessel will map the seafloor, collect water samples, and record currents.",
            "The vessel will map the seafloor, collecting water samples, and record currents.",
            "parallel verb-form substitution: collect -> collecting",
            "Change collecting to collect.",
            "The coordinated verbs after will must use the base form collect.",
            error_type="wrong_verb_form",
            target="PARALLEL_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("participial", " ".join(result.reasons))

    def test_F_forced_parallel_mismatch_is_valid(self) -> None:
        result = check(
            "The team plans to collect water samples and analyze the results during the survey.",
            "The team plans to collect water samples and analyzing the results during the survey.",
            "parallel base-form substitution: analyze -> analyzing",
            "Change analyzing to analyze.",
            "The infinitive plan coordinates collect and analyze, so analyzing is the wrong verb form.",
            error_type="wrong_verb_form",
            target="PARALLEL_STRUCTURE",
        )
        self.assertEqual(result.status, "PASS", result.reasons)

    def test_multiword_ing_target_is_checked_at_the_mutated_verb(self) -> None:
        result = check(
            "The vessel will map the seafloor, record data, and report findings.",
            "The vessel will map the seafloor, recording data, and report findings.",
            "parallel base-form substitution: record -> recording data",
            "Change recording data to record.",
            "The recording data phrase can be read as a supplementary participial clause.",
            error_type="wrong_verb_form",
            target="PARALLEL_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("participial", " ".join(result.reasons))

    def test_infinitival_correction_keeps_the_to_connector_in_the_target(self) -> None:
        result = check(
            "The digital catalog allows visitors to locate rare manuscripts.",
            "The digital catalog allows visitors locating rare manuscripts.",
            "allow-complement substitution: to locate -> locating",
            "Change locating to to locate.",
            "Allow visitors requires the infinitive to locate in this complement frame.",
            error_type="wrong_verb_form",
            target="VERB_COMPLEMENTATION",
        )
        self.assertEqual(result.status, "PASS", result.reasons)

    def test_arrow_form_minimal_correction_is_parseable(self) -> None:
        result = check(
            "The observatory records the readings.",
            "The observatory record the readings.",
            "verb-form substitution: records -> record",
            "record → records",
            "The singular subject requires records, not record.",
            error_type="agreement_error",
            target="CLAUSE_STRUCTURE",
        )
        self.assertEqual(result.status, "PASS", result.reasons)

    def test_unparseable_mutation_direction_fails_closed(self) -> None:
        result = check(
            "The team plans to collect samples and analyze results.",
            "The team plans to collect samples and analyzing results.",
            "parallel base-form substitution: analyze to analyzing",
            "Change analyzing to analyze.",
            "The coordinated verb has the wrong form.",
            error_type="wrong_verb_form",
            target="PARALLEL_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("parseable", " ".join(result.reasons))

    def test_changed_token_must_be_at_the_declared_marked_position(self) -> None:
        clean = "The curator records the archive and record carefully."
        error = "The curator record the archive and record carefully."
        result = check(
            clean,
            error,
            "verb-form substitution: records -> record",
            "Change record to records.",
            "The verb record is the mutation evidence.",
            error_type="wrong_verb_form",
            target="CLAUSE_STRUCTURE",
            item={
                "sentence": error,
                "correct_answer": "C",
                "marked_parts": {"A": "The", "B": "curator", "C": "record carefully", "D": "archive"},
            },
        )
        self.assertEqual(result.status, "REJECT")
        self.assertFalse(result.invariants["declared_marked_span_contains_defect"])
        self.assertIn("outside the declared", " ".join(result.reasons))

    def test_qa_error_form_must_match_emitted_sentence(self) -> None:
        result = check(
            "The curator records the archive.",
            "The curator record the archive.",
            "verb-form substitution: records -> record",
            "Change record to records.",
            "The verb record is the mutation evidence.",
            error_type="wrong_verb_form",
            target="CLAUSE_STRUCTURE",
            item={
                "sentence": "The curator records the archive.",
                "correct_answer": "B",
                "marked_parts": {"A": "The", "B": "records", "C": "archive", "D": "archive"},
            },
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("exactly match the emitted sentence", " ".join(result.reasons))

    def test_G_metadata_direction_mismatch_fails(self) -> None:
        result = check(
            "The curator confirmed that the archive was secure.",
            "The curator confirmed who the archive was secure.",
            "relative-pronoun substitution: whom -> who",
            "Change who to whom.",
            "The marked relative form is inconsistent with the clean sentence.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertFalse(result.metadata_consistent)
        self.assertTrue(any("clean_form" in reason for reason in result.reasons))

    def test_stale_direction_must_match_the_actual_token_diff(self) -> None:
        result = check(
            "The curator records the archive.",
            "The curator record the archive.",
            "verb-form substitution: records -> samples",
            "Change record to records.",
            "The verb record is the mutation evidence.",
            error_type="wrong_verb_form",
            target="CLAUSE_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("token diff", " ".join(result.reasons))

    def test_deletion_correction_source_must_occur_in_error_form(self) -> None:
        result = check(
            "The efficiency of solar panels depends on regular inspections.",
            "The efficiency of solar panels depends regular inspections.",
            "preposition omission: depends on -> depends",
            "Change banana to depends on.",
            "The preposition on is missing after depends.",
            error_type="incorrect_preposition",
            target="VERB_COMPLEMENTATION",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("source does not occur", " ".join(result.reasons))

    def test_degree_morphology_label_requires_an_inflectional_surface_change(self) -> None:
        result = check(
            "The device is reliable.",
            "The device is highly reliable.",
            "degree morphology: reliable -> highly reliable",
            "Change highly reliable to reliable.",
            "The change adds a degree adverb but does not change adjective morphology.",
            error_type="wrong_degree_form",
            target="COMPARATIVES_DEGREE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("inflection", " ".join(result.reasons))

    def test_parallel_agreement_requires_coordination_scope(self) -> None:
        result = check(
            "The observatory records the readings.",
            "The observatory record the readings.",
            "parallel agreement substitution: records -> record",
            "Change record to records.",
            "The singular subject requires records, not record.",
            error_type="agreement_error",
            target="PARALLEL_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("coordination scope", " ".join(result.reasons))

    def test_degree_mutation_without_a_morphosyntactic_trigger_is_quarantined(self) -> None:
        result = check(
            "The device is reliable.",
            "The device is highly reliable.",
            "reliable -> highly reliable",
            "Change highly reliable to reliable.",
            "The change is semantic only.",
            error_type="wrong_degree_form",
            target="COMPARATIVES_DEGREE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertEqual(result.template_id, "degree.unclassified_mutation")
        self.assertIn("quarantined", " ".join(result.reasons))

    def test_minimal_correction_requires_a_parseable_direction(self) -> None:
        result = check(
            "The observatory records the readings.",
            "The observatory record the readings.",
            "records -> record",
            "Use the singular form for the finite verb.",
            "The singular subject requires records, not record.",
            error_type="agreement_error",
            target="CLAUSE_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("minimal_correction must contain a parseable", " ".join(result.reasons))

    def test_explanation_must_preserve_the_clean_to_error_direction(self) -> None:
        result = check(
            "The archive records the samples.",
            "The archive record the samples.",
            "finite agreement substitution: records -> record",
            "Change record to records.",
            "The plural subject requires record, not records.",
            error_type="agreement_error",
            target="CLAUSE_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("reverses the clean -> error direction", " ".join(result.reasons))

    def test_unrecognised_reference_replacement_is_quarantined(self) -> None:
        result = check(
            "After the curator labeled the artifact, the artifact was returned to storage.",
            "After the curator labeled the artifact, it was returned to storage.",
            "reference replacement: the artifact -> it",
            "Replace it with the artifact.",
            "The replacement is not independently justified as a reference defect.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertEqual(result.template_class, TemplateClass.QUARANTINE.value)

    def test_formal_antecedent_label_is_not_reference_evidence(self) -> None:
        result = check(
            "After the curator labeled the artifact, the artifact was returned to storage.",
            "After the curator labeled the artifact, it was returned to storage.",
            "formally invalid antecedent relation: the artifact -> it",
            "Replace it with the artifact.",
            "The pronoun it has a clear artifact antecedent and is not a formal reference defect.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("not evidence", " ".join(result.reasons))

    def test_modal_coordination_scope_rejects_object_gerund_parse(self) -> None:
        result = check(
            "The committee will review the proposal and file the report.",
            "The committee will review the proposal and filing the report.",
            "parallel verb-form substitution: file -> filing",
            "Change filing to file.",
            "The modal will cannot license filing as a coordinated verb after the object proposal.",
            error_type="wrong_verb_form",
            target="PARALLEL_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("object phrase", " ".join(result.reasons))

    def test_prepositional_to_does_not_hide_modal_object_ambiguity(self) -> None:
        result = check(
            "The committee will object to postponing the vote and approve the revision.",
            "The committee will object to postponing the vote and approving the revision.",
            "parallel base-form substitution: approve -> approving",
            "Change approving to approve.",
            "The modal will cannot license approving as a coordinated verb after the object phrase.",
            error_type="wrong_verb_form",
            target="PARALLEL_STRUCTURE",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("object phrase", " ".join(result.reasons))

    def test_deletion_boundary_counts_as_marked_defect(self) -> None:
        error = "The efficiency of solar panels depends during routine inspections."
        result = check(
            "The efficiency of solar panels depends on during routine inspections.",
            error,
            "preposition omission: depends on -> depends",
            "Change depends to depends on.",
            "The verb depends requires the preposition on, which is missing after depends.",
            error_type="incorrect_preposition",
            target="VERB_COMPLEMENTATION",
            item={
                "sentence": error,
                "correct_answer": "C",
                "marked_parts": {"A": "The efficiency", "B": "of solar panels", "C": "depends", "D": "during"},
            },
        )
        self.assertEqual(result.status, "PASS", result.reasons)
        self.assertTrue(result.invariants["declared_marked_span_contains_defect"])

    def test_strong_invariant_is_fail_closed_without_external_evidence(self) -> None:
        result = check(
            "The filter is more reliable than the earlier procedure.",
            "The filter is most reliable than the earlier procedure.",
            "comparative/superlative substitution: more reliable -> most reliable",
            "Change most reliable to more reliable.",
            "The explicit than comparison requires comparative more reliable.",
            error_type="wrong_degree_form",
            target="COMPARATIVES_DEGREE",
        )
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.grammar_evidence_status, "REQUIRES_EXTERNAL_REVIEW")
        self.assertIsNone(result.invariants["clean_sentence_grammatical"])

    def test_strong_invariant_rejects_incomplete_external_evidence(self) -> None:
        result = check(
            "The filter is more reliable than the earlier procedure.",
            "The filter is most reliable than the earlier procedure.",
            "comparative/superlative substitution: more reliable -> most reliable",
            "Change most reliable to more reliable.",
            "The explicit than comparison requires comparative more reliable.",
            error_type="wrong_degree_form",
            target="COMPARATIVES_DEGREE",
        )
        result = audit_mutation(
            clean_form="The filter is more reliable than the earlier procedure.",
            error_form="The filter is most reliable than the earlier procedure.",
            mutation_type="comparative/superlative substitution: more reliable -> most reliable",
            minimal_correction="Change most reliable to more reliable.",
            answer_explanation="The explicit than comparison requires comparative more reliable.",
            tested_error_type="wrong_degree_form",
            primary_target="COMPARATIVES_DEGREE",
            external_evidence={"clean_sentence_grammatical": True},
        )
        self.assertEqual(result.status, "REJECT")
        self.assertEqual(result.grammar_evidence_status, "FAIL")

    def test_single_contiguous_reorder_passes_but_disjoint_reorders_fail(self) -> None:
        local = check(
            "The team quickly records samples in Europe.",
            "The quickly team records samples in Europe.",
            "word-order substitution: team quickly -> quickly team",
            "Change quickly team to team quickly.",
            "The local word-order change moves quickly before team, rather than changing the other words.",
            error_type="wrong_word_order",
            target="CLAUSE_STRUCTURE",
        )
        self.assertTrue(local.surface_integrity, local.reasons)
        self.assertEqual(local.status, "PASS", local.reasons)

        broad = check(
            "The team quickly records samples in Europe.",
            "Quickly the samples team Europe in records.",
            "word-order substitution: The team quickly records samples in Europe -> Quickly the samples team Europe in records",
            "Change Quickly the samples team Europe in records to The team quickly records samples in Europe.",
            "The reordered sentence changes several disjoint word-order relationships.",
            error_type="wrong_word_order",
            target="CLAUSE_STRUCTURE",
        )
        self.assertFalse(broad.surface_integrity)
        self.assertIn("exactly one local surface mutation", " ".join(broad.reasons))

    def test_formal_number_mismatch_pronoun_is_not_blanket_quarantined(self) -> None:
        result = check(
            "The students submitted reports after the students met.",
            "The students submitted reports after he met.",
            "pronoun substitution: the students -> he",
            "Change he to the students.",
            "The plural antecedent students requires they, not he.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "PASS", result.reasons)
        self.assertEqual(result.template_class, TemplateClass.NEEDS_GUARD.value)
        self.assertNotIn("template is quarantined", " ".join(result.reasons))

    def test_finite_verb_is_not_inferred_as_a_pronoun_antecedent(self) -> None:
        result = check(
            "The researchers said that he participated.",
            "The researchers said that they participated.",
            "number mismatch: he -> they",
            "Change they to he.",
            "The sentence permits either pronoun in reported speech, so this is not an objective number defect.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "REJECT")
        self.assertIn("objective", " ".join(result.reasons))

    def test_possessive_reference_number_mismatch_is_objective(self) -> None:
        result = check(
            "The coral released its spores.",
            "The coral released their spores.",
            "number mismatch: its -> their",
            "Change their to its.",
            "The singular antecedent coral requires its, not their.",
            error_type="incorrect_reference",
            target="REFERENCE_AND_DETERMINERS",
        )
        self.assertEqual(result.status, "PASS", result.reasons)

    def test_targeted_template_catalog_is_classified(self) -> None:
        records = {record["template_id"]: record for record in template_audit_records()}
        self.assertEqual(records["reference.ambiguous_pronoun_substitution"]["classification"], "QUARANTINE")
        self.assertEqual(records["degree.semantic_marker_substitution"]["classification"], "QUARANTINE")
        self.assertEqual(records["parallel.base_form_to_ing"]["classification"], "NEEDS_GUARD")
        self.assertEqual(records["degree.comparative_superlative_explicit_than"]["classification"], "NEEDS_GUARD")
        self.assertEqual(records["degree.unclassified_mutation"]["classification"], "QUARANTINE")


class ProductionValidationRouting(unittest.TestCase):
    @staticmethod
    def validator_module():
        path = ROOT / "agents" / "toefl_itp_we_generator_v2" / "scripts" / "validate_output.py"
        spec = importlib.util.spec_from_file_location("we_v2_production_validator", path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_v21_routes_through_mutation_safety_and_v20_is_legacy_gated(self) -> None:
        module = self.validator_module()
        item = json.loads(
            (ROOT / "analysis" / "we_v2_1_2_grammar_pilot" / "runtime" / "generator" / "we_v2.1.2_grammar_pilot_001.json").read_text(encoding="utf-8")
        )
        config = module.load_json(module.CONFIG_PATH)
        grammar = module.load_json(module.GRAMMAR_SPEC_PATH)
        taxonomy = module.load_json(module.TAXONOMY_PATH)
        targets = {entry["id"] for entry in taxonomy["primary_targets"]}
        error_types = {
            entry["id"]
            for entry in grammar["tested_error_types"]
            if entry["id"] not in {"fragment", "wrong_complementation"}
        }

        with mock.patch.object(module, "validate_mutation_item", wraps=module.validate_mutation_item) as checked:
            result = module.validate_contract(item, config, targets, error_types)
        self.assertTrue(checked.called)
        self.assertFalse(result["valid"])
        self.assertTrue(any("grammar_check_status PASS" in error for error in result["errors"]))

        legacy = copy.deepcopy(item)
        legacy["agent_version"] = "Written Expression Generator v2.0"
        legacy["provenance"]["agent_version"] = "Written Expression Generator v2.0"
        self.assertFalse(module.mutation_safety_required(legacy))

    def test_v21_batch_ids_cannot_opt_out_of_mutation_safety(self) -> None:
        module = self.validator_module()
        batch_path = ROOT / "analysis" / "we_v2_1_pilot" / "runtime" / "generator_batch.json"
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        item = copy.deepcopy(batch["items"][0])
        item["provenance"]["generation_batch_id"] = "we-v2.1-forged-retained-artifact"
        self.assertTrue(module.mutation_safety_required(item))

        current = json.loads(
            (ROOT / "analysis" / "we_v2_1_2_grammar_pilot" / "runtime" / "generator" / "we_v2.1.2_grammar_pilot_001.json").read_text(encoding="utf-8")
        )
        current["provenance"]["generation_batch_id"] = "we-v2.1-forged-retained-artifact"
        config = module.load_json(module.CONFIG_PATH)
        grammar = module.load_json(module.GRAMMAR_SPEC_PATH)
        taxonomy = module.load_json(module.TAXONOMY_PATH)
        targets = {entry["id"] for entry in taxonomy["primary_targets"]}
        error_types = {
            entry["id"]
            for entry in grammar["tested_error_types"]
            if entry["id"] not in {"fragment", "wrong_complementation"}
        }
        result = module.validate_contract(current, config, targets, error_types)
        self.assertTrue(any("grammar_check_status PASS" in error for error in result["errors"]))

    def test_v21_grammar_pass_label_cannot_replace_strong_grammar_evidence(self) -> None:
        module = self.validator_module()
        item = json.loads(
            (ROOT / "analysis" / "we_v2_1_2_grammar_pilot" / "runtime" / "generator" / "we_v2.1.2_grammar_pilot_001.json").read_text(encoding="utf-8")
        )
        item["qa_metadata"]["grammar_check_status"] = "PASS"
        config = module.load_json(module.CONFIG_PATH)
        grammar = module.load_json(module.GRAMMAR_SPEC_PATH)
        taxonomy = module.load_json(module.TAXONOMY_PATH)
        targets = {entry["id"] for entry in taxonomy["primary_targets"]}
        error_types = {
            entry["id"]
            for entry in grammar["tested_error_types"]
            if entry["id"] not in {"fragment", "wrong_complementation"}
        }
        result = module.validate_contract(item, config, targets, error_types)
        self.assertFalse(result["valid"])
        self.assertTrue(any("grammar_evidence_status PASS" in error for error in result["errors"]))

    def test_v21_forwards_external_grammar_evidence_to_mutation_validator(self) -> None:
        module = self.validator_module()
        item = json.loads(
            (ROOT / "analysis" / "we_v2_1_2_grammar_pilot" / "runtime" / "generator" / "we_v2.1.2_grammar_pilot_001.json").read_text(encoding="utf-8")
        )
        item["qa_metadata"]["grammar_check_status"] = "PASS"
        evidence = {
            "content_hash": module.grammar_evidence_content_hash(item),
            "evidence": {name: True for name in STRONG_INVARIANT_NAMES},
        }
        config = module.load_json(module.CONFIG_PATH)
        grammar = module.load_json(module.GRAMMAR_SPEC_PATH)
        taxonomy = module.load_json(module.TAXONOMY_PATH)
        targets = {entry["id"] for entry in taxonomy["primary_targets"]}
        error_types = {
            entry["id"]
            for entry in grammar["tested_error_types"]
            if entry["id"] not in {"fragment", "wrong_complementation"}
        }
        result = module.validate_contract(item, config, targets, error_types, evidence)
        self.assertTrue(result["valid"], result["errors"])

    def test_stale_external_grammar_evidence_is_rejected_after_form_change(self) -> None:
        module = self.validator_module()
        item = json.loads(
            (ROOT / "analysis" / "we_v2_1_2_grammar_pilot" / "runtime" / "generator" / "we_v2.1.2_grammar_pilot_001.json").read_text(encoding="utf-8")
        )
        item["qa_metadata"]["grammar_check_status"] = "PASS"
        evidence = {
            "content_hash": module.grammar_evidence_content_hash(item),
            "evidence": {name: True for name in STRONG_INVARIANT_NAMES},
        }
        item["qa_metadata"]["error_form"] = item["qa_metadata"]["error_form"].replace("record", "records")
        config = module.load_json(module.CONFIG_PATH)
        grammar = module.load_json(module.GRAMMAR_SPEC_PATH)
        taxonomy = module.load_json(module.TAXONOMY_PATH)
        targets = {entry["id"] for entry in taxonomy["primary_targets"]}
        error_types = {
            entry["id"]
            for entry in grammar["tested_error_types"]
            if entry["id"] not in {"fragment", "wrong_complementation"}
        }
        result = module.validate_contract(item, config, targets, error_types, evidence)
        self.assertFalse(result["valid"])
        self.assertTrue(any("not bound to the exact item content" in error for error in result["errors"]))

    def test_external_evidence_loader_requires_content_hash(self) -> None:
        module = self.validator_module()
        with self.assertRaisesRegex(ValueError, "requires a nonempty content_hash"):
            with mock.patch.object(module, "load_json", return_value={"items": [{"item_id": "x", "evidence": {"a": True}}]}):
                module.load_external_evidence(Path("unused.json"))

    def test_top_level_minimal_correction_must_match_qa_metadata(self) -> None:
        item = {
            "agent_version": "Written Expression Generator v2.1",
            "provenance": {"generation_batch_id": "we-v2.1.2-test"},
            "sentence": "The curator record the archive.",
            "correct_answer": "B",
            "marked_parts": {"A": "The", "B": "record", "C": "the", "D": "archive"},
            "minimal_correction": "Change archive to archives.",
            "error_explanation": "The verb record should be records.",
            "tested_error_type": "wrong_verb_form",
            "primary_target": "CLAUSE_STRUCTURE",
            "qa_metadata": {
                "clean_form": "The curator records the archive.",
                "error_form": "The curator record the archive.",
                "minimal_correction": "Change record to records.",
                "mutation_type": "verb-form substitution: records -> record",
            },
        }
        result = validate_mutation_item(item)
        self.assertEqual(result.status, "REJECT")
        self.assertIn("must exactly match", " ".join(result.reasons))


if __name__ == "__main__":
    unittest.main()
