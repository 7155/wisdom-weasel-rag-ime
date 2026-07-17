from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rag_ime.control_api import ControlClientKind
from rag_ime.debug_server import DebugRequestHandler


class _GatewayService:
    config = SimpleNamespace(server_name="agent gateway")

    def health(self) -> dict[str, object]:
        return {"ok": True, "service": "agent gateway"}

    def control_capabilities(self, context) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.control-capabilities.v1",
            "features": {},
            "clientKind": context.client_kind.value,
            "routes": [],
        }


class AgentGatewayRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-gateway-web-")
        self.web = Path(self.tmp.name)
        (self.web / "assets").mkdir()
        (self.web / "index.html").write_text("<!doctype html><title>Gateway UI</title>", encoding="utf-8")
        (self.web / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

        class Handler(DebugRequestHandler):
            pass

        Handler.service = _GatewayService()  # type: ignore[assignment]
        Handler.static_dir = self.web
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.tmp.cleanup()

    def test_loopback_serves_the_same_origin_control_center(self) -> None:
        with urlopen(f"{self.base_url}/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
            self.assertIn(b"Gateway UI", response.read())

    def test_tailscale_identity_and_login_allowlist_gate_remote_routes(self) -> None:
        headers = {
            "Host": "weasel.example.ts.net",
            "Tailscale-User-Login": "owner@example.com",
        }
        with patch.dict(
            os.environ,
            {"RAG_IME_REMOTE_ALLOWED_LOGINS": "owner@example.com"},
            clear=False,
        ):
            with urlopen(Request(f"{self.base_url}/api/health", headers=headers), timeout=5) as response:
                self.assertTrue(json.loads(response.read())["ok"])
            with urlopen(
                Request(f"{self.base_url}/api/agent/control/capabilities", headers=headers),
                timeout=5,
            ) as response:
                payload = json.loads(response.read())
                self.assertEqual(payload["clientKind"], ControlClientKind.REMOTE_WEB.value)

            denied = Request(
                f"{self.base_url}/api/agent/providers",
                headers=headers,
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(denied, timeout=5)
            self.assertEqual(raised.exception.code, 403)
            raised.exception.close()

    def test_non_tailscale_or_unlisted_remote_requests_fail_closed(self) -> None:
        with patch.dict(
            os.environ,
            {"RAG_IME_REMOTE_ALLOWED_LOGINS": "owner@example.com"},
            clear=False,
        ):
            for headers in (
                {"Host": "weasel.example.ts.net"},
                {
                    "Host": "weasel.example.ts.net",
                    "Tailscale-User-Login": "other@example.com",
                },
            ):
                with self.subTest(headers=headers), self.assertRaises(HTTPError) as raised:
                    urlopen(Request(f"{self.base_url}/api/health", headers=headers), timeout=5)
                self.assertEqual(raised.exception.code, 403)
                raised.exception.close()


if __name__ == "__main__":
    unittest.main()
