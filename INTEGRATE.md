# Using PMG as a memory layer

PMG is not a chatbot here. It sits between you and whatever model you use:
`pmg_core.py` stores and retrieves tiny chunks; `mcp_server.py` and `proxy.py` are two ways to plug it in.
The old chat app (`server.py`, `index.html`, `memory.py`) is untouched and not needed for this.

## Setup
    pip install -r requirements-layer.txt
    python test_core.py

## A. MCP (Claude Desktop / Claude Code / Cursor)
Add to the client's MCP config (use absolute paths):

    { "mcpServers": { "pmg": { "command": "python", "args": ["C:/path/to/mcp_server.py"] } } }

Claude Code: `claude mcp add pmg -- python /path/to/mcp_server.py`

Tools: `memory_retrieve`, `memory_remember`, `memory_forget`, `memory_list`, `memory_tune`.
The server's instructions tell the model to retrieve before answering and remember durable facts.

## B. HTTP MCP (clients that need a URL, such as ChatGPT connectors)
    python mcp_server.py --http --port 8765      # endpoint: http://127.0.0.1:8765/mcp
ChatGPT can only reach public HTTPS URLs, so this needs a tunnel or hosting, plus authentication
before you expose it. Do not publish it open: anyone with the URL could read your memory.

## C. OpenAI-compatible proxy (OpenRouter, OmniRoute, LiteLLM, LangChain, OpenAI SDK)
    set PMG_UPSTREAM_URL=https://openrouter.ai/api/v1
    uvicorn proxy:app --port 8766
Set the client's base URL to `http://127.0.0.1:8766/v1`. Keep using your normal API key; it is passed
through. Each request gets one small system message of relevant memory, and the user's message is
classified and stored afterwards. Works with any model behind the router, so memory is shared across them.

## Where the LLM is used (optional)
Only to classify messages and tune rules, never to chat. Point it at any OpenAI-compatible endpoint,
for example a local Ollama model:

    PMG_LLM_BASE_URL=http://localhost:11434/v1
    PMG_LLM_MODEL=llama3.1:8b

Without it, the keyword rules in `rules.json` decide what is stored. LLM output is validated
(allowed kinds, length, secret patterns) and falls back to the rules on any problem.
`memory_tune` asks the LLM to suggest numbers (token budget, chunk limit); values are clamped, and
applied only when you pass `apply=true`.

## Editing the rules
`rules.json` controls token budget, which kinds always load, kind weights, decay, and never-store patterns.
