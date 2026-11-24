"""Dense vectors, SimHash fingerprints, exact brute force and the cascade. See PROTOCOL.md."""
from __future__ import annotations

import math
import time
from collections import Counter

import numpy as np

DIM = 256
K = 10


class Store:
    """Dense random projection of TF-IDF vectors, L2-normalised, float32."""

    def __init__(self, chunks, seed: int = 0, dim: int = DIM):
        rng = np.random.default_rng(seed)
        docs = [c.text.split() for c in chunks]
        df = Counter(w for d in docs for w in set(d))
        self.vocab = {w: i for i, w in enumerate(df)}
        n = len(docs)
        self.idf = np.array([math.log((n + 1) / (df[w] + 1)) + 1 for w in self.vocab], dtype=np.float32)
        self.proj = rng.standard_normal((len(self.vocab), dim)).astype(np.float32)
        self.dim = dim
        self.vecs = np.stack([self._embed(d) for d in docs])

    def _embed(self, words):
        counts = Counter(w for w in words if w in self.vocab)
        if not counts:
            return np.zeros(self.dim, dtype=np.float32)
        ids = np.fromiter((self.vocab[w] for w in counts), dtype=np.int64, count=len(counts))
        tf = np.fromiter((1 + math.log(c) for c in counts.values()), dtype=np.float32, count=len(counts))
        v = (tf * self.idf[ids]) @ self.proj[ids]
        norm = float(np.linalg.norm(v))
        return v / norm if norm else v

    def embed_query(self, text):
        return self._embed(text.split())


class Fingerprints:
    """Random-hyperplane signs packed into uint64 words (bits must be a multiple of 64)."""

    def __init__(self, store: Store, bits: int, seed: int = 1):
        assert bits % 64 == 0
        self.bits = bits
        self.planes = np.random.default_rng(seed).standard_normal((store.dim, bits)).astype(np.float32)
        self.codes = self.sign(store.vecs)

    def sign(self, x):
        packed = np.packbits((x @ self.planes) > 0, axis=-1)          # (..., bits/8) uint8
        return np.ascontiguousarray(packed).view(np.uint64)           # (..., bits/64)


def exact_top(store: Store, q, k: int = K):
    s = store.vecs @ q
    idx = np.argpartition(s, -k)[-k:]
    return idx[np.argsort(-s[idx])]


def cascade_top(store: Store, fp: Fingerprints, q, shortlist: int, k: int = K):
    code = fp.sign(q[None, :])[0]
    ham = np.bitwise_count(fp.codes ^ code).sum(axis=1)
    r = min(shortlist, len(ham))
    cand = np.argpartition(ham, r - 1)[:r] if r < len(ham) else np.arange(len(ham))
    s = store.vecs[cand] @ q
    top = np.argsort(-s)[:k]
    return cand[top]


def bytes_exact(n: int, dim: int = DIM) -> int:
    return n * dim * 4


def bytes_cascade(n: int, bits: int, shortlist: int, dim: int = DIM) -> int:
    return n * bits // 8 + min(shortlist, n) * dim * 4


def timed(fn, *args):
    t = time.perf_counter_ns()
    out = fn(*args)
    return out, (time.perf_counter_ns() - t) / 1e6
