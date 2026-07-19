from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.curated_codex_memory import (
    CURATED_CODEX_MEMORY_SCHEMA_VERSION,
    apply_curated_replacement,
    load_curated_bundle,
    plan_curated_replacement,
)


class CuratedCodexMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-curated-codex-")
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "rag-ime.sqlite"
        sources = AgentMemorySourceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )
        sources.initialize()
        imported = sources.checkpoint_external_summary(
            provider="codex",
            external_ref="rollout_summaries/2026-07-01.md",
            text="Codex 已整理的近期 Session 摘要：thread_id=legacy raw summary",
            tier="rollout-summary",
            source_occurred_at_ms=100,
            created_at_ms=200,
        )
        source = imported["source"]
        self.event_id = int(source["inputEventId"])
        self.source_id = str(source["sourceId"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, source_event_ids_json,
                    source_memory_ids_json, scope_app, scope_project, language,
                    confidence, quality_score, echo_risk, privacy_level, status,
                    created_at_ms, updated_at_ms, last_used_at_ms, owner_kind,
                    owner_id, claim_key, lineage_id, claim_state, valid_from_ms,
                    valid_to_ms, supersedes_id
                ) VALUES (
                    'atom:legacy-superseded', 'durable_preference', '已过期摘要',
                    '已过期摘要', ?, '[]', NULL, 'wisdom-weasel-rag-ime',
                    'zh', 0.8, 0.8, 0.0, 'local', 'superseded', 100, 100, NULL,
                    'user', 'default', 'legacy:superseded', 'legacy:superseded',
                    'superseded', 100, 200, NULL
                )
                """,
                (json.dumps([self.event_id]),),
            )
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, source_event_ids_json,
                    source_memory_ids_json, scope_app, scope_project, language,
                    confidence, quality_score, echo_risk, privacy_level, status,
                    created_at_ms, updated_at_ms, last_used_at_ms, owner_kind,
                    owner_id, claim_key, lineage_id, claim_state, valid_from_ms,
                    valid_to_ms, supersedes_id
                ) VALUES (
                    'atom:legacy-codex', 'durable_preference', '旧 Session 原样摘要',
                    '旧 session 原样摘要', ?, '[]', NULL, 'wisdom-weasel-rag-ime',
                    'zh', 0.8, 0.8, 0.0, 'local', 'active', 200, 200, NULL,
                    'user', 'default', 'legacy:codex', 'legacy:codex', 'current',
                    200, NULL, NULL
                )
                """,
                (json.dumps([self.event_id]),),
            )
            conn.execute(
                """
                INSERT INTO memory_books(
                    book_id, book_type, book_key, title, summary, normalized_text,
                    project, app, tags_json, surface_hints_json,
                    query_expansions_json, source_event_ids_json,
                    memory_atom_ids_json, status, confidence, quality_score,
                    created_at_ms, updated_at_ms, metadata_json, archived_at_ms,
                    last_active_at_ms, archive_reason, owner_kind, owner_id
                ) VALUES (
                    'book:legacy-codex', 'topic', 'legacy-codex', '旧 Codex 摘要',
                    '逐 Session 原样归档', '逐 session 原样归档',
                    'wisdom-weasel-rag-ime', '', '[]', '[]', '[]', ?,
                    '["atom:legacy-codex", "atom:legacy-superseded"]',
                    'active', 0.8, 0.8, 200, 200,
                    '{}', NULL, 200, '', 'user', 'default'
                )
                """,
                (json.dumps([self.event_id]),),
            )
            conn.execute(
                """
                INSERT INTO management_settings(
                    key, value_json, updated_at_ms, updated_by, audit_id
                ) VALUES ('memory', ?, 200, 'test', NULL)
                """,
                (
                    json.dumps(
                        {
                            "enabled": True,
                            "externalSources": {
                                "codexMemory": {"enabled": True}
                            },
                        }
                    ),
                ),
            )
        self.bundle_path = self.root / "bundle.json"
        self.bundle_path.write_text(
            json.dumps(
                {
                    "schemaVersion": CURATED_CODEX_MEMORY_SCHEMA_VERSION,
                    "bundleId": "codex-2026-q2-q3-v1",
                    "project": "wisdom-weasel-rag-ime",
                    "period": {"start": "2026-04-20", "end": "2026-07-19"},
                    "items": [
                        {
                            "claimKey": "user:engineering:runtime-verification",
                            "memoryKind": "preference",
                            "text": "产品改动需要验证正式安装包、运行态和真实交互。",
                            "sourceRefs": ["memory_summary.md", "MEMORY.md"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_replacement_retires_direct_rows_and_applies_reviewed_atoms(self) -> None:
        bundle = load_curated_bundle(self.bundle_path)
        plan = plan_curated_replacement(self.db_path, bundle)
        self.assertEqual(plan["activeDirectSourceCount"], 1)
        self.assertEqual(plan["retiringAtomCount"], 1)
        self.assertEqual(plan["retiringBookCount"], 1)
        self.assertEqual(plan["additionCount"], 1)

        report = apply_curated_replacement(
            self.db_path,
            bundle,
            backup_path=self.root / "before.sqlite",
            confirm_text="APPLY CURATED CODEX MEMORY",
        )

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["expiredDirectSourceCount"], 1)
        self.assertEqual(report["forgottenAtomCount"], 1)
        self.assertEqual(report["archivedBookCount"], 1)
        self.assertEqual(report["addedAtomCount"], 1)
        self.assertEqual(report["legacyCodexSettingRowCount"], 0)
        self.assertTrue((self.root / "before.sqlite").is_file())
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM agent_memory_sources WHERE source_id = ?",
                    (self.source_id,),
                ).fetchone()[0],
                "superseded",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM memory_atoms WHERE id = 'atom:legacy-codex'"
                ).fetchone()[0],
                "tombstoned",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM memory_books WHERE book_id = 'book:legacy-codex'"
                ).fetchone()[0],
                "archived",
            )
            atom = conn.execute(
                """
                SELECT id, status FROM memory_atoms
                WHERE claim_key = 'user:engineering:runtime-verification'
                """
            ).fetchone()
            self.assertEqual(atom[1], "approved")
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_atom_evidence_links WHERE memory_atom_id = ?",
                    (atom[0],),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_projection_outbox WHERE state != 'applied'"
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
