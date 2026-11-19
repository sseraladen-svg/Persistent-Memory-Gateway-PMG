import json
import unittest

from pmg import classify, rules
from pmg.store import Memory

from helpers import IsolatedTestCase


class ClassifierTests(IsolatedTestCase):
    def test_only_durable_messages_are_stored(self):
        m = Memory()
        self.assertIsNone(m.ingest("what is the weather today"))
        self.assertIsNotNone(m.ingest("Remember that my dog is named Biscuit"))
        self.assertEqual(m.list()[0]["text"], "my dog is named Biscuit")

    def test_secrets_are_never_stored(self):
        m = Memory()
        for text in ("remember my password is hunter2",
                     "remember this key sk-abcdefghijklmnop12345",
                     "remember card 4111 1111 1111 1111"):
            self.assertIsNone(m.ingest(text), text)

    def test_llm_answer_is_validated_with_fallback(self):
        r = rules.load()
        good = lambda p: ('{"store": true, "kind": "fact", "text": "user lives in Madurai", '
                          '"tags": "city madurai", "importance": 4, "key": "user.city"}')
        v = classify.by_llm("I moved to Madurai", r, good)
        self.assertEqual((v["kind"], v["key"], v["importance"]), ("fact", "user.city", 4))
        self.assertFalse(classify.by_llm("hello there", r, lambda p: '{"store": true, "kind": "hack", "text": "x y z"}')["store"])
        self.assertTrue(classify.by_llm("remember I like tea", r, lambda p: "not json")["store"])
        leaky = lambda p: '{"store": true, "kind": "fact", "text": "key is sk-abcdefghijklmnop12345"}'
        self.assertFalse(classify.by_llm("remember it", r, leaky)["store"])


class RetrievalTests(IsolatedTestCase):
    def test_relevant_and_small(self):
        m = Memory()
        for t in ["remember my dog is named Biscuit", "remember I work as a nurse in Madurai",
                  "remember my favorite tea is masala chai", "from now on answer in short sentences"]:
            m.ingest(t)
        r = m.retrieve("what should I feed my dog?")
        texts = [c["text"] for c in r["chunks"]]
        self.assertIn("my dog is named Biscuit", texts)
        self.assertNotIn("I work as a nurse in Madurai", texts)
        self.assertTrue(any("short sentences" in t for t in texts), "behavior rules always load")
        self.assertLessEqual(r["tokens"], rules.load()["budget_tokens"])

    def test_stemming_matches_word_forms(self):
        m = Memory()
        m.add("fact", "I enjoy running along the river every morning")
        self.assertEqual(len(m.retrieve("suggest a good run route")["chunks"]), 1)

    def test_token_budget_is_enforced(self):
        m = Memory()
        for i in range(40):
            m.add("fact", f"coffee fact number {i} " + "word " * 20)
        self.assertLessEqual(m.retrieve("coffee", budget_tokens=60)["tokens"], 60)

    def test_key_replaces_old_value(self):
        m = Memory()
        m.add("fact", "user lives in Chennai", key="user.city")
        m.add("fact", "user lives in Madurai", key="user.city")
        self.assertEqual([c["text"] for c in m.list()], ["user lives in Madurai"])
        self.assertEqual(m.retrieve("where does the user live")["chunks"][0]["text"], "user lives in Madurai")

    def test_duplicates_merge_and_forget_removes_from_search(self):
        m = Memory()
        a = m.add("fact", "I like green tea")
        b = m.add("fact", "  i LIKE green   tea ")
        self.assertEqual(a, b)
        self.assertTrue(m.forget(a))
        self.assertEqual(m.retrieve("green tea")["chunks"], [])


class StatsTests(IsolatedTestCase):
    def test_saved_percent_reflects_selective_loading(self):
        m = Memory()
        for i in range(30):
            m.add("fact", f"unrelated note number {i} about topic{i} " + "filler " * 10)
        m.add("fact", "my dog is named Biscuit")
        m.retrieve("tell me about my dog")
        s = m.stats()
        self.assertEqual(s["chunks"], 31)
        self.assertEqual(s["requests"], 1)
        self.assertGreater(s["saved_percent"], 90)

    def test_unlogged_retrieval_leaves_stats_alone(self):
        m = Memory()
        m.add("fact", "my dog is named Biscuit")
        m.retrieve("dog", log=False)
        self.assertEqual(m.stats()["requests"], 0)


class RulesTests(IsolatedTestCase):
    def test_default_rules_are_valid_and_copied_to_data_dir(self):
        self.assertEqual(rules.validate(rules.load()), [])

    def test_invalid_rules_are_rejected_with_reasons(self):
        bad = rules.load()
        bad["budget_tokens"] = 5
        bad["never_store_patterns"] = ["(unclosed"]
        problems = rules.validate(bad)
        self.assertTrue(any("budget_tokens" in p for p in problems))
        self.assertTrue(any("never_store_patterns" in p for p in problems))
        with self.assertRaises(ValueError):
            rules.save(bad)

    def test_tuning_proposal_is_clamped_and_whitelisted(self):
        m = Memory()
        m.add("fact", "a b c fact")
        out = m.propose_rules(lambda p: '{"budget_tokens": 99999, "max_chunks": 4, "evil": 1, "why": "x"}')
        self.assertEqual(out, {"max_chunks": 4, "why": "x"})
        self.assertEqual(rules.apply_numeric({"max_chunks": 4, "evil": 1, "budget_tokens": 1}), {"max_chunks": 4})
        self.assertEqual(rules.load()["max_chunks"], 4)


if __name__ == "__main__":
    unittest.main()
