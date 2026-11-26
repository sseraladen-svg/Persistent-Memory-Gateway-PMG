"""`pmg bench`: measure how much memory PMG loads, and whether it still finds what a question needs, on real data.

Input is a JSON file in one of three formats:
  generic       {"cases": [{"messages": ["...", ...], "questions": [{"q": "...", "needed": [3, 7]}]}]}
                (a question may give "answers": ["text", ...] instead of "needed"; set "abstain": true for
                a question that has no answer in the messages, where the right amount to load is nothing)
  locomo        the LoCoMo file (locomo10.json): evidence turns are the needed messages
  longmemeval   a LongMemEval file: turns marked has_answer are the needed messages; ids ending in _abs are abstain

Every message becomes one chunk (this measures retrieval, not the classifier). Policies are compared on the same
matches, so the differences come only from how many chunks each one loads.
"""
from __future__ import annotations

import json
import os
import statistics
import tempfile
import time
from typing import Iterable, Optional

from .store import Memory, chunk_cost
from .textutil import normalize, unique_keywords

TOP_K = (1, 3, 5, 10, 20)
BETAS = (0.3, 0.5, 0.7)
POOL = 50
MAX_CUTOFF_CHUNKS = 20


# ------------------------------------------------------------------ dataset adapters
def from_generic(data: dict) -> list[dict]:
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError('generic format needs a top-level "cases" list')
    return cases


def _answers(value) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [str(a) for a in items if a is not None and str(a).strip()]


def from_locomo(data: list) -> list[dict]:
    cases = []
    for sample in data:
        conv, messages, index = sample.get("conversation", {}), [], {}
        sessions = sorted((k for k in conv if k.startswith("session_") and isinstance(conv[k], list)),
                          key=lambda k: int(k.split("_")[1]) if k.split("_")[1].isdigit() else 0)
        for key in sessions:
            for turn in conv[key]:
                text = str(turn.get("text", "")).strip()
                if text:
                    index[turn.get("dia_id")] = len(messages)
                    messages.append(f"{turn.get('speaker', '')}: {text}")
        questions, skipped = [], 0
        for qa in sample.get("qa", []):
            ids = [i.strip() for e in qa.get("evidence", []) for i in str(e).replace(";", " ").split()]
            needed = sorted({index[i] for i in ids if i in index})
            if not needed:
                skipped += 1  # unanswerable category or evidence we cannot map
                continue
            questions.append({"q": qa["question"], "needed": needed, "answers": _answers(qa.get("answer"))})
        cases.append({"messages": messages, "questions": questions, "skipped": skipped})
    return cases


def from_longmemeval(data: list) -> list[dict]:
    cases = []
    for item in data:
        messages, needed = [], []
        for session in item.get("haystack_sessions", []):
            for turn in session:
                if turn.get("has_answer"):
                    needed.append(len(messages))
                messages.append(f"{turn.get('role', '')}: {turn.get('content', '')}".strip())
        abstain = str(item.get("question_id", "")).endswith("_abs")
        if not needed and not abstain:
            continue
        cases.append({"messages": messages, "questions": [
            {"q": item["question"], "needed": [], "abstain": True} if abstain
            else {"q": item["question"], "needed": needed, "answers": _answers(item.get("answer"))}]})
    return cases


def load_dataset(path: str, fmt: str = "auto") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if fmt == "auto":
        if isinstance(data, dict) and "cases" in data:
            fmt = "generic"
        elif isinstance(data, list) and data and "conversation" in data[0]:
            fmt = "locomo"
        elif isinstance(data, list) and data and "haystack_sessions" in data[0]:
            fmt = "longmemeval"
        else:
            raise ValueError("Could not tell the file format; pass --format generic|locomo|longmemeval")
    return {"generic": from_generic, "locomo": from_locomo, "longmemeval": from_longmemeval}[fmt](data)


# ------------------------------------------------------------------ policies
def _fixed(k):
    return lambda cands: cands[:k]


def _cutoff(beta):
    def pick(cands):
        if not cands:
            return []
        floor = beta * cands[0][2]
        return [c for c in cands if c[2] >= floor][:MAX_CUTOFF_CHUNKS]
    return pick


