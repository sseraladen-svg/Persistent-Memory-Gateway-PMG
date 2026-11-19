# Integration guide

PMG can plug into your tools in two ways. Both share the same memory, stored locally in `~/.pmg`
(change it with the `PMG_DATA` environment variable).

| You use | Choose |
|---|---|
| Claude Desktop, Claude Code, Cursor or another MCP client | [MCP server](#mcp-server) |
| A router or framework with a configurable OpenAI-compatible base URL (OpenRouter, LiteLLM, LangChain, the OpenAI SDK, ...) | [Proxy](#proxy) |

## Install

```bash
git clone https://github.com/sseraladen-svg/Persistent-Memory-Gateway-PMG
cd Persistent-Memory-Gateway-PMG
pip install -e ".[mcp]"      # drop [mcp] if you only need the proxy, dashboard and CLI
pmg --version
```

PMG itself has no dependencies. The `mcp` extra installs the MCP SDK for the MCP server only.

## MCP server

### Local clients (stdio)

Claude Code:

```bash
claude mcp add pmg -- pmg mcp
```

Claude Desktop, Cursor and others take a JSON entry. Use the full path to `pmg` if it is not on the client's PATH
(`which pmg` on macOS and Linux, `where pmg` on Windows):

```json
{ "mcpServers": { "pmg": { "command": "pmg", "args": ["mcp"] } } }
```

### Remote clients (HTTP)

```bash
pmg mcp --http --port 8765        # endpoint: http://127.0.0.1:8765/mcp
```

It listens on your own machine only. Clients that need a public HTTPS address, such as ChatGPT connectors, can't
reach it directly. If you expose it through a tunnel or hosting, put authentication in front first, because anyone
who can reach it can read and change your memory.

### Tools

| Tool | What it does |
|---|---|
| `memory_retrieve(query, budget_tokens)` | Returns the memories relevant to a message, within a token budget. |
| `memory_remember(text, kind)` | Stores a fact, preference or instruction. Without `kind`, the classifier decides. |
| `memory_forget(chunk_id)` | Deletes one memory. |
| `memory_list(limit)` | Lists what is stored. |
| `memory_tune(apply)` | Asks the optional LLM for better numeric settings; applied only when `apply` is true. |

The server tells the model to call `memory_retrieve` at the start of each turn and `memory_remember` when you share
something durable. How reliably a given model follows that depends on the model and client.

## Proxy

```bash
pmg proxy --upstream https://openrouter.ai/api/v1 --port 8766
```

Then set your client's base URL to `http://127.0.0.1:8766/v1` and keep your normal API key, which is passed through to
the upstream untouched. With the OpenAI Python SDK:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8766/v1", api_key="YOUR_UPSTREAM_KEY")
```

For each chat request the proxy:
1. finds the relevant memories for the last user message and adds them as one system message at the top,
2. forwards the request, streaming included,
3. afterwards classifies the user's message and stores it if it is worth keeping.

Requests to other paths (such as `/v1/models`) pass through unchanged. If the upstream can't be reached, the proxy
answers 502 with a clear message. `GET /health` reports that the proxy itself is running.

## Dashboard

```bash
pmg dashboard
```

Opens `http://127.0.0.1:8787` with three views: a **Playground** that shows which memories a message would load and
how much of the token budget they use, a **Memory** list for adding and deleting, and a **Rules** editor. It only
accepts local connections.

## Optional: a model to classify and tune

By default, keyword rules in `rules.json` decide what to store. To let a model make that decision with more nuance,
point PMG at any OpenAI-compatible endpoint, such as a local Ollama model:

```bash
export PMG_LLM_BASE_URL=http://localhost:11434/v1
export PMG_LLM_MODEL=llama3.1:8b
export PMG_LLM_KEY=...             # only if the endpoint needs one
```

The model never chats with you through PMG. Its answers are checked (allowed kinds, length, secret patterns) and the
rules take over if anything looks wrong.

## Rules

`pmg rules` checks your rules file and shows where it is. The same settings are editable in the dashboard.

| Setting | Meaning |
|---|---|
| `budget_tokens` | Most memory loaded for one request (default 400). |
| `always_load_share` | Part of the budget kept for standing instructions. |
| `max_chunks` | Most memories loaded for one request. |
| `min_chars` | Shortest message worth keeping. |
| `kinds.<name>` | Trigger phrases, ranking `weight`, `always_load`, and `half_life_days` (how fast it fades, or `null`). |
| `never_store_patterns` | Regular expressions for content that must never be saved. |

## Privacy

Your memory is a local SQLite file. Anything PMG adds to a request is sent to whichever model provider you use, just
like the rest of your message, so only store what you are comfortable sharing with that provider. Secret patterns
(API keys, card numbers, passwords) are blocked before storage.

## Troubleshooting

- **`pmg: command not found`.** Run `pip install -e .` again, or use `python -m pmg` instead.
- **MCP client can't start the server.** Use the full path to `pmg`, and confirm `pip show mcp` works in the same environment.
- **Nothing is being remembered.** Check that your phrase matches a trigger (for example "remember that ..."), or store it directly with `pmg add --kind fact "..."`. The rule check `pmg rules` lists problems with your rules file.
- **Reset everything.** Delete the `~/.pmg` folder.
