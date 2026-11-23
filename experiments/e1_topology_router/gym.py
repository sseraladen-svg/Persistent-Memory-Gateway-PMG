"""Synthetic memory gym with known ground truth. See PROTOCOL.md.

Every chunk belongs to one topic. Queries come in four types:
  A  one specific fact              needs 1 chunk
  B  broad question about a topic   needs the 3 key chunks of that topic
  C  facts from 2 or 3 topics       needs 1 chunk per topic (kinds C2, C3)
  D  vague, no needed chunk         the right action is to inject nothing
"""
from __future__ import annotations

import random
from dataclasses import dataclass

N_COMMON = 300
TOPIC_WORDS = 60
MIX = (("A", 0.35), ("B", 0.20), ("C2", 0.25), ("C3", 0.10), ("D", 0.10))


@dataclass(frozen=True)
class Chunk:
    id: int
    topic: int
    text: str
    facts: tuple
    key: bool


@dataclass(frozen=True)
class Query:
    id: int
    kind: str      # A, B, C2, C3, D
    group: str     # A, B, C, D
    text: str
    needed: tuple  # chunk ids


@dataclass(frozen=True)
class Gym:
    seed: int
    chunks: tuple
    queries: tuple


def _zipf(n: int) -> list:
    return [1.0 / (i + 1) for i in range(n)]


def make_gym(seed: int, n_topics: int = 40, per_topic: int = 50, n_queries: int = 400) -> Gym:
    rng = random.Random(seed)
    common = [f"c{i:03d}" for i in range(N_COMMON)]
    common_w, topic_w = _zipf(N_COMMON), _zipf(TOPIC_WORDS)
    vocab = {t: [f"t{t:02d}w{j:02d}" for j in range(TOPIC_WORDS)] for t in range(n_topics)}
    related = {t: ((t + 1) % n_topics, (t + 7) % n_topics) for t in range(n_topics)}

    chunks, by_topic, cid = [], {t: [] for t in range(n_topics)}, 0
    for t in range(n_topics):
        key_slots = set(rng.sample(range(per_topic), 3))
        for i in range(per_topic):
            key = i in key_slots
            words = rng.choices(vocab[t], weights=topic_w, k=9 if key else 5)
            facts = (f"f{t:02d}x{i:03d}a", f"f{t:02d}x{i:03d}b")
            words += list(facts)
            words += rng.choices(common, weights=common_w, k=4)
            if rng.random() < 0.2:  # leakage from a related topic makes clusters overlap
                words += rng.choices(vocab[rng.choice(related[t])], weights=topic_w, k=rng.choice((1, 2)))
            rng.shuffle(words)
            chunk = Chunk(cid, t, " ".join(words), facts, key)
            chunks.append(chunk)
            by_topic[t].append(chunk)
            cid += 1

    def topic_words(t, k):
        return rng.choices(vocab[t], weights=topic_w, k=k)

    def common_words(k):
        return rng.choices(common, weights=common_w, k=k)

    kinds = rng.choices([k for k, _ in MIX], weights=[w for _, w in MIX], k=n_queries)
    queries = []
    for qid, kind in enumerate(kinds):
        if kind == "A":
            c = rng.choice(chunks)
            words, needed = list(c.facts) + topic_words(c.topic, 2) + common_words(2), (c.id,)
        elif kind == "B":
            t = rng.randrange(n_topics)
            words = topic_words(t, 5) + common_words(2)
            needed = tuple(c.id for c in by_topic[t] if c.key)
        elif kind in ("C2", "C3"):
            words, picked = [], []
            for t in rng.sample(range(n_topics), 2 if kind == "C2" else 3):
                c = rng.choice(by_topic[t])
                words += list(c.facts) + topic_words(t, 1)
                picked.append(c.id)
            words += common_words(1)
            needed = tuple(picked)
        else:  # D
            words = common_words(5)
            if rng.random() < 0.5:
                words += topic_words(rng.randrange(n_topics), 1)
            needed = ()
        rng.shuffle(words)
        queries.append(Query(qid, kind, kind[0], " ".join(words), needed))
    return Gym(seed, tuple(chunks), tuple(queries))
