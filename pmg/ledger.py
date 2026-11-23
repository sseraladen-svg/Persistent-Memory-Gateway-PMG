"""A tiny cost ledger: records time, tokens and operation counts per named stage.

Usage:
    ledger = Ledger()
    with ledger.stage("search") as s:
        results, ops = do_search()
        s["ops"] = ops
    print(ledger.summary())
"""
from __future__ import annotations

import contextlib
import statistics
import time


class Ledger:
    def __init__(self) -> None:
        self.rows: list[tuple[str, float, int, int]] = []

    def add(self, stage: str, ms: float = 0.0, tokens: int = 0, ops: int = 0) -> None:
        self.rows.append((stage, ms, tokens, ops))

    @contextlib.contextmanager
    def stage(self, name: str, tokens: int = 0, ops: int = 0):
        """Time a block. The yielded dict lets the block report its own tokens and ops."""
        box = {"tokens": tokens, "ops": ops}
        start = time.perf_counter()
        try:
            yield box
        finally:
            self.add(name, (time.perf_counter() - start) * 1000, box["tokens"], box["ops"])

    def summary(self) -> dict:
        out: dict[str, dict] = {}
        for name in dict.fromkeys(r[0] for r in self.rows):
            rows = [r for r in self.rows if r[0] == name]
            times = sorted(r[1] for r in rows)
            out[name] = {
                "count": len(rows),
                "total_ms": sum(times),
                "median_ms": statistics.median(times),
                "p95_ms": times[min(len(times) - 1, int(0.95 * len(times)))],
                "tokens": sum(r[2] for r in rows),
                "ops": sum(r[3] for r in rows),
            }
        return out
