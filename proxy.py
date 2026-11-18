"""PMG as a drop-in OpenAI-compatible proxy, for routers/frameworks that don't speak MCP
(OpenRouter, OmniRoute, LiteLLM, LangChain, any OpenAI SDK client).

Point the client's base URL at this proxy. Per request it:
  1. retrieves the few relevant memory chunks and adds them as one system message,
  2. forwards the request unchanged to the real upstream (your key is passed through),
  3. afterwards classifies the user's message and stores it if durable.
There is no chat UI and no model of its own.

  PMG_UPSTREAM_URL=https://openrouter.ai/api/v1 uvicorn proxy:app --port 8766
"""
import os
import threading

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

import pmg_core

UPSTREAM = os.environ.get("PMG_UPSTREAM_URL", "https://openrouter.ai/api/v1").rstrip("/")
memory = pmg_core.Memory()
complete = pmg_core.llm_from_env()
app = FastAPI()

_SKIP = {"host", "content-length", "accept-encoding", "connection"}


def _fwd_headers(req: Request) -> dict:
    return {k: v for k, v in req.headers.items() if k.lower() not in _SKIP}


def _last_user_text(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return ""


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    messages = body.get("messages", [])
    user_text = _last_user_text(messages)
    if user_text:
        block = memory.retrieve(user_text)["text"]
        if block:
            body["messages"] = [{"role": "system", "content": block}, *messages]
        threading.Thread(target=memory.ingest, args=(user_text, complete), daemon=True).start()

    headers = _fwd_headers(req)
    url = f"{UPSTREAM}/chat/completions"
    if body.get("stream"):
        client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
        up = await client.send(client.build_request("POST", url, json=body, headers=headers), stream=True)

        async def gen():
            try:
                async for chunk in up.aiter_raw():
                    yield chunk
            finally:
                await up.aclose()
                await client.aclose()

        return StreamingResponse(gen(), status_code=up.status_code,
                                 media_type=up.headers.get("content-type", "text/event-stream"))
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        up = await client.post(url, json=body, headers=headers)
    return Response(up.content, status_code=up.status_code, media_type=up.headers.get("content-type"))


@app.get("/v1/models")
async def models(req: Request):
    async with httpx.AsyncClient(timeout=30.0) as client:
        up = await client.get(f"{UPSTREAM}/models", headers=_fwd_headers(req))
    return Response(up.content, status_code=up.status_code, media_type=up.headers.get("content-type"))
