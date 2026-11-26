"""Opt-in evidence rule (E4): load nothing unless chunks hold 2 informative query words or 1 rare one."""
import unittest

from pmg.store import Memory

from helpers import IsolatedTestCase


class EvidenceRuleTests(IsolatedTestCase):
    def store(self):
        m = Memory()
        for i in range(60):
            m.add("fact", f"project note {i} about budget planning item{i}")
        m.add("fact", "the zebra migration is owned by Priya")
        m.add("fact", "budget approval needs Rahul and Meena")
        return m

    def test_off_by_default(self):
        m = self.store()
        self.assertIsNone(m.evidence_rule)
        self.assertGreater(len(m.retrieve("project note", log=False)["chunks"]), 0)

    def test_common_words_alone_load_nothing(self):
        m = self.store()
        m.evidence_rule = (0.1, 3)
        self.assertEqual(m.retrieve("project note budget planning", log=False)["chunks"], [])

    def test_one_rare_word_is_enough(self):
        m = self.store()
        m.evidence_rule = (0.1, 3)
        texts = [c["text"] for c in m.retrieve("who owns the zebra", log=False)["chunks"]]
        self.assertEqual(texts, ["the zebra migration is owned by Priya"])

    def test_two_informative_words_in_one_chunk_are_enough(self):
        m = self.store()
        m.evidence_rule = (0.5, 3)
        texts = [c["text"] for c in m.retrieve("budget approval", log=False)["chunks"]]
        self.assertIn("budget approval needs Rahul and Meena", texts)


if __name__ == "__main__":
    unittest.main()