POLICIES = {**{f"top-{k}": _fixed(k) for k in TOP_K}, **{f"cutoff {b}": _cutoff(b) for b in BETAS}}


def _build_store(messages: Iterable[str], directory: str) -> Memory:
    os.environ["PMG_DATA"] = directory
    m = Memory()
    now = time.time()
    with m._db() as c:  # one chunk per message, in order, so chunk id = message index + 1
        for i, text in enumerate(messages):
            norm = f"{i}:{normalize(text)}"  # unique per message, so repeated messages still get their own chunk
            cur = c.execute("INSERT INTO chunks (kind,text,norm,tags,created_at,updated_at) VALUES ('fact',?,?,?,?,?)",
                            (text, norm, " ".join(unique_keywords(text, 6)), now, now))
            c.execute("INSERT INTO chunks_fts(rowid,text,tags) VALUES (?,?,?)", (cur.lastrowid, text, ""))
    return m


def _recall(q: dict, loaded_ids: set, loaded_text: str) -> Optional[float]:
    if q.get("needed"):
        return sum((n + 1) in loaded_ids for n in q["needed"]) / len(q["needed"])
    if q.get("answers"):
        low = loaded_text.lower()
        return 1.0 if any(str(a).lower() in low for a in q["answers"]) else 0.0
    return None


EMB_K, EMB_MARGINS, HYBRID_K, RRF_K = (1, 3, 5, 10, 20), (0.05, 0.10, 0.15), (3, 5, 10), 60


def _emb_policies(order, scores):
    """Embedding and hybrid choices from an embedding ranking (`order`, `scores`) and the keyword candidates."""
    top = scores[order[0]] if len(order) else 0.0
    out = {f"emb top-{k}": [int(i) + 1 for i in order[:k]] for k in EMB_K}
    for d in EMB_MARGINS:
        out[f"emb margin {d}"] = [int(i) + 1 for i in order if scores[i] >= top - d][:MAX_CUTOFF_CHUNKS]
    return out


def _hybrid(order, cands):
    """Reciprocal rank fusion of the embedding ranking and the keyword ranking (ids are chunk ids)."""
    fused = {}
    for rank, i in enumerate(order[:POOL]):
        fused[int(i) + 1] = fused.get(int(i) + 1, 0.0) + 1.0 / (RRF_K + rank)
    for rank, (cid, _, _) in enumerate(cands):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    ranked = sorted(fused, key=lambda c: -fused[c])
    out = {f"hybrid top-{k}": ranked[:k] for k in HYBRID_K}
    top = fused[ranked[0]] if ranked else 0.0
    out["hybrid cutoff 0.6"] = [c for c in ranked if fused[c] >= 0.6 * top][:MAX_CUTOFF_CHUNKS]
    return out


