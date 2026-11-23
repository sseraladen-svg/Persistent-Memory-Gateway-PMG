"""Sanity tests for the E1 gym, engine and ledger. These guard the experiment against silent bugs."""
import sys
import time
import unittest
from pathlib import Path

E1 = Path(__file__).resolve().parents[1] / "experiments" / "e1_topology_router"
sys.path.insert(0, str(E1))

from engine import Index, clusters, mst_edges, precompute, route_p0, route_p1b, route_p2, run_router  # noqa: E402
from gym import make_gym  # noqa: E402
from pmg.ledger import Ledger  # noqa: E402


class GymTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gym = make_gym(5, n_queries=300)
        cls.index = Index(cls.gym.chunks)

    def test_is_deterministic_per_seed(self):
        self.assertEqual(make_gym(5, n_queries=50).queries, make_gym(5, n_queries=50).queries)
        self.assertNotEqual(make_gym(5, n_queries=50).queries, make_gym(6, n_queries=50).queries)

    def test_ground_truth_is_consistent(self):
        ids = {c.id: c for c in self.gym.chunks}
        seen = set()
        for q in self.gym.queries:
            seen.add(q.kind)
            self.assertTrue(all(n in ids for n in q.needed))
            topics = [ids[n].topic for n in q.needed]
            if q.kind == "A":
                self.assertEqual(len(q.needed), 1)
            elif q.kind == "B":
                self.assertEqual(len(q.needed), 3)
                self.assertTrue(all(ids[n].key for n in q.needed))
                self.assertEqual(len(set(topics)), 1)
            elif q.kind in ("C2", "C3"):
                self.assertEqual(len(q.needed), int(q.kind[1]))
                self.assertEqual(len(set(topics)), len(topics))
            else:
                self.assertEqual(q.needed, ())
        self.assertEqual(seen, {"A", "B", "C2", "C3", "D"})

    def test_single_fact_queries_are_findable(self):
        hits = total = 0
        for q in self.gym.queries:
            if q.kind == "A":
                top, _ = self.index.search(q.text, top=1)
                total += 1
                hits += top[0][0] == q.needed[0]
        self.assertGreater(hits / total, 0.9)  # otherwise the generator is broken, not the router


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gym = make_gym(7, n_queries=120)
        cls.index = Index(cls.gym.chunks)
        cls.pres = precompute(cls.gym, cls.index, Ledger())

    def test_mst_spans_and_is_minimal_against_a_star(self):
        ids = [d for d, _ in self.pres[0].cands[:20]]
        edges, ops = mst_edges(self.index, ids)
        self.assertEqual(len(edges), len(ids) - 1)
        self.assertEqual(ops, len(ids) * (len(ids) - 1) // 2)
        reached = {0} | {j for _, j, _ in edges}
        self.assertEqual(reached, set(range(len(ids))))
        star = sum(max(0.0, 1 - self.index.cosine(ids[0], ids[j])) for j in range(1, len(ids)))
        self.assertLessEqual(sum(d for *_, d in edges), star + 1e-9)

    def test_clusters_partition_candidates(self):
        for p in self.pres[:30]:
            for gap in (0.6, 0.9, 1.0):
                groups = clusters(p, 20, gap)
                flat = sorted(pos for g in groups for pos in g)
                self.assertEqual(flat, list(range(min(20, len(p.cands)))))
        # a huge gap gives one cluster, a zero gap gives all singletons
        p = self.pres[0]
        self.assertEqual(len(clusters(p, 20, 10.0)), 1)
        self.assertEqual(len(clusters(p, 20, -1.0)), min(20, len(p.cands)))

    def test_routers_obey_their_parameters(self):
        p = self.pres[0]
        self.assertEqual(len(route_p0(p, 4)), 4)
        self.assertEqual(route_p1b(p, 10.0, 0.5, 10), [])  # floor above any score
        self.assertEqual(route_p2(p, 10.0, 20, 0.9, 0.5, 0.5, 5), [])
        self.assertTrue(set(route_p1b(p, 0, 0.5, 10)) <= set(range(10)))
        for pos_list in (route_p2(p, 0, 20, 0.8, 0.5, 0.5, 3),):
            self.assertEqual(len(pos_list), len(set(pos_list)))

    def test_recall_and_tokens_accounting(self):
        tokens, recalls, waste = run_router("P0", {"k": 3}, self.pres)
        for p, t, r, w in zip(self.pres, tokens, recalls, waste):
            self.assertEqual(t, sum(p.costs[:3]))
            self.assertEqual(r is None, p.need_count == 0)
            self.assertLessEqual(w, t)
        all_tokens, all_recalls, _ = run_router("P0", {"k": 50}, self.pres)
        self.assertGreaterEqual(sum(r for r in all_recalls if r is not None),
                                sum(r for r in recalls if r is not None))


class LedgerTests(unittest.TestCase):
    def test_records_time_tokens_and_ops(self):
        ledger = Ledger()
        with ledger.stage("work", tokens=5) as s:
            time.sleep(0.01)
            s["ops"] = 7
        ledger.add("other", ms=1.0, tokens=2, ops=3)
        summary = ledger.summary()
        self.assertEqual(summary["work"]["count"], 1)
        self.assertGreaterEqual(summary["work"]["median_ms"], 10)
        self.assertEqual((summary["work"]["tokens"], summary["work"]["ops"]), (5, 7))
        self.assertEqual(summary["other"]["tokens"], 2)

    def test_records_even_when_the_block_fails(self):
        ledger = Ledger()
        with self.assertRaises(ValueError):
            with ledger.stage("boom"):
                raise ValueError
        self.assertEqual(ledger.summary()["boom"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
