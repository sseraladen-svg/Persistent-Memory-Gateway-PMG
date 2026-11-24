# Changelog

## Unreleased

### Added
- Lossless raw log: every message that is not a secret is kept word for word, and each chunk links to the messages it came from. Replacing a fact keeps the history of what was said.
- Short forms: when a chunk does not fit the token budget it is included as a few-word gist marked `(#id short)` instead of being dropped.
- `memory_expand` MCP tool (and `Memory.expand`) returns the full chunk and its original messages.
- Cost ledger: retrieval time and tokens are recorded per request; the dashboard shows the median time and how many original messages are kept.
- Older databases are upgraded in place when opened.

- `pmg bench` command and `docs/BENCHMARKS.md`: measure tokens loaded and recall on LoCoMo, LongMemEval or a generic file.

- Faster requests on large stores: the stored-token total is kept by SQL triggers instead of summing every chunk on each request, and usage counters and event rows are written in batches (every 25 requests or 2 seconds, on `stats()`/`list()`, and at exit). Median request time at 100,000 chunks fell from 60 ms to 33 ms with identical results.
- Optional word pruning (`Memory.common_df`, off by default) cuts the 100,000-chunk request time to about 14 ms.

### Security
- Text that reads like an instruction to the model ("ignore previous instructions", "reveal your system prompt", "send the data to http://...", fake `</system>` tags) is never stored as a memory, through any door (classifier, CLI, MCP, dashboard). The message is still kept in the raw log but is not reachable from memory.
- A memory longer than 400 characters is not stored (a pasted document is not a durable fact).
- Secrets are now refused by every door, including `memory_remember` with an explicit kind.
- Memory text is rendered on a single line, so a newline cannot forge a new "Follow:" section.

### Fixed
- Concurrent writers could crash with a unique-constraint error when replacing the same fact or storing the same text; writes now take the lock first.
- The rules file is created and saved atomically, so a reader never sees a half-written file.

### Changed
- `forget` now also deletes the raw messages linked to that chunk.

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
