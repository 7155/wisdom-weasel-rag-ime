from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_tool_ids import ASSISTANT_CONTROL_TOOL_IDS, CONTROL_TOOL_IDS
from rag_ime.managed_pi_runtime import (
    MANIFEST_NAME,
    POINTER_NAME,
    POINTER_SCHEMA_VERSION,
    ManagedPiRuntimeError,
    build_managed_pi_runtime_manifest,
    discover_managed_pi_runtime,
    install_managed_pi_runtime,
    write_managed_pi_runtime_manifest,
)
from rag_ime.pi_runtime import PiRuntimeConfig, PiRuntimeManager


class ManagedPiRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-managed-pi-")
        self.root = Path(self.tmp.name)
        self.app_support = self.root / "Application Support" / "RagIme"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_install_and_discover_use_only_verified_managed_paths(self) -> None:
        payload, _ = self._payload("runtime-1")

        installed = install_managed_pi_runtime(payload, self.app_support)
        discovered = discover_managed_pi_runtime(self.app_support, expected_pi_version="0.80.7")

        self.assertEqual(installed.runtime_version, "runtime-1")
        self.assertEqual(discovered.runtime_dir, (self.app_support / "PiRuntime" / "runtime-1").resolve())
        self.assertEqual(discovered.executable.name, "cli.js")
        self.assertEqual(Path(discovered.node_executable).name, "node")
        self.assertEqual(discovered.extension_path.name, "rag-ime-control.ts")
        self.assertEqual(discovered.tools, CONTROL_TOOL_IDS)
        self.assertTrue((self.app_support / "PiRuntime" / POINTER_NAME).is_file())

    def test_discovery_rejects_pointer_and_runtime_file_tampering(self) -> None:
        payload, _ = self._payload("runtime-1")
        installed = install_managed_pi_runtime(payload, self.app_support)
        installed.executable.write_text("tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(ManagedPiRuntimeError, "size mismatch|digest mismatch"):
            discover_managed_pi_runtime(self.app_support)

        payload_two, _ = self._payload("runtime-2")
        install_managed_pi_runtime(payload_two, self.app_support)
        pointer_path = self.app_support / "PiRuntime" / POINTER_NAME
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["manifestSha256"] = "0" * 64
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        with self.assertRaisesRegex(ManagedPiRuntimeError, "digest does not match"):
            discover_managed_pi_runtime(self.app_support)

    def test_manifest_path_traversal_and_symlinks_fail_closed(self) -> None:
        payload, manifest = self._payload("runtime-unsafe")
        manifest["piEntrypoint"] = "../outside.js"
        write_managed_pi_runtime_manifest(payload / MANIFEST_NAME, manifest)
        with self.assertRaisesRegex(ManagedPiRuntimeError, "unsafe managed Pi runtime path"):
            install_managed_pi_runtime(payload, self.app_support)

        symlink_payload = self.root / "payload-symlink"
        (symlink_payload / "bin").mkdir(parents=True)
        outside = self.root / "outside-node"
        outside.write_text("node\n", encoding="utf-8")
        (symlink_payload / "bin" / "node").symlink_to(outside)
        with self.assertRaisesRegex(ManagedPiRuntimeError, "symlink"):
            build_managed_pi_runtime_manifest(
                symlink_payload,
                runtime_version="runtime-symlink",
                pi_version="0.80.7",
                launch_kind="node",
                pi_entrypoint="bin/node",
                node_entrypoint="bin/node",
                extension_entrypoint="bin/node",
                source_repository="local/pi",
                source_commit="test",
                source_package="@earendil-works/pi-coding-agent",
            )

    def test_atomic_activation_retains_previous_version_for_rollback(self) -> None:
        first, _ = self._payload("runtime-1")
        second, _ = self._payload("runtime-2")

        install_managed_pi_runtime(first, self.app_support)
        install_managed_pi_runtime(second, self.app_support)

        runtime_root = self.app_support / "PiRuntime"
        self.assertTrue((runtime_root / "runtime-1" / MANIFEST_NAME).is_file())
        self.assertTrue((runtime_root / "runtime-2" / MANIFEST_NAME).is_file())
        pointer = json.loads((runtime_root / POINTER_NAME).read_text(encoding="utf-8"))
        self.assertEqual(pointer["schemaVersion"], POINTER_SCHEMA_VERSION)
        self.assertEqual(pointer["version"], "runtime-2")
        self.assertEqual(discover_managed_pi_runtime(self.app_support).runtime_version, "runtime-2")

    def test_protocol_v2_manifest_is_discovered_by_the_product_runtime(self) -> None:
        payload, _ = self._payload("runtime-v2", protocol_version="2")
        install_managed_pi_runtime(payload, self.app_support)

        discovered = discover_managed_pi_runtime(self.app_support, expected_pi_version="0.80.7")
        with patch.dict(
            os.environ,
            {
                "RAG_IME_APP_SUPPORT_DIR": str(self.app_support),
                "RAG_IME_PI_ENABLED": "true",
            },
            clear=True,
        ):
            config = PiRuntimeConfig.from_environment()

        self.assertEqual(discovered.protocol_version, "2")
        self.assertEqual(config.protocol_version, "2")

    def test_pi_runtime_config_discovers_managed_install_without_path_fallback(self) -> None:
        payload, _ = self._payload("runtime-1")
        installed = install_managed_pi_runtime(payload, self.app_support)
        with patch.dict(
            os.environ,
            {
                "RAG_IME_APP_SUPPORT_DIR": str(self.app_support),
                "RAG_IME_PI_ENABLED": "true",
            },
            clear=True,
        ):
            config = PiRuntimeConfig.from_environment()

        self.assertEqual(config.executable, installed.executable)
        self.assertEqual(config.node_executable, installed.node_executable)
        self.assertEqual(config.extension_path, installed.extension_path)
        self.assertEqual(config.installation_error, "")
        command = config.launch_command(session={"title": "managed"})
        self.assertEqual(command[:2], [installed.node_executable, str(installed.executable)])
        self.assertEqual(
            command[command.index("--tools") + 1],
            ",".join(ASSISTANT_CONTROL_TOOL_IDS),
        )

    def test_explicit_development_executable_overrides_managed_install(self) -> None:
        payload, _ = self._payload("runtime-1")
        install_managed_pi_runtime(payload, self.app_support)
        developer_pi = self.root / "developer-pi.js"
        developer_extension = self.root / "developer-extension.ts"
        developer_pi.write_text("console.log('dev')\n", encoding="utf-8")
        developer_extension.write_text("export default function () {}\n", encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "RAG_IME_APP_SUPPORT_DIR": str(self.app_support),
                "RAG_IME_PI_EXECUTABLE": str(developer_pi),
                "RAG_IME_PI_NODE": "/dev/node-for-test",
                "RAG_IME_PI_EXTENSION": str(developer_extension),
            },
            clear=True,
        ):
            config = PiRuntimeConfig.from_environment()

        self.assertEqual(config.executable, developer_pi)
        self.assertEqual(config.extension_path, developer_extension)
        self.assertEqual(config.node_executable, "/dev/node-for-test")

    def test_missing_or_invalid_installation_is_visible_but_does_not_use_global_pi(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PATH": "/a/path/that/might/contain/global/pi",
                "RAG_IME_APP_SUPPORT_DIR": str(self.app_support),
                "RAG_IME_PI_ENABLED": "true",
            },
            clear=True,
        ):
            config = PiRuntimeConfig.from_environment()
        self.assertIsNone(config.executable)
        self.assertIn("pointer is missing", config.installation_error)

        class _NoSessions:
            pass

        class _NoEvents:
            pass

        status = PiRuntimeManager(config=config, sessions=_NoSessions(), events=_NoEvents()).runtime_status()
        self.assertEqual(status["status"], "not_installed")
        self.assertIn("pointer is missing", status["lastError"])

    def test_required_pi_version_mismatch_fails_closed(self) -> None:
        payload, _ = self._payload("runtime-1")
        install_managed_pi_runtime(payload, self.app_support)
        with self.assertRaisesRegex(ManagedPiRuntimeError, "does not match required"):
            discover_managed_pi_runtime(self.app_support, expected_pi_version="0.81.0")

    def _payload(
        self,
        runtime_version: str,
        *,
        protocol_version: str = "1",
    ) -> tuple[Path, dict[str, object]]:
        payload = self.root / f"payload-{runtime_version}"
        node = payload / "bin" / "node"
        executable = payload / "lib" / "pi" / "dist" / "cli.js"
        extension = payload / "extensions" / "rag-ime-control.ts"
        node.parent.mkdir(parents=True)
        executable.parent.mkdir(parents=True)
        extension.parent.mkdir(parents=True)
        node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        node.chmod(0o755)
        executable.write_text(f"console.log('{runtime_version}')\n", encoding="utf-8")
        extension.write_text("export default function () {}\n", encoding="utf-8")
        manifest = build_managed_pi_runtime_manifest(
            payload,
            runtime_version=runtime_version,
            pi_version="0.80.7",
            launch_kind="node",
            pi_entrypoint="lib/pi/dist/cli.js",
            node_entrypoint="bin/node",
            extension_entrypoint="extensions/rag-ime-control.ts",
            source_repository="local/pi",
            source_commit=hashlib.sha256(runtime_version.encode("utf-8")).hexdigest()[:12],
            source_package="@earendil-works/pi-coding-agent",
            protocol_version=protocol_version,
        )
        write_managed_pi_runtime_manifest(payload / MANIFEST_NAME, manifest)
        return payload, manifest


if __name__ == "__main__":
    unittest.main()
