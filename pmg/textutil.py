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


def replaces(new: str, old: str) -> bool:
    """True when `new` looks like the same note with a changed number or date at the end (see E8)."""
    a, b = slot_tokens(new), slot_tokens(old)
    shared = set(a) & set(b)
    only_a, only_b = [t for t in a if t not in shared], [t for t in b if t not in shared]
    if not only_a or not only_b:
        return False
    if not all(is_value_token(t) for t in only_a + only_b):
        return False
    # How alike the notes are is judged on content words only: a changed month or number is the point, not a difference.
    content = lambda toks: {t for t in toks if not is_value_token(t)}
    shared_content = shared & content(a) & content(b)
    if len(shared_content) < 2 or len(shared_content) < 0.6 * min(len(content(a)), len(content(b))):
        return False
    last_shared = lambda toks: max((i for i, t in enumerate(toks) if t in shared), default=-1)
    first_diff = lambda toks: min(i for i, t in enumerate(toks) if t not in shared)
    return first_diff(a) > last_shared(a) and first_diff(b) > last_shared(b)


def make_gist(text: str, max_words: int = 12) -> str | None:
    """A very short extractive form (the first words), or None when the text is already that short."""
    words = text.split()
    if len(words) <= max_words + 2:
        return None
    return " ".join(words[:max_words]).rstrip(",;:") + "..."
