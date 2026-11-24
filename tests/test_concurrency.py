"""The proxy, the MCP server and the dashboard are separate processes or threads on one database."""
import multiprocessing
import os
import threading
import unittest

from pmg.store import Memory

from helpers import IsolatedTestCase


def _writer(data_dir, worker, n):
    os.environ["PMG_DATA"] = data_dir
    m = Memory()
    for i in range(n):
        m.ingest(f"Remember that worker {worker} noted item number {i} about project zebra{worker}x{i}")


class ThreadTests(IsolatedTestCase):
    def run_threads(self, targets):
        errors = []

        def wrap(fn):
            def go():
                try:
                    fn()
                except Exception as err:  # noqa: BLE001
                    errors.append(repr(err))
            return go

        threads = [threading.Thread(target=wrap(t)) for t in targets]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        return errors

    def test_many_writers_and_readers_at_once_lose_nothing(self):
        m = Memory()
        writers = [lambda w=w: [m.ingest(f"Remember that thread {w} stored fact {i} about zebra{w}x{i}") for i in range(40)]
                   for w in range(6)]
        readers = [lambda: [m.retrieve("zebra fact thread") for _ in range(40)] for _ in range(3)]
        errors = self.run_threads(writers + readers)
        self.assertEqual(errors, [])
        self.assertEqual(m.stats()["chunks"], 6 * 40)
        self.assertEqual(m.stats()["raw_messages"], 6 * 40)

    def test_many_writers_replacing_the_same_fact_leave_exactly_one(self):
        m = Memory()
        errors = self.run_threads([lambda w=w: [m.add("fact", f"the deadline is March {w}{i}", key="deadline")
                                               for i in range(15)] for w in range(8)])
        self.assertEqual(errors, [])
        self.assertEqual(len([c for c in m.list() if c["key"] == "deadline"]), 1)

    def test_many_writers_storing_the_same_text_leave_exactly_one(self):
        m = Memory()
        errors = self.run_threads([lambda: [m.add("fact", "my dog is named Biscuit") for _ in range(20)] for _ in range(8)])
        self.assertEqual(errors, [])
        self.assertEqual(m.stats()["chunks"], 1)


class ProcessTests(IsolatedTestCase):
    def test_separate_processes_share_one_database_safely(self):
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=_writer, args=(self._dir, w, 30)) for w in range(4)]
        for p in procs:
            p.start()
        reader_errors = []
        m = Memory()
        for _ in range(30):  # read while the writers run
            try:
                m.retrieve("project zebra")
            except Exception as err:  # noqa: BLE001
                reader_errors.append(repr(err))
        for p in procs:
            p.join(120)
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(reader_errors, [])
        self.assertEqual(m.stats()["chunks"], 4 * 30)


if __name__ == "__main__":
    unittest.main()
