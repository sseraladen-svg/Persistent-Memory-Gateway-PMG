"""Descriptive follow-up to E2 (not part of the verdict): how large a shortlist would 0.95 overlap need?

    python experiments/e2_fingerprint_cascade/diagnose.py
"""
from __future__ import annotations

import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parents[1] / "experiments" / "e1_topology_router"))

import statistics  # noqa: E402
import run as R  # noqa: E402
from engine import Fingerprints, bytes_cascade, bytes_exact  # noqa: E402

lines = ["# E2 diagnostics", "", "Descriptive only; run after the verdict on validation seed 101. Does not change it.", "",
         "| N | bits | shortlist | overlap@10 | bytes vs exact | latency ms (cascade) |", "|---|---|---|---|---|---|"]
for n in (10000, 50000):
    gym, store, qs, ex = R.prepare(101, n)
    for bits in (256,):
        fp = Fingerprints(store, bits)
        for r in (320, 1000, 3000, 10000, 25000):
            if r > n:
                continue
            o, _, t = R.evaluate(store, qs, ex, fp, r)
            lines.append(f"| {n} | {bits} | {r} | {statistics.mean(o):.3f} | {bytes_cascade(n, bits, r) / bytes_exact(n):.0%} | {statistics.median(t):.2f} |")
(HERE / "DIAGNOSTICS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
