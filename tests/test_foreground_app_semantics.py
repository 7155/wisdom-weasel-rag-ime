from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.foreground_app_semantics import enrich_window_context_with_app_semantics
from rag_ime.smart_rag_context_packet import build_active_rag_context_packet
from rag_ime.window_context import project_window_context_for_generation, validate_window_context


class ForegroundApplicationSemanticsTests(unittest.TestCase):
    def test_zed_state_restores_active_editor_and_project_root_without_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_project = root / "TargetProject"
            other_project = root / "OtherProject"
            target_file = target_project / "src" / "target.py"
            other_file = other_project / "other.py"
            target_file.parent.mkdir(parents=True)
            other_project.mkdir()
            target_file.write_text("disk marker\n" * 120, encoding="utf-8")
            other_file.write_text("other marker\n", encoding="utf-8")
            (target_project / "docs").mkdir()
            (target_project / "README.md").write_text("readme", encoding="utf-8")
            (target_project / "node_modules").mkdir()
            db_path = root / "zed.sqlite"
            fixture_key = "sk-" + "1234567890abcdefghijklmnop"
            _create_zed_state_db(db_path)
            _insert_editor(
                db_path,
                workspace_id=1,
                project=target_project,
                buffer_path=target_file,
                timestamp="2026-07-23 12:00:00",
                contents=(
                    "unsaved line 1\n"
                    f"api_key = {fixture_key}\n"
                    f"workspace = {target_project}\n"
                    "unsaved line 4"
                ),
                scroll_top_row=1,
            )
            _insert_editor(
                db_path,
                workspace_id=2,
                project=other_project,
                buffer_path=other_file,
                timestamp="2026-07-24 12:00:00",
                contents=None,
                scroll_top_row=0,
            )

            enriched = enrich_window_context_with_app_semantics(
                _zed_window_context("TargetProject — target.py"),
                zed_state_db=db_path,
            )
            validated = validate_window_context(enriched)
            projected = project_window_context_for_generation(validated)

        semantics = projected["applicationSemantics"]
        self.assertEqual(semantics["source"], "zed_workspace_state")
        self.assertEqual(semantics["projectName"], "TargetProject")
        self.assertEqual(semantics["activeFile"], "src/target.py")
        self.assertIn("api_key = [REDACTED_SECRET]", semantics["editorExcerpt"])
        self.assertNotIn(fixture_key, semantics["editorExcerpt"])
        self.assertIn("workspace = [WORKSPACE]", semantics["editorExcerpt"])
        self.assertIn("\n", semantics["editorExcerpt"])
        self.assertEqual(semantics["contentOrigin"], "zed_recovery_buffer")
        self.assertFalse(semantics["trust"]["mayLagUnsavedChanges"])
        self.assertIn("docs/", semantics["projectEntries"])
        self.assertIn("README.md", semantics["projectEntries"])
        self.assertNotIn("node_modules/", semantics["projectEntries"])
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(temp_dir, serialized)

    def test_zed_disk_fallback_is_bounded_budgeted_and_marked_as_possibly_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "Project"
            active_file = project / "main.py"
            project.mkdir()
            active_file.write_text(
                "\n".join(f"line_{index} = {index}" for index in range(600)),
                encoding="utf-8",
            )
            for index in range(60):
                (project / f"entry-{index:02d}.txt").write_text("", encoding="utf-8")
            db_path = root / "zed.sqlite"
            _create_zed_state_db(db_path)
            _insert_editor(
                db_path,
                workspace_id=1,
                project=project,
                buffer_path=active_file,
                timestamp="2026-07-24 12:00:00",
                contents=None,
                scroll_top_row=300,
            )
            enriched = validate_window_context(
                enrich_window_context_with_app_semantics(
                    _zed_window_context("Project — main.py"),
                    zed_state_db=db_path,
                )
            )
            packet = build_active_rag_context_packet(
                scene="active_rag",
                current_context="请解释终端上方的代码",
                selected_text="请解释终端上方的代码",
                selected_text_hash="hash",
                frontend_revision=1,
                selection_epoch=1,
                panel_session_id="zed-terminal",
                project="Project",
                app="dev.zed.Zed",
                evidence=(),
                window_context=enriched,
            )

        semantics = packet["windowContext"]["applicationSemantics"]
        self.assertEqual(semantics["contentOrigin"], "workspace_file")
        self.assertTrue(semantics["trust"]["mayLagUnsavedChanges"])
        self.assertIn("line_294", semantics["editorExcerpt"])
        self.assertLessEqual(
            packet["trace"]["contextSourceTokens"]["windowContext"],
            900,
        )
        self.assertLessEqual(len(semantics["projectEntries"]), 48)

    def test_non_zed_apps_are_not_enriched(self) -> None:
        context = _zed_window_context("Notes")
        context["application"] = {
            "pid": 42,
            "bundleId": "com.apple.TextEdit",
            "name": "TextEdit",
            "windowTitle": "Notes",
        }
        context["applicationSemantics"] = {
            "source": "zed_workspace_state",
            "editorExcerpt": "frontend supplied text must not survive",
        }

        enriched = enrich_window_context_with_app_semantics(
            context,
            zed_state_db="/does/not/exist",
        )

        self.assertNotIn("applicationSemantics", enriched)
        self.assertNotIn("frontend supplied text", json.dumps(enriched))

    def test_zed_sensitive_active_file_keeps_project_orientation_but_blocks_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "Project"
            active_file = project / ".env"
            project.mkdir()
            disk_fixture_key = "sk-" + "should-never-leave-the-file"
            stored_fixture_key = "sk-" + "stored-secret-should-not-leave"
            active_file.write_text(
                f"API_KEY={disk_fixture_key}",
                encoding="utf-8",
            )
            db_path = root / "zed.sqlite"
            _create_zed_state_db(db_path)
            _insert_editor(
                db_path,
                workspace_id=1,
                project=project,
                buffer_path=active_file,
                timestamp="2026-07-24 12:00:00",
                contents=f"API_KEY={stored_fixture_key}",
                scroll_top_row=0,
            )

            enriched = validate_window_context(
                enrich_window_context_with_app_semantics(
                    _zed_window_context("Project — .env"),
                    zed_state_db=db_path,
                )
            )

        semantics = enriched["applicationSemantics"]
        self.assertEqual(semantics["projectName"], "Project")
        self.assertEqual(semantics["activeFile"], "")
        self.assertEqual(semantics["editorExcerpt"], "")
        self.assertEqual(semantics["contentOrigin"], "sensitive_file_blocked")
        self.assertNotIn("stored-secret", json.dumps(semantics))


