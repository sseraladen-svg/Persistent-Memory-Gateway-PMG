# Changelog

## 0.2.0

The project is now a memory layer first, and a chat app second.

### Added
- `pmg` command line: `add`, `search`, `list`, `forget`, `stats`, `rules`, `dashboard`, `proxy`, `mcp`.
- Local dashboard with a live token-budget view, memory management and a rules editor.
- MCP server (`memory_retrieve`, `memory_remember`, `memory_forget`, `memory_list`, `memory_tune`) for Claude Desktop, Claude Code, Cursor and other MCP clients.
- OpenAI-compatible proxy for routers and frameworks, with streaming and error pass-through, and no dependencies.
- Word-form matching (a search for "run" finds "running") through stemmed full-text search.
- Usage statistics showing how many tokens were loaded compared with loading everything.
- Slot keys, so a new value replaces an older one instead of contradicting it.
- Rules validation, secret blocking, and a validated, optional LLM classifier that falls back to the rules.
- Test suite (32 tests), CI on Python 3.10 to 3.13, MIT license, `pyproject.toml`.

### Changed
- Storage is a single SQLite file with a full-text index. Redis and ChromaDB are no longer needed.
- The original chat client moved to `legacy/` and is otherwise unchanged.

## 0.1.0

- Multi-provider chat client (Ollama, OpenAI, Anthropic, HuggingFace, custom) with web UI, voice input and keyword-triggered memory.
