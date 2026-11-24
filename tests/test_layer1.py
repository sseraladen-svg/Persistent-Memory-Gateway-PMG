"""Layer 1: raw log (lossless), gists (short form), expand, upgrade of old databases, cost ledger."""
import sqlite3

from pmg import rules
from pmg.store import Memory
from pmg.textutil import make_gist

from helpers import IsolatedTestCase

LONG = ("Our production database runs PostgreSQL 16 on a managed cluster in the Mumbai region, with nightly "
        "backups at 02:00 IST and a read replica used only by the analytics team for reporting dashboards")


class RawLogTests(IsolatedTestCase):
    def test_every_message_is_kept_word_for_word_even_when_no_chunk_is_made(self):
        m = Memory()
        self.assertIsNone(m.ingest("what is the weather today"))
        self.assertEqual(m.stats()["raw_messages"], 1)

    def test_chunk_links_to_the_original_message(self):
        m = Memory()
        cid = m.ingest("Remember that my dog is named Biscuit")
        found = m.expand(cid)
        self.assertEqual(found["text"], "my dog is named Biscuit")
        self.assertEqual(found["raw"][0]["text"], "Remember that my dog is named Biscuit")

    def test_secrets_never_reach_the_raw_log(self):
        m = Memory()
        m.ingest("remember my password is hunter2")
        self.assertEqual(m.stats()["raw_messages"], 0)

    def test_replacing_a_fact_keeps_the_history_of_what_was_said(self):
        m = Memory()
        a = m.add("fact", "the deadline is March 3", key="deadline", raw_id=m.log_raw("deadline is March 3"))
        b = m.add("fact", "the deadline is March 10", key="deadline", raw_id=m.log_raw("deadline moved to March 10"))
        self.assertEqual(a, b)
        texts = [r["text"] for r in m.expand(a)["raw"]]
        self.assertEqual(texts, ["deadline moved to March 10", "deadline is March 3"])

    def test_forgetting_a_chunk_also_removes_its_source_messages(self):
        m = Memory()
        cid = m.ingest("Remember that my dog is named Biscuit")
        self.assertTrue(m.forget(cid))
        self.assertEqual(m.stats()["raw_messages"], 0)
        self.assertIsNone(m.expand(cid))


class GistTests(IsolatedTestCase):
    def test_short_text_has_no_gist_and_long_text_does(self):
        self.assertIsNone(make_gist("my dog is named Biscuit"))
        gist = make_gist(LONG)
        self.assertTrue(gist.endswith("...") and len(gist.split()) <= 12)

    def test_a_chunk_that_does_not_fit_is_kept_as_a_short_form_not_dropped(self):
        m = Memory()
        cid = m.add("fact", LONG)
        full = m.retrieve("postgresql database backups", budget_tokens=500, log=False)
        self.assertEqual(full["chunks"][0]["level"], "full")
        tight = m.retrieve("postgresql database backups", budget_tokens=full["tokens"] - 5, log=False)
        self.assertEqual(len(tight["chunks"]), 1)
        self.assertEqual(tight["chunks"][0]["level"], "gist")
        self.assertIn(f"(#{cid} short)", tight["text"])
        self.assertLess(tight["tokens"], full["tokens"])
        self.assertEqual(m.expand(cid)["text"], LONG)  # the full detail is one call away

    def test_budget_is_still_a_hard_limit_with_gists(self):
        m = Memory()
        for i in range(8):
            m.add("fact", f"{LONG} variant {i} extra words to make this one unique")
        for budget in (20, 40, 80):
            self.assertLessEqual(m.retrieve("postgresql database backups", budget_tokens=budget, log=False)["tokens"], budget)


class UpgradeAndLedgerTests(IsolatedTestCase):
    def test_an_old_database_is_upgraded_in_place(self):
        m = Memory()
        db = m.db_path
        c = sqlite3.connect(db)
        c.executescript("DROP TABLE raw; ALTER TABLE chunks DROP COLUMN gist; ALTER TABLE chunks DROP COLUMN raw_id; "
                        "ALTER TABLE events DROP COLUMN ms;")
        c.close()
        m2 = Memory(db)  # reopening adds the missing pieces
        cid = m2.ingest("Remember that my dog is named Biscuit")
        self.assertEqual(m2.expand(cid)["raw"][0]["text"], "Remember that my dog is named Biscuit")
        self.assertIn("dog", m2.retrieve("dog name")["text"])

    def test_retrieval_records_time_and_tokens(self):
        m = Memory()
        m.add("fact", "my dog is named Biscuit")
        result = m.retrieve("dog name")
        summary = m.ledger.summary()
        self.assertEqual(summary["retrieve.total"]["tokens"], result["tokens"])
        self.assertIn("retrieve.search", summary)
        self.assertIsNotNone(m.stats()["median_ms"])


class CommonWordPruningTests(IsolatedTestCase):
    def make(self):
        m = Memory()
        m.common_df = 20
        for i in range(60):
            m.add("fact", f"project note {i} about budget item number{i}")
        m.add("fact", "the zebra migration project is owned by Priya")
        return m

    def test_a_very_common_word_is_dropped_but_a_rare_word_still_finds_its_chunk(self):
        m = self.make()
        result = m.retrieve("project zebra", log=False)
        self.assertEqual([c["text"] for c in result["chunks"]], ["the zebra migration project is owned by Priya"])

    def test_a_query_of_only_common_words_returns_nothing_from_search(self):
        m = self.make()
        self.assertEqual(m.retrieve("project note budget", log=False)["chunks"], [])

    def test_switching_it_off_restores_plain_search(self):
        m = self.make()
        m.common_df = 0
        self.assertGreater(len(m.retrieve("project note budget", log=False)["chunks"]), 0)

    def test_small_stores_are_never_pruned_by_default(self):
        m = Memory()
        for i in range(30):
            m.add("fact", f"project note {i} about budget item number{i}")
        self.assertGreater(len(m.retrieve("project", log=False)["chunks"]), 0)
