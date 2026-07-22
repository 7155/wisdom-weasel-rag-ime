from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.retrieval_vector_index import (
    load_retrieval_doc_vectors,
    rebuild_retrieval_doc_vectors,
)


class _Provider:
    fingerprint = "test:revision-cas"

    def __init__(self, callback=None) -> None:
        self.callback = callback
        self.called = False

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if self.callback is not None and not self.called:
            self.called = True
            self.callback()
        return [[float(index + 1), 1.0] for index, _ in enumerate(texts)]

    def embed(self, text: str) -> list[float]:
        return [float(len(text) or 1), 1.0]


class RetrievalVectorRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-vector-revision-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        LocalSqliteCoreClient(self.db_path).initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def test_cached_vector_is_removed_when_doc_revision_no_longer_has_a_vector(self) -> None:
        with closing(self.connect()) as conn:
            self._insert_doc(conn, "phrase:a", revision=1)
            rebuild_retrieval_doc_vectors(conn, _Provider(), doc_ids=["phrase:a"])
            self.assertIn(
                "phrase:a",
                load_retrieval_doc_vectors(conn, _Provider.fingerprint, ["phrase:a"]),
            )

            conn.execute(
                "UPDATE memory_retrieval_docs SET source_revision = 2 WHERE doc_id = 'phrase:a'"
            )
            conn.execute(
                "DELETE FROM memory_retrieval_doc_vectors WHERE doc_id = 'phrase:a'"
            )

            self.assertEqual(
                load_retrieval_doc_vectors(conn, _Provider.fingerprint, ["phrase:a"]),
                {},
            )

    def test_vector_loader_rejects_mixed_source_revisions(self) -> None:
        with closing(self.connect()) as conn:
            self._insert_doc(conn, "phrase:a", revision=2)
            conn.execute(
                """
                INSERT INTO memory_retrieval_doc_vectors(
                    doc_id, provider_fingerprint, raw_vector_json,
                    tag_vector_json, group_vector_json, dimensions,
                    source_revision, projection_version, built_at_ms, updated_at_ms
                ) VALUES ('phrase:a', ?, '[1,0]', '[0,1]', '[]', 2, 1, 1, 10, 10)
                """,
                (_Provider.fingerprint,),
            )

            self.assertEqual(
                load_retrieval_doc_vectors(conn, _Provider.fingerprint, ["phrase:a"]),
                {},
            )

    def test_stale_vector_worker_cannot_overwrite_new_doc_revision(self) -> None:
        with closing(self.connect()) as conn:
            self._insert_doc(conn, "phrase:a", revision=1)

            def advance_revision() -> None:
                conn.execute(
                    "UPDATE memory_retrieval_docs SET source_revision = 2 WHERE doc_id = 'phrase:a'"
                )

            report = rebuild_retrieval_doc_vectors(
                conn,
                _Provider(advance_revision),
                doc_ids=["phrase:a"],
            )

            self.assertEqual(report["documents"], 0)
            self.assertEqual(report["skippedStale"], 1)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_retrieval_doc_vectors"
                ).fetchone()[0],
                0,
            )

    def test_per_doc_rebuild_does_not_touch_unrequested_docs(self) -> None:
        with closing(self.connect()) as conn:
            self._insert_doc(conn, "phrase:a", revision=1)
            self._insert_doc(conn, "phrase:b", revision=1)

            report = rebuild_retrieval_doc_vectors(
                conn,
                _Provider(),
                doc_ids=["phrase:b"],
            )

            self.assertEqual(report["requestedDocuments"], 1)
            self.assertEqual(
                [
                    str(row[0])
                    for row in conn.execute(
                        "SELECT doc_id FROM memory_retrieval_doc_vectors ORDER BY doc_id"
                    ).fetchall()
                ],
                ["phrase:b"],
            )

    @staticmethod
    def _insert_doc(
        conn: sqlite3.Connection,
        doc_id: str,
        *,
        revision: int,
    ) -> None:
        conn.execute(
            """
            INSERT INTO memory_retrieval_docs(
                doc_id, doc_type, source_id, raw_text, tags_text,
                aliases_text, surface_hints_text, query_expansions_text,
                time_key, project, app, status, source_revision,
                projection_version, updated_at_ms, metadata_json
            ) VALUES (?, 'phrase', ?, 'vector revision test', 'vector', '',
                      '', '', '', 'test', '', 'active', ?, 1, 1, '{}')
            """,
            (doc_id, doc_id, revision),
        )


if __name__ == "__main__":
    unittest.main()
