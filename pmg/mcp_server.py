"""PMG as an MCP server, so any MCP client (Claude Desktop, Claude Code, Cursor, ...) can use the memory layer.

Works with both the 1.x (FastMCP) and 2.x (MCPServer) versions of the `mcp` package.
"""
from __future__ import annotations

import json
from typing import Optional

from . import rules as rules_mod
from .llm import Completer, from_env
from .store import Memory

INSTRUCTIONS = (
    "Persistent memory layer. At the start of each user turn, call memory_retrieve with the user's message "
    "and follow what it returns. When the user shares a durable fact, preference or instruction, call "
    "memory_remember. If a memory ends with (#n short), it is a shortened form: call memory_expand(n) when you "
    "need the full detail. Do not call these for one-off questions that need no personal context."
)


def build_server(memory: Optional[Memory] = None, complete: Optional[Completer] = None,
                 host: str = "127.0.0.1", port: int = 8765):
    """Create the MCP server with its tools registered. Returns (server, is_v2)."""
    memory = memory or Memory()
    complete = complete if complete is not None else from_env()
    try:
        from mcp.server.mcpserver import MCPServer  # mcp 2.x

        server, v2 = MCPServer("pmg", instructions=INSTRUCTIONS), True
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP  # mcp 1.x

            server, v2 = FastMCP("pmg", instructions=INSTRUCTIONS, host=host, port=port), False
        except ImportError as err:
            raise SystemExit("The MCP server needs the 'mcp' package. Install it with: pip install mcp") from err

    @server.tool()
    def memory_retrieve(query: str, budget_tokens: int = 0) -> str:
        """Return the few stored memory chunks relevant to `query`, within a token budget (0 = default)."""
        return memory.retrieve(query, budget_tokens)["text"] or "(no relevant memory)"

    @server.tool()
    def memory_remember(text: str, kind: str = "") -> str:
        """Store a durable fact, preference or behavior instruction. `kind` is optional."""
        if kind in rules_mod.load()["kinds"]:
            cid = memory.add(kind, text)
        else:
            cid = memory.ingest(text, complete)
        return f"stored #{cid}" if cid else "not stored (nothing durable, or it looked like a secret)"

    @server.tool()
    def memory_expand(chunk_id: int) -> str:
        """Return the full stored text of a chunk and the original messages it came from (nothing is shortened)."""
        found = memory.expand(chunk_id)
        return json.dumps(found, indent=1) if found else "no such chunk"

    @server.tool()
    def memory_forget(chunk_id: int) -> str:
        """Delete one stored chunk by id (see memory_list)."""
        return "forgotten" if memory.forget(chunk_id) else "no such chunk"

    @server.tool()
    def memory_list(limit: int = 50) -> str:
        """List stored chunks (id, kind, text) so the user can review or delete them."""
        rows = [{k: r[k] for k in ("id", "kind", "text", "key", "importance", "uses")} for r in memory.list(limit)]
        return json.dumps(rows, indent=1)

    @server.tool()
    def memory_tune(apply: bool = False) -> str:
        """Ask the configured LLM to propose better rule settings; they are applied only if apply=true."""
        if not complete:
            return "No LLM configured. Set PMG_LLM_BASE_URL and PMG_LLM_MODEL to enable tuning."
        proposal = memory.propose_rules(complete)
        applied = rules_mod.apply_numeric({k: v for k, v in proposal.items() if k != "why"}) if apply else {}
        return json.dumps({"applied": applied, **proposal})

    return server, v2


def run(http: bool = False, host: str = "127.0.0.1", port: int = 8765) -> None:
    server, v2 = build_server(host=host, port=port)
    if not http:
        server.run()
    elif v2:
        server.run(transport="streamable-http", host=host, port=port)
    else:
        server.run(transport="streamable-http")
