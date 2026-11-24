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


def make_gist(text: str, max_words: int = 12) -> str | None:
    """A very short extractive form (the first words), or None when the text is already that short."""
    words = text.split()
    if len(words) <= max_words + 2:
        return None
    return " ".join(words[:max_words]).rstrip(",;:") + "..."
