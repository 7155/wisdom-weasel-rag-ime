from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MemoryBookMaintenanceDoctorTests(unittest.TestCase):
    def test_thin_gateway_trigger_runtime_passes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-doctor-") as tmp:
            base = Path(tmp)
            app_root = base / "app"
            app_root.mkdir()
            wrapper = app_root / "memory_book_maintenance_launch.py"
            wrapper.write_text("# installed\n", encoding="utf-8")
            marker = app_root / "rag-ime-install-marker.json"
            marker.write_text(
                json.dumps(
                    {
                        "component": "memory-maintenance-trigger",
                        "transport": "gateway-loopback-http",
                        "sourceCommit": "abc123",
                    }
                ),
                encoding="utf-8",
            )
            plist_path = base / "maintenance.plist"
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "ProgramArguments": ["/usr/bin/python3", str(wrapper)],
                        "WorkingDirectory": str(app_root),
                        "EnvironmentVariables": {
                            "RAG_IME_AGENT_GATEWAY_URL": "http://127.0.0.1:8768",
                            "RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER": "scheduled",
                        },
                    }
                )
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/doctor_memory_book_maintenance.py"),
                    "--app-root",
                    str(app_root),
                    "--plist-path",
                    str(plist_path),
                ],
                cwd=root,
                env={**os.environ, "PATH": ""},
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertEqual(
            report["schemaVersion"],
            "rag-ime.memory-book-maintenance-doctor.v2",
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["gatewayUrl"], "http://127.0.0.1:8768")
        self.assertFalse(report["schedulerReadsDatabase"])
        self.assertFalse(report["schedulerStartsRuntimeHost"])

    def test_obsolete_packaged_runtime_is_rejected(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-doctor-old-") as tmp:
            base = Path(tmp)
            app_root = base / "app"
            wrapper = app_root / "memory_book_maintenance_launch.py"
            package = app_root / "rag_ime/cli.py"
            for path in (wrapper, package):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# installed\n", encoding="utf-8")
            (app_root / "rag-ime-install-marker.json").write_text(
                json.dumps(
                    {
                        "component": "memory-maintenance-trigger",
                        "sourceCommit": "abc123",
                    }
                ),
                encoding="utf-8",
            )
            plist_path = base / "maintenance.plist"
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "ProgramArguments": ["/usr/bin/python3", str(wrapper)],
                        "WorkingDirectory": str(app_root),
                        "EnvironmentVariables": {
                            "RAG_IME_AGENT_GATEWAY_URL": "http://127.0.0.1:8768",
                            "RAG_IME_DB_PATH": "/tmp/legacy.sqlite",
                        },
                    }
                )
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/doctor_memory_book_maintenance.py"),
                    "--app-root",
                    str(app_root),
                    "--plist-path",
                    str(plist_path),
                ],
                cwd=root,
                env={**os.environ, "PATH": ""},
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("obsolete database/runtime payload", result.stdout)
        self.assertIn("database/model runtime settings", result.stdout)

    def test_external_checkout_program_argument_fails(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-doctor-path-") as tmp:
            base = Path(tmp)
            app_root = base / "app"
            app_root.mkdir()
            plist_path = base / "maintenance.plist"
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "ProgramArguments": [
                            "/bin/bash",
                            "/Volumes/external/repo/scripts/run_memory_book_maintenance_once.sh",
                        ],
                        "WorkingDirectory": "/Volumes/external/repo",
                        "EnvironmentVariables": {
                            "RAG_IME_AGENT_GATEWAY_URL": "http://127.0.0.1:8768",
                        },
                    }
                )
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/doctor_memory_book_maintenance.py"),
                    "--app-root",
                    str(app_root),
                    "--plist-path",
                    str(plist_path),
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app-local maintenance wrapper", result.stdout)


if __name__ == "__main__":
    unittest.main()
