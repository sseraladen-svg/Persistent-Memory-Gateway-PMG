import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["PMG_DATA"] = _tmp
shutil.copy(Path(__file__).parent / "rules.json", Path(_tmp) / "rules.json")
os.environ["PMG_RULES"] = str(Path(_tmp) / "rules.json")

import pmg_core  # noqa: E402


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.m = pmg_core.Memory(Path(_tmp) / f"{self.id()}.db")

    def test_rule_classifier_stores_only_durable_triggers(self):
        self.assertIsNone(self.m.ingest("what is the weather today"))
        cid = self.m.ingest("Remember that my dog is named Biscuit")
        self.assertIsNotNone(cid)
        self.assertEqual(self.m.list()[0]["text"], "my dog is named Biscuit")

    def test_secrets_never_stored(self):
        self.assertIsNone(self.m.ingest("remember my password is hunter2"))
        self.assertIsNone(self.m.ingest("remember this key sk-abcdefghijklmnop12345"))
        self.assertIsNone(self.m.ingest("remember card 4111 1111 1111 1111"))

    def test_retrieval_is_relevant_and_small(self):
        for t in ["remember my dog is named Biscuit", "remember I work as a nurse in Madurai",
                  "remember my favorite tea is masala chai", "from now on answer in short sentences"]:
            self.m.ingest(t)
        r = self.m.retrieve("what should I feed my dog?")
        texts = [c["text"] for c in r["chunks"]]
        self.assertIn("my dog is named Biscuit", texts)
        self.assertNotIn("I work as a nurse in Madurai", texts)
        self.assertTrue(any("short sentences" in t for t in texts), "behavior rules always load")
        self.assertLessEqual(r["tokens"], pmg_core.load_rules()["budget_tokens"])

    def test_token_budget_is_enforced(self):
        for i in range(40):
            self.m.add("fact", f"coffee fact number {i} " + "word " * 20)
        r = self.m.retrieve("coffee", budget_tokens=60)
        self.assertLessEqual(r["tokens"], 60)

    def test_key_replaces_old_value(self):
        self.m.add("fact", "user lives in Chennai", key="user.city")
        self.m.add("fact", "user lives in Madurai", key="user.city")
        texts = [c["text"] for c in self.m.list()]
        self.assertEqual(texts, ["user lives in Madurai"])
        self.assertEqual(self.m.retrieve("where does the user live")["chunks"][0]["text"], "user lives in Madurai")

    def test_duplicate_and_forget(self):
        a = self.m.add("fact", "I like green tea")
        b = self.m.add("fact", "  i LIKE green   tea ")
        self.assertEqual(a, b)
        self.assertTrue(self.m.forget(a))
        self.assertEqual(self.m.retrieve("green tea")["chunks"], [])

    def test_llm_classifier_is_validated_with_fallback(self):
        rules = pmg_core.load_rules()
        good = lambda p: '{"store": true, "kind": "fact", "text": "user lives in Madurai", "tags": "city madurai", "importance": 4, "key": "user.city"}'
        v = pmg_core.classify_llm("I moved to Madurai", rules, good)
        self.assertEqual((v["kind"], v["key"], v["importance"]), ("fact", "user.city", 4))
        bad_kind = lambda p: '{"store": true, "kind": "hack", "text": "x y z"}'
        self.assertFalse(pmg_core.classify_llm("hello there", rules, bad_kind)["store"])
        self.assertTrue(pmg_core.classify_llm("remember I like tea", rules, lambda p: "garbage")["store"])
        leaky = lambda p: '{"store": true, "kind": "fact", "text": "key is sk-abcdefghijklmnop12345"}'
        self.assertFalse(pmg_core.classify_llm("remember it", rules, leaky)["store"])

    def test_propose_rules_clamps_values(self):
        self.m.add("fact", "a b c fact")
        out = self.m.propose_rules(lambda p: '{"budget_tokens": 99999, "max_chunks": 4, "evil": 1, "why": "x"}')
        self.assertEqual(out, {"max_chunks": 4, "why": "x"})


if __name__ == "__main__":
    unittest.main()
