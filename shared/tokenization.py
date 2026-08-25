"""Shared lexical tokenization for Written Expression format artifacts.

The format analysis, planner, deterministic validator, and pilot integrity
audit must count the same tokens.  A lexical token is a Unicode letter/number
run with an internal ASCII or curly apostrophe or ASCII hyphen.  Punctuation
and punctuation-only fragments are not tokens.
"""

from __future__ import annotations

import re


# ``[^\W_]`` means a Unicode word character other than underscore.  Keeping
# the pattern here prevents the analysis artifact and runtime validators from
# silently developing different word-count contracts.
LEXICAL_TOKEN_PATTERN = r"[^\W_]+(?:['’\-][^\W_]+)*"
LEXICAL_TOKEN_RE = re.compile(LEXICAL_TOKEN_PATTERN, re.UNICODE)


def lexical_token_matches(text: str | None) -> list[re.Match[str]]:
    """Return lexical token matches, excluding punctuation-only fragments."""

    return list(LEXICAL_TOKEN_RE.finditer(text or ""))


def lexical_tokens(text: str | None) -> list[str]:
    """Return lexical token surface forms under the shared contract."""

    return [match.group(0) for match in lexical_token_matches(text)]


def lexical_token_spans(
    sentence: str | None,
    span: str | None,
    *,
    casefold: bool = False,
) -> list[tuple[int, int]]:
    """Find contiguous token-sequence occurrences in ``sentence``.

    The returned ranges are half-open token indices.  Matching is performed
    on lexical tokens, never on raw substrings, so ``in`` does not occur inside
    ``international`` and ``he`` does not occur inside ``the``.  Surface case
    is preserved by default to retain the existing exact-span behavior; callers
    that need case-insensitive analysis can opt into ``casefold=True``.
    """

    sentence_words = lexical_tokens(sentence)
    span_words = lexical_tokens(span)
    if not span_words or len(span_words) > len(sentence_words):
        return []

    if casefold:
        sentence_words = [word.casefold() for word in sentence_words]
        span_words = [word.casefold() for word in span_words]

    width = len(span_words)
    return [
        (start, start + width)
        for start in range(len(sentence_words) - width + 1)
        if sentence_words[start : start + width] == span_words
    ]
