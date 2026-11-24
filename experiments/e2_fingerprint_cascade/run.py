"""Run E2 exactly as written in PROTOCOL.md.   python experiments/e2_fingerprint_cascade/run.py [--smoke]"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import json
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parents[1] / "experiments" / "e1_topology_router"))  # after HERE so `engine` is E2's

from engine import K, Fingerprints, Store, bytes_cascade, bytes_exact, cascade_top, exact_top, timed  # noqa: E402
from gym import make_gym  # noqa: E402

SIZES = {2000: 40, 10000: 200, 50000: 1000}      # N -> topics (50 chunks each)
VAL_SEEDS, TEST_SEEDS = (101, 102), (401, 402, 403)
BITS, SHORTLISTS = (64, 128, 256), (20, 40, 80, 160, 320)
N_QUERIES = 300


def recall(ids, needed):
    return sum(n in ids for n in needed) / len(needed) if needed else None


def prepare(seed, n):
    gym = make_gym(seed, n_topics=SIZES[n], per_topic=50, n_queries=N_QUERIES)
    store = Store(gym.chunks, seed=seed)
    qs = [(q, store.embed_query(q.text)) for q in gym.queries]
    exact = [exact_top(store, v) for _, v in qs]
    return gym, store, qs, exact


def evaluate(store, qs, exact, fp, shortlist, with_time=False):
    overlaps, recs, times = [], [], []
    for (q, v), ex in zip(qs, exact):
        out, ms = timed(cascade_top, store, fp, v, shortlist)
        overlaps.append(len(set(out.tolist()) & set(ex.tolist())) / K)
        recs.append(recall(set(out.tolist()), q.needed) if q.kind != "D" else None)
        times.append(ms)
    return overlaps, recs, times


def macro(qs, recs):
    by = {}
    for (q, _), r in zip(qs, recs):
        if r is not None:
            by.setdefault(q.group, []).append(r)
    return statistics.mean(statistics.mean(v) for v in by.values())


def per_query_recall(qs, ids_list):
    return [recall(set(i.tolist()), q.needed) if q.kind != "D" else None for (q, _), i in zip(qs, ids_list)]


def bootstrap_diff(qs, ra, rb, n=2000, seed=0):
    """Paired bootstrap of macro recall (a minus b) over queries."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(qs))
    groups = np.array([q.group for q, _ in qs])
    a = np.array([np.nan if r is None else r for r in ra])
    b = np.array([np.nan if r is None else r for r in rb])
    diffs = []
    for _ in range(n):
        s = rng.choice(idx, size=len(idx), replace=True)
        parts = []
        for g in ("A", "B", "C"):
            m = s[groups[s] == g]
            if len(m):
                parts.append(np.nanmean(a[m]) - np.nanmean(b[m]))
        diffs.append(np.mean(parts))
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def run(smoke=False):
    sizes = [2000] if smoke else list(SIZES)
    val_seeds, test_seeds = ((101,), (201,)) if smoke else (VAL_SEEDS, TEST_SEEDS)
    report = {"sizes": {}}
    for n in sizes:
        print(f"N={n}: preparing validation gyms", flush=True)
        val = [prepare(s, n) for s in val_seeds]
        grid = []
        for bits in BITS:
            for r in SHORTLISTS:
                ov = []
                for (gym, store, qs, ex) in val:
                    fp = Fingerprints(store, bits)
                    o, _, _ = evaluate(store, qs, ex, fp, r)
                    ov += o
                grid.append({"bits": bits, "shortlist": r, "val_overlap": statistics.mean(ov),
                             "bytes": bytes_cascade(n, bits, r)})
        ok = [g for g in grid if g["val_overlap"] >= 0.95]
        chosen = min(ok, key=lambda g: g["bytes"]) if ok else max(grid, key=lambda g: g["val_overlap"])
        chosen["met_validation_target"] = bool(ok)
        del val
        print(f"N={n}: chosen {chosen}; evaluating on test seeds", flush=True)

        ov, rc, rb, tc, tb, per_seed = [], [], [], [], [], []
        qs_all = []
        for s in test_seeds:
            gym, store, qs, ex = prepare(s, n)
            fp = Fingerprints(store, chosen["bits"])
            for (q, v) in qs[:20]:                              # warm-up
                exact_top(store, v)
                cascade_top(store, fp, v, chosen["shortlist"])
            o, _, t_c = evaluate(store, qs, ex, fp, chosen["shortlist"])
            outs = [cascade_top(store, fp, v, chosen["shortlist"]) for _, v in qs]
            t_b = [timed(exact_top, store, v)[1] for _, v in qs]
            ov += o
            rc += per_query_recall(qs, outs)
            rb += per_query_recall(qs, ex)
            tc += t_c
            tb += t_b
            qs_all += qs
        rec_c, rec_b = macro(qs_all, rc), macro(qs_all, rb)
        lo, hi = bootstrap_diff(qs_all, rc, rb)
        res = {
            "chosen": chosen,
            "overlap_at_10": statistics.mean(ov),
            "macro_recall_cascade": rec_c, "macro_recall_exact": rec_b,
            "recall_diff": rec_c - rec_b, "recall_diff_ci95": [lo, hi],
            "bytes_cascade": chosen["bytes"], "bytes_exact": bytes_exact(n),
            "bytes_ratio": chosen["bytes"] / bytes_exact(n),
            "latency_ms_cascade_median": statistics.median(tc), "latency_ms_exact_median": statistics.median(tb),
            "latency_ratio": statistics.median(tc) / statistics.median(tb),
        }
        report["sizes"][n] = res
        print(json.dumps(res, indent=1), flush=True)

    big = report["sizes"].get(50000)
    if big:
        checks = {
            "overlap_ge_0.95": big["overlap_at_10"] >= 0.95,
            "recall_within_0.01": big["recall_diff"] >= -0.01,
            "bytes_le_25pct": big["bytes_ratio"] <= 0.25,
            "latency_le_50pct": big["latency_ratio"] <= 0.5,
        }
        report["verdict"] = {"pass": all(checks.values()), "checks": checks}
    if not smoke:
        (HERE / "results.json").write_text(json.dumps(report, indent=1))
        write_md(report)
    return report


