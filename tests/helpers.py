"""Test helpers: isolate every test in its own PMG_DATA directory."""
import os
import shutil
import tempfile
import unittest


class IsolatedTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="pmg-test-")
        self._saved = {k: os.environ.get(k) for k in ("PMG_DATA", "PMG_RULES")}
        os.environ["PMG_DATA"] = self._dir
        os.environ.pop("PMG_RULES", None)
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self._dir, ignore_errors=True)
