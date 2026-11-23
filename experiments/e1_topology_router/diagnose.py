"""Diagnostics for E1: why did the topology router behave the way it did? (descriptive only, not part of the verdict)

    python experiments/e1_topology_router/diagnose.py
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import run as R  # noqa: E402
from engine import Index, clusters, precompute, run_router  # noqa: E402
from gym import make_gym  # noqa: E402
from pmg.ledger import Ledger  # noqa: E402


def quantiles(xs):
    xs = sorted(xs)
    return [xs[int(q * (len(xs) - 1))] for q in (0.05, 0.25, 0.5, 0.75, 0.95)]


def main():
    lines = ["# E1 diagnostics", "", "Descriptive checks run after the verdict. They do not change it.", ""]

    # 1. Does the geometry contain visible cluster structure?
    same, cross = [], []
    for seed in R.VAL_SEEDS:
        gym = make_gym(seed)
        index = Index(gym.chunks)
        for p, q in zip(precompute(gym, index, Ledger()), gym.queries):
            ids = [d for d, _ in p.cands[:20]]
            for i, j, d in p.mst[20]:
                (same if gym.chunks[ids[i]].topic == gym.chunks[ids[j]].topic else cross).append(d)
    lines += ["## 1. Are chunks of the same topic closer together than chunks of different topics?", "",
              "MST edge lengths (cosine distance) among the top-20 candidates, validation gyms.", "",
              "| Edge type | Count | 5% | 25% | median | 75% | 95% |", "|---|---|---|---|---|---|---|"]
    for name, xs in (("same topic", same), ("different topics", cross)):
        q = quantiles(xs)
        lines.append(f"| {name} | {len(xs)} | " + " | ".join(f"{v:.3f}" for v in q) + " |")
    lines += ["", f"Share of all MST edges at or below each gap threshold in the grid:", ""]
    alle = same + cross
    lines.append("| gap | " + " | ".join(str(g) for g in R.GRIDS["P2"]["gap"]) + " |")
    lines.append("|---|" + "---|" * len(R.GRIDS["P2"]["gap"]))
    lines.append("| share of edges | " + " | ".join(f"{sum(d <= g for d in alle) / len(alle):.0%}" for g in R.GRIDS["P2"]["gap"]) + " |")

    # 2. What did the tuned P2 actually do with the clusters?
    val, test = R.build(R.VAL_SEEDS, Ledger()), R.build(R.TEST_SEEDS, Ledger())
    tuned = {n: R.tune(n, 600, val) for n in ("P0", "P1", "P1b", "P2")}
    cfg, _ = R.select(tuned["P2"], 0.90)
    sizes = [min(cfg["m"], len(p.cands)) for p in test]
    counts = [len(clusters(p, cfg["m"], cfg["gap"])) for p in test]
    singletons = sum(c == s for c, s in zip(counts, sizes)) / len(test)
    lines += ["", "## 2. What the tuned P2 did with the clusters (target 0.90)", "",
              f"Chosen configuration: `{cfg}`", "",
              f"- mean number of clusters it found: {statistics.mean(counts):.1f} out of {statistics.mean(sizes):.1f} candidates",
              f"- queries where every candidate was its own cluster: {singletons:.0%}", "",
              "If this is near 100%, the optimiser chose settings where clustering does nothing, and P2 reduces to a "
              "relative score cutoff like P1b."]

    # 3. Tokens needed at several recall targets (validation-selected, evaluated on test)
    lines += ["", "## 3. Tokens versus recall on the test seeds", "",
              "Each configuration is chosen on validation data for the target, then evaluated on test seeds.", "",
              "| Target | P0 tokens / recall | P1b tokens / recall | P2 tokens / recall |", "|---|---|---|---|"]
    for target in (0.80, 0.84, 0.88, 0.90, 0.92, 0.94, 0.95):
        row = []
        for name in ("P0", "P1b", "P2"):
            cfg, _ = R.select(tuned[name], target)
            agg = R.aggregate(test, *run_router(name, cfg, test))
            row.append(f"{agg['mean_tokens']:.0f} / {agg['macro_recall']:.3f}")
        lines.append(f"| {target:.2f} | " + " | ".join(row) + " |")

    # 4. Where do the tokens go for vague (type D) queries?
    cfg, _ = R.select(tuned["P1b"], 0.90)
    tokens, _, _ = run_router("P1b", cfg, test)
    d_tokens = [t for p, t in zip(test, tokens) if p.group == "D"]
    top = [p.cands[0][1] for p in test if p.group == "D" and p.cands]
    ans_top = [p.cands[0][1] for p in test if p.group != "D" and p.cands]
    lines += ["", "## 4. Vague (type D) questions", "",
              f"- median top score on vague questions: {statistics.median(top):.3f}; on answerable questions: {statistics.median(ans_top):.3f}",
              f"- P1b at target 0.90 injects {statistics.mean(d_tokens):.0f} tokens on average for vague questions, "
              "which is the most expensive query type and returns nothing useful.", ""]
    (HERE / "DIAGNOSTICS.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
