import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import redis

DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)

SYSTEM = (
    "You are JARVIS, a personal AI assistant. Be concise and helpful. "
    "Follow all learned facts and behavior rules below. Keep replies short unless asked for detail."
)

LEARN_TRIGGERS = (
    "remember", "don't forget", "keep in mind", "learn this", "save this",
    "my name is", "call me", "i am ", "i'm ", "i work", "i live in", "i study",
    "act like", "behave like", "respond like", "talk like", "speak like",
    "from now on", "always ", "never ", "i prefer", "i like", "i hate",
    "my favorite", "about me", "i'm from", "my age", "my birthday",
)

BEHAVIOR_TRIGGERS = (
    "act like", "behave", "from now on", "always ", "never ", "respond like",
    "talk like", "speak like", "be more", "be less", "don't be",
)

PROFILE_TRIGGERS = (
    "my name is", "call me", "i am ", "i'm ", "i work", "i live", "i study",
    "about me", "i'm from", "my age", "my birthday", "my job",
)

_chroma = None
_chroma_lock = threading.Lock()
_redis_client = None
_redis_mode = "embedded"


def _get_redis():
    global _redis_client, _redis_mode
    if _redis_client is not None:
        return _redis_client

    import fakeredis

    box = [fakeredis.FakeRedis(decode_responses=True)]
    mode = ["embedded"]

    def _try_local():
        try:
            r = redis.Redis(host="localhost", port=6379, decode_responses=True)
            r.ping()
            box[0] = r
            mode[0] = "local"
        except (redis.ConnectionError, redis.TimeoutError, OSError):
            pass

    t = threading.Thread(target=_try_local, daemon=True)
    t.start()
    t.join(timeout=0.4)

    _redis_client = box[0]
    _redis_mode = mode[0]
    return _redis_client

_db_path = DATA / "jarvis.db"


def _db():
    conn = sqlite3.connect(_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

        CREATE TABLE IF NOT EXISTS learned (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            content TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_learned_category ON learned(category);
        """
    )
    return conn


def _get_chroma():
    global _chroma
    if _chroma is not None:
        return _chroma
    with _chroma_lock:
        if _chroma is None:
            import chromadb

            client = chromadb.PersistentClient(path=str(DATA / "chroma"))
            _chroma = client.get_or_create_collection("jarvis_memory")
    return _chroma


def _invalidate_learned_cache():
    _get_redis().delete("learned:context")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def should_learn(text: str) -> bool:
    t = text.lower()
    if re.match(r"^remember[\s:,]+", t) or re.match(r"^remember that ", t):
        return True
    return any(k in t for k in LEARN_TRIGGERS)


def _category(text: str) -> str:
    t = text.lower()
    if any(k in t for k in BEHAVIOR_TRIGGERS):
        return "behavior"
    if any(k in t for k in PROFILE_TRIGGERS):
        return "profile"
    return "fact"


def _extract_fact(text: str) -> str:
    t = text.strip()
    for pat in (
        r"^remember[\s:,]+(.+)",
        r"^remember that (.+)",
        r"^keep in mind[\s:,]+(.+)",
        r"^don't forget[\s:,]+(.+)",
        r"^learn this[\s:,]+(.+)",
        r"^save this[\s:,]+(.+)",
    ):
        m = re.match(pat, t, re.I)
        if m:
            return m.group(1).strip()
    return t


def learn_from_message(text: str) -> str | None:
    """Fast SQLite-only save. ChromaDB indexes in background."""
    if not should_learn(text):
        return None
    fact = _extract_fact(text)
    if len(fact) < 3:
        return None
    category = _category(text)
    with _db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM learned WHERE content = ? OR lower(content) = ?",
            (fact, _normalize(fact)),
        ).fetchone()
        if exists:
            return category
        conn.execute(
            "INSERT INTO learned (category, content, created_at) VALUES (?, ?, ?)",
            (category, fact, time.time()),
        )
    _invalidate_learned_cache()
    threading.Thread(target=_index_chroma, args=(fact, category), daemon=True).start()
    return category


def _index_chroma(fact: str, category: str):
    try:
        _get_chroma().add(
            ids=[str(uuid.uuid4())],
            documents=[fact],
            metadatas=[{"category": category, "permanent": True}],
        )
    except Exception:
        pass


def get_learned_context() -> str:
    r = _get_redis()
    cached = r.get("learned:context")
    if cached is not None:
        return cached
    with _db() as conn:
        rows = conn.execute(
            "SELECT category, content FROM learned ORDER BY created_at"
        ).fetchall()
    if not rows:
        r.setex("learned:context", 300, "")
        return ""
    profiles, behaviors, facts = [], [], []
    for row in rows:
        bucket = {"profile": profiles, "behavior": behaviors, "fact": facts}.get(row["category"], facts)
        bucket.append(row["content"])
    parts = []
    if profiles:
        parts.append("About the user:\n" + "\n".join(f"- {p}" for p in profiles))
    if behaviors:
        parts.append("How you must behave:\n" + "\n".join(f"- {b}" for b in behaviors))
    if facts:
        parts.append("Permanent facts:\n" + "\n".join(f"- {f}" for f in facts))
    ctx = "\n\n".join(parts)
    if len(ctx) > 1500:
        ctx = ctx[:1500] + "\n...(truncated)"
    r.setex("learned:context", 300, ctx)
    return ctx


def get_learned_facts():
    with _db() as conn:
        return [
            {"category": r["category"], "content": r["content"], "created_at": r["created_at"]}
            for r in conn.execute(
                "SELECT category, content, created_at FROM learned ORDER BY created_at DESC"
            )
        ]


def save_message(session_id: str, role: str, content: str):
    with _db() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, time.time()),
        )


def get_history(session_id: str, limit: int = 6):
    with _db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def cache_session(session_id: str, messages: list):
    _get_redis().setex(f"session:{session_id}", 3600, json.dumps(messages[-6:]))


def status():
    with _db() as conn:
        msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        learned_count = conn.execute("SELECT COUNT(*) FROM learned").fetchone()[0]
    return {
        "sqlite": {"ok": True, "messages": msg_count, "learned": learned_count},
        "chromadb": {"ok": True, "memories": learned_count},
        "redis": {"ok": True, "mode": _redis_mode if _redis_client else "embedded"},
    }
