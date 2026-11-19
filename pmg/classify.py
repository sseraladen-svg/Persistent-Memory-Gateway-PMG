"""Decide whether a message is worth remembering, and how to store it.

The rule-based classifier is always available. An optional LLM can do the same job with more nuance,
but its answer is validated and the layer falls back to the rules on any problem.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .llm import Completer
from .textutil import unique_keywords

NO = {"store": False}

PROMPT = """You classify one user message for a long-term memory store.
Reply with ONLY a JSON object, no prose:
{{"store": true|false, "kind": "<one of {kinds}>", "text": "<short, self-contained rewrite, max 25 words>",
 "tags": "<up to 6 lowercase keywords, space separated>", "importance": 1-5,
 "key": "<stable slot name like user.city if this replaces an older fact, else null>"}}
Store only durable facts, preferences or behavior instructions. Never store secrets, credentials or card numbers.
Message: {message}"""

_LEAD = re.compile(
    r"^(?:please\s+)?(?:remember|don't forget|keep in mind|learn this|save this)(?:\s+that)?[\s:,]+(.+)",
    re.I | re.S,
)


def extract_fact(text: str) -> str:
    """Strip a leading 'remember that ...' style command, keeping the fact itself."""
    t = text.strip()
    m = _LEAD.match(t)
    return m.group(1).strip() if m else t


def contains_secret(text: str, rules: dict) -> bool:
    return any(re.search(p, text) for p in rules.get("never_store_patterns", []))


def by_rules(text: str, rules: dict) -> dict:
    """Keyword classifier. Returns {store, kind, text, tags, importance, key}."""
    t = text.strip()
    min_chars = rules.get("min_chars", 3)
    if len(t) < min_chars or contains_secret(t, rules):
        return NO
    low = t.lower()
    for kind, spec in rules["kinds"].items():
        if any(trigger in low for trigger in spec["triggers"]):
            fact = extract_fact(t)
            if len(fact) < min_chars:
                return NO
            return {"store": True, "kind": kind, "text": fact,
                    "tags": " ".join(unique_keywords(fact, 6)), "importance": 3, "key": None}
    return NO


def by_llm(text: str, rules: dict, complete: Completer) -> dict:
    """Ask the model, validate the answer, and fall back to the rules if anything looks off."""
    fallback = by_rules(text, rules)
    try:
        raw = complete(PROMPT.format(kinds="/".join(rules["kinds"]), message=text[:1500]))
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        if not data.get("store"):
            return NO
        kind, body = data.get("kind"), str(data.get("text", "")).strip()
        if kind not in rules["kinds"] or len(body) < rules.get("min_chars", 3) or len(body) > 400:
            return fallback
        if contains_secret(body, rules) or contains_secret(text, rules):
            return NO
        importance = max(1, min(5, int(data.get("importance", 3))))
        key = data.get("key")
        key = key if isinstance(key, str) and re.fullmatch(r"[a-z0-9_.]{1,40}", key) else None
        tags = " ".join(unique_keywords(str(data.get("tags", "")), 6))
        return {"store": True, "kind": kind, "text": body, "tags": tags, "importance": importance, "key": key}
    except Exception:
        return fallback


def classify(text: str, rules: dict, complete: Optional[Completer] = None) -> dict:
    return by_llm(text, rules, complete) if complete else by_rules(text, rules)
