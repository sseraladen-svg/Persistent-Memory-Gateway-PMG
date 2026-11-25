import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pmg import proxy
from pmg.store import Memory

from helpers import IsolatedTestCase


class FakeUpstream:
    """A stand-in for an OpenAI-compatible API that records what it receives."""

    def __init__(self):
        outer = self
        self.requests = []
        self.reply = "hi"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append(("GET", self.path, dict(self.headers), None))
                body = b'{"data":[{"id":"fake-model"}]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(("POST", self.path, dict(self.headers), payload))
                if self.headers.get("Authorization") == "Bearer bad":
                    body = b'{"error":{"message":"bad key"}}'
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if payload.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for part in ("Hel", "lo", "!"):
                        self.wfile.write(f'data: {{"delta":"{part}"}}\n\n'.encode())
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                body = json.dumps({"choices": [{"message": {"role": "assistant", "content": outer.reply}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class ProxyTests(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.upstream = FakeUpstream()
        self.addCleanup(self.upstream.stop)
        self.memory = Memory()
        self.memory.add("fact", "my dog is named Biscuit")
        self.memory.add("behavior", "answer in short sentences")
        self.server = proxy.make_server(self.upstream.url, self.memory, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def post(self, body, key="good"):
        req = urllib.request.Request(
            self.base + "/v1/chat/completions", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        return urllib.request.urlopen(req, timeout=10)

    def test_memory_is_injected_and_credentials_pass_through(self):
        with self.post({"model": "m", "messages": [{"role": "user", "content": "what should my dog eat?"}]}) as r:
            self.assertEqual(json.load(r)["choices"][0]["message"]["content"], "hi")
        method, path, headers, payload = self.upstream.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer good")
        first = payload["messages"][0]
        self.assertEqual(first["role"], "system")
        self.assertIn("Biscuit", first["content"])
        self.assertIn("short sentences", first["content"])
        self.assertEqual(payload["messages"][-1]["content"], "what should my dog eat?")

    def test_echo_is_estimated_from_the_reply(self):
        self.upstream.reply = "Biscuit should eat dog food twice a day."
        self.post({"model": "m", "messages": [{"role": "user", "content": "what should my dog eat?"}]}).close()
        deadline = time.time() + 5
        while time.time() < deadline and self.memory.stats()["echo_requests"] < 1:
            time.sleep(0.05)
        stats = self.memory.stats()
        self.assertEqual(stats["echo_requests"], 1)
        self.assertEqual(stats["echo_percent"], 100.0)
        self.upstream.reply = "I cannot say."
        self.post({"model": "m", "messages": [{"role": "user", "content": "what should my dog eat?"}]}).close()
        while time.time() < deadline and self.memory.stats()["echo_requests"] < 2:
            time.sleep(0.05)
        self.assertEqual(self.memory.stats()["echo_percent"], 50.0)

    def test_streaming_is_relayed(self):
        with self.post({"model": "m", "stream": True,
                        "messages": [{"role": "user", "content": "hello"}]}) as r:
            text = r.read().decode()
        self.assertIn('"delta":"Hel"', text)
        self.assertTrue(text.rstrip().endswith("data: [DONE]"))

    def test_user_message_is_remembered_afterwards(self):
        self.post({"model": "m", "messages": [{"role": "user", "content": "remember that I live in Madurai"}]}).close()
        deadline = time.time() + 5
        while time.time() < deadline and not any("Madurai" in c["text"] for c in self.memory.list()):
            time.sleep(0.05)
        self.assertTrue(any(c["text"] == "I live in Madurai" for c in self.memory.list()))

    def test_upstream_errors_pass_through(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post({"model": "m", "messages": [{"role": "user", "content": "hi"}]}, key="bad")
        self.assertEqual(ctx.exception.code, 401)
        self.assertIn("bad key", ctx.exception.read().decode())

    def test_other_routes_pass_through(self):
        with urllib.request.urlopen(self.base + "/v1/models", timeout=10) as r:
            self.assertEqual(json.load(r)["data"][0]["id"], "fake-model")

    def test_invalid_body_is_rejected(self):
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=b"not json",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_unreachable_upstream_gives_502(self):
        dead = proxy.make_server("http://127.0.0.1:1/v1", self.memory, port=0)
        threading.Thread(target=dead.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (dead.shutdown(), dead.server_close()))
        req = urllib.request.Request(
            f"http://127.0.0.1:{dead.server_address[1]}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 502)


if __name__ == "__main__":
    unittest.main()
