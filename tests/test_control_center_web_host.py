from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "macos" / "RagImeControlWebHost"
DIST_CHECK = ROOT / "scripts" / "check_control_center_web_dist.sh"


def _write_native_dist(
    target: Path,
    *,
    marker_updates: dict[str, object] | None = None,
    javascript: str = "console.log('native-only');\n",
) -> None:
    (target / "assets").mkdir(parents=True)
    (target / "index.html").write_text(
        '<meta http-equiv="Content-Security-Policy" content="connect-src \'self\';">\n',
        encoding="utf-8",
    )
    (target / "manifest.webmanifest").write_text("{}\n", encoding="utf-8")
    (target / "assets" / "index.js").write_text(javascript, encoding="utf-8")
    marker: dict[str, object] = {
        "schemaVersion": "rag-ime.control-web-build.v1",
        "buildChannel": "production",
        "transport": "native",
        "nativeOnly": True,
        "forbiddenTransportModulesExcluded": True,
        "previewFixturesExcluded": True,
        "sourceCommit": "test-source-commit",
    }
    marker.update(marker_updates or {})
    (target / "rag-ime-control-web-build.json").write_text(
        json.dumps(marker) + "\n",
        encoding="utf-8",
    )


class ControlCenterWebHostTests(unittest.TestCase):
    def test_swift_path_ids_match_python_control_manifest(self) -> None:
        from rag_ime.control_api.route_policy import ControlPathId

        source = (HOST / "NativeRoutePolicy.swift").read_text(encoding="utf-8")
        swift_ids = set(re.findall(r'"([A-Za-z][A-Za-z0-9.-]+)"\s*:\s*route\(', source))
        swift_ids.update(re.findall(r'"(control\.(?:bootstrap|capabilities))"', source))
        python_ids = {item.value for item in ControlPathId}
        self.assertEqual(swift_ids, python_ids)
        self.assertEqual(len(swift_ids), 68)

    def test_native_route_policy_executes_fail_closed_security_cases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-native-route-") as temporary:
            output = Path(temporary) / "native-route-tests"
            environment = os.environ.copy()
            environment["CLANG_MODULE_CACHE_PATH"] = str(Path(temporary) / "clang-cache")
            environment["SWIFT_MODULECACHE_PATH"] = str(Path(temporary) / "swift-cache")
            subprocess.run(
                [
                    "xcrun",
                    "swiftc",
                    "-swift-version",
                    "5",
                    "-target",
                    "arm64-apple-macosx13.0",
                    str(HOST / "NativeRoutePolicy.swift"),
                    str(ROOT / "tests" / "swift" / "NativeRoutePolicyTests.swift"),
                    "-o",
                    str(output),
                ],
                check=True,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [str(output)],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertIn("NativeRoutePolicyTests: OK", result.stdout)

    def test_bridge_and_asset_loader_are_narrow(self) -> None:
        bridge = (HOST / "NativeBridge.swift").read_text(encoding="utf-8")
        assets = (HOST / "ControlCenterAssetSchemeHandler.swift").read_text(encoding="utf-8")
        navigation = (HOST / "NativeNavigationPolicy.swift").read_text(encoding="utf-8")

        self.assertIn('static let handlerName = "ragImeNativeBridge"', bridge)
        self.assertIn('"arbitraryFetch": false', bridge)
        self.assertIn('"arbitraryShell": false', bridge)
        self.assertNotIn("Process()", bridge)
        self.assertNotIn("NSTask", bridge)
        self.assertNotIn("unsafe-eval", assets)
        self.assertIn('url.scheme == ControlCenterAssetSchemeHandler.scheme', navigation)
        self.assertNotIn("NSWorkspace.shared.open(url)", navigation)

    def test_host_keeps_a_native_draggable_titlebar(self) -> None:
        source = (HOST / "RagImeControlWebApp.swift").read_text(encoding="utf-8")

        self.assertNotIn(".fullSizeContentView", source)
        self.assertIn("window.titlebarAppearsTransparent = false", source)
        self.assertIn("window.titleVisibility = .visible", source)
        self.assertIn("window.isMovable = true", source)

    def test_preview_build_cannot_overwrite_production_app(self) -> None:
        script = (ROOT / "scripts" / "build_control_center_web_host.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("RagImeControlWebPreview.app", script)
        self.assertIn("com.rag-ime.control.web-preview", script)
        self.assertIn('build|install-preview)', script)
        self.assertIn('build-release|install-release)', script)
        self.assertIn('INSTALL_DEST="$HOME/Applications/RagImeControlWebPreview.app"', script)
        self.assertIn('INSTALL_DEST="$HOME/Applications/RagImeControl.app"', script)
        self.assertIn('if [[ "$ACTION" == "install-preview" || "$ACTION" == "install-release" ]]', script)
        self.assertIn("must not enter the app bundle", script)
        self.assertIn("RAG_IME_CONTROL_TRANSPORT=native", script)
        self.assertIn('FRONTEND_CHANNEL="production"', script)
        self.assertIn("check_control_center_web_dist.sh", script)
        self.assertIn('"frontendTransport": "native"', script)

    def test_native_dist_guard_accepts_only_production_native_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-native-dist-") as temporary:
            dist = Path(temporary)
            _write_native_dist(dist)
            result = subprocess.run(
                ["bash", str(DIST_CHECK), str(dist), "native", "production"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("production/native", result.stdout)

    def test_native_dist_guard_rejects_mock_http_or_preview_artifacts(self) -> None:
        cases = (
            ({"transport": "mock"}, "console.log('native-only');\n"),
            ({"buildChannel": "preview"}, "console.log('native-only');\n"),
            ({}, "throw new Error('No mock response registered for system.health');\n"),
            ({}, "const endpoint = 'http://127.0.0.1:8766';\n"),
            ({}, "const session = 'session-preview';\n"),
            ({"previewFixturesExcluded": False}, "console.log('native-only');\n"),
        )
        for marker_updates, javascript in cases:
            with self.subTest(marker_updates=marker_updates, javascript=javascript):
                with tempfile.TemporaryDirectory(prefix="rag-ime-rejected-dist-") as temporary:
                    dist = Path(temporary)
                    _write_native_dist(
                        dist,
                        marker_updates=marker_updates,
                        javascript=javascript,
                    )
                    result = subprocess.run(
                        ["bash", str(DIST_CHECK), str(dist), "native", "production"],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)

    def test_production_frontend_uses_a_native_only_entry(self) -> None:
        vite = (ROOT / "control-center-web" / "vite.config.ts").read_text(encoding="utf-8")
        native_entry = (
            ROOT / "control-center-web" / "src" / "app" / "control-transport.native.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("Production control-center builds require", vite)
        self.assertIn("control-transport.native.tsx", vite)
        self.assertIn("/src/platform/http-transport.ts", vite)
        self.assertIn("/src/test/mock-transport.ts", vite)
        self.assertIn("/src/features/agent/preview-data.ts", vite)
        self.assertIn("forbiddenTransportModulesExcluded", vite)
        self.assertIn("previewFixturesExcluded", vite)
        self.assertIn("return new NativeControlTransport()", native_entry)
        self.assertNotIn("HttpControlTransport", native_entry)
        self.assertNotIn("MockControlTransport", native_entry)


if __name__ == "__main__":
    unittest.main()
