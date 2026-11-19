"""The memory store: tiny chunks in SQLite, selected by full-text search inside a token budget."""
from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from . import classify, config, rules as rules_mod
from .llm import Completer
from .textutil import est_tokens, normalize, unique_keywords

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, text TEXT NOT NULL, norm TEXT NOT NULL UNIQUE,
    tags TEXT NOT NULL DEFAULT '', key TEXT, importance INTEGER NOT NULL DEFAULT 3,
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    last_used REAL, uses INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_key ON chunks(key) WHERE key IS NOT NULL;
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tags, tokenize = 'porter unicode61');
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL, injected_tokens INTEGER NOT NULL,
    chunks INTEGER NOT NULL, stored_tokens INTEGER NOT NULL
);
"""

_COST = "(MAX(1, LENGTH(text) / 4) + 2)"  # mirrors est_tokens(text) + 2 (per-line overhead)


def chunk_cost(text: str) -> int:
    return est_tokens(text) + 2


class Memory:
    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = str(db_path or config.db_path())
        with self._db() as c:
            c.executescript(SCHEMA)

    @contextlib.contextmanager
    def _db(self):
        """Open, commit on success, roll back on error, and always close."""
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            with c:
                yield c
        finally:
            c.close()

    # ------------------------------------------------------------------ writing
    def add(self, kind: str, text: str, tags: str = "", importance: int = 3, key: Optional[str] = None) -> int:
        """Store one chunk. Exact duplicates merge; a repeated `key` replaces the older value."""
        text = text.strip()
        now, norm = time.time(), normalize(text)
        tags = tags or " ".join(unique_keywords(text, 6))
        with self._db() as c:
            row = c.execute("SELECT id FROM chunks WHERE norm = ?", (norm,)).fetchone()
            if row:
                c.execute("UPDATE chunks SET updated_at = ? WHERE id = ?", (now, row["id"]))
                return row["id"]
            if key:
                row = c.execute("SELECT id FROM chunks WHERE key = ?", (key,)).fetchone()
                if row:
                    c.execute(
                        "UPDATE chunks SET kind=?, text=?, norm=?, tags=?, importance=?, updated_at=? WHERE id=?",
                        (kind, text, norm, tags, importance, now, row["id"]))
                    c.execute("DELETE FROM chunks_fts WHERE rowid = ?", (row["id"],))
                    c.execute("INSERT INTO chunks_fts(rowid, text, tags) VALUES (?,?,?)", (row["id"], text, tags))
                    return row["id"]
            cur = c.execute(
                "INSERT INTO chunks (kind,text,norm,tags,key,importance,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (kind, text, norm, tags, key, importance, now, now))
            c.execute("INSERT INTO chunks_fts(rowid, text, tags) VALUES (?,?,?)", (cur.lastrowid, text, tags))
            return cur.lastrowid

    def ingest(self, text: str, complete: Optional[Completer] = None) -> Optional[int]:
        """Classify a raw message and keep it if it is worth remembering. Returns the chunk id or None."""
        verdict = classify.classify(text, rules_mod.load(), complete)
        if not verdict.get("store"):
            return None
        return self.add(verdict["kind"], verdict["text"], verdict["tags"], verdict["importance"], verdict["key"])

    def forget(self, chunk_id: int) -> bool:
        with self._db() as c:
            removed = c.execute("DELETE FROM chunks WHERE id = ?", (chunk_id,)).rowcount
            c.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
        return removed > 0

    # ------------------------------------------------------------------ reading
    def list(self, limit: int = 200, kind: Optional[str] = None, q: Optional[str] = None) -> list[dict]:
        sql, args = "SELECT id, kind, text, tags, key, importance, uses, created_at, updated_at FROM chunks", []
        where = []
        if kind:
            where.append("kind = ?"); args.append(kind)
        if q:
            where.append("(text LIKE ? OR tags LIKE ?)"); args += [f"%{q}%", f"%{q}%"]
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        with self._db() as c:
            return [dict(r) for r in c.execute(sql, [*args, limit])]

    def retrieve(self, query: str, budget_tokens: int = 0, log: bool = True) -> dict:
        """Choose the chunks to inject for `query`, inside a token budget.

        Order: always-load kinds (standing instructions) first, up to their share of the budget; then
        BM25 matches, weighted by kind weight, importance and recency decay.
        """
        rules = rules_mod.load()
        budget = budget_tokens or rules["budget_tokens"]
        max_chunks = rules["max_chunks"]
        always_cap = int(budget * rules["always_load_share"])
        now, picked, used = time.time(), [], 0
        with self._db() as c:
            always = [k for k, spec in rules["kinds"].items() if spec.get("always_load")]
            if always:
                marks = ",".join("?" * len(always))
                for r in c.execute(
                        f"SELECT * FROM chunks WHERE kind IN ({marks}) ORDER BY importance DESC, updated_at DESC", always):
                    cost = chunk_cost(r["text"])
                    if used + cost <= always_cap and len(picked) < max_chunks:
                        picked.append({**dict(r), "score": None, "tokens": cost, "why": "always"}); used += cost
            words = unique_keywords(query)
            if words:
                match = " OR ".join(f'"{w}"' for w in words)
                have = {p["id"] for p in picked}
                rows = c.execute(
                    "SELECT c.*, -bm25(chunks_fts) AS s FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                    "WHERE chunks_fts MATCH ? ORDER BY s DESC LIMIT 30", (match,)).fetchall()
                scored = []
                for r in rows:
                    if r["id"] in have:
                        continue
                    spec = rules["kinds"].get(r["kind"], {})
                    half_life = spec.get("half_life_days")
                    decay = 0.5 ** (((now - r["updated_at"]) / 86400) / half_life) if half_life else 1.0
                    score = r["s"] * spec.get("weight", 1.0) * decay * (1 + 0.1 * r["importance"])
                    scored.append((score, dict(r)))
                for score, r in sorted(scored, key=lambda x: -x[0]):
                    cost = chunk_cost(r["text"])
                    if used + cost <= budget and len(picked) < max_chunks:
                        picked.append({**r, "score": round(score, 3), "tokens": cost, "why": "match"}); used += cost
            if picked:
                ids = [p["id"] for p in picked]
                c.execute(f"UPDATE chunks SET uses = uses + 1, last_used = ? WHERE id IN ({','.join('?' * len(ids))})",
                          [now, *ids])
            if log:
                stored = c.execute(f"SELECT COALESCE(SUM({_COST}), 0) FROM chunks").fetchone()[0]
                c.execute("INSERT INTO events (ts, injected_tokens, chunks, stored_tokens) VALUES (?,?,?,?)",
                          (now, used, len(picked), stored))
        return {"chunks": picked, "tokens": used, "budget": budget, "text": format_chunks(picked)}

    def stats(self) -> dict:
        """Counts, stored size, and how much smaller the injected memory is than loading everything."""
        with self._db() as c:
            total = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            stored = c.execute(f"SELECT COALESCE(SUM({_COST}), 0) FROM chunks").fetchone()[0]
            kinds = {r["kind"]: r["n"] for r in c.execute("SELECT kind, COUNT(*) n FROM chunks GROUP BY kind")}
            recent = c.execute(
                "SELECT injected_tokens, stored_tokens FROM events ORDER BY id DESC LIMIT 200").fetchall()
            requests = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        injected = sum(r["injected_tokens"] for r in recent)
        baseline = sum(r["stored_tokens"] for r in recent)
        saved = round(100 * (1 - injected / baseline), 1) if baseline > 0 else None
        return {
            "chunks": total, "stored_tokens": stored, "kinds": kinds, "requests": requests,
            "avg_injected_tokens": round(injected / len(recent), 1) if recent else None,
            "saved_percent": saved,
        }

    # ------------------------------------------------------------------ tuning
    def propose_rules(self, complete: Completer) -> dict:
        """Ask the model for better numeric settings. Output is validated and clamped; nothing is applied here."""
        current = {k: v for k, v in rules_mod.load().items() if k in rules_mod.LIMITS}
        with self._db() as c:
            per_kind = [dict(r) for r in c.execute(
                "SELECT kind, COUNT(*) n, ROUND(AVG(uses),2) avg_uses, ROUND(AVG(LENGTH(text)),1) avg_len "
                "FROM chunks GROUP BY kind")]
        limits = ", ".join(f"{k} {lo}-{hi}" for k, (lo, hi) in rules_mod.LIMITS.items())
        raw = complete(
            f"You tune a memory layer. Current settings: {json.dumps(current)}. Per-kind stats: {json.dumps(per_kind)}. "
            f"Goal: fewest tokens injected per request while keeping useful chunks. Reply ONLY with JSON containing "
            f"any of these keys you want to change ({limits}) plus a 'why' string.")
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        out = {}
        for key, (lo, hi) in rules_mod.LIMITS.items():
            v = data.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
                out[key] = v
        out["why"] = str(data.get("why", ""))[:300]
        return out


def format_chunks(chunks: list[dict]) -> str:
    """Render chosen chunks as one compact block for a system message."""
    if not chunks:
        return ""
    behavior = [c["text"] for c in chunks if c["kind"] == "behavior"]
    rest = [c["text"] for c in chunks if c["kind"] != "behavior"]
    parts = []
    if behavior:
        parts.append("Follow:\n" + "\n".join(f"- {t}" for t in behavior))
    if rest:
        parts.append("Known about the user:\n" + "\n".join(f"- {t}" for t in rest))
    return "\n".join(parts)
