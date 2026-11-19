"""OpenAI-compatible proxy that adds memory to any client or router, with no dependencies.

Point a client's base URL at this proxy. For each chat request it
  1. retrieves the few relevant memory chunks and prepends them as one system message,
  2. forwards the request to the real upstream with the client's own credentials,
  3. afterwards classifies the user's message and stores it if it is worth keeping.
Every other request is passed through untouched.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .llm import Completer
from .store import Memory

HOP_BY_HOP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding",
              "keep-alive", "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate"}


def last_user_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return ""


def make_server(upstream: str, memory: Memory, complete: Optional[Completer] = None,
                host: str = "127.0.0.1", port: int = 8766) -> ThreadingHTTPServer:
    upstream = upstream.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        server_version = "pmg-proxy"

        def log_message(self, *args):  # keep the console quiet
            pass

        # -- helpers
        def _target(self) -> str:
            path = self.path
            if path.startswith("/v1/") or path == "/v1":
                path = path[3:]
            return upstream + path

        def _headers(self) -> dict:
            out = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            out["Accept-Encoding"] = "identity"
            return out

        def _send_error(self, status: int, message: str):
            body = json.dumps({"error": {"message": message, "type": "pmg_proxy_error"}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _forward(self, method: str, body: Optional[bytes]):
            req = urllib.request.Request(self._target(), data=body, method=method, headers=self._headers())
            try:
                resp = urllib.request.urlopen(req, timeout=600)
            except urllib.error.HTTPError as err:
                resp = err
            except OSError as err:
                return self._send_error(502, f"Could not reach upstream: {err}")
            with resp:
                self.send_response(resp.status if hasattr(resp, "status") else resp.code)
                for k, v in resp.headers.items():
                    if k.lower() not in HOP_BY_HOP:
                        self.send_header(k, v)
                self.send_header("Connection", "close")  # body ends when the connection closes (works for SSE)
                self.end_headers()
                try:
                    while True:
                        chunk = resp.read1(8192) if hasattr(resp, "read1") else resp.read(8192)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        # -- routes
        def do_GET(self):
            if self.path == "/health":
                body = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._forward("GET", None)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path.rstrip("/").endswith("/chat/completions"):
                try:
                    body = json.loads(raw)
                    messages = body["messages"]
                except (ValueError, KeyError, TypeError):
                    return self._send_error(400, "Request body must be JSON with a messages list.")
                user_text = last_user_text(messages)
                if user_text:
                    block = memory.retrieve(user_text)["text"]
                    if block:
                        body["messages"] = [{"role": "system", "content": block}, *messages]
                    threading.Thread(target=memory.ingest, args=(user_text, complete), daemon=True).start()
                raw = json.dumps(body).encode()
            self._forward("POST", raw)

    return ThreadingHTTPServer((host, port), Handler)
