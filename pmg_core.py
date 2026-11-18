"""PMG core: a small, model-agnostic memory layer.

Stores information as tiny chunks in SQLite (FTS5 index) and loads only the
chunks that match the current input, inside a hard token budget.

The LLM is NOT a chatbot here. It is optional and used offline for two jobs:
  1. classify(): decide whether a message is worth storing and how.
  2. propose_rules(): suggest better rules/storage settings from stored data.
Without an LLM, the rule-based classifier in rules.json is used.
"""
import contextlib
import json
import os
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get("PMG_DATA", ROOT / "data"))
RULES_PATH = Path(os.environ.get("PMG_RULES", ROOT / "rules.json"))

STOPWORDS = set(
    "the a an and or but if then of to in on at for with from by is are was were be been "
    "am do does did have has had i me my you your we our it its this that these those "
    "what which who how when where why can could should would will just about into over "
    "not no yes so as than too very".split()
)

ALLOWED_RULE_KEYS = {"budget_tokens", "always_load_share", "max_chunks", "min_chars"}


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _words(text: str):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS]


def load_rules() -> dict:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- classify

def _extract_fact(text: str) -> str:
    t = text.strip()
    m = re.match(r"^(?:please\s+)?(?:remember|don't forget|keep in mind|learn this|save this)(?:\s+that)?[\s:,]+(.+)", t, re.I | re.S)
    return m.group(1).strip() if m else t


def classify_rules(text: str, rules: dict) -> dict:
    """Cheap keyword classifier. Returns {store, kind, text, tags, importance, key}."""
    no = {"store": False}
    t = text.strip()
    if len(t) < rules.get("min_chars", 3):
        return no
    for pat in rules.get("never_store_patterns", []):
        if re.search(pat, t):
            return no
    low = t.lower()
    for kind, spec in rules["kinds"].items():
        if any(trig in low for trig in spec["triggers"]):
            fact = _extract_fact(t)
            if len(fact) < rules.get("min_chars", 3):
                return no
            tags = " ".join(list(dict.fromkeys(_words(fact)))[:6])
            return {"store": True, "kind": kind, "text": fact, "tags": tags, "importance": 3, "key": None}
    return no


CLASSIFY_PROMPT = """You classify one user message for a long-term memory store.
Reply with ONLY a JSON object, no prose:
{{"store": true|false, "kind": "<one of {kinds}>", "text": "<short, self-contained rewrite, max 25 words>",
 "tags": "<up to 6 lowercase keywords, space separated>", "importance": 1-5,
 "key": "<stable slot name like user.city if this replaces an older fact, else null>"}}
Store only durable facts, preferences or behavior instructions. Never store secrets, credentials or card numbers.
Message: {message}"""


def classify_llm(text: str, rules: dict, complete) -> dict:
    """complete(prompt)->str. Falls back to rules on any problem; output is validated."""
    fallback = classify_rules(text, rules)
    try:
        raw = complete(CLASSIFY_PROMPT.format(kinds="/".join(rules["kinds"]), message=text[:1500]))
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0))
        if not data.get("store"):
            return {"store": False}
        kind = data.get("kind")
        body = str(data.get("text", "")).strip()
        if kind not in rules["kinds"] or len(body) < rules.get("min_chars", 3) or len(body) > 400:
            return fallback
        for pat in rules.get("never_store_patterns", []):
            if re.search(pat, body) or re.search(pat, text):
                return {"store": False}
        imp = max(1, min(5, int(data.get("importance", 3))))
        key = data.get("key") if isinstance(data.get("key"), str) and re.fullmatch(r"[a-z0-9_.]{1,40}", data["key"]) else None
        tags = " ".join(_words(str(data.get("tags", "")))[:6])
        return {"store": True, "kind": kind, "text": body, "tags": tags, "importance": imp, "key": key}
    except Exception:
        return fallback


