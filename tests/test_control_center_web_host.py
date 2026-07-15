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
HOST_BUILD = ROOT / "scripts" / "build_control_center_web_host.sh"
DIST_CHECK = ROOT / "scripts" / "check_control_center_web_dist.sh"
WEB_GATE = ROOT / "scripts" / "test_control_center_web.sh"


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
        self.assertEqual(len(swift_ids), len(ControlPathId))

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

    def test_navigation_policy_opens_only_the_codex_device_page_externally(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-native-navigation-") as temporary:
            output = Path(temporary) / "native-navigation-tests"
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
                    str(HOST / "NativeNavigationPolicy.swift"),
                    str(ROOT / "tests" / "swift" / "NativeNavigationPolicyTests.swift"),
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
            self.assertIn("NativeNavigationPolicyTests: OK", result.stdout)

    def test_bridge_and_asset_loader_are_narrow(self) -> None:
        bridge = (HOST / "NativeBridge.swift").read_text(encoding="utf-8")
        assets = (HOST / "ControlCenterAssetSchemeHandler.swift").read_text(encoding="utf-8")
        navigation = (HOST / "NativeNavigationPolicy.swift").read_text(encoding="utf-8")
        web_host = (HOST / "WebHostView.swift").read_text(encoding="utf-8")

        self.assertIn('static let handlerName = "ragImeNativeBridge"', bridge)
        self.assertIn('"arbitraryFetch": false', bridge)
        self.assertIn('"arbitraryShell": false', bridge)
        self.assertEqual(bridge.count("Process()"), 1)
        self.assertIn('pathId: "diagnostics.action.job"', bridge)
        self.assertIn("expectedRuntimeActionCommandSha256", bridge)
        self.assertIn('executable = URL(fileURLWithPath: "/bin/bash")', bridge)
        self.assertNotIn('arguments = ["-c"', bridge)
        self.assertNotIn('requiredString("command"', bridge)
        self.assertNotIn("NSTask", bridge)
        self.assertNotIn("unsafe-eval", assets)
        self.assertIn('"frame-src blob:"', assets)
        self.assertNotIn('"frame-src \'none\'"', assets)
        self.assertIn('url.scheme == ControlCenterAssetSchemeHandler.scheme', navigation)
        self.assertNotIn("NSWorkspace.shared.open(url)", navigation)
        self.assertIn('url.host == "auth.openai.com"', navigation)
        self.assertIn('url.path == "/codex/device"', navigation)
        self.assertIn("navigationAction.navigationType == .linkActivated", web_host)
        self.assertIn("navigationPolicy.allowsExternalBrowserOpen", web_host)
        self.assertIn("NSWorkspace.shared.open(url)", web_host)

        self.assertIn('"cancelRequest"', bridge)
        self.assertIn("NativeBinaryTransferPlan.chunkRanges", bridge)
        self.assertNotIn("binary.data.base64EncodedString()", bridge)

    def test_native_binary_chunk_plan_handles_25_and_50_mib_payloads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-native-binary-") as temporary:
            output = Path(temporary) / "native-binary-tests"
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
                    str(HOST / "NativeBinaryTransfer.swift"),
                    str(ROOT / "tests" / "swift" / "NativeBinaryTransferTests.swift"),
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
            self.assertIn("NativeBinaryTransferTests: OK", result.stdout)

    def test_host_keeps_a_native_draggable_titlebar(self) -> None:
        source = (HOST / "RagImeControlWebApp.swift").read_text(encoding="utf-8")

        self.assertNotIn(".fullSizeContentView", source)
        self.assertIn("window.titlebarAppearsTransparent = false", source)
        self.assertIn("window.titleVisibility = .visible", source)
        self.assertIn("window.isMovable = true", source)

    def test_preview_build_cannot_overwrite_production_app(self) -> None:
        script = HOST_BUILD.read_text(encoding="utf-8")
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

    def test_verified_dist_reuse_is_explicit_and_fail_closed(self) -> None:
        script = HOST_BUILD.read_text(encoding="utf-8")

        self.assertIn(
            'USE_VERIFIED_WEB_DIST="${RAG_IME_USE_VERIFIED_WEB_DIST:-0}"',
            script,
        )
        self.assertIn(
            'if [[ "$USE_VERIFIED_WEB_DIST" != "0" && "$USE_VERIFIED_WEB_DIST" != "1" ]]',
            script,
        )
        self.assertIn(
            'if [[ "$USE_VERIFIED_WEB_DIST" == "0" && "${RAG_IME_SKIP_WEB_BUILD:-0}" != "1" ]]',
            script,
        )
        first_dist_guard = script.index('"$ROOT/scripts/check_control_center_web_dist.sh"')
        destructive_app_rebuild = script.index('rm -rf "$APP"')
        self.assertLess(first_dist_guard, destructive_app_rebuild)
        self.assertIn(
            '"$WEB/dist" native "$FRONTEND_CHANNEL" "$SOURCE_COMMIT"',
            script,
        )

        environment = os.environ.copy()
        environment["RAG_IME_USE_VERIFIED_WEB_DIST"] = "yes"
        result = subprocess.run(
            ["bash", str(HOST_BUILD), "build-release"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be 0 or 1", result.stderr)

    def test_web_gate_reuses_the_verified_production_dist(self) -> None:
        script = WEB_GATE.read_text(encoding="utf-8")

        self.assertIn("RAG_IME_USE_VERIFIED_WEB_DIST=1", script)
        self.assertNotIn(
            'RAG_IME_SKIP_WEB_BUILD=1 "$ROOT/scripts/build_control_center_web_host.sh" build-release',
            script,
        )

    def test_native_dist_guard_accepts_only_production_native_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-native-dist-") as temporary:
            dist = Path(temporary)
            _write_native_dist(dist)
            result = subprocess.run(
                [
                    "bash",
                    str(DIST_CHECK),
                    str(dist),
                    "native",
                    "production",
                    "test-source-commit",
                ],
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

    def test_native_dist_guard_rejects_a_stale_source_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-stale-dist-") as temporary:
            dist = Path(temporary)
            _write_native_dist(dist)
            result = subprocess.run(
                [
                    "bash",
                    str(DIST_CHECK),
                    str(dist),
                    "native",
                    "production",
                    "different-source-commit",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source commit", result.stderr)

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
