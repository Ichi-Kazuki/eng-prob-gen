#!/usr/bin/env python3
"""Apply Reading structural-difficulty calibration v0.1.

Usage:
  python apply_reading_difficulty_v01.py --check
  python apply_reading_difficulty_v01.py --apply

Run this from the eng-prob-gen repository root.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DIFFICULTY_PY = '"""Deterministic structural-difficulty proxies for Reading v0.2.\n\nThis module deliberately does not claim psychometric equivalence with TOEFL\nITP. It exposes a stable calibration interface now, while official-item\nfeature measurements and human response data can replace the provisional\nguardrails later without changing Planner/diagnostics call sites.\n"""\n\nfrom __future__ import annotations\n\nimport json\nimport re\nfrom collections import Counter\nfrom pathlib import Path\nfrom statistics import mean\nfrom typing import Any\n\nROOT = Path(__file__).resolve().parents[1]\nDIFFICULTY_PROFILE_PATH = ROOT / "analysis" / "reading_v0_2_difficulty_profile.json"\n\n_WORD_RE = re.compile(r"[A-Za-z]+(?:\'[A-Za-z]+)?")\n_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])(?:[\\"\')\\]]*)\\s+")\n\n_STOPWORDS = frozenset({\n    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",\n    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",\n    "he", "her", "hers", "him", "his", "how", "if", "in", "into", "is", "it",\n    "its", "may", "might", "more", "most", "not", "of", "on", "or", "our",\n    "she", "should", "so", "some", "such", "than", "that", "the", "their",\n    "them", "then", "there", "these", "they", "this", "those", "to", "was",\n    "we", "were", "what", "when", "where", "which", "while", "who", "why",\n    "will", "with", "would", "you", "your",\n})\n\n_EVIDENCE_SCOPE_BY_SUBTYPE = {\n    "DIRECT_FACTUAL_DETAIL": "LOCAL",\n    "PARAPHRASED_FACTUAL_DETAIL": "LOCAL_TO_MULTI_SENTENCE",\n    "NEGATIVE_EXCEPT_DETAIL": "LOCAL_TO_MULTI_SENTENCE",\n    "LOCAL_INFERENCE": "LOCAL_TO_MULTI_SENTENCE",\n    "CROSS_IDEA_INFERENCE": "DISTRIBUTED",\n    "RHETORICAL_PURPOSE": "LOCAL_TO_MULTI_SENTENCE",\n    "VOCABULARY_CONTEXT_MEANING": "LOCAL",\n    "PASSAGE_MAIN_IDEA": "WHOLE_PASSAGE",\n    "ANTECEDENT_REFERENCE": "LOCAL",\n}\n\n_INFERENCE_DEPTH_BY_SUBTYPE = {\n    "LOCAL_INFERENCE": "LOCAL",\n    "CROSS_IDEA_INFERENCE": "CROSS_IDEA",\n    "RHETORICAL_PURPOSE": "RHETORICAL_PURPOSE",\n}\n\n\ndef _load_profile(path: Path = DIFFICULTY_PROFILE_PATH) -> dict[str, Any]:\n    try:\n        raw = json.loads(path.read_text(encoding="utf-8"))\n    except (OSError, json.JSONDecodeError) as exc:\n        raise RuntimeError(f"could not load Reading difficulty profile: {path}") from exc\n    if not isinstance(raw, dict):\n        raise RuntimeError("Reading difficulty profile must be an object")\n    required = {\n        "schema_version",\n        "status",\n        "target_band",\n        "psychometric_equivalence",\n        "dimensions",\n        "guardrails",\n    }\n    if not required.issubset(raw):\n        missing = ", ".join(sorted(required - set(raw)))\n        raise RuntimeError(f"Reading difficulty profile is missing: {missing}")\n    if raw["psychometric_equivalence"] is not False:\n        raise RuntimeError("provisional Reading difficulty profile must not claim psychometric equivalence")\n    if not isinstance(raw["dimensions"], dict) or not isinstance(raw["guardrails"], dict):\n        raise RuntimeError("Reading difficulty dimensions and guardrails must be objects")\n    return raw\n\n\nDIFFICULTY_PROFILE = _load_profile()\n\n\ndef plan_difficulty_profile() -> dict[str, Any]:\n    """Return the Planner-facing, prompt-safe structural target."""\n\n    return {\n        "profile_id": DIFFICULTY_PROFILE["schema_version"],\n        "target_band": DIFFICULTY_PROFILE["target_band"],\n        "calibration_status": "PROVISIONAL_STRUCTURAL_PROXY",\n        "psychometric_equivalence": False,\n        "dimensions": dict(DIFFICULTY_PROFILE["dimensions"]),\n    }\n\n\ndef _word_tokens(text: str) -> list[str]:\n    return [match.group(0).casefold() for match in _WORD_RE.finditer(text)]\n\n\ndef _content_tokens(text: str) -> set[str]:\n    return {\n        token\n        for token in _word_tokens(text)\n        if len(token) > 2 and token not in _STOPWORDS\n    }\n\n\ndef _sentence_word_counts(text: str) -> list[int]:\n    normalized = re.sub(r"\\s+", " ", text).strip()\n    if not normalized:\n        return []\n    sentences = [\n        sentence.strip()\n        for sentence in _SENTENCE_SPLIT_RE.split(normalized)\n        if sentence.strip()\n    ]\n    return [len(_word_tokens(sentence)) for sentence in sentences if _word_tokens(sentence)]\n\n\ndef _lexical_overlap(left: str, right: str) -> float | None:\n    left_tokens = _content_tokens(left)\n    right_tokens = _content_tokens(right)\n    if not left_tokens or not right_tokens:\n        return None\n    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)\n\n\ndef _question_answer_evidence_overlap(question: dict[str, Any]) -> float | None:\n    if question.get("question_type") in {"VOCABULARY_IN_CONTEXT", "REFERENCE"}:\n        return None\n    choices = question.get("choices")\n    correct = question.get("correct_answer")\n    evidence = question.get("evidence")\n    if not isinstance(choices, dict) or not isinstance(correct, str) or not isinstance(evidence, dict):\n        return None\n    answer = choices.get(correct)\n    anchor = evidence.get("anchor")\n    if not isinstance(answer, str) or not isinstance(anchor, str):\n        return None\n    return _lexical_overlap(answer, anchor)\n\n\ndef _distractor_categories(question: dict[str, Any]) -> list[str]:\n    metadata = question.get("distractor_metadata")\n    correct = question.get("correct_answer")\n    if not isinstance(metadata, dict) or not isinstance(correct, str):\n        return []\n    categories: list[str] = []\n    for label, entry in metadata.items():\n        if label == correct or not isinstance(entry, dict):\n            continue\n        category = entry.get("category")\n        if isinstance(category, str):\n            categories.append(category)\n    return categories\n\n\ndef _round(value: float | None, digits: int = 4) -> float | None:\n    return None if value is None else round(value, digits)\n\n\ndef estimate_difficulty_alignment(\n    plan: dict[str, Any] | None,\n    generator: dict[str, Any] | None,\n) -> dict[str, Any]:\n    """Estimate observable structural difficulty and compare it with guardrails.\n\n    PASS means only that no anti-pattern guardrail fired. It does not mean\n    empirical or score equivalence with an official TOEFL ITP item.\n    """\n\n    target = plan.get("difficulty_profile") if isinstance(plan, dict) else None\n    if not isinstance(target, dict):\n        target = plan_difficulty_profile()\n\n    base = {\n        "schema_version": "reading-difficulty-estimate-v0.1",\n        "target_band": target.get("target_band", DIFFICULTY_PROFILE["target_band"]),\n        "calibration_status": "PROVISIONAL_STRUCTURAL_PROXY",\n        "psychometric_equivalence": False,\n    }\n    if not isinstance(generator, dict):\n        return {\n            **base,\n            "status": "UNAVAILABLE",\n            "dimension_status": {},\n            "observed": {},\n            "warnings": [],\n        }\n\n    passage = generator.get("passage")\n    questions = generator.get("questions")\n    if not isinstance(passage, str) or not isinstance(questions, list):\n        return {\n            **base,\n            "status": "UNAVAILABLE",\n            "dimension_status": {},\n            "observed": {},\n            "warnings": ["DIFFICULTY_INPUT_UNAVAILABLE"],\n        }\n\n    question_objects = [q for q in questions if isinstance(q, dict)]\n    words = _word_tokens(passage)\n    sentence_words = _sentence_word_counts(passage)\n\n    long_word_rate = (\n        sum(len(token.replace("\'", "")) >= 8 for token in words) / len(words)\n        if words else 0.0\n    )\n    mean_sentence_words = mean(sentence_words) if sentence_words else 0.0\n\n    overlaps = [\n        overlap\n        for question in question_objects\n        if (overlap := _question_answer_evidence_overlap(question)) is not None\n    ]\n    guardrails = DIFFICULTY_PROFILE["guardrails"]\n    copy_threshold = float(guardrails["surface_copy_overlap_warning_at_or_above"])\n    copied = [overlap for overlap in overlaps if overlap >= copy_threshold]\n    surface_copy_share = len(copied) / len(overlaps) if overlaps else None\n\n    subtype_counts = Counter(\n        question.get("subtype", "UNKNOWN")\n        for question in question_objects\n        if isinstance(question.get("subtype"), str)\n    )\n    evidence_scope_counts = Counter(\n        _EVIDENCE_SCOPE_BY_SUBTYPE.get(question.get("subtype"), "UNKNOWN")\n        for question in question_objects\n    )\n    inference_depth_counts = Counter(\n        _INFERENCE_DEPTH_BY_SUBTYPE.get(question.get("subtype"), "UNKNOWN")\n        for question in question_objects\n        if question.get("question_type") == "INFERENCE"\n    )\n\n    distractor_categories = [\n        category\n        for question in question_objects\n        for category in _distractor_categories(question)\n    ]\n    distractor_counts = Counter(distractor_categories)\n    contradicted_share = (\n        distractor_counts["CONTRADICTED_BY_PASSAGE"] / len(distractor_categories)\n        if distractor_categories else None\n    )\n\n    warnings: list[str] = []\n    if long_word_rate > float(guardrails["long_word_rate_warning_above"]):\n        warnings.append("LEXICAL_LOAD_RISK")\n    if mean_sentence_words > float(guardrails["mean_sentence_words_warning_above"]):\n        warnings.append("SYNTACTIC_LOAD_RISK")\n    if (\n        surface_copy_share is not None\n        and surface_copy_share > float(guardrails["surface_copy_question_share_warning_above"])\n    ):\n        warnings.append("CORRECT_OPTION_SURFACE_COPY_RISK")\n    if (\n        contradicted_share is not None\n        and contradicted_share > float(guardrails["contradicted_distractor_share_warning_above"])\n    ):\n        warnings.append("DIRECTLY_CONTRADICTED_DISTRACTOR_DOMINANCE")\n\n    dimension_status = {\n        "lexical": "WARN" if "LEXICAL_LOAD_RISK" in warnings else "PASS",\n        "syntactic": "WARN" if "SYNTACTIC_LOAD_RISK" in warnings else "PASS",\n        "paraphrase": "WARN" if "CORRECT_OPTION_SURFACE_COPY_RISK" in warnings else "PASS",\n        "evidence_distance": "OBSERVED_ONLY",\n        "inference_depth": "OBSERVED_ONLY",\n        "distractor_competitiveness": (\n            "WARN" if "DIRECTLY_CONTRADICTED_DISTRACTOR_DOMINANCE" in warnings else "PASS"\n        ),\n    }\n\n    return {\n        **base,\n        "status": "WARN" if warnings else "PASS",\n        "dimension_status": dimension_status,\n        "observed": {\n            "passage_word_count": len(words),\n            "sentence_count": len(sentence_words),\n            "mean_sentence_words": _round(mean_sentence_words, 2),\n            "long_word_rate": _round(long_word_rate),\n            "answer_evidence_lexical_overlap_mean": _round(mean(overlaps) if overlaps else None),\n            "surface_copy_question_share": _round(surface_copy_share),\n            "subtype_distribution": dict(sorted(subtype_counts.items())),\n            "evidence_scope_proxy_distribution": dict(sorted(evidence_scope_counts.items())),\n            "inference_depth_proxy_distribution": dict(sorted(inference_depth_counts.items())),\n            "distractor_category_distribution": dict(sorted(distractor_counts.items())),\n            "directly_contradicted_distractor_share": _round(contradicted_share),\n        },\n        "warnings": warnings,\n    }\n'
PROFILE = {'schema_version': 'reading-difficulty-profile-v0.1', 'status': 'provisional_structural_proxy', 'target_band': 'ITP_STYLE_STANDARD', 'psychometric_equivalence': False, 'calibration_basis': 'Engineering guardrails for structural difficulty. These thresholds are not ETS-derived item difficulty parameters and are not score-equivalent to TOEFL ITP.', 'dimensions': {'lexical': 'MODERATE_ACADEMIC_NOT_OBSCURE', 'syntactic': 'MODERATE_ACADEMIC_NOT_ARTIFICIALLY_COMPLEX', 'paraphrase': 'MEANING_PRESERVING_NONCOPYING', 'evidence_distance': 'MIX_LOCAL_AND_DISTRIBUTED_WHEN_NATURAL', 'inference_depth': 'SUPPORTED_NONTRIVIAL_WHEN_PLANNED', 'distractor_competitiveness': 'PLAUSIBLE_TEXT_GROUNDED'}, 'guardrails': {'long_word_rate_warning_above': 0.36, 'mean_sentence_words_warning_above': 34.0, 'surface_copy_overlap_warning_at_or_above': 0.82, 'surface_copy_question_share_warning_above': 0.5, 'contradicted_distractor_share_warning_above': 0.5}, 'future_calibration': {'official_feature_measurement_required': True, 'recommended_features': ['evidence_distance', 'answer_evidence_lexical_overlap', 'inference_depth', 'distractor_mechanism', 'vocabulary_context_discrimination'], 'human_response_data_required_for_psychometric_difficulty': True}}
DOC = '# Reading difficulty calibration v0.1\n\nThis layer adds a deterministic structural-difficulty interface to Reading v0.2\nwithout claiming TOEFL ITP score equivalence.\n\nThe Planner emits a `difficulty_profile` with six dimensions: lexical load,\nsyntactic load, paraphrase distance, evidence distance, inference depth, and\ndistractor competitiveness. The Generator treats those dimensions as\nconstruction constraints. Diagnostics then estimate observable proxies from\nthe generated passage and private QA metadata.\n\nThe current thresholds are engineering guardrails only. They are intended to\ncatch artificial hardness (obscure lexical load, excessive sentence length)\nand artificial easiness (surface-copy answers, distractors dominated by\ndirect contradiction). They are deliberately not used as a hard acceptance\ngate.\n\nNext calibration step: measure the same features on the official-derived B-E\nreference set, preferably with a held-out-test design. Once learner response\ndata exists, add empirical item difficulty, discrimination, and eventually a\nRasch/IRT layer without changing the Planner/diagnostics interface.\n'
TEST_PY = '"""Regression tests for the provisional Reading difficulty layer."""\n\nfrom __future__ import annotations\n\nimport unittest\n\nfrom reading.difficulty import estimate_difficulty_alignment, plan_difficulty_profile\nfrom reading.planner import build_plan_v02\n\n\nclass ReadingDifficultyTests(unittest.TestCase):\n    def test_planner_emits_difficulty_profile(self) -> None:\n        plan = build_plan_v02(12345)\n        profile = plan["difficulty_profile"]\n        self.assertEqual(profile["target_band"], "ITP_STYLE_STANDARD")\n        self.assertEqual(profile["calibration_status"], "PROVISIONAL_STRUCTURAL_PROXY")\n        self.assertFalse(profile["psychometric_equivalence"])\n        self.assertEqual(\n            set(profile["dimensions"]),\n            {\n                "lexical",\n                "syntactic",\n                "paraphrase",\n                "evidence_distance",\n                "inference_depth",\n                "distractor_competitiveness",\n            },\n        )\n\n    def test_estimator_never_claims_score_equivalence(self) -> None:\n        report = estimate_difficulty_alignment(\n            {"difficulty_profile": plan_difficulty_profile()},\n            {"passage": "Plants store energy. Researchers compare several sites.", "questions": []},\n        )\n        self.assertFalse(report["psychometric_equivalence"])\n        self.assertIn(report["status"], {"PASS", "WARN"})\n\n\nif __name__ == "__main__":\n    unittest.main()\n'

TARGET_FILES = (
    "reading/planner.py",
    "reading/pipeline.py",
    "reading/diagnostics.py",
    "reading/schemas/reading_plan_v0_2.schema.json",
    ".claude/agents/toefl-itp-reading-generator-v0.2.md",
)


def die(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count == 0:
        die(f"{label}: expected anchor was not found. Repository may have changed.")
    if count > 1:
        die(f"{label}: expected anchor appears {count} times; refusing ambiguous edit.")
    return text.replace(old, new, 1)


def git_dirty(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *TARGET_FILES],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def check_repo(root: Path) -> None:
    if not (root / ".git").exists():
        die("run this script from the eng-prob-gen repository root (.git not found)")
    for rel in TARGET_FILES:
        if not (root / rel).exists():
            die(f"missing expected file: {rel}")


def build_changes(root: Path) -> dict[str, str]:
    changes: dict[str, str] = {}

    # planner.py
    rel = "reading/planner.py"
    text = (root / rel).read_text(encoding="utf-8")
    if "from .difficulty import plan_difficulty_profile" not in text:
        text = replace_once(
            text,
            "from shared.schema_validation import load_schema, schema_errors\n",
            "from shared.schema_validation import load_schema, schema_errors\n\nfrom .difficulty import plan_difficulty_profile\n",
            label=rel,
        )
    if '"difficulty_profile": plan_difficulty_profile(),' not in text:
        text = replace_once(
            text,
            '        "question_type_counts": question_type_counts,\n    }',
            '        "question_type_counts": question_type_counts,\n'
            '        "difficulty_profile": plan_difficulty_profile(),\n'
            '    }',
            label=rel,
        )
    changes[rel] = text

    # pipeline.py
    rel = "reading/pipeline.py"
    text = (root / rel).read_text(encoding="utf-8")
    difficulty_guidance = (
        'READING_DIFFICULTY_GUIDANCE = (\n'
        '    "If the plan contains difficulty_profile, treat it as a structural calibration target, not a request for arbitrary " \n'
        '    "hardness. Keep lexical and syntactic load at moderate academic levels; do not manufacture difficulty with obscure " \n'
        '    "terminology, unnecessary sentence embedding, or trick logic. Create difficulty primarily through meaning-preserving " \n'
        '    "paraphrase, appropriate evidence integration, genuine supported inference when the planned type calls for it, and " \n'
        '    "plausible text-grounded distractors. Distributed evidence should be used only when naturally supported. The profile is " \n'
        '    "a provisional structural proxy and never implies TOEFL ITP score equivalence."\n'
        ')\n'
    )
    if "READING_DIFFICULTY_GUIDANCE = (" not in text:
        text = replace_once(
            text,
            "READING_INFERENCE_GUIDANCE = (\n",
            difficulty_guidance + "READING_INFERENCE_GUIDANCE = (\n",
            label=rel,
        )
    old = (
        '        f"{READING_INFERENCE_GUIDANCE} {READING_LENGTH_GUIDANCE} {READING_VOCABULARY_GUIDANCE} {READING_TARGET_GUIDANCE} "\n'
        '        f"{READING_CHOICE_GUIDANCE} {READING_TAXONOMY_GUIDANCE} {READING_DISTRACTOR_GUIDANCE} {READING_DOMAIN_GUIDANCE} "\n'
    )
    new = (
        '        f"{READING_DIFFICULTY_GUIDANCE} {READING_INFERENCE_GUIDANCE} {READING_LENGTH_GUIDANCE} "\n'
        '        f"{READING_VOCABULARY_GUIDANCE} {READING_TARGET_GUIDANCE} {READING_CHOICE_GUIDANCE} "\n'
        '        f"{READING_TAXONOMY_GUIDANCE} {READING_DISTRACTOR_GUIDANCE} {READING_DOMAIN_GUIDANCE} "\n'
    )
    if "f\"{READING_DIFFICULTY_GUIDANCE}" not in text:
        text = replace_once(text, old, new, label=rel)
    changes[rel] = text

    # diagnostics.py
    rel = "reading/diagnostics.py"
    text = (root / rel).read_text(encoding="utf-8")
    if "from .difficulty import estimate_difficulty_alignment" not in text:
        text = replace_once(
            text,
            "from .contracts import (\n",
            "from .difficulty import estimate_difficulty_alignment\n\nfrom .contracts import (\n",
            label=rel,
        )
    if '"difficulty": estimate_difficulty_alignment(result.get("plan"), None),' not in text:
        text = replace_once(
            text,
            '            "choice_quality_warnings": [],\n'
            '            "reviewer_solver_agreement": {"agree": 0, "total": 0, "rate": None},\n',
            '            "choice_quality_warnings": [],\n'
            '            "difficulty": estimate_difficulty_alignment(result.get("plan"), None),\n'
            '            "reviewer_solver_agreement": {"agree": 0, "total": 0, "rate": None},\n',
            label=rel,
        )
    if '"difficulty": estimate_difficulty_alignment(result.get("plan"), generator),' not in text:
        text = replace_once(
            text,
            '        "choice_quality_warnings": choice_quality_warnings(generator),\n'
            '        "reviewer_solver_agreement": {\n',
            '        "choice_quality_warnings": choice_quality_warnings(generator),\n'
            '        "difficulty": estimate_difficulty_alignment(result.get("plan"), generator),\n'
            '        "reviewer_solver_agreement": {\n',
            label=rel,
        )
    changes[rel] = text

    # Plan schema: additive/optional for backward compatibility with existing test fixtures.
    rel = "reading/schemas/reading_plan_v0_2.schema.json"
    schema = json.loads((root / rel).read_text(encoding="utf-8"))
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        die(f"{rel}: malformed properties")
    properties["difficulty_profile"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "profile_id",
            "target_band",
            "calibration_status",
            "psychometric_equivalence",
            "dimensions",
        ],
        "properties": {
            "profile_id": {"const": "reading-difficulty-profile-v0.1"},
            "target_band": {"const": "ITP_STYLE_STANDARD"},
            "calibration_status": {"const": "PROVISIONAL_STRUCTURAL_PROXY"},
            "psychometric_equivalence": {"const": False},
            "dimensions": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "lexical",
                    "syntactic",
                    "paraphrase",
                    "evidence_distance",
                    "inference_depth",
                    "distractor_competitiveness",
                ],
                "properties": {
                    "lexical": {"const": "MODERATE_ACADEMIC_NOT_OBSCURE"},
                    "syntactic": {"const": "MODERATE_ACADEMIC_NOT_ARTIFICIALLY_COMPLEX"},
                    "paraphrase": {"const": "MEANING_PRESERVING_NONCOPYING"},
                    "evidence_distance": {"const": "MIX_LOCAL_AND_DISTRIBUTED_WHEN_NATURAL"},
                    "inference_depth": {"const": "SUPPORTED_NONTRIVIAL_WHEN_PLANNED"},
                    "distractor_competitiveness": {"const": "PLAUSIBLE_TEXT_GROUNDED"},
                },
            },
        },
    }
    changes[rel] = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"

    # Agent definition.
    rel = ".claude/agents/toefl-itp-reading-generator-v0.2.md"
    text = (root / rel).read_text(encoding="utf-8")
    marker = "- For INFERENCE questions, vary reasoning depth according to what the passage naturally supports."
    difficulty_bullet = (
        "- If the plan contains `difficulty_profile`, treat it as a structural calibration target, not as a request for arbitrary hardness. "
        "Keep lexical and syntactic load at moderate academic levels; do not manufacture difficulty with obscure terminology, unnecessary "
        "sentence embedding, or trick logic. Create difficulty primarily through meaning-preserving paraphrase, appropriate evidence "
        "integration, genuine supported inference when the planned type calls for it, and plausible text-grounded distractors. "
        "`MIX_LOCAL_AND_DISTRIBUTED_WHEN_NATURAL` means use distributed evidence only when the passage genuinely supports it; never force "
        "cross-idea reasoning just to satisfy the profile. The profile is a provisional structural proxy and never implies TOEFL ITP score equivalence.\n"
    )
    if "`difficulty_profile`" not in text:
        text = replace_once(text, marker, difficulty_bullet + marker, label=rel)
    changes[rel] = text

    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true", help="allow target files with uncommitted changes")
    args = parser.parse_args()

    root = Path.cwd()
    check_repo(root)

    dirty = git_dirty(root)
    if dirty and not args.force:
        print("Target files have uncommitted changes:")
        for line in dirty:
            print("  " + line)
        die("commit/stash those changes first, or rerun with --force if you intentionally want to edit them")

    changes = build_changes(root)

    new_files = {
        "reading/difficulty.py": DIFFICULTY_PY,
        "analysis/reading_v0_2_difficulty_profile.json": json.dumps(PROFILE, ensure_ascii=False, indent=2) + "\n",
        "analysis/READING_DIFFICULTY_CALIBRATION.md": DOC,
        "tests/test_reading_difficulty.py": TEST_PY,
    }

    if args.check:
        print("CHECK OK")
        print("Existing files that can be updated safely:")
        for rel in changes:
            print("  " + rel)
        print("New files that will be created:")
        for rel in new_files:
            print("  " + rel)
        return 0

    for rel, content in changes.items():
        (root / rel).write_text(content, encoding="utf-8")
    for rel, content in new_files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    print("APPLY OK")
    print("Next run:")
    print("  python -m pytest tests/test_reading_difficulty.py tests/test_reading_v025_regressions.py")
    print("Then inspect:")
    print("  git diff -- reading analysis tests .claude/agents/toefl-itp-reading-generator-v0.2.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
