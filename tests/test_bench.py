import json
import os
import tempfile
import unittest

from pmg import bench
from pmg.cli import main

from helpers import IsolatedTestCase

MESSAGES = ["Priya: the deadline for the audit is March 3", "Ravi: lunch was great today", "Priya: we use PostgreSQL for the ledger",
            "Ravi: the weather is hot in Chennai", "Priya: Ravi owns the zebra migration project"]


def generic():
    return {"cases": [{"messages": MESSAGES, "questions": [
        {"q": "when is the audit deadline", "needed": [0]},
        {"q": "who owns the zebra migration", "answers": ["Ravi owns"]},
        {"q": "what is the meaning of life", "needed": [], "abstain": True}]}]}


class BenchTests(IsolatedTestCase):
    def test_generic_run_reports_every_policy_and_finds_the_needed_message(self):
        rep = bench.run(bench.from_generic(generic()))
        self.assertEqual(rep["questions"], 3)
        rows = {r["policy"]: r for r in rep["rows"]}
        self.assertEqual(set(rows), {*bench.POLICIES, *(f"top-{k} +-1" for k in bench.WINDOW_K), "product (budget 400)"})
        self.assertEqual(rows["top-3"]["recall"], 1.0)
        self.assertLess(rows["top-1"]["mean_tokens"], rows["top-20"]["mean_tokens"] + 1e-9)
        self.assertEqual(rows["top-3"]["mean_tokens_on_unanswerable"], 0)  # nothing matches "meaning of life"
        self.assertIn("top-3", bench.format_report(rep))

    def test_duplicate_messages_keep_chunk_ids_aligned(self):
        data = {"cases": [{"messages": ["same line here", "same line here", "the audit deadline is March 3"],
                           "questions": [{"q": "audit deadline", "needed": [2]}]}]}
        rows = {r["policy"]: r for r in bench.run(bench.from_generic(data))["rows"]}
        self.assertEqual(rows["top-1"]["recall"], 1.0)

    def test_locomo_adapter_maps_evidence_to_messages(self):
        sample = [{"conversation": {"speaker_a": "A", "speaker_b": "B", "session_1": [
            {"speaker": "A", "dia_id": "D1:1", "text": "I adopted a dog named Biscuit"},
            {"speaker": "B", "dia_id": "D1:2", "text": "nice"}]},
            "qa": [{"question": "What is the dog called?", "answer": "Biscuit", "evidence": ["D1:1"], "category": 1},
                   {"question": "Unanswerable?", "evidence": [], "category": 5}]}]
        cases = bench.from_locomo(sample)
        self.assertEqual(cases[0]["questions"], [{"q": "What is the dog called?", "needed": [0], "answers": ["Biscuit"]}])
        self.assertEqual(cases[0]["skipped"], 1)

    def test_longmemeval_adapter_uses_has_answer_and_abstain(self):
        data = [{"question_id": "q1", "question": "Where do I live?", "haystack_sessions": [[
            {"role": "user", "content": "I live in Pune", "has_answer": True}, {"role": "assistant", "content": "ok"}]]},
            {"question_id": "q2_abs", "question": "What is my pet's name?", "haystack_sessions": [[
                {"role": "user", "content": "hello"}]]}]
        cases = bench.from_longmemeval(data)
        self.assertEqual(cases[0]["questions"][0]["needed"], [0])
        self.assertTrue(cases[1]["questions"][0]["abstain"])

    def test_cli_bench_and_format_detection(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "d.json")
            with open(path, "w") as f:
                json.dump(generic(), f)
            self.assertEqual(main(["bench", path, "--json", os.path.join(d, "out.json")]), 0)
            with open(os.path.join(d, "out.json")) as f:
                self.assertEqual(json.load(f)["questions"], 3)
            with open(os.path.join(d, "bad.json"), "w") as f:
                f.write("[]")
            self.assertEqual(main(["bench", os.path.join(d, "bad.json")]), 2)


if __name__ == "__main__":
    unittest.main()
