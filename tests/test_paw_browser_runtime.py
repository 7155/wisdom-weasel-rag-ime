from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from rag_ime.paw_browser_runtime import PawBrowserRuntime


class PawBrowserRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.calls: list[tuple[str, str, object]] = []
        self.targets = [
            {
                "id": "A1B2C3D4E5F6",
                "type": "page",
                "title": "PAW docs",
                "url": "https://example.com/docs",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/A1B2C3D4E5F6",
            }
        ]
        self.runtime = PawBrowserRuntime(
            Path(self.temp.name) / "runtime-profile",
            json_request=self._json_request,
            cdp_request=self._cdp_request,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_tabs_are_direct_devtools_targets_with_stable_numeric_ids(self) -> None:
        tabs = self.runtime.tabs(9222)

        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["targetId"], "A1B2C3D4E5F6")
        self.assertEqual(tabs[0]["tabId"], self.runtime.tab_id("A1B2C3D4E5F6"))
        self.assertEqual(tabs[0]["title"], "PAW docs")

    def test_live_electron_host_uses_its_own_listener_instead_of_a_stale_shared_port_file(self) -> None:
        profile = Path(self.temp.name) / "shared-runtime-profile"
        profile.mkdir(parents=True)
        (profile / "PAWBrowserHost.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        (profile / "DevToolsActivePort").write_text("60028\n/devtools/browser/stale\n", encoding="utf-8")

        def request(_method: str, url: str) -> object:
            if url == "http://127.0.0.1:59957/json/version":
                return {"Browser": "Chrome/150"}
            raise OSError("not a DevTools listener")

        runtime = PawBrowserRuntime(
            profile,
            json_request=request,
            listening_ports=lambda pid: [59957, 8770] if pid == os.getpid() else [],
        )

        self.assertEqual(runtime.port(), 59957)

    def test_live_electron_host_fails_closed_when_the_stale_port_belongs_elsewhere(self) -> None:
        profile = Path(self.temp.name) / "ambiguous-runtime-profile"
        profile.mkdir(parents=True)
        (profile / "PAWBrowserHost.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        (profile / "DevToolsActivePort").write_text("60028\n/devtools/browser/stale\n", encoding="utf-8")
        runtime = PawBrowserRuntime(
            profile,
            json_request=lambda _method, _url: (_ for _ in ()).throw(OSError("not DevTools")),
            listening_ports=lambda _pid: [8770],
        )

        self.assertEqual(runtime.port(), 0)

    def test_standalone_browser_still_uses_the_profile_port_file(self) -> None:
        self.runtime.profile_path.mkdir(parents=True)
        self.runtime.port_file.write_text("9222\n/devtools/browser/root\n", encoding="utf-8")

        self.assertEqual(self.runtime.port(), 9222)

    def test_electron_host_page_is_excluded_and_selected_webview_is_first(self) -> None:
        self.targets = [
            {
                "id": "HOST",
                "type": "page",
                "title": "Personal Agent Workbench",
                "url": "http://127.0.0.1:54321/?frontend=paw-os&pawHost=electron#/browser",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/HOST",
            },
            {
                "id": "GUEST-ONE",
                "type": "webview",
                "title": "First",
                "url": "https://first.example/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/GUEST-ONE",
            },
            {
                "id": "GUEST-TWO",
                "type": "webview",
                "title": "Second",
                "url": "https://second.example/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/GUEST-TWO",
            },
        ]
        self.runtime.active_target_file.parent.mkdir(parents=True, exist_ok=True)
        self.runtime.active_target_file.write_text(
            '{"targetId":"GUEST-TWO","title":"Second","url":"https://second.example/"}\n',
            encoding="utf-8",
        )

        tabs = self.runtime.tabs(9222)

        self.assertEqual([tab["title"] for tab in tabs], ["Second", "First"])
        self.assertTrue(tabs[0]["active"])
        self.assertFalse(tabs[1]["active"])

    def test_navigate_click_and_type_use_cdp_without_a_command_queue(self) -> None:
        tab_id = self.runtime.tab_id("A1B2C3D4E5F6")

        navigated = self.runtime.execute(9222, "navigate", {"tabId": tab_id, "url": "https://example.com/next"})
        clicked = self.runtime.execute(9222, "click", {"tabId": tab_id, "refId": "0:e1"})
        typed = self.runtime.execute(9222, "type", {"tabId": tab_id, "refId": "0:e2", "text": "hello", "clear": True})

        methods = [method for kind, method, _params in self.calls if kind == "cdp"]
        self.assertIn("Page.navigate", methods)
        self.assertGreaterEqual(methods.count("Runtime.evaluate"), 4)
        self.assertTrue(navigated["ok"])
        self.assertTrue(clicked["ok"])
        self.assertTrue(typed["ok"])
        self.assertEqual(typed["targetId"], "A1B2C3D4E5F6")
        self.assertEqual(typed["title"], "PAW docs")

    def test_screenshot_returns_a_bounded_data_url_and_structured_page(self) -> None:
        result = self.runtime.execute(
            9222,
            "screenshot",
            {"tabId": self.runtime.tab_id("A1B2C3D4E5F6")},
        )

        self.assertEqual(result["screenshotDataUrl"], "data:image/png;base64,iVBORw0KGgo=")
        self.assertIn("# PAW docs", result["markdown"])
        self.assertEqual(result["interactiveCount"], 2)

    def test_closing_the_last_tab_keeps_a_blank_page_available(self) -> None:
        result = self.runtime.execute(
            9222,
            "close_tab",
            {"tabId": self.runtime.tab_id("A1B2C3D4E5F6")},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["url"], "about:blank")
        self.assertIn("Page.navigate", [method for kind, method, _params in self.calls if kind == "cdp"])
        self.assertFalse(any(kind == "json" and "/json/close/" in str(params) for kind, _method, params in self.calls))

    def _json_request(self, method: str, url: str) -> object:
        self.calls.append(("json", method, url))
        if url.endswith("/json/version"):
            return {"Browser": "Chrome/140", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/root"}
        if "/json/list" in url:
            return self.targets
        return {}

    def _cdp_request(self, websocket_url: str, method: str, params: dict[str, object]) -> object:
        self.calls.append(("cdp", method, params))
        if method == "Runtime.evaluate" and "document.title" in str(params.get("expression") or ""):
            return {
                "result": {
                    "value": {
                        "title": "PAW docs",
                        "url": "https://example.com/docs",
                        "markdown": "# PAW docs\n- [0:e1] button \"Continue\"",
                        "interactiveCount": 2,
                        "viewport": {"width": 1280, "height": 720},
                    }
                }
            }
        if method == "Page.captureScreenshot":
            return {"data": "iVBORw0KGgo="}
        return {"result": {"value": True}}


if __name__ == "__main__":
    unittest.main()
