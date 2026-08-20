from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControlCenterCutoverTests(unittest.TestCase):
    def test_full_stack_installer_refuses_existing_explicit_squirrel_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-stack-") as tmp:
            tmp_path = Path(tmp)
            existing_workdir = tmp_path / "caller-owned-squirrel"
            existing_workdir.mkdir()
            caller_marker = existing_workdir / "keep-me"
            caller_marker.write_text("caller owned\n", encoding="utf-8")

            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "install_product_stack.sh"), "--include-squirrel"],
                cwd=ROOT,
                env={
                    **os.environ,
                    "HOME": str(tmp_path),
                    "RAG_IME_ALLOW_DIRTY_INSTALL": "1",
                    "RAG_IME_APP_SUPPORT_DIR": str(tmp_path / "app-support"),
                    "RAG_IME_SQUIRREL_WORKDIR": str(existing_workdir),
                },
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 73)
            self.assertIn(
                "refusing to reuse existing explicit RAG_IME_SQUIRREL_WORKDIR",
                result.stderr,
            )
            self.assertEqual(caller_marker.read_text(encoding="utf-8"), "caller owned\n")
            self.assertFalse((tmp_path / "app-support").exists())

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
        self.assertIn("install_desktop_bridge_launch_agent.sh", installer)
        self.assertIn("--require desktopBridge", installer)
        self.assertIn("install_agent_gateway_launch_agent.sh", installer)
        self.assertIn("WEB_SUITE_VERIFIED=0", installer)
        self.assertIn("WEB_SUITE_VERIFIED=1", installer)
        self.assertIn('if [[ "$WEB_SUITE_VERIFIED" == "1" ]]', installer)
        self.assertIn("RAG_IME_SKIP_WEB_INSTALL=1", installer)
        self.assertIn("RAG_IME_SKIP_WEB_TESTS=1", installer)
        self.assertLess(
            installer.index("WEB_SUITE_VERIFIED=1"),
            installer.index("RAG_IME_SKIP_WEB_TESTS=1"),
        )
        self.assertIn("build_managed_pi_runtime_v2.py", installer)
        self.assertIn("--pi-worktree", installer)
        self.assertIn("RAG_IME_PI_WORKTREE", installer)
        self.assertIn("../pi/integrations/rag-ime-runtime-host", installer)
        self.assertIn("install_managed_pi_runtime.py", installer)
        self.assertIn("--no-activate", installer)
        self.assertIn("smoke_pi_session_staged_runtime.py", installer)
        self.assertIn("smoke_pi_room_composition.py", installer)
        self.assertIn("--deterministic-test-gate", installer)
        self.assertIn("--acceptance-report", installer)
        self.assertLess(
            installer.index("--no-activate"),
            installer.index("smoke_pi_session_staged_runtime.py"),
        )
        self.assertLess(
            installer.index("smoke_pi_session_staged_runtime.py"),
            installer.index("smoke_pi_room_composition.py"),
        )
        self.assertLess(
            installer.index("smoke_pi_room_composition.py"),
            installer.index("--acceptance-report"),
        )
        self.assertIn("--require piSkills", installer)
        self.assertNotIn("--require roomKernelMode", installer)
        self.assertIn("RAG_IME_INSTALL_AGENT_GATEWAY=0", installer)
        self.assertNotIn("RAG_IME_ROOM_KERNEL_MODE", installer)
        self.assertIn('"$ROOT/scripts/install_sidecar_launch_agent.sh"', installer)
        self.assertLess(
            installer.index('"$ROOT/scripts/install_mlx_predictor_launch_agent.sh"'),
            installer.index('"$ROOT/scripts/install_sidecar_launch_agent.sh"'),
        )
        self.assertIn("install_voice_input_launch_agent.sh", installer)
        self.assertIn("check_installed_product_components.py", installer)
        self.assertIn("--require-current", installer)
        self.assertIn("prepare_stack_squirrel_workspace()", installer)
        self.assertIn(
            'mktemp -d "${TMPDIR:-/tmp}/rag-ime-squirrel-install-stack.XXXXXX"',
            installer,
        )
        self.assertIn(
            "refusing to reuse existing explicit $label",
            installer,
        )
        self.assertIn(
            'RAG_IME_SQUIRREL_PATCH="$ROOT/squirrel-patches/0001-add-rag-ime-sidecar.patch"',
            installer,
        )
        self.assertIn("RAG_IME_SQUIRREL_RESET=0", installer)
        self.assertIn("RAG_IME_SQUIRREL_BUILD_DRY_RUN=0", installer)
        self.assertIn(
            'SQUIRREL_ALLOW_SOURCE_ROOT_CHANGE="${RAG_IME_SQUIRREL_ALLOW_SOURCE_ROOT_CHANGE:-0}"',
            installer,
        )
        self.assertIn(
            'RAG_IME_SQUIRREL_ALLOW_SOURCE_ROOT_CHANGE="$SQUIRREL_ALLOW_SOURCE_ROOT_CHANGE"',
            installer,
        )
        self.assertNotIn("RAG_IME_SQUIRREL_ALLOW_SOURCE_ROOT_CHANGE=0 \\", installer)
        self.assertIn(
            'run_with_stack_squirrel_workspace "$ROOT/scripts/prepare_squirrel_workspace.sh"',
            installer,
        )
        self.assertIn(
            'run_with_stack_squirrel_workspace "$ROOT/scripts/build_patched_squirrel.sh" install',
            installer,
        )
        self.assertLess(
            installer.rindex("  prepare_stack_squirrel_workspace"),
            installer.index('EXTENSION_SOURCE="$ROOT/integrations/browser-copilot/extension"'),
        )
        self.assertIn("prune_managed_pi_runtime.py", installer)
        self.assertIn("--retain-generations 2", installer)
        self.assertIn("--plan \"$PI_RETENTION_PLAN\"", installer)
        self.assertLess(
            installer.index("check_installed_product_components.py"),
            installer.index("prune_managed_pi_runtime.py"),
        )

        gateway_installer = (
            ROOT / "scripts" / "install_agent_gateway_launch_agent.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("wait_for_gateway_port_release", gateway_installer)
        self.assertIn("bootstrap_launch_agent", gateway_installer)
        self.assertIn("restore_web_source_dist", gateway_installer)
        self.assertIn("trap restore_web_source_dist EXIT", gateway_installer)
        self.assertIn('ditto "$WEB_SOURCE_DIR" "$WEB_INSTALL_DIR"', gateway_installer)

        desktop_installer = (
            ROOT / "scripts" / "install_desktop_bridge_launch_agent.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("wait_for_previous_job_release", desktop_installer)
        self.assertIn("bootstrap_launch_agent", desktop_installer)
        self.assertIn("for attempt in 1 2 3 4 5 6 7 8 9 10", desktop_installer)
        self.assertIn('launchctl print "$DOMAIN/$LABEL"', desktop_installer)
        self.assertNotIn('if launchctl print "$DOMAIN/$LABEL"', desktop_installer)
        self.assertIn('launchctl kickstart "$DOMAIN/$LABEL"', desktop_installer)
        self.assertNotIn('launchctl kickstart -k "$DOMAIN/$LABEL"', desktop_installer)

    def test_database_maintenance_stop_and_reinstall_cover_voice_and_maintenance_jobs(self) -> None:
        stop = (ROOT / "scripts" / "stop_rag_ime_runtime.sh").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_product_stack.sh").read_text(encoding="utf-8")
        voice = (ROOT / "scripts" / "install_voice_input_launch_agent.sh").read_text(encoding="utf-8")
        maintenance = (
            ROOT / "scripts" / "install_memory_book_maintenance_launch_agent.sh"
        ).read_text(encoding="utf-8")

        for label in ("com.rag-ime.voice", "com.rag-ime.memory-book-maintenance"):
            self.assertIn(label, stop)
        self.assertIn("[R]agImeVoice", stop)
        self.assertIn("[m]emory_book_maintenance_launch.py", stop)
        self.assertIn("install_voice_input_launch_agent.sh", installer)
        self.assertIn("install_memory_book_maintenance_launch_agent.sh", installer)
        self.assertLess(voice.index("launchctl enable"), voice.index("launchctl bootstrap"))
        self.assertLess(maintenance.index("launchctl enable"), maintenance.index("launchctl bootstrap"))

    def test_remote_gateway_uses_tailnet_only_serve_and_loopback_backend(self) -> None:
        script = (
            ROOT / "scripts" / "configure_agent_gateway_tailscale.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("tailscale serve", script.lower())
        self.assertIn("http://127.0.0.1:8768", script)
        self.assertIn("RAG_IME_REMOTE_ALLOWED_LOGINS", script)
        self.assertNotIn('"$TAILSCALE" funnel', script)

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
        self.assertIn("source_signature()", build)
        self.assertIn('SOURCE_SIGNATURE="$(source_signature)"', build)
        self.assertEqual(build.count("require_source_stable"), 3)
        self.assertIn(
            "source changed during Control Center build; refusing to install a mixed app",
            build,
        )
        self.assertLess(
            build.rindex("require_source_stable"),
            build.index(
                'python3 - "$RESOURCES/rag-ime-control-web-build-marker.json"'
            ),
        )
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
