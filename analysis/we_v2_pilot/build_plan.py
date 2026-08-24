#!/usr/bin/env python3
"""Deterministically build the WE v2 Live Pilot 25-slot batch plan.

The plan is the only artifact shared across all 25 items. Realization stays
per-microbatch so that a single huge generation context cannot drift.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_plan.json"

BATCH_ID = "we-v2-live-pilot-20260824"

# (primary_target, subtype, tested_error_type, difficulty, vocabulary_domain,
#  correction_locality, decision_granularity, planned_correct_position,
#  sentence_length_region, expected_span_profile, expected_coverage_profile,
#  expected_correct_span_type)
SLOTS = [
    ("REFERENCE_AND_DETERMINERS", "subject-verb agreement across an intervening of-phrase", "agreement_error", "MEDIUM", "glacial geology", "DEPENDENCY_BASED", "AGREEMENT_DEPENDENCY", "B", "21-25", "four single-word spans", "20-29%", "SINGLE_WORD"),
    ("REFERENCE_AND_DETERMINERS", "possessive determiner number agreement with its antecedent", "incorrect_reference", "MEDIUM", "marine biology", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "D", "16-20", "three single-word spans and one two-word span", "20-29%", "SINGLE_WORD"),
    ("REFERENCE_AND_DETERMINERS", "redundant determiner after a quantifier phrase", "extraneous_element", "EASY", "American colonial history", "LOCAL_SHORT_SPAN", "FUNCTION_WORD", "C", "16-20", "two single-word spans and two two-word spans", "20-29%", "SHORT_PHRASE"),
    ("REFERENCE_AND_DETERMINERS", "demonstrative determiner number agreement with head noun", "agreement_error", "EASY", "observational astronomy", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "A", "16-20", "four single-word spans", "20-29%", "SINGLE_WORD"),
    ("REFERENCE_AND_DETERMINERS", "missing article before a singular count noun", "missing_required_element", "MEDIUM", "agricultural economics", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "B", "16-20", "four single-word spans", "20-29%", "SINGLE_WORD"),

    ("VERB_COMPLEMENTATION", "gerund required after a preposition-taking verb", "wrong_verb_form", "MEDIUM", "art history", "CLAUSE_LEVEL", "VERB_FRAME", "C", "21-25", "three single-word spans and one two-word span", "20-29%", "SINGLE_WORD"),
    ("VERB_COMPLEMENTATION", "verb plus required preposition collocation", "wrong_preposition_collocation", "MEDIUM", "plant physiology", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "D", "16-20", "four single-word spans", "20-29%", "SINGLE_WORD"),
    ("VERB_COMPLEMENTATION", "bare infinitive required in a causative complement", "wrong_verb_form", "HARD", "atmospheric science", "CLAUSE_LEVEL", "VERB_FRAME", "B", "21-25", "three single-word spans and one clause-like span", "26-35%", "SINGLE_WORD"),

    ("PARALLEL_STRUCTURE", "coordinated noun phrases requiring the same word class", "incorrect_part_of_speech", "MEDIUM", "cultural anthropology", "LOCAL_SHORT_SPAN", "WORD_CLASS", "D", "21-25", "two single-word spans and two two-word spans", "20-29%", "SINGLE_WORD"),
    ("PARALLEL_STRUCTURE", "coordinated verb phrases requiring the same verb form", "wrong_verb_form", "MEDIUM", "analytical chemistry", "CLAUSE_LEVEL", "VERB_FRAME", "C", "21-25", "two single-word spans and two short phrases", "26-35%", "SHORT_PHRASE"),
    ("PARALLEL_STRUCTURE", "correlative not only ... but also parallelism", "incorrect_part_of_speech", "HARD", "nineteenth-century American literature", "CLAUSE_LEVEL", "WORD_CLASS", "B", "26-30", "three single-word spans and one clause-like span", "20-29%", "CLAUSE_OR_CLAUSE_LIKE"),

    ("WORD_CLASS_FORM", "adjective used where an adverb is required", "incorrect_part_of_speech", "EASY", "structural engineering", "LOCAL_SINGLE_TOKEN", "MORPHOLOGY", "A", "16-20", "four single-word spans", "20-29%", "SINGLE_WORD"),
    ("WORD_CLASS_FORM", "noun used where an adjective is required", "incorrect_part_of_speech", "MEDIUM", "ornithology", "LOCAL_SINGLE_TOKEN", "MORPHOLOGY", "C", "16-20", "four single-word spans", "20-29%", "SINGLE_WORD"),
    ("WORD_CLASS_FORM", "verb form used where a nominal is required", "incorrect_part_of_speech", "MEDIUM", "urban sociology", "LOCAL_SINGLE_TOKEN", "MORPHOLOGY", "D", "21-25", "four single-word spans", "16-25%", "SINGLE_WORD"),

    ("NONFINITE_VERB_PHRASES", "past participle required in a reduced relative clause", "wrong_verb_form", "MEDIUM", "paleontology", "CLAUSE_LEVEL", "VERB_FRAME", "A", "21-25", "two single-word spans and two short phrases", "26-35%", "SHORT_PHRASE"),
    ("NONFINITE_VERB_PHRASES", "infinitive of purpose in the wrong nonfinite form", "wrong_verb_form", "MEDIUM", "public health", "CLAUSE_LEVEL", "VERB_FRAME", "B", "16-20", "three single-word spans and one two-word span", "20-29%", "SINGLE_WORD"),
    ("NONFINITE_VERB_PHRASES", "present versus past participle as a prenominal modifier", "incorrect_part_of_speech", "HARD", "materials science", "LOCAL_SINGLE_TOKEN", "MORPHOLOGY", "C", "21-25", "four single-word spans", "16-25%", "SINGLE_WORD"),

    ("VERB_FORM_VOICE", "passive voice required by an inanimate patient subject", "wrong_voice", "MEDIUM", "archaeology", "CLAUSE_LEVEL", "VERB_FRAME", "B", "21-25", "two single-word spans and two short phrases", "26-35%", "SHORT_PHRASE"),
    ("VERB_FORM_VOICE", "perfect auxiliary followed by the wrong participle form", "wrong_verb_form", "MEDIUM", "music history", "CLAUSE_LEVEL", "VERB_FRAME", "D", "16-20", "three single-word spans and one two-word span", "20-29%", "SINGLE_WORD"),

    ("CONNECTORS_CONJUNCTIONS", "clausal subordinator required where a prepositional connector appears", "incorrect_subordinator", "MEDIUM", "environmental policy", "CLAUSE_LEVEL", "CLAUSE_RELATION", "A", "21-25", "two short phrases and two single-word spans", "20-29%", "SHORT_PHRASE"),

    ("RELATIVE_CLAUSES", "relative marker selection determined by the antecedent", "incorrect_relative_marker", "MEDIUM", "historical geography", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "C", "21-25", "four single-word spans", "16-25%", "SINGLE_WORD"),
    ("RELATIVE_CLAUSES", "relative clause verb agreeing with the antecedent head", "agreement_error", "HARD", "developmental psychology", "DEPENDENCY_BASED", "AGREEMENT_DEPENDENCY", "D", "21-25", "three single-word spans and one two-word span", "20-29%", "SINGLE_WORD"),

    ("CLAUSE_STRUCTURE", "resumptive subject pronoun after a full subject noun phrase", "double_subject", "EASY", "immunology", "CLAUSE_LEVEL", "CLAUSE_RELATION", "B", "16-20", "three single-word spans and one clause-like span", "26-35%", "CLAUSE_OR_CLAUSE_LIKE"),

    ("WORD_ORDER_MODIFICATION", "adverb misplaced between verb and its direct object", "wrong_word_order", "MEDIUM", "computer engineering", "LOCAL_SHORT_SPAN", "WORD_ORDER", "C", "16-20", "two single-word spans and two short phrases", "26-35%", "CLAUSE_OR_CLAUSE_LIKE"),

    ("COMPARATIVES_DEGREE", "comparative form used where the superlative is required", "wrong_degree_form", "MEDIUM", "descriptive linguistics", "DEPENDENCY_BASED", "OTHER", "A", "11-15", "three single-word spans and one two-word span", "26-35%", "SHORT_PHRASE"),
]

MICROBATCH_SIZES = [3, 3, 3, 3, 3, 3, 3, 3, 1]


def build() -> dict:
    assert len(SLOTS) == 25, len(SLOTS)
    assert sum(MICROBATCH_SIZES) == 25

    micro_of_slot: list[str] = []
    for index, size in enumerate(MICROBATCH_SIZES, start=1):
        micro_of_slot.extend([f"{BATCH_ID}-micro-{index:02d}"] * size)

    slots = []
    for order, (row, micro) in enumerate(zip(SLOTS, micro_of_slot), start=1):
        (primary_target, subtype, error_type, difficulty, domain, locality,
         granularity, position, length_region, span_profile, coverage_profile,
         correct_span_type) = row
        slots.append({
            "item_id": f"we-v2-pilot-{order:03d}",
            "item_generation_order": order,
            "microbatch_id": micro,
            "primary_target": primary_target,
            "subtype": subtype,
            "tested_error_type": error_type,
            "difficulty": difficulty,
            "vocabulary_domain": domain,
            "correction_locality": locality,
            "decision_granularity": granularity,
            "planned_correct_position": position,
            "format_plan": {
                "sentence_length_region": length_region,
                "expected_span_profile": span_profile,
                "expected_coverage_profile": coverage_profile,
                "expected_correct_span_type": correct_span_type,
                "expected_context_profile": "natural unmarked context before, between, and after the four spans",
            },
        })

    def counts(key, source=None):
        return dict(sorted(Counter(
            (slot[key] if source is None else slot[source][key]) for slot in slots
        ).items(), key=lambda kv: (-kv[1], kv[0])))

    return {
        "plan_version": "WE_V2_LIVE_PILOT_PLAN_1.0",
        "generation_batch_id": BATCH_ID,
        "section": "Written Expression",
        "generator_version": "Written Expression Generator v2.0",
        "reviewer_version": "Written Expression Reviewer v2.0",
        "spec_sources": [
            "specs/TOEFL_ITP_GRAMMAR_SPEC.md",
            "specs/toefl_itp_grammar_spec.json",
            "specs/TOEFL_ITP_WE_FORMAT_SPEC_ADDENDUM.md",
            "specs/toefl_itp_we_format_spec_addendum.json",
            "analysis/GRAMMAR_TAXONOMY.md",
            "analysis/grammar_taxonomy.json",
        ],
        "scope": {
            "initial_candidates": 25,
            "structure_items": 0,
            "replacement_generation": False,
            "evaluation_unit": "exactly 25 initial candidates",
        },
        "distribution_policy": "Official 125-item distributions are soft targets only; they are not quotas and are not copied mechanically per microbatch.",
        "microbatch_sizes": MICROBATCH_SIZES,
        "planned_distributions": {
            "primary_target": counts("primary_target"),
            "tested_error_type": counts("tested_error_type"),
            "difficulty": counts("difficulty"),
            "planned_correct_position": counts("planned_correct_position"),
            "correction_locality": counts("correction_locality"),
            "decision_granularity": counts("decision_granularity"),
            "sentence_length_region": counts("sentence_length_region", "format_plan"),
            "expected_correct_span_type": counts("expected_correct_span_type", "format_plan"),
        },
        "official_soft_reference": {
            "source": "analysis/we_format/written_expression_format_official.json",
            "item_count": 125,
            "sentence_median": 20,
            "span_median": 1,
            "coverage_median": 0.2632,
            "unmarked_context_median": 15,
            "gap_medians": {"gap_A_B": 4, "gap_B_C": 4, "gap_C_D": 4},
        },
        "slots": slots,
    }


if __name__ == "__main__":
    plan = build()
    OUT.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(plan["planned_distributions"], indent=2, ensure_ascii=False))
    print(f"wrote {OUT} with {len(plan['slots'])} slots")
