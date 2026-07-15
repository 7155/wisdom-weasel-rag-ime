from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_tag_graph import propagate_tag_energy, recompute_tag_graph


class MemoryTagGraphGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-tag-governance-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        LocalSqliteCoreClient(self.db_path).initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_only_dsv4_or_user_tags_participate_in_tag_recall(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO memory_items(
                    memory_id, kind, text, normalized_text, project, status,
                    privacy_class, created_at_ms, updated_at_ms
                ) VALUES ('phrase:候选稳定性', 'phrase', '候选稳定性', '候选稳定性',
                          'wisdom-weasel-rag-ime', 'approved', 'local', 1, 1)
                """
            )
            item_id = int(conn.execute("SELECT id FROM memory_items").fetchone()[0])
            governed = int(
                conn.execute(
                    """
                    INSERT INTO memory_tags(
                        tag, normalized_tag, tag_type, quality_score,
                        created_at_ms, updated_at_ms, source, status
                    ) VALUES ('输入法', '输入法', 'concept', 0.9, 1, 1, 'dsv4', 'active')
                    """
                ).lastrowid
            )
            related = int(
                conn.execute(
                    """
                    INSERT INTO memory_tags(
                        tag, normalized_tag, tag_type, quality_score,
                        created_at_ms, updated_at_ms, source, status
                    ) VALUES ('候选稳定性', '候选稳定性', 'concept', 0.8, 1, 1, 'user', 'active')
                    """
                ).lastrowid
            )
            legacy = int(
                conn.execute(
                    """
                    INSERT INTO memory_tags(
                        tag, normalized_tag, tag_type, quality_score,
                        created_at_ms, updated_at_ms, source, status
                    ) VALUES ('前台上', '前台上', 'concept', 0.9, 1, 1, 'legacy_auto', 'hidden')
                    """
                ).lastrowid
            )
            for position, tag_id in enumerate((governed, related, legacy)):
                conn.execute(
                    """
                    INSERT INTO memory_item_tags(memory_item_id, tag_id, weight, position, evidence)
                    VALUES (?, ?, 0.8, ?, 'test')
                    """,
                    (item_id, tag_id, position),
                )
            conn.execute(
                """
                INSERT INTO memory_tag_edges(
                    src_tag_id, dst_tag_id, edge_type, weight, direction_bias,
                    evidence_count, updated_at_ms, metadata_json
                ) VALUES (?, ?, 'related', 0.9, 0.0, 2, 1, '{"source":"dsv4"}')
                """,
                (governed, related),
            )
            recompute_tag_graph(conn, project="wisdom-weasel-rag-ime")

            governed_energy = propagate_tag_energy(conn, query_text="输入法")
            legacy_energy = propagate_tag_energy(conn, query_text="前台上")
            legacy_edges = conn.execute(
                """
                SELECT COUNT(*) FROM memory_tag_edges
                WHERE edge_type = 'cooccur' AND (src_tag_id = ? OR dst_tag_id = ?)
                """,
                (legacy, legacy),
            ).fetchone()[0]

        self.assertIn(governed, governed_energy)
        self.assertIn(related, governed_energy)
        self.assertEqual(legacy_energy, {})
        self.assertEqual(legacy_edges, 0)


if __name__ == "__main__":
    unittest.main()
