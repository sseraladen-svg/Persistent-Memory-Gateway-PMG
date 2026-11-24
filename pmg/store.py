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
from .ledger import Ledger
from .llm import Completer
from .textutil import est_tokens, make_gist, normalize, unique_keywords

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
-- Level 1: the append-only raw log. Every non-secret message is kept verbatim, so shrinking never loses a detail.
CREATE TABLE IF NOT EXISTS raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL, source TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, chunk_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_raw_chunk ON raw(chunk_id);
"""

# Columns added after the first release. Older databases are upgraded in place.
MIGRATIONS = (
    ("chunks", "gist", "TEXT"),            # level 3: a very short form, used when the full chunk does not fit
    ("chunks", "raw_id", "INTEGER"),       # link to the raw message this chunk came from
    ("events", "ms", "REAL NOT NULL DEFAULT 0"),  # time spent choosing chunks
)

_COST = "(MAX(1, LENGTH(text) / 4) + 2)"  # mirrors est_tokens(text) + 2 (per-line overhead)


def chunk_cost(text: str) -> int:
    return est_tokens(text) + 2


class Memory:
    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = str(db_path or config.db_path())
        self.ledger = Ledger()
        with self._db() as c:
            c.executescript(SCHEMA)
            for table, column, decl in MIGRATIONS:
                if column not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

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
    def add(self, kind: str, text: str, tags: str = "", importance: int = 3, key: Optional[str] = None,
            raw_id: Optional[int] = None) -> Optional[int]:
        """Store one chunk. Exact duplicates merge; a repeated `key` replaces the older value.

        Returns None, storing nothing, for secrets, text that reads like an instruction to the model, or text that
        is too long to be a note. This guard applies to every way in (CLI, MCP, dashboard, proxy)."""
        text = text.strip()
        if classify.unsafe_reason(text, rules_mod.load()):
            return None
        now, norm = time.time(), normalize(text)
        tags = tags or " ".join(unique_keywords(text, 6))
        gist = make_gist(text)
        with self._db() as c:
            c.execute("BEGIN IMMEDIATE")  # take the write lock first, so the check-then-insert below cannot race
            row = c.execute("SELECT id FROM chunks WHERE norm = ?", (norm,)).fetchone()
            if row:
                c.execute("UPDATE chunks SET updated_at = ? WHERE id = ?", (now, row["id"]))
                return row["id"]
            if key:
                row = c.execute("SELECT id FROM chunks WHERE key = ?", (key,)).fetchone()
                if row:
                    c.execute(
                        "UPDATE chunks SET kind=?, text=?, norm=?, tags=?, importance=?, updated_at=?, gist=?, "
                        "raw_id=COALESCE(?, raw_id) WHERE id=?",
                        (kind, text, norm, tags, importance, now, gist, raw_id, row["id"]))
                    if raw_id:
                        c.execute("UPDATE raw SET chunk_id = ? WHERE id = ?", (row["id"], raw_id))
                    c.execute("DELETE FROM chunks_fts WHERE rowid = ?", (row["id"],))
                    c.execute("INSERT INTO chunks_fts(rowid, text, tags) VALUES (?,?,?)", (row["id"], text, tags))
                    return row["id"]
            cur = c.execute(
                "INSERT INTO chunks (kind,text,norm,tags,key,importance,created_at,updated_at,gist,raw_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", (kind, text, norm, tags, key, importance, now, now, gist, raw_id))
            c.execute("INSERT INTO chunks_fts(rowid, text, tags) VALUES (?,?,?)", (cur.lastrowid, text, tags))
            if raw_id:
                c.execute("UPDATE raw SET chunk_id = ? WHERE id = ?", (cur.lastrowid, raw_id))
            return cur.lastrowid

    def log_raw(self, text: str, source: str = "") -> Optional[int]:
        """Append a message to the raw log, unless it looks like a secret. Returns the raw id."""
        text = text.strip()
        if not text or classify.contains_secret(text, rules_mod.load()):
            return None
        with self._db() as c:
            return c.execute("INSERT INTO raw (ts, source, text) VALUES (?,?,?)",
                             (time.time(), source, text)).lastrowid

    def ingest(self, text: str, complete: Optional[Completer] = None, source: str = "") -> Optional[int]:
        """Log a message verbatim, then keep a chunk of it if it is worth remembering.

        Returns the chunk id, or None when nothing durable was found (the raw message is still in the log)."""
        raw_id = self.log_raw(text, source)
        verdict = classify.classify(text, rules_mod.load(), complete)
        if not verdict.get("store"):
            return None
        return self.add(verdict["kind"], verdict["text"], verdict["tags"], verdict["importance"], verdict["key"],
                        raw_id=raw_id)

    def expand(self, chunk_id: int) -> Optional[dict]:
        """Return a chunk with every raw message that produced it (newest first). Nothing is summarised."""
        with self._db() as c:
            row = c.execute("SELECT id, kind, text, key, created_at, updated_at FROM chunks WHERE id = ?",
                            (chunk_id,)).fetchone()
            if not row:
                return None
            raws = [dict(r) for r in c.execute(
                "SELECT id, ts, source, text FROM raw WHERE chunk_id = ? ORDER BY id DESC", (chunk_id,))]
        return {**dict(row), "raw": raws}

    def forget(self, chunk_id: int) -> bool:
        with self._db() as c:
            removed = c.execute("DELETE FROM chunks WHERE id = ?", (chunk_id,)).rowcount
            c.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
            c.execute("DELETE FROM raw WHERE chunk_id = ?", (chunk_id,))  # forgetting means forgetting the source too
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
        started = time.perf_counter()
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
                with self.ledger.stage("retrieve.search") as st:
                    rows = c.execute(
                        "SELECT c.*, -bm25(chunks_fts) AS s FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                        "WHERE chunks_fts MATCH ? ORDER BY s DESC LIMIT 30", (match,)).fetchall()
                    st["ops"] = len(rows)
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
                    if len(picked) >= max_chunks:
                        break
                    cost = chunk_cost(r["text"])
                    if used + cost <= budget:
                        picked.append({**r, "score": round(score, 3), "tokens": cost, "why": "match", "level": "full"})
                        used += cost
                        continue
                    if r.get("gist"):  # does not fit in full: keep the idea in a few words instead of dropping it
                        short = f"{r['gist']} (#{r['id']} short)"
                        gist_cost = chunk_cost(short)
                        if gist_cost < cost and used + gist_cost <= budget:
                            picked.append({**r, "text": short, "score": round(score, 3), "tokens": gist_cost,
                                           "why": "match", "level": "gist"})
                            used += gist_cost
            if picked:
                ids = [p["id"] for p in picked]
                c.execute(f"UPDATE chunks SET uses = uses + 1, last_used = ? WHERE id IN ({','.join('?' * len(ids))})",
                          [now, *ids])
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.ledger.add("retrieve.total", elapsed_ms, tokens=used)
            if log:
                stored = c.execute(f"SELECT COALESCE(SUM({_COST}), 0) FROM chunks").fetchone()[0]
                c.execute("INSERT INTO events (ts, injected_tokens, chunks, stored_tokens, ms) VALUES (?,?,?,?,?)",
                          (now, used, len(picked), stored, elapsed_ms))
        return {"chunks": picked, "tokens": used, "budget": budget, "text": format_chunks(picked)}

    def stats(self) -> dict:
        """Counts, stored size, and how much smaller the injected memory is than loading everything."""
        with self._db() as c:
            total = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            stored = c.execute(f"SELECT COALESCE(SUM({_COST}), 0) FROM chunks").fetchone()[0]
            kinds = {r["kind"]: r["n"] for r in c.execute("SELECT kind, COUNT(*) n FROM chunks GROUP BY kind")}
            recent = c.execute(
                "SELECT injected_tokens, stored_tokens, ms FROM events ORDER BY id DESC LIMIT 200").fetchall()
            requests = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            raw_messages = c.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
        injected = sum(r["injected_tokens"] for r in recent)
        baseline = sum(r["stored_tokens"] for r in recent)
        saved = round(100 * (1 - injected / baseline), 1) if baseline > 0 else None
        return {
            "chunks": total, "stored_tokens": stored, "kinds": kinds, "requests": requests,
            "avg_injected_tokens": round(injected / len(recent), 1) if recent else None,
            "saved_percent": saved, "raw_messages": raw_messages,
            "median_ms": round(sorted(r["ms"] for r in recent)[len(recent) // 2], 2) if recent else None,
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
    one_line = lambda t: " ".join(t.split())  # a note can never start a new line, so it cannot forge a section
    parts = []
    if behavior:
        parts.append("Follow:\n" + "\n".join(f"- {one_line(t)}" for t in behavior))
    if rest:
        parts.append("Known about the user:\n" + "\n".join(f"- {one_line(t)}" for t in rest))
    return "\n".join(parts)
