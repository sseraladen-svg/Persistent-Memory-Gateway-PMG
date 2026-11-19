import http.client
import json
import threading
import unittest

from pmg import dashboard
from pmg.store import Memory

from helpers import IsolatedTestCase


class DashboardTests(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.memory = Memory()
        self.server = dashboard.make_server(self.memory, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.port = self.server.server_address[1]

    def call(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"X-PMG-Request": "1", "Content-Type": "application/json", **(headers or {})}
        if host:
            hdrs["Host"] = host
        conn.request(method, path, json.dumps(body) if body is not None else None, hdrs)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw

    def test_serves_the_ui(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", body)

    def test_add_list_search_and_delete(self):
        status, created = self.call("POST", "/api/chunks", {"kind": "fact", "text": "my dog is named Biscuit"})
        self.assertEqual(status, 201)
        _, listed = self.call("GET", "/api/chunks")
        self.assertEqual([c["text"] for c in listed["chunks"]], ["my dog is named Biscuit"])
        _, hit = self.call("GET", "/api/chunks?q=biscuit")
        self.assertEqual(len(hit["chunks"]), 1)
        _, none = self.call("GET", "/api/chunks?kind=behavior")
        self.assertEqual(none["chunks"], [])
        self.assertEqual(self.call("DELETE", f"/api/chunks/{created['id']}")[0], 200)
        self.assertEqual(self.call("DELETE", f"/api/chunks/{created['id']}")[0], 404)

    def test_validation_and_secret_blocking(self):
        self.assertEqual(self.call("POST", "/api/chunks", {"kind": "nope", "text": "hello there"})[0], 400)
        self.assertEqual(self.call("POST", "/api/chunks", {"kind": "fact", "text": "hi"})[0], 400)
        status, err = self.call("POST", "/api/chunks", {"kind": "fact", "text": "my password is hunter2"})
        self.assertEqual(status, 400)
        self.assertIn("secret", err["error"])

    def test_playground_retrieval_is_not_counted_in_stats(self):
        self.memory.add("fact", "my dog is named Biscuit")
        _, r = self.call("POST", "/api/retrieve", {"query": "feed my dog", "budget": 100})
        self.assertEqual(r["budget"], 100)
        self.assertEqual(len(r["chunks"]), 1)
        _, stats = self.call("GET", "/api/stats")
        self.assertEqual(stats["requests"], 0)
        self.assertIn("rules", stats)

    def test_rules_can_be_read_and_saved_but_not_broken(self):
        _, rules = self.call("GET", "/api/rules")
        rules["budget_tokens"] = 250
        self.assertEqual(self.call("PUT", "/api/rules", rules)[0], 200)
        self.assertEqual(self.call("GET", "/api/rules")[1]["budget_tokens"], 250)
        rules["budget_tokens"] = 1
        status, err = self.call("PUT", "/api/rules", rules)
        self.assertEqual(status, 400)
        self.assertIn("budget_tokens", err["error"])
        self.assertEqual(self.call("GET", "/api/rules")[1]["budget_tokens"], 250)

    def test_foreign_host_is_rejected(self):
        self.assertEqual(self.call("GET", "/api/stats", host="evil.example.com")[0], 403)

    def test_changes_require_the_custom_header(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/chunks", json.dumps({"kind": "fact", "text": "sneaky write"}),
                     {"Content-Type": "text/plain"})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual(self.memory.list(), [])

    def test_malformed_json_is_a_400_not_a_crash(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/retrieve", "{oops", {"X-PMG-Request": "1", "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()


if __name__ == "__main__":
    unittest.main()
