from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_extensions import AgentExtensionService
from rag_ime.agent_runtime_driver import AgentRuntimeError


class _FakePluginRuntime:
    def __init__(self) -> None:
        self.installed: list[dict[str, object]] = []
        self.calls: list[tuple[str, object]] = []

    def plugin_list(self):
        return list(self.installed)

    def plugin_validate(self, source_path: str):
        self.calls.append(("validate", source_path))
        manifest = json.loads((Path(source_path) / "rag-ime-plugin.json").read_text())
        digest = hashlib.sha256((Path(source_path) / "index.ts").read_bytes()).hexdigest()
        return {
            "manifest": manifest,
            "digest": digest,
            "files": ["index.ts", "rag-ime-plugin.json"],
            "totalBytes": 100,
            "installPreview": {"operation": "install", "enabledAfterInstall": False},
        }

    def plugin_prepare_package(self, source: str):
        self.calls.append(("prepare_package", source))
        return {
            "preparedPackageId": "prepared-pi-package",
            "manifest": {
                "schemaVersion": 1,
                "id": "context-helper",
                "name": "Context Helper",
                "version": "2.1.0",
                "description": "Adds a bounded context Skill",
                "entry": "generated-entry.ts",
                "permissions": [],
            },
            "digest": "a" * 64,
            "files": ["skills/context-helper/SKILL.md"],
            "totalBytes": 96,
            "resources": {
                "extensions": [],
                "skills": ["skills/context-helper/SKILL.md"],
                "prompts": [],
                "themes": [],
            },
            "source": {
                "kind": "npm",
                "requested": source,
                "resolved": "npm:@example/context-helper@2.1.0",
            },
            "installPreview": {
                "operation": "install",
                "enabledAfterInstall": False,
            },
        }

    def plugin_create_package(self, payload):
        self.calls.append(("create_package", dict(payload)))
        return {
            "draftId": str(payload["draftId"]),
            "sourcePath": str(self.calls and Path("/managed/pi-package-draft")),
            "package": {
                "name": str(payload["packageJson"]["name"]),
                "version": str(payload["packageJson"]["version"]),
            },
        }

    def plugin_install(self, payload):
        self.calls.append(("install", dict(payload)))
        plugin = {
            "id": "log-helper",
            "name": "Log Helper",
            "version": "1.0.0",
            "description": "Inspect session logs",
            "digest": payload["expectedDigest"],
            "enabled": payload["enable"],
            "permissions": ["session.read"],
            "installedVersions": [
                {"version": "1.0.0", "digest": payload["expectedDigest"]}
            ],
        }
        self.installed = [plugin]
        return plugin

    def plugin_enable(
        self,
        plugin_id: str,
        *,
        enabled: bool,
        expected_active_digest: str,
        expected_enabled: bool,
    ):
        self.calls.append(
            (
                "enable",
                {
                    "pluginId": plugin_id,
                    "enabled": enabled,
                    "expectedActiveDigest": expected_active_digest,
                    "expectedEnabled": expected_enabled,
                },
            )
        )
        if (
            self.installed[0]["digest"] != expected_active_digest
            or self.installed[0]["enabled"] is not expected_enabled
        ):
            raise ValueError("plugin state changed")
        self.installed[0]["enabled"] = enabled
        return self.installed[0]

    def plugin_rollback(
        self,
        plugin_id: str,
        *,
        expected_active_digest: str,
        target_digest: str,
    ):
        self.calls.append(
            (
                "rollback",
                {
                    "pluginId": plugin_id,
                    "expectedActiveDigest": expected_active_digest,
                    "targetDigest": target_digest,
                },
            )
        )
        if self.installed[0]["digest"] != expected_active_digest:
            raise ValueError("active digest changed")
        target = next(
            value
            for value in self.installed[0]["installedVersions"]
            if value["digest"] == target_digest
        )
        self.installed[0]["digest"] = target_digest
        self.installed[0]["version"] = target["version"]
        return self.installed[0]


class AgentExtensionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-plugin-service-")
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "rag-ime-plugin.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "log-helper",
                    "name": "Log Helper",
                    "version": "1.0.0",
                    "description": "Inspect session logs",
                    "entry": "index.ts",
                    "permissions": ["session.read"],
                }
            )
        )
        (self.source / "index.ts").write_text("export default function () {}\n")
        self.runtime = _FakePluginRuntime()
        self.service = AgentExtensionService(
            runtime_provider=lambda: self.runtime,
            inbox_root=self.root / "managed-inbox",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_projects_runtime_unavailable_without_dropping_the_http_response(self) -> None:
        def unavailable_runtime():
            raise AgentRuntimeError("Pi runtime is disabled")

        service = AgentExtensionService(
            runtime_provider=unavailable_runtime,
            inbox_root=self.root / "unavailable-inbox",
        )

        self.assertEqual(
            service.list(),
            {
                "schemaVersion": "rag-ime.plugin-inventory.v1",
                "ok": True,
                "runtimeAvailable": False,
                "items": [],
            },
        )
        catalog = service.catalog()
        self.assertTrue(catalog["ok"])
        self.assertFalse(catalog["runtimeAvailable"])

    def test_install_requires_validation_preview_digest_and_explicit_apply(self) -> None:
        validation = self.service.validate(
            {"catalogId": "session-review", "catalogVersion": "1.1.0"}
        )
        staged = Path(str(self.runtime.calls[0][1]))
        self.assertTrue(staged.is_relative_to((self.root / "managed-inbox").resolve()))
        self.assertNotEqual(staged, self.source)

        preview = self.service.preview(
            {
                "action": "install",
                "validationToken": validation["validationToken"],
                "enable": True,
            }
        )
        with self.assertRaisesRegex(ValueError, "confirmText=apply"):
            self.service.apply(
                {
                    "previewToken": preview["previewToken"],
                    "payloadSha256": preview["payloadSha256"],
                    "confirmText": "yes",
                }
            )
        receipt = self.service.apply(
            {
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(receipt["receipt"]["action"], "install")
        self.assertTrue(self.runtime.installed[0]["enabled"])
        with self.assertRaisesRegex(ValueError, "invalid or expired"):
            self.service.apply(
                {
                    "previewToken": preview["previewToken"],
                    "payloadSha256": preview["payloadSha256"],
                    "confirmText": "apply",
                }
            )

    def test_enable_disable_and_rollback_also_use_preview(self) -> None:
        self.runtime.installed = [
            {
                "id": "log-helper",
                "name": "Log Helper",
                "version": "2.0.0",
                "description": "Inspect session logs",
                "digest": "digest-v2",
                "enabled": True,
                "permissions": ["session.read"],
                "installedVersions": [
                    {"version": "1.0.0", "digest": "digest-v1"},
                    {"version": "2.0.0", "digest": "digest-v2"},
                ],
                "rollbackTarget": {"version": "1.0.0", "digest": "digest-v1"},
            }
        ]

        disable = self.service.preview({"action": "disable", "pluginId": "log-helper"})
        self.assertEqual(disable["summary"]["version"], "2.0.0")
        self.assertEqual(disable["summary"]["permissions"], ["session.read"])
        self.service.apply(
            {
                "previewToken": disable["previewToken"],
                "payloadSha256": disable["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertFalse(self.runtime.installed[0]["enabled"])
        self.assertEqual(
            self.runtime.calls[-1],
            (
                "enable",
                {
                    "pluginId": "log-helper",
                    "enabled": False,
                    "expectedActiveDigest": "digest-v2",
                    "expectedEnabled": True,
                },
            ),
        )
        self.assertEqual(self.service.list()["items"][0]["displayName"], "Log Helper")

        rollback = self.service.preview({"action": "rollback", "pluginId": "log-helper"})
        self.assertEqual(rollback["summary"]["targetVersion"], "1.0.0")
        self.service.apply(
            {
                "previewToken": rollback["previewToken"],
                "payloadSha256": rollback["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(self.runtime.installed[0]["version"], "1.0.0")
        self.assertEqual(
            self.runtime.calls[-1],
            (
                "rollback",
                {
                    "pluginId": "log-helper",
                    "expectedActiveDigest": "digest-v2",
                    "targetDigest": "digest-v1",
                },
            ),
        )

    def test_enable_disable_preview_rejects_state_changed_after_review(self) -> None:
        self.runtime.installed = [
            {
                "id": "log-helper",
                "name": "Log Helper",
                "version": "2.0.0",
                "digest": "digest-v2",
                "enabled": True,
                "permissions": ["session.read"],
                "installedVersions": [
                    {"version": "2.0.0", "digest": "digest-v2"},
                ],
            }
        ]
        disable = self.service.preview({"action": "disable", "pluginId": "log-helper"})
        self.runtime.installed[0]["enabled"] = False
        with self.assertRaisesRegex(ValueError, "plugin state changed"):
            self.service.apply(
                {
                    "previewToken": disable["previewToken"],
                    "payloadSha256": disable["payloadSha256"],
                    "confirmText": "apply",
                }
            )

    def test_rollback_preview_rejects_state_changed_after_review(self) -> None:
        self.runtime.installed = [
            {
                "id": "log-helper",
                "name": "Log Helper",
                "version": "2.0.0",
                "digest": "digest-v2",
                "enabled": True,
                "installedVersions": [
                    {"version": "1.0.0", "digest": "digest-v1"},
                    {"version": "2.0.0", "digest": "digest-v2"},
                ],
                "rollbackTarget": {"version": "1.0.0", "digest": "digest-v1"},
            }
        ]
        rollback = self.service.preview({"action": "rollback", "pluginId": "log-helper"})
        self.runtime.installed[0]["digest"] = "digest-v3"
        with self.assertRaisesRegex(ValueError, "active digest changed"):
            self.service.apply(
                {
                    "previewToken": rollback["previewToken"],
                    "payloadSha256": rollback["payloadSha256"],
                    "confirmText": "apply",
                }
            )

    def test_local_plugin_source_is_review_only_and_cannot_execute(self) -> None:
        validation = self.service.validate({"sourcePath": str(self.source)})
        with self.assertRaisesRegex(ValueError, "review-only"):
            self.service.preview(
                {
                    "action": "install",
                    "validationToken": validation["validationToken"],
                    "enable": True,
                }
            )

    def test_pi_package_source_uses_pi_resolver_and_the_same_explicit_apply_gate(self) -> None:
        validation = self.service.validate(
            {"packageSource": "npm:@example/context-helper@2.1.0"}
        )

        self.assertEqual(validation["distribution"], "pi_package")
        self.assertEqual(validation["extension"]["version"], "2.1.0")
        self.assertEqual(
            validation["extension"]["resources"]["skills"],
            ["skills/context-helper/SKILL.md"],
        )
        self.assertEqual(
            self.runtime.calls[-1],
            ("prepare_package", "npm:@example/context-helper@2.1.0"),
        )

        preview = self.service.preview(
            {
                "action": "install",
                "validationToken": validation["validationToken"],
                "enable": True,
            }
        )
        with self.assertRaisesRegex(ValueError, "confirmText=apply"):
            self.service.apply(
                {
                    "previewToken": preview["previewToken"],
                    "payloadSha256": preview["payloadSha256"],
                    "confirmText": "yes",
                }
            )

        self.service.apply(
            {
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(
            self.runtime.calls[-1],
            (
                "install",
                {
                    "preparedPackageId": "prepared-pi-package",
                    "expectedDigest": "a" * 64,
                    "enable": True,
                },
            ),
        )

    def test_agent_can_create_an_immutable_pi_package_draft_before_validation(self) -> None:
        result = self.service.create_package_draft(
            {
                "draftId": "context-helper-v1",
                "packageJson": {
                    "name": "@example/context-helper",
                    "version": "1.0.0",
                    "description": "Adds a bounded context Skill",
                    "pi": {"skills": ["skills/context-helper"]},
                },
                "files": {
                    "skills/context-helper/SKILL.md": (
                        "---\nname: context-helper\n"
                        "description: Load bounded context.\n---\n"
                    )
                },
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["draft"]["draftId"], "context-helper-v1")
        self.assertEqual(
            self.runtime.calls[-1][0],
            "create_package",
        )

    def test_rejects_symlinks_and_unsupported_files_before_runtime_validation(self) -> None:
        (self.source / "payload.bin").write_bytes(b"unsafe")
        with self.assertRaisesRegex(ValueError, "unsupported plugin source file"):
            self.service.validate({"sourcePath": str(self.source)})

    def test_bundled_catalog_exposes_version_history_and_uses_the_same_apply_gate(self) -> None:
        catalog = self.service.catalog()
        item = next(value for value in catalog["items"] if value["id"] == "session-review")
        self.assertEqual(item["latestVersion"], "1.1.0")
        self.assertEqual([value["version"] for value in item["versions"]], ["1.1.0", "1.0.0"])
        self.assertTrue(item["actionable"])

        validation = self.service.validate(
            {"catalogId": "session-review", "catalogVersion": "1.1.0"}
        )
        self.assertEqual(validation["catalog"]["catalogVersion"], "1.1.0")
        preview = self.service.preview(
            {
                "action": "install",
                "validationToken": validation["validationToken"],
                "enable": True,
            }
        )
        with self.assertRaisesRegex(ValueError, "confirmText=apply"):
            self.service.apply(
                {
                    "previewToken": preview["previewToken"],
                    "payloadSha256": preview["payloadSha256"],
                    "confirmText": "install",
                }
            )

    def test_review_only_catalog_item_cannot_be_validated_for_install(self) -> None:
        with self.assertRaisesRegex(ValueError, "review only"):
            self.service.validate({"catalogId": "community-catalog-preview"})

    def test_catalog_update_is_detected_and_reuses_digest_bound_install_apply(self) -> None:
        self.runtime.installed = [
            {
                "id": "session-review",
                "name": "Session Review",
                "version": "1.0.0",
                "enabled": True,
                "installedVersions": [{"version": "1.0.0", "digest": "old"}],
            }
        ]
        item = next(
            value
            for value in self.service.catalog()["items"]
            if value["id"] == "session-review"
        )
        self.assertTrue(item["updateAvailable"])

        validation = self.service.validate(
            {"catalogId": "session-review", "catalogVersion": "1.1.0"}
        )
        preview = self.service.preview(
            {
                "action": "update",
                "validationToken": validation["validationToken"],
                "enable": True,
            }
        )
        receipt = self.service.apply(
            {
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(receipt["receipt"]["action"], "update")
        self.assertEqual(self.runtime.calls[-1][0], "install")


if __name__ == "__main__":
    unittest.main()
