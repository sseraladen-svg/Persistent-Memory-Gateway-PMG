"""Run experiment E1. See PROTOCOL.md for the question and the pass/fail rules.

    python experiments/e1_topology_router/run.py            # full run
    python experiments/e1_topology_router/run.py --smoke    # quick check that everything works
    python experiments/e1_topology_router/run.py --sensitivity 1500   # also give P2 more search budget
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from itertools import product
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from engine import PARAM_NAMES, Index, precompute, run_router  # noqa: E402
from gym import make_gym  # noqa: E402
from pmg.ledger import Ledger  # noqa: E402

VAL_SEEDS = (101, 102, 103)
TEST_SEEDS = (301, 302, 303, 304, 305)  # moved from 201-205 after the smoke run showed seed 201 (see PROTOCOL.md)
TARGETS = (0.85, 0.90, 0.95)
BASELINES = ("P0", "P1", "P1b")
FLOORS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
GRIDS = {
    # every router may use up to the full pool of 50 candidates (the smoke run found baselines capped at 20)
    "P0": {"k": list(range(1, 51))},
    "P1": {"floor": FLOORS, "margin": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6], "k_fallback": [3, 5, 8, 12, 16, 20, 30, 50]},
    "P1b": {"floor": FLOORS, "beta": [round(0.2 + 0.05 * i, 2) for i in range(15)], "k_max": [5, 10, 20, 30, 50]},
    "P2": {"floor": FLOORS, "m": [20, 50], "gap": [0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0],
           "alpha": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9], "beta": [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
           "cap": [3, 5, 8]},
}


def build(seeds, ledger):
    pres, groups = [], []
    for seed in seeds:
        gym = make_gym(seed)
        pres += precompute(gym, Index(gym.chunks), ledger)
    return pres


def aggregate(pres, tokens, recalls, waste):
    by = {}
    for i, p in enumerate(pres):
        by.setdefault(p.group, []).append(i)
    recall_by = {g: sum(recalls[i] for i in idx) / len(idx) for g, idx in by.items() if g != "D"}
    d = by.get("D", [])
    return {
        "mean_tokens": sum(tokens) / len(tokens),
        "macro_recall": sum(recall_by.values()) / len(recall_by),
        "recall_by_type": recall_by,
        "tokens_by_type": {g: sum(tokens[i] for i in idx) / len(idx) for g, idx in by.items()},
        "waste_ratio": sum(waste) / max(1, sum(tokens)),
        "abstain_rate": sum(tokens[i] == 0 for i in d) / max(1, len(d)),
    }


def configs(name, budget):
    keys = PARAM_NAMES[name]
    allc = [dict(zip(keys, v)) for v in product(*[GRIDS[name][k] for k in keys])]
    return random.Random(12345).sample(allc, budget) if len(allc) > budget else allc


def tune(name, budget, val_pres):
    return [(cfg, aggregate(val_pres, *run_router(name, cfg, val_pres))) for cfg in configs(name, budget)]


def select(results, target):
    ok = [r for r in results if r[1]["macro_recall"] >= target]
    if ok:
        return min(ok, key=lambda r: (r[1]["mean_tokens"], -r[1]["macro_recall"]))
    return max(results, key=lambda r: (r[1]["macro_recall"], -r[1]["mean_tokens"]))


def bootstrap_tokens(base, other, n, seed=7):
    """Paired bootstrap of mean(base - other). Positive means `other` uses fewer tokens."""
    rng, diff = random.Random(seed), [a - b for a, b in zip(base, other)]
    means = sorted(sum(rng.choices(diff, k=len(diff))) / len(diff) for _ in range(n))
    return sum(diff) / len(diff), means[int(0.025 * n)], means[int(0.975 * n) - 1]


def bootstrap_macro(groups, rec_other, rec_base, n, seed=11):
    """Paired bootstrap of macro-recall(other) - macro-recall(base) over answerable queries."""
    rng = random.Random(seed)
    idx = [i for i, g in enumerate(groups) if g != "D"]
    diffs = []
    for _ in range(n):
        cnt, so, sb = {}, {}, {}
        for i in rng.choices(idx, k=len(idx)):
            g = groups[i]
            cnt[g] = cnt.get(g, 0) + 1
            so[g] = so.get(g, 0.0) + rec_other[i]
            sb[g] = sb.get(g, 0.0) + rec_base[i]
        diffs.append(sum((so[g] - sb[g]) / cnt[g] for g in cnt) / len(cnt))
    diffs.sort()
    return sum(diffs) / len(diffs), diffs[int(0.025 * n)], diffs[int(0.975 * n) - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--sensitivity", type=int, default=0, help="extra P2 run with this many configurations")
    args = ap.parse_args()
    val_seeds, test_seeds = ((101,), (201,)) if args.smoke else (VAL_SEEDS, TEST_SEEDS)
    budget, boots = (40, 200) if args.smoke else (600, 2000)

    t0, ledger = time.time(), Ledger()
    print("building gyms and precomputing candidates...", flush=True)
    val_pres, test_pres = build(val_seeds, ledger), build(test_seeds, ledger)
    groups = [p.group for p in test_pres]
    print(f"  {len(val_pres)} validation and {len(test_pres)} test queries ({time.time() - t0:.0f}s)", flush=True)

    tuned = {}
    for name in ("P0", "P1", "P1b", "P2"):
        tuned[name] = tune(name, budget, val_pres)
        print(f"  tuned {name}: {len(tuned[name])} configurations ({time.time() - t0:.0f}s)", flush=True)
    if args.sensitivity:
        tuned["P2-big"] = tune("P2", args.sensitivity, val_pres)
        print(f"  tuned P2-big: {len(tuned['P2-big'])} configurations ({time.time() - t0:.0f}s)", flush=True)

    out = {"val_seeds": val_seeds, "test_seeds": test_seeds, "budget": budget, "targets": {}}
    for target in TARGETS:
        chosen, test = {}, {}
        for name, results in tuned.items():
            cfg, val_agg = select(results, target)
            algo = "P2" if name == "P2-big" else name
            raw = run_router(algo, cfg, test_pres)
            chosen[name] = {"config": cfg, "validation": val_agg}
            test[name] = {"aggregate": aggregate(test_pres, *raw), "tokens": raw[0], "recalls": raw[1]}
        # best baseline is picked on validation data only
        best = min((n for n in BASELINES), key=lambda n: (
            chosen[n]["validation"]["macro_recall"] < target, chosen[n]["validation"]["mean_tokens"]
            if chosen[n]["validation"]["macro_recall"] >= target else -chosen[n]["validation"]["macro_recall"]))
        entry = {"chosen": chosen, "best_baseline": best,
                 "test": {n: t["aggregate"] for n, t in test.items()}, "comparisons": {}}
        for name in [n for n in test if n.startswith("P2")]:
            mean_d, lo, hi = bootstrap_tokens(test[best]["tokens"], test[name]["tokens"], boots)
            base_mean = test[best]["aggregate"]["mean_tokens"]
            r_d, r_lo, r_hi = bootstrap_macro(groups, test[name]["recalls"], test[best]["recalls"], boots)
            m = chosen[name]["config"]["m"]
            entry["comparisons"][name] = {
                "tokens_saved_mean": mean_d, "tokens_saved_ci": [lo, hi], "relative_saving": mean_d / base_mean,
                "macro_recall_diff": r_d, "macro_recall_diff_ci": [r_lo, r_hi], "m": m}
        out["targets"][str(target)] = entry
        print(f"  evaluated target {target} ({time.time() - t0:.0f}s)", flush=True)

    summary = ledger.summary()
    out["overhead"] = {k: {"median_ms": v["median_ms"], "p95_ms": v["p95_ms"], "ops_per_query": v["ops"] / v["count"]}
                       for k, v in summary.items()}
    primary = out["targets"]["0.9"]
    comp = primary["comparisons"]["P2"]
    overhead_ms = out["overhead"][f"mst{comp['m']}"]["median_ms"]
    checks = {
        "fewer_tokens_ge_10pct_ci_excludes_0": comp["relative_saving"] >= 0.10 and comp["tokens_saved_ci"][0] > 0,
        "recall_noninferior_within_0.01": comp["macro_recall_diff"] >= -0.01,
        "overhead_le_10ms": overhead_ms <= 10.0,
    }
    out["verdict"] = {"checks": checks, "overhead_ms": overhead_ms, "passed": all(checks.values())}
    out["seconds"] = time.time() - t0

    (HERE / "results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (HERE / "RESULTS.md").write_text(render(out), encoding="utf-8")
    print("\nverdict:", "PASS" if out["verdict"]["passed"] else "FAIL", checks)
    print(f"wrote {HERE / 'RESULTS.md'}")


def render(out):
    lines = ["# E1 results", "",
             "Generated by `run.py`. The pass/fail rules in `PROTOCOL.md` were fixed before this run. "
             "Everything below is from a **synthetic gym with word-count vectors**, so it tests whether the mechanism "
             "can work, not whether it helps on real conversations with real embeddings.", "",
             f"Validation seeds {list(out['val_seeds'])}, test seeds {list(out['test_seeds'])}, "
             f"P2 search budget {out['budget']} configurations (baselines searched exhaustively).", ""]
    v = out["verdict"]
    lines += [f"## Verdict (target recall 0.90, P2 vs best baseline): **{'PASS' if v['passed'] else 'FAIL'}**", ""]
    for name, ok in v["checks"].items():
        lines.append(f"- {'pass' if ok else 'FAIL'}: {name}")
    lines += [f"- router overhead measured: {v['overhead_ms']:.2f} ms per query (median)", ""]
    for target, entry in out["targets"].items():
        lines += [f"## Test results, validation-selected for recall at least {target}", "",
                  f"Best baseline (chosen on validation): **{entry['best_baseline']}**", "",
                  "| Router | Mean tokens | Macro recall | Waste ratio | Abstains on vague | Tokens A / B / C / D |",
                  "|---|---|---|---|---|---|"]
        for name, a in entry["test"].items():
            t = a["tokens_by_type"]
            lines.append(f"| {name} | {a['mean_tokens']:.1f} | {a['macro_recall']:.3f} | {a['waste_ratio']:.2f} | "
                         f"{a['abstain_rate']:.0%} | {t['A']:.0f} / {t['B']:.0f} / {t['C']:.0f} / {t['D']:.0f} |")
        lines += ["", "Selected configurations (from validation):", ""]
        for name, c in entry["chosen"].items():
            lines.append(f"- {name}: `{json.dumps(c['config'])}`, validation tokens {c['validation']['mean_tokens']:.1f}, "
                         f"recall {c['validation']['macro_recall']:.3f}")
        lines.append("")
        for name, c in entry["comparisons"].items():
            lo, hi = c["tokens_saved_ci"]
            rlo, rhi = c["macro_recall_diff_ci"]
            lines.append(f"{name} vs {entry['best_baseline']}: tokens saved {c['tokens_saved_mean']:.1f} per query "
                         f"(95% CI {lo:.1f} to {hi:.1f}), {c['relative_saving']:.1%} relative; "
                         f"macro recall difference {c['macro_recall_diff']:+.3f} (95% CI {rlo:+.3f} to {rhi:+.3f}).")
        lines.append("")
    lines += ["## Cost of the router", "", "| Stage | Median ms | p95 ms | Operations per query |", "|---|---|---|---|"]
    for stage, o in out["overhead"].items():
        lines.append(f"| {stage} | {o['median_ms']:.3f} | {o['p95_ms']:.3f} | {o['ops_per_query']:.0f} |")
    lines += ["", "Times are pure Python on one CPU core, and include dictionary-based sparse vectors, so they overstate what an optimised "
              "implementation would cost. Operation counts are implementation-independent.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
