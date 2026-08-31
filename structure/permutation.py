"""Deterministic post-Generator answer-position permutation for Structure v0.1."""

from __future__ import annotations

import copy
import random
from collections import Counter
from typing import Any, Mapping

from .contracts import LETTERS


PERMUTATION_VERSION = "structure-answer-position-permutation-v0.1"


def _validate_seed(seed: int) -> None:
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("permutation seed must be a non-negative integer")


def target_final_positions(seed: int) -> list[str]:
    """Return the seeded target key sequence with exact 4/4/4/3 counts."""

    _validate_seed(seed)
    rng = random.Random(seed)
    short_key = rng.choice(LETTERS)
    targets = [key for key in LETTERS for _ in range(3 if key == short_key else 4)]
    rng.shuffle(targets)
    counts = Counter(targets)
    if sorted(counts.values()) != [3, 4, 4, 4]:
        raise AssertionError("answer-position target distribution is not 4/4/4/3")
    return targets


def permute_generator_output(generator: Mapping[str, Any], seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Move each original correct option to a seeded canonical key and remap rationales."""

    _validate_seed(seed)
    source_items = generator.get("items")
    if not isinstance(source_items, list) or len(source_items) != 15:
        raise ValueError("answer permutation requires exactly 15 Generator items")
    targets = target_final_positions(seed)
    # Mapping draws use a fresh deterministic stream. The target sequence is
    # already fully determined by the same Planner seed above.
    mapping_rng = random.Random(seed)

    output = copy.deepcopy(dict(generator))
    records: list[dict[str, Any]] = []
    for index, item in enumerate(source_items):
        if not isinstance(item, dict):
            raise ValueError(f"answer permutation item {index} is not an object")
        original_correct = item.get("correct_answer")
        if original_correct not in LETTERS:
            raise ValueError(f"answer permutation item {index} has an invalid correct_answer")
        final_correct = targets[index]
        remaining_originals = [key for key in LETTERS if key != original_correct]
        remaining_canonical = [key for key in LETTERS if key != final_correct]
        mapping_rng.shuffle(remaining_originals)
        mapping_rng.shuffle(remaining_canonical)
        original_to_canonical = {original_correct: final_correct}
        original_to_canonical.update(dict(zip(remaining_originals, remaining_canonical)))
        canonical_to_original = {canonical: original for original, canonical in original_to_canonical.items()}

        original_options = item.get("options", {})
        original_rationales = item.get("distractor_rationales", {})
        if not isinstance(original_options, dict) or not isinstance(original_rationales, dict):
            raise ValueError(f"answer permutation item {index} is missing options/rationales")
        item_copy = output["items"][index]
        item_copy["options"] = {
            canonical: copy.deepcopy(original_options[original])
            for canonical, original in canonical_to_original.items()
        }
        item_copy["distractor_rationales"] = {
            canonical: copy.deepcopy(original_rationales[original])
            for canonical, original in canonical_to_original.items()
        }
        item_copy["correct_answer"] = final_correct
        records.append({
            "item_id": item.get("item_id"),
            "original_correct_answer": original_correct,
            "canonical_correct_answer": final_correct,
            "original_to_canonical": original_to_canonical,
            "canonical_to_original": canonical_to_original,
        })

    permutation = {
        "version": PERMUTATION_VERSION,
        "seed_material": {
            "planner_seed": seed,
            "rng": "python.random.Random",
            "algorithm": "MT19937",
            "target_position_derivation": "seeded choice of the 3-count key, then seeded shuffle",
            "mapping_derivation": "seeded shuffle of remaining original and canonical keys per item",
        },
        "target_final_answer_positions": targets,
        "final_answer_position_distribution": dict(sorted(Counter(targets).items())),
        "items": records,
    }
    return output, permutation


apply_answer_permutation = permute_generator_output
permute_answer_positions = permute_generator_output
final_answer_positions = target_final_positions
