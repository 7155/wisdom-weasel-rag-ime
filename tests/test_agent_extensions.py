from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_extensions import (
    AgentExtensionService,
    extension_app_binding_capability,
    extension_app_binding_sha256,
)
from rag_ime.agent_runtime_driver import AgentRuntimeError


def _native_package_digest(package: Path) -> str:
    files: list[Path] = []

    def visit(directory: Path) -> None:
        for item in sorted(directory.iterdir(), key=lambda path: path.name.casefold()):
            if item.is_dir():
                visit(item)
            else:
                files.append(item)

    visit(package)
    digest = hashlib.sha256()
    for item in files:
        digest.update(item.relative_to(package).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_bound_extension_package(root: Path) -> tuple[Path, str, str, str]:
    package = root / "zhanggui-package-source"
    if package.exists():
        shutil.rmtree(package)
    skill = package / "skills" / "zhanggui-wenshu" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: zhanggui-wenshu\ndescription: test\n---\n",
        encoding="utf-8",
    )
    skill_sha256 = hashlib.sha256(skill.read_bytes()).hexdigest()
    app_manifest: dict[str, object] = {
        "schemaVersion": "pawos.extension-app.v1",
        "id": "extension:zhanggui-wenshu",
        "version": "0.1.0",
        "bindingSha256": "0" * 64,
        "packageId": "@paw/zhanggui-wenshu",
        "label": "掌柜问数",
        "shortLabel": "问数",
        "tagline": "test",
        "route": "/extensions/zhanggui-wenshu",
        "presentation": "conversation",
        "accent": "green",
        "icon": {"symbol": "analytics", "background": "#087F68"},
        "skillRef": "zhanggui-wenshu",
        "skillSha256": skill_sha256,
        "verticalSuiteId": "sgg",
        "verticalSuiteRevision": "fixture-v2",
    }
    binding_sha256 = extension_app_binding_sha256(
        app_manifest,
        skill_sha256=skill_sha256,
        package_version="0.1.0",
    )
    app_manifest["bindingSha256"] = binding_sha256
    binding_capability = extension_app_binding_capability(binding_sha256)
    package_manifest = {
        "name": "@paw/zhanggui-wenshu",
        "version": "0.1.0",
        "pi": {"extensions": ["./index.ts"], "skills": ["./skills"]},
        "paw": {
            "capabilities": [binding_capability],
            "extensionApp": {
                "id": app_manifest["id"],
                "packageId": app_manifest["packageId"],
                "version": app_manifest["version"],
                "bindingSha256": binding_sha256,
                "skillRef": app_manifest["skillRef"],
                "skillSha256": skill_sha256,
                "verticalSuiteId": app_manifest["verticalSuiteId"],
                "verticalSuiteRevision": app_manifest["verticalSuiteRevision"],
                "manifest": app_manifest,
            },
        },
    }
    (package / "package.json").write_text(
        json.dumps(package_manifest, ensure_ascii=False), encoding="utf-8"
    )
    (package / "index.ts").write_text("export {};\n", encoding="utf-8")
    package_digest = _native_package_digest(package)
    package_key = hashlib.sha256(b"@paw/zhanggui-wenshu").hexdigest()[:16]
    managed = root / "packages" / package_key / package_digest
    managed.parent.mkdir(parents=True, exist_ok=True)
    if managed.exists():
        shutil.rmtree(managed)
    shutil.copytree(package, managed)
    return managed, package_digest, binding_sha256, binding_capability


