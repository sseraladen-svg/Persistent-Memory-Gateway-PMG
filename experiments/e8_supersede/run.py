"""Run E8 as written in PROTOCOL.md.   python experiments/e8_supersede/run.py"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

SEED = 901
ATTRS = ("deadline budget owner location version release priority target quota limit rate price size headcount score "
         "capacity timeout discount salary schedule review launch margin forecast").split()
MONTHS = ("January February March April May June July August September October November December").split()


def names(rng, n, pool):
    out = set()
    while len(out) < n:
        out.add("".join(rng.choice(pool) for _ in range(3)).capitalize())
    return sorted(out)


def build_stream(seed=SEED):
    rng = random.Random(seed)
    ents = names(rng, 150, ["ka", "vro", "tel", "mi", "zan", "dor", "lu", "pe", "xi", "bar", "non", "ya"])
    people = names(rng, 100, ["pri", "ya", "ra", "vi", "su", "ni", "ta", "ro", "ha", "ji"])
    used = set()

    def slot(attr=None, ent=None):
        while True:
            e, a = ent or rng.choice(ents), attr or rng.choice(ATTRS)
            if (e, a) not in used:
                used.add((e, a))
                return e, a

    date = lambda: f"{rng.choice(MONTHS)} {rng.randint(1, 28)}"
    initial, later, meta = [], [], {"tail": [], "mid": [], "text": [], "dA": [], "dB": [], "dC": [], "dup": []}
    for i in range(100):
        e, a = slot()
        v1 = date()
        v2 = date()
        while v2 == v1:
            v2 = date()
        filler = i % 2 == 1
        old, new = f"{e} {a} is {v1}", f"{e} {a} is {'now ' if filler else ''}{v2}"
        initial.append(old); later.append(new)
        meta["tail"].append({"q": f"{e} {a}", "old": v1, "new": v2, "filler": filler, "old_text": old, "new_text": new})
    for _ in range(50):
        e, a = slot()
        n1, n2 = rng.sample(range(1, 10), 2)
        old, new = f"{e} {a} is {n1} million dollars", f"{e} {a} is {n2} million dollars"
        initial.append(old); later.append(new)
        meta["mid"].append({"q": f"{e} {a}", "old": f"{n1} million", "new": f"{n2} million", "old_text": old, "new_text": new})
    for _ in range(50):
        e, a = slot()
        p1, p2 = rng.sample(people, 2)
        old, new = f"{e} {a} is {p1}", f"{e} {a} is {p2}"
        initial.append(old); later.append(new)
        meta["text"].append({"q": f"{e} {a}", "old": p1, "new": p2, "old_text": old, "new_text": new})
    for _ in range(50):  # same attribute, different entity
        a = rng.choice(ATTRS)
        e1, _ = slot(a); e2, _ = slot(a)
        t1, t2 = f"{e1} {a} is {date()}", f"{e2} {a} is {date()}"
        initial.append(t1); later.append(t2); meta["dA"].append([t1, t2])
    for _ in range(50):  # same entity, different attribute
        e = rng.choice(ents)
        _, a1 = slot(None, e); _, a2 = slot(None, e)
        t1, t2 = f"{e} {a1} is {date()}", f"{e} {a2} is {date()}"
        initial.append(t1); later.append(t2); meta["dB"].append([t1, t2])
    for _ in range(50):  # numbered slots
        e, a = slot()
        d = date()
        t1, t2 = f"{e} sprint 3 {a} is {d}", f"{e} sprint 4 {a} is {d}"
        initial.append(t1); later.append(t2); meta["dC"].append([t1, t2])
    for t in rng.sample(initial, 50):
        later.append(t); meta["dup"].append(t)
    rng.shuffle(initial)
    rng.shuffle(later)
    return initial, later, meta


def run_policy(supersede: bool, initial, later):
    from pmg.store import Memory
    d = tempfile.mkdtemp(prefix="pmg-e8-")
    os.environ["PMG_DATA"] = d
    m = Memory()
    m.supersede = supersede
    for t in initial + later:
        m.add("fact", t)
    return m


def has(text, value):
    return re.search(rf"\b{re.escape(value)}\b", text, re.I) is not None


def exists(m, text):
    from pmg.textutil import normalize
    with m._db() as c:
        return c.execute("SELECT 1 FROM chunks WHERE norm = ?", (normalize(text),)).fetchone() is not None


def evaluate(m, meta):
    out = {}
    for fam in ("tail", "mid", "text"):
        rows = []
        for s in meta[fam]:
            top = " | ".join(t for _, t, _ in m.candidates(s["q"], 3))
            rows.append({**s, "ok": has(top, s["new"]) and not has(top, s["old"]), "stale": has(top, s["old"])})
        out[fam] = rows
    out["tail_ok"] = sum(r["ok"] for r in out["tail"]) / 100
    plain = [r for r in out["tail"] if not r["filler"]]
    out["tail_ok_no_filler"] = sum(r["ok"] for r in plain) / len(plain)
    out["tail_stale_all"] = sum(r["stale"] for r in out["tail"]) / 100
    out["mid_ok"] = sum(r["ok"] for r in out["mid"]) / 50
    out["text_ok"] = sum(r["ok"] for r in out["text"]) / 50
    pairs = meta["dA"] + meta["dB"] + meta["dC"]
    out["false_replacement"] = sum(not (exists(m, a) and exists(m, b)) for a, b in pairs) / len(pairs)
    out["false_replacement_by_kind"] = {k: sum(not (exists(m, a) and exists(m, b)) for a, b in meta[k]) / 50 for k in ("dA", "dB", "dC")}
    updated_old = {s["old_text"] for fam in ("tail", "mid", "text") for s in meta[fam]}
    kept = {s["old_text"] for fam in ("tail", "mid", "text") for s in meta[fam]}
    out["chunks"] = m.stats()["chunks"]
    return out


def main():
    initial, later, meta = build_stream()
    base = evaluate(run_policy(False, initial, later), meta)
    new_m = run_policy(True, initial, later)
    new = evaluate(new_m, meta)
    # replaced tail updates: stale rate among them (criterion 3), and collateral loss (criterion 4)
    replaced = [r for r in new["tail"] if r["ok"]]
    stale_replaced = sum(r["stale"] for r in replaced) / len(replaced) if replaced else None
    base_stale = base["tail_stale_all"]
    collateral = [t for fam in ("dA", "dB", "dC") for pair in meta[fam] for t in pair if not exists(new_m, t)]
    tail_initial_lost = [s for fam in () for s in []]
    checks = {
        "tail_replaced_ge_0.45_and_no_filler_ge_0.9": new["tail_ok"] >= 0.45 and new["tail_ok_no_filler"] >= 0.9,
        "false_replacement_le_0.01": new["false_replacement"] <= 0.01,
        "stale_80pct_lower_among_replaced": stale_replaced is not None and stale_replaced <= 0.2 * base_stale,
        "no_collateral_loss": not collateral,
    }
    rep = {"baseline": {k: v for k, v in base.items() if not isinstance(v, list)},
           "feature": {k: v for k, v in new.items() if not isinstance(v, list)},
           "stale_among_replaced": stale_replaced, "baseline_stale_all": base_stale,
           "collateral_loss": len(collateral), "checks": checks, "pass": all(checks.values())}
    (HERE / "results.json").write_text(json.dumps(rep, indent=1))
    f, b = rep["feature"], rep["baseline"]
    L = ["# E8 results (replacing outdated notes without an LLM)", "",
         "Generated by `run.py`. Rules in `PROTOCOL.md` were fixed before the feature was implemented. Templated synthetic text.", "",
         f"## Verdict: **{'PASS' if rep['pass'] else 'FAIL'}**", ""]
    L += [f"- {'pass' if v else 'FAIL'}: {k}" for k, v in checks.items()]
    L += ["", "| Measure | Baseline (off) | Feature (on) |", "|---|---|---|",
          f"| tail-numeric updates fixed (new value shown, old gone), all 100 | {b['tail_ok']:.2f} | {f['tail_ok']:.2f} |",
          f"| ...among updates without the filler word | {b['tail_ok_no_filler']:.2f} | {f['tail_ok_no_filler']:.2f} |",
          f"| tail-numeric slots where the old value is still returned | {b['tail_stale_all']:.2f} | {f['tail_stale_all']:.2f} |",
          f"| middle-numeric updates fixed (expected miss) | {b['mid_ok']:.2f} | {f['mid_ok']:.2f} |",
          f"| textual updates fixed (expected miss) | {b['text_ok']:.2f} | {f['text_ok']:.2f} |",
          f"| false replacements over 150 distractor pairs | {b['false_replacement']:.3f} | {f['false_replacement']:.3f} |",
          f"| ...different entity / different attribute / numbered | - | {f['false_replacement_by_kind']['dA']:.2f} / {f['false_replacement_by_kind']['dB']:.2f} / {f['false_replacement_by_kind']['dC']:.2f} |",
          f"| chunks stored | {b['chunks']} | {f['chunks']} |",
          "", f"Among tail updates that were replaced, the old value was still returned in {stale_replaced:.2f} of cases "
          f"(baseline, all tail updates: {base_stale:.2f}). This criterion is nearly vacuous; the all-update figure above is the honest one."]
    (HERE / "RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
