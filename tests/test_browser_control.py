from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.browser_control import BrowserControlError, BrowserControlService
from rag_ime.paw_browser_runtime import PawBrowserRuntime


class BrowserControlServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.runtime = FakePawBrowserRuntime(root / "direct-profile")
        self.service = BrowserControlService(
            root / "rag-ime.sqlite",
            app_support_root=root / "support",
            browser_runtime=self.runtime,
        )
        with self.service._connection() as connection:
            self.service._set_setting(connection, "managed_pid", str(os.getpid()))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_snapshot_is_durable_across_service_instances(self) -> None:
        self.service.push_snapshot(
            {
                "deviceId": PawBrowserRuntime.DEVICE_ID,
                "snapshotId": "snap-test",
                "tabId": self.runtime.tab_id,
                "url": "https://example.com/docs",
                "title": "Example Docs",
                "summary": "2 个可交互元素",
                "markdown": '# Example\n- [0:e1] link "Read"',
                "interactiveCount": 2,
                "viewport": {"width": 1280, "height": 720},
            }
        )
        other = BrowserControlService(
            self.service.db_path,
            app_support_root=Path(self.temp.name) / "support",
            browser_runtime=self.runtime,
        )

        snapshot = other.latest_snapshot(
            device_id=PawBrowserRuntime.DEVICE_ID,
            tab_id=self.runtime.tab_id,
        )

        self.assertEqual(snapshot["snapshotId"], "snap-test")
        self.assertIn("[0:e1]", snapshot["markdown"])

    def test_status_uses_created_at_index_for_latest_snapshot(self) -> None:
        with self.service._connection() as connection:
            indexes = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA index_list(browser_control_snapshots)"
                ).fetchall()
            }
            plan = " ".join(
                str(row[3])
                for row in connection.execute(
                    "EXPLAIN QUERY PLAN "
                    "SELECT * FROM browser_control_snapshots "
                    "ORDER BY created_at_ms DESC LIMIT 1"
                ).fetchall()
            )

        self.assertIn("idx_browser_snapshots_created", indexes)
        self.assertIn("idx_browser_snapshots_created", plan)

    def test_snapshot_urls_redact_credentials_fragments_and_sensitive_queries(self) -> None:
        unsafe_url = (
            "https://reader:password@example.com/docs"
            "?query=browser&access_token=private&session_id=session-1#account"
        )
        self.service.push_snapshot(
            {
                "deviceId": PawBrowserRuntime.DEVICE_ID,
                "snapshotId": "snap-private-url",
                "tabId": self.runtime.tab_id,
                "url": unsafe_url,
                "title": "Private URL",
                "markdown": f"# Private URL\nURL: {unsafe_url}",
            }
        )

        snapshot = self.service.latest_snapshot(
            device_id=PawBrowserRuntime.DEVICE_ID,
            tab_id=self.runtime.tab_id,
        )

        self.assertEqual(
            snapshot["url"],
            "https://example.com/docs?query=browser&access_token=%5Bredacted%5D"
            "&session_id=%5Bredacted%5D",
        )
        self.assertNotIn("password", snapshot["markdown"])
        self.assertNotIn("access_token=private", snapshot["markdown"])
        self.assertNotIn("#account", snapshot["markdown"])

    def test_inventory_contains_only_the_direct_paw_browser(self) -> None:
        items = self.service.tabs()["items"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["deviceId"], PawBrowserRuntime.DEVICE_ID)
        self.assertEqual(items[0]["clientKind"], "managed")
        self.assertEqual(items[0]["targetId"], "DIRECTTARGET")
        status = self.service.status()
        self.assertEqual(status["mode"], "managed")
        self.assertNotIn("permissions", status)
        self.assertNotIn("extensionPath", status)

    def test_browser_rejects_any_device_outside_the_isolated_profile(self) -> None:
        with self.assertRaisesRegex(BrowserControlError, "only target PAW Browser"):
            self.service.submit_command(
                "navigate",
                {
                    "deviceId": "daily-chrome",
                    "url": "https://example.com/not-allowed",
                },
            )

    def test_direct_commands_and_trace_share_the_selected_browser(self) -> None:
        for action in ("back", "forward", "reload"):
            result = self.service.submit_command(
                action,
                {"deviceId": PawBrowserRuntime.DEVICE_ID, "tabId": self.runtime.tab_id},
                session_id="session-test",
            )
            self.assertTrue(result["ok"])

        self.assertEqual(self.runtime.actions, ["back", "forward", "reload"])
        traces = self.service.traces()["items"]
        self.assertEqual([item["action"] for item in traces[:3]], ["reload", "forward", "back"])
        self.assertTrue(all(item["sourceKind"] == "agent" for item in traces[:3]))

    def test_screenshot_is_stored_behind_bounded_binary_route(self) -> None:
        result = self.service.submit_command(
            "screenshot",
            {"tabId": self.runtime.tab_id},
            session_id="control-center",
        )
        snapshot_id = str(result["result"]["snapshotId"])

        mime_type, data = self.service.snapshot_image(snapshot_id)

        self.assertEqual(mime_type, "image/png")
        self.assertEqual(data, FakePawBrowserRuntime.PNG_BYTES)
        trace = self.service.traces()["items"][0]
        self.assertEqual(trace["sourceKind"], "human")
        self.assertEqual(trace["result"]["snapshotId"], snapshot_id)

    def test_agent_browser_action_runs_without_per_action_approval(self) -> None:
        sessions = AgentSessionStore(Path(self.temp.name) / "agent.sqlite")
        sessions.initialize()
        session = sessions.create(title="managed browser", created_at_ms=1)
        gateway = ControlToolGateway(
            sessions=sessions,
            management=object(),
            core=object(),
            project="browser-test",
            browser_control=self.service,
        )

        response = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": session["id"],
                "tool": "browser",
                "toolCallId": "tool:browser:managed-direct",
                "args": {
                    "op": "navigate",
                    "url": "https://example.com/managed",
                },
            }
        )["result"]

        self.assertNotIn("approvalRequired", response)
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["action"], "navigate")
        self.assertEqual(self.runtime.actions, ["navigate"])
        trace = self.service.traces()["items"][0]
        self.assertEqual(trace["sessionId"], session["id"])
        self.assertEqual(trace["sourceKind"], "agent")
        self.assertEqual(trace["target"], "https://example.com/managed")

    def test_legacy_pairing_and_permission_apis_are_absent(self) -> None:
        for name in (
            "pairing",
            "authenticate",
            "hello",
            "set_mode",
            "next_command",
            "request_permission",
            "decide_permission",
        ):
            self.assertFalse(hasattr(self.service, name), name)

    def test_ego_script_attaches_to_the_existing_paw_browser(self) -> None:
        captured: dict[str, object] = {}

        def start_ego(command: list[str], **kwargs: object) -> FakeEgoProcess:
            captured["command"] = command
            captured["env"] = kwargs.get("env")
            environment = kwargs.get("env")
            assert isinstance(environment, dict)
            return FakeEgoProcess(Path(str(environment["EGO_PAW_TRACE_PATH"])))

        self.service.ego_process_runner = start_ego
        with (
            mock.patch.object(self.service, "_ego_node", return_value=Path("/usr/bin/node")),
            mock.patch.object(self.service, "_ensure_ego_host") as ensure_host,
        ):
            result = self.service.submit_command(
                "run",
                {
                    "script": "const task = await taskSpaces.useOrCreate('test'); console.log(task.id)",
                    "timeoutMs": 3_000,
                },
                session_id="session-ego-test",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["stdout"], '{"taskSpaceId":2}\n')
        self.assertFalse(result["result"]["secondBrowserProcess"])
        self.assertIn("--permission", captured["command"])
        self.assertFalse(any("allow-child-process" in value for value in captured["command"]))
        self.assertTrue(any("allow-fs-write" in value for value in captured["command"]))
        environment = captured["env"]
        self.assertEqual(environment["EGO_CDP_PORT"], "9222")
        self.assertEqual(environment["EGO_USER_DATA_DIR"], str(self.runtime.profile_path))
        ensure_host.assert_called_once()
        steps = self.service.traces()["items"][0]["steps"]
        self.assertEqual(
            [(step["event"], step["action"]) for step in steps],
            [("started", "click"), ("completed", "click")],
        )

    def test_ego_host_restarts_when_doctor_owns_a_stale_cdp_port(self) -> None:
        doctor_calls: list[list[str]] = []
        responses = iter(
            [
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "ok": True,
                            "cdpPort": 9111,
                            "cdpUp": False,
                            "profileDir": str(self.runtime.profile_path),
                        }
                    ),
                    stderr="",
                ),
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "ok": True,
                            "cdpPort": 9222,
                            "cdpUp": True,
                            "profileDir": str(self.runtime.profile_path),
                        }
                    ),
                    stderr="",
                ),
            ]
        )

        def check(command: list[str], **_kwargs: object) -> SimpleNamespace:
            doctor_calls.append(command)
            return next(responses)

        self.service.ego_check_runner = check
        environment = {
            "EGO_CDP_PORT": "9222",
            "EGO_USER_DATA_DIR": str(self.runtime.profile_path),
        }
        with (
            mock.patch.object(self.service, "_ego_runtime_available", return_value=True),
            mock.patch.object(self.service, "_stop_ego_host", return_value=True) as stop_host,
        ):
            self.service._ensure_ego_host(
                node=Path("/usr/bin/node"),
                environment=environment,
            )

        stop_host.assert_called_once_with()
        self.assertEqual(len(doctor_calls), 2)

    def test_stop_terminates_the_active_ego_script_and_cancels_visible_trace(self) -> None:
        with self.service._connection() as connection:
            self.service._set_setting(connection, "ego_runner_pid", "424242")
            self.service._set_setting(connection, "ego_runner_command_id", "bcmd-active")
            connection.execute(
                """
                INSERT INTO browser_control_commands(
                    command_id, device_id, session_id, action, payload_json,
                    status, created_at_ms
                ) VALUES ('bcmd-active', ?, 'session-test', 'run', '{}', 'claimed', 1)
                """,
                (PawBrowserRuntime.DEVICE_ID,),
            )
        with (
            mock.patch.object(self.service, "_pid_running", return_value=True),
            mock.patch.object(self.service, "_terminate_process_group") as terminate,
        ):
            result = self.service.stop()

        self.assertTrue(result["egoRunnerStopped"])
        self.assertEqual(result["cancelled"], 1)
        terminate.assert_called_once_with(424242)
        trace = self.service.traces()["items"][0]
        self.assertEqual(trace["status"], "cancelled")
        with self.service._connection() as connection:
            self.assertEqual(self.service._setting(connection, "ego_runner_pid"), "")

    def test_managed_browser_launches_an_isolated_direct_cdp_profile(self) -> None:
        root = Path(self.temp.name)
        runtime = FakePawBrowserRuntime(root / "launch-profile")
        service = BrowserControlService(
            root / "launch.sqlite",
            app_support_root=root / "launch-support",
            browser_runtime=runtime,
        )
        captured: list[str] = []

        def launch(command: list[str], **_kwargs: object) -> SimpleNamespace:
            captured.extend(command)
            return SimpleNamespace(pid=os.getpid())

        service.command_runner = launch
        fake_chrome = root / "Google Chrome"
        fake_chrome.write_text("", encoding="utf-8")

        with mock.patch.object(service, "_chrome_executable", return_value=fake_chrome):
            response = service.start_managed()

        self.assertTrue(response["running"])
        self.assertIn(f"--user-data-dir={runtime.profile_path}", captured)
        self.assertIn("--remote-debugging-address=127.0.0.1", captured)
        self.assertIn("--remote-debugging-port=0", captured)
        self.assertFalse(any("extension" in item for item in captured))
        self.assertFalse(any("bootstrap" in item for item in captured))
        self.assertEqual(response["controlProtocol"], "ego-browser")
        self.assertEqual(response["browserTransport"], "cdp")
        self.assertFalse(response["egoBrowser"]["secondBrowserProcess"])

    def test_managed_browser_adopts_the_live_electron_host_without_launching_chrome(self) -> None:
        root = Path(self.temp.name)
        runtime = FakePawBrowserRuntime(root / "electron-profile")
        runtime.host_pid_file.parent.mkdir(parents=True, exist_ok=True)
        runtime.host_pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
        service = BrowserControlService(
            root / "electron.sqlite",
            app_support_root=root / "electron-support",
            browser_runtime=runtime,
        )

        with mock.patch.object(service, "_chrome_executable") as chrome:
            response = service.start_managed()

        chrome.assert_not_called()
        self.assertTrue(response["running"])
        self.assertTrue(response["connected"])
        self.assertEqual(response["hostKind"], "electron-webview")