def write_md(rep):
    v = rep["verdict"]
    L = ["# E2 results", "",
         "Generated by `run.py`. The pass/fail rules in `PROTOCOL.md` were fixed before this run. Vectors are random "
         "projections of TF-IDF from a synthetic gym, so this tests the cascade mechanism, not real embeddings.", "",
         f"Validation seeds {list(VAL_SEEDS)}, test seeds {list(TEST_SEEDS)}, {N_QUERIES} queries per seed.", "",
         f"## Verdict (N = 50,000): **{'PASS' if v['pass'] else 'FAIL'}**", ""]
    L += [f"- {'pass' if ok else 'FAIL'}: {k}" for k, ok in v["checks"].items()]
    L += ["", "## All store sizes (configuration chosen on validation, evaluated on test)", "",
          "| N | bits | shortlist | overlap@10 | recall cascade | recall exact | diff (95% CI) | bytes ratio | latency ms (cascade / exact) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for n, r in rep["sizes"].items():
        c = r["chosen"]
        L.append(f"| {n} | {c['bits']} | {c['shortlist']} | {r['overlap_at_10']:.3f} | {r['macro_recall_cascade']:.3f} | "
                 f"{r['macro_recall_exact']:.3f} | {r['recall_diff']:+.3f} ({r['recall_diff_ci95'][0]:+.3f} to "
                 f"{r['recall_diff_ci95'][1]:+.3f}) | {r['bytes_ratio']:.1%} | "
                 f"{r['latency_ms_cascade_median']:.2f} / {r['latency_ms_exact_median']:.2f} |")
    L += ["", "Bytes are read per query. The cascade still scans every fingerprint, so its cost grows linearly with N."]
    (HERE / "RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run(smoke="--smoke" in sys.argv)
