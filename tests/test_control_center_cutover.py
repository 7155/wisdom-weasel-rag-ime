from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControlCenterCutoverTests(unittest.TestCase):
    def test_legacy_swift_control_center_is_removed(self) -> None:
        self.assertFalse((ROOT / "macos" / "RagImeControl").exists())

        tracked = "\n".join(
            path.as_posix()
            for path in ROOT.rglob("*")
            if path.is_file() and "node_modules" not in path.parts and "dist" not in path.parts
        )
        self.assertNotIn("macos/RagImeControl/", tracked)

    def test_public_build_entry_only_dispatches_to_the_web_host(self) -> None:
        script = (ROOT / "scripts" / "build_control_center.sh").read_text(encoding="utf-8")

        self.assertIn("build_control_center_web_host.sh", script)
        self.assertIn("build-release", script)
        self.assertIn("install-release", script)
        for forbidden in (
            "native-legacy",
            "RAG_IME_CONTROL_UI",
            "swiftc",
            "SwiftUI",
            "macos/RagImeControl",
        ):
            self.assertNotIn(forbidden, script)

    def test_release_footprint_gate_requires_the_web_bundle(self) -> None:
        script = (ROOT / "scripts" / "check_control_center_footprint.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("rag-ime-control-web-build-marker.json", script)
        self.assertIn("/WebKit.framework/", script)
        self.assertIn("control-center-web", script)
        self.assertNotIn("native-legacy", script)
        self.assertNotIn("RAG_IME_CONTROL_UI", script)

    def test_full_stack_installer_fails_closed_on_mixed_runtime_generations(self) -> None:
        entry = (ROOT / "scripts" / "build_control_center.sh").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_product_stack.sh").read_text(encoding="utf-8")

        self.assertIn("install-stack", entry)
        self.assertIn("refusing to install a mixed product stack from dirty tracked source", installer)
        self.assertIn("install_sidecar_launch_agent.sh", installer)
        self.assertIn("install_agent_gateway_launch_agent.sh", installer)
        self.assertIn("install_voice_input_launch_agent.sh", installer)
        self.assertIn("check_installed_product_components.py", installer)
        self.assertIn("--require-current", installer)

    def test_web_host_owns_the_release_bundle_and_agent_deep_link(self) -> None:
        host = ROOT / "macos" / "RagImeControlWebHost"
        app = (host / "RagImeControlWebApp.swift").read_text(encoding="utf-8")
        view = (host / "WebHostView.swift").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "build_control_center_web_host.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("com.rag-ime.control.open-agent", app)
        self.assertIn("openAgent", app)
        self.assertIn("#/agent", view)
        self.assertIn('INSTALL_DEST="$HOME/Applications/RagImeControl.app"', build)
        self.assertIn("rag-ime-control-web-build-marker.json", build)
        self.assertIn("lsregister", build)
        self.assertIn('PROCESS_PATTERN="/Contents/MacOS/$EXECUTABLE([[:space:]]|$)"', build)
        self.assertIn('pkill -TERM -f "$PROCESS_PATTERN"', build)
        self.assertIn("unable to stop the existing $EXECUTABLE", build)
        self.assertIn(
            '"$DEST/Contents/Resources/control-center-web" native "$FRONTEND_CHANNEL" "$SOURCE_COMMIT"',
            build,
        )


if __name__ == "__main__":
    unittest.main()
