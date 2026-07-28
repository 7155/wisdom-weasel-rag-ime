from __future__ import annotations

import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from rag_ime.macos_uninstall import (
    MacOSUninstallOptions,
    apply_macos_uninstall_plan,
    build_macos_uninstall_plan,
    write_uninstall_report,
)


class MacOSUninstallTests(unittest.TestCase):
    def test_home_that_resolves_to_filesystem_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-home-root-") as tmp:
            root_link = Path(tmp) / "not-a-home"
            root_link.symlink_to("/", target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "filesystem root"):
                build_macos_uninstall_plan(root_link)

    def test_default_plan_preserves_user_data_rime_squirrel_and_credentials(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-plan-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)
            plan = build_macos_uninstall_plan(home, uid=501)

        self.assertTrue(plan["ok"])
        self.assertTrue(plan["requiresExplicitApply"])
        self.assertEqual(plan["domain"], "gui/501")
        self.assertEqual(plan["options"]["componentScope"], "all")
        planned_kinds = {item["kind"] for item in plan["actions"] if item["status"] == "planned"}
        self.assertEqual(planned_kinds, {"remove_launch_agent", "remove_owned_app"})
        launch_agents = [
            item for item in plan["actions"] if item["kind"] == "remove_launch_agent"
        ]
        active_labels = {
            item["metadata"]["expectedLabel"]
            for item in launch_agents
            if item["metadata"]["lifecycle"] == "active"
        }
        legacy_labels = {
            item["metadata"]["expectedLabel"]
            for item in launch_agents
            if item["metadata"]["lifecycle"] == "legacy"
        }
        self.assertEqual(
            active_labels,
            {
                "com.rag-ime.agent-gateway",
                "com.rag-ime.desktop-bridge",
                "com.rag-ime.memory-book-maintenance",
                "com.rag-ime.mineru",
                "com.rag-ime.mlx-predictor",
                "com.rag-ime.sidecar",
                "com.rag-ime.voice",
            },
        )
        self.assertEqual(legacy_labels, {"com.rag-ime.frontend"})
        self.assertFalse(plan["options"]["removePatchedSquirrel"])
        self.assertFalse(plan["options"]["removeRimeManagedConfig"])
        self.assertFalse(plan["options"]["purgeLocalData"])
        self.assertFalse(plan["options"]["purgeCredentials"])
        self.assertNotIn("private-token", json.dumps(plan, ensure_ascii=False))

    def test_plan_refuses_unmarked_squirrel_and_wrong_app_bundle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-unowned-") as tmp:
            home = Path(tmp)
            self._write_app(home / "Applications" / "RagImeControl.app", "org.example.control")
            squirrel = home / "Library" / "Input Methods" / "Squirrel.app"
            self._write_app(squirrel, "im.rime.inputmethod.Squirrel")

            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(remove_patched_squirrel=True),
            )

        control = next(item for item in plan["actions"] if str(item["target"]).endswith("RagImeControl.app"))
        squirrel_action = next(item for item in plan["actions"] if item["kind"] == "remove_marked_squirrel")
        self.assertEqual(control["status"], "skipped_unverified")
        self.assertEqual(squirrel_action["status"], "skipped_unverified")
        warning_ids = {item["id"] for item in plan["warnings"]}
        self.assertIn("app_bundle_not_owned", warning_ids)
        self.assertIn("squirrel_not_owned", warning_ids)

    def test_plan_refuses_wrong_launch_agent_label(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-agent-owner-") as tmp:
            home = Path(tmp)
            target = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            target.parent.mkdir(parents=True)
            target.write_bytes(plistlib.dumps({"Label": "org.example.unrelated"}))

            plan = build_macos_uninstall_plan(home)
            action = next(item for item in plan["actions"] if item["target"] == str(target))

        self.assertEqual(action["status"], "skipped_unverified")
        self.assertIn("launch_agent_not_owned", {item["id"] for item in plan["warnings"]})

    def test_apply_rechecks_launch_agent_ownership_after_planning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-agent-toctou-") as tmp:
            home = Path(tmp)
            target = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            target.parent.mkdir(parents=True)
            target.write_bytes(plistlib.dumps({"Label": "com.rag-ime.sidecar"}))
            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(component_scope="sidecar"),
            )
            target.write_bytes(plistlib.dumps({"Label": "org.example.replaced"}))
            calls: list[list[str]] = []

            def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
                calls.append([str(item) for item in args])
                return subprocess.CompletedProcess(args, 0, "", "")

            report = apply_macos_uninstall_plan(plan, command_runner=runner, platform_name="darwin")

            self.assertFalse(report["ok"])
            self.assertEqual(report["results"][0]["status"], "failed")
            self.assertTrue(target.is_file())
            self.assertEqual(calls, [])

    def test_apply_stops_before_unlink_or_later_removal_when_bootout_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-bootout-failure-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)
            first_plist = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.rag-ime.agent-gateway.plist"
            )
            control_app = home / "Applications" / "RagImeControl.app"
            calls: list[list[str]] = []

            def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
                command = [str(item) for item in args]
                calls.append(command)
                return subprocess.CompletedProcess(
                    command,
                    5,
                    "",
                    "Input/output error",
                )

            plan = build_macos_uninstall_plan(home, uid=501)
            report = apply_macos_uninstall_plan(
                plan,
                command_runner=runner,
                platform_name="darwin",
            )

            self.assertFalse(report["ok"])
            self.assertEqual(len(calls), 1)
            self.assertTrue(first_plist.is_file())
            self.assertTrue(control_app.is_dir())
            self.assertEqual(report["results"][0]["status"], "failed")
            self.assertTrue(
                all(
                    result["status"] == "not_applied"
                    for result in report["results"][1:]
                )
            )

    def test_apply_treats_an_already_unloaded_launch_agent_as_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-bootout-absent-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)
            calls: list[list[str]] = []

            def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
                command = [str(item) for item in args]
                calls.append(command)
                return subprocess.CompletedProcess(
                    command,
                    3,
                    "",
                    "Boot-out failed: 3: No such process",
                )

            plan = build_macos_uninstall_plan(
                home,
                uid=501,
                options=MacOSUninstallOptions(component_scope="sidecar"),
            )
            report = apply_macos_uninstall_plan(
                plan,
                command_runner=runner,
                platform_name="darwin",
            )

            self.assertTrue(report["ok"])
            self.assertEqual(len(calls), 2)
            self.assertTrue(
                all(result["status"] == "already_absent" for result in report["results"])
            )
            self.assertFalse(
                (home / "Library" / "LaunchAgents" / "com.rag-ime.agent-gateway.plist").exists()
            )
            self.assertFalse(
                (home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist").exists()
            )

    def test_component_scope_limits_base_removal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-scope-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)

            voice = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(component_scope="voice"),
            )
            sidecar = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(component_scope="sidecar"),
            )

        self.assertEqual(
            {Path(item["target"]).name for item in voice["actions"]},
            {"com.rag-ime.voice.plist", "RagImeVoice.app"},
        )
        self.assertEqual(
            {Path(item["target"]).name for item in sidecar["actions"]},
            {"com.rag-ime.sidecar.plist", "com.rag-ime.agent-gateway.plist"},
        )

    def test_apply_removes_only_owned_components_and_managed_rime_blocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-apply-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)
            calls: list[list[str]] = []

            def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
                command = [str(item) for item in args]
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, "", "")

            plan = build_macos_uninstall_plan(
                home,
                uid=501,
                options=MacOSUninstallOptions(
                    remove_patched_squirrel=True,
                    remove_rime_managed_config=True,
                ),
            )
            report = apply_macos_uninstall_plan(plan, command_runner=runner, platform_name="darwin")

            self.assertTrue(report["ok"])
            self.assertFalse((home / "Applications" / "RagImeControl.app").exists())
            self.assertFalse((home / "Applications" / "RagImeVoice.app").exists())
            self.assertFalse((home / "Library" / "Input Methods" / "Squirrel.app").exists())
            self.assertTrue((home / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite").is_file())
            for name, _, _ in self._rime_blocks():
                target = home / "Library" / "Rime" / name
                text = target.read_text(encoding="utf-8")
                self.assertIn("user-owned-setting", text)
                self.assertNotIn("RAG-IME", text)
                self.assertTrue(target.with_name(target.name + ".rag-ime-uninstall.bak").is_file())

            self.assertEqual(len([call for call in calls if call[0] == "launchctl"]), 8)
        self.assertFalse(any(call[0] == "security" for call in calls))

    def test_runtime_cache_purge_removes_only_owned_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-runtime-cache-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)
            app_support = home / "Library" / "Application Support" / "RagIme"
            removable = (
                app_support / "app",
                app_support / "components",
                app_support / "BrowserCopilot" / "extension",
                app_support / "disabled-input-method-backups",
                home
                / "Library"
                / "Caches"
                / "RagIme"
                / "BrowserCopilot"
                / "managed-profile"
                / "Default"
                / "Cache",
                home
                / "Library"
                / "Caches"
                / "RagIme"
                / "BrowserCopilot"
                / "managed-profile"
                / "Default"
                / "Code Cache",
            )
            for target in removable:
                target.mkdir(parents=True, exist_ok=True)
                (target / "owned-cache").write_text("remove\n", encoding="utf-8")
            preserved = (
                app_support / "rag-ime.sqlite",
                app_support / "config.json",
                app_support / "Agent" / "settings.json",
                app_support / "curated-memory" / "atom.json",
                app_support / "backups" / "rag-ime.sqlite",
                app_support / "PiRuntime" / "current.json",
                app_support / "KnowledgeRuntime" / "current.json",
                app_support / "BrowserCopilot" / "managed-profile" / "Preferences",
                app_support / "MinerU" / "config.json",
            )
            for target in preserved[1:]:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("keep\n", encoding="utf-8")

            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(purge_runtime_cache=True),
            )
            report = apply_macos_uninstall_plan(
                plan,
                command_runner=lambda args: subprocess.CompletedProcess(args, 0, "", ""),
                platform_name="darwin",
            )

            self.assertTrue(report["ok"])
            self.assertTrue(all(not target.exists() for target in removable))
            self.assertTrue(all(target.is_file() for target in preserved))
            self.assertFalse(plan["options"]["purgeLocalData"])
            self.assertTrue(plan["options"]["purgeRuntimeCache"])

    def test_squirrel_marker_v1_and_v2_are_owned_but_rechecked_on_apply(self) -> None:
        for schema in (
            "rag-ime.squirrel-build-marker.v1",
            "rag-ime.squirrel-build-marker.v2",
        ):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory(
                prefix="rag-ime-uninstall-squirrel-schema-"
            ) as tmp:
                home = Path(tmp)
                self._seed_owned_install(home)
                squirrel = home / "Library" / "Input Methods" / "Squirrel.app"
                marker = squirrel / "Contents" / "Resources" / "rag-ime-build-marker.json"
                marker.write_text(
                    json.dumps(
                        {
                            "schemaVersion": schema,
                            "bundleId": "im.rime.inputmethod.Squirrel",
                        }
                    ),
                    encoding="utf-8",
                )
                plan = build_macos_uninstall_plan(
                    home,
                    options=MacOSUninstallOptions(remove_patched_squirrel=True),
                )
                action = next(
                    item for item in plan["actions"] if item["kind"] == "remove_marked_squirrel"
                )
                self.assertEqual(action["status"], "planned")

                marker.write_text(
                    json.dumps(
                        {
                            "schemaVersion": "rag-ime.squirrel-build-marker.v3",
                            "bundleId": "im.rime.inputmethod.Squirrel",
                        }
                    ),
                    encoding="utf-8",
                )
                report = apply_macos_uninstall_plan(
                    plan,
                    command_runner=lambda args: subprocess.CompletedProcess(
                        args,
                        0,
                        "",
                        "",
                    ),
                    platform_name="darwin",
                )

                squirrel_result = next(
                    item for item in report["results"] if item["kind"] == "remove_marked_squirrel"
                )
                self.assertEqual(squirrel_result["status"], "failed")
                self.assertTrue(squirrel.is_dir())

    def test_explicit_purge_removes_local_data_logs_and_keychain_items(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-purge-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)
            calls: list[list[str]] = []

            def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
                command = [str(item) for item in args]
                calls.append(command)
                return subprocess.CompletedProcess(command, 44 if command[0] == "security" else 0, "", "")

            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(
                    purge_local_data=True,
                    purge_credentials=True,
                    purge_voice_config=True,
                ),
            )
            report = apply_macos_uninstall_plan(plan, command_runner=runner, platform_name="darwin")

            self.assertTrue(report["ok"])
            self.assertFalse((home / "Library" / "Application Support" / "RagIme").exists())
            self.assertFalse((home / "Library" / "Logs" / "RagIme").exists())

        self.assertEqual(len([call for call in calls if call[0] == "security"]), 3)

    def test_voice_config_purge_keeps_other_local_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-voice-config-") as tmp:
            home = Path(tmp)
            self._seed_owned_install(home)
            hotwords = home / "Library" / "Application Support" / "RagIme" / "voice-hotwords.json"
            database = home / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite"
            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(
                    component_scope="voice",
                    purge_voice_config=True,
                ),
            )

            report = apply_macos_uninstall_plan(
                plan,
                command_runner=lambda args: subprocess.CompletedProcess(args, 0, "", ""),
                platform_name="darwin",
            )

            self.assertTrue(report["ok"])
            self.assertFalse(hotwords.exists())
            self.assertTrue(database.is_file())

    def test_apply_rejects_path_outside_selected_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-escape-") as tmp:
            home = Path(tmp) / "home"
            outside = Path(tmp) / "outside.txt"
            home.mkdir()
            outside.write_text("keep\n", encoding="utf-8")
            plan = build_macos_uninstall_plan(home)
            plan["actions"] = [
                {
                    "kind": "purge_owned_data",
                    "target": str(outside),
                    "status": "planned",
                    "metadata": {},
                }
            ]

            report = apply_macos_uninstall_plan(plan, platform_name="darwin")

            self.assertFalse(report["ok"])
            self.assertEqual(report["results"][0]["status"], "failed")
            self.assertTrue(outside.is_file())

    def test_apply_rejects_unallowlisted_path_inside_selected_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-allowlist-") as tmp:
            home = Path(tmp)
            unrelated = home / "Documents" / "keep.txt"
            unrelated.parent.mkdir()
            unrelated.write_text("keep\n", encoding="utf-8")
            plan = build_macos_uninstall_plan(home)
            plan["actions"] = [
                {
                    "kind": "purge_owned_data",
                    "target": str(unrelated),
                    "status": "planned",
                    "metadata": {},
                }
            ]

            report = apply_macos_uninstall_plan(plan, platform_name="darwin")

            self.assertFalse(report["ok"])
            self.assertEqual(report["results"][0]["status"], "failed")
            self.assertTrue(unrelated.is_file())

    def test_incomplete_rime_markers_are_never_edited(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-rime-marker-") as tmp:
            home = Path(tmp)
            target = home / "Library" / "Rime" / "squirrel.custom.yaml"
            target.parent.mkdir(parents=True)
            original = "user-owned-setting: true\n# >>> RAG-IME managed block\nmanaged: true\n"
            target.write_text(original, encoding="utf-8")
            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(remove_rime_managed_config=True),
            )
            action = next(item for item in plan["actions"] if item["target"] == str(target))
            report = apply_macos_uninstall_plan(plan, platform_name="darwin")

            self.assertEqual(action["status"], "skipped_unverified")
            self.assertIn("rime_managed_markers_incomplete", {item["id"] for item in plan["warnings"]})
            self.assertTrue(report["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertFalse(target.with_name(target.name + ".rag-ime-uninstall.bak").exists())

    def test_duplicate_rime_markers_are_never_edited(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-rime-duplicate-") as tmp:
            home = Path(tmp)
            target = home / "Library" / "Rime" / "squirrel.custom.yaml"
            target.parent.mkdir(parents=True)
            block = "# >>> RAG-IME managed block\nmanaged: true\n# <<< RAG-IME managed block\n"
            original = f"user-owned-setting: true\n{block}{block}"
            target.write_text(original, encoding="utf-8")

            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(remove_rime_managed_config=True),
            )
            action = next(item for item in plan["actions"] if item["target"] == str(target))
            report = apply_macos_uninstall_plan(plan, platform_name="darwin")

            self.assertEqual(action["status"], "skipped_unverified")
            self.assertIn("rime_managed_markers_ambiguous", {item["id"] for item in plan["warnings"]})
            self.assertTrue(report["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_rime_backup_never_follows_preexisting_dangling_symlink(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-rime-backup-") as tmp:
            root = Path(tmp)
            home = root / "home"
            target = home / "Library" / "Rime" / "squirrel.custom.yaml"
            target.parent.mkdir(parents=True)
            target.write_text(
                "user-owned-setting: true\n"
                "# >>> RAG-IME managed block\nmanaged: true\n# <<< RAG-IME managed block\n",
                encoding="utf-8",
            )
            outside = root / "outside-backup"
            first_backup = target.with_name(target.name + ".rag-ime-uninstall.bak")
            first_backup.symlink_to(outside)
            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(remove_rime_managed_config=True),
            )

            report = apply_macos_uninstall_plan(plan, platform_name="darwin")
            result = next(item for item in report["results"] if item["kind"] == "remove_rime_managed_block")
            second_backup = target.with_name(target.name + ".rag-ime-uninstall.bak.1")

            self.assertTrue(report["ok"])
            self.assertEqual(result["backupPath"], str(second_backup))
            self.assertTrue(first_backup.is_symlink())
            self.assertFalse(outside.exists())
            self.assertTrue(second_backup.is_file())

    def test_symlinked_rime_target_outside_home_is_never_read_or_edited(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-rime-symlink-") as tmp:
            root = Path(tmp)
            home = root / "home"
            outside = root / "outside.yaml"
            outside_text = (
                "outside-user-setting: true\n"
                "# >>> RAG-IME managed block\nmanaged: true\n# <<< RAG-IME managed block\n"
            )
            outside.write_text(outside_text, encoding="utf-8")
            target = home / "Library" / "Rime" / "squirrel.custom.yaml"
            target.parent.mkdir(parents=True)
            target.symlink_to(outside)

            plan = build_macos_uninstall_plan(
                home,
                options=MacOSUninstallOptions(remove_rime_managed_config=True),
            )
            action = next(item for item in plan["actions"] if item["target"] == str(target))
            report = apply_macos_uninstall_plan(plan, platform_name="darwin")

            self.assertEqual(action["status"], "skipped_unverified")
            self.assertIn("rime_target_escapes_home", {item["id"] for item in plan["warnings"]})
            self.assertTrue(report["ok"])
            self.assertTrue(target.is_symlink())
            self.assertEqual(outside.read_text(encoding="utf-8"), outside_text)

    def test_symlinked_app_parent_outside_home_is_never_removed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-app-symlink-") as tmp:
            root = Path(tmp)
            home = root / "home"
            outside_apps = root / "outside-apps"
            home.mkdir()
            outside_apps.mkdir()
            (home / "Applications").symlink_to(outside_apps, target_is_directory=True)
            control = outside_apps / "RagImeControl.app"
            self._write_app(control, "com.rag-ime.control")

            plan = build_macos_uninstall_plan(home)
            action = next(item for item in plan["actions"] if item["target"].endswith("RagImeControl.app"))
            report = apply_macos_uninstall_plan(plan, platform_name="darwin")

            self.assertEqual(action["status"], "skipped_unverified")
            self.assertIn("app_path_escapes_home", {item["id"] for item in plan["warnings"]})
            self.assertTrue(report["ok"])
            self.assertTrue(control.is_dir())

    def test_cli_defaults_to_dry_run_and_mode_600_report(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-uninstall-cli-") as tmp:
            home = Path(tmp) / "home"
            self._seed_owned_install(home)
            report_path = Path(tmp) / "uninstall.json"
            result = subprocess.run(
                [
                    "python3",
                    "scripts/uninstall_rag_ime.py",
                    "--home",
                    str(home),
                    "--report",
                    str(report_path),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(payload["mode"], "dry-run")
            self.assertTrue((home / "Applications" / "RagImeControl.app").is_dir())
            self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)

    def test_voice_only_uninstaller_is_also_dry_run_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-voice-uninstall-cli-") as tmp:
            home = Path(tmp) / "home"
            app = home / "Applications" / "RagImeVoice.app"
            plist = home / "Library" / "LaunchAgents" / "com.rag-ime.voice.plist"
            hotwords = home / "Library" / "Application Support" / "RagIme" / "voice-hotwords.json"
            self._write_app(app, "com.rag-ime.voice")
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps({"Label": "com.rag-ime.voice"}))
            hotwords.parent.mkdir(parents=True)
            hotwords.write_text("private\n", encoding="utf-8")
            env = dict(os.environ)
            env["HOME"] = str(home)

            result = subprocess.run(
                ["bash", "scripts/uninstall_voice_input.sh", "--purge-credentials"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["mode"], "dry-run")
            self.assertEqual(payload["options"]["componentScope"], "voice")
            self.assertTrue(payload["options"]["purgeCredentials"])
            self.assertTrue(payload["options"]["purgeVoiceConfig"])
            self.assertTrue(app.is_dir())
            self.assertTrue(plist.is_file())
            self.assertTrue(hotwords.is_file())

    def test_sidecar_only_uninstaller_is_dry_run_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-sidecar-uninstall-cli-") as tmp:
            home = Path(tmp) / "home"
            plist = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps({"Label": "com.rag-ime.sidecar"}))
            env = dict(os.environ)
            env["HOME"] = str(home)

            result = subprocess.run(
                ["bash", "scripts/uninstall_sidecar_launch_agent.sh"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(payload["mode"], "dry-run")
            self.assertEqual(payload["options"]["componentScope"], "sidecar")
            self.assertEqual(payload["plannedActionCount"], 1)
            self.assertEqual(
                {Path(item["target"]).name for item in payload["actions"]},
                {"com.rag-ime.sidecar.plist", "com.rag-ime.agent-gateway.plist"},
            )
            self.assertTrue(plist.is_file())

    def _seed_owned_install(self, home: Path) -> None:
        launch_agents = home / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True, exist_ok=True)
        for label in (
            "com.rag-ime.frontend",
            "com.rag-ime.agent-gateway",
            "com.rag-ime.desktop-bridge",
            "com.rag-ime.memory-book-maintenance",
            "com.rag-ime.mineru",
            "com.rag-ime.mlx-predictor",
            "com.rag-ime.sidecar",
            "com.rag-ime.voice",
        ):
            (launch_agents / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label}))
        self._write_app(home / "Applications" / "RagImeControl.app", "com.rag-ime.control")
        self._write_app(
            home / "Applications" / "RagImeDesktopBridge.app",
            "com.rag-ime.desktop-bridge",
        )
        self._write_app(home / "Applications" / "RagImeVoice.app", "com.rag-ime.voice")
        squirrel = home / "Library" / "Input Methods" / "Squirrel.app"
        self._write_app(squirrel, "im.rime.inputmethod.Squirrel")
        marker = squirrel / "Contents" / "Resources" / "rag-ime-build-marker.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.squirrel-build-marker.v2",
                    "bundleId": "im.rime.inputmethod.Squirrel",
                }
            ),
            encoding="utf-8",
        )
        for name, begin, end in self._rime_blocks():
            target = home / "Library" / "Rime" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"user-owned-setting: true\n{begin}\nmanaged: true\n{end}\n", encoding="utf-8")
        app_support = home / "Library" / "Application Support" / "RagIme"
        app_support.mkdir(parents=True, exist_ok=True)
        (app_support / "rag-ime.sqlite").write_text("private-token\n", encoding="utf-8")
        (app_support / "voice-hotwords.json").write_text("private-hotword\n", encoding="utf-8")
        logs = home / "Library" / "Logs" / "RagIme"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "sidecar.log").write_text("log\n", encoding="utf-8")

    @staticmethod
    def _write_app(path: Path, bundle_id: str) -> None:
        info = path / "Contents" / "Info.plist"
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_bytes(plistlib.dumps({"CFBundleIdentifier": bundle_id}))

    @staticmethod
    def _rime_blocks() -> tuple[tuple[str, str, str], ...]:
        return (
            ("squirrel.custom.yaml", "# >>> RAG-IME managed block", "# <<< RAG-IME managed block"),
            (
                "default.custom.yaml",
                "# >>> RAG-IME default managed block",
                "# <<< RAG-IME default managed block",
            ),
            (
                "luna_pinyin_simp.custom.yaml",
                "# rag-ime-managed-sichuan-fuzzy-pinyin: begin",
                "# rag-ime-managed-sichuan-fuzzy-pinyin: end",
            ),
        )


if __name__ == "__main__":
    unittest.main()
