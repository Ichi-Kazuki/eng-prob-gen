"""Structure v0.2 deterministic candidate selection and final assembly.

Implements only:
  * private exact-text reconciliation between one Generator item's seven
    raw candidates and the canonical blind Reviewer judgment/diagnostic
    for those same exact texts;
  * the intended-correct acceptance rule (VALID + natural_wording==true +
    serious_defect==false);
  * INVALID-only distractor eligibility with a deterministic SHA-256
    priority order over d1..d6, selecting the first three eligible
    candidates;
  * a pure replay validator that rebuilds and compares the expected
    selection artifact;
  * pre-permutation four-option final assembly (A = intended correct,
    B/C/D = the three selected distractors in priority order).

No model calls, no regeneration, no repair, and no item replacement
happen here. The frozen answer-position permutation in
structure/permutation.py is applied later, outside this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shared.schema_validation import load_schema, schema_errors

from structure.v02.blinding import (
    DISTRACTOR_IDS,
    extract_candidate_entries,
    selection_priority,
    validate_seed,
)


ROOT = Path(__file__).resolve().parent
CANDIDATE_SELECTION_SCHEMA_PATH = ROOT / "schemas" / "candidate_selection.schema.json"
GENERATOR_FINAL_SCHEMA_PATH = ROOT / "schemas" / "generator_final.schema.json"

VALID = "VALID"
INVALID = "INVALID"
MARGINAL = "MARGINAL"
JUDGMENTS = frozenset({VALID, INVALID, MARGINAL})


def _generator_items(generator: Any) -> list[dict[str, Any]]:
    if not isinstance(generator, dict):
        raise ValueError("Generator output must be an object")
    items = generator.get("items")
    if not isinstance(items, list) or len(items) != 15:
        raise ValueError("Generator output must contain exactly 15 items")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Generator items must be objects")
    return items


def _canonical_reviewer_errors(
    generator_items: list[dict[str, Any]], canonical_reviewer: Any
) -> list[str]:
    """Fail-closed structural preconditions for the canonical Reviewer object.

    Requires exactly 15 items in Generator order/identity, option_judgments
    keys exactly equal to the seven Generator visible texts, and
    candidate_diagnostics keys exactly equal to all and only the
    VALID/MARGINAL texts (so INVALID texts have no diagnostic).
    """

    if not isinstance(canonical_reviewer, dict):
        return ["canonical Reviewer output must be an object"]
    items = canonical_reviewer.get("items")
    if not isinstance(items, list) or len(items) != 15:
        return ["canonical Reviewer output must contain exactly 15 items"]

    generated_ids = [item.get("item_id") for item in generator_items]
    reviewer_ids = [item.get("item_id") if isinstance(item, dict) else None for item in items]
    if reviewer_ids != generated_ids:
        return ["canonical Reviewer item IDs/order do not match Generator"]

    errors: list[str] = []
    for gen_item, item in zip(generator_items, items):
        item_id = item.get("item_id") if isinstance(item, dict) else None
        if not isinstance(item, dict):
            errors.append(f"item {item_id}: canonical Reviewer item must be an object")
            continue

        entries = extract_candidate_entries(gen_item)
        expected_texts = {text for _candidate_id, text in entries}

        option_judgments = item.get("option_judgments")
        if not isinstance(option_judgments, dict) or set(option_judgments) != expected_texts:
            errors.append(
                f"item {item_id}: canonical option_judgments keys must exactly equal the seven "
                "Generator visible texts"
            )
            continue
        if any(judgment not in JUDGMENTS for judgment in option_judgments.values()):
            errors.append(f"item {item_id}: canonical option_judgments values must be VALID/INVALID/MARGINAL")
            continue

        candidate_diagnostics = item.get("candidate_diagnostics")
        if not isinstance(candidate_diagnostics, dict):
            errors.append(f"item {item_id}: canonical candidate_diagnostics must be an object")
            continue
        valid_marginal_texts = {
            text for text, judgment in option_judgments.items() if judgment in (VALID, MARGINAL)
        }
        if set(candidate_diagnostics) != valid_marginal_texts:
            errors.append(
                f"item {item_id}: canonical candidate_diagnostics keys must exactly equal all and only "
                "the VALID/MARGINAL texts"
            )
            continue
        for text, diagnostic in candidate_diagnostics.items():
            if (
                not isinstance(diagnostic, dict)
                or not isinstance(diagnostic.get("natural_wording"), bool)
                or not isinstance(diagnostic.get("serious_defect"), bool)
            ):
                errors.append(
                    f"item {item_id}: canonical candidate_diagnostics[{text!r}] must carry boolean "
                    "natural_wording/serious_defect"
                )

    return errors


def build_candidate_selection(
    generator: Any, canonical_reviewer: Any, seed: Any
) -> dict[str, Any]:
    """Deterministically reconcile one Generator batch against its canonical Reviewer.

    Reconciliation and eligibility use exact raw-string identity only; no
    fuzzy matching, trimming, casefolding, NFKC, or whitespace normalization
    is applied. Reviewer `comment`, difficulty, and observed_clause_count
    never influence the result.
    """

    validated_seed = validate_seed(seed)
    generator_items = _generator_items(generator)

    canonical_errors = _canonical_reviewer_errors(generator_items, canonical_reviewer)
    if canonical_errors:
        raise ValueError(
            "canonical Reviewer output is structurally inconsistent: " + "; ".join(canonical_errors)
        )

    reviewer_items_by_id = {item["item_id"]: item for item in canonical_reviewer["items"]}

    selection_items: list[dict[str, Any]] = []
    for item in generator_items:
        item_id = item["item_id"]
        entries = extract_candidate_entries(item)
        text_by_id = dict(entries)
        if len(set(text_by_id.values())) != 7:
            raise ValueError(f"item {item_id}: seven candidate texts are not unique; cannot reconcile privately")

        reviewer_item = reviewer_items_by_id[item_id]
        option_judgments = reviewer_item["option_judgments"]
        candidate_diagnostics = reviewer_item["candidate_diagnostics"]

        correct_text = text_by_id["correct"]
        intended_judgment = option_judgments[correct_text]

        failure_reasons: list[str] = []
        natural_wording: bool | None
        serious_defect: bool | None

        if intended_judgment == INVALID:
            natural_wording = None
            serious_defect = None
            failure_reasons.append("intended_correct_not_valid:INVALID")
        else:
            diagnostic = candidate_diagnostics[correct_text]
            natural_wording = diagnostic["natural_wording"]
            serious_defect = diagnostic["serious_defect"]
            if intended_judgment == MARGINAL:
                failure_reasons.append("intended_correct_not_valid:MARGINAL")
            else:
                if natural_wording is not True:
                    failure_reasons.append("intended_correct_natural_wording_false")
                if serious_defect is not False:
                    failure_reasons.append("intended_correct_serious_defect_true")

        priority_order = sorted(
            DISTRACTOR_IDS,
            key=lambda candidate_id: (selection_priority(validated_seed, item_id, candidate_id), candidate_id),
        )

        eligible_invalid: list[str] = []
        rejected_valid: list[str] = []
        rejected_marginal: list[str] = []
        for candidate_id in priority_order:
            judgment = option_judgments[text_by_id[candidate_id]]
            if judgment == INVALID:
                eligible_invalid.append(candidate_id)
            elif judgment == VALID:
                rejected_valid.append(candidate_id)
            else:
                rejected_marginal.append(candidate_id)

        selected_ids = eligible_invalid[:3]
        if len(eligible_invalid) < 3:
            failure_reasons.append(f"insufficient_invalid_distractors:{len(eligible_invalid)}")
        selected_texts = [text_by_id[candidate_id] for candidate_id in selected_ids]

        selection_items.append({
            "item_id": item_id,
            "intended_correct_text": correct_text,
            "intended_correct_judgment": intended_judgment,
            "intended_correct_natural_wording": natural_wording,
            "intended_correct_serious_defect": serious_defect,
            "eligible_invalid_candidate_ids": eligible_invalid,
            "rejected_valid_candidate_ids": rejected_valid,
            "rejected_marginal_candidate_ids": rejected_marginal,
            "deterministic_priority_order": priority_order,
            "selected_candidate_ids": selected_ids,
            "selected_candidate_texts": selected_texts,
            "passed": not failure_reasons,
            "failure_reasons": failure_reasons,
        })

    selection = {
        "schema_version": "structure-candidate-selection-v0.2",
        "version": "v0.2",
        "seed": validated_seed,
        "items": selection_items,
    }
    schema_validation_errors = schema_errors(selection, load_schema(CANDIDATE_SELECTION_SCHEMA_PATH))
    if schema_validation_errors:
        raise ValueError(
            "constructed candidate selection failed schema validation: " + "; ".join(schema_validation_errors)
        )
    return selection


def candidate_selection_errors(
    generator: Any, canonical_reviewer: Any, selection: Any, seed: Any
) -> list[str]:
    """Return errors comparing `selection` against the deterministic replay result.

    No repair or fuzzy reconciliation is attempted: a tampered artifact
    simply fails to compare equal to the freshly rebuilt expectation.
    """

    try:
        expected = build_candidate_selection(generator, canonical_reviewer, seed)
    except ValueError as exc:
        return [f"candidate selection could not be derived for replay: {exc}"]

    errors = schema_errors(selection, load_schema(CANDIDATE_SELECTION_SCHEMA_PATH))
    if selection != expected:
        errors.append("candidate selection does not match the deterministic replay result")
    return list(dict.fromkeys(errors))


def assemble_final_generator_output(generator: Any, selection: Any) -> dict[str, Any]:
    """Assemble the pre-permutation four-option final batch.

    This is a deterministic artifact-integrity boundary: every mutable
    field the selection artifact carries (semantic pass invariants, the
    seed-derived deterministic priority order, and the three-way
    classification partition) is independently re-verified against the
    already-existing SHA-256 selection_priority helper before any option
    is assembled. Fails closed (raises ValueError) rather than repairing
    or assembling a partial batch. A = the intended correct option,
    B/C/D = the three selected distractors in deterministic-priority
    order. correct_answer == "A" always, since this is the internal
    layout before structure/permutation.py runs (not called here).
    """

    generator_items = _generator_items(generator)

    if not isinstance(selection, dict):
        raise ValueError("candidate selection must be an object")

    selection_schema_errors = schema_errors(selection, load_schema(CANDIDATE_SELECTION_SCHEMA_PATH))
    if selection_schema_errors:
        raise ValueError(
            "candidate selection failed schema validation: " + "; ".join(selection_schema_errors)
        )

    selection_seed = validate_seed(selection["seed"])
    selection_items = selection["items"]

    generator_ids = [item["item_id"] for item in generator_items]
    selection_ids = [item["item_id"] for item in selection_items]
    if generator_ids != selection_ids:
        raise ValueError("candidate selection item IDs/order do not match Generator")

    final_items: list[dict[str, Any]] = []
    for item, sel in zip(generator_items, selection_items):
        item_id = item["item_id"]
        entries = extract_candidate_entries(item)
        text_by_id = dict(entries)

        if sel["passed"] is not True:
            raise ValueError(f"item {item_id}: candidate selection item must have passed exactly True")
        if sel["failure_reasons"] != []:
            raise ValueError(f"item {item_id}: candidate selection item must have empty failure_reasons")
        if sel["intended_correct_judgment"] != VALID:
            raise ValueError(f"item {item_id}: intended_correct_judgment must be exactly VALID")
        if sel["intended_correct_natural_wording"] is not True:
            raise ValueError(f"item {item_id}: intended_correct_natural_wording must be exactly True")
        if sel["intended_correct_serious_defect"] is not False:
            raise ValueError(f"item {item_id}: intended_correct_serious_defect must be exactly False")

        distractor_candidates = item.get("distractor_candidates")
        if not isinstance(distractor_candidates, dict):
            raise ValueError(f"item {item_id}: distractor_candidates is missing or invalid")
        rationale_by_id = {"correct": item.get("answer_explanation")}
        for candidate_id in DISTRACTOR_IDS:
            candidate = distractor_candidates.get(candidate_id)
            if not isinstance(candidate, dict):
                raise ValueError(f"item {item_id}: distractor_candidates.{candidate_id} is missing or invalid")
            rationale_by_id[candidate_id] = candidate.get("rationale")

        intended_text = sel["intended_correct_text"]
        if text_by_id["correct"] != intended_text:
            raise ValueError(f"item {item_id}: candidate selection intended_correct_text does not match Generator")

        expected_priority_order = sorted(
            DISTRACTOR_IDS,
            key=lambda candidate_id: (selection_priority(selection_seed, item_id, candidate_id), candidate_id),
        )
        if sel["deterministic_priority_order"] != expected_priority_order:
            raise ValueError(
                f"item {item_id}: deterministic_priority_order does not match the recomputed seed-derived "
                "selection priority"
            )

        eligible = sel["eligible_invalid_candidate_ids"]
        rejected_valid = sel["rejected_valid_candidate_ids"]
        rejected_marginal = sel["rejected_marginal_candidate_ids"]
        classification_lists = {
            "eligible_invalid_candidate_ids": eligible,
            "rejected_valid_candidate_ids": rejected_valid,
            "rejected_marginal_candidate_ids": rejected_marginal,
        }
        for name, class_list in classification_lists.items():
            if (
                not isinstance(class_list, list)
                or any(candidate_id not in DISTRACTOR_IDS for candidate_id in class_list)
                or len(set(class_list)) != len(class_list)
            ):
                raise ValueError(f"item {item_id}: {name} must be a list of unique d1..d6 IDs with no duplicates")

        eligible_set = set(eligible)
        rejected_valid_set = set(rejected_valid)
        rejected_marginal_set = set(rejected_marginal)
        if (
            eligible_set & rejected_valid_set
            or eligible_set & rejected_marginal_set
            or rejected_valid_set & rejected_marginal_set
        ):
            raise ValueError(f"item {item_id}: classification lists must not overlap")
        if eligible_set | rejected_valid_set | rejected_marginal_set != set(DISTRACTOR_IDS):
            raise ValueError(
                f"item {item_id}: eligible/rejected_valid/rejected_marginal lists must together partition d1..d6"
            )

        class_sets = {
            "eligible_invalid_candidate_ids": eligible_set,
            "rejected_valid_candidate_ids": rejected_valid_set,
            "rejected_marginal_candidate_ids": rejected_marginal_set,
        }
        for name, class_list in classification_lists.items():
            expected_class_order = [
                candidate_id for candidate_id in expected_priority_order if candidate_id in class_sets[name]
            ]
            if class_list != expected_class_order:
                raise ValueError(
                    f"item {item_id}: {name} order does not follow the recomputed deterministic priority order"
                )

        selected_ids = sel["selected_candidate_ids"]
        selected_texts = sel["selected_candidate_texts"]
        if not isinstance(selected_ids, list) or len(selected_ids) != 3 or len(set(selected_ids)) != 3:
            raise ValueError(f"item {item_id}: candidate selection must have exactly 3 unique selected IDs")
        if any(candidate_id not in DISTRACTOR_IDS for candidate_id in selected_ids):
            raise ValueError(f"item {item_id}: selected candidate IDs must belong to d1..d6")
        if not isinstance(selected_texts, list) or [text_by_id[cid] for cid in selected_ids] != selected_texts:
            raise ValueError(f"item {item_id}: selected candidate texts do not match selected IDs")
        if any(candidate_id not in eligible_set for candidate_id in selected_ids):
            raise ValueError(f"item {item_id}: selected candidate IDs must be eligible_invalid_candidate_ids")
        expected_first_three = [candidate_id for candidate_id in expected_priority_order if candidate_id in eligible_set][:3]
        if selected_ids != expected_first_three:
            raise ValueError(
                f"item {item_id}: selected candidate IDs are not the first 3 eligible IDs under "
                "the recomputed deterministic priority order"
            )

        options = {
            "A": intended_text,
            "B": selected_texts[0],
            "C": selected_texts[1],
            "D": selected_texts[2],
        }
        distractor_rationales = {
            "A": rationale_by_id["correct"],
            "B": rationale_by_id[selected_ids[0]],
            "C": rationale_by_id[selected_ids[1]],
            "D": rationale_by_id[selected_ids[2]],
        }

        final_items.append({
            "item_id": item_id,
            "section": item.get("section"),
            "primary_target": item.get("primary_target"),
            "subtype": item.get("subtype"),
            "secondary_features": item.get("secondary_features"),
            "difficulty": item.get("difficulty"),
            "vocabulary_domain": item.get("vocabulary_domain"),
            "stem": item.get("stem"),
            "options": options,
            "correct_answer": "A",
            "answer_explanation": item.get("answer_explanation"),
            "distractor_rationales": distractor_rationales,
        })

    final = {"items": final_items}
    schema_validation_errors = schema_errors(final, load_schema(GENERATOR_FINAL_SCHEMA_PATH))
    if schema_validation_errors:
        raise ValueError(
            "assembled final generator output failed schema validation: " + "; ".join(schema_validation_errors)
        )
    return final


__all__ = [
    "build_candidate_selection",
    "candidate_selection_errors",
    "assemble_final_generator_output",
]