class _FakePluginRuntime:
    def __init__(self) -> None:
        self.installed: list[dict[str, object]] = []
        self.calls: list[tuple[str, object]] = []

    def plugin_list(self):
        return list(self.installed)

    def plugin_catalog(self):
        return [
            {
                "id": "@paw/session-workflow",
                "name": "@paw/session-workflow",
                "displayName": "Session Workflow",
                "version": "1.0.0",
                "description": "Optional Goal, Plan, Todo, and Workflow state",
                "capabilities": ["session-workflow"],
                "source": str(self.package_source),
                "distribution": "pi_package",
                "bundled": True,
                "installed": any(
                    value.get("id") == "@paw/session-workflow"
                    for value in self.installed
                ),
                "enabled": any(
                    value.get("id") == "@paw/session-workflow"
                    and value.get("enabled") is True
                    for value in self.installed
                ),
            }
        ]

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

    def plugin_preview_install(self, payload):
        self.calls.append(("preview_install", dict(payload)))
        return {
            "previewToken": "host-preview-token",
            "payloadSha256": "b" * 64,
            "requiredConfirm": "apply",
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

    def plugin_uninstall(
        self,
        plugin_id: str,
        *,
        expected_active_digest: str,
        expected_enabled: bool,
    ):
        self.calls.append(
            (
                "uninstall",
                {
                    "pluginId": plugin_id,
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
        removed = {
            "id": plugin_id,
            "digest": expected_active_digest,
            "removed": True,
        }
        self.installed = []
        return removed


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
        self.runtime.package_source = self.root / "session-workflow"
        self.runtime.package_source.mkdir()
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

    def test_list_and_receipt_preserve_extension_app_binding_evidence(self) -> None:
        package, package_digest, binding_sha256, binding_capability = (
            _write_bound_extension_package(self.root)
        )
        self.runtime.installed = [
            {
                "id": "@paw/zhanggui-wenshu",
                "name": "掌柜问数",
                "version": "0.1.0",
                "digest": package_digest,
                "enabled": True,
                "capabilities": [binding_capability],
                "source": str(package),
                "installedVersions": [{
                    "version": "0.1.0",
                    "digest": package_digest,
                    "source": str(package),
                }],
            }
        ]

        item = self.service.list()["items"][0]
        self.assertNotIn(str(package), json.dumps(item, ensure_ascii=False))
        self.assertEqual(item["capabilities"], [binding_capability])
        self.assertEqual(item["extensionApp"]["bindingSha256"], binding_sha256)
        self.assertEqual(item["extensionApp"]["version"], "0.1.0")
        self.assertEqual(item["extensionApp"]["skillRef"], "zhanggui-wenshu")
        self.assertEqual(item["extensionApp"]["verticalSuiteId"], "sgg")
        self.assertEqual(
            self.service.extension_app_skill_owners(),
            {"zhanggui-wenshu": "extension:zhanggui-wenshu"},
        )

        preview = self.service.preview(
            {"action": "disable", "pluginId": "@paw/zhanggui-wenshu"}
        )
        receipt = self.service.apply(
            {
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(
            receipt["receipt"]["extensionApp"]["bindingCapability"],
            binding_capability,
        )
        self.assertNotIn(
            str(package), json.dumps(receipt["receipt"], ensure_ascii=False)
        )

    def test_list_rechecks_installed_bytes_after_successful_verification(self) -> None:
        package, package_digest, _binding_sha256, binding_capability = (
            _write_bound_extension_package(self.root)
        )
        self.runtime.installed = [{
            "id": "@paw/zhanggui-wenshu",
            "name": "掌柜问数",
            "version": "0.1.0",
            "digest": package_digest,
            "enabled": True,
            "capabilities": [binding_capability],
            "source": str(package),
            "installedVersions": [],
        }]
        self.assertIn("extensionApp", self.service.list()["items"][0])

        (package / "skills" / "zhanggui-wenshu" / "SKILL.md").write_text(
            "---\nname: zhanggui-wenshu\ndescription: changed after verification\n---\n",
            encoding="utf-8",
        )
        self.assertNotIn("extensionApp", self.service.list()["items"][0])

    def test_list_rejects_partial_extension_evidence(self) -> None:
        package, package_digest, binding_sha256, binding_capability = (
            _write_bound_extension_package(self.root)
        )
        self.runtime.installed = [{
            "id": "@paw/zhanggui-wenshu",
            "name": "掌柜问数",
            "version": "0.1.0",
            "digest": package_digest,
            "enabled": True,
            "capabilities": [binding_capability],
            "extensionApp": {
                "version": "0.1.0",
                "bindingSha256": binding_sha256,
                "bindingCapability": binding_capability,
            },
            "installedVersions": [],
        }]
        self.assertNotIn("extensionApp", self.service.list()["items"][0])

    def test_list_rejects_missing_digest_relative_and_unmanaged_sources(self) -> None:
        package, package_digest, _binding_sha256, binding_capability = (
            _write_bound_extension_package(self.root)
        )
        base = {
            "id": "@paw/zhanggui-wenshu",
            "name": "掌柜问数",
            "version": "0.1.0",
            "enabled": True,
            "capabilities": [binding_capability],
            "source": str(package),
            "digest": package_digest,
            "installedVersions": [],
        }
        for override in (
            {"digest": ""},
            {"source": "relative/package"},
            {"source": str(self.root / "unmanaged" / package_digest)},
            {"capabilities": [binding_capability, "runtime.extra"]},
        ):
            self.runtime.installed = [{**base, **override}]
            self.assertNotIn("extensionApp", self.service.list()["items"][0])

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

    def test_catalog_projects_native_pi_packages_and_prepares_them_in_pi(self) -> None:
        catalog = self.service.catalog()
        workflow = next(
            item
            for item in catalog["items"]
            if item["id"] == "@paw/session-workflow"
        )
        self.assertEqual(workflow["distribution"], "pi_package")
        self.assertEqual(workflow["capabilities"], ["session-workflow"])
        self.assertEqual(workflow["installState"], "available")

        validation = self.service.validate(
            {"catalogId": "@paw/session-workflow", "catalogVersion": "1.0.0"}
        )

        self.assertEqual(validation["distribution"], "pi_package")
        self.assertEqual(
            self.runtime.calls[-1],
            ("prepare_package", str(self.runtime.package_source)),
        )

    def test_catalog_rebuilds_uninstalled_extension_candidate_evidence(self) -> None:
        managed, package_digest, binding_sha256, binding_capability = (
            _write_bound_extension_package(self.root)
        )
        bundled = self.root / "bundled" / "zhanggui-wenshu"
        bundled.parent.mkdir(parents=True)
        shutil.copytree(managed, bundled)
        self.runtime.plugin_catalog = lambda: [{
            "id": "@paw/zhanggui-wenshu",
            "name": "@paw/zhanggui-wenshu",
            "displayName": "掌柜问数",
            "version": "0.1.0",
            "capabilities": [binding_capability],
            "source": str(bundled),
            "distribution": "pi_package",
            "bundled": True,
            "installed": False,
            "enabled": False,
        }]

        item = self.service.catalog()["items"][0]
        self.assertEqual(item["extensionApp"]["bindingSha256"], binding_sha256)
        self.assertEqual(item["extensionApp"]["packageDigest"], package_digest)

        (bundled / "skills" / "zhanggui-wenshu" / "SKILL.md").write_text(
            "---\nname: zhanggui-wenshu\ndescription: changed catalog bytes\n---\n",
            encoding="utf-8",
        )
        self.assertNotIn("extensionApp", self.service.catalog()["items"][0])

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
                    "previewToken": "host-preview-token",
                    "payloadSha256": "b" * 64,
                    "confirmText": "apply",
                },
            ),
        )

    def test_uninstall_uses_reviewed_digest_and_removes_runtime_capability(self) -> None:
        self.runtime.installed = [
            {
                "id": "log-helper",
                "name": "Log Helper",
                "version": "1.0.0",
                "digest": "digest-v1",
                "enabled": False,
                "installedVersions": [
                    {"version": "1.0.0", "digest": "digest-v1"},
                ],
            }
        ]

        preview = self.service.preview(
            {"action": "uninstall", "pluginId": "log-helper"}
        )
        receipt = self.service.apply(
            {
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )

        self.assertEqual(receipt["receipt"]["action"], "uninstall")
        self.assertTrue(receipt["receipt"]["plugin"]["removed"])
        self.assertEqual(self.runtime.installed, [])
        self.assertEqual(
            self.runtime.calls[-1],
            (
                "uninstall",
                {
                    "pluginId": "log-helper",
                    "expectedActiveDigest": "digest-v1",
                    "expectedEnabled": False,
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

    def test_vertical_agent_sandbox_is_an_actionable_bundled_plugin(self) -> None:
        catalog = self.service.catalog()
        item = next(
            value for value in catalog["items"]
            if value["id"] == "vertical-agent-sandbox"
        )

        self.assertEqual(item["latestVersion"], "0.1.1")
        self.assertEqual(
            [value["version"] for value in item["versions"]],
            ["0.1.1", "0.1.0"],
        )
        self.assertEqual(item["permissions"], ["sandbox.run"])
        self.assertTrue(item["actionable"])
        validation = self.service.validate(
            {"catalogId": "vertical-agent-sandbox", "catalogVersion": "0.1.1"}
        )
        self.assertEqual(validation["extension"]["id"], "vertical-agent-sandbox")
        self.assertEqual(validation["catalog"]["catalogVersion"], "0.1.1")

    def test_vertical_agent_sandbox_host_connector_fix_is_a_real_update(self) -> None:
        self.runtime.installed = [
            {
                "id": "vertical-agent-sandbox",
                "name": "Vertical Agent Sandbox",
                "version": "0.1.0",
                "enabled": True,
                "installedVersions": [{"version": "0.1.0", "digest": "old"}],
            }
        ]

        item = next(
            value
            for value in self.service.catalog()["items"]
            if value["id"] == "vertical-agent-sandbox"
        )

        self.assertTrue(item["updateAvailable"])
        self.assertEqual(item["installState"], "update_available")

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


    def test_skill_inventory_is_ordered_and_detail_reads_only_server_owned_id(self) -> None:
        bundled_root = self.root / "bundled"
        project_root = self.root / "project"
        package_source = self.root / "package-source"

        def write_skill(root: Path, name: str, description: str, body: str) -> None:
            path = root / name / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
                encoding="utf-8",
            )

        write_skill(bundled_root, "alpha", "Bundled alpha", "Bundled instructions.")
        write_skill(project_root, "beta", "Project beta", "Project instructions.")
        write_skill(package_source / "skills", "package-skill", "Package skill", "Package instructions.")
        package_manifest = {"name": "@example/skills", "version": "1.2.0"}
        (package_source / "package.json").write_text(
            json.dumps(package_manifest),
            encoding="utf-8",
        )
        package_digest = _native_package_digest(package_source)
        package_key = hashlib.sha256(b"@example/skills").hexdigest()[:16]
        managed_package = self.root / "packages" / package_key / package_digest
        managed_package.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_source, managed_package)
        self.runtime.installed = [{
            "id": "@example/skills",
            "version": "1.2.0",
            "digest": package_digest,
            "enabled": True,
            "source": str(managed_package),
            "resources": {"skills": ["skills/package-skill/SKILL.md"]},
        }]
        service = AgentExtensionService(
            runtime_provider=lambda: self.runtime,
            inbox_root=self.root / "skill-inbox",
            bundled_skills_root=bundled_root,
            project_skills_roots=(project_root,),
        )

        inventory = service.skills_list()
        self.assertEqual(
            [item["skillId"] for item in inventory["items"]],
            ["alpha", "beta", "package-skill"],
        )
        self.assertEqual(
            {item["sourceKind"] for item in inventory["items"]},
            {"bundled", "project", "package"},
        )
        self.assertTrue(all(str(self.root) not in json.dumps(item) for item in inventory["items"]))

        detail = service.skill_detail({"skillId": "package-skill", "path": str(self.root / "secret")})
        self.assertEqual(detail["item"]["body"], "Package instructions.")
        self.assertEqual(detail["item"]["contentRevision"], inventory["items"][2]["contentRevision"])
        with self.assertRaisesRegex(ValueError, "skillId is invalid"):
            service.skill_detail({"skillId": "../package-skill"})

if __name__ == "__main__":
    unittest.main()
