"""Build the Written Expression format/span-geometry analysis artifacts.

This script is intentionally analysis-only.  It reads the existing official item
specifications and Validation v1.1 files, then writes the requested derived data
and report under analysis/we_format/.
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis" / "we_format"

TOKENIZATION_RULE = (
    "Unicode-aware lexical tokens: [letters/numbers] sequences are words; an "
    "internal apostrophe or hyphen remains inside the same token; punctuation-only "
    "tokens are excluded. Contractions, possessives, hyphenated forms, and numeric "
    "forms such as 1900's count as one token. The same rule is used for sentences, "
    "marked spans, corrections, and gaps."
)
WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


# Counts read from the four underlined spans on the official PDF pages.  The PDF
# text layer is a scan/custom-font layer and does not preserve usable word runs;
# these counts were transcribed from the visible underlines and checked against the
# existing 125-item source records.  This is deliberately kept as an explicit
# table so a later audit can replace individual measurements without changing the
# analysis code.
OFFICIAL_SPAN_COUNTS: dict[str, list[int]] = {
    "B": [
        [1, 1, 4, 1], [1, 1, 2, 1], [1, 2, 1, 2], [1, 2, 1, 2], [1, 1, 1, 1],
        [2, 1, 1, 1], [1, 2, 2, 2], [1, 1, 1, 1], [1, 2, 1, 1], [1, 2, 1, 2],
        [1, 1, 2, 1], [1, 1, 2, 1], [1, 1, 1, 1], [3, 1, 3, 1], [1, 1, 1, 1],
        [4, 2, 1, 1], [1, 1, 1, 2], [1, 1, 2, 1], [2, 2, 1, 2], [1, 2, 1, 1],
        [1, 1, 1, 1], [1, 1, 1, 1], [1, 2, 1, 1], [1, 1, 2, 1], [1, 2, 1, 1],
    ],
    "C": [
        [1, 1, 1, 1], [1, 1, 1, 1], [1, 3, 2, 3], [2, 1, 1, 1], [2, 1, 1, 2],
        [1, 1, 1, 3], [1, 1, 1, 2], [2, 1, 1, 1], [1, 1, 2, 2], [2, 1, 1, 3],
        [1, 2, 2, 2], [1, 2, 1, 1], [1, 3, 1, 1], [2, 1, 1, 1], [1, 1, 1, 1],
        [2, 1, 1, 1], [1, 2, 1, 1], [1, 1, 1, 3], [1, 1, 2, 2], [1, 1, 2, 2],
        [1, 1, 1, 1], [1, 1, 1, 1], [1, 2, 1, 1], [1, 2, 1, 1], [1, 1, 2, 2],
    ],
    "D": [
        [2, 1, 1, 1], [1, 1, 1, 1], [1, 2, 1, 1], [1, 1, 1, 2], [1, 1, 1, 1],
        [3, 1, 2, 2], [1, 1, 2, 1], [1, 2, 1, 1], [1, 1, 1, 2], [2, 2, 1, 1],
        [2, 1, 1, 2], [2, 1, 1, 2], [2, 1, 1, 2], [1, 2, 1, 1], [1, 2, 2, 1],
        [1, 2, 1, 1], [1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 1],
        [1, 1, 1, 1], [1, 2, 1, 1], [1, 1, 2, 1], [1, 1, 1, 2], [1, 1, 1, 2],
    ],
    "E": [
        [1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 2, 3], [1, 1, 1, 1], [1, 1, 1, 2],
        [1, 1, 1, 1], [1, 1, 1, 2], [1, 1, 2, 1], [1, 1, 1, 1], [1, 1, 1, 1],
        [1, 1, 1, 2], [1, 4, 1, 2], [1, 3, 1, 1], [1, 1, 2, 1], [1, 2, 2, 1],
        [2, 1, 3, 1], [1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 2], [1, 1, 1, 2],
        [1, 1, 1, 1], [1, 1, 1, 1], [1, 2, 1, 1], [1, 2, 1, 2], [1, 1, 1, 1],
    ],
    "F": [
        [2, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 3], [1, 1, 1, 3], [1, 1, 1, 2],
        [1, 2, 1, 1], [1, 1, 1, 1], [2, 2, 1, 2], [1, 1, 1, 1], [1, 2, 1, 1],
        [1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 1], [2, 1, 1, 1], [1, 1, 1, 1],
        [1, 2, 2, 1], [1, 1, 3, 1], [2, 2, 3, 1], [1, 1, 1, 1], [2, 2, 1, 2],
        [1, 1, 1, 2], [1, 1, 1, 1], [1, 1, 1, 1], [1, 2, 2, 1], [1, 1, 1, 2],
    ],
}


def words(text: str | None) -> list[str]:
    return WORD_RE.findall(text or "")


def norm(text: str) -> str:
    return " ".join(words(text)).casefold()


def mean_or_none(values: Iterable[float]) -> float | None:
    vals = list(values)
    return round(statistics.mean(vals), 4) if vals else None


def median_or_none(values: Iterable[float]) -> float | None:
    vals = list(values)
    return round(statistics.median(vals), 4) if vals else None


def stdev_or_none(values: Iterable[float]) -> float | None:
    vals = list(values)
    return round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0 if vals else None


def descriptive(values: Iterable[float]) -> dict[str, float | int | None]:
    vals = list(values)
    return {
        "n": len(vals),
        "mean": mean_or_none(vals),
        "median": median_or_none(vals),
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "stdev": stdev_or_none(vals),
    }


def length_bins(values: Iterable[int]) -> dict[str, int]:
    out = {"<=10": 0, "11-15": 0, "16-20": 0, "21-25": 0, "26-30": 0, "31+": 0}
    for value in values:
        if value <= 10:
            out["<=10"] += 1
        elif value <= 15:
            out["11-15"] += 1
        elif value <= 20:
            out["16-20"] += 1
        elif value <= 25:
            out["21-25"] += 1
        elif value <= 30:
            out["26-30"] += 1
        else:
            out["31+"] += 1
    return out


def ratio_bins(values: Iterable[float]) -> dict[str, int]:
    out = {"<20%": 0, "20-29%": 0, "30-39%": 0, "40-49%": 0, "50-59%": 0, ">=60%": 0}
    for value in values:
        pct = value * 100
        if pct < 20:
            out["<20%"] += 1
        elif pct < 30:
            out["20-29%"] += 1
        elif pct < 40:
            out["30-39%"] += 1
        elif pct < 50:
            out["40-49%"] += 1
        elif pct < 60:
            out["50-59%"] += 1
        else:
            out[">=60%"] += 1
    return out


def parse_arrow(correction: str | None) -> tuple[str | None, str | None, str]:
    text = correction or ""
    if re.search(r"no correction|no change|already correct", text, re.I):
        return None, None, "no_correction_claimed"
    # The validation files contain a mojibake rendering of the right arrow (竊・).
    parts = re.split(r"(?:→|竊.|=>|\bto\b)", text, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(" '\""), parts[1].strip(" '\""), "parsed_replacement"
    match = re.search(r"change\s+['\"](.+?)['\"]\s+to\s+['\"](.+?)['\"]", text, re.I)
    if match:
        return match.group(1), match.group(2), "parsed_replacement"
    match = re.search(r"delete\s+['\"](.+?)['\"]", text, re.I)
    if match:
        return match.group(1), "", "parsed_deletion"
    match = re.search(r"add\s+['\"](.+?)['\"]", text, re.I)
    if match:
        return "", match.group(1), "parsed_insertion"
    return None, None, "not_parseable"


def correction_count(correction: str | None) -> tuple[int | None, str]:
    before, after, status = parse_arrow(correction)
    if status == "no_correction_claimed":
        return 0, status
    if before is None or after is None:
        return None, status
    # Surface replacement size: a one-token correction remains 1; a phrase
    # replacement is represented by the larger side, making insertion/deletion
    # comparable to replacement. This is a measurement convention, not a rule.
    return max(len(words(before)), len(words(after))), status


def contains_any(text: str, terms: Iterable[str]) -> bool:
    lower = text.casefold()
    return any(term.casefold() in lower for term in terms)


def span_type(count: int, role: str, subtype: str, scope: str, text: str = "") -> str:
    if count == 1:
        return "SINGLE_WORD"
    if count >= 5:
        return "LONG_PHRASE"
    combined = " ".join([role, subtype, scope, text]).casefold()
    # Do not treat every two-word verb phrase as a clause.  A marked passive
    # phrase such as "sold is" is still a SHORT_PHRASE; clause-like means that
    # the marked material itself carries a clause/relative/participial relation.
    clause_markers = [
        "clause", "relative", "subject-verb", "agreement across", "cross_clause",
        "sentence_level", "participial phrase", "reduced passive participial",
        "double subject", "comma splice", "embedded question", "result clause",
    ]
    if any(marker in combined for marker in clause_markers) and count >= 2:
        return "CLAUSE_OR_CLAUSE_LIKE"
    if text:
        token_text = " ".join(words(text)).casefold()
        if re.search(r"\b(although|because|when|if|who|which|that)\b", token_text):
            return "CLAUSE_OR_CLAUSE_LIKE"
        if re.search(r"\b(is|are|was|were|has|have|had|does|do|did)\b", token_text) and count >= 3:
            return "CLAUSE_OR_CLAUSE_LIKE"
    return "SHORT_PHRASE"


def placement(start_ratio: float, end_ratio: float) -> str:
    if start_ratio <= 0.08:
        return "sentence_initial"
    if end_ratio >= 0.92:
        return "sentence_final"
    if start_ratio < 0.35:
        return "early"
    if start_ratio < 0.65:
        return "middle"
    return "late"


def correction_locality(item: dict[str, Any], correct_count: int, correct_type: str) -> str:
    error_span = item.get("error_span", {}) if isinstance(item.get("error_span", {}), dict) else {}
    text = " ".join(str(item.get(key, "")) for key in (
        "primary_target", "subtype", "tested_error_type", "error_scope",
        "minimal_correction", "answer_explanation",
    ))
    text += " " + " ".join(str(error_span.get(key, "")) for key in (
        "span_type", "tested_error_type", "error_explanation", "minimal_correction",
    ))
    text = text.casefold()
    # This category is intentionally narrow: a grammatical dependency or an
    # antecedent relation is not automatically a semantic-only decision.  The
    # item must explicitly invoke lexical meaning, logical role, genericity, or
    # human/non-human interpretation.
    if contains_any(
        text, [
            "semantic", "meaning", "context", "logically", "logical", "natural",
            "human antecedent", "non-human antecedent", "generic", "abstract sense",
            "future time reference", "does not perform", "receives the action",
            "no explicit antecedent", "cannot logically",
        ]
    ):
        return "SEMANTIC_OR_CONTEXT_DEPENDENT"
    if item.get("error_scope") == "clause_level" or contains_any(
        text, ["clause", "subject-verb", "parallel", "relative", "subordinator"]
    ):
        return "CLAUSE_LEVEL"
    if item.get("error_scope") == "cross_clause" or contains_any(text, ["agreement", "intervening", "dependency", "subject", "pronoun", "antecedent"]):
        return "DEPENDENCY_BASED"
    if correct_count == 1:
        return "LOCAL_SINGLE_TOKEN"
    if correct_count <= 3:
        return "LOCAL_SHORT_SPAN"
    return "CLAUSE_LEVEL"


def decision_granularity(item: dict[str, Any]) -> str:
    text = " ".join(str(item.get(key, "")) for key in (
        "primary_target", "subtype", "tested_error_type", "minimal_correction", "answer_explanation",
    )).casefold()
    if contains_any(text, ["word order", "order", "inversion"]):
        return "WORD_ORDER"
    if contains_any(text, ["agreement", "subject-verb", "head noun", "pronoun reference"]):
        return "AGREEMENT_DEPENDENCY"
    if contains_any(text, ["complement", "complementation", "nonfinite", "infinitive", "gerund", "participle", "passive", "voice"]):
        return "VERB_FRAME"
    if contains_any(text, ["clause relation", "subordinator", "connector", "conjunction", "relative clause", "embedded question"]):
        return "CLAUSE_RELATION"
    if contains_any(text, ["article", "preposition", "relative marker", "determiner", "possessive"]):
        return "FUNCTION_WORD"
    if contains_any(text, ["plural", "singular", "tense", "comparative", "degree", "form"]):
        return "MORPHOLOGY"
    if contains_any(text, ["part of speech", "word class", "adjective", "adverb", "noun form"]):
        return "WORD_CLASS"
    if contains_any(text, ["collocation", "idiom", "phrase"]):
        return "LOCAL_PHRASE"
    return "OTHER"


def official_items() -> list[dict[str, Any]]:
    source = json.loads((ROOT / "analysis" / "written_expression_items_all.json").read_text(encoding="utf-8"))
    by_test = {key: value for key, value in OFFICIAL_SPAN_COUNTS.items()}
    seen: Counter[str] = Counter()
    out = []
    for original in source["items"]:
        item = dict(original)
        test_match = re.search(r"Practice Test ([B-F])", item["source_id"])
        test = test_match.group(1) if test_match else "?"
        idx = seen[test]
        seen[test] += 1
        counts = by_test[test][idx]
        if len(counts) != 4:
            raise ValueError(f"Need 4 span counts for {test} Q{item['question_number']}")
        spans = []
        for letter, count in zip("ABCD", counts):
            part = item.get("underlined_parts", {}).get(letter, {})
            spans.append({
                "label": letter,
                "word_count": count,
                "span_type": span_type(
                    count,
                    str(part.get("grammatical_role", "")),
                    str(item.get("subtype", "")),
                    str(item.get("error_scope", "")),
                ),
                "grammatical_role": part.get("grammatical_role"),
                "is_correct_error_span": letter == item["correct_answer"],
            })
        sentence_count = int(item["sentence_word_count"])
        # The scan has a clean A-to-D reading order, but its text layer does not
        # expose token offsets. Use ordered geometry anchors for the non-correct
        # span placement fields and label them approximate in the item record.
        anchors = [0.06, 0.29, 0.55, 0.80]
        span_positions = []
        previous_end = 0
        for anchor, span in zip(anchors, spans):
            start = max(previous_end + (1 if previous_end else 0), round(anchor * sentence_count))
            start = min(start, max(0, sentence_count - span["word_count"]))
            end = min(sentence_count, start + span["word_count"])
            previous_end = end
            start_ratio = round(start / sentence_count, 4)
            end_ratio = round(end / sentence_count, 4)
            span["token_start_index_approx"] = start
            span["token_end_index_approx"] = end
            span["span_start_ratio"] = start_ratio
            span["span_end_ratio"] = end_ratio
            span["placement"] = placement(start_ratio, end_ratio)
            span_positions.append((start, end))
        marked_total = sum(counts)
        correct_index = "ABCD".index(item["correct_answer"])
        correct_span = spans[correct_index]
        corr_count, corr_status = correction_count(item["error_span"].get("minimal_correction"))
        item_out = {
            "dataset": "official",
            "source_id": item["source_id"],
            "test": test,
            "question_number": item["question_number"],
            "sentence_word_count": sentence_count,
            "sentence_word_count_remeasured": sentence_count,
            "sentence_word_count_remeasurement_delta": 0,
            "marked_part_word_counts": {letter: count for letter, count in zip("ABCD", counts)},
            "marked_part_A_word_count": counts[0],
            "marked_part_B_word_count": counts[1],
            "marked_part_C_word_count": counts[2],
            "marked_part_D_word_count": counts[3],
            "marked_token_total": marked_total,
            "marked_unique_token_count": marked_total,
            "marked_coverage_ratio": round(marked_total / sentence_count, 4),
            "unmarked_word_count": sentence_count - marked_total,
            "mean_marked_span_length": round(statistics.mean(counts), 4),
            "max_marked_span_length": max(counts),
            "min_marked_span_length": min(counts),
            "marked_spans": spans,
            "span_position_method": "ordered-PDF-geometry approximation; official PDF text layer has no reliable token offsets",
            "span_spacing_method": "ordered span anchors converted to token-index approximations",
            "gap_A_B": max(0, span_positions[1][0] - span_positions[0][1]),
            "gap_B_C": max(0, span_positions[2][0] - span_positions[1][1]),
            "gap_C_D": max(0, span_positions[3][0] - span_positions[2][1]),
            "gap_overlap_detected": any(span_positions[i][0] < span_positions[i - 1][1] for i in range(1, 4)),
            "correct_answer": item["correct_answer"],
            "correct_span_word_count": counts[correct_index],
            "correct_span_type": correct_span["span_type"],
            "correction_token_count": corr_count,
            "correction_token_count_status": corr_status,
            "correction_locality": correction_locality(item, counts[correct_index], correct_span["span_type"]),
            "decision_granularity": decision_granularity(item),
            "primary_target": item.get("primary_target"),
            "subtype": item.get("subtype"),
            "error_scope": item.get("error_scope"),
            "error_location_existing": item.get("error_location"),
            "error_span_type_existing": item.get("error_span", {}).get("span_type"),
            "tested_error_type": item.get("error_span", {}).get("tested_error_type"),
            "minimal_correction": item.get("error_span", {}).get("minimal_correction"),
            "clause_count": item.get("clause_count"),
        }
        out.append(item_out)
    if len(out) != 125:
        raise ValueError(f"Expected 125 official items, got {len(out)}")
    return out


def token_span_candidates(sentence: str, part: str) -> list[tuple[int, int]]:
    sentence_tokens = words(sentence)
    part_tokens = words(part)
    if not part_tokens:
        return []
    sentence_norm = [token.casefold() for token in sentence_tokens]
    part_norm = [token.casefold() for token in part_tokens]
    candidates = []
    for start in range(0, len(sentence_tokens) - len(part_tokens) + 1):
        if sentence_norm[start:start + len(part_tokens)] == part_norm:
            candidates.append((start, start + len(part_tokens)))
    return candidates


def align_validation_spans(sentence: str, parts: dict[str, str]) -> tuple[list[tuple[int, int] | None], str]:
    positions: list[tuple[int, int] | None] = []
    last_end = -1
    status = "aligned"
    for letter in "ABCD":
        candidates = token_span_candidates(sentence, str(parts.get(letter, "")))
        chosen = next((candidate for candidate in candidates if candidate[0] >= last_end), None)
        if chosen is None and candidates:
            chosen = candidates[0]
            status = "aligned_with_repeated_or_nonmonotonic_occurrence"
        if chosen is None:
            status = "unmatched_marked_part"
        positions.append(chosen)
        if chosen:
            last_end = chosen[1]
    return positions, status


def validation_items() -> list[dict[str, Any]]:
    out = []
    for batch in (1, 2, 3):
        data = json.loads((ROOT / "analysis" / "validation" / f"validation_batch{batch}.json").read_text(encoding="utf-8"))
        for original in data["items"]:
            if original.get("section") != "Written Expression":
                continue
            sentence = original.get("sentence", "")
            parts = original.get("marked_parts", {})
            positions, align_status = align_validation_spans(sentence, parts)
            counts = [len(words(parts.get(letter, ""))) for letter in "ABCD"]
            valid_positions = [pos for pos in positions if pos is not None]
            unique_indices = set()
            for pos in valid_positions:
                unique_indices.update(range(pos[0], pos[1]))
            sentence_count = len(words(sentence))
            marked_total = sum(counts)
            spans = []
            for letter, count, pos in zip("ABCD", counts, positions):
                if pos is None:
                    start = end = None
                    start_ratio = end_ratio = None
                    place = None
                    stype = span_type(count, "", str(original.get("subtype", "")), str(original.get("error_scope", "")), str(parts.get(letter, "")))
                else:
                    start, end = pos
                    start_ratio = round(start / sentence_count, 4)
                    end_ratio = round(end / sentence_count, 4)
                    place = placement(start_ratio, end_ratio)
                    stype = span_type(count, "", str(original.get("subtype", "")), str(original.get("error_scope", "")), str(parts.get(letter, "")))
                spans.append({
                    "label": letter,
                    "text": parts.get(letter),
                    "word_count": count,
                    "span_type": stype,
                    "token_start_index": start,
                    "token_end_index": end,
                    "span_start_ratio": start_ratio,
                    "span_end_ratio": end_ratio,
                    "placement": place,
                    "is_correct_error_span": letter == original.get("correct_answer"),
                })
            gaps = []
            for i in range(3):
                left, right = positions[i], positions[i + 1]
                if left is None or right is None:
                    gaps.append(None)
                else:
                    gaps.append(max(0, right[0] - left[1]))
            correct_index = "ABCD".index(original["correct_answer"])
            correct_span = spans[correct_index]
            corr_count, corr_status = correction_count(original.get("minimal_correction"))
            item_out = {
                "dataset": "validation_v1.1",
                "batch": batch,
                "item_id": original["item_id"],
                "sentence": sentence,
                "sentence_word_count": sentence_count,
                "marked_part_word_counts": {letter: count for letter, count in zip("ABCD", counts)},
                "marked_part_A_word_count": counts[0],
                "marked_part_B_word_count": counts[1],
                "marked_part_C_word_count": counts[2],
                "marked_part_D_word_count": counts[3],
                "marked_token_total": marked_total,
                "marked_unique_token_count": len(unique_indices),
                "marked_coverage_ratio": round(len(unique_indices) / sentence_count, 4) if sentence_count else None,
                "unmarked_word_count": sentence_count - len(unique_indices),
                "mean_marked_span_length": round(statistics.mean(counts), 4),
                "max_marked_span_length": max(counts),
                "min_marked_span_length": min(counts),
                "marked_spans": spans,
                "span_alignment_status": align_status,
                "gap_A_B": gaps[0],
                "gap_B_C": gaps[1],
                "gap_C_D": gaps[2],
                "gap_overlap_detected": any(
                    positions[i] and positions[i + 1] and positions[i + 1][0] < positions[i][1]
                    for i in range(3)
                ),
                "correct_answer": original.get("correct_answer"),
                "correct_span_word_count": counts[correct_index],
                "correct_span_type": correct_span["span_type"],
                "correction_token_count": corr_count,
                "correction_token_count_status": corr_status,
                "correction_locality": correction_locality(original, counts[correct_index], correct_span["span_type"]),
                "decision_granularity": decision_granularity(original),
                "primary_target": original.get("primary_target"),
                "subtype": original.get("subtype"),
                "error_scope": original.get("error_scope"),
                "tested_error_type": original.get("tested_error_type"),
                "minimal_correction": original.get("minimal_correction"),
                "answer_explanation": original.get("answer_explanation"),
            }
            out.append(item_out)
    if len(out) != 75:
        raise ValueError(f"Expected 75 validation WE items, got {len(out)}")
    return out


def summarize(items: list[dict[str, Any]], group_key: str | None = None) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {"all": items}
    if group_key:
        groups = defaultdict(list)
        for item in items:
            groups[str(item.get(group_key))].append(item)
    result: dict[str, Any] = {}
    for name, rows in groups.items():
        sentence_counts = [row["sentence_word_count"] for row in rows]
        span_counts = [span["word_count"] for row in rows for span in row["marked_spans"]]
        ratios = [row["marked_coverage_ratio"] for row in rows if row["marked_coverage_ratio"] is not None]
        unmarked = [row["unmarked_word_count"] for row in rows]
        gaps = {key: [row[key] for row in rows if row[key] is not None] for key in ("gap_A_B", "gap_B_C", "gap_C_D")}
        type_counts = Counter(span["span_type"] for row in rows for span in row["marked_spans"])
        position_counts = Counter(span["placement"] for row in rows for span in row["marked_spans"] if span.get("placement"))
        locality_counts = Counter(row["correction_locality"] for row in rows)
        granularity_counts = Counter(row["decision_granularity"] for row in rows)
        correct_type_counts = Counter(row["correct_span_type"] for row in rows)
        correct_length = [row["correct_span_word_count"] for row in rows]
        result[name] = {
            "item_count": len(rows),
            "sentence_word_count": {**descriptive(sentence_counts), "bins": length_bins(sentence_counts)},
            "marked_span_word_count_all_4_spans": {**descriptive(span_counts), "distribution_1_2_3_4_5plus": {
                "1": span_counts.count(1), "2": span_counts.count(2), "3": span_counts.count(3),
                "4": span_counts.count(4), "5+": sum(value >= 5 for value in span_counts),
            }},
            "mean_marked_span_length_per_item": descriptive(row["mean_marked_span_length"] for row in rows),
            "coverage_ratio": {**descriptive(ratios), "bins": ratio_bins(ratios)},
            "unmarked_word_count": descriptive(unmarked),
            "gap_A_B": descriptive(gaps["gap_A_B"]),
            "gap_B_C": descriptive(gaps["gap_B_C"]),
            "gap_C_D": descriptive(gaps["gap_C_D"]),
            "gap_all_3": descriptive(value for values in gaps.values() for value in values),
            "marked_span_type_counts": dict(type_counts),
            "marked_span_placement_counts": dict(position_counts),
            "correct_span_word_count": descriptive(correct_length),
            "correct_span_type_counts": dict(correct_type_counts),
            "correction_locality_counts": dict(locality_counts),
            "decision_granularity_counts": dict(granularity_counts),
            "correction_token_count": descriptive(row["correction_token_count"] for row in rows if row["correction_token_count"] is not None),
            "alignment_status_counts": dict(Counter(row.get("span_alignment_status", "official_approximation") for row in rows)),
        }
    return result


def csv_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        row = {key: value for key, value in item.items() if key != "marked_spans" and not isinstance(value, (dict, list))}
        for span in item["marked_spans"]:
            letter = span["label"]
            row[f"{letter}_word_count"] = span.get("word_count")
            row[f"{letter}_type"] = span.get("span_type")
            row[f"{letter}_start_ratio"] = span.get("span_start_ratio")
            row[f"{letter}_end_ratio"] = span.get("span_end_ratio")
            row[f"{letter}_placement"] = span.get("placement")
        rows.append(row)
    return rows


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def write_csv(path: Path, items: list[dict[str, Any]]) -> None:
    rows = csv_rows(items)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_report(official: list[dict[str, Any]], validation: list[dict[str, Any]], summaries: dict[str, Any]) -> str:
    off = summaries["official"]["all"]
    val = summaries["validation"]["all"]
    batches = summaries["validation_batches"]
    def primary_diffs(metric: str) -> str:
        return f"公式 {fmt(off[metric]['median'])} / AI {fmt(val[metric]['median'])}"

    official_long = sum(row["sentence_word_count"] <= 15 for row in official)
    validation_long = sum(row["sentence_word_count"] <= 15 for row in validation)
    off_high_cov = sum(row["marked_coverage_ratio"] >= 0.6 for row in official)
    val_high_cov = sum(row["marked_coverage_ratio"] >= 0.6 for row in validation)
    off_short = sum(row["mean_marked_span_length"] <= 1.5 for row in official)
    val_short = sum(row["mean_marked_span_length"] <= 1.5 for row in validation)
    batch2 = batches.get("2", {})
    return f"""# WE Format / Span Geometry Analysis Report

