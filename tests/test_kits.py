import unittest

from pmg import ann, bench, bench_llm
from pmg.cli import build_parser

from helpers import IsolatedTestCase

MESSAGES = ["Priya: the deadline for the audit is March 3", "Ravi: lunch was great today", "Priya: we use PostgreSQL for the ledger",
            "Ravi: the weather is hot in Chennai", "Priya: Ravi owns the zebra migration project"]
DATA = {"cases": [{"messages": MESSAGES, "questions": [
    {"q": "when is the audit deadline", "needed": [0], "answers": ["March 3"]},
    {"q": "who owns the zebra migration", "needed": [4], "answers": ["Ravi"]}]}]}


def hashing_embedder(texts):
    import numpy as np
    out = np.zeros((len(texts), 64), dtype="float32")
    for i, t in enumerate(texts):
        for w in t.lower().split():
            out[i, hash(w.strip(":,.")) % 64] += 1
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(n == 0, 1, n)


class KitTests(IsolatedTestCase):
    def test_bench_with_embedder_adds_embedding_and_hybrid_rows(self):
        rep = bench.run(bench.from_generic(DATA), embedder=hashing_embedder)
        names = {r["policy"] for r in rep["rows"]}
        self.assertTrue(any("emb" in n for n in names))
        self.assertTrue(any("hybrid" in n for n in names))
        self.assertIn("top-3", bench.format_report(rep))

    def test_ivf_with_all_clusters_probed_matches_exact_search(self):
        import numpy as np
        rng = np.random.default_rng(1)
        v = rng.normal(size=(200, 16)).astype("float32")
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        rows = ann.ivf_report(v, v[:10], nprobes=(1, 100000), k=5)
        self.assertEqual(rows[-1]["overlap_at_k"], 1.0)
        self.assertLessEqual(rows[0]["scanned_fraction"], rows[-1]["scanned_fraction"])

    def test_bench_llm_runs_with_a_fake_model(self):
        def complete(prompt):
            return "March 3" if "audit" in prompt and "March 3" in prompt else "Ravi" if "Ravi owns" in prompt else "I don't know"
        rep = bench_llm.run(bench.from_generic(DATA), complete, limit=5)
        self.assertEqual(rep["questions"], 2)
        rows = {r["condition"]: r for r in rep["rows"]}
        self.assertEqual(rows["no memory"]["accuracy"], 0.0)
        self.assertEqual(rows["cutoff 0.5"]["accuracy"], 1.0)
        self.assertLess(rows["cutoff 0.5"]["mean_prompt_tokens"], rows["full history"]["mean_prompt_tokens"] + 1)
        self.assertIn("accuracy", bench_llm.format_report(rep))

    def test_is_correct(self):
        self.assertTrue(bench_llm.is_correct("It is on March 3.", ["March 3"]))
        self.assertFalse(bench_llm.is_correct("no idea", ["March 3"]))

    def test_cli_accepts_new_options(self):
        p = build_parser()
        a = p.parse_args(["bench", "f.json", "--embeddings", "http", "--ann"])
        self.assertTrue(a.ann)
        b = p.parse_args(["bench-llm", "f.json", "--limit", "3"])
        self.assertEqual(b.limit, 3)

    def test_validate_writes_report_with_e3_verdict(self):
        import json, os
        path = os.path.join(os.environ["PMG_DATA"], "d.json"); out = os.path.join(os.environ["PMG_DATA"], "r.md")
        json.dump(DATA, open(path, "w"))
        from pmg.cli import main
        self.assertEqual(main(["validate", path, "--out", out]), 0)
        report = open(out).read()
        self.assertIn("E3 rule", report)
        self.assertIn("E11", report)


if __name__ == "__main__":
    unittest.main()
