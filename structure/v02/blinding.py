"""Structure v0.2 blind candidate projection and deterministic ordering.

This module implements only:
  * pure extraction of the seven private Generator candidate identities;
  * domain-separated SHA-256 deterministic priority helpers (reviewer-order,
    and the future selection domain, exposed but unused here);
  * the blind Reviewer candidate projection (exact visible text only, no
    internal IDs, no Generator private metadata);
  * a pure validator that rebuilds and compares the expected projection.

No candidate selection, no pipeline, no prompts, and no model calls exist
here. See structure/v02/contracts.py for the Reviewer output contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from shared.schema_validation import load_schema, schema_errors


ROOT = Path(__file__).resolve().parent
REVIEWER_INPUT_SCHEMA_PATH = ROOT / "schemas" / "reviewer_input.schema.json"

CANDIDATE_IDS: tuple[str, ...] = ("correct", "d1", "d2", "d3", "d4", "d5", "d6")
DISTRACTOR_IDS: tuple[str, ...] = CANDIDATE_IDS[1:]

REVIEWER_ORDER_DOMAIN = "reviewer-order"
SELECTION_DOMAIN = "selection"

REVIEWER_INPUT_KEYS = ("item_id", "section", "stem", "candidate_options")


def validate_seed(seed: Any) -> int:
    """Return `seed` if it is a valid deterministic seed, else raise ValueError."""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be a non-negative integer, not a bool")
    if seed < 0:
        raise ValueError("seed must be a non-negative integer")
    return seed


def extract_candidate_entries(item: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return the seven private (candidate_id, text) entries for one Generator item.

    Order is always ("correct", "d1", ..., "d6"), independent of any dict
    iteration order in the source item.
    """

    if not isinstance(item, dict):
        raise TypeError("Generator item must be an object")
    correct_option = item.get("correct_option")
    if not isinstance(correct_option, dict) or not isinstance(correct_option.get("text"), str):
        raise ValueError(f"item {item.get('item_id', '?')}: correct_option.text is missing or invalid")
    distractor_candidates = item.get("distractor_candidates")
    if not isinstance(distractor_candidates, dict):
        raise ValueError(f"item {item.get('item_id', '?')}: distractor_candidates is missing or invalid")

    entries: list[tuple[str, str]] = [("correct", correct_option["text"])]
    for candidate_id in DISTRACTOR_IDS:
        candidate = distractor_candidates.get(candidate_id)
        if not isinstance(candidate, dict) or not isinstance(candidate.get("text"), str):
            raise ValueError(
                f"item {item.get('item_id', '?')}: distractor_candidates.{candidate_id}.text is missing or invalid"
            )
        entries.append((candidate_id, candidate["text"]))
    return entries


def _priority_digest(domain: str, seed: int, item_id: str, candidate_id: str) -> str:
    validate_seed(seed)
    material = f"structure-v0.2|{domain}|{seed}|{item_id}|{candidate_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def reviewer_order_priority(seed: int, item_id: str, candidate_id: str) -> str:
    """Return the deterministic SHA-256 hex priority for Reviewer-visible ordering."""

    return _priority_digest(REVIEWER_ORDER_DOMAIN, seed, item_id, candidate_id)


def selection_priority(seed: int, item_id: str, candidate_id: str) -> str:
    """Return the deterministic SHA-256 hex priority for the future selection domain.

    Exposed for later commits; not consumed for candidate selection here.
    """

    return _priority_digest(SELECTION_DOMAIN, seed, item_id, candidate_id)


def _ordered_visible_texts(item: Mapping[str, Any], seed: int) -> list[str]:
    item_id = item.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        raise ValueError("item_id must be a non-empty string")
    entries = extract_candidate_entries(item)

    texts = [text for _candidate_id, text in entries]
    if len(set(texts)) != len(texts):
        raise ValueError(f"item {item_id}: duplicate candidate text(s) among the seven raw candidates")

    ordered = sorted(entries, key=lambda entry: reviewer_order_priority(seed, item_id, entry[0]))
    return [text for _candidate_id, text in ordered]