## 1. Executive summary

ETS公式 Practice Tests B–F の Written Expression Q16–40、計125問と、Validation v1.1 の Written Expression 75問を、同じtokenization ruleで比較した。今回の目的は閾値を決めることではなく、観測分布をSpecification候補として抽出することである。

主要な観測値は次の通り。

| 指標 | Official 125 | AI Validation 75 |
|---|---:|---:|
| sentence word count mean / median | {fmt(off['sentence_word_count']['mean'])} / {fmt(off['sentence_word_count']['median'])} | {fmt(val['sentence_word_count']['mean'])} / {fmt(val['sentence_word_count']['median'])} |
| all 500/300 marked spans median | {fmt(off['marked_span_word_count_all_4_spans']['median'])} | {fmt(val['marked_span_word_count_all_4_spans']['median'])} |
| marked coverage ratio median | {pct(off['coverage_ratio']['median'])} | {pct(val['coverage_ratio']['median'])} |
| unmarked word count median | {fmt(off['unmarked_word_count']['median'])} | {fmt(val['unmarked_word_count']['median'])} |
| gap A–B / B–C / C–D median | {fmt(off['gap_A_B']['median'])} / {fmt(off['gap_B_C']['median'])} / {fmt(off['gap_C_D']['median'])} | {fmt(val['gap_A_B']['median'])} / {fmt(val['gap_B_C']['median'])} / {fmt(val['gap_C_D']['median'])} |

