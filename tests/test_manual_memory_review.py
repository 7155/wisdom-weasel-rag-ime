from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.manual_memory_review import (
    MANUAL_MEMORY_MANIFEST_SCHEMA_VERSION,
    ManualMemoryReviewError,
    assemble_manual_memory_manifest,
    export_manual_memory_review,
    validate_manual_memory_manifest,
)


PROJECT = "wisdom-weasel-rag-ime"


class ManualMemoryReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-manual-review-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        sessions = AgentSessionStore(self.db_path)
        sessions.initialize()
        self.session = sessions.create(title="review", created_at_ms=1)
        self.sources = AgentMemorySourceStore(self.db_path, project=PROJECT)
        self.sources.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_export_is_read_only_and_redacts_sensitive_input(self) -> None:
        self._checkpoint("稳定偏好：所有数据库迁移都先在副本验证。", entry="one")
        self._checkpoint("旧版历史记录占位文本", entry="secret")
        # The current checkpoint gate already blocks secrets. Simulate a legacy
        # row captured before that gate existed to verify the review export also
        # fails closed.
        fixture_key = "sk-" + "test-1234567890abcdef"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE input_events SET committed_text = ? WHERE id = (SELECT MAX(id) FROM input_events)",
                (f"API key 是 {fixture_key}",),
            )
        with sqlite3.connect(self.db_path) as conn:
            before = conn.total_changes
            export = export_manual_memory_review(conn, project=PROJECT)
            self.assertEqual(conn.total_changes, before)

        self.assertEqual(export["counts"]["logicalInputs"], 2)
        self.assertEqual(export["counts"]["sensitiveLogicalInputs"], 1)
        sensitive = next(item for item in export["inputs"] if item["sensitive"])
        self.assertEqual(sensitive["text"], "[REDACTED: sensitive input]")
        self.assertTrue(str(export["evidenceFingerprint"]).startswith("sha256:"))
        self.assertTrue(str(export["memoryCatalogFingerprint"]).startswith("sha256:"))
        self.assertTrue(str(export["governanceFingerprint"]).startswith("sha256:"))

    def test_validation_fails_closed_on_incomplete_or_unbacked_review(self) -> None:
        self._checkpoint("数据库迁移必须先在候选副本验证。", entry="one")
        with sqlite3.connect(self.db_path) as conn:
            export = export_manual_memory_review(conn, project=PROJECT)
        input_item = export["inputs"][0]
        incomplete = self._manifest(export, decisions=[], atoms=[])
        validation = validate_manual_memory_manifest(export, manifest=incomplete)
        self.assertFalse(validation["ok"])
        self.assertIn("missing_decisions:1", validation["errors"])

        remembered_without_atom = self._manifest(
            export,
            decisions=[
                {
                    "inputId": input_item["inputId"],
                    "decision": "remember",
                    "reasonCode": "durable_database_safety",
                }
            ],
            atoms=[],
        )
        validation = validate_manual_memory_manifest(
            export,
            manifest=remembered_without_atom,
        )
        self.assertFalse(validation["ok"])
        self.assertTrue(
            any(
                str(error).startswith("remembered_input_without_memory_artifact:")
                for error in validation["errors"]
            )
        )

    def test_assemble_requires_complete_source_and_existing_memory_review(self) -> None:
        self._checkpoint("数据库迁移必须先在候选副本验证。", entry="one")
        with sqlite3.connect(self.db_path) as conn:
            export = export_manual_memory_review(conn, project=PROJECT)
        input_item = export["inputs"][0]
        event_id = int(input_item["sourceEventIds"][0])
        part = {
            "schemaVersion": "rag-ime.manual-memory-review-part.v1",
            "reviewer": {"model": "gpt-5.6-sol", "effort": "medium"},
            "decisions": [
                {
                    "inputId": input_item["inputId"],
                    "decision": "remember",
                    "reasonCode": "durable_database_safety",
                }
            ],
            "atoms": [
                {
                    "atomId": "atom:database-candidate-first",
                    "claimKey": "engineering:database.candidate-first",
                    "canonicalText": "数据库迁移必须先在隔离候选副本验证。",
                    "kind": "durable_preference",
                    "sourceEventIds": [event_id],
                    "confidence": 0.96,
                    "qualityScore": 0.94,
                    "directCandidateAllowed": False,
                }
            ],
            "books": [],
            "supersedes": [],
        }
        audit = {
            "atoms": [
                {
                    "atomId": item["atomId"],
                    "action": "archive",
                    "reason": "fixture review",
                }
                for item in export["existingAtoms"]
            ],
            "books": [
                {
                    "bookId": item["bookId"],
                    "action": "archive",
                    "reason": "fixture review",
                }
                for item in export["existingBooks"]
            ],
        }
        manifest = assemble_manual_memory_manifest(
            export,
            parts=[part],
            existing_audit=audit,
        )
        self.assertTrue(manifest["validation"]["ok"])
        self.assertEqual(manifest["validation"]["counts"]["decisions"], 1)

        with self.assertRaises(ManualMemoryReviewError):
            assemble_manual_memory_manifest(
                export,
                parts=[{**part, "decisions": []}],
                existing_audit=audit,
            )

    def test_mutable_source_governance_and_project_catalog_are_fingerprinted(self) -> None:
        self._checkpoint("数据库迁移必须先在候选副本验证。", entry="one")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO memory_atoms(
                       id, kind, text, canonical_text, source_event_ids_json,
                       source_memory_ids_json, scope_app, scope_project,
                       confidence, quality_score, privacy_level, status,
                       created_at_ms, updated_at_ms, owner_kind, owner_id,
                       claim_key, lineage_id, claim_state, valid_from_ms
                   ) VALUES ('atom:other', 'fact', 'other', 'other', '[]', '[]', '',
                             'other-project', .9, .9, 'local', 'active', 1, 1,
                             'user', 'default', 'other', 'other', 'current', 1)"""
            )
            first = export_manual_memory_review(conn, project=PROJECT)
            self.assertNotIn("atom:other", {item["atomId"] for item in first["existingAtoms"]})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE agent_memory_sources SET disposition_reason = 'changed'"
            )
        with sqlite3.connect(self.db_path) as conn:
            second = export_manual_memory_review(conn, project=PROJECT)
            self.assertNotEqual(first["evidenceFingerprint"], second["evidenceFingerprint"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO memory_compile_state(
                       project, last_compiled_event_id, last_run_ms, pending_event_count,
                       last_bundle_hash, last_drafted_event_id, last_draft_ms,
                       last_draft_bundle_hash, last_draft_run_id
                   ) VALUES (?, 0, 1, 0, '', 0, 0, '', '')""",
                (PROJECT,),
            )
        with sqlite3.connect(self.db_path) as conn:
            third = export_manual_memory_review(conn, project=PROJECT)
            self.assertNotEqual(second["governanceFingerprint"], third["governanceFingerprint"])

    def test_timeline_requires_remembered_evidence_and_implemented_actions(self) -> None:
        self._checkpoint("今天完成候选数据库验证。", entry="one")
        with sqlite3.connect(self.db_path) as conn:
            event_id = int(conn.execute("SELECT id FROM input_events").fetchone()[0])
            conn.execute(
                """INSERT INTO memory_atoms(
                       id, kind, text, canonical_text, source_event_ids_json,
                       source_memory_ids_json, scope_app, scope_project,
                       confidence, quality_score, privacy_level, status,
                       created_at_ms, updated_at_ms, owner_kind, owner_id,
                       claim_key, lineage_id, claim_state, valid_from_ms
                   ) VALUES ('atom:existing', 'fact', 'existing', 'existing', ?, '[]', '',
                             ?, .9, .9, 'local', 'active', 1, 1, 'user', 'default',
                             'existing', 'existing', 'current', 1)""",
                (f"[{event_id}]", PROJECT),
            )
            export = export_manual_memory_review(conn, project=PROJECT)
        item = export["inputs"][0]
        manifest = self._manifest(
            export,
            decisions=[
                {
                    "inputId": item["inputId"],
                    "decision": "not_for_memory",
                    "reasonCode": "ephemeral_activity",
                }
            ],
            atoms=[],
        )
        manifest["timelines"] = [
            {
                "date": item["date"],
                "start": "00:00",
                "end": "23:59",
                "goal": "验证候选数据库",
                "actualActions": "执行完整性检查。",
                "resultOrBlocker": "验证完成。",
                "apps": ["Codex"],
                "evidenceLogicalInputIds": [item["inputId"]],
            }
        ]
        validation = validate_manual_memory_manifest(export, manifest=manifest)
        self.assertIn(
            f"timeline_evidence_not_remembered:{item['date']}:{item['inputId']}",
            validation["errors"],
        )

        unsupported = deepcopy(manifest)
        unsupported["timelines"] = []
        unsupported["existingMemoryAudit"]["atoms"] = [
            {"atomId": atom["atomId"], "action": "keep", "reason": "keep"}
            for atom in export["existingAtoms"]
        ]
        unsupported_validation = validate_manual_memory_manifest(
            export, manifest=unsupported
        )
        self.assertTrue(
            any(
                str(error).startswith("invalid_existing_atom_action:")
                for error in unsupported_validation["errors"]
            )
        )

    def test_phrase_audit_is_complete_and_keep_requires_all_sources_remembered(self) -> None:
        self._checkpoint("候选数据库是正式激活前的验证副本。", entry="one")
        self._checkpoint("加油加油", entry="two")
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, committed_text FROM input_events ORDER BY id"
            ).fetchall()
            event_by_text = {str(row[1]): int(row[0]) for row in rows}
            stable_event = event_by_text["候选数据库是正式激活前的验证副本。"]
            noise_event = event_by_text["加油加油"]
            conn.execute(
                """INSERT INTO memory_items(
                       memory_id, kind, text, normalized_text, summary,
                       source_event_id, project, status, created_at_ms,
                       updated_at_ms, metadata_json
                   ) VALUES
                     ('phrase:term', 'phrase', '候选数据库', '候选数据库', '稳定术语',
                      ?, ?, 'active', 1, 1, '{}'),
                     ('phrase:mixed', 'phrase', '数据库验证', '数据库验证', '混合来源',
                      ?, ?, 'active', 1, 1, ?),
                     ('phrase:slogan', 'phrase', '加油', '加油', '无来源口号',
                      NULL, ?, 'active', 1, 1, '{}')""",
                (
                    stable_event,
                    PROJECT,
                    stable_event,
                    PROJECT,
                    json.dumps({"sourceEventIds": [stable_event, noise_event]}),
                    PROJECT,
                ),
            )
            export = export_manual_memory_review(conn, project=PROJECT)
        phrases = {item["memoryId"]: item for item in export["existingPhrases"]}
        self.assertEqual(
            set(phrases["phrase:mixed"]["declaredSourceEventIds"]),
            {stable_event, noise_event},
        )
        inputs = {item["text"]: item for item in export["inputs"]}
        manifest = self._manifest(
            export,
            decisions=[
                {
                    "inputId": inputs["候选数据库是正式激活前的验证副本。"]["inputId"],
                    "decision": "remember",
                    "reasonCode": "stable_term",
                },
                {
                    "inputId": inputs["加油加油"]["inputId"],
                    "decision": "not_for_memory",
                    "reasonCode": "slogan_noise",
                },
            ],
            atoms=[
                {
                    "atomId": "atom:stable-term",
                    "claimKey": "term:candidate-database",
                    "canonicalText": "候选数据库用于正式激活前的隔离验证。",
                    "kind": "fact",
                    "sourceEventIds": [stable_event],
                    "confidence": 0.95,
                    "qualityScore": 0.95,
                    "directCandidateAllowed": False,
                }
            ],
        )
        manifest["existingPhraseAudit"] = [
            {"memoryId": "phrase:term", "action": "keep", "reason": "合法术语"},
            {"memoryId": "phrase:mixed", "action": "archive", "reason": "混合排除来源"},
            {"memoryId": "phrase:slogan", "action": "archive", "reason": "无来源口号"},
        ]
        self.assertTrue(validate_manual_memory_manifest(export, manifest=manifest)["ok"])

        incomplete = deepcopy(manifest)
        incomplete["existingPhraseAudit"] = incomplete["existingPhraseAudit"][:-1]
        self.assertIn(
            "existing_phrase_audit_incomplete",
            validate_manual_memory_manifest(export, manifest=incomplete)["errors"],
        )
        mixed_keep = deepcopy(manifest)
        mixed_keep["existingPhraseAudit"][1]["action"] = "keep"
        self.assertIn(
            "kept_phrase_uses_unremembered_evidence:phrase:mixed",
            validate_manual_memory_manifest(export, manifest=mixed_keep)["errors"],
        )

    def test_shared_physical_event_must_be_remembered_by_every_logical_input(self) -> None:
        self._checkpoint("数据库迁移必须先在候选副本验证。", entry="shared")
        with sqlite3.connect(self.db_path) as conn:
            event_id = int(conn.execute("SELECT id FROM input_events").fetchone()[0])
            conn.execute(
                """INSERT INTO memory_items(
                       memory_id, kind, text, normalized_text, summary,
                       source_event_id, project, status, created_at_ms,
                       updated_at_ms, metadata_json
                   ) VALUES ('phrase:candidate-db', 'phrase', '候选数据库',
                             '候选数据库', '稳定术语', ?, ?, 'active', 1, 1, '{}')""",
                (event_id, PROJECT),
            )
            export = export_manual_memory_review(conn, project=PROJECT)

        original = dict(export["inputs"][0])
        duplicate = {
            **original,
            "inputId": "logical:shared-event-excluded",
            "sourceIds": ["source:shared-event-excluded"],
        }
        export["inputs"].append(duplicate)
        atom = {
            "atomId": "atom:candidate-database",
            "claimKey": "engineering:database.candidate-first",
            "canonicalText": "数据库变更先在隔离候选副本完成验证。",
            "kind": "durable_preference",
            "sourceEventIds": [event_id],
            "confidence": 0.96,
            "qualityScore": 0.94,
            "directCandidateAllowed": False,
        }
        manifest = self._manifest(
            export,
            decisions=[
                {
                    "inputId": original["inputId"],
                    "decision": "remember",
                    "reasonCode": "durable_database_safety",
                },
                {
                    "inputId": duplicate["inputId"],
                    "decision": "not_for_memory",
                    "reasonCode": "duplicate_excluded_source",
                },
            ],
            atoms=[atom],
        )
        manifest["books"] = [
            {
                "bookId": "book:candidate-database",
                "bookKey": "candidate-database",
                "title": "候选数据库治理",
                "summary": "数据库迁移使用隔离候选并保留可追溯来源。",
                "sourceEventIds": [event_id],
                "memoryAtomIds": [atom["atomId"]],
            }
        ]
        manifest["timelines"] = [
            {
                "date": original["date"],
                "start": "00:00",
                "end": "23:59",
                "goal": "验证候选数据库",
                "actualActions": "执行数据库完整性检查。",
                "resultOrBlocker": "候选副本验证已经完成。",
                "apps": ["Codex"],
                "evidenceLogicalInputIds": [original["inputId"]],
            }
        ]
        manifest["existingPhraseAudit"] = [
            {
                "memoryId": "phrase:candidate-db",
                "action": "keep",
                "reason": "稳定术语",
            }
        ]

        validation = validate_manual_memory_manifest(export, manifest=manifest)

        self.assertFalse(validation["ok"])
        self.assertIn(
            "atom_uses_unremembered_evidence:atom:candidate-database",
            validation["errors"],
        )
        self.assertIn(
            "book_uses_unremembered_evidence:book:candidate-database",
            validation["errors"],
        )
        self.assertIn(
            f"timeline_uses_unremembered_evidence:{original['date']}:{original['inputId']}",
            validation["errors"],
        )
        self.assertIn(
            "kept_phrase_uses_unremembered_evidence:phrase:candidate-db",
            validation["errors"],
        )

    def _checkpoint(self, text: str, *, entry: str) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id=f"entry:{entry}",
            turn_id=f"turn:{entry}",
            text=text,
            created_at_ms=(
                1_700_000_000_000 + sum(ord(character) for character in entry) * 86_400_000
            ),
        )

    @staticmethod
    def _manifest(
        export: dict[str, object],
        *,
        decisions: list[dict[str, object]],
        atoms: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "schemaVersion": MANUAL_MEMORY_MANIFEST_SCHEMA_VERSION,
            "project": PROJECT,
            "evidenceFingerprint": export["evidenceFingerprint"],
            "memoryCatalogFingerprint": export["memoryCatalogFingerprint"],
            "governanceFingerprint": export["governanceFingerprint"],
            "decisions": decisions,
            "atoms": atoms,
            "books": [],
            "supersedes": [],
            "existingMemoryAudit": {
                "atoms": [
                    {
                        "atomId": item["atomId"],
                        "action": "archive",
                        "reason": "fixture review",
                    }
                    for item in export["existingAtoms"]
                ],
                "books": [
                    {
                        "bookId": item["bookId"],
                        "action": "archive",
                        "reason": "fixture review",
                    }
                    for item in export["existingBooks"]
                ],
            },
            "existingPhraseAudit": [
                {
                    "memoryId": item["memoryId"],
                    "action": "archive",
                    "reason": "fixture review",
                }
                for item in export.get("existingPhrases", [])
            ],
        }


if __name__ == "__main__":
    unittest.main()