def build_reviewer_candidate_input(generator: Mapping[str, Any], seed: Any) -> dict[str, Any]:
    """Project one Generator output batch to the v0.2 blind Reviewer candidate input."""

    validated_seed = validate_seed(seed)
    if not isinstance(generator, dict):
        raise ValueError("Generator output must be an object")
    items = generator.get("items")
    if not isinstance(items, list):
        raise ValueError("Generator output must contain an items array")

    payload_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Generator items must be objects")
        stem = item.get("stem")
        section = item.get("section")
        if section != "Structure":
            raise ValueError(f"item {item.get('item_id', '?')}: section must be Structure")
        if not isinstance(stem, str) or not stem:
            raise ValueError(f"item {item.get('item_id', '?')}: stem is missing or invalid")
        candidate_options = _ordered_visible_texts(item, validated_seed)
        payload_items.append({
            "item_id": item["item_id"],
            "section": "Structure",
            "stem": stem,
            "candidate_options": candidate_options,
        })

    payload = {"items": payload_items}
    errors = schema_errors(payload, load_schema(REVIEWER_INPUT_SCHEMA_PATH))
    if errors:
        raise ValueError("blind Reviewer candidate input failed schema validation: " + "; ".join(errors))
    return payload


def reviewer_candidate_input_errors(generator: Any, payload: Any, seed: Any) -> list[str]:
    """Return errors comparing `payload` against the deterministic expected projection."""

    try:
        validate_seed(seed)
    except ValueError as exc:
        return [str(exc)]
    if not isinstance(generator, dict) or not isinstance(payload, dict):
        return ["Structure blind candidate input and Generator output must be objects"]
    try:
        expected = build_reviewer_candidate_input(generator, seed)
    except ValueError as exc:
        return [f"Structure blind candidate input could not be derived: {exc}"]

    errors: list[str] = []
    if payload != expected:
        expected_items = {item["item_id"]: item for item in expected["items"]}
        payload_items = payload.get("items")
        if not isinstance(payload_items, list):
            errors.append("Structure blind candidate input does not match the canonical projection")
        else:
            for entry in payload_items:
                if not isinstance(entry, dict):
                    errors.append("Structure blind candidate input item is not an object")
                    continue
                item_id = entry.get("item_id")
                expected_item = expected_items.get(item_id)
                if expected_item is None:
                    errors.append(f"item {item_id}: unexpected or missing item_id in blind candidate input")
                    continue
                allowed_keys = set(REVIEWER_INPUT_KEYS)
                extra_keys = set(entry) - allowed_keys
                if extra_keys:
                    errors.append(f"item {item_id}: unexpected private field(s) {sorted(extra_keys)}")
                if entry.get("candidate_options") != expected_item["candidate_options"]:
                    errors.append(f"item {item_id}: candidate order or text does not match the expected projection")
                if entry.get("stem") != expected_item["stem"]:
                    errors.append(f"item {item_id}: stem does not match the Generator source")
                if entry.get("section") != "Structure":
                    errors.append(f"item {item_id}: section must be Structure")
        if not errors:
            errors.append("Structure blind candidate input does not match the canonical projection")

    errors.extend(schema_errors(payload, load_schema(REVIEWER_INPUT_SCHEMA_PATH)))
    return list(dict.fromkeys(errors))


__all__ = [
    "CANDIDATE_IDS",
    "DISTRACTOR_IDS",
    "REVIEWER_ORDER_DOMAIN",
    "SELECTION_DOMAIN",
    "REVIEWER_INPUT_KEYS",
    "validate_seed",
    "extract_candidate_entries",
    "reviewer_order_priority",
    "selection_priority",
    "build_reviewer_candidate_input",
    "reviewer_candidate_input_errors",
]