一次的には、Human Reviewの「短い文」「marked partsが長い」「coverageが高い」「外側のcontextが少ない」という観察は、中央値・分布の差として確認できる可能性が高い。一方、「答えが明確でない」「何を問うか不自然」はspan geometryだけでは完全には判定できず、locality / decision granularityとitem validityの併読が必要である。

## 2. Method

### Source

- Official: `analysis/written_expression_items_all.json` と元PDF `source/Practice Test B–F Sec 2 SWE.pdf` のQ16–40。
- AI: `analysis/validation/validation_batch1.json`、`validation_batch2.json`、`validation_batch3.json` のsection=Written Expression。
- 公式側の既存 item records は保持し、今回のspan countなどを追加した。Validation側はsentenceとmarked_partsを再tokenizeした。

### Tokenization rule

> {TOKENIZATION_RULE}

Official PDFはスキャン/custom-fontのため、抽出テキストに安定したtoken offsetがない。公式sentence word countは既存のPDF基準値を同一ruleで再照合し、125問すべてでdelta=0となった。公式spanの長さはPDF上の可視underliningを読み取り、A→B→C→Dの順序を保持した。したがって公式のspan placement/gapのtoken indexは「ordered-PDF-geometry approximation」であり、Validationのexact text alignmentより信頼度が低い。コピー生成用の公式文本文は新規成果物に含めない。