class FakePawBrowserRuntime:
    PNG_BYTES = b"\x89PNG\r\n\x1a\nfixture"

    def __init__(self, profile_path: Path) -> None:
        self.profile_path = profile_path
        self.host_pid_file = profile_path / "PAWBrowserHost.pid"
        self.tab_id = PawBrowserRuntime.tab_id("DIRECTTARGET")
        self.actions: list[str] = []

    def port(self) -> int:
        return 9222

    def version(self, _port: int) -> dict[str, object]:
        return {"Browser": "Chrome/Test"}

    def tabs(self, _port: int) -> list[dict[str, object]]:
        return [{
            "deviceId": PawBrowserRuntime.DEVICE_ID,
            "deviceName": PawBrowserRuntime.DISPLAY_NAME,
            "clientKind": "managed",
            "targetId": "DIRECTTARGET",
            "tabId": self.tab_id,
            "title": "Direct",
            "url": "https://example.com",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/DIRECTTARGET",
            "active": True,
            "connected": True,
        }]

    def execute(self, _port: int, action: str, payload: object) -> dict[str, object]:
        self.actions.append(action)
        result: dict[str, object] = {
            "ok": True,
            "summary": f"history:{action}" if action in {"back", "forward"} else "已打开页面",
            "tabId": self.tab_id,
            "url": "https://example.com/managed",
            "title": "Managed",
            "markdown": "# Managed",
            "interactiveCount": 0,
            "viewport": {},
        }
        if action == "screenshot":
            encoded = base64.b64encode(self.PNG_BYTES).decode("ascii")
            result["screenshotDataUrl"] = f"data:image/png;base64,{encoded}"
        return result

    def prepare_launch(self) -> None:
        self.profile_path.mkdir(parents=True, exist_ok=True)

    def launch_command(self, executable: Path) -> list[str]:
        return [
            str(executable),
            f"--user-data-dir={self.profile_path}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
        ]

    def wait_for_port(self) -> int:
        return 9222


class FakeEgoProcess:
    pid = 424243
    returncode = 0

    def __init__(self, trace_path: Path) -> None:
        self.trace_path = trace_path

    def communicate(
        self,
        *,
        input: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        del input, timeout
        self.trace_path.write_text(
            "\n".join(
                [
                    '{"schemaVersion":"paw.ego-browser-step.v1","event":"started","action":"click","target":"getByRole(button): Continue","atMs":10}',
                    '{"schemaVersion":"paw.ego-browser-step.v1","event":"completed","action":"click","target":"getByRole(button): Continue","atMs":20}',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return '{"taskSpaceId":2}\n', ""


if __name__ == "__main__":
    unittest.main()
