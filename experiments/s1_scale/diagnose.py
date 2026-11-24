"""Descriptive follow-up to S1 (does not change the verdict): where does the time go at 100,000 chunks?"""
import os, sys, tempfile, statistics, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1]))
sys.path.append(str(HERE.parents[1] / "experiments" / "e1_topology_router"))
import run as S
from pmg.textutil import unique_keywords

with tempfile.TemporaryDirectory(prefix="pmg-scale-") as d:
    m, gym = S.build(d, 100_000)
    for q in gym.queries[:20]:
        m.retrieve(q.text, log=False)
    m.ledger.rows.clear()
    common, rare = [], []
    for q in gym.queries[:300]:
        words = unique_keywords(q.text)
        t = time.perf_counter(); m.retrieve(q.text, log=False); ms = (time.perf_counter() - t) * 1000
        (common if any(w.startswith("c") and w[1:].isdigit() for w in words) else rare).append(ms)
    s = m.ledger.summary()
    lines = ["# S1 diagnostics (100,000 chunks, descriptive only)", "",
             f"- queries containing a very common word: {len(common)}, median {statistics.median(common):.1f} ms" if common else "",
             f"- queries with only topic/fact words: {len(rare)}, median {statistics.median(rare):.1f} ms" if rare else "",
             f"- stage `retrieve.search` (the FTS5 BM25 query) median {s['retrieve.search']['median_ms']:.1f} ms of "
             f"`retrieve.total` median {s['retrieve.total']['median_ms']:.1f} ms"]
    (HERE / "DIAGNOSTICS.md").write_text("\n".join(l for l in lines if l) + "\n", encoding="utf-8")
    print("\n".join(l for l in lines if l))
