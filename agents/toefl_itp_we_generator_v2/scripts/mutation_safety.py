"""Fail-closed safety checks for Written Expression grammar mutations.

This module deliberately does not decide format geometry, span selection, or
Reviewer/Solver routing.  It protects the mutation boundary only:

* known unsafe template families are quarantined or guarded;
* the clean -> error surface edit remains local to the declared span;
* mutation metadata describes the same lexical change as the item; and
* an external grammar runtime can attach the strong one-error invariant.

The local checks are intentionally conservative.  They are not a replacement
for a grammar-capable Generator/Reviewer runtime.  When external grammar
evidence is absent, ``grammar_evidence_status`` is
``REQUIRES_EXTERNAL_REVIEW`` rather than silently claiming a grammaticality
judgement.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping


try:
    from shared.tokenization import lexical_token_matches, lexical_token_spans, lexical_tokens
except ModuleNotFoundError:  # pragma: no cover - supports direct CLI execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from shared.tokenization import lexical_token_matches, lexical_token_spans, lexical_tokens


LABELS = ("A", "B", "C", "D")
PRONOUNS = {"it", "he", "she", "they", "him", "her", "them", "its", "their"}
REFERENCE_FEATURES: dict[str, tuple[str, str]] = {
    # value: (number, person)
    "i": ("singular", "first"),
    "me": ("singular", "first"),
    "we": ("plural", "first"),
    "us": ("plural", "first"),
    "you": ("ambiguous", "second"),
    "he": ("singular", "third"),
    "him": ("singular", "third"),
    "she": ("singular", "third"),
    "her": ("singular", "third"),
    "it": ("singular", "third"),
    "they": ("plural", "third"),
    "them": ("plural", "third"),
    # Possessive determiners/pronouns participate in the same objective
    # number/person agreement checks as their corresponding personal forms.
    "my": ("singular", "first"),
    "our": ("plural", "first"),
    "your": ("ambiguous", "second"),
    "his": ("singular", "third"),
    "its": ("singular", "third"),
    "their": ("plural", "third"),
    "mine": ("singular", "first"),
    "ours": ("plural", "first"),
    "yours": ("ambiguous", "second"),
    "hers": ("singular", "third"),
    "theirs": ("plural", "third"),
    "this": ("singular", "third"),
    "that": ("singular", "third"),
    "these": ("plural", "third"),
    "those": ("plural", "third"),
}
REFERENCE_DETERMINERS: dict[str, str] = {
    "a": "singular", "an": "singular", "each": "singular", "every": "singular",
    "either": "singular", "neither": "singular", "many": "plural", "few": "plural",
    "several": "plural", "both": "plural", "much": "mass", "little": "mass",
}
REFERENCE_FUNCTION_WORDS = {
    "a", "an", "the", "this", "that", "these", "those", "each", "every",
    "either", "neither", "many", "few", "several", "both", "much", "little",
    "of", "after", "before", "during", "from", "in", "on", "to", "with",
    "and", "or", "but", "if", "because", "when", "while", "as", "than",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "has", "have", "had", "will", "can", "may", "must", "should", "could",
    "would", "might", "not", "very", "more", "most",
    "my", "our", "your", "his", "its", "their", "mine", "ours", "yours", "hers", "theirs",
}
FINITE_VERB_FORMS = {
    # Lexical finite verbs that do not carry the regular -ed/-ing signal and
    # would otherwise look like singular noun heads during antecedent scans.
    "arise", "arose", "become", "became", "begin", "began", "bring", "brought",
    "come", "came", "do", "did", "draw", "drew", "drink", "drank", "drive", "drove",
    "eat", "ate", "fall", "fell", "feel", "felt", "find", "found", "fly", "flew",
    "forget", "forgot", "give", "gave", "go", "went", "grow", "grew", "hear", "heard",
    "hold", "held", "keep", "kept", "know", "knew", "leave", "left", "make", "made",
    "mean", "meant", "meet", "met", "pay", "paid", "read", "run", "ran", "say", "said",
    "see", "saw", "send", "sent", "set", "speak", "spoke", "stand", "stood", "take",
    "took", "tell", "told", "think", "thought", "understand", "understood", "write", "wrote",
}
SINGULAR_NOUN_EXCEPTIONS = {
    "analysis", "basis", "crisis", "diagnosis", "hypothesis", "news", "series",
    "species", "status", "thesis", "this", "physics", "mathematics", "research",
    "information", "equipment", "evidence",
}
# A small deterministic lexical layer is enough for the noun-phrase shape
# this guard needs.  It prevents an attributive adjective from being treated
# as the head noun while keeping the validator independent of an NLP runtime.
COMMON_ATTRIBUTIVE_ADJECTIVES = {
    "ancient", "annual", "central", "coastal", "consistent", "deep", "detailed",
    "digital", "early", "eastern", "extended", "faint", "fragile", "heavy",
    "large", "local", "long", "new", "northern", "odd", "older", "polar",
    "prolonged", "rare", "regional", "remote", "revised", "shared", "small",
    "subtle", "unusual", "updated", "western", "winter", "young",
}
ADJECTIVE_SUFFIXES = ("able", "ible", "al", "ant", "ary", "ent", "ful", "ic", "ish", "ive", "less", "ous", "y")
PERSONAL_PRONOUNS = {"i", "me", "we", "us", "you", "he", "him", "she", "her", "they", "them"}
MODAL_TRIGGERS = {"will", "can", "may", "must", "should", "could", "would", "might"}
STRONG_INVARIANT_NAMES = (
    "clean_sentence_grammatical",
    "mutated_sentence_ungrammatical",
    "exactly_one_grammatical_defect",
    "declared_marked_span_contains_defect",
    "minimal_repair_restores_grammaticality",
    "no_plausible_alternate_parse",
    "defect_is_grammatical_not_semantic",
)
EVIDENCE_PROVENANCE_REQUIRED_FIELDS = (
    "evidence_producer",
    "evidence_producer_version",
    "invocation_id",
    "created_at",
    "evidence_method",
    "model_identifier",
)
ARROW_RE = re.compile(r"(?P<left>[^:;\n]+?)\s*(?:->|→)\s*(?P<right>[^,;\n]+)")
CHANGE_BODY_RE = re.compile(
    r"\b(?:change|replace)\s+(?P<body>.+?)(?:[.!?]|$)",
    re.IGNORECASE,
)
CORRECTION_CONNECTOR_RE = re.compile(r"\b(?:to|with)\b", re.IGNORECASE)
REMOVE_USE_RE = re.compile(
    r"\bremove\s+(?P<source>\S+).*?\buse\s+(?P<target>\S+)",
    re.IGNORECASE,
)
REORDER_RE = re.compile(
    r"\breorder\s+(?P<source>.+?)\s+as\s+(?P<target>.+?)(?:[.!?]|$)",
    re.IGNORECASE,
)


def evidence_provenance_errors(record: Mapping[str, Any]) -> list[str]:
    """Validate audit provenance without treating it as cryptographic proof.

    These fields make an evidence record attributable and replay-auditable.
    They do not authenticate the producer; only the content hash binds the
    record to the current item, and no signature/HMAC is implied here.
    """
    errors: list[str] = []
    for field in EVIDENCE_PROVENANCE_REQUIRED_FIELDS:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} must be a nonempty string")
    content_hash = record.get("content_hash")
    if not isinstance(content_hash, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash):
        errors.append("content_hash must match sha256:<64 lowercase hexadecimal characters>")
    created_at = record.get("created_at")
    if isinstance(created_at, str) and created_at.strip():
        try:
            parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("created_at must be an ISO-8601 timestamp")
        else:
            if parsed_created_at.tzinfo is None:
                errors.append("created_at must include a timezone offset")
    return errors


class TemplateClass(str, Enum):
    SAFE = "SAFE"
    NEEDS_GUARD = "NEEDS_GUARD"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True)
class TemplateRecord:
    template_id: str
    tested_error_type: str
    primary_target: str
    classification: TemplateClass
    guard: str
    rationale: str


@dataclass
class MutationSafetyResult:
    status: str
    template_class: str
    template_id: str
    reasons: list[str]
    metadata_consistent: bool
    surface_integrity: bool
    grammar_evidence_status: str
    invariants: dict[str, bool | None]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Catalogued template families.  The catalog is deliberately broader than the
# four pilot failures so future generation cannot quietly reintroduce the same
# mechanisms under a new sentence.
TEMPLATE_CATALOG: tuple[TemplateRecord, ...] = (
    TemplateRecord(
        "reference.ambiguous_pronoun_substitution",
        "incorrect_reference",
        "REFERENCE_AND_DETERMINERS",
        TemplateClass.QUARANTINE,
        "formal_reference_evidence_required",
        "A nearby noun is not evidence of a grammatical reference error.",
    ),
    TemplateRecord(
        "reference.number_disagreement",
        "incorrect_reference",
        "REFERENCE_AND_DETERMINERS",
        TemplateClass.SAFE,
        "number_mismatch_required",
        "Objective number disagreement is a formally testable defect.",
    ),
    TemplateRecord(
        "reference.person_disagreement",
        "incorrect_reference",
        "REFERENCE_AND_DETERMINERS",
        TemplateClass.SAFE,
        "person_mismatch_required",
        "Objective person disagreement is a formally testable defect.",
    ),
    TemplateRecord(
        "reference.demonstrative_determiner_form",
        "incorrect_reference",
        "REFERENCE_AND_DETERMINERS",
        TemplateClass.SAFE,
        "determiner_form_required",
        "A demonstrative/determiner form must be licensed by the noun phrase.",
    ),
    TemplateRecord(
        "reference.invalid_antecedent_relation",
        "incorrect_reference",
        "REFERENCE_AND_DETERMINERS",
        TemplateClass.NEEDS_GUARD,
        "formally_invalid_antecedent_relation_required",
        "The antecedent relation must be formally impossible, not merely unclear.",
    ),
    TemplateRecord(
        "degree.comparative_superlative_explicit_than",
        "wrong_degree_form",
        "COMPARATIVES_DEGREE",
        TemplateClass.NEEDS_GUARD,
        "explicit_comparative_trigger_required",
        "Most X than is invalid only because an explicit comparative trigger is present.",
    ),
    TemplateRecord(
        "degree.invalid_comparative_morphology",
        "wrong_degree_form",
        "COMPARATIVES_DEGREE",
        TemplateClass.SAFE,
        "morphological_defect_required",
        "The mutation must damage comparative/superlative morphology.",
    ),
    TemplateRecord(
        "degree.semantic_marker_substitution",
        "wrong_degree_form",
        "COMPARATIVES_DEGREE",
        TemplateClass.QUARANTINE,
        "morphosyntax_required",
        "Sufficiently/too and enough/too substitutions can both be grammatical.",
    ),
    TemplateRecord(
        "parallel.base_form_to_ing",
        "wrong_verb_form",
        "PARALLEL_STRUCTURE",
        TemplateClass.NEEDS_GUARD,
        "forced_coordination_and_no_alternate_parse",
        "An -ing phrase after a comma can survive as a participial clause.",
    ),
    TemplateRecord(
        "parallel.agreement_form_mismatch",
        "agreement_error",
        "PARALLEL_STRUCTURE",
        TemplateClass.NEEDS_GUARD,
        "coordination_scope_required",
        "Agreement mutations must identify the coordinated subject/verb scope.",
    ),
    TemplateRecord(
        "degree.unclassified_mutation",
        "wrong_degree_form",
        "COMPARATIVES_DEGREE",
        TemplateClass.QUARANTINE,
        "morphosyntax_required",
        "Unclassified degree mutations cannot be accepted without a morphosyntactic trigger.",
    ),
)


def _norm_tokens(text: str) -> list[str]:
    return [token.casefold() for token in lexical_tokens(text)]


def _contains_phrase(haystack: Iterable[str], needle: Iterable[str]) -> bool:
    hay = list(haystack)
    ned = list(needle)
    if not ned:
        return False
    width = len(ned)
    return any(hay[i : i + width] == ned for i in range(len(hay) - width + 1))


def _direction(text: str) -> tuple[str, str] | None:
    match = ARROW_RE.search(text or "")
    if not match:
        return None
    return match.group("left").strip(), match.group("right").strip().rstrip(".")


def _direction_tokens(text: str) -> tuple[list[str], list[str]] | None:
    parsed = _direction(text)
    if parsed is None:
        return None
    return _norm_tokens(parsed[0]), _norm_tokens(parsed[1])


def _extract_correction_direction(
    text: str,
    *,
    expected_source: list[str] | None = None,
    expected_target: list[str] | None = None,
) -> tuple[list[str], list[str]] | None:
    # Minimal corrections may use the same compact arrow notation as
    # mutation_type (for example, ``record -> records``).  Parse it first so
    # the prose-specific handlers below do not reject valid metadata.
    arrow_direction = _direction_tokens(text)
    if arrow_direction is not None:
        return arrow_direction

    change = CHANGE_BODY_RE.search(text or "")
    if change:
        body = change.group("body").strip()
        candidates: list[tuple[list[str], list[str]]] = []
        for connector in CORRECTION_CONNECTOR_RE.finditer(body):
            source = _norm_tokens(body[: connector.start()].strip())
            target = _norm_tokens(body[connector.end() :].strip())
            if source and target:
                candidates.append((source, target))
        if expected_source is not None and expected_target is not None:
            for source, target in candidates:
                if _contains_phrase(source, expected_source) and _contains_phrase(target, expected_target):
                    return source, target
        if candidates:
            return candidates[0]

    match = REORDER_RE.search(text or "")
    if match:
        return _norm_tokens(match.group("source")), _norm_tokens(match.group("target"))
    match = REMOVE_USE_RE.search(text or "")
    if match:
        return _norm_tokens(match.group("source")), _norm_tokens(match.group("target"))
    return None


def _diff_tokens(clean: str, error: str) -> tuple[list[str], list[str], list[tuple[str, int, int, int, int]]]:
    clean_tokens = _norm_tokens(clean)
    error_tokens = _norm_tokens(error)
    matcher = SequenceMatcher(a=clean_tokens, b=error_tokens, autojunk=False)
    opcodes = matcher.get_opcodes()
    changed_clean: list[str] = []
    changed_error: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "equal":
            changed_clean.extend(clean_tokens[i1:i2])
            changed_error.extend(error_tokens[j1:j2])
    return changed_clean, changed_error, [op for op in opcodes if op[0] != "equal"]


def _is_single_contiguous_reorder(clean_tokens: list[str], error_tokens: list[str]) -> bool:
    """Return whether error_tokens moves exactly one clean-side token span.

    A matching token multiset is not sufficient: two disjoint swaps and other
    broad permutations also preserve the multiset.  Model a reorder as one
    contiguous block removed from the clean sequence and inserted elsewhere,
    while requiring the untouched tokens to retain their relative order.
    """

    if clean_tokens == error_tokens or Counter(clean_tokens) != Counter(error_tokens):
        return False

    for start in range(len(clean_tokens)):
        for end in range(start + 1, len(clean_tokens) + 1):
            moved = clean_tokens[start:end]
            remaining = clean_tokens[:start] + clean_tokens[end:]
            for insertion in range(len(remaining) + 1):
                if insertion == start:
                    continue
                candidate = remaining[:insertion] + moved + remaining[insertion:]
                if candidate == error_tokens:
                    return True
    return False


def _surface_edit_is_local(clean: str, error: str) -> tuple[bool, dict[str, Any]]:
    changed_clean, changed_error, opcodes = _diff_tokens(clean, error)
    clean_tokens = _norm_tokens(clean)
    error_tokens = _norm_tokens(error)
    reordered = bool(opcodes) and _is_single_contiguous_reorder(clean_tokens, error_tokens)
    one_edit = len(opcodes) == 1 or reordered
    changed_error_indices: list[int] = []
    changed_error_boundaries: list[int] = []
    for tag, _, _, start, end in opcodes:
        if tag == "delete":
            # A deleted clean-side token has no error-side token index.  Keep
            # its insertion boundary so a marked span ending at (or beginning
            # at) that boundary can still own the omission defect.
            changed_error_indices.append(start)
            changed_error_boundaries.append(start)
        else:
            changed_error_indices.extend(range(start, end))
    return one_edit and bool(changed_clean or changed_error), {
        "changed_clean_tokens": changed_clean,
        "changed_error_tokens": changed_error,
        "changed_error_indices": changed_error_indices,
        "changed_error_boundaries": changed_error_boundaries,
        "opcode_count": len(opcodes),
        "reordered": reordered,
    }


def _metadata_audit(
    clean: str,
    error: str,
    mutation_type: str,
    minimal_correction: str,
    answer_explanation: str,
) -> tuple[bool, list[str]]:
    issues: list[str] = []
    clean_tokens = _norm_tokens(clean)
    error_tokens = _norm_tokens(error)
    changed_clean, changed_error, opcodes = _diff_tokens(clean, error)
    reordered = bool(opcodes) and _is_single_contiguous_reorder(clean_tokens, error_tokens)

    def matches_surface_direction(
        source: list[str],
        target: list[str],
        actual_source: list[str],
        actual_target: list[str],
        *,
        label: str,
        source_form_tokens: list[str] | None = None,
        target_form_tokens: list[str] | None = None,
        require_form_occurrence: bool = False,
    ) -> None:
        """Require metadata to describe the changed tokens, not just tokens nearby.

        Legacy labels sometimes append context after the changed word (for
        example ``for -> of after responsible``), so the declared side may
        contain the actual changed side.  A stale direction such as
        ``records -> samples`` still fails because ``record`` is not contained
        in the declared target.  Reorders are checked as two complete local
        phrases because their SequenceMatcher replacement opcodes only expose
        the moved boundary tokens.
        """

        source_form_tokens = clean_tokens if source_form_tokens is None else source_form_tokens
        target_form_tokens = error_tokens if target_form_tokens is None else target_form_tokens

        if reordered:
            if Counter(source) != Counter(target):
                issues.append(f"{label} direction does not describe the reordered token set")
                return
            if not _contains_phrase(source_form_tokens, source):
                issues.append(f"{label} source does not occur as a clean-form phrase")
            if not _contains_phrase(target_form_tokens, target):
                issues.append(f"{label} target does not occur as an error-form phrase")
            return

        if actual_source and not _contains_phrase(source, actual_source):
            issues.append(f"{label} source does not match the clean_form token diff")
        if actual_target and not _contains_phrase(target, actual_target):
            issues.append(f"{label} target does not match the error_form token diff")
        if require_form_occurrence:
            if source and not _contains_phrase(source_form_tokens, source):
                issues.append(f"{label} source does not occur in its source form")
            if target and not _contains_phrase(target_form_tokens, target):
                issues.append(f"{label} target does not occur in its target form")

    if not clean or not error:
        issues.append("clean_form and error_form must be nonempty")
    if clean_tokens == error_tokens:
        issues.append("clean_form and error_form must differ")
    if not mutation_type.strip():
        issues.append("mutation_type must be nonempty")
    if not minimal_correction.strip():
        issues.append("minimal_correction must be nonempty")
    if not answer_explanation.strip():
        issues.append("answer_explanation must be nonempty")

    mutation_direction = _direction_tokens(mutation_type)
    if mutation_type.strip() and mutation_direction is None:
        issues.append("mutation_type must contain a parseable source -> target direction")
    elif mutation_direction is not None:
        source, target = mutation_direction
        if not source or not target:
            issues.append("mutation_type source and target must be nonempty")
        matches_surface_direction(
            source,
            target,
            changed_clean,
            changed_error,
            label="mutation_type",
        )

    correction_direction = _extract_correction_direction(
        minimal_correction,
        expected_source=changed_error if not reordered else None,
        expected_target=changed_clean if not reordered else None,
    )
    if minimal_correction.strip() and correction_direction is None:
        issues.append("minimal_correction must contain a parseable source -> target direction")
    elif correction_direction is not None:
        source, target = correction_direction
        matches_surface_direction(
            source,
            target,
            changed_error,
            changed_clean,
            label="minimal_correction",
            source_form_tokens=error_tokens,
            target_form_tokens=clean_tokens,
            require_form_occurrence=True,
        )

    explanation_tokens = _norm_tokens(answer_explanation)
    evidence_tokens = set(changed_clean + changed_error)
    if evidence_tokens:
        clean_phrase_mentioned = _contains_phrase(explanation_tokens, changed_clean)
        error_phrase_mentioned = _contains_phrase(explanation_tokens, changed_error)
        explanation_token_set = set(explanation_tokens)
        clean_mentioned = clean_phrase_mentioned or bool(explanation_token_set.intersection(changed_clean))
        error_mentioned = error_phrase_mentioned or bool(explanation_token_set.intersection(changed_error))
        if not clean_mentioned and not error_mentioned:
            issues.append("answer_explanation does not mention the mutation evidence")
        else:
            positive_cues = {
                "appropriate", "correct", "correctly", "demand", "demands", "followed",
                "need", "needs", "must", "proper", "require", "required", "requires",
                "selects", "should", "takes", "use", "uses",
            }
            negative_cues = {
                "breaks", "cannot", "can't", "incorrect", "inappropriate", "invalid",
                "not", "rather", "instead", "ungrammatical", "wrong",
            }

            def near_cue(evidence: list[str], cues: set[str]) -> bool:
                if not evidence:
                    return False
                for index, token in enumerate(explanation_tokens):
                    if token not in evidence:
                        continue
                    context = explanation_tokens[max(0, index - 5) : index + 6]
                    if any(token in cues for token in context):
                        return True
                return False

            clean_positive = near_cue(changed_clean, positive_cues)
            error_negative = near_cue(changed_error, negative_cues)
            if not clean_positive and not error_negative:
                issues.append("answer_explanation does not describe the clean -> error direction")

            # In the common ``correct, not incorrect`` construction the
            # required clean form must precede the erroneous form.  Merely
            # mentioning both changed tokens is insufficient because it also
            # accepts explanations that reverse the grammatical direction.
            if clean_phrase_mentioned and error_phrase_mentioned:
                clean_index = next(
                    index
                    for index in range(len(explanation_tokens) - len(changed_clean) + 1)
                    if explanation_tokens[index : index + len(changed_clean)] == changed_clean
                )
                error_index = next(
                    index
                    for index in range(len(explanation_tokens) - len(changed_error) + 1)
                    if explanation_tokens[index : index + len(changed_error)] == changed_error
                )
                between = explanation_tokens[
                    min(clean_index, error_index) : max(
                        clean_index + len(changed_clean), error_index + len(changed_error)
                    )
                ]
                directional_connector = {"not", "rather", "instead", "than"}
                if any(token in directional_connector for token in between) and clean_index > error_index:
                    issues.append("answer_explanation reverses the clean -> error direction")

    return not issues, issues


def _find_target_phrase(error: str, mutation_type: str) -> tuple[str, str] | None:
    direction = _direction(mutation_type)
    if direction is None:
        return None
    return direction


def _noun_number(token: str) -> str:
    token = token.casefold()
    if token in SINGULAR_NOUN_EXCEPTIONS:
        return "singular"
    if token.endswith(("men", "women", "children", "people")):
        return "plural"
    if token.endswith("s") and not token.endswith("ss"):
        return "plural"
    return "singular"


def _looks_like_attributive_adjective(token: str) -> bool:
    """Recognize common adjective modifiers conservatively.

    This is intentionally not a general part-of-speech tagger.  It only
    avoids selecting an obvious modifier such as ``large`` as the head of
    ``these large instruments``; uncertain words remain noun candidates and
    are handled by the fail-closed mismatch checks.
    """

    token = token.casefold()
    return token in COMMON_ATTRIBUTIVE_ADJECTIVES or token.endswith(ADJECTIVE_SUFFIXES)


def _nearest_antecedent_number(tokens: list[str], before_index: int) -> str | None:
    for index in range(before_index - 1, -1, -1):
        token = tokens[index]
        if token in REFERENCE_FEATURES or token in REFERENCE_FUNCTION_WORDS:
            continue
        if token.endswith(("ly", "ing", "ed")):
            continue
        if token in FINITE_VERB_FORMS:
            # A form such as ``said`` is not noun-phrase evidence.  Being
            # conservative here is intentional: missing a weak antecedent
            # candidate sends the item to external review rather than
            # accepting a grammatical mutation as an objective defect.
            continue
        return _noun_number(token)
    return None


def _following_noun_number(tokens: list[str], after_index: int) -> str | None:
    for token in tokens[after_index + 1 :]:
        if token in REFERENCE_FUNCTION_WORDS:
            continue
        if token.endswith(("ly", "ing", "ed")):
            continue
        if _looks_like_attributive_adjective(token):
            continue
        return _noun_number(token)
    return None


def _has_objective_reference_defect(clean: str, error: str, mutation_type: str) -> bool:
    """Find a concrete number/person/determiner mismatch in the two forms.

    The mutation label is only a routing hint.  In particular, words such as
    ``formally invalid antecedent`` are not evidence by themselves.  This
    deliberately recognizes only objective local mismatches and otherwise
    leaves the item for external grammar review.
    """

    error_tokens = _norm_tokens(error)
    changed_clean, changed_error, _ = _diff_tokens(clean, error)
    if not changed_error:
        return False

    mutation_lower = mutation_type.casefold()
    target_is_person = "person" in mutation_lower
    # ``mismatch`` is too broad: a person-mismatch label must not silently
    # route through the number check just because its target pronoun changes
    # singular/plural (for example, grammatical ``I -> we``).
    target_is_number = "number" in mutation_lower

    for index, token in enumerate(error_tokens):
        if token not in changed_error:
            continue
        features = REFERENCE_FEATURES.get(token)
        if features is not None:
            antecedent_number = _nearest_antecedent_number(error_tokens, index)
            if antecedent_number is None:
                continue
            target_number, target_person = features
            if target_number != "ambiguous" and target_number != antecedent_number:
                if target_is_number or not target_is_person:
                    return True
            if target_is_person and token in PERSONAL_PRONOUNS:
                source_person = next(
                    (REFERENCE_FEATURES[source][1] for source in changed_clean if source in REFERENCE_FEATURES),
                    None,
                )
                # First- and second-person pronouns are not defects merely
                # because they are first- or second-person.  Require a
                # changed pronoun pair with different person features; this
                # keeps grammatical ``I -> we`` reported-speech edits out of
                # the objective reference guard.
                if source_person is not None and source_person != target_person:
                    return True

        determiner_number = REFERENCE_DETERMINERS.get(token)
        if determiner_number is None:
            continue
        noun_number = _following_noun_number(error_tokens, index)
        if noun_number is None:
            continue
        if determiner_number in {"singular", "plural"} and determiner_number != noun_number:
            return True

    # Demonstratives are tested against their following noun, even when the
    # label says only ``formally invalid antecedent``.
    for index, token in enumerate(error_tokens):
        if token not in changed_error or token not in {"this", "that", "these", "those"}:
            continue
        noun_number = _following_noun_number(error_tokens, index)
        if noun_number is not None:
            demonstrative_number = REFERENCE_FEATURES[token][0]
            if demonstrative_number != noun_number:
                return True

    return False


def _reference_guard(
    clean: str,
    error: str,
    mutation_type: str,
    external_evidence: Mapping[str, bool] | None = None,
) -> list[str]:
    lowered = mutation_type.casefold()
    evidence_keys = {
        "reference_objective_defect",
        "reference_number_mismatch",
        "reference_person_mismatch",
        "reference_formal_antecedent_defect",
    }
    has_strong_external_evidence = external_evidence is not None and all(
        external_evidence.get(name) is True for name in STRONG_INVARIANT_NAMES
    )
    has_formal_reference_evidence = _has_objective_reference_defect(clean, error, mutation_type) or (
        external_evidence is not None and (
        any(external_evidence.get(key) is True for key in evidence_keys)
        or has_strong_external_evidence
        )
    )
    if "ambiguous-pronoun" in lowered or "pronoun substitution" in lowered:
        if not has_formal_reference_evidence:
            return ["ambiguous-pronoun substitution is quarantined without formal reference evidence"]
        return []
    objective_markers = ("number", "person", "demonstrative", "determiner", "antecedent", "mismatch")
    if not any(marker in lowered for marker in objective_markers):
        return ["incorrect_reference requires an objective number/person/formal antecedent defect"]
    if external_evidence is not None and (
        any(external_evidence.get(key) is True for key in evidence_keys)
        or has_strong_external_evidence
    ):
        return []
    if not _has_objective_reference_defect(clean, error, mutation_type):
        return [
            "incorrect_reference label is not evidence of an objective number/person/formal antecedent defect"
        ]
    return []


DEGREE_MARKER_WORDS = {"more", "most"}
IRREGULAR_DEGREE_BASES = {
    "better": "good",
    "best": "good",
    "worse": "bad",
    "worst": "bad",
    "less": "little",
    "least": "little",
    "farther": "far",
    "farthest": "far",
    "further": "far",
    "furthest": "far",
}


def _degree_base_forms(token: str) -> set[str]:
    """Return plausible base forms for an inflected degree adjective."""

    token = token.casefold()
    bases = {token}
    irregular = IRREGULAR_DEGREE_BASES.get(token)
    if irregular is not None:
        bases.add(irregular)
    if token.endswith("iest") and len(token) > 4:
        bases.add(token[:-4] + "y")
    if token.endswith("ier") and len(token) > 3:
        bases.add(token[:-3] + "y")
    if token.endswith("est") and len(token) > 3:
        stem = token[:-3]
        bases.update({stem, stem + "e"})
    if token.endswith("er") and len(token) > 2:
        stem = token[:-2]
        bases.update({stem, stem + "e"})
    return bases


def _has_degree_morphological_change(clean: str, error: str) -> bool:
    """Require an actual comparative/superlative inflectional change."""

    changed_clean, changed_error, _ = _diff_tokens(clean, error)
    clean_words = [token for token in changed_clean if token not in DEGREE_MARKER_WORDS]
    error_words = [token for token in changed_error if token not in DEGREE_MARKER_WORDS]
    if len(clean_words) != 1 or len(error_words) != 1:
        return False

    left, right = clean_words[0], error_words[0]
    if left == right:
        return False
    left_has_degree_suffix = left.endswith(("er", "est"))
    right_has_degree_suffix = right.endswith(("er", "est"))
    if not (left_has_degree_suffix or right_has_degree_suffix or left in IRREGULAR_DEGREE_BASES or right in IRREGULAR_DEGREE_BASES):
        return False
    return left in _degree_base_forms(right) or right in _degree_base_forms(left)


def _degree_guard(clean: str, error: str, mutation_type: str) -> list[str]:
    clean_lower = clean.casefold()
    error_lower = error.casefold()
    mutation_lower = mutation_type.casefold()
    if (
        ("sufficiently" in clean_lower and "too" in error_lower)
        or ("enough" in clean_lower and "too" in error_lower)
        or ("too" in clean_lower and "sufficiently" in error_lower)
        or ("too" in clean_lower and "enough" in error_lower)
    ):
        return ["degree mutation changes meaning between grammatical constructions"]

    # Invalid inflection is a morphosyntactic mutation in its own right, but
    # the label is not evidence that an inflection actually changed.
    if "morpholog" in mutation_lower:
        if not _has_degree_morphological_change(clean, error):
            return ["degree morphology label is not supported by a comparative/superlative inflection change"]
        return []

    comparative_markers = ("comparative", "superlative", "more", "most")
    if any(marker in mutation_lower for marker in comparative_markers):
        clean_tokens = _norm_tokens(clean)
        error_tokens = _norm_tokens(error)
        if "than" not in error_tokens and "than" not in clean_tokens:
            return ["comparative/superlative mutation lacks an explicit comparative trigger"]
        if "most" not in error_tokens or "than" not in error_tokens:
            return ["comparative/superlative mutation is not the guarded most-X-than mismatch"]
        return []

    return ["degree mutation has no demonstrated morphosyntactic trigger"]


def _parallel_agreement_scope_guard(clean: str, error: str, mutation_type: str) -> list[str]:
    direction = _find_target_phrase(error, mutation_type)
    if direction is None:
        return ["parallel agreement mutation needs an explicit clean -> error direction"]
    _, target = direction
    occurrences = lexical_token_spans(error, target, casefold=True)
    if len(occurrences) != 1:
        return ["parallel agreement target cannot be located uniquely in error_form"]

    start, end = occurrences[0]
    tokens = _norm_tokens(error)
    coordinator_indices = [
        index for index, token in enumerate(tokens)
        if token in {"and", "or", "nor"}
    ]
    nearby = [index for index in coordinator_indices if abs(index - start) <= 8]
    if not nearby:
        return ["parallel agreement mutation has no explicit coordination scope"]

    for coordinator_index in nearby:
        left = tokens[max(0, start - 8) : coordinator_index]
        right = tokens[coordinator_index + 1 : min(len(tokens), end + 8)]
        if left and right:
            return []
    return ["parallel agreement mutation does not have two coordinated constituents in scope"]


def _is_infinitival_to(tokens: list[str], index: int) -> bool:
    """Return whether ``to`` has a plausible infinitival complement.

    The local parallel guard only needs to distinguish the common
    prepositional ``to`` + ``-ing`` shape from an infinitival trigger.  A
    preposition followed by a noun phrase is likewise not treated as an
    infinitive; uncertain bare forms remain eligible so the guard stays
    conservative.
    """

    if index + 1 >= len(tokens):
        return False
    following = tokens[index + 1]
    if following in REFERENCE_FUNCTION_WORDS:
        return False
    return not following.endswith(("ing", "ed"))


def _parallel_guard(clean: str, error: str, mutation_type: str) -> list[str]:
    direction = _find_target_phrase(error, mutation_type)
    if direction is None:
        return ["parallel mutation needs an explicit clean -> error direction"]
    _, target = direction
    target_tokens = _norm_tokens(target)
    if "agreement" in mutation_type.casefold():
        return _parallel_agreement_scope_guard(clean, error, mutation_type)
    ing_offsets = [index for index, token in enumerate(target_tokens) if token.endswith("ing")]
    if not ing_offsets:
        return []
    occurrences = lexical_token_spans(error, target, casefold=True)
    if len(occurrences) != 1:
        return ["parallel mutation target cannot be located in error_form"]
    target_start, _ = occurrences[0]
    error_matches = lexical_token_matches(error)
    mutated_verb_match = error_matches[target_start + ing_offsets[0]]
    prefix = error.casefold()[: mutated_verb_match.start()]

    # A comma before -ing is the exact blind-009 failure shape: the phrase can
    # be a supplementary/adverbial participial clause.
    if re.search(r",\s*(?:and\s+|or\s+)?$", prefix):
        return ["-ing phrase can survive as a supplementary/adverbial participial clause"]

    # The coordinator must be the token immediately before the mutated verb.
    # Looking for any earlier auxiliary is insufficient: in
    # ``will review the proposal and filing the report`` the coordinator can
    # instead join two objects, leaving ``filing`` as a grammatical gerund.
    prefix_tokens = _norm_tokens(prefix)
    if not prefix_tokens or prefix_tokens[-1] not in {"and", "or", "nor"}:
        return ["parallel -ing mutation is not immediately coordinated"]
    coordinator_index = len(prefix_tokens) - 1
    trigger_indices = [
        index
        for index, token in enumerate(prefix_tokens[:coordinator_index])
        if (
            token in MODAL_TRIGGERS
            or token in {"let", "help"}
            or (token == "to" and _is_infinitival_to(prefix_tokens, index))
        )
    ]
    paired_indices = [
        index
        for index, token in enumerate(prefix_tokens[:coordinator_index])
        if token in {"both", "either", "neither"}
    ]
    if not trigger_indices and not paired_indices:
        return ["parallel -ing mutation is not structurally forced by coordination"]

    if trigger_indices:
        trigger_index = trigger_indices[-1]
        trigger = prefix_tokens[trigger_index]
        if trigger in MODAL_TRIGGERS:
            between = prefix_tokens[trigger_index + 1 : coordinator_index]
            # A modal plus an overt object before the coordinator is the
            # characteristic alternate object-NP parse.  Reject it instead
            # of treating the modal's mere presence as proof of verb scope.
            if len(between) > 1 or any(token in REFERENCE_FUNCTION_WORDS for token in between):
                return [
                    "parallel coordinator scope is ambiguous: it may join an object phrase rather than verb heads"
                ]
    else:
        paired_index = paired_indices[-1]
        first_conjunct = prefix_tokens[paired_index + 1 : coordinator_index]
        if not first_conjunct or first_conjunct[0] in REFERENCE_FUNCTION_WORDS:
            return ["parallel paired coordinator does not introduce a verb head"]
    return []


def classify_template(mutation_type: str, tested_error_type: str = "", primary_target: str = "") -> TemplateRecord:
    """Classify a mutation family without inspecting sentence meaning."""

    lowered = mutation_type.casefold()
    if tested_error_type == "incorrect_reference":
        if "ambiguous-pronoun" in lowered or "pronoun substitution" in lowered:
            return TEMPLATE_CATALOG[0]
        if "number" in lowered:
            return TEMPLATE_CATALOG[1]
        if "person" in lowered:
            return TEMPLATE_CATALOG[2]
        if "demonstrative" in lowered or "determiner" in lowered:
            return TEMPLATE_CATALOG[3]
        if "antecedent" in lowered:
            return TEMPLATE_CATALOG[4]
        # Any unrecognised reference label remains quarantined.  In
        # particular, labels such as ``reference replacement: the artifact ->
        # it`` must not fall through to the generic SAFE record.
        return TEMPLATE_CATALOG[0]
    if tested_error_type == "wrong_degree_form" or "degree" in primary_target.casefold():
        if any(term in lowered for term in ("sufficiently", "enough", "degree-marker", "semantic")):
            return TEMPLATE_CATALOG[7]
        if "morpholog" in lowered:
            return TEMPLATE_CATALOG[6]
        if "comparative" in lowered or "superlative" in lowered or "more" in lowered or "most" in lowered:
            return TEMPLATE_CATALOG[5]
        return TEMPLATE_CATALOG[10]
    if primary_target == "PARALLEL_STRUCTURE" or "parallel" in lowered:
        if "agreement" in tested_error_type or "agreement" in lowered:
            return TEMPLATE_CATALOG[9]
        return TEMPLATE_CATALOG[8]
    return TemplateRecord(
        "unclassified.safe_surface_mutation",
        tested_error_type or "unknown",
        primary_target or "unknown",
        TemplateClass.SAFE,
        "metadata_and_external_grammar_review_required",
        "No special guard was selected; the strong grammar invariant remains external.",
    )


def _marked_span_contains_changed_error(
    item: Mapping[str, Any],
    error_form: str,
    changed_error_indices: list[int],
    changed_error_boundaries: list[int] | None = None,
) -> bool | None:
    answer = item.get("correct_answer")
    marked = item.get("marked_parts")
    sentence = item.get("sentence")
    if (
        answer not in LABELS
        or not isinstance(marked, Mapping)
        or not isinstance(sentence, str)
        or sentence != error_form
    ):
        return False
    occurrences = lexical_token_spans(sentence, str(marked.get(answer, "")), casefold=True)
    if len(occurrences) != 1 or not changed_error_indices:
        return False
    start, end = occurrences[0]
    # Compare positions, not token membership.  A changed word can occur in a
    # different marked span and must not satisfy the declared-defect invariant.
    boundaries = set(changed_error_boundaries or ())
    return all(
        start <= index <= end if index in boundaries else start <= index < end
        for index in changed_error_indices
    )


def audit_mutation(
    *,
    clean_form: str,
    error_form: str,
    mutation_type: str,
    minimal_correction: str,
    answer_explanation: str,
    tested_error_type: str = "",
    primary_target: str = "",
    item: Mapping[str, Any] | None = None,
    external_evidence: Mapping[str, bool] | None = None,
) -> MutationSafetyResult:
    """Audit one mutation and return a structured, fail-closed result."""

    template = classify_template(mutation_type, tested_error_type, primary_target)
    metadata_ok, metadata_issues = _metadata_audit(
        clean_form,
        error_form,
        mutation_type,
        minimal_correction,
        answer_explanation,
    )
    surface_ok, surface_details = _surface_edit_is_local(clean_form, error_form)
    reasons = list(metadata_issues)
    if not surface_ok:
        reasons.append("clean_form -> error_form is not exactly one local surface mutation")

    effective_template_class = template.classification
    formal_pronoun_reference = (
        template.template_id == "reference.ambiguous_pronoun_substitution"
        and (
            _has_objective_reference_defect(clean_form, error_form, mutation_type)
            or (
                external_evidence is not None
                and (
                    any(
                        external_evidence.get(key) is True
                        for key in {
                            "reference_objective_defect",
                            "reference_number_mismatch",
                            "reference_person_mismatch",
                            "reference_formal_antecedent_defect",
                        }
                    )
                    or all(external_evidence.get(name) is True for name in STRONG_INVARIANT_NAMES)
                )
            )
        )
    )
    if formal_pronoun_reference:
        # Pronoun substitutions remain guarded, but a formally established
        # number/person/reference defect is not the ambiguous case that the
        # quarantine catalog is intended to reject.
        effective_template_class = TemplateClass.NEEDS_GUARD

    if effective_template_class == TemplateClass.QUARANTINE:
        reasons.append(f"template is quarantined: {template.template_id}")
        if template.template_id.startswith("reference."):
            reasons.extend(_reference_guard(clean_form, error_form, mutation_type, external_evidence))
        elif template.template_id.startswith("degree."):
            reasons.extend(_degree_guard(clean_form, error_form, mutation_type))
    elif template.template_id.startswith("reference."):
        reasons.extend(_reference_guard(clean_form, error_form, mutation_type, external_evidence))
    elif template.template_id.startswith("degree."):
        reasons.extend(_degree_guard(clean_form, error_form, mutation_type))
    elif template.template_id.startswith("parallel."):
        reasons.extend(_parallel_guard(clean_form, error_form, mutation_type))

    changed_clean = surface_details["changed_clean_tokens"]
    changed_error = surface_details["changed_error_tokens"]
    changed_error_indices = surface_details["changed_error_indices"]
    changed_error_boundaries = surface_details["changed_error_boundaries"]
    if item is not None and item.get("sentence") != error_form:
        reasons.append("qa_metadata.error_form must exactly match the emitted sentence")
    span_invariant = (
        _marked_span_contains_changed_error(item, error_form, changed_error_indices, changed_error_boundaries)
        if item is not None
        else None
    )
    if span_invariant is False:
        reasons.append("changed error tokens are outside the declared correct span")

    invariant_names = STRONG_INVARIANT_NAMES
    invariants: dict[str, bool | None] = {name: None for name in invariant_names}
    invariants["declared_marked_span_contains_defect"] = span_invariant
    grammar_evidence_status = "REQUIRES_EXTERNAL_REVIEW"
    if external_evidence is not None:
        grammar_evidence_status = "PASS" if all(external_evidence.get(name) is True for name in invariant_names) else "FAIL"
        for name in invariant_names:
            invariants[name] = external_evidence.get(name) is True
        if grammar_evidence_status == "FAIL":
            reasons.append("external grammar evidence does not satisfy every post-mutation invariant")

    return MutationSafetyResult(
        status="PASS" if not reasons else "REJECT",
        template_class=effective_template_class.value,
        template_id=template.template_id,
        reasons=reasons,
        metadata_consistent=metadata_ok,
        surface_integrity=surface_ok,
        grammar_evidence_status=grammar_evidence_status,
        invariants=invariants,
    )


def validate_item(item: Mapping[str, Any], external_evidence: Mapping[str, bool] | None = None) -> MutationSafetyResult:
    """Validate the v2 item shape without changing the v2 schema contract."""

    qa = item.get("qa_metadata") if isinstance(item, Mapping) else None
    if not isinstance(qa, Mapping):
        qa = {}
    clean = str(qa.get("clean_form", ""))
    error = str(qa.get("error_form", ""))
    qa_correction = qa.get("minimal_correction")
    top_level_correction = item.get("minimal_correction")
    correction = str(
        top_level_correction
        if top_level_correction is not None
        else (qa_correction if qa_correction is not None else "")
    )
    explanation = str(item.get("answer_explanation", item.get("error_explanation", "")))
    result = audit_mutation(
        clean_form=clean,
        error_form=error,
        mutation_type=str(qa.get("mutation_type", "")),
        minimal_correction=correction,
        answer_explanation=explanation,
        tested_error_type=str(item.get("tested_error_type", "")),
        primary_target=str(item.get("primary_target", "")),
        item=item,
        external_evidence=external_evidence,
    )
    if (
        isinstance(qa_correction, str)
        and isinstance(top_level_correction, str)
        and qa_correction.strip() != top_level_correction.strip()
    ):
        result.reasons.append(
            "qa_metadata.minimal_correction must exactly match top-level minimal_correction"
        )
        result.status = "REJECT"
        result.metadata_consistent = False
    return result


def template_audit_records() -> list[dict[str, Any]]:
    """Return the complete targeted template classification table."""

    return [
        {
            "template_id": record.template_id,
            "tested_error_type": record.tested_error_type,
            "primary_target": record.primary_target,
            "classification": record.classification.value,
            "guard": record.guard,
            "rationale": record.rationale,
        }
        for record in TEMPLATE_CATALOG
    ]


if __name__ == "__main__":  # pragma: no cover - small inspection CLI
    import json

    print(json.dumps({"templates": template_audit_records()}, indent=2, ensure_ascii=False))