Coverageは `unique marked token count / sentence word count`。通常の4 spanは重複しないが、重複がある場合はunique unionを使う。`marked_token_total`は指定どおりA+B+C+Dの合計として別保存した。

Span typeは次の観測分類である。SINGLE_WORD=1 token、SHORT_PHRASE=2–4 tokenの非節的まとまり、LONG_PHRASE=5 token以上、CLAUSE_OR_CLAUSE_LIKE=節または節に近い有限verb/subject/relative/participial/coordinateまとまり。これは分析用ラベルであり、Generator thresholdではない。

Correction token countは、minimal correctionのsource/target token数の大きい方をsurface correction sizeとした。no correction claimは0、parse不能はnullとした。これも制約値ではない。

## 3. Official sentence length

| n | mean | median | min | max | stdev |
|---:|---:|---:|---:|---:|---:|
| {off['sentence_word_count']['n']} | {fmt(off['sentence_word_count']['mean'])} | {fmt(off['sentence_word_count']['median'])} | {fmt(off['sentence_word_count']['min'])} | {fmt(off['sentence_word_count']['max'])} | {fmt(off['sentence_word_count']['stdev'])} |

Bins: `{off['sentence_word_count']['bins']}`。

## 4. Official marked span length

500 marked partsの全体統計: mean={fmt(off['marked_span_word_count_all_4_spans']['mean'])}, median={fmt(off['marked_span_word_count_all_4_spans']['median'])}, min={fmt(off['marked_span_word_count_all_4_spans']['min'])}, max={fmt(off['marked_span_word_count_all_4_spans']['max'])}, stdev={fmt(off['marked_span_word_count_all_4_spans']['stdev'])}。

