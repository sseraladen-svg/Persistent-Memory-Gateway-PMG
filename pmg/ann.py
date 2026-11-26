"""E5 check: how much of the exact nearest-neighbour answer does a simple IVF index keep, and how much does it scan?

IVF = k-means clusters; a query is compared with the cluster centres, then only with the vectors in its `nprobe`
nearest clusters. Vectors must be unit length. Needs numpy.
"""
from __future__ import annotations

import math


def build_ivf(vectors, nlist: int | None = None, iters: int = 8, seed: int = 0):
    import numpy as np
    n = len(vectors)
    nlist = nlist or max(1, int(math.sqrt(n)))
    rng = np.random.default_rng(seed)
    centres = vectors[rng.choice(n, size=nlist, replace=False)].copy()
    for _ in range(iters):
        assign = np.argmax(vectors @ centres.T, axis=1)
        for j in range(nlist):
            members = vectors[assign == j]
            if len(members):
                c = members.mean(axis=0)
                centres[j] = c / (np.linalg.norm(c) or 1)
    assign = np.argmax(vectors @ centres.T, axis=1)
    return centres, [np.where(assign == j)[0] for j in range(nlist)]


def search_ivf(vectors, centres, lists, q, nprobe: int, k: int = 10):
    """(top-k ids, number of vectors compared including the centres)."""
    import numpy as np
    order = np.argsort(-(centres @ q))[:nprobe]
    ids = np.concatenate([lists[j] for j in order]) if len(order) else np.array([], dtype=int)
    if not len(ids):
        return [], len(centres)
    s = vectors[ids] @ q
    top = ids[np.argsort(-s)[:k]]
    return top.tolist(), len(centres) + len(ids)


def ivf_report(vectors, queries, nprobes=(1, 2, 4, 8, 16, 32), k: int = 10) -> list[dict]:
    import numpy as np
    centres, lists = build_ivf(vectors)
    n, rows = len(vectors), []
    exact = [set(np.argsort(-(vectors @ q))[:k].tolist()) for q in queries]
    for p in nprobes:
        p = min(p, len(lists))
        overlaps, scanned = [], []
        for q, ex in zip(queries, exact):
            got, cost = search_ivf(vectors, centres, lists, q, p, k)
            overlaps.append(len(ex & set(got)) / max(1, len(ex)))
            scanned.append(cost / n)
        rows.append({"nprobe": p, "nlist": len(lists), "overlap_at_k": float(np.mean(overlaps)),
                     "scanned_fraction": float(np.mean(scanned))})
    return rows
