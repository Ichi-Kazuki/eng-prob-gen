"""Small, provider-neutral helpers shared by the live batch drivers.

The state machine remains in :mod:`orchestrator`; these helpers only keep the
two persistence-oriented drivers from drifting in how they record external
stage results. Callers pass the production transition function explicitly so
tests and replay drivers retain the same validation boundary.
"""

from __future__ import annotations

from typing import Callable

from orchestrator import Candidate, strip_internal_test_keys


def apply_generation_result(
    candidate: Candidate,
    raw_item: dict,
    config: dict,
    process_generation: Callable[[Candidate, dict], Candidate],
) -> Candidate:
    """Persist one Generator result in generation history, then validate it."""
    item = strip_internal_test_keys(raw_item)
    candidate.generator_item = item
    candidate.generation_history.append({
        "attempt": candidate.generation_attempt,
        "item": item,
    })
    return process_generation(candidate, config)


def apply_review_result(
    candidate: Candidate,
    raw_item: dict,
    round_label: str,
    config: dict,
    process_review: Callable[[Candidate, dict], Candidate],
) -> Candidate:
    """Validate one Reviewer result and durably record its routed state."""
    item = strip_internal_test_keys(raw_item)
    candidate.reviewer_item = item
    candidate = process_review(candidate, config)
    candidate.review_history.append({
        "round": round_label,
        "output": item,
        "routed_state": candidate.state,
    })
    return candidate