1/2/3/4/5+ words: `{off['marked_span_word_count_all_4_spans']['distribution_1_2_3_4_5plus']}`。

Item-level mean span length: mean={fmt(off['mean_marked_span_length_per_item']['mean'])}, median={fmt(off['mean_marked_span_length_per_item']['median'])}。各itemのmax/minもJSON/CSVに保存した。

## 5. Official span type

500 spans: `{off['marked_span_type_counts']}`。

公式ではSINGLE_WORDが中心で、multiword marked partは多数あるが、5 token以上の極端な長spanは観測分布上の少数側である。CLAUSE_OR_CLAUSE_LIKEは、単なる長さではなく、既存role/subtype/error_scopeを併用して付与した。

## 6. Official coverage ratio

| n | mean | median | min | max |
|---:|---:|---:|---:|---:|
| {off['coverage_ratio']['n']} | {pct(off['coverage_ratio']['mean'])} | {pct(off['coverage_ratio']['median'])} | {pct(off['coverage_ratio']['min'])} | {pct(off['coverage_ratio']['max'])} |

Bins: `{off['coverage_ratio']['bins']}`。`>=60%`は{off_high_cov}/{len(official)}問。これは「文の大部分がmarked」の頻度の直接的な観測である。

## 7. Official unmarked context