def _zed_window_context(window_title: str) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.window-context.v1",
        "captureMode": "accessibility_semantics",
        "snapshotId": "axsnap-zed",
        "revision": 1,
        "privacyDisposition": "allowed",
        "application": {
            "pid": 42,
            "bundleId": "dev.zed.Zed",
            "name": "Zed",
            "windowTitle": window_title,
        },
        "nodes": [],
    }


def _create_zed_state_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE workspaces (
                workspace_id INTEGER PRIMARY KEY,
                paths TEXT,
                timestamp TEXT NOT NULL
            );
            CREATE TABLE panes (
                pane_id INTEGER PRIMARY KEY,
                workspace_id INTEGER NOT NULL,
                active INTEGER NOT NULL
            );
            CREATE TABLE items (
                item_id INTEGER NOT NULL,
                workspace_id INTEGER NOT NULL,
                pane_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                position INTEGER NOT NULL,
                active INTEGER NOT NULL
            );
            CREATE TABLE editors (
                item_id INTEGER NOT NULL,
                workspace_id INTEGER NOT NULL,
                buffer_path TEXT,
                scroll_top_row INTEGER NOT NULL,
                contents TEXT
            );
            """
        )
        connection.commit()


def _insert_editor(
    db_path: Path,
    *,
    workspace_id: int,
    project: Path,
    buffer_path: Path,
    timestamp: str,
    contents: str | None,
    scroll_top_row: int,
) -> None:
    pane_id = workspace_id * 10
    item_id = workspace_id * 100
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "INSERT INTO workspaces(workspace_id, paths, timestamp) VALUES (?, ?, ?)",
            (workspace_id, str(project), timestamp),
        )
        connection.execute(
            "INSERT INTO panes(pane_id, workspace_id, active) VALUES (?, ?, 1)",
            (pane_id, workspace_id),
        )
        connection.execute(
            """
            INSERT INTO items(item_id, workspace_id, pane_id, kind, position, active)
            VALUES (?, ?, ?, 'Editor', 0, 1)
            """,
            (item_id, workspace_id, pane_id),
        )
        connection.execute(
            """
            INSERT INTO editors(
                item_id, workspace_id, buffer_path, scroll_top_row, contents
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, workspace_id, str(buffer_path), scroll_top_row, contents),
        )
        connection.commit()


if __name__ == "__main__":
    unittest.main()
