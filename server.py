import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import memory

MODEL = "llama3.1:8b"
OLLAMA = "http://localhost:11434/api/chat"
ROOT = Path(__file__).parent

OLLAMA_OPTS = {
    "num_ctx": 2048,
    "num_predict": 300,
    "temperature": 0.6,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
}

# Long read timeout — first token can be slow on CPU
OLLAMA_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)


async def _warm_ollama(client: httpx.AsyncClient):
    try:
        await client.post(
            OLLAMA,
            json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
    except httpx.HTTPError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = httpx.AsyncClient(timeout=OLLAMA_TIMEOUT)
    app.state.http = client
    asyncio.create_task(_warm_ollama(client))
    yield
    await client.aclose()


app = FastAPI(lifespan=lifespan)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=ROOT), name="static")


class ChatRequest(BaseModel):
    message: str
    session_id: str


def build_messages(history: list):
    learned = memory.get_learned_context()
    messages = [{"role": "system", "content": memory.SYSTEM}]
    if learned:
        messages.append({"role": "system", "content": learned})
    messages.extend(history)
    return messages


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
async def health():
    ollama_ok = False
    try:
        r = await app.state.http.get("http://localhost:11434/api/tags", timeout=3)
        ollama_ok = r.status_code == 200
    except httpx.HTTPError:
        pass
    return {"ollama": ollama_ok, **memory.status()}


@app.get("/api/memory")
def list_memory():
    return {"learned": memory.get_learned_facts()}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    learned_cat, history = await asyncio.gather(
        asyncio.to_thread(memory.learn_from_message, req.message),
        asyncio.to_thread(memory.get_history, req.session_id, 6),
    )
    await asyncio.to_thread(memory.save_message, req.session_id, "user", req.message)
    history = history + [{"role": "user", "content": req.message}]
    messages = build_messages(history)

    headers = {"X-Learned": learned_cat} if learned_cat else {}

    async def stream():
        reply = ""
        try:
            async with app.state.http.stream(
                "POST",
                OLLAMA,
                json={
                    "model": MODEL,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": "30m",
                    "options": OLLAMA_OPTS,
                },
            ) as res:
                res.raise_for_status()
                async for line in res.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        reply += token
                        yield token
        except httpx.HTTPError as e:
            yield f"\n[Error: {type(e).__name__} — is Ollama running?]"
            return
        if reply:
            await asyncio.to_thread(memory.save_message, req.session_id, "assistant", reply)
            await asyncio.to_thread(memory.cache_session, req.session_id, history)

    return StreamingResponse(stream(), media_type="text/plain", headers=headers)
