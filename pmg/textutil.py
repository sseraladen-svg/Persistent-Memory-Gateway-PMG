"""Small text helpers shared across the layer."""
from __future__ import annotations

import re

STOPWORDS = frozenset(
    "the a an and or but if then of to in on at for with from by is are was were be been "
    "am do does did have has had i me my you your we our it its this that these those "
    "what which who how when where why can could should would will just about into over "
    "not no yes so as than too very".split()
)


def est_tokens(text: str) -> int:
    """Cheap token estimate (about four characters per token). Good enough for budgeting."""
    return max(1, len(text) // 4)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def keywords(text: str) -> list[str]:
    """Lowercase content words, without stopwords or very short tokens."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS]


def unique_keywords(text: str, limit: int | None = None) -> list[str]:
    words = list(dict.fromkeys(keywords(text)))
    return words[:limit] if limit else words


MONTHS = frozenset("january february march april may june july august september october november december "
                   "jan feb mar apr jun jul aug sep sept oct nov dec".split())
_NUMERIC = re.compile(r"[0-9][0-9.,:/%-]*[a-z]{0,3}")


def slot_tokens(text: str) -> list[str]:
    """Lowercase tokens in order, keeping numbers, without stopwords."""
    return [w for w in re.findall(r"[a-z0-9]+(?:[.,:/%-][0-9]+)*", text.lower()) if w not in STOPWORDS]


def is_value_token(token: str) -> bool:
    return bool(_NUMERIC.fullmatch(token)) or token in MONTHS


FILLER = frozenset("now currently updated update changed new actually".split())
_ASSIGN = frozenset("is are was to at be".split())


def _raw_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[.,:/%-][0-9]+)*", text.lower())


def _split_value(text: str):
    """(tokens before the value run, the value run, the token that introduces it) for a note ending in a value."""
    toks = _raw_tokens(text)
    i = len(toks)
    while i > 0 and is_value_token(toks[i - 1]):
        i -= 1
    if i == len(toks):
        return None
    j = i
    while j > 0 and toks[j - 1] in FILLER:
        j -= 1
    if j == 0 or toks[j - 1] not in _ASSIGN:
        return None
    prefix = [t for t in toks[:i] if t not in STOPWORDS and t not in FILLER]
    return prefix, toks[i:], toks[j - 1]


def replaces(new: str, old: str) -> bool:
    """True when `new` is the same note as `old` with a different value at the end (see experiments/e8_supersede)."""
    a, b = _split_value(new), _split_value(old)
    if not a or not b:
        return False
    return a[0] == b[0] and len(a[0]) >= 2 and a[1] != b[1]


def make_gist(text: str, max_words: int = 12) -> str | None:
    """A very short extractive form (the first words), or None when the text is already that short."""
    words = text.split()
    if len(words) <= max_words + 2:
        return None
    return " ".join(words[:max_words]).rstrip(",;:") + "..."
