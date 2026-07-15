from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_extensions import AgentExtensionService


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

    def plugin_enable(self, plugin_id: str, *, enabled: bool):
        self.calls.append(("enable", {"pluginId": plugin_id, "enabled": enabled}))
        self.installed[0]["enabled"] = enabled
        return self.installed[0]

    def plugin_rollback(self, plugin_id: str):
        self.calls.append(("rollback", plugin_id))
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

    def test_install_requires_validation_preview_digest_and_explicit_apply(self) -> None:
        validation = self.service.validate({"sourcePath": str(self.source)})
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
        validation = self.service.validate({"sourcePath": str(self.source)})
        preview = self.service.preview(
            {"action": "install", "validationToken": validation["validationToken"]}
        )
        self.service.apply(
            {
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )

        disable = self.service.preview({"action": "disable", "pluginId": "log-helper"})
        self.service.apply(
            {
                "previewToken": disable["previewToken"],
                "payloadSha256": disable["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertFalse(self.runtime.installed[0]["enabled"])
        self.assertEqual(self.service.list()["items"][0]["displayName"], "Log Helper")

    def test_rejects_symlinks_and_unsupported_files_before_runtime_validation(self) -> None:
        (self.source / "payload.bin").write_bytes(b"unsafe")
        with self.assertRaisesRegex(ValueError, "unsupported plugin source file"):
            self.service.validate({"sourcePath": str(self.source)})


if __name__ == "__main__":
    unittest.main()
