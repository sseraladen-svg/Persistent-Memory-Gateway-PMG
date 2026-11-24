"""Loading, validating and saving rules.json."""
from __future__ import annotations

import json
import re

from . import config

# Numeric settings that can be tuned, with their allowed ranges.
LIMITS = {
    "budget_tokens": (50, 4000),
    "always_load_share": (0.0, 0.9),
    "max_chunks": (1, 30),
    "min_chars": (2, 20),
}


def load() -> dict:
    with open(config.rules_path(), encoding="utf-8") as f:
        return json.load(f)


def validate(rules: dict) -> list[str]:
    """Return a list of human-readable problems; an empty list means the rules are valid."""
    problems: list[str] = []
    for key, (lo, hi) in LIMITS.items():
        value = rules.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not lo <= value <= hi:
            problems.append(f"{key} must be a number between {lo} and {hi}")
    kinds = rules.get("kinds")
    if not isinstance(kinds, dict) or not kinds:
        problems.append("kinds must be an object with at least one kind")
    else:
        for name, spec in kinds.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,23}", name):
                problems.append(f"kind name '{name}' must be lowercase letters, digits or underscores")
            if not isinstance(spec, dict) or not isinstance(spec.get("triggers"), list) \
                    or not all(isinstance(t, str) for t in spec["triggers"]):
                problems.append(f"kind '{name}' needs a list of text triggers")
                continue
            if not isinstance(spec.get("weight", 1.0), (int, float)) or spec.get("weight", 1.0) <= 0:
                problems.append(f"kind '{name}' weight must be a positive number")
            hl = spec.get("half_life_days")
            if hl is not None and (not isinstance(hl, (int, float)) or hl <= 0):
                problems.append(f"kind '{name}' half_life_days must be a positive number or null")
    patterns = rules.get("never_store_patterns")
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        problems.append("never_store_patterns must be a list of regular expressions")
    else:
        for p in patterns:
            try:
                re.compile(p)
            except re.error as exc:
                problems.append(f"never_store_patterns: '{p}' is not a valid expression ({exc})")
    return problems


def save(rules: dict) -> None:
    problems = validate(rules)
    if problems:
        raise ValueError("; ".join(problems))
    config.write_atomic(config.rules_path(), json.dumps(rules, indent=2) + "\n")


def apply_numeric(changes: dict) -> dict:
    """Apply only the whitelisted numeric settings, clamped to their limits. Returns what was applied."""
    rules = load()
    applied = {}
    for key, value in changes.items():
        if key in LIMITS and isinstance(value, (int, float)) and not isinstance(value, bool):
            lo, hi = LIMITS[key]
            if lo <= value <= hi:
                rules[key] = value
                applied[key] = value
    save(rules)
    return applied
