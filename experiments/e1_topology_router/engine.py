"""TF-IDF retrieval, MST (H0 persistence) and the four routers. See PROTOCOL.md."""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass

from pmg.textutil import est_tokens

TOP = 50
MST_SIZES = (20, 50)


def chunk_cost(text: str) -> int:
    return est_tokens(text) + 2


class Index:
    """Sparse TF-IDF vectors with an inverted index. Cosine similarity on L2-normalised vectors."""

    def __init__(self, chunks):
        n = len(chunks)
        counts_all, df = [], defaultdict(int)
        for c in chunks:
            counts = defaultdict(int)
            for w in c.text.split():
                counts[w] += 1
            counts_all.append(counts)
            for w in counts:
                df[w] += 1
        self.idf = {w: math.log((n + 1) / (d + 1)) + 1 for w, d in df.items()}
        self.vecs, self.post = [], defaultdict(list)
        for i, counts in enumerate(counts_all):
            self.vecs.append(self._normalise({w: (1 + math.log(k)) * self.idf[w] for w, k in counts.items()}))
            for w, x in self.vecs[-1].items():
                self.post[w].append((i, x))

    @staticmethod
    def _normalise(vec):
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        return {w: x / norm for w, x in vec.items()}

    def query_vec(self, text):
        counts = defaultdict(int)
        for w in text.split():
            if w in self.idf:
                counts[w] += 1
        return self._normalise({w: (1 + math.log(k)) * self.idf[w] for w, k in counts.items()})

    def search(self, text, top=TOP):
        """Return (list of (doc_id, score) best first, number of multiply-adds)."""
        scores, ops = defaultdict(float), 0
        for w, qx in self.query_vec(text).items():
            for doc, x in self.post.get(w, ()):
                scores[doc] += qx * x
                ops += 1
        return heapq.nlargest(top, scores.items(), key=lambda kv: kv[1]), ops

    def cosine(self, i, j):
        a, b = self.vecs[i], self.vecs[j]
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(w, 0.0) for w, x in a.items())


def mst_edges(index, doc_ids):
    """Prim's algorithm on cosine distance. Returns (edges, distance_computations).

    The edge lengths are exactly the finite H0 persistence values (single-linkage merge heights)."""
    m = len(doc_ids)
    if m < 2:
        return [], 0
    in_tree, best, parent, edges, ops = [False] * m, [math.inf] * m, [-1] * m, [], 0
    best[0] = 0.0
    for _ in range(m):
        u = min((v for v in range(m) if not in_tree[v]), key=lambda v: best[v])
        in_tree[u] = True
        if parent[u] >= 0:
            edges.append((parent[u], u, best[u]))
        for v in range(m):
            if not in_tree[v]:
                d = max(0.0, 1.0 - index.cosine(doc_ids[u], doc_ids[v]))
                ops += 1
                if d < best[v]:
                    best[v], parent[v] = d, u
    return edges, ops


@dataclass
class Pre:
    """Everything a router may look at for one query, computed once."""
    group: str
    cands: list          # [(doc_id, score)] best first
    costs: list          # token cost of each candidate
    needed_flags: list   # True where the candidate is a needed chunk
    need_count: int
    mst: dict            # m -> edges among the first min(m, len(cands)) candidates
    search_ops: int
    mst_ops: dict


def precompute(gym, index, ledger):
    pres = []
    for q in gym.queries:
        with ledger.stage("search") as s:
            cands, ops = index.search(q.text)
            s["ops"] = ops
        ids = [d for d, _ in cands]
        needed = set(q.needed)
        mst, mst_ops = {}, {}
        for m in MST_SIZES:
            with ledger.stage(f"mst{m}") as s:
                mst[m], mst_ops[m] = mst_edges(index, ids[:m])
                s["ops"] = mst_ops[m]
        pres.append(Pre(q.group, cands, [chunk_cost(gym.chunks[d].text) for d in ids],
                        [d in needed for d in ids], len(needed), mst, ops, mst_ops))
    return pres


# ---------------------------------------------------------------- routers (return candidate positions)

def route_p0(p, k):
    return list(range(min(k, len(p.cands))))


def route_p1(p, floor, margin, k_fallback):
    if not p.cands or p.cands[0][1] < floor:
        return []
    s1 = p.cands[0][1]
    s2 = p.cands[1][1] if len(p.cands) > 1 else 0.0
    if (s1 - s2) / s1 >= margin:
        return [0]
    return list(range(min(k_fallback, len(p.cands))))


def route_p1b(p, floor, beta, k_max):
    if not p.cands or p.cands[0][1] < floor:
        return []
    s1 = p.cands[0][1]
    return [i for i in range(min(k_max, len(p.cands))) if p.cands[i][1] >= beta * s1]


def clusters(p, m, gap):
    """Single-linkage clusters of the top-m candidates: cut MST edges longer than `gap`."""
    size = min(m, len(p.cands))
    parent = list(range(size))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j, d in p.mst[m]:
        if d <= gap:
            parent[find(i)] = find(j)
    groups = defaultdict(list)
    for pos in range(size):
        groups[find(pos)].append(pos)
    return list(groups.values())


def route_p2(p, floor, m, gap, alpha, beta, cap):
    if not p.cands or p.cands[0][1] < floor:
        return []
    s1, out = p.cands[0][1], []
    for members in clusters(p, m, gap):
        best = p.cands[members[0]][1]  # members are in score order
        if best >= alpha * s1:
            out += [pos for pos in members if p.cands[pos][1] >= beta * best][:cap]
    return out


ROUTERS = {"P0": route_p0, "P1": route_p1, "P1b": route_p1b, "P2": route_p2}
PARAM_NAMES = {
    "P0": ("k",),
    "P1": ("floor", "margin", "k_fallback"),
    "P1b": ("floor", "beta", "k_max"),
    "P2": ("floor", "m", "gap", "alpha", "beta", "cap"),
}


def run_router(name, cfg, pres):
    """Per-query (tokens, recall or None, wasted_tokens) for one configuration."""
    fn, args = ROUTERS[name], [cfg[k] for k in PARAM_NAMES[name]]
    tokens, recalls, waste = [], [], []
    for p in pres:
        chosen = fn(p, *args)
        t = sum(p.costs[i] for i in chosen)
        tokens.append(t)
        if p.need_count:
            recalls.append(sum(p.needed_flags[i] for i in chosen) / p.need_count)
        else:
            recalls.append(None)
        waste.append(sum(p.costs[i] for i in chosen if not p.needed_flags[i]))
    return tokens, recalls, waste
