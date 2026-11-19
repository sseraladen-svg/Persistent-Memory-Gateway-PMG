"""MCP tools and the command line."""
import asyncio
import contextlib
import io
import json
import unittest

from pmg import cli
from pmg.store import Memory

from helpers import IsolatedTestCase

try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


class CliTests(IsolatedTestCase):
    def test_add_search_list_stats_forget(self):
        code, out = run_cli("add", "remember", "that", "my", "dog", "is", "named", "Biscuit")
        self.assertEqual(code, 0)
        self.assertIn("Stored as #1", out)
        self.assertEqual(run_cli("add", "what", "is", "the", "weather")[0], 1)
        _, out = run_cli("search", "what", "should", "my", "dog", "eat")
        self.assertIn("Biscuit", out)
        self.assertIn("1 chunks", out)
        _, out = run_cli("list")
        self.assertIn("my dog is named Biscuit", out)
        self.assertIn("Chunks:", run_cli("stats")[1])
        self.assertEqual(run_cli("forget", "1")[0], 0)
        self.assertEqual(run_cli("forget", "1")[0], 1)

    def test_add_with_kind_stores_as_is(self):
        self.assertEqual(run_cli("add", "--kind", "preference", "likes", "masala", "chai")[0], 0)
        self.assertEqual(Memory().list()[0]["kind"], "preference")

    def test_rules_command_reports_valid(self):
        code, out = run_cli("rules")
        self.assertEqual(code, 0)
        self.assertIn("valid", out)


@unittest.skipUnless(HAVE_MCP, "mcp package not installed")
class McpTests(IsolatedTestCase):
    def test_tools_are_registered_and_work(self):
        from pmg.mcp_server import build_server

        server, _ = build_server(Memory(), complete=None)

        async def go():
            names = {t.name for t in await server.list_tools()}
            await server.call_tool("memory_remember", {"text": "remember my dog is named Biscuit"})
            result = await server.call_tool("memory_retrieve", {"query": "what should my dog eat"})
            return names, str(result)

        names, result = asyncio.run(go())
        self.assertEqual(names, {"memory_retrieve", "memory_remember", "memory_forget", "memory_list", "memory_tune"})
        self.assertIn("Biscuit", result)


if __name__ == "__main__":
    unittest.main()
