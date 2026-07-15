from __future__ import annotations

import json
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.pi_provider_auth import (
    PiProviderAuthError,
    PiProviderAuthService,
    PiProviderBridgeConfig,
)


ROOT = Path(__file__).resolve().parents[1]
PI_PACKAGE_ENTRY = ROOT.parent / "pi" / "packages" / "coding-agent" / "dist" / "index.js"


class _FakePiProviderAuthService(PiProviderAuthService):
    def __init__(self, config: PiProviderBridgeConfig) -> None:
        super().__init__(config)
        self.calls: list[dict[str, object]] = []

    def catalog(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.pi-provider-catalog.v1",
            "ok": True,
            "available": True,
            "providers": [
                {
                    "id": "openai-codex",
                    "name": "ChatGPT Plus/Pro",
                    "auth": {
                        "configured": False,
                        "oauthDeviceCodeSupported": True,
                    },
                },
                {
                    "id": "test-provider",
                    "name": "Test Provider",
                    "auth": {"configured": True, "type": "api_key"},
                },
            ],
        }

    def _call(self, request):  # type: ignore[no-untyped-def]
        self.calls.append(dict(request))
        return {
            "ok": True,
            "provider": request.get("provider"),
            "beforeType": "api_key",
        }

    def _start_oauth(self, provider: str, provider_name: str) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.pi-provider-oauth-status.v1",
            "ok": True,
            "loginId": "pi-login-test",
            "provider": provider,
            "providerName": provider_name,
            "state": "starting",
        }


class PiProviderAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-pi-provider-")
        root = Path(self.temporary.name)
        package_entry = root / "index.js"
        bridge_script = root / "bridge.mjs"
        package_entry.write_text("export {};\n", encoding="utf-8")
        bridge_script.write_text("\n", encoding="utf-8")
        self.service = _FakePiProviderAuthService(
            PiProviderBridgeConfig(
                node_executable="node",
                package_entry=package_entry,
                agent_dir=root / "agent",
                bridge_script=bridge_script,
            )
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def test_api_key_replace_uses_one_time_confirmation_and_secret_free_receipt(self) -> None:
        preview = self.service.preview(
            {"provider": "test-provider", "action": "set_api_key"}
        )
        receipt = self.service.apply(
            {
                "previewToken": preview["previewToken"],
                "confirmText": "replace",
                "apiKey": "secret-sentinel-value",
            }
        )

        self.assertEqual(self.service.calls[-1]["action"], "set_api_key")
        self.assertEqual(self.service.calls[-1]["apiKey"], "secret-sentinel-value")
        self.assertNotIn("secret-sentinel-value", json.dumps(receipt))
        self.assertTrue(receipt["requiresAgentRestart"])
        with self.assertRaisesRegex(PiProviderAuthError, "失效"):
            self.service.apply(
                {
                    "previewToken": preview["previewToken"],
                    "confirmText": "replace",
                    "apiKey": "another-key",
                }
            )

    def test_logout_and_oauth_device_code_are_explicit_receipted_actions(self) -> None:
        logout = self.service.preview(
            {"provider": "test-provider", "action": "logout"}
        )
        logout_receipt = self.service.apply(
            {"previewToken": logout["previewToken"], "confirmText": "logout"}
        )
        self.assertEqual(logout_receipt["action"], "logout")

        oauth = self.service.preview(
            {"provider": "openai-codex", "action": "oauth_device_code"}
        )
        oauth_receipt = self.service.apply(
            {"previewToken": oauth["previewToken"], "confirmText": "connect"}
        )
        self.assertEqual(oauth_receipt["login"]["state"], "starting")
        self.assertEqual(oauth_receipt["receiptState"], "login_started")
        self.assertFalse(oauth_receipt["requiresAgentRestart"])
        self.assertNotIn("token", json.dumps(oauth_receipt).lower())

    def test_provider_and_action_are_allowlisted(self) -> None:
        with self.assertRaises(PiProviderAuthError):
            self.service.preview({"provider": "../../auth.json", "action": "logout"})
        with self.assertRaises(PiProviderAuthError):
            self.service.preview({"provider": "test-provider", "action": "read_secret"})

    @unittest.skipUnless(PI_PACKAGE_ENTRY.is_file(), "local Pi build is not available")
    def test_real_pi_auth_storage_bridge_replaces_and_logs_out_without_echoing_secret(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-real-pi-auth-") as temporary:
            agent_dir = Path(temporary)
            (agent_dir / "models.json").write_text(
                json.dumps(
                    {
                        "providers": {
                            "test-provider": {
                                "baseUrl": "https://example.invalid/v1",
                                "api": "openai-completions",
                                "models": [{"id": "test-model", "name": "Test Model"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            service = PiProviderAuthService(
                PiProviderBridgeConfig(
                    node_executable="node",
                    package_entry=PI_PACKAGE_ENTRY,
                    agent_dir=agent_dir,
                    bridge_script=ROOT / "rag_ime" / "node" / "pi_provider_bridge.mjs",
                    timeout_seconds=10,
                )
            )
            preview = service.preview(
                {"provider": "test-provider", "action": "set_api_key"}
            )
            receipt = service.apply(
                {
                    "previewToken": preview["previewToken"],
                    "confirmText": "replace",
                    "apiKey": "secret-sentinel-real-pi",
                }
            )
            provider = next(
                item
                for item in service.catalog()["providers"]
                if item["id"] == "test-provider"
            )
            self.assertTrue(provider["auth"]["configured"])
            self.assertEqual(provider["auth"]["type"], "api_key")
            self.assertEqual(provider["availableModelCount"], 1)
            self.assertNotIn("secret-sentinel-real-pi", json.dumps(receipt))
            self.assertEqual(
                stat.S_IMODE((agent_dir / "auth.json").stat().st_mode),
                0o600,
            )

            logout = service.preview(
                {"provider": "test-provider", "action": "logout"}
            )
            service.apply(
                {"previewToken": logout["previewToken"], "confirmText": "logout"}
            )
            self.assertEqual(
                json.loads((agent_dir / "auth.json").read_text(encoding="utf-8")),
                {},
            )

    def test_oauth_is_single_flight_and_has_a_bounded_timeout(self) -> None:
        root = Path(self.temporary.name)
        bridge = root / "oauth_bridge.py"
        bridge.write_text(
            "import json, sys, time\n"
            "json.load(sys.stdin)\n"
            "print(json.dumps({'event': 'device_code', 'userCode': 'TEST-CODE', "
            "'verificationUri': 'https://auth.openai.com/codex/device', "
            "'expiresInSeconds': 900}), flush=True)\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        service = PiProviderAuthService(
            PiProviderBridgeConfig(
                node_executable=sys.executable,
                package_entry=root / "index.js",
                agent_dir=root / "agent",
                bridge_script=bridge,
                oauth_timeout_seconds=1,
            )
        )
        try:
            started = service._start_oauth("openai-codex", "ChatGPT Plus/Pro")
            with self.assertRaisesRegex(PiProviderAuthError, "正在进行"):
                service._start_oauth("openai-codex", "ChatGPT Plus/Pro")

            status = started
            deadline = time.monotonic() + 4
            while status["state"] != "failed" and time.monotonic() < deadline:
                time.sleep(0.05)
                status = service.oauth_status(started["loginId"])
            self.assertEqual(status["state"], "failed")
            self.assertIn("超时", status["error"])
            self.assertFalse(status["requiresAgentRestart"])
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
