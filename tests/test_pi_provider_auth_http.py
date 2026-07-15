from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi_provider_auth import PiProviderAuthError


class _ProviderAuth:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def catalog(self) -> dict[str, object]:
        self.calls.append(("catalog", None))
        return {
            "schemaVersion": "rag-ime.pi-provider-catalog.v1",
            "ok": True,
            "available": True,
            "providers": [{"id": "openai-codex", "auth": {"configured": False}}],
        }

    def preview(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("preview", dict(payload)))
        return {
            "schemaVersion": "rag-ime.pi-provider-auth-preview.v1",
            "ok": True,
            "previewToken": "preview-1",
            "requiredConfirm": "replace",
        }

    def apply(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("apply", dict(payload)))
        return {
            "schemaVersion": "rag-ime.pi-provider-auth-receipt.v1",
            "ok": True,
            "receiptId": "receipt-1",
            "requiresAgentRestart": True,
        }

    def oauth_status(self, login_id: object) -> dict[str, object]:
        self.calls.append(("status", login_id))
        if login_id == "missing":
            raise PiProviderAuthError("登录会话不存在或服务已重启，请重新连接。")
        return {
            "schemaVersion": "rag-ime.pi-provider-oauth-status.v1",
            "ok": True,
            "loginId": str(login_id),
            "state": "waiting_for_user",
        }

    def oauth_cancel(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("cancel", dict(payload)))
        return {
            "schemaVersion": "rag-ime.pi-provider-oauth-status.v1",
            "ok": True,
            "loginId": str(payload.get("loginId") or ""),
            "state": "cancelled",
        }


class _Service:
    def __init__(self) -> None:
        self.pi_provider_auth = _ProviderAuth()

    def management_security_settings(self) -> dict[str, object]:
        return {
            "postRequiresJson": True,
            "sameOriginOnly": True,
            "requireToken": False,
        }


class PiProviderAuthHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _Service()

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service  # type: ignore[assignment]
        Handler.static_dir = Path("debug")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/api/agent/providers"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def test_provider_routes_map_to_the_secret_free_service_boundary(self) -> None:
        catalog = self._get(self.base_url)
        preview = self._post(
            f"{self.base_url}/auth/preview",
            {"provider": "openai-codex", "action": "set_api_key"},
        )
        secret = "secret-http-sentinel"
        receipt = self._post(
            f"{self.base_url}/auth/apply",
            {
                "previewToken": preview["previewToken"],
                "confirmText": "replace",
                "apiKey": secret,
            },
        )
        status = self._get(f"{self.base_url}/oauth/status?loginId=login-1")
        cancelled = self._post(
            f"{self.base_url}/oauth/cancel",
            {"loginId": "login-1"},
        )

        self.assertTrue(catalog["available"])
        self.assertEqual(status["state"], "waiting_for_user")
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertNotIn(secret, json.dumps(receipt))
        preview_call = next(payload for name, payload in self.service.pi_provider_auth.calls if name == "preview")
        apply_call = next(payload for name, payload in self.service.pi_provider_auth.calls if name == "apply")
        self.assertNotIn("apiKey", preview_call)
        self.assertEqual(apply_call["apiKey"], secret)

    def test_missing_oauth_job_returns_a_bounded_error_envelope(self) -> None:
        request = Request(f"{self.base_url}/oauth/status?loginId=missing")
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)
        try:
            payload = json.loads(raised.exception.read().decode("utf-8"))
        finally:
            raised.exception.close()

        self.assertEqual(raised.exception.code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["schemaVersion"], "rag-ime.pi-provider-oauth-status.v1")
        self.assertNotIn("auth.json", json.dumps(payload))

    @staticmethod
    def _get(url: str) -> dict[str, object]:
        with urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _post(url: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