def llm_from_env():
    """Optional offline classifier via any OpenAI-compatible endpoint (Ollama, OpenRouter, ...).
    Set PMG_LLM_BASE_URL and PMG_LLM_MODEL (and PMG_LLM_KEY if needed). Returns None if unset."""
    base, model = os.environ.get("PMG_LLM_BASE_URL"), os.environ.get("PMG_LLM_MODEL")
    if not base or not model:
        return None
    key = os.environ.get("PMG_LLM_KEY", "")

    def complete(prompt: str) -> str:
        body = json.dumps({"model": model, "temperature": 0, "max_tokens": 300,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body,
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {key}"} if key else {})})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["choices"][0]["message"]["content"]

    return complete


# ------------------------------------------------------------------- store

class Memory:
    def __init__(self, db_path=None):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path or DATA_DIR / "pmg.db")
        with self._db() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL, text TEXT NOT NULL, norm TEXT NOT NULL UNIQUE,
                    tags TEXT NOT NULL DEFAULT '', key TEXT, importance INTEGER NOT NULL DEFAULT 3,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    last_used REAL, uses INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_key ON chunks(key) WHERE key IS NOT NULL;
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tags);
                """
            )

    @contextlib.contextmanager
    def _db(self):
        """Open, commit-on-success / rollback-on-error, and always close."""
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            with c:
                yield c
        finally:
            c.close()

    # -- write
    def add(self, kind: str, text: str, tags: str = "", importance: int = 3, key=None) -> int:
        now, norm = time.time(), _norm(text)
        tags = tags or " ".join(list(dict.fromkeys(_words(text)))[:6])
        with self._db() as c:
            row = c.execute("SELECT id FROM chunks WHERE norm = ?", (norm,)).fetchone()
            if row:  # duplicate: just refresh
                c.execute("UPDATE chunks SET updated_at=? WHERE id=?", (now, row["id"]))
                return row["id"]
            if key:
                row = c.execute("SELECT id FROM chunks WHERE key = ?", (key,)).fetchone()
                if row:  # same slot: replace old value
                    c.execute("UPDATE chunks SET kind=?, text=?, norm=?, tags=?, importance=?, updated_at=? WHERE id=?",
                              (kind, text, norm, tags, importance, now, row["id"]))
                    c.execute("DELETE FROM chunks_fts WHERE rowid=?", (row["id"],))
                    c.execute("INSERT INTO chunks_fts(rowid, text, tags) VALUES (?,?,?)", (row["id"], text, tags))
                    return row["id"]
            cur = c.execute(
                "INSERT INTO chunks (kind,text,norm,tags,key,importance,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (kind, text, norm, tags, key, importance, now, now))
            c.execute("INSERT INTO chunks_fts(rowid, text, tags) VALUES (?,?,?)", (cur.lastrowid, text, tags))
            return cur.lastrowid

    def ingest(self, text: str, complete=None):
        """Classify a raw message and store it if worth keeping. Returns chunk id or None."""
        rules = load_rules()
        verdict = classify_llm(text, rules, complete) if complete else classify_rules(text, rules)
        if not verdict.get("store"):
            return None
        return self.add(verdict["kind"], verdict["text"], verdict["tags"], verdict["importance"], verdict["key"])

    def forget(self, chunk_id: int) -> bool:
        with self._db() as c:
            n = c.execute("DELETE FROM chunks WHERE id=?", (chunk_id,)).rowcount
            c.execute("DELETE FROM chunks_fts WHERE rowid=?", (chunk_id,))
        return n > 0

    def list(self, limit: int = 50):
        with self._db() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, kind, text, tags, key, importance, uses FROM chunks ORDER BY updated_at DESC LIMIT ?", (limit,))]

    # -- read
    def retrieve(self, query: str, budget_tokens: int = 0) -> dict:
        """Pick the chunks to inject for this query, inside a token budget.
        Order: always-load kinds (rules of behavior) first, then FTS5/BM25 matches
        weighted by kind weight, recency decay and importance."""
        rules = load_rules()
        budget = budget_tokens or rules["budget_tokens"]
        max_chunks = rules["max_chunks"]
        always_cap = int(budget * rules["always_load_share"])
        now, picked, used = time.time(), [], 0
        with self._db() as c:
            always_kinds = [k for k, s in rules["kinds"].items() if s.get("always_load")]
            if always_kinds:
                q = ",".join("?" * len(always_kinds))
                for r in c.execute(f"SELECT * FROM chunks WHERE kind IN ({q}) ORDER BY importance DESC, updated_at DESC", always_kinds):
                    cost = est_tokens(r["text"]) + 2
                    if used + cost <= always_cap and len(picked) < max_chunks:
                        picked.append(dict(r)); used += cost
            words = _words(query)
            if words:
                match = " OR ".join(f'"{w}"' for w in dict.fromkeys(words))
                have = {p["id"] for p in picked}
                rows = c.execute(
                    "SELECT c.*, -bm25(chunks_fts) AS s FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                    "WHERE chunks_fts MATCH ? ORDER BY s DESC LIMIT 30", (match,)).fetchall()
                scored = []
                for r in rows:
                    if r["id"] in have:
                        continue
                    spec = rules["kinds"].get(r["kind"], {})
                    hl = spec.get("half_life_days")
                    decay = 0.5 ** (((now - r["updated_at"]) / 86400) / hl) if hl else 1.0
                    scored.append((r["s"] * spec.get("weight", 1.0) * decay * (1 + 0.1 * r["importance"]), dict(r)))
                for _, r in sorted(scored, key=lambda x: -x[0]):
                    cost = est_tokens(r["text"]) + 2
                    if used + cost <= budget and len(picked) < max_chunks:
                        picked.append(r); used += cost
            if picked:
                ids = [p["id"] for p in picked]
                c.execute(f"UPDATE chunks SET uses = uses + 1, last_used = ? WHERE id IN ({','.join('?' * len(ids))})", [now, *ids])
        return {"chunks": picked, "tokens": used, "text": format_chunks(picked)}

    # -- self-tuning
    def propose_rules(self, complete) -> dict:
        """Ask the LLM to suggest numeric rule settings from usage stats. Validated, never applied here."""
        rules = load_rules()
        with self._db() as c:
            stats = [dict(r) for r in c.execute(
                "SELECT kind, COUNT(*) n, ROUND(AVG(uses),2) avg_uses, ROUND(AVG(LENGTH(text)),1) avg_len FROM chunks GROUP BY kind")]
        prompt = ("You tune a memory layer. Current settings: "
                  + json.dumps({k: rules[k] for k in ALLOWED_RULE_KEYS})
                  + f" Per-kind stats: {json.dumps(stats)}. "
                  "Goal: fewest tokens injected per request while keeping useful chunks. "
                  "Reply ONLY with JSON containing any of these keys you want to change "
                  "(budget_tokens 100-2000, always_load_share 0-0.8, max_chunks 1-20, min_chars 2-10) plus a 'why' string.")
        raw = complete(prompt)
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        limits = {"budget_tokens": (100, 2000), "always_load_share": (0, 0.8), "max_chunks": (1, 20), "min_chars": (2, 10)}
        out = {k: v for k, v in data.items() if k in limits and isinstance(v, (int, float)) and limits[k][0] <= v <= limits[k][1]}
        out["why"] = str(data.get("why", ""))[:300]
        return out

    @staticmethod
    def apply_rules(changes: dict):
        rules = load_rules()
        for k, v in changes.items():
            if k in ALLOWED_RULE_KEYS:
                rules[k] = v
        RULES_PATH.write_text(json.dumps(rules, indent=2), encoding="utf-8")


def format_chunks(chunks) -> str:
    if not chunks:
        return ""
    beh = [c["text"] for c in chunks if c["kind"] == "behavior"]
    rest = [c["text"] for c in chunks if c["kind"] != "behavior"]
    parts = []
    if beh:
        parts.append("Follow:\n" + "\n".join(f"- {t}" for t in beh))
    if rest:
        parts.append("Known about the user:\n" + "\n".join(f"- {t}" for t in rest))
    return "\n".join(parts)