def run(cases: list[dict], limit_questions: int = 0, embedder=None, ann: bool = False) -> dict:
    names = [*POLICIES, "product (budget 400)"]
    if embedder:
        names += [*(f"emb top-{k}" for k in EMB_K), *(f"emb margin {d}" for d in EMB_MARGINS),
                  *(f"hybrid top-{k}" for k in HYBRID_K), "hybrid cutoff 0.6"]
    pooled_vectors, pooled_queries = [], []
    acc = {n: {"tokens": [], "recall": [], "ms": [], "abstain_tokens": []} for n in names}
    full_tokens, asked = [], 0
    for case in cases:
        messages = case["messages"]
        full = sum(chunk_cost(t) for t in messages)
        with tempfile.TemporaryDirectory(prefix="pmg-bench-") as d:
            saved = os.environ.get("PMG_DATA")
            try:
                m = _build_store(messages, d)
                if embedder:
                    vectors = embedder(messages)
                    texts_by_id = {i + 1: t for i, t in enumerate(messages)}
                    pooled_vectors.append(vectors)
                for q in case["questions"]:
                    if limit_questions and asked >= limit_questions:
                        break
                    asked += 1
                    full_tokens.append(full)
                    t = time.perf_counter()
                    cands = m.candidates(q["q"], POOL)
                    search_ms = (time.perf_counter() - t) * 1000
                    for name, pick in POLICIES.items():
                        t = time.perf_counter()
                        chosen = pick(cands)
                        ms = search_ms + (time.perf_counter() - t) * 1000
                        _record(acc[name], q, {c[0] for c in chosen}, " ".join(c[1] for c in chosen),
                                sum(chunk_cost(c[1]) for c in chosen), ms)
                    if embedder:
                        import numpy as np
                        t = time.perf_counter()
                        qv = embedder([q["q"]])[0]
                        scores = vectors @ qv
                        order = np.argsort(-scores)[:POOL]
                        emb_ms = (time.perf_counter() - t) * 1000
                        pooled_queries.append(qv)
                        chosen = {**_emb_policies(order, scores), **_hybrid(order, cands)}
                        for name, ids in chosen.items():
                            _record(acc[name], q, set(ids), " ".join(texts_by_id[i] for i in ids),
                                    sum(chunk_cost(texts_by_id[i]) for i in ids), emb_ms + search_ms)
                    t = time.perf_counter()
                    r = m.retrieve(q["q"], log=False)
                    ms = (time.perf_counter() - t) * 1000
                    _record(acc["product (budget 400)"], q, {c["id"] for c in r["chunks"]},
                            " ".join(c["text"] for c in r["chunks"]), r["tokens"], ms)
            finally:
                if saved is None:
                    os.environ.pop("PMG_DATA", None)
                else:
                    os.environ["PMG_DATA"] = saved
        if limit_questions and asked >= limit_questions:
            break
    mean_full = statistics.mean(full_tokens) if full_tokens else 0
    rows = []
    for name, a in acc.items():
        if not a["tokens"]:
            continue
        rec = [r for r in a["recall"] if r is not None]
        rows.append({
            "policy": name, "mean_tokens": statistics.mean(a["tokens"]),
            "recall": statistics.mean(rec) if rec else None,
            "percent_of_full_history": 100 * statistics.mean(a["tokens"]) / mean_full if mean_full else None,
            "median_ms": statistics.median(a["ms"]),
            "mean_tokens_on_unanswerable": statistics.mean(a["abstain_tokens"]) if a["abstain_tokens"] else None,
        })
    report = {"questions": asked, "mean_full_history_tokens": mean_full, "rows": rows}
    if embedder and ann and pooled_vectors:
        import numpy as np
        from .ann import ivf_report
        report["ann"] = ivf_report(np.concatenate(pooled_vectors), np.stack(pooled_queries))
    return report


def _record(slot, q, ids, text, tokens, ms):
    slot["tokens"].append(tokens)
    slot["ms"].append(ms)
    slot["recall"].append(_recall(q, ids, text))
    if q.get("abstain"):
        slot["abstain_tokens"].append(tokens)


def format_report(rep: dict) -> str:
    out = [f"{rep['questions']} questions; loading the whole history would cost about "
           f"{rep['mean_full_history_tokens']:.0f} tokens per question.", "",
           f"{'policy':<22}{'tokens':>8}{'% of full':>11}{'recall':>9}{'ms':>8}{'tokens if unanswerable':>25}"]
    for r in rep["rows"]:
        rec = "-" if r["recall"] is None else f"{r['recall']:.3f}"
        un = "-" if r["mean_tokens_on_unanswerable"] is None else f"{r['mean_tokens_on_unanswerable']:.0f}"
        out.append(f"{r['policy']:<22}{r['mean_tokens']:>8.0f}{r['percent_of_full_history']:>10.1f}%{rec:>9}"
                   f"{r['median_ms']:>8.2f}{un:>25}")
    if rep.get("ann"):
        out += ["", "IVF index versus exact search over all pooled vectors (top-10):",
                f"{'nprobe':>8}{'nlist':>8}{'overlap@10':>13}{'scanned':>10}"]
        out += [f"{a['nprobe']:>8}{a['nlist']:>8}{a['overlap_at_k']:>13.3f}{a['scanned_fraction']:>9.1%}" for a in rep["ann"]]
    out += ["", "Recall is the share of needed messages that were loaded. 'emb' and 'hybrid' rows exist only when "
                "--embeddings is given; everything else is keyword search."]
    return "\n".join(out)
