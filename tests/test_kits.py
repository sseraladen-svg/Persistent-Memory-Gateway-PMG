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

    def test_empty_or_null_replies_do_not_crash_and_are_flagged(self):
        rep = bench_llm.run(bench.from_generic(DATA), lambda p: None, limit=2)
        self.assertEqual(rep["empty_replies"], rep["calls"])
        self.assertIn("WARNING", bench_llm.format_report(rep))

    def test_server_error_is_reported_not_a_traceback(self):
        import io, os, urllib.error
        from unittest import mock
        from pmg import llm
        err = urllib.error.HTTPError("http://x", 400, "Bad Request", {}, io.BytesIO(b'{"error":"not a valid model ID"}'))
        env = {"PMG_LLM_BASE_URL": "http://x", "PMG_LLM_MODEL": "m"}
        with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                llm.from_env()("hi")
        self.assertIn("not a valid model ID", str(ctx.exception))

    def test_conditions_subset_makes_fewer_calls(self):
        rep = bench_llm.run(bench.from_generic(DATA), lambda p: "March 3", limit=2,
                            conditions=["full history", "product (budget 400)"])
        self.assertEqual(rep["calls"], 4)
        self.assertEqual({r["condition"] for r in rep["rows"]}, {"full history", "product (budget 400)"})

    def test_stride_spreads_the_sample(self):
        data = {"cases": [{"messages": MESSAGES, "questions": [
            {"q": f"when is the audit deadline {i}", "needed": [0], "answers": ["March 3"]} for i in range(6)]}]}
        rep = bench_llm.run(bench.from_generic(data), lambda p: "March 3", limit=10, stride=3, conditions=["product (budget 400)"])
        self.assertEqual(rep["questions"], 2)

    def test_timeout_can_be_set_for_slow_local_models(self):
        import os, io, json
        from unittest import mock
        from pmg import llm
        seen = {}
        def fake(req, timeout=None):
            seen["t"] = timeout
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())
        env = {"PMG_LLM_BASE_URL": "http://localhost:11434/v1", "PMG_LLM_MODEL": "m", "PMG_LLM_TIMEOUT": "300"}
        with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(llm.from_env()("hi"), "ok")
        self.assertEqual(seen["t"], 300.0)

    def test_echo_check_is_skipped_when_cutoff_is_not_run(self):
        rep = bench_llm.run(bench.from_generic(DATA), lambda p: "March 3", limit=2, conditions=["full history"])
        self.assertEqual(rep["echo_check"]["loaded_chunks"], 0)

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

    def test_tokens_at_recall_uses_plain_topk_curve(self):
        from pmg.cli import _tokens_at_recall
        topk = [{"recall": r, "mean_tokens": t} for r, t in
                [(0.316, 39), (0.470, 112), (0.539, 183), (0.618, 359), (0.684, 706)]]
        self.assertAlmostEqual(_tokens_at_recall(topk, 0.595), 307.8, delta=1)
        self.assertAlmostEqual(_tokens_at_recall(topk, 0.650), 527, delta=2)
        self.assertIsNone(_tokens_at_recall(topk, 0.709))  # above the curve: cannot compare

    def test_big_files_are_read_one_item_at_a_time(self):
        import json, os
        from pmg import bench
        items = [{"question_id": f"q{i}", "question": f"what is item {i}", "answer": f"a{i}",
                  "haystack_sessions": [[{"role": "user", "content": f"note {i} " + "x" * 200, "has_answer": True},
                                         {"role": "assistant", "content": "ok"}]]} for i in range(30)]
        path = os.path.join(os.environ["PMG_DATA"], "big.json")
        json.dump(items, open(path, "w"))
        old = bench._BIG_FILE
        bench._BIG_FILE = 100  # force the streaming path on a small file
        try:
            streamed = bench.load_dataset(path)
            small = list(streamed)
            again = list(streamed)  # can be iterated twice
        finally:
            bench._BIG_FILE = old
        self.assertEqual(len(small), 30)
        self.assertEqual(small, again)
        self.assertEqual(small, bench.load_dataset(path))
        tiny = [x for x in bench.iter_json_array(path, block=64)]  # items split across many blocks
        self.assertEqual(len(tiny), 30)


if __name__ == "__main__":
    unittest.main()
