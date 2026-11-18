"""PMG as an MCP server: a memory layer any MCP client can plug in.

  stdio (Claude Desktop, Claude Code, Cursor, ...):  python mcp_server.py
  HTTP  (remote clients / ChatGPT connectors):       python mcp_server.py --http --port 8765
"""
import argparse
import json

import pmg_core

ap = argparse.ArgumentParser()
ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8765)
args, _ = ap.parse_known_args()

INSTRUCTIONS = (
    "Persistent memory layer. At the start of each user turn, call memory_retrieve with the user's message "
    "and follow what it returns. When the user shares a durable fact, preference or instruction, call "
    "memory_remember. Do not call these for one-off questions that need no personal context."
)

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("pmg", instructions=INSTRUCTIONS)
    V2 = True
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("pmg", instructions=INSTRUCTIONS, host=args.host, port=args.port)
    V2 = False

memory = pmg_core.Memory()
complete = pmg_core.llm_from_env()  # optional offline classifier; None = rule-based only


@mcp.tool()
def memory_retrieve(query: str, budget_tokens: int = 0) -> str:
    """Return the few stored memory chunks relevant to `query`, within a token budget (0 = default from rules.json)."""
    return memory.retrieve(query, budget_tokens)["text"] or "(no relevant memory)"


@mcp.tool()
def memory_remember(text: str, kind: str = "") -> str:
    """Store a durable fact, preference or behavior instruction. `kind` is optional: behavior, preference or fact."""
    rules = pmg_core.load_rules()
    if kind in rules["kinds"]:
        cid = memory.add(kind, text.strip())
    else:
        cid = memory.ingest(text, complete)
    return f"stored #{cid}" if cid else "not stored (nothing durable, or it looked like a secret)"


@mcp.tool()
def memory_forget(chunk_id: int) -> str:
    """Delete one stored chunk by id (see memory_list)."""
    return "forgotten" if memory.forget(chunk_id) else "no such chunk"


@mcp.tool()
def memory_list(limit: int = 50) -> str:
    """List stored chunks (id, kind, text) so the user can review or delete them."""
    return json.dumps(memory.list(limit), indent=1)


@mcp.tool()
def memory_tune(apply: bool = False) -> str:
    """Ask the configured LLM to propose better rule settings (token budget, chunk limits). Applies only if apply=true."""
    if not complete:
        return "No LLM configured. Set PMG_LLM_BASE_URL and PMG_LLM_MODEL to enable tuning."
    proposal = memory.propose_rules(complete)
    if apply:
        memory.apply_rules({k: v for k, v in proposal.items() if k != "why"})
    return json.dumps({"applied": apply, **proposal})


if __name__ == "__main__":
    if args.http:
        if V2:
            mcp.run(transport="streamable-http", host=args.host, port=args.port)
        else:
            mcp.run(transport="streamable-http")
    else:
        mcp.run()