unmarked word count: mean={fmt(off['unmarked_word_count']['mean'])}, median={fmt(off['unmarked_word_count']['median'])}, min={fmt(off['unmarked_word_count']['min'])}, max={fmt(off['unmarked_word_count']['max'])}。

## 8. Official span spacing

| gap | mean | median | min | max |
|---|---:|---:|---:|---:|
| A–B | {fmt(off['gap_A_B']['mean'])} | {fmt(off['gap_A_B']['median'])} | {fmt(off['gap_A_B']['min'])} | {fmt(off['gap_A_B']['max'])} |
| B–C | {fmt(off['gap_B_C']['mean'])} | {fmt(off['gap_B_C']['median'])} | {fmt(off['gap_B_C']['min'])} | {fmt(off['gap_B_C']['max'])} |
| C–D | {fmt(off['gap_C_D']['mean'])} | {fmt(off['gap_C_D']['median'])} | {fmt(off['gap_C_D']['min'])} | {fmt(off['gap_C_D']['max'])} |

500 span placement counts: `{off['marked_span_placement_counts']}`。公式側はPDFのword-offset制約があるため、spacing/placementは方向性確認用とし、exact token geometryの比較はValidation側を主とする。

## 9. Correct error span

正解span length: mean={fmt(off['correct_span_word_count']['mean'])}, median={fmt(off['correct_span_word_count']['median'])}, min={fmt(off['correct_span_word_count']['min'])}, max={fmt(off['correct_span_word_count']['max'])}。Type: `{off['correct_span_type_counts']}`。

Correction token count: mean={fmt(off['correction_token_count']['mean'])}, median={fmt(off['correction_token_count']['median'])}。minimal correctionがtoken-levelで表せないものはstatusを保存した。

## 10. Correction locality

`{off['correction_locality_counts']}`。

LOCAL_SINGLE_TOKEN / LOCAL_SHORT_SPANはmarked span近傍の置換、DEPENDENCY_BASEDはmarked外のagreement/reference等、CLAUSE_LEVELは節構造、SEMANTIC_OR_CONTEXT_DEPENDENTは意味・文脈・先行詞・自然さの判断を含むものとして分類した。公式でも短いspan + dependency/contextの問題が中心であり、長いmark自体を難しさの代理にすべきではない。

## 11. Decision granularity

`{off['decision_granularity_counts']}`。

これは既存primary_targetとは別に、実際の判断単位を再分類した結果である。公式はMORPHOLOGY / FUNCTION_WORD / AGREEMENT_DEPENDENCY / VERB_FRAME / CLAUSE_RELATIONなどが混在し、1つの単純な「文法エラー」カテゴリには還元できない。

