from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from rag_ime.agent_workspace import WorkspaceHarness


@unittest.skipUnless(sys.platform == "darwin", "requires the macOS sandbox")
class WorkspaceSqliteScratchTests(unittest.TestCase):
    def test_test_databases_work_only_in_command_scratch(self) -> None:
        harness = WorkspaceHarness()
        if not harness.sandbox_executable.is_file():
            self.skipTest("sandbox-exec is unavailable")
        with tempfile.TemporaryDirectory(prefix="paw-sqlite-sandbox-test-") as directory:
            root = Path(directory).resolve()
            (root / "source.sqlite").write_text("private fixture")
            script = root / "probe.py"
            script.write_text(textwrap.dedent('''\
                import json, os, pathlib, sqlite3, tempfile
                workspace = pathlib.Path.cwd()
                scratch = pathlib.Path(tempfile.mkdtemp())
                checks = {}
                for extension in ("sqlite", "sqlite3", "db"):
                    db = scratch / ("test." + extension)
                    with sqlite3.connect(db) as connection:
                        connection.execute("pragma journal_mode=wal")
                        connection.execute("create table items(value)")
                        connection.execute("insert into items values (?)", (extension,))
                    with sqlite3.connect(db) as connection:
                        checks[extension] = connection.execute("select value from items").fetchone()[0]
                    db.unlink()
                for label, target in (
                    ("source_read", workspace / "source.sqlite"),
                    ("workspace_database", workspace / "new.sqlite"),
                    ("scratch_key", scratch / "private.key"),
                    ("scratch_auth", scratch / "auth.json"),
                    ("scratch_cookie", scratch / "cookies.sqlite"),
                ):
                    try:
                        if label == "source_read":
                            target.read_bytes()
                        else:
                            target.write_text("forbidden")
                    except OSError:
                        checks[label] = "denied"
                    else:
                        checks[label] = "allowed"
                link = scratch / "linked.sqlite"
                link.symlink_to(workspace / "source.sqlite")
                try:
                    link.read_bytes()
                except OSError:
                    checks["symlink_escape"] = "denied"
                else:
                    checks["symlink_escape"] = "allowed"
                try:
                    hardlink = scratch / "hardlink.sqlite"
                    os.link(workspace / "source.sqlite", hardlink)
                    hardlink.read_bytes()
                except OSError:
                    checks["hardlink_escape"] = "denied"
                else:
                    checks["hardlink_escape"] = "allowed"
                print(json.dumps(checks, sort_keys=True))
            '''), encoding="utf-8")
            for mode in ("workspace_managed", "read_only"):
                with self.subTest(mode=mode):
                    receipt = harness.execute(harness.prepare_command(
                        {"id": "agent:sqlite-test", "mode": "coordinator",
                         "executionMode": mode, "workspaceRoots": [str(root)],
                         "toolProfileVersion": "control-center-v1"},
                        {"command": "python3 probe.py", "cwd": str(root)},
                    ))
                    self.assertEqual(receipt["exitCode"], 0, receipt["output"])
                    self.assertEqual(json.loads(receipt["output"]), {
                        "sqlite": "sqlite", "sqlite3": "sqlite3", "db": "db",
                        "source_read": "denied", "workspace_database": "denied",
                        "scratch_key": "denied", "scratch_auth": "denied",
                        "scratch_cookie": "denied", "symlink_escape": "denied",
                        "hardlink_escape": "denied",
                    })
                    self.assertFalse((root / "new.sqlite").exists())
                    self.assertEqual((root / "source.sqlite").read_text(), "private fixture")
