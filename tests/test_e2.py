"""Sanity tests for the E2 engine: the cascade must be exact when the shortlist is everything."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
import importlib.util

E2 = Path(__file__).resolve().parents[1] / "experiments" / "e2_fingerprint_cascade"
sys.path.append(str(E2.parent / "e1_topology_router"))

import numpy as np  # noqa: E402
from gym import make_gym  # noqa: E402

# E1 and E2 both have a module called `engine`, so load E2's under its own name.
_spec = importlib.util.spec_from_file_location("e2_engine", E2 / "engine.py")
e2 = importlib.util.module_from_spec(_spec)
sys.modules["e2_engine"] = e2
_spec.loader.exec_module(e2)
Fingerprints, Store, bytes_cascade, bytes_exact, cascade_top, exact_top = (
    e2.Fingerprints, e2.Store, e2.bytes_cascade, e2.bytes_exact, e2.cascade_top, e2.exact_top)


class CascadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gym = make_gym(3, n_topics=10, per_topic=50, n_queries=40)
        cls.store = Store(cls.gym.chunks, seed=3)
        cls.fp = Fingerprints(cls.store, 128)

    def test_vectors_are_unit_length(self):
        norms = np.linalg.norm(self.store.vecs, axis=1)
        self.assertTrue(np.allclose(norms, 1.0, atol=1e-4))

    def test_a_vector_matches_its_own_fingerprint_exactly(self):
        i = 17
        ham = np.bitwise_count(self.fp.codes ^ self.fp.sign(self.store.vecs[i][None, :])[0]).sum(axis=1)
        self.assertEqual(int(ham[i]), 0)
        self.assertEqual(self.fp.codes.shape, (len(self.gym.chunks), 2))

    def test_full_shortlist_equals_exact_search(self):
        for q in self.gym.queries[:20]:
            v = self.store.embed_query(q.text)
            if not v.any():
                continue
            exact = exact_top(self.store, v)
            got = cascade_top(self.store, self.fp, v, shortlist=len(self.gym.chunks))
            self.assertEqual(set(exact.tolist()), set(got.tolist()))

    def test_bytes_accounting(self):
        self.assertEqual(bytes_exact(1000), 1000 * 256 * 4)
        self.assertEqual(bytes_cascade(1000, 128, 50), 1000 * 16 + 50 * 1024)
        self.assertLess(bytes_cascade(1000, 128, 50), bytes_exact(1000))


if __name__ == "__main__":
    unittest.main()
