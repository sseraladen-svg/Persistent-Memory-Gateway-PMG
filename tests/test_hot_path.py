"""The request path: running token total and batched usage writes must stay exactly correct."""
import os
import subprocess
import sys
import threading
import unittest

from pmg.store import FLUSH_EVENTS, Memory

from helpers import IsolatedTestCase

SUM_SQL = "SELECT COALESCE(SUM(MAX(1, LENGTH(text) / 4) + 2), 0) FROM chunks"


def total(m):
    with m._db() as c:
        return c.execute("SELECT value FROM meta WHERE key = 'stored_tokens'").fetchone()[0], c.execute(SUM_SQL).fetchone()[0]


def events(m):
    with m._db() as c:
        return c.execute("SELECT COUNT(*) FROM events").fetchone()[0]


class RunningTotalTests(IsolatedTestCase):
    def test_total_matches_a_full_recount_after_every_kind_of_change(self):
        m = Memory()
        a = m.add("fact", "my dog is named Biscuit")
        m.add("fact", "the deadline is March 3", key="deadline")
        m.add("fact", "the deadline is now March 10 for everyone on the team", key="deadline")  # replaces, longer
        b = m.add("preference", "I like masala chai in the morning")
        for _ in range(2):
            self.assertEqual(*total(m))
            m.forget(a)
        m.forget(b)
        self.assertEqual(*total(m))
        self.assertEqual(m.stats()["stored_tokens"], total(m)[1])

    def test_an_old_database_without_the_total_is_upgraded(self):
        m = Memory()
        m.add("fact", "my dog is named Biscuit")
        with m._db() as c:
            c.executescript("DROP TRIGGER chunks_tokens_ins; DROP TRIGGER chunks_tokens_del; "
                            "DROP TRIGGER chunks_tokens_upd; DROP TABLE meta;")
        m2 = Memory(m.db_path)
        m2.add("fact", "the deadline is March 3")
        self.assertEqual(*total(m2))


class BatchedWriteTests(IsolatedTestCase):
    def test_no_usage_is_lost_after_a_flush(self):
        m = Memory()
        m.add("fact", "my dog is named Biscuit")
        for _ in range(7):
            m.retrieve("dog name")
        self.assertEqual(m.stats()["requests"], 7)  # stats() flushes first
        self.assertEqual(m.list()[0]["uses"], 7)

    def test_a_full_batch_is_written_without_being_asked(self):
        m = Memory()
        m.add("fact", "my dog is named Biscuit")
        for _ in range(FLUSH_EVENTS):
            m.retrieve("dog name")
        self.assertEqual(events(m), FLUSH_EVENTS)

    def test_another_process_sees_the_batch_after_a_flush_and_exit_flushes_the_rest(self):
        m = Memory()
        m.add("fact", "my dog is named Biscuit")
        code = ("from pmg.store import Memory\nm = Memory()\nfor _ in range(3): m.retrieve('dog name')\n")
        subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ, "PYTHONPATH": os.getcwd()})
        self.assertEqual(events(m), 3)

    def test_threads_sharing_one_memory_lose_no_events(self):
        m = Memory()
        m.add("fact", "my dog is named Biscuit")
        ts = [threading.Thread(target=lambda: [m.retrieve("dog name") for _ in range(30)]) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(m.stats()["requests"], 120)
        self.assertEqual(m.list()[0]["uses"], 120)

    def test_immediate_mode_gives_the_same_counts(self):
        m = Memory()
        m.defer_writes = False
        m.add("fact", "my dog is named Biscuit")
        for _ in range(5):
            m.retrieve("dog name")
        self.assertEqual(events(m), 5)
        self.assertEqual(m.list()[0]["uses"], 5)


if __name__ == "__main__":
    unittest.main()
