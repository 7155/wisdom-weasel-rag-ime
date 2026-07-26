"""The migrated management reads must forward exactly the parameters they did.

Five of the six routes moved into the descriptor table in this batch had no
HTTP coverage at all, so a passing suite said nothing about them. What the
migration actually changed is the request-to-payload mapping: the chain built a
dict of named `_query_first` lookups, and the descriptor now states that list
as `query_args`. A dropped, added or renamed parameter would silently change
the result the service computes while still returning 200.

These tests drive real HTTP through the real dispatcher and assert the payload
the handler received, which is the only thing that proves the mapping survived.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from rag_ime.debug_server import DebugRequestHandler


class _RecordingService:
    """Captures the payload each migrated read hands to the application."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _record(self, name: str):
        def handler(payload):
            self.calls.append((name, dict(payload)))
            return {"ok": True, "handler": name}

        return handler

    def __getattr__(self, name: str):
        # Only the handlers the descriptors name are reachable; anything else
        # would be a typo the route-ownership gate already rejects.
        if name.startswith("_"):
            raise AttributeError(name)
        return self._record(name)


# route path -> (handler name, query sent, payload the handler must receive)
CASES = {
    "/api/audit": (
        "management_audit",
        {"limit": "7", "action": "commit"},
        {"limit": "7", "action": "commit"},
    ),
    "/api/history": (
        "management_history",
        {"limit": "3", "project": "p", "query": "q", "source": "s",
         "includeDeleted": "1", "generatedOnly": "0"},
        {"limit": "3", "project": "p", "query": "q", "source": "s",
         "includeDeleted": "1", "generatedOnly": "0"},
    ),
    "/api/lexicon": (
        "management_lexicon",
        {"limit": "9", "project": "p", "status": "pending", "kind": "phrase"},
        {"limit": "9", "project": "p", "status": "pending", "kind": "phrase"},
    ),
    "/api/cleanup-diff": (
        "management_cleanup_diff",
        {"id": "1", "diffId": "2", "runId": "3", "status": "open", "limit": "4"},
        {"id": "1", "diffId": "2", "runId": "3", "status": "open", "limit": "4"},
    ),
    "/api/candidates/explain": (
        "candidate_explain",
        {"query": "q", "currentInput": "ni", "recentContext": "c",
         "project": "p", "app": "a", "topK": "5"},
        {"query": "q", "currentInput": "ni", "recentContext": "c",
         "project": "p", "app": "a", "topK": "5"},
    ),
    "/api/predictor/latency": (
        "predictor_latency",
        {"log": "trace.jsonl", "last": "20"},
        {"log": "trace.jsonl", "last": "20"},
    ),
}


class ManagementReadDescriptorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _RecordingService()

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path("debug")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.shutdown)

    def _get(self, path: str, query: dict[str, str]) -> dict[str, object]:
        url = f"http://127.0.0.1:{self.server.server_port}{path}?{urlencode(query)}"
        with urlopen(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def test_each_read_forwards_exactly_its_declared_parameters(self) -> None:
        for path, (handler, query, expected) in CASES.items():
            with self.subTest(path=path):
                self.service.calls.clear()
                body = self._get(path, query)
                self.assertEqual(body, {"ok": True, "handler": handler})
                self.assertEqual(self.service.calls, [(handler, expected)])

    def test_absent_parameters_are_forwarded_as_empty_strings(self) -> None:
        """The chain used `_query_first`, which yields "" for a missing key.

        Forwarding `None`, or omitting the key, would change how the services
        below apply their defaults, so the empty string is part of the contract.
        """

        for path, (handler, query, _expected) in CASES.items():
            with self.subTest(path=path):
                self.service.calls.clear()
                self._get(path, {})
                self.assertEqual(
                    self.service.calls,
                    [(handler, {name: "" for name in query})],
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
