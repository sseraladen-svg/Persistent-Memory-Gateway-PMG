"""Local dashboard: a small JSON API plus the single-page UI in pmg/web.

Safety: it binds to localhost, rejects requests whose Host header is not local (blocks DNS rebinding),
sends no CORS headers, and requires a custom header on every change (blocks cross-site forms).
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import rules as rules_mod
from .store import Memory

WEB = Path(__file__).with_name("web")
LOCAL_HOST = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
MAX_BODY = 64 * 1024


def make_server(memory: Memory, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "pmg-dashboard"

        def log_message(self, *args):
            pass

        def _json(self, status: int, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("Request body is too large.")
            return json.loads(self.rfile.read(length) or b"{}")

        def _guard(self, changes: bool) -> bool:
            if not LOCAL_HOST.match(self.headers.get("Host", "")):
                self._json(403, {"error": "Only local access is allowed."})
                return False
            if changes and self.headers.get("X-PMG-Request") != "1":
                self._json(403, {"error": "Missing X-PMG-Request header."})
                return False
            return True

        def _route(self, method: str):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            if method == "GET" and path == "/":
                body = (WEB / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if method == "GET" and path == "/api/stats":
                return self._json(200, {**memory.stats(), "rules": rules_mod.load()})
            if method == "GET" and path == "/api/chunks":
                return self._json(200, {"chunks": memory.list(limit=500, kind=q.get("kind"), q=q.get("q"))})
            if method == "POST" and path == "/api/chunks":
                data = self._body()
                text, kind = str(data.get("text", "")).strip(), str(data.get("kind", "fact"))
                rules = rules_mod.load()
                if kind not in rules["kinds"]:
                    return self._json(400, {"error": f"Kind must be one of: {', '.join(rules['kinds'])}."})
                if not 3 <= len(text) <= 400:
                    return self._json(400, {"error": "Text must be between 3 and 400 characters."})
                from .classify import contains_secret
                if contains_secret(text, rules):
                    return self._json(400, {"error": "That looks like a secret, so it was not saved."})
                return self._json(201, {"id": memory.add(kind, text)})
            m = re.fullmatch(r"/api/chunks/(\d+)", path)
            if method == "DELETE" and m:
                return self._json(200 if memory.forget(int(m.group(1))) else 404, {})
            if method == "POST" and path == "/api/retrieve":
                data = self._body()
                budget = data.get("budget")
                budget = int(budget) if isinstance(budget, (int, float)) and budget > 0 else 0
                return self._json(200, memory.retrieve(str(data.get("query", ""))[:2000], budget, log=False))
            if method == "GET" and path == "/api/rules":
                return self._json(200, rules_mod.load())
            if method == "PUT" and path == "/api/rules":
                try:
                    rules_mod.save(self._body())
                except ValueError as err:
                    return self._json(400, {"error": str(err)})
                return self._json(200, rules_mod.load())
            self._json(404, {"error": "Not found."})

        def _handle(self, method: str):
            if not self._guard(changes=method in ("POST", "PUT", "DELETE")):
                return
            try:
                self._route(method)
            except (ValueError, json.JSONDecodeError) as err:
                self._json(400, {"error": str(err) or "Invalid request."})

        def do_GET(self): self._handle("GET")
        def do_POST(self): self._handle("POST")
        def do_PUT(self): self._handle("PUT")
        def do_DELETE(self): self._handle("DELETE")

    return ThreadingHTTPServer((host, port), Handler)
