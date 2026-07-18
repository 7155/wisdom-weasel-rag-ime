from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.manual_memory_application import (
    _apply_source_decisions,
    apply_manual_memory_manifest,
    verify_manual_memory_application,
)
from rag_ime.manual_memory_review import (
    MANUAL_MEMORY_MANIFEST_SCHEMA_VERSION,
    export_manual_memory_review,
)


PROJECT = "wisdom-weasel-rag-ime"


class ManualMemoryApplicationTests(unittest.TestCase):
    def test_coalesced_fragment_is_not_remembered_without_artifact_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-source-selection-") as temporary:
            db_path = Path(temporary) / "rag-ime.sqlite"
            sessions = AgentSessionStore(db_path)
            sessions.initialize()
            session = sessions.create(title="selection", created_at_ms=1)
            sources = AgentMemorySourceStore(db_path, project=PROJECT)
            sources.initialize()
            for suffix, text, created_at_ms in (
                ("full", "候选数据库通过完整校验后才能激活。", 1_700_000_000_000),
                ("fragment", "候选数据库通过", 1_700_000_001_000),
            ):
                sources.checkpoint_user_message(
                    session_id=str(session["id"]),
                    pi_entry_id=f"entry:{suffix}",
                    turn_id=f"turn:{suffix}",
                    text=text,
                    created_at_ms=created_at_ms,
                )
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT source.source_id, source.input_event_id, event.committed_text
                       FROM agent_memory_sources AS source
                       JOIN input_events AS event ON event.id = source.input_event_id
                       ORDER BY source.input_event_id"""
                ).fetchall()
                full_event_id = int(rows[0]["input_event_id"])
                source_to_input = {str(row["source_id"]): "logical:coalesced" for row in rows}
                _apply_source_decisions(
                    conn,
                    inputs={},
                    decisions={
                        "logical:coalesced": {
                            "decision": "remember",
                            "reasonCode": "durable_database_safety",
                        }
                    },
                    source_to_input=source_to_input,
                    selected_event_ids={full_event_id},
                    run_id="test-selection",
                    reviewer="test",
                    timestamp=1_800_000_000_000,
                )
                dispositions = {
                    str(row[0]): (str(row[1]), str(row[2]), json.loads(str(row[3])))
                    for row in conn.execute(
                        """SELECT event.committed_text, source.disposition,
                                  source.disposition_reason, source.metadata_json
                           FROM agent_memory_sources AS source
                           JOIN input_events AS event ON event.id = source.input_event_id"""
                    )
                }
            self.assertEqual(dispositions["候选数据库通过完整校验后才能激活。"][0], "remember")
            fragment = dispositions["候选数据库通过"]
            self.assertEqual(fragment[0], "not_for_memory")
            self.assertEqual(fragment[1], "coalesced_source_not_selected")
            self.assertEqual(fragment[2]["manualHistoryReview"]["logicalDecision"], "remember")
            self.assertEqual(
                fragment[2]["manualHistoryReview"]["effectiveDecision"],
                "not_for_memory",
            )

    def test_applies_only_reviewed_conclusions_and_keeps_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-manual-apply-") as temporary:
            db_path = Path(temporary) / "rag-ime.sqlite"
            sessions = AgentSessionStore(db_path)
            sessions.initialize()
            session = sessions.create(title="manual-review", created_at_ms=1)
            sources = AgentMemorySourceStore(db_path, project=PROJECT)
            sources.initialize()
            sources.checkpoint_user_message(
                session_id=str(session["id"]),
                pi_entry_id="entry:stable",
                turn_id="turn:stable",
                text="所有正式数据库变更先在隔离候选副本完成验证。",
                created_at_ms=1_700_000_000_000,
            )
            sources.checkpoint_user_message(
                session_id=str(session["id"]),
                pi_entry_id="entry:stable-repeat",
                turn_id="turn:stable-repeat",
                text="所有正式数据库变更先在隔离候选副本完成验证。",
                created_at_ms=1_700_000_030_000,
            )
            sources.checkpoint_user_message(
                session_id=str(session["id"]),
                pi_entry_id="entry:noise",
                turn_id="turn:noise",
                text="请调用 ime_memory Tool 的 curation_prepare 操作。",
                created_at_ms=1_700_000_060_000,
            )
            with sqlite3.connect(db_path) as conn:
                event_id = int(
                    conn.execute(
                        "SELECT id FROM input_events WHERE committed_text LIKE '所有正式数据库%'"
                    ).fetchone()[0]
                )
                conn.execute(
                    """INSERT INTO memory_atoms(
                           id, kind, text, canonical_text, source_event_ids_json,
                           source_memory_ids_json, scope_app, scope_project,
                           confidence, quality_score, privacy_level, status,
                           created_at_ms, updated_at_ms, owner_kind, owner_id,
                           claim_key, lineage_id, claim_state, valid_from_ms
                       ) VALUES (
                           'atom:old-question', 'project_requirement',
                           '数据库应该怎么迁移？', '数据库应该怎么迁移？', ?, '[]', '', ?,
                           0.7, 0.7, 'local', 'active', 1, 1, 'user', 'default',
                           'legacy:database-question', 'lineage:legacy', 'current', 1
                       )""",
                    (f"[{event_id}]", PROJECT),
                )
                conn.execute(
                    """INSERT INTO memory_books(
                           book_id, book_type, book_key, title, summary,
                           normalized_text, project, tags_json,
                           source_event_ids_json, memory_atom_ids_json, status,
                           confidence, quality_score, created_at_ms, updated_at_ms,
                           metadata_json, owner_kind, owner_id
                       ) VALUES (
                           'book:old-log', 'topic', 'old-log', '旧日志',
                           '请调用工具的原始日志。', '旧日志', ?, '[]', ?,
                           '["atom:old-question"]', 'active', 0.7, 0.7, 1, 1,
                           '{}', 'user', 'default'
                       )""",
                    (PROJECT, f"[{event_id}]"),
                )
                conn.execute(
                    """INSERT INTO memory_cleanup_runs(
                           run_id, created_at_ms, provider, model, status, summary, metadata_json
                       ) VALUES ('unrelated-draft', 1, '', '', 'draft', '', '{}')"""
                )
                conn.execute(
                    """INSERT INTO memory_items(
                           memory_id, kind, text, normalized_text, summary,
                           source_event_id, project, status, created_at_ms,
                           updated_at_ms, metadata_json
                       ) VALUES
                         ('phrase:legal', 'phrase', '候选数据库', '候选数据库',
                          '候选数据库术语', ?, ?, 'active', 1, 1, '{}'),
                         ('phrase:slogan', 'phrase', '加油加油', '加油加油',
                          '无来源口号', NULL, ?, 'active', 1, 1, '{}')""",
                    (event_id, PROJECT, PROJECT),
                )
                export = export_manual_memory_review(conn, project=PROJECT)

            stable_inputs = [item for item in export["inputs"] if "正式数据库" in item["text"]]
            stable = stable_inputs[0]
            for duplicate in stable_inputs[1:]:
                stable["sourceIds"] = list(stable["sourceIds"]) + list(duplicate["sourceIds"])
                stable["sourceEventIds"] = list(stable["sourceEventIds"]) + list(
                    duplicate["sourceEventIds"]
                )
                export["inputs"].remove(duplicate)
            noise = next(item for item in export["inputs"] if "curation_prepare" in item["text"])
            manifest = {
                "schemaVersion": MANUAL_MEMORY_MANIFEST_SCHEMA_VERSION,
                "project": PROJECT,
                "evidenceFingerprint": export["evidenceFingerprint"],
                "memoryCatalogFingerprint": export["memoryCatalogFingerprint"],
                "governanceFingerprint": export["governanceFingerprint"],
                "decisions": [
                    {
                        "inputId": stable["inputId"],
                        "decision": "remember",
                        "reasonCode": "durable_database_safety",
                    },
                    {
                        "inputId": noise["inputId"],
                        "decision": "not_for_memory",
                        "reasonCode": "tool_instruction_without_fact",
                    },
                ],
                "atoms": [
                    {
                        "atomId": "atom:review:database-candidate-first",
                        "claimKey": "engineering:database:candidate-first",
                        "canonicalText": "正式数据库仅接受已在隔离候选库通过完整校验的变更。",
                        "kind": "durable_preference",
                        "sourceEventIds": stable["sourceEventIds"],
                        "confidence": 0.98,
                        "qualityScore": 0.98,
                        "tags": ["数据库安全"],
                        "validFromMs": stable["createdAtMs"],
                        "directCandidateAllowed": False,
                    }
                ],
                "books": [
                    {
                        "bookId": "book:topic:database-safety",
                        "bookType": "topic",
                        "bookKey": "memory-rag-governance",
                        "title": "数据库安全与候选迁移",
                        "summary": "数据库整理先生成隔离候选并完成一致性验证，再通过可回滚流程替换正式库。",
                        "tags": ["数据库安全"],
                        "queryExpansions": ["候选数据库", "回滚"],
                        "sourceEventIds": stable["sourceEventIds"],
                        "memoryAtomIds": ["atom:review:database-candidate-first"],
                        "confidence": 0.98,
                        "qualityScore": 0.98,
                    }
                ],
                "timelines": [
                    {
                        "date": stable["date"],
                        "start": datetime.fromtimestamp(
                            int(stable["createdAtMs"]) / 1000,
                            tz=ZoneInfo("Asia/Shanghai"),
                        ).strftime("%H:%M"),
                        "end": datetime.fromtimestamp(
                            int(stable["createdAtMs"]) / 1000,
                            tz=ZoneInfo("Asia/Shanghai"),
                        ).strftime("%H:%M"),
                        "goal": "确定数据库整理的安全边界",
                        "actualActions": "明确候选库先行、验证完整性并保留回滚副本。",
                        "resultOrBlocker": "形成可执行的数据迁移约束，尚未代表正式库已切换。",
                        "apps": ["Codex"],
                        "evidenceLogicalInputIds": [stable["inputId"]],
                    }
                ],
                "supersedes": [
                    {
                        "oldId": "atom:old-question",
                        "newId": "atom:review:database-candidate-first",
                        "sourceEventIds": stable["sourceEventIds"],
                    }
                ],
                "existingMemoryAudit": {
                    "atoms": [
                        {
                            "atomId": "atom:old-question",
                            "action": "supersede",
                            "replacementAtomId": "atom:review:database-candidate-first",
                            "reason": "用已核验的长期约束替换原始问题。",
                        }
                    ],
                    "books": [
                        {
                            "bookId": "book:old-log",
                            "action": "archive",
                            "reason": "工具指令日志不能作为主题书。",
                        }
                    ],
                },
                "existingPhraseAudit": [
                    {
                        "memoryId": "phrase:legal",
                        "action": "keep",
                        "reason": "有可追溯来源的稳定项目术语。",
                    },
                    {
                        "memoryId": "phrase:slogan",
                        "action": "archive",
                        "reason": "无来源口号，不进入长期检索。",
                    },
                ],
            }
            with sqlite3.connect(db_path) as conn, patch(
                "rag_ime.manual_memory_application.verify_manual_memory_application",
                return_value={"ok": False, "errors": ["forced_post_verify_failure"]},
            ):
                conn.row_factory = sqlite3.Row
                with self.assertRaises(RuntimeError):
                    apply_manual_memory_manifest(
                        conn,
                        candidate_path=db_path,
                        export=export,
                        manifest=manifest,
                        applied_at_ms=1_800_000_000_000,
                    )
                self.assertEqual(
                    conn.execute(
                        "SELECT disposition FROM agent_memory_sources WHERE source_id = ?",
                        (stable["sourceIds"][0],),
                    ).fetchone()[0],
                    "pending",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT status FROM memory_books WHERE book_id = 'book:old-log'"
                    ).fetchone()[0],
                    "active",
                )
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                report = apply_manual_memory_manifest(
                    conn,
                    candidate_path=db_path,
                    export=export,
                    manifest=manifest,
                    applied_at_ms=1_800_000_000_000,
                )
                active_texts = [
                    str(row[0])
                    for row in conn.execute(
                        "SELECT canonical_text FROM memory_atoms WHERE status = 'active'"
                    ).fetchall()
                ]
                dispositions = dict(
                    conn.execute(
                        """SELECT e.committed_text, s.disposition
                           FROM agent_memory_sources s
                           JOIN input_events e ON e.id = s.input_event_id"""
                    ).fetchall()
                )
                old_book = conn.execute(
                    "SELECT status, archive_reason FROM memory_books WHERE book_id = 'book:old-log'"
                ).fetchone()
                timeline = conn.execute(
                    "SELECT status, summary_text, event_count, segments_json FROM daily_activity_timelines"
                ).fetchone()
                cleanup_status = conn.execute(
                    "SELECT status FROM memory_cleanup_runs WHERE run_id = 'unrelated-draft'"
                ).fetchone()[0]
                old_supersedes = conn.execute(
                    "SELECT supersedes_id FROM memory_atoms WHERE id = 'atom:old-question'"
                ).fetchone()[0]
                new_supersedes = conn.execute(
                    "SELECT supersedes_id FROM memory_atoms WHERE id = 'atom:review:database-candidate-first'"
                ).fetchone()[0]
                supersession = conn.execute(
                    """SELECT old_memory_id, new_memory_id FROM memory_supersessions
                       WHERE old_memory_id = 'atom:old-question'"""
                ).fetchone()
                phrase_rows = dict(
                    conn.execute(
                        "SELECT memory_id, status FROM memory_items WHERE kind = 'phrase'"
                    ).fetchall()
                )
                slogan_metadata = json.loads(
                    conn.execute(
                        "SELECT metadata_json FROM memory_items WHERE memory_id = 'phrase:slogan'"
                    ).fetchone()[0]
                )
                # Corrupt governance so one physical evidence event has both a
                # remember and a not_for_memory source. A set-of-event-ids
                # comparison alone cannot observe this mixed disposition.
                conn.execute(
                    """UPDATE agent_memory_sources
                       SET input_event_id = ?
                       WHERE source_id = ?""",
                    (int(stable["sourceEventIds"][0]), str(noise["sourceIds"][0])),
                )
                mixed_source_verification = verify_manual_memory_application(
                    conn,
                    manifest=manifest,
                    project=PROJECT,
                )

            self.assertTrue(report["ok"])
            self.assertEqual(
                active_texts,
                ["正式数据库仅接受已在隔离候选库通过完整校验的变更。"],
            )
            self.assertEqual(dispositions[noise["text"]], "not_for_memory")
            self.assertEqual(dispositions[stable["text"]], "remember")
            self.assertEqual(tuple(old_book), ("archived", "discarded_by_manual_review"))
            self.assertEqual(timeline["status"], "approved")
            self.assertNotIn("请调用", timeline["summary_text"])
            self.assertNotIn("。；", timeline["summary_text"])
            self.assertNotIn("；；", timeline["summary_text"])
            self.assertTrue(timeline["summary_text"].endswith("。"))
            self.assertEqual(timeline["event_count"], 1)
            timeline_segment = json.loads(timeline["segments_json"])[0]
            self.assertEqual(timeline_segment["eventCount"], 1)
            self.assertEqual(timeline_segment["physicalEventCount"], 2)
            self.assertEqual(len(timeline_segment["sourceEventIds"]), 2)
            self.assertEqual(cleanup_status, "draft")
            self.assertIsNone(old_supersedes)
            self.assertEqual(new_supersedes, "atom:old-question")
            self.assertEqual(
                tuple(supersession),
                ("atom:old-question", "atom:review:database-candidate-first"),
            )
            self.assertEqual(phrase_rows["phrase:legal"], "active")
            self.assertEqual(phrase_rows["phrase:slogan"], "hidden")
            self.assertEqual(
                slogan_metadata["manualHistoryReview"]["action"], "archive"
            )
            self.assertFalse(mixed_source_verification["ok"])
            self.assertTrue(mixed_source_verification["invalidArtifactSources"])
            self.assertTrue(
                any(
                    str(error).startswith("active_artifact_invalid_source=")
                    for error in mixed_source_verification["errors"]
                )
            )

    def test_rejects_connection_not_bound_to_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-manual-path-") as temporary:
            first = Path(temporary) / "first.sqlite"
            second = Path(temporary) / "second.sqlite"
            AgentSessionStore(first).initialize()
            AgentSessionStore(second).initialize()
            with sqlite3.connect(first) as conn:
                with self.assertRaisesRegex(Exception, "path mismatch"):
                    apply_manual_memory_manifest(
                        conn,
                        candidate_path=second,
                        export={},
                        manifest={},
                    )


if __name__ == "__main__":
    unittest.main()
