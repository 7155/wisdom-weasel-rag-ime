from __future__ import annotations

import base64
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.browser_control import BrowserControlError, BrowserControlService


class BrowserControlServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        extension = root / "extension"
        extension.mkdir()
        (extension / "manifest.json").write_text("{}", encoding="utf-8")
        self.service = BrowserControlService(
            root / "rag-ime.sqlite",
            extension_root=extension,
            app_support_root=root / "support",
        )
        self.service.hello(
            {
                "deviceId": "chrome-test",
                "displayName": "测试 Chrome",
                "clientKind": "user",
                "extensionVersion": "1.0.0",
                "browserName": "Chrome",
                "activeTabId": 7,
            }
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_pairing_and_snapshot_are_shared_across_service_instances(self) -> None:
        token = str(self.service.pairing()["pairingToken"])
        self.assertTrue(self.service.authenticate(token))
        self.service.push_snapshot(
            {
                "deviceId": "chrome-test",
                "snapshotId": "snap-test",
                "tabId": 7,
                "url": "https://example.com/docs",
                "title": "Example Docs",
                "summary": "2 个可交互元素",
                "markdown": "# Example\n- [0:e1] link \"Read\"",
                "interactiveCount": 2,
                "viewport": {"width": 1280, "height": 720},
            }
        )
        other = BrowserControlService(self.service.db_path, extension_root=self.service.extension_root)

        snapshot = other.latest_snapshot(device_id="chrome-test", tab_id=7)
        self.assertEqual(snapshot["snapshotId"], "snap-test")
        self.assertIn("[0:e1]", snapshot["markdown"])
        self.assertEqual(other.tabs()["items"][0]["title"], "Example Docs")

    def test_status_uses_active_tab_projection_without_loading_global_snapshot_payload(self) -> None:
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nstatus-fixture").decode("ascii")
        self.service.push_snapshot(
            {
                "deviceId": "chrome-test",
                "snapshotId": "snap-status",
                "tabId": 7,
                "url": "https://example.com/status",
                "title": "Status",
                "summary": "状态快照",
                "markdown": "# payload must not be loaded by status",
                "screenshotDataUrl": f"data:image/png;base64,{png}",
            }
        )

        with mock.patch.object(
            self.service,
            "_latest_snapshot_row",
            side_effect=AssertionError("status must not run the global payload query"),
        ):
            status = self.service.status()

        self.assertEqual(status["latestSnapshot"]["snapshotId"], "snap-status")
        self.assertTrue(status["latestSnapshot"]["hasScreenshot"])
        self.assertNotIn("markdown", status["latestSnapshot"])

    def test_snapshot_urls_redact_credentials_fragments_and_sensitive_queries(self) -> None:
        unsafe_url = (
            "https://reader:password@example.com/docs"
            "?query=browser&access_token=private&session_id=session-1#account"
        )
        self.service.push_snapshot(
            {
                "deviceId": "chrome-test",
                "snapshotId": "snap-private-url",
                "tabId": 7,
                "url": unsafe_url,
                "title": "Private URL",
                "markdown": f"# Private URL\nURL: {unsafe_url}",
            }
        )

        snapshot = self.service.latest_snapshot(device_id="chrome-test", tab_id=7)
        self.assertEqual(
            snapshot["url"],
            "https://example.com/docs?query=browser&access_token=%5Bredacted%5D"
            "&session_id=%5Bredacted%5D",
        )
        self.assertNotIn("password", snapshot["markdown"])
        self.assertNotIn("access_token=private", snapshot["markdown"])
        self.assertNotIn("#account", snapshot["markdown"])

    def test_observe_mode_blocks_write_commands(self) -> None:
        with self.assertRaisesRegex(BrowserControlError, "observe mode"):
            self.service.submit_command(
                "navigate",
                {"url": "https://example.com"},
                timeout_seconds=1,
            )

    def test_command_queue_round_trip_strips_large_snapshot_from_result(self) -> None:
        self.service.set_mode("codrive")

        def extension_worker() -> None:
            command = self.service.next_command(
                device_id="chrome-test",
                client_id="chrome-test:worker",
                timeout_seconds=2,
            )["command"]
            assert isinstance(command, dict)
            self.service.complete_command(
                {
                    "commandId": command["commandId"],
                    "result": {
                        "ok": True,
                        "summary": "已打开页面",
                        "tabId": 7,
                        "url": "https://example.com/next",
                        "title": "Next",
                        "markdown": "# Next\n- [0:e1] button \"Continue\"",
                        "interactiveCount": 1,
                    },
                }
            )

        worker = threading.Thread(target=extension_worker)
        worker.start()
        result = self.service.submit_command(
            "navigate",
            {"url": "https://example.com/next", "tabId": 7},
            session_id="session-test",
            timeout_seconds=3,
        )
        worker.join(timeout=3)

        self.assertTrue(result["ok"])
        self.assertNotIn("markdown", result["result"])
        self.assertTrue(result["result"]["snapshotId"].startswith("snap_"))
        self.assertIn("Next", self.service.latest_snapshot(tab_id=7)["markdown"])

    def test_screenshot_is_stored_behind_bounded_binary_route(self) -> None:
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode("ascii")
        self.service.set_mode("codrive")

        def extension_worker() -> None:
            command = self.service.next_command(
                device_id="chrome-test",
                client_id="chrome-test:worker",
                timeout_seconds=2,
            )["command"]
            assert isinstance(command, dict)
            self.service.complete_command(
                {
                    "commandId": command["commandId"],
                    "result": {
                        "ok": True,
                        "tabId": 7,
                        "url": "https://example.com",
                        "title": "Example",
                        "screenshotDataUrl": f"data:image/png;base64,{png}",
                    },
                }
            )

        worker = threading.Thread(target=extension_worker)
        worker.start()
        result = self.service.submit_command("screenshot", {"tabId": 7}, timeout_seconds=3)
        worker.join(timeout=3)
        snapshot_id = str(result["result"]["snapshotId"])
        mime_type, data = self.service.snapshot_image(snapshot_id)
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(data, b"\x89PNG\r\n\x1a\nfixture")

    def test_permissions_require_explicit_resolution(self) -> None:
        prompt = self.service.request_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://example.com/account",
                "action": "domain_transition",
                "reason": "即将进入新的站点",
            }
        )
        prompt_id = str(prompt["promptId"])
        self.assertEqual(self.service.permission_status(prompt_id)["status"], "pending")

        resolved = self.service.decide_permission(prompt_id, "allow_once")
        self.assertEqual(resolved["decision"], "allow_once")
        self.assertEqual(self.service.permission_status(prompt_id)["status"], "resolved")

        reused = self.service.request_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://example.com/another-page",
                "action": "domain_transition",
                "reason": "再次进入同一站点",
            }
        )
        self.assertTrue(reused["authorized"])
        self.assertEqual(reused["decision"], "allow_once")
        self.assertEqual(self.service.permission_status(prompt_id)["status"], "consumed")

        next_prompt = self.service.request_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://example.com/third-page",
                "action": "domain_transition",
                "reason": "单次授权已经消费",
            }
        )
        self.assertFalse(next_prompt["authorized"])
        self.assertNotEqual(next_prompt["promptId"], prompt_id)

    def test_extension_auto_approval_consumes_existing_site_prompt(self) -> None:
        prompt = self.service.request_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://pi.dev/",
                "action": "domain_transition",
                "reason": "从 chatgpt.com 前往 pi.dev",
            }
        )

        approved = self.service.request_extension_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://pi.dev/",
                "action": "domain_transition",
                "reason": "从 chatgpt.com 前往 pi.dev",
            }
        )

        self.assertTrue(approved["authorized"])
        self.assertTrue(approved["autoApproved"])
        self.assertEqual(approved["decision"], "allow_once")
        self.assertEqual(approved["promptId"], prompt["promptId"])
        self.assertEqual(self.service.permission_status(str(prompt["promptId"]))["status"], "consumed")
        self.assertEqual(self.service.status()["pendingPermissions"], 0)

        opted_out = self.service.request_extension_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://example.com/",
                "action": "domain_transition",
                "reason": "逐次确认",
                "autoApprove": False,
            }
        )
        self.assertFalse(opted_out["authorized"])

    def test_site_permission_is_reused_without_a_new_prompt(self) -> None:
        prompt = self.service.request_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://docs.example.com/guide",
                "action": "domain_transition",
                "reason": "进入文档站点",
            }
        )
        self.service.decide_permission(str(prompt["promptId"]), "allow_site")

        reused = self.service.request_permission(
            {
                "deviceId": "chrome-test",
                "origin": "https://docs.example.com/reference",
                "action": "domain_transition",
                "reason": "再次进入文档站点",
            }
        )
        self.assertTrue(reused["authorized"])
        self.assertEqual(reused["decision"], "allow_site")

    def test_agent_tool_reads_status_and_invalidates_stale_write_approval(self) -> None:
        self.service.push_snapshot(
            {
                "deviceId": "chrome-test",
                "snapshotId": "snap-agent",
                "tabId": 7,
                "url": "https://example.com",
                "title": "Agent Page",
                "markdown": '# Agent Page\n- [0:e1] button "Continue"',
            }
        )
        self.service.set_mode("codrive")
        sessions = AgentSessionStore(Path(self.temp.name) / "agent.sqlite")
        sessions.initialize()
        session = sessions.create(title="browser tool", created_at_ms=1)
        gateway = ControlToolGateway(
            sessions=sessions,
            management=object(),
            core=object(),
            project="browser-test",
            browser_control=self.service,
        )
        call = {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": session["id"],
            "tool": "browser",
            "toolCallId": "tool:browser",
        }

        status = gateway.execute({**call, "args": {"op": "status"}})["result"]
        self.assertTrue(status["connected"])
        self.assertNotIn("extensionPath", status)

        prepared = gateway.execute(
            {
                **call,
                "args": {
                    "op": "click",
                    "deviceId": "chrome-test",
                    "tabId": 7,
                    "refId": "0:e1",
                },
            }
        )["result"]
        approval = prepared["approval"]
        self.assertEqual(approval["preview"]["baseState"]["snapshotId"], "snap-agent")
        decided = sessions.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        self.service.push_snapshot(
            {
                "deviceId": "chrome-test",
                "snapshotId": "snap-agent-updated",
                "tabId": 7,
                "url": "https://example.com",
                "title": "Updated Agent Page",
                "markdown": '# Updated Agent Page\n- [0:e1] button "Continue"',
            }
        )
        with self.assertRaisesRegex(ValueError, "browser page changed"):
            gateway.apply_approval(decided)

        prepared = gateway.execute(
            {
                **call,
                "toolCallId": "tool:browser:mode",
                "args": {
                    "op": "click",
                    "deviceId": "chrome-test",
                    "tabId": 7,
                    "refId": "0:e1",
                },
            }
        )["result"]
        approval = prepared["approval"]
        decided = sessions.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        self.service.set_mode("managed")
        with self.assertRaisesRegex(ValueError, "browser mode changed"):
            gateway.apply_approval(decided)

    def test_managed_mode_never_falls_back_to_user_browser(self) -> None:
        self.service.set_mode("managed")

        with self.assertRaisesRegex(BrowserControlError, "daily browser"):
            self.service.submit_command(
                "navigate",
                {
                    "deviceId": "chrome-test",
                    "url": "https://example.com/managed",
                },
                timeout_seconds=1,
            )

        with self.assertRaisesRegex(BrowserControlError, "managed browser extension"):
            self.service.submit_command(
                "navigate",
                {"url": "https://example.com/managed"},
                timeout_seconds=1,
            )

    def test_managed_client_requires_bootstrap_token(self) -> None:
        payload = {
            "deviceId": "chrome-managed",
            "displayName": "托管 Chrome",
            "clientKind": "managed",
            "extensionVersion": "1.0.0",
            "browserName": "Chrome",
            "activeTabId": 9,
        }
        with self.assertRaisesRegex(BrowserControlError, "bootstrap token"):
            self.service.hello(payload)

        with self.service._connection() as connection:
            self.service._set_setting(
                connection,
                "managed_bootstrap_token",
                "managed-test-token",
            )
        response = self.service.hello(
            {
                **payload,
                "managedBootstrapToken": "managed-test-token",
            }
        )
        self.assertEqual(response["deviceId"], "chrome-managed")

        self.service.set_mode("managed")
        selected = self.service._select_device(
            requested="chrome-managed",
            prefer_managed=True,
        )
        self.assertEqual(selected, "chrome-managed")

    def test_managed_browser_launches_with_isolated_bootstrap(self) -> None:
        captured: list[str] = []
        self.service.command_runner = lambda command, **_kwargs: (
            captured.extend(command) or SimpleNamespace(pid=os.getpid())
        )
        fake_chrome = Path(self.temp.name) / "Google Chrome"
        fake_chrome.write_text("", encoding="utf-8")

        with mock.patch.object(
            self.service,
            "_chrome_executable",
            return_value=fake_chrome,
        ):
            response = self.service.start_managed()

        self.assertTrue(response["running"])
        self.assertIn(
            f"--user-data-dir={self.service.app_support_root / 'BrowserCopilot' / 'managed-profile'}",
            captured,
        )
        bootstrap_url = next(
            item
            for item in captured
            if item.startswith("http://127.0.0.1:8766/api/browser/managed/bootstrap")
        )
        bootstrap_token = bootstrap_url.split("token=", 1)[1]
        managed = self.service.hello(
            {
                "deviceId": "chrome-managed-launch",
                "displayName": "托管 Chrome",
                "clientKind": "managed",
                "extensionVersion": "1.0.0",
                "browserName": "Chrome",
                "activeTabId": 11,
                "managedBootstrapToken": bootstrap_token,
            }
        )
        self.assertEqual(managed["mode"], "managed")


if __name__ == "__main__":
    unittest.main()
