"""Experimental: replace a note when only a trailing number or date changes (E8, off by default)."""
import unittest

from pmg.store import Memory
from pmg.textutil import replaces

from helpers import IsolatedTestCase


class ReplacesTests(unittest.TestCase):
    def test_a_changed_trailing_number_or_date_replaces(self):
        self.assertTrue(replaces("Kavrotel deadline is March 10", "Kavrotel deadline is March 3"))
        self.assertTrue(replaces("Kavrotel deadline is April 10", "Kavrotel deadline is March 3"))
        self.assertTrue(replaces("audit budget is 7", "audit budget is 5"))

    def test_changes_that_could_be_a_different_slot_do_not_replace(self):
        self.assertFalse(replaces("Ravi budget is 5", "Priya budget is 5"))                      # different person
        self.assertFalse(replaces("Kavrotel sprint 4 deadline is March 5", "Kavrotel sprint 3 deadline is March 5"))
        self.assertFalse(replaces("Kavrotel budget for 2026 is 5", "Kavrotel budget for 2025 is 5"))
        self.assertFalse(replaces("Kavrotel owner is Ravi", "Kavrotel owner is Priya"))          # textual value
        self.assertFalse(replaces("Kavrotel deadline is now March 10", "Kavrotel deadline is March 3"))
        self.assertFalse(replaces("deadline is March 10", "deadline is March 3"))                # too little shared
        self.assertFalse(replaces("Kavrotel deadline is March 3", "Kavrotel deadline is March 3"))


class MemoryTests(IsolatedTestCase):
    def test_off_by_default(self):
        m = Memory()
        m.add("fact", "Kavrotel deadline is March 3")
        m.add("fact", "Kavrotel deadline is March 10")
        self.assertEqual(m.stats()["chunks"], 2)

    def test_when_on_the_old_value_is_replaced_and_its_message_is_kept(self):
        m = Memory()
        m.supersede = True
        first = m.ingest("Remember that Kavrotel deadline is March 3")
        second = m.ingest("Remember that Kavrotel deadline is March 10")
        self.assertEqual(first, second)
        self.assertEqual(m.stats()["chunks"], 1)
        found = m.expand(first)
        self.assertEqual(found["text"], "Kavrotel deadline is March 10")
        self.assertEqual([r["text"] for r in found["raw"]],
                         ["Remember that Kavrotel deadline is March 10", "Remember that Kavrotel deadline is March 3"])
        self.assertNotIn("March 3", m.retrieve("Kavrotel deadline", log=False)["text"].replace("March 10", ""))

    def test_a_different_kind_is_never_replaced(self):
        m = Memory()
        m.supersede = True
        m.add("fact", "Kavrotel deadline is March 3")
        m.add("preference", "Kavrotel deadline is March 10")
        self.assertEqual(m.stats()["chunks"], 2)


if __name__ == "__main__":
    unittest.main()
