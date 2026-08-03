from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.debug_server import DebugImeService, DebugServerConfig
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.management_service import page_request
from rag_ime.memory_evidence_admission import (
    evidence_is_admitted,
    transition_evidence_admission,
)
from rag_ime.models import InputEvent


APP = "com.apple.TextEdit"
PROJECT = "personal-agent-workbench"
TEXT = "用户要求个人记忆必须保留原始愿景。"


def _capture_metadata() -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.input-capture.v2",
        "captureId": "capture:admission:1",
        "transactionId": "transaction:admission:1",
        "sequence": 1,
        "channel": "input_method",
        "boundaryKind": "host_return",
        "boundaryConfidence": "strong",
        "nativeCompositionBefore": False,
        "rimeHandled": False,
        "hostForwarded": True,
        "modifiedReturn": False,
        "finalCommitted": True,
        "controllerEpoch": 1,
        "focusEpoch": 1,
        "appBundleId": APP,
        "fieldIdentitySha256": hashlib.sha256(b"field:admission").hexdigest(),
        "privacyRevision": "foreground-privacy.v1",
        "occurredStartMs": 100,
        "occurredEndMs": 120,
        "contentSha256": hashlib.sha256(TEXT.encode("utf-8")).hexdigest(),
        "captureSource": "text_input_client",
        "fallbackReason": "",
        "fieldContextChars": len(TEXT),
        "imeBufferChars": len(TEXT),
        "selectionRule": "final_committed_segment",
    }


class MemoryEvidenceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-evidence-admission-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.event_ref, self.receipt = self.core.record_event_with_capture_receipt(
            InputEvent(
                event_id=None,
                created_at_ms=1_000,
                source="squirrel_input_segment",
                committed_text=TEXT,
                privacy_disposition="allowed",
                app=APP,
                project=PROJECT,
                capture_metadata=_capture_metadata(),
            )
        )
        self.event_id = int(self.event_ref.removeprefix("event:"))
        self.evidence_id = str(self.receipt["evidenceId"])
        self.service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                project=PROJECT,
                seed_if_empty=False,
            )
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def test_one_predicate_controls_count_list_and_references(self) -> None:
        self.assertEqual(self.receipt["evidenceState"], "candidate")
        self.assertEqual(self._evidence_ids(), set())
        self.assertEqual(
            self.service.management.memory_summary()["memoryEvidenceCount"],
            0,
        )
        for kind, identifier in (
            ("evidence", self.evidence_id),
            ("event", str(self.event_id)),
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                self.service.management.memory_reference(kind, identifier)

        with self.core._connect() as conn:
            result = transition_evidence_admission(
                conn,
                self.evidence_id,
                new_state="admitted",
                reason_code="luna_personal_memory_confirmed",
                actor_kind="luna",
                created_at_ms=1_100,
                run_id="luna:test:1",
            )
            self.assertTrue(result["changed"])
            self.assertTrue(evidence_is_admitted(conn, self.evidence_id))
            compatibility = conn.execute(
                """
                SELECT disposition, disposition_reason
                FROM agent_memory_sources WHERE input_event_id = ?
                """,
                (self.event_id,),
            ).fetchone()
            self.assertEqual(
                tuple(compatibility),
                ("remember", "luna_personal_memory_confirmed"),
            )

        self.assertEqual(self._evidence_ids(), {self.evidence_id})
        self.assertEqual(
            self.service.management.memory_summary()["memoryEvidenceCount"],
            1,
        )
        self.assertEqual(
            self.service.management.memory_reference(
                "evidence", self.evidence_id
            )["ref"]["id"],
            self.evidence_id,
        )
        self.assertEqual(
            self.service.management.memory_reference(
                "event", str(self.event_id)
            )["ref"]["id"],
            str(self.event_id),
        )

    def test_forget_and_restore_change_canonical_evidence_and_rewind_review(self) -> None:
        with self.core._connect() as conn:
            transition_evidence_admission(
                conn,
                self.evidence_id,
                new_state="admitted",
                reason_code="luna_personal_memory_confirmed",
                actor_kind="luna",
                created_at_ms=1_100,
            )
            source = conn.execute(
                """
                SELECT source_id, created_at_ms
                FROM agent_memory_sources
                WHERE input_event_id = ?
                """,
                (self.event_id,),
            ).fetchone()
            source_id = str(source["source_id"])
            conn.execute(
                """
                INSERT INTO memory_curation_cursors(
                    owner_kind, owner_id, project, lane,
                    last_source_created_at_ms, last_source_id,
                    next_due_at_ms, status, updated_at_ms
                ) VALUES ('user', 'default', ?, 'daily', ?, ?, 999999,
                          'idle', 1100)
                """,
                (PROJECT, int(source["created_at_ms"]), source_id),
            )

        forgotten = self.service.management.memory_source_disposition(
            {
                "evidenceId": self.evidence_id,
                "disposition": "not_for_memory",
            }
        )
        self.assertEqual(forgotten["evidence"]["admissionState"], "forgotten")
        self.assertEqual(forgotten["source"]["disposition"], "not_for_memory")
        self.assertEqual(self._evidence_ids(), set())
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.management.memory_reference("event", str(self.event_id))

        restored = self.service.management.memory_source_disposition(
            {
                "sourceId": source_id,
                "disposition": "pending",
            }
        )
        self.assertEqual(restored["evidenceId"], self.evidence_id)
        self.assertEqual(restored["evidence"]["admissionState"], "needs_review")
        self.assertEqual(restored["source"]["disposition"], "needs_review")
        self.assertEqual(self._evidence_ids(), set())

        with self.core._connect() as conn:
            evidence = conn.execute(
                """
                SELECT admission_state, admission_reason, forgotten_at_ms
                FROM agent_memory_evidence
                WHERE evidence_id = ?
                """,
                (self.evidence_id,),
            ).fetchone()
            receipt = conn.execute(
                """
                SELECT evidence_state, evidence_reason
                FROM input_capture_receipts
                WHERE evidence_id = ?
                """,
                (self.evidence_id,),
            ).fetchone()
            cursor = conn.execute(
                """
                SELECT last_source_created_at_ms, last_source_id,
                       next_due_at_ms, status
                FROM memory_curation_cursors
                WHERE owner_kind = 'user' AND owner_id = 'default'
                  AND project = ? AND lane = 'daily'
                """,
                (PROJECT,),
            ).fetchone()
            evidence_events = conn.execute(
                """
                SELECT new_state, reason_code, actor_kind
                FROM memory_evidence_admission_events
                WHERE evidence_id = ?
                ORDER BY created_at_ms, event_id
                """,
                (self.evidence_id,),
            ).fetchall()
            source_events = conn.execute(
                """
                SELECT new_disposition, reason_code, actor_kind
                FROM memory_source_disposition_events
                WHERE source_id = ?
                ORDER BY created_at_ms, event_id
                """,
                (source_id,),
            ).fetchall()

        self.assertEqual(
            tuple(evidence),
            ("needs_review", "user_restored_for_review", None),
        )
        self.assertEqual(
            tuple(receipt),
            ("needs_review", "user_restored_for_review"),
        )
        self.assertEqual(tuple(cursor), (0, "", 0, "idle"))
        self.assertEqual(
            [tuple(row) for row in evidence_events[-2:]],
            [
                ("forgotten", "user_forgotten", "user"),
                ("needs_review", "user_restored_for_review", "user"),
            ],
        )
        self.assertEqual(
            [tuple(row) for row in source_events[-2:]],
            [
                ("not_for_memory", "user_forgotten", "user"),
                ("needs_review", "user_restored_for_review", "user"),
            ],
        )

    def test_rejected_evidence_is_not_resurrected_by_an_atom_link(self) -> None:
        with self.core._connect() as conn:
            transition_evidence_admission(
                conn,
                self.evidence_id,
                new_state="admitted",
                reason_code="luna_personal_memory_confirmed",
                actor_kind="luna",
                created_at_ms=1_100,
            )
        session = AgentSessionStore(self.db_path).create(
            title="Evidence link fixture",
            created_at_ms=1_150,
        )
        proposal_id = "proposal:evidence-admission-test"
        atom_id = "atom:evidence-admission-test"
        payload_sha = hashlib.sha256(b"proposal:evidence-admission-test").hexdigest()
        with sqlite3.connect(self.db_path) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO memory_governance_proposals(
                    proposal_id, session_id, project, operation,
                    memory_kind, proposed_text, reason, evidence_ids_json,
                    evidence_snapshot_json, action_json, payload_sha256,
                    idempotency_key, status, created_at_ms, expires_at_ms,
                    updated_at_ms
                ) VALUES (?, ?, ?, 'remember_preview', 'requirement', ?,
                          'fixture', ?, '{}', '{}', ?, ?, 'preview', ?, ?, ?)
                """,
                (
                    proposal_id,
                    session["id"],
                    PROJECT,
                    TEXT,
                    json.dumps([self.evidence_id]),
                    payload_sha,
                    "evidence-admission-test",
                    1_150,
                    2_150,
                    1_150,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, source_event_ids_json,
                    scope_project, privacy_level, status,
                    created_at_ms, updated_at_ms
                ) VALUES (?, 'requirement', ?, ?, ?, ?, 'local', 'active',
                          1150, 1150)
                """,
                (atom_id, TEXT, TEXT, json.dumps([self.event_id]), PROJECT),
            )
            conn.execute(
                """
                INSERT INTO memory_atom_evidence_links(
                    memory_atom_id, evidence_id, proposal_id, relation,
                    content_sha256, provenance_json, created_at_ms
                ) VALUES (?, ?, ?, 'supports', ?, '{}', 1150)
                """,
                (
                    atom_id,
                    self.evidence_id,
                    proposal_id,
                    hashlib.sha256(TEXT.encode("utf-8")).hexdigest(),
                ),
            )
        with self.core._connect() as conn:
            transition_evidence_admission(
                conn,
                self.evidence_id,
                new_state="rejected",
                reason_code="user_rejected_memory_candidate",
                actor_kind="user",
                created_at_ms=1_200,
            )

        atom = self.service.management.memory_reference("atom", atom_id)
        self.assertEqual(atom["evidenceRefs"], [])
        atom_page = self.service.management.memory_page(
            "atoms",
            page_request({"project": PROJECT, "limit": 20}),
        )
        projected_atom = next(
            item for item in atom_page["items"] if item["id"] == atom_id
        )
        self.assertEqual(projected_atom["evidenceRefs"], [])
        self.assertEqual(self._evidence_ids(), set())
        for kind, identifier in (
            ("evidence", self.evidence_id),
            ("event", str(self.event_id)),
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                self.service.management.memory_reference(kind, identifier)

    def test_deleting_a_session_keeps_source_disposition_and_capture_history(self) -> None:
        session = AgentSessionStore(self.db_path).create(
            title="Disposable source session",
            created_at_ms=1_300,
        )
        source_id = "source:session-retention"
        digest = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.db_path) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO agent_memory_sources(
                    source_id, session_id, pi_entry_id, input_event_id,
                    source_role, canonical_text_sha256, created_at_ms,
                    source_kind, trust_class, disposition, metadata_json
                ) VALUES (?, ?, 'entry:retention', ?, 'user', ?, 1300,
                          'user_final', 'user_claim', 'needs_review', '{}')
                """,
                (source_id, session["id"], self.event_id, digest),
            )
            conn.execute(
                """
                INSERT INTO memory_source_disposition_events(
                    event_id, source_id, previous_disposition, new_disposition,
                    reason_code, actor_kind, created_at_ms, metadata_json
                ) VALUES ('disposition:retention', ?, 'pending', 'needs_review',
                          'legacy_requires_review', 'rule', 1300, '{}')
                """,
                (source_id,),
            )
            conn.execute(
                """
                INSERT INTO memory_capture_hints(
                    hint_id, source_id, kind, normalized_claim, scope, reason,
                    status, created_at_ms, updated_at_ms
                ) VALUES ('hint:retention', ?, 'decision', ?, 'user',
                          'future reuse', 'active', 1300, 1300)
                """,
                (source_id, TEXT),
            )
            conn.execute("DELETE FROM agent_sessions WHERE id = ?", (session["id"],))
            retained = (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_memory_sources WHERE source_id = ?",
                    (source_id,),
                ).fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM memory_source_disposition_events WHERE source_id = ?",
                    (source_id,),
                ).fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM memory_capture_hints WHERE source_id = ?",
                    (source_id,),
                ).fetchone()[0],
            )
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()

        self.assertEqual(retained, (1, 1, 1))
        self.assertEqual(foreign_key_errors, [])

    def test_reset_clears_canonical_evidence_without_foreign_key_damage(self) -> None:
        self.core.reset()

        with self.core._connect() as conn:
            counts = tuple(
                int(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in (
                    "input_events",
                    "input_capture_receipts",
                    "agent_memory_sources",
                    "agent_memory_evidence",
                    "memory_evidence_input_event_links",
                    "memory_evidence_admission_events",
                )
            )
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()

        self.assertEqual(counts, (0, 0, 0, 0, 0, 0))
        self.assertEqual(foreign_key_errors, [])

    def _evidence_ids(self) -> set[str]:
        page = self.service.management.memory_page(
            "evidence",
            page_request({"project": PROJECT, "limit": 20}),
        )
        return {str(item["id"]) for item in page["items"]}


if __name__ == "__main__":
    unittest.main()
