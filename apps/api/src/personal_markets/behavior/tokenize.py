from __future__ import annotations

import re

_SPLIT = re.compile(r"[^a-z0-9]+")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "by",
        "with",
        "from",
        "at",
        "is",
        "be",
        "page",
        "tab",
        "repo",
        "github",
        "notion",
        "sheets",
        "calendar",
        "gmail",
        "strava",
        "drive",
    }
)


def stem(token: str) -> str:
    if len(token) <= 3:
        return token
    for suffix in ("ing", "ers", "ies", "ied", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            stemmed = token[: -len(suffix)]
            if suffix == "ies":
                return stemmed + "y"
            return stemmed
    return token


def tokenize(*parts: object) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set)):
            text = " ".join(str(item) for item in part)
        elif isinstance(part, dict):
            text = " ".join(str(value) for value in part.values() if value is not None)
        else:
            text = str(part)
        for raw in _SPLIT.split(text.lower()):
            if not raw or raw in _STOP or raw.isdigit():
                continue
            token = stem(raw)
            if token in _STOP or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens


def char_ngrams(text: str, size: int = 4) -> set[str]:
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def overlap_score(left: list[str], right: list[str], left_text: str = "", right_text: str = "") -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        token_jaccard = 0.0
    else:
        token_jaccard = len(left_set & right_set) / len(left_set | right_set)
    grams_left = char_ngrams(left_text or " ".join(left))
    grams_right = char_ngrams(right_text or " ".join(right))
    if not grams_left or not grams_right:
        gram_jaccard = 0.0
    else:
        gram_jaccard = len(grams_left & grams_right) / len(grams_left | grams_right)
    return 0.7 * token_jaccard + 0.3 * gram_jaccard
