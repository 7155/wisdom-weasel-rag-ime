from __future__ import annotations

import hashlib
import json
import plistlib
import tempfile
import unittest
from pathlib import Path

from rag_ime.deployment_status import assistant_overlay_sha256, audit_installed_product


class InstalledProductAuditTests(unittest.TestCase):
    def test_reports_aligned_core_installation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-audit-") as tmp:
            root, home, support = self._layout(Path(tmp))
            commit = "a" * 40
            self._write_control(home, commit)
            self._write_component(support / "app", "sidecar-runtime", commit)
            self._write_squirrel(root, home)

            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                verify_pi_files=False,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["expectedCommit"], commit)
        self.assertTrue(report["components"]["sidecar"]["current"])
        self.assertEqual(report["components"]["roomKernelMode"]["mode"], "kernel_only")
        self.assertEqual(report["components"]["voice"]["code"], "not_installed")

    def test_detects_optional_component_from_another_product_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-audit-drift-") as tmp:
            root, home, support = self._layout(Path(tmp))
            commit = "b" * 40
            self._write_control(home, commit)
            self._write_component(support / "app", "sidecar-runtime", commit)
            self._write_component(
                support / "components" / "memory-book-maintenance",
                "memory-book-maintenance",
                "c" * 40,
            )
            self._write_squirrel(root, home)

            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                verify_pi_files=False,
            )

        self.assertFalse(report["ok"])
        component = report["components"]["memoryBookMaintenance"]
        self.assertEqual(component["code"], "commit_mismatch")
        self.assertIn("expected", component["detail"])

    def test_detects_shared_sidecar_marker_overwritten_by_another_component(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-audit-overwrite-") as tmp:
            root, home, support = self._layout(Path(tmp))
            commit = "d" * 40
            self._write_control(home, commit)
            self._write_component(support / "app", "memory-book-maintenance", commit)
            self._write_squirrel(root, home)

            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                verify_pi_files=False,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["components"]["sidecar"]["code"], "invalid_marker")

    def test_detects_a_formal_sidecar_still_using_the_legacy_room_route(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-audit-room-mode-") as tmp:
            root, home, support = self._layout(Path(tmp))
            commit = "9" * 40
            self._write_control(home, commit)
            self._write_component(support / "app", "sidecar-runtime", commit)
            self._write_squirrel(root, home)
            self._write_sidecar_plist(home, mode="off")

            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                verify_pi_files=False,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["components"]["roomKernelMode"]["code"], "inactive_mode")

    def test_desktop_bridge_requires_semantics_without_screen_capture(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-audit-desktop-") as tmp:
            root, home, support = self._layout(Path(tmp))
            commit = "e" * 40
            self._write_control(home, commit)
            self._write_component(support / "app", "sidecar-runtime", commit)
            self._write_desktop_bridge(home, commit, screen_capture=False)
            self._write_squirrel(root, home)

            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                required_components=("control", "sidecar", "squirrel", "desktopBridge"),
                verify_pi_files=False,
            )
            self.assertTrue(report["components"]["desktopBridge"]["ok"])

            self._write_desktop_bridge(home, commit, screen_capture=True)
            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                required_components=("control", "sidecar", "squirrel", "desktopBridge"),
                verify_pi_files=False,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["components"]["desktopBridge"]["code"], "incomplete_capabilities")

    def test_product_agent_skills_are_verified_independently_from_pi_executable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-audit-skills-") as tmp:
            root, home, support = self._layout(Path(tmp))
            commit = "f" * 40
            self._write_control(home, commit)
            self._write_component(support / "app", "sidecar-runtime", commit)
            self._write_squirrel(root, home)
            source = (
                root
                / "integrations"
                / "pi"
                / "skills"
                / "memory-curation"
                / "SKILL.md"
            )
            installed = (
                support
                / "Agent"
                / "config"
                / "skills"
                / "memory-curation"
                / "SKILL.md"
            )
            source.parent.mkdir(parents=True)
            installed.parent.mkdir(parents=True)
            source.write_text("remember_preview and native approval\n", encoding="utf-8")
            installed.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                required_components=("control", "sidecar", "squirrel", "piSkills"),
                verify_pi_files=False,
            )
            self.assertTrue(report["components"]["piSkills"]["ok"])

            installed.write_text("stale skill\n", encoding="utf-8")
            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                required_components=("control", "sidecar", "squirrel", "piSkills"),
                verify_pi_files=False,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["components"]["piSkills"]["code"], "source_mismatch")

    def test_portable_room_runtime_resources_detect_missing_and_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-room-resource-audit-") as tmp:
            root, home, support = self._layout(Path(tmp))
            commit = "1" * 40
            self._write_control(home, commit)
            self._write_component(support / "app", "sidecar-runtime", commit)
            self._write_squirrel(root, home)
            installed_root = support / "app" / "integrations" / "pi"
            policy = installed_root / "room-skill-policy.json"
            policy.unlink()

            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                verify_pi_files=False,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(
                report["components"]["roomRuntimeResources"]["code"],
                "not_installed",
            )

            source_policy = root / "integrations" / "pi" / "room-skill-policy.json"
            policy.write_text(source_policy.read_text(encoding="utf-8"), encoding="utf-8")
            installed_skill = (
                installed_root / "skills" / "room-test" / "SKILL.md"
            )
            installed_skill.write_text("stale room skill\n", encoding="utf-8")
            report = audit_installed_product(
                repo_root=root,
                home=home,
                app_support=support,
                verify_pi_files=False,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(
            report["components"]["roomRuntimeResources"]["code"],
            "source_mismatch",
        )

    def _layout(self, base: Path) -> tuple[Path, Path, Path]:
        root = base / "repo"
        home = base / "home"
        support = home / "Library" / "Application Support" / "RagIme"
        sources = root / "squirrel-patches" / "sources"
        sources.mkdir(parents=True)
        (root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch").write_text(
            "test patch\n", encoding="utf-8"
        )
        for name in (
            "RagImeAssistantSurfaceState.swift",
            "RagImeSuggestionCardView.swift",
            "RagImeSuggestionRowView.swift",
            "RagImeNonActivatingPanel.swift",
            "RagImeAssistantPanelController.swift",
        ):
            (sources / name).write_text(f"// {name}\n", encoding="utf-8")
        source_pi = root / "integrations" / "pi"
        installed_pi = support / "app" / "integrations" / "pi"
        source_skill = source_pi / "skills" / "room-test" / "SKILL.md"
        installed_skill = installed_pi / "skills" / "room-test" / "SKILL.md"
        agent_skill = (
            support
            / "Agent"
            / "config"
            / "skills"
            / "room-test"
            / "SKILL.md"
        )
        source_skill.parent.mkdir(parents=True)
        installed_skill.parent.mkdir(parents=True)
        agent_skill.parent.mkdir(parents=True)
        source_policy = source_pi / "room-skill-policy.json"
        installed_policy = installed_pi / "room-skill-policy.json"
        source_policy.write_text('{"schemaVersion":"test"}\n', encoding="utf-8")
        installed_policy.write_text(
            source_policy.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        source_skill.write_text("room test skill\n", encoding="utf-8")
        installed_skill.write_text(
            source_skill.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        agent_skill.write_text(
            source_skill.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self._write_sidecar_plist(home, mode="kernel_only")
        return root, home, support

    def _write_sidecar_plist(self, home: Path, *, mode: str) -> None:
        path = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as target:
            plistlib.dump(
                {
                    "Label": "com.rag-ime.sidecar",
                    "EnvironmentVariables": {"RAG_IME_ROOM_KERNEL_MODE": mode},
                },
                target,
            )

    def _write_control(self, home: Path, commit: str) -> None:
        marker = (
            home
            / "Applications"
            / "RagImeControl.app"
            / "Contents"
            / "Resources"
            / "rag-ime-control-web-build-marker.json"
        )
        self._write_json(
            marker,
            {
                "schemaVersion": "rag-ime.control-build-marker.v1",
                "gitCommit": commit,
                "gitDirty": False,
            },
        )

    def _write_component(self, directory: Path, component: str, commit: str) -> None:
        self._write_json(
            directory / "rag-ime-install-marker.json",
            {
                "schemaVersion": "rag-ime.component-install-marker.v1",
                "component": component,
                "sourceCommit": commit,
                "sourceDirty": False,
            },
        )

    def _write_desktop_bridge(self, home: Path, commit: str, *, screen_capture: bool) -> None:
        marker = (
            home
            / "Applications"
            / "RagImeDesktopBridge.app"
            / "Contents"
            / "Resources"
            / "rag-ime-desktop-bridge-build-marker.json"
        )
        self._write_json(
            marker,
            {
                "schemaVersion": "rag-ime.desktop-bridge-build-marker.v1",
                "gitCommit": commit,
                "gitDirty": False,
                "capabilities": {
                    "accessibilitySemantics": True,
                    "treeDiff": True,
                    "semanticActions": True,
                    "liveStateRevalidation": True,
                    "modelSuppliedCoordinates": False,
                    "screenCapture": screen_capture,
                },
            },
        )

    def _write_squirrel(self, root: Path, home: Path) -> None:
        patch = root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch"
        marker = (
            home
            / "Library"
            / "Input Methods"
            / "Squirrel.app"
            / "Contents"
            / "Resources"
            / "rag-ime-build-marker.json"
        )
        self._write_json(
            marker,
            {
                "schemaVersion": "rag-ime.squirrel-build-marker.v2",
                "patchSha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
                "overlaySha256": assistant_overlay_sha256(root),
                "gitDirty": False,
            },
        )

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
