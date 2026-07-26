"""What the descriptor dispatcher promises, proven against the dispatcher.

The migrated management reads must forward exactly the parameters they did.

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


class SessionIdFallbackTests(unittest.TestCase):
    """`sessionId` or `id`, collapsed to `sessionId` -- and `id` never sent on.

    The active-RAG reads accepted either spelling. Declaring both as query
    arguments is what makes them readable, but the service only ever received
    `sessionId`, so forwarding `id` as well would hand it a key it has never
    seen. These cases pin both halves: the fallback works, and the alternate
    spelling does not leak into the payload.
    """

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

    def _get(self, path: str, query: dict[str, str]):
        url = f"http://127.0.0.1:{self.server.server_port}{path}?{urlencode(query)}"
        with urlopen(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            response.read()
        return self.service.calls

    def test_session_id_is_preferred_and_id_is_the_fallback(self) -> None:
        for path, handler in (
            ("/api/active-rag/status", "active_rag_status"),
            ("/api/active-rag/session", "active_rag_status"),
            ("/api/active-rag/diagnostics", "active_rag_diagnostics"),
            ("/api/knowledge/status", "knowledge_workbench_status"),
            ("/api/knowledge/session", "knowledge_workbench_status"),
        ):
            with self.subTest(path=path):
                self.service.calls.clear()
                self.assertEqual(
                    self._get(path, {"sessionId": "primary", "id": "ignored"}),
                    [(handler, {"sessionId": "primary"})],
                )
                self.service.calls.clear()
                self.assertEqual(
                    self._get(path, {"id": "fallback"}),
                    [(handler, {"sessionId": "fallback"})],
                )
                self.service.calls.clear()
                self.assertEqual(self._get(path, {}), [(handler, {"sessionId": ""})])

    def test_the_trace_reads_carry_the_limit_alongside_the_session(self) -> None:
        for path in ("/api/active-rag/traces", "/api/active-rag/chain-trace"):
            with self.subTest(path=path):
                self.service.calls.clear()
                self.assertEqual(
                    self._get(path, {"id": "fallback", "limit": "25"}),
                    [("active_rag_traces", {"sessionId": "fallback", "limit": "25"})],
                )


class _Recorder:
    """Stands in for the application service and any of its sub-services.

    Attribute access returns another recorder, so a dotted handler such as
    `management.planning_assistant` resolves the same way it does against the
    real service; calling one records the arguments it was given.
    """

    def __init__(self, calls: list, path: tuple[str, ...] = ()) -> None:
        self._calls = calls
        self._path = path

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Recorder(self._calls, (*self._path, name))

    def __call__(self, *args, **kwargs):
        self._calls.append((".".join(self._path), args, kwargs))
        return {"ok": True}


class PostDescriptorPassThroughTests(unittest.TestCase):
    """Every straight POST descriptor must hand its payload through unchanged.

    Most migrated writes were one chain line -- take the payload, call one
    method, answer a fixed status -- and only a handful have HTTP tests. This
    walks the table itself, so a route added later is covered the day it is
    declared rather than whenever someone remembers to write a test.

    Routes declaring a request or response contract are excluded: a synthetic
    payload could not satisfy their schemas, and their validation is covered
    separately below.
    """

    def _straight_post_routes(self):
        from rag_ime.control_api.route_table import MIGRATED_ROUTES

        return [
            route for route in MIGRATED_ROUTES
            if route.method == "POST"
            and route.takes_arguments
            and not route.contract
            and not route.response_contract
            and route.transform is None
        ]

    def test_table_has_straight_post_routes_to_check(self) -> None:
        # Guards against the filter above quietly matching nothing, which would
        # make the test below pass while checking no route at all.
        self.assertGreater(len(self._straight_post_routes()), 20)

    def test_payload_reaches_the_handler_unchanged_with_the_declared_status(self) -> None:
        from rag_ime.debug_server import DebugRequestHandler

        for route in self._straight_post_routes():
            with self.subTest(path=route.path, handler=route.handler):
                calls: list = []
                handler = DebugRequestHandler.__new__(DebugRequestHandler)
                handler.service = _Recorder(calls)
                written: list = []
                handler._write_json = lambda status, body: written.append((int(status), body))

                payload = {"probe": route.path}
                handler._dispatch_descriptor_route(route, payload=payload)

                # `payload_args` are keyword arguments, not payload keys:
                # `vocabulary_item_save(payload, *, action)` declares the
                # discriminator keyword-only, so merging it into the payload
                # would both lose the argument and corrupt the payload.
                self.assertEqual(
                    calls,
                    [(route.handler, (payload,), dict(route.payload_args))],
                )
                self.assertEqual(written, [(route.status, {"ok": True})])


class ResponseContractEnforcementTests(unittest.TestCase):
    """A declared response contract must be enforced however the handler is called.

    Response validation used to live inside the dispatcher's argument-free
    branch. Every route that declared a response contract happened to be
    argument-free, so the omission was invisible -- until a route that takes
    arguments declares one, at which point the descriptor would claim
    validation that never ran. This pins the fix to the behaviour, not to the
    shape of the code.
    """

    def _dispatch(self, *, takes_arguments: bool, response: dict[str, object]):
        from rag_ime.control_api.route_table import RouteDescriptor
        from rag_ime.debug_server import DebugRequestHandler

        route = RouteDescriptor(
            method="POST", path="/api/test/contract", handler="handler",
            takes_arguments=takes_arguments,
            response_contract="frontend-selection-response.v1.json",
        )

        class _Service:
            def handler(self, *args, **kwargs):
                return response

        handler = DebugRequestHandler.__new__(DebugRequestHandler)
        handler.service = _Service()
        written: list[tuple[int, dict[str, object]]] = []
        handler._write_json = lambda status, body: written.append((int(status), body))
        handler._dispatch_descriptor_route(route, payload={})
        return written

    def test_invalid_response_is_rejected_for_a_route_that_takes_arguments(self) -> None:
        with self.assertRaises(Exception) as caught:
            self._dispatch(takes_arguments=True, response={"not": "a valid response"})
        self.assertNotIsInstance(caught.exception, AssertionError)

    def test_invalid_response_is_rejected_for_an_argument_free_route(self) -> None:
        with self.assertRaises(Exception) as caught:
            self._dispatch(takes_arguments=False, response={"not": "a valid response"})
        self.assertNotIsInstance(caught.exception, AssertionError)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
