from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.hybrid_rag_models import HybridRagQuery, MemoryHit
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.knowledge_scope import record_shadow_diff, session_knowledge_caller
from rag_ime.memory_projectors import AgentMemoryProjector
from rag_ime.personal_context import AgentMemoryEvidenceStore
from rag_ime.retrieval_docs import rebuild_retrieval_docs


class RoomKnowledgeScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-knowledge-scope-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.store = AgentMemorySourceStore(self.db_path, project="scope-test")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_room_binding_overrides_default_owner_and_removed_binding_quarantines(self) -> None:
        active = self.sessions.create(title="active", created_at_ms=1)
        removed = self.sessions.create(title="removed", created_at_ms=2)
        with self._connect() as conn:
            self._bind(conn, "room:a", "participant:a", str(active["id"]), "active")
            self._bind(conn, "room:b", "participant:b", str(removed["id"]), "removed")

        written = self.store.checkpoint_user_message(
            session_id=str(active["id"]), pi_entry_id="entry:a", turn_id="turn:a",
            text="只有 A 会话能看到的证据", created_at_ms=10,
        )
        blocked = self.store.checkpoint_user_message(
            session_id=str(removed["id"]), pi_entry_id="entry:b", turn_id="turn:b",
            text="已移除成员不能写入", created_at_ms=11,
        )

        self.assertEqual((written["source"]["ownerKind"], written["source"]["ownerId"]),
                         ("session", str(active["id"])))
        self.assertEqual(written["source"]["scopeMode"], "authoritative")
        self.assertEqual(written["source"]["knowledgeDomain"], "participant_private")
        self.assertEqual(blocked["status"], "quarantined")
        with self._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_scope_quarantine").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 1)

    def test_no_room_binding_preserves_legacy_behavior(self) -> None:
        session = self.sessions.create(title="legacy", created_at_ms=1)
        result = self.store.checkpoint_user_message(
            session_id=str(session["id"]), pi_entry_id="legacy:1", turn_id="turn:1",
            text="普通 Agent 仍按旧规则工作", created_at_ms=10,
        )
        self.assertEqual((result["source"]["ownerKind"], result["source"]["ownerId"]),
                         ("user", "default"))
        self.assertEqual(result["source"]["scopeMode"], "legacy")

    def test_room_evidence_uses_server_binding_and_rejects_claimed_other_room(self) -> None:
        session = self.sessions.create(title="room", created_at_ms=1)
        with self._connect() as conn:
            self._bind(conn, "room:a", "participant:a", str(session["id"]), "active")
        evidence = AgentMemoryEvidenceStore(self.db_path, project="scope-test")
        accepted = evidence.record_room_event(
            room_id="room:a", event_id="event:a", session_id=str(session["id"]),
            role_id="role", text="Room A 已确认的事件", accepted=True,
        )
        rejected = evidence.record_room_event(
            room_id="room:b", event_id="event:b", session_id=str(session["id"]),
            role_id="role", text="模型声称来自另一个 Room", accepted=True,
        )
        self.assertEqual((accepted["evidence"]["ownerKind"], accepted["evidence"]["ownerId"]),
                         ("room", "room:a"))
        self.assertEqual(accepted["evidence"]["scopeMode"], "authoritative")
        self.assertEqual(rejected["status"], "quarantined")

    def test_candidate_generation_fences_cross_room_and_cross_session(self) -> None:
        session_a = self.sessions.create(title="a", created_at_ms=1)
        session_b = self.sessions.create(title="b", created_at_ms=2)
        with self._connect() as conn:
            self._bind(conn, "room:a", "participant:a", str(session_a["id"]), "active")
            self._bind(conn, "room:b", "participant:b", str(session_b["id"]), "active")
            caller_a = session_knowledge_caller(conn, str(session_a["id"]))
            self._doc(conn, "legacy", "user", "default", "legacy", "legacy", "", "公共关键词")
            self._doc(conn, "a", "session", str(session_a["id"]), "authoritative", "session", str(session_a["id"]), "A关键词")
            self._doc(conn, "b", "session", str(session_b["id"]), "authoritative", "session", str(session_b["id"]), "B关键词")
            result = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(query_text="关键词", project="scope-test", top_k=10,
                               visible_owners=(("user", "default"), ("session", str(session_a["id"])), ("session", str(session_b["id"]))),
                               knowledge_caller=caller_a),
            )
            legacy = retrieve_hybrid_rag_candidates(
                conn, HybridRagQuery(query_text="关键词", project="scope-test", top_k=10,
                                     visible_owners=(("user", "default"), ("session", str(session_a["id"])))),
            )
        self.assertIn("A关键词", [hit["text"] for hit in result["hits"]])
        self.assertNotIn("B关键词", [hit["text"] for hit in result["hits"]])
        self.assertNotIn("A关键词", [hit["text"] for hit in legacy["hits"]])

    def test_personal_profile_is_visible_without_opening_room_private_scope(self) -> None:
        with self._connect() as conn:
            self._doc(
                conn,
                "profile",
                "user",
                "default",
                "authoritative",
                "user",
                "default",
                "个人偏好关键词",
            )
            conn.execute(
                """
                UPDATE memory_books
                SET knowledge_domain = 'user_profile_preference',
                    visibility = 'private'
                WHERE book_id = 'profile'
                """
            )
            conn.execute(
                """
                UPDATE memory_retrieval_docs
                SET knowledge_domain = 'user_profile_preference',
                    visibility = 'private'
                WHERE doc_id = 'book:profile'
                """
            )
            self._doc(
                conn,
                "participant",
                "session",
                "session:a",
                "authoritative",
                "session",
                "session:a",
                "Room 私有关键词",
            )
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="关键词",
                    project="scope-test",
                    top_k=10,
                    visible_owners=(
                        ("user", "default"),
                        ("session", "session:a"),
                    ),
                ),
            )

        texts = [hit["text"] for hit in payload["hits"]]
        self.assertIn("个人偏好关键词", texts)
        self.assertNotIn("Room 私有关键词", texts)

    def test_context_projector_is_second_scope_defense_and_shadow_is_diff_only(self) -> None:
        session = self.sessions.create(title="a", created_at_ms=1)
        with self._connect() as conn:
            self._bind(conn, "room:a", "participant:a", str(session["id"]), "active")
            caller = session_knowledge_caller(conn, str(session["id"]))
            before_outbox = conn.execute("SELECT COUNT(*) FROM memory_projection_outbox").fetchone()[0]
            diff = record_shadow_diff(conn, query="q", primary_refs=("a",), shadow_refs=("a", "b"))
            after_outbox = conn.execute("SELECT COUNT(*) FROM memory_projection_outbox").fetchone()[0]
        allowed = self._hit("allowed", {"scopeMode": "authoritative", "knowledgeDomain": "participant_private", "scopeKind": "session", "scopeId": str(session["id"])})
        denied = self._hit("denied", {"scopeMode": "authoritative", "knowledgeDomain": "participant_private", "scopeKind": "session", "scopeId": "other"})
        block = AgentMemoryProjector().project([allowed, denied], project="scope-test", query="q", knowledge_caller=caller).block
        self.assertIn("allowed", block)
        self.assertNotIn("denied", block)
        self.assertEqual(diff["addedRefs"], ["b"])
        self.assertEqual(before_outbox, after_outbox)

    def test_projection_quarantines_incomplete_authoritative_scope(self) -> None:
        session = self.sessions.create(title="legacy", created_at_ms=1)
        result = self.store.checkpoint_user_message(
            session_id=str(session["id"]), pi_entry_id="projection:1", turn_id="turn:1",
            text="不完整作用域不应该进入检索索引", created_at_ms=10,
        )
        event_id = result["source"]["inputEventId"]
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET kind='note', status='active', scope_mode='authoritative', knowledge_domain='participant_private', scope_kind='session', scope_id='', visibility='private', authorization_revision='rev', binding_id='binding' WHERE source_event_id=?",
                (event_id,),
            )
            rebuild_retrieval_docs(conn, project="scope-test", include_legacy_items=True)
            projected = conn.execute("SELECT COUNT(*) FROM memory_retrieval_docs WHERE source_id IN (SELECT memory_id FROM memory_items WHERE source_event_id=?)", (event_id,)).fetchone()[0]
            quarantined = conn.execute("SELECT reason_code FROM knowledge_scope_quarantine WHERE source_table='memory_items'").fetchone()[0]
        self.assertEqual(projected, 0)
        self.assertEqual(quarantined, "invalid_authoritative_scope")

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return closing(conn)

    @staticmethod
    def _bind(conn, room_id: str, participant_id: str, session_id: str, status: str) -> None:
        conn.execute("INSERT OR IGNORE INTO agent_rooms(id,title,routing_policy,status,room_file,created_at_ms,updated_at_ms) VALUES (?,?,'manual_mentions','active','room.md',1,1)", (room_id, room_id))
        conn.execute("INSERT INTO agent_room_participants(id,room_id,session_id,role_id,role_version,display_name,participant_status,ordinal,created_at_ms) VALUES (?,?,?,'role','v1',?,?,1,1)", (participant_id, room_id, session_id, participant_id, status))
        conn.commit()

    @staticmethod
    def _doc(conn, suffix: str, owner_kind: str, owner_id: str, mode: str, scope_kind: str, scope_id: str, text: str) -> None:
        knowledge_domain = "legacy" if mode == "legacy" else "participant_private"
        visibility = "legacy" if mode == "legacy" else "private"
        authorization_revision = "" if mode == "legacy" else "rev"
        binding_id = "" if mode == "legacy" else "binding"
        conn.execute(
            """INSERT INTO memory_books(
                   book_id, book_type, book_key, title, summary, normalized_text,
                   project, memory_atom_ids_json, status, created_at_ms,
                   updated_at_ms, metadata_json, owner_kind, owner_id,
                   knowledge_domain, scope_kind, scope_id, visibility,
                   authorization_revision, binding_id, scope_mode
               ) VALUES (?, 'topic', ?, ?, ?, ?, 'scope-test', '[]', 'active',
                         1, 1, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                suffix,
                suffix,
                text,
                text,
                text,
                owner_kind,
                owner_id,
                knowledge_domain,
                scope_kind,
                scope_id,
                visibility,
                authorization_revision,
                binding_id,
                mode,
            ),
        )
        conn.execute("INSERT INTO memory_retrieval_docs(doc_id,doc_type,source_id,raw_text,project,owner_kind,owner_id,knowledge_domain,scope_kind,scope_id,visibility,authorization_revision,binding_id,scope_mode,status,updated_at_ms,metadata_json) VALUES (?,?,?,?,'scope-test',?,?,?,?,?,?,?,?,?,'active',1,'{}')",
                     (f"book:{suffix}", "book", suffix, text, owner_kind, owner_id, knowledge_domain, scope_kind, scope_id, visibility, authorization_revision, binding_id, mode))
        rowid = conn.execute("SELECT rowid FROM memory_retrieval_docs WHERE doc_id=?", (f"book:{suffix}",)).fetchone()[0]
        conn.execute("INSERT INTO memory_retrieval_docs_fts(rowid,raw_text) VALUES (?,?)", (rowid, text))
        conn.commit()

    @staticmethod
    def _hit(text: str, metadata: dict[str, object]) -> MemoryHit:
        return MemoryHit(hit_id=text, doc_id=text, doc_type="book", source_id=text, text=text,
                         surface_hints=(), source_type="book", source_lane="bm25_raw",
                         score=1.0, confidence=1.0, tags=(), memory_ids=(), atom_ids=(),
                         book_ids=(text,), evidence_event_ids=(), evidence_preview=text,
                         metadata=metadata)


if __name__ == "__main__":
    unittest.main()