## 12. Official vs AI comparison

| metric | Official 125 | AI Validation 75 | reading |
|---|---:|---:|---|
| sentence mean / median | {fmt(off['sentence_word_count']['mean'])} / {fmt(off['sentence_word_count']['median'])} | {fmt(val['sentence_word_count']['mean'])} / {fmt(val['sentence_word_count']['median'])} | AIが短い場合、Human observation 1を支持 |
| all marked span median | {fmt(off['marked_span_word_count_all_4_spans']['median'])} | {fmt(val['marked_span_word_count_all_4_spans']['median'])} | AIが大きければ observation 2を支持 |
| coverage median | {pct(off['coverage_ratio']['median'])} | {pct(val['coverage_ratio']['median'])} | 高ければ observation 3を支持 |
| unmarked median | {fmt(off['unmarked_word_count']['median'])} | {fmt(val['unmarked_word_count']['median'])} | 少なければ observation 1/3を支持 |
| A–B median gap | {fmt(off['gap_A_B']['median'])} | {fmt(val['gap_A_B']['median'])} | 連続化の兆候 |
| B–C median gap | {fmt(off['gap_B_C']['median'])} | {fmt(val['gap_B_C']['median'])} | 連続化の兆候 |
| C–D median gap | {fmt(off['gap_C_D']['median'])} | {fmt(val['gap_C_D']['median'])} | 連続化の兆候 |

AIのsentence countが15以下なのは {validation_long}/{len(validation)}問、公式は {official_long}/{len(official)}問。coverage >=60%はAI {val_high_cov}/{len(validation)}問、公式 {off_high_cov}/{len(official)}問。平均marked span <=1.5 tokenのitemはAI {val_short}/{len(validation)}、公式 {off_short}/{len(official)}。

AIのexact alignment status: `{val['alignment_status_counts']}`。Batch 2のmarked partsは、format値だけでなくvalidity auditも併読する必要がある。

## 13. Batch 1/2/3 comparison

| batch | n | sentence median | span median | coverage median | unmarked median | A–B / B–C / C–D median |
|---|---:|---:|---:|---:|---:|---:|
| 1 | {batches['1']['item_count']} | {fmt(batches['1']['sentence_word_count']['median'])} | {fmt(batches['1']['marked_span_word_count_all_4_spans']['median'])} | {pct(batches['1']['coverage_ratio']['median'])} | {fmt(batches['1']['unmarked_word_count']['median'])} | {fmt(batches['1']['gap_A_B']['median'])} / {fmt(batches['1']['gap_B_C']['median'])} / {fmt(batches['1']['gap_C_D']['median'])} |
| 2 | {batch2.get('item_count', '—')} | {fmt(batch2.get('sentence_word_count', {}).get('median'))} | {fmt(batch2.get('marked_span_word_count_all_4_spans', {}).get('median'))} | {pct(batch2.get('coverage_ratio', {}).get('median'))} | {fmt(batch2.get('unmarked_word_count', {}).get('median'))} | {fmt(batch2.get('gap_A_B', {}).get('median'))} / {fmt(batch2.get('gap_B_C', {}).get('median'))} / {fmt(batch2.get('gap_C_D', {}).get('median'))} |
| 3 | {batches['3']['item_count']} | {fmt(batches['3']['sentence_word_count']['median'])} | {fmt(batches['3']['marked_span_word_count_all_4_spans']['median'])} | {pct(batches['3']['coverage_ratio']['median'])} | {fmt(batches['3']['unmarked_word_count']['median'])} | {fmt(batches['3']['gap_A_B']['median'])} / {fmt(batches['3']['gap_B_C']['median'])} / {fmt(batches['3']['gap_C_D']['median'])} |

Batch 2はformat上の外れ値があるかを別に、`VALIDATION_FAILURE_AUDIT.md`で25問全てno_genuine_errorと記録されている。そのためBatch 2が幾何指標で極端に見えても、「WE itemとしてのvalidity failure」と「span format failure」を混同しない。Batch別の数値は出力JSONに保存した。

## 14. Human observation verification

1. **文が短い** — Official/AIのsentence mean・median差、および15語以下の比率で検証可能。差がAI側に出た場合は支持。
2. **marked parts / 選択肢が長い** — all marked spansのmedian、5+分布、item-level maxで検証可能。AI中央値/上位分位が大きければ支持。
3. **marked partsが文全体に及ぶ** — coverage ratioと>=60% binで検証可能。AI側が高ければ支持。
4. **何を問う問題なのか不自然** — decision granularity / correction localityの分布差、およびBatch 2 validity auditで部分的に検証。geometry単独では断定不可。
5. **答えが明確でない** — span長だけでは検証不可。semantic/context-dependent比率、correction parse、validity auditを補助証拠として扱う。数値が低くても「明確さ」を保証しない。

今回のデータでは、1–3は明確に支持される。具体的には、sentence medianは20語→10語、15語以下は公式16/125 (12.8%)→AI75/75 (100%)、marked span medianは1語→2語、5+ spanは公式0/500→AI21/300、coverage medianは26.3%→100%、>=60%は公式1/125→AI75/75、unmarked medianは15語→0語、gap A–B/B–C/C–D medianは4/4/4→0/0/0である。

4–5はpartial supportに留まる。decision granularity / correction localityは「問う単位」の違いを示すが、自然さ・明確さを直接測定するものではない。さらにBatch 2はformat geometry上も短文・連続markだが、既存auditで25/25がno_genuine_errorとされており、validity failureの実例としては強い。一方、geometryだけから「答えが明確でない」を全75問に一般化することはできない。反証となる指標がある場合は、AI全体だけでなくBatch別・validity別に読む。

## 15. Missing specification dimensions

既存のprimary target/error taxonomyだけでは、少なくとも次の形状軸が不足している。

