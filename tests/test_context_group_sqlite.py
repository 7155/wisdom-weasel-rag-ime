from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms


class ContextGroupSqliteTest(unittest.TestCase):
    def test_initialize_migrates_old_input_events_and_persists_group(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-group-migration-") as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute(
                    """
                    CREATE TABLE input_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at_ms INTEGER NOT NULL,
                        source TEXT NOT NULL,
                        committed_text TEXT NOT NULL,
                        recent_context TEXT NOT NULL DEFAULT '',
                        preedit TEXT NOT NULL DEFAULT '',
                        schema_id TEXT NOT NULL DEFAULT 'default',
                        app TEXT NOT NULL DEFAULT 'manual',
                        project TEXT NOT NULL DEFAULT '',
                        candidate_rank INTEGER,
                        provider_name TEXT NOT NULL DEFAULT 'local',
                        tags_json TEXT NOT NULL DEFAULT '[]'
                    )
                    """
                )
            core = LocalSqliteCoreClient(db_path)
            core.initialize()
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="squirrel",
                    committed_text="完成前台闭环",
                    privacy_disposition="allowed",
                    context_group_id="doc:a",
                    context_group_level="document",
                )
            )
            with closing(sqlite3.connect(db_path)) as conn, conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(input_events)")}
                row = conn.execute(
                    "SELECT context_group_id, context_group_level FROM input_events ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertIn("context_group_id", columns)
            self.assertIn("context_group_level", columns)
            self.assertEqual(row, ("doc:a", "document"))


if __name__ == "__main__":
    unittest.main()
