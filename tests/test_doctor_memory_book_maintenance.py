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
    def test_owner_scoped_run_is_a_valid_maintenance_result(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-doctor-owner-") as tmp:
            base = Path(tmp)
            app_root = base / "app"
            runs_dir = base / "runs"
            db_path = base / "rag-ime.sqlite"
            plist_path = base / "maintenance.plist"
            for path in (
                app_root / "memory_book_maintenance_launch.py",
                app_root / "scripts/run_memory_book_maintenance_once.sh",
                app_root / "rag_ime/cli.py",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# installed\n", encoding="utf-8")
            (app_root / "rag-ime-install-marker.json").write_text(
                json.dumps({"sourceCommit": "abc123"}),
                encoding="utf-8",
            )
            db_path.write_text("db", encoding="utf-8")
            runs_dir.mkdir()
            (runs_dir / "owner-memory-20260710T000000Z.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "ranScopeCount": 1,
                        "results": [{"reviewRequired": True}],
                    }
                ),
                encoding="utf-8",
            )
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "ProgramArguments": [
                            "/usr/bin/python3",
                            str(app_root / "memory_book_maintenance_launch.py"),
                        ],
                        "WorkingDirectory": str(app_root),
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
                    "--runs-dir",
                    str(runs_dir),
                    "--db-path",
                    str(db_path),
                    "--require-run",
                ],
                cwd=root,
                env={**os.environ, "PATH": ""},
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertEqual(report["latestRun"]["mode"], "owner_scoped")
        self.assertTrue(report["latestRun"]["validationOk"])
        self.assertTrue(report["latestRun"]["reviewRequired"])

    def test_packaged_runtime_and_latest_validated_run_pass(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-doctor-") as tmp:
            base = Path(tmp)
            app_root = base / "app"
            runs_dir = base / "runs"
            db_path = base / "rag-ime.sqlite"
            plist_path = base / "maintenance.plist"
            for path in (
                app_root / "memory_book_maintenance_launch.py",
                app_root / "scripts/run_memory_book_maintenance_once.sh",
                app_root / "rag_ime/cli.py",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# installed\n", encoding="utf-8")
            (app_root / "rag-ime-install-marker.json").write_text(
                json.dumps({"sourceCommit": "abc123"}), encoding="utf-8"
            )
            db_path.write_text("db", encoding="utf-8")
            runs_dir.mkdir()
            stem = "memory-book-20260710T000000Z"
            (runs_dir / f"{stem}.json").write_text("{}", encoding="utf-8")
            (runs_dir / f"{stem}.preview.json").write_text("{}", encoding="utf-8")
            (runs_dir / f"{stem}.validate.json").write_text('{"ok": true}', encoding="utf-8")
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "ProgramArguments": ["/usr/bin/python3", str(app_root / "memory_book_maintenance_launch.py")],
                        "WorkingDirectory": str(app_root),
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
                    "--runs-dir",
                    str(runs_dir),
                    "--db-path",
                    str(db_path),
                    "--require-run",
                ],
                cwd=root,
                env={**os.environ, "PATH": ""},
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertTrue(report["latestRun"]["validationOk"])
        self.assertFalse(report["launchd"]["loaded"])

    def test_external_checkout_program_argument_fails(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-doctor-") as tmp:
            base = Path(tmp)
            app_root = base / "app"
            app_root.mkdir()
            plist_path = base / "maintenance.plist"
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "ProgramArguments": ["/bin/bash", "/Volumes/external/repo/scripts/run_memory_book_maintenance_once.sh"],
                        "WorkingDirectory": "/Volumes/external/repo",
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
                    "--runs-dir",
                    str(base / "runs"),
                    "--db-path",
                    str(base / "missing/rag-ime.sqlite"),
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app-local maintenance wrapper", result.stdout)


if __name__ == "__main__":
    unittest.main()
