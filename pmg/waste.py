"""Estimate how much of the memory PMG loaded was actually echoed in the model's reply.

This is an estimate, not a measurement of use: a model can use a fact without repeating its words, and can repeat words
without needing the fact. Only chunks loaded because they matched the question are counted; standing instructions
("answer briefly") shape the reply without being quoted, so they are left out.
"""
from __future__ import annotations

import json
import math
import re

from .textutil import unique_keywords

MAX_REPLY_BYTES = 64_000
_SHARE = 0.3  # a chunk counts as echoed when this share of its key words appear in the reply (at least one)


def reply_text(raw: bytes) -> str:
    """The assistant's text from an OpenAI-style JSON response or a server-sent-events stream. Empty if unknown."""
    try:
        text = raw[:MAX_REPLY_BYTES].decode("utf-8", errors="ignore")
    except Exception:
        return ""
    parts: list[str] = []
    if re.match(r"\s*data:", text):
        for line in text.splitlines():
            if not line.startswith("data:") or line.strip() == "data: [DONE]":
                continue
            try:
                obj = json.loads(line[5:])
            except ValueError:
                continue
            for ch in obj.get("choices", []) if isinstance(obj, dict) else []:
                piece = (ch.get("delta") or {}).get("content")
                if isinstance(piece, str):
                    parts.append(piece)
        return "".join(parts)
    try:
        obj = json.loads(text)
    except ValueError:
        return ""
    for ch in obj.get("choices", []) if isinstance(obj, dict) else []:
        content = (ch.get("message") or {}).get("content")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _meets(word: str, reply_words: set[str]) -> bool:
    """True if the word, or a crude form of it ("run" for "running"), appears in the reply."""
    if word in reply_words:
        return True
    return len(word) >= 3 and any(len(r) >= 3 and (word.startswith(r) or r.startswith(word)) for r in reply_words)


def echoed_tokens(chunks: list[dict], reply: str) -> tuple[int, int]:
    """(tokens of matched chunks echoed in the reply, tokens of all matched chunks)."""
    reply_words = set(re.findall(r"[a-z0-9]+", reply.lower()))
    echoed = total = 0
    for c in chunks:
        if c.get("why") != "match":
            continue
        total += c["tokens"]
        words = unique_keywords(c["text"])
        if words and sum(_meets(w, reply_words) for w in words) >= max(1, math.ceil(_SHARE * len(words))):
            echoed += c["tokens"]
    return echoed, total