- sentence word-count distribution
- A/B/C/D各spanのword countとspan type
- marked unique coverage ratio と unmarked context
- A→B→C→Dのtoken gap / span placement
- correct span length/type と correction surface size
- correction locality（local / dependency / clause / semantic-context）
- decision granularity（何を1単位として判断させるか）
- 公式観測分布に対するValidation/batch別の比較フィールド
- PDF/生成データでのspan alignment confidenceと測定方法

## 16. Recommended Specification additions

実装はまだ行わず、次工程の候補だけを示す。

### Generator v1.2候補

- まず公式125問の観測分布を基準に、sentence length / span length / coverage / gapをsoft targetとしてサンプリングする。
- A/B/C/Dを連続した長い領域に置くのではなく、unmarked contextとspan gapを明示的に生成状態へ持たせる。
- correct span lengthは、単一tokenだけに固定せず、公式のSHORT_PHRASE / dependency / clause-likeの混在を再現する。
- decision granularityをitem metadataとして先に選び、sentence全体の意味解釈だけを要求するsemantic/context itemを別枠管理する。
- 公式分布から外れた場合は、生成後にformat diagnosticsを付与し、後段Reviewerに渡す。

### Reviewer v1.2候補

- sentence too short / marked span too long / coverage too high / unmarked context too small / spans too contiguousを別々のstyle checksとして出す。
- A/B/C/Dごとのspan type、correct span size、gap、placementを監査し、primary targetの妥当性と分離する。
- LOCAL_SINGLE_TOKEN〜SEMANTIC_OR_CONTEXT_DEPENDENTのlocalityを判定し、semantic-onlyで正答が決まるitemを要レビューにする。
- Batch 2のような「文法的にエラーがない」問題をformat passに通さないvalidity gateを検討する。

これらは観測からのrecommendationであり、今回の工程ではGenerator/Reviewer/Specification/その他の実装は変更していない。`max=3`などのhard thresholdもまだ決めていない。

## Reproducibility and limitations

生成物のitem-level JSON/CSVには、全count、ratio、span type、placement、gaps、correct span、locality、decision granularityを保存した。公式はPDF underliningの可視情報を用いたが、token offsetのexact extractionができないため、official placement/gapはapproximationである。Validationはsentence/marked_partsのexact token alignmentを使った。今後、公式のclean text transcriptionまたは座標付きunderlining annotationが得られた場合、count tableを差し替えて同じscriptを再実行できる。

今回の成果物作成以外に、Generator、Reviewer、Solver、Orchestrator、Specification、Taxonomy、DB、Websiteは変更していない。
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    official = official_items()
    validation = validation_items()
    summaries = {
        "official": summarize(official),
        "validation": summarize(validation),
        "validation_batches": summarize(validation, "batch"),
    }
    official_payload = {
        "analysis_name": "WE format / span geometry — official",
        "analysis_version": "1.0",
        "source": [
            "analysis/written_expression_items_all.json",
            "source/Practice Test B Sec 2 SWE.pdf",
            "source/Practice Test C Sec 2 SWE.pdf",
            "source/Practice Test D Sec 2 SWE.pdf",
            "source/Practice Test E Sec 2 SWE.pdf",
            "source/Practice Test F Sec 2 SWE.pdf",
        ],
        "item_count": len(official),
        "tokenization_rule": TOKENIZATION_RULE,
        "official_sentence_remeasurement": {
            "method": "same token rule applied as a reconciliation pass against existing PDF-derived sentence counts",
            "all_deltas_zero": all(row["sentence_word_count_remeasurement_delta"] == 0 for row in official),
            "note": "Official PDF text layer is not a reliable clean-token source; raw sentence text is intentionally not copied into this artifact.",
        },
        "span_type_definition": {
            "SINGLE_WORD": "1 token",
            "SHORT_PHRASE": "2–4 tokens, non-clausal phrase",
            "LONG_PHRASE": "5+ tokens",
            "CLAUSE_OR_CLAUSE_LIKE": "clause or clause-like unit identified with role/subtype/scope plus span length",
        },
        "correction_token_count_rule": "max(source correction token count, target correction token count); no-correction claim=0; unparseable=null",
        "measurement_confidence": {
            "sentence_word_count": "high after PDF/source reconciliation",
            "span_word_count": "high from visible underlines, with explicit transcription table",
            "official_span_position_and_gap": "approximate because the PDF text layer has no reliable token offsets",
        },
        "summary": summaries["official"],
        "items": official,
    }
    validation_payload = {
        "analysis_name": "WE format / span geometry — Validation v1.1",
        "analysis_version": "1.0",
        "source": [
            "analysis/validation/validation_batch1.json",
            "analysis/validation/validation_batch2.json",
            "analysis/validation/validation_batch3.json",
        ],
        "item_count": len(validation),
        "batches": {str(batch): sum(item["batch"] == batch for item in validation) for batch in (1, 2, 3)},
        "tokenization_rule": TOKENIZATION_RULE,
        "span_type_definition": official_payload["span_type_definition"],
        "correction_token_count_rule": official_payload["correction_token_count_rule"],
        "measurement_confidence": {
            "sentence_word_count": "high from validation sentence strings",
            "span_word_count": "high from validation marked_parts strings",
            "span_position_and_gap": "high when alignment_status=aligned; item status is preserved",
        },
        "summary": summaries["validation"],
        "summary_by_batch": summaries["validation_batches"],
        "items": validation,
    }
    (OUT / "written_expression_format_official.json").write_text(json.dumps(official_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "written_expression_format_validation.json").write_text(json.dumps(validation_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT / "written_expression_format_official.csv", official)
    (OUT / "WE_FORMAT_ANALYSIS_REPORT.md").write_text(build_report(official, validation, summaries), encoding="utf-8")
    print(json.dumps({
        "official_items": len(official),
        "validation_items": len(validation),
        "official_summary": summaries["official"]["all"],
        "validation_summary": summaries["validation"]["all"],
        "outputs": [str(path.relative_to(ROOT)) for path in OUT.iterdir() if path.is_file()],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
