from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.historical_memory_catalog_audit import (
    build_historical_catalog_audit_packet,
    quarantine_historical_catalog_audit_atoms,
)
from rag_ime.memory_book_compiler import (
    apply_stored_memory_book_run,
    memory_book_plan_from_compile_output,
    rollback_memory_book_run,
    store_memory_book_plan,
)
from rag_ime.memory_evidence_admission import transition_evidence_admission
from rag_ime.models import InputEvent
from rag_ime.personal_memory_books import personal_memory_book_projection_status
from rag_ime.personal_memory_luna_evaluation import atom_first_memory_state_summary


class PersonalMemoryApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-personal-apply-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.sessions = AgentSessionStore(self.db_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_cross_batch_atoms_build_book_and_rollback_reprojects_it(self) -> None:
        first_event, first_evidence = self._evidence(
            1,
            "我长期偏好简洁自然的回答。",
        )
        first_run = self._apply_atom(
            ordinal=1,
            event_id=first_event,
            evidence_id=first_evidence,
            claim_key="user:answer-style",
            canonical="用户长期偏好简洁自然的回答。",
        )
        with self.core._connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_books WHERE knowledge_domain = 'personal_memory' AND status = 'active'"
                ).fetchone()[0],
                0,
            )
        singleton_state = atom_first_memory_state_summary(self.db_path)
        self.assertTrue(singleton_state["allGovernedCurrentAtomsHaveLegalLineage"])
        self.assertEqual(
            singleton_state["bookProjection"]["unbookedGovernedAtomCount"],
            1,
        )
        self.assertTrue(singleton_state["bookProjection"]["inSync"])

        second_event, second_evidence = self._evidence(
            2,
            "我也希望提问过程不要太像机器话术。",
        )
        second_run = self._apply_atom(
            ordinal=2,
            event_id=second_event,
            evidence_id=second_evidence,
            claim_key="user:question-style",
            canonical="用户希望提问自然，不使用机器化话术。",
        )

        with self.core._connect() as conn:
            atoms = conn.execute(
                """
                SELECT id, knowledge_domain, scope_kind, scope_id, visibility,
                       scope_mode, scope_project, scope_app
                FROM memory_atoms
                WHERE claim_state = 'current' AND status = 'active'
                ORDER BY claim_key
                """
            ).fetchall()
            links = conn.execute(
                """
                SELECT memory_atom_id, evidence_id, relation
                FROM memory_atom_evidence_links
                ORDER BY evidence_id
                """
            ).fetchall()
            proposals = conn.execute(
                "SELECT status, operation FROM memory_governance_proposals ORDER BY created_at_ms"
            ).fetchall()
            book = conn.execute(
                """
                SELECT status, summary, memory_atom_ids_json, knowledge_domain,
                       scope_mode, project, app
                FROM memory_books
                WHERE knowledge_domain = 'personal_memory' AND status = 'active'
                """
            ).fetchone()

        self.assertEqual(len(atoms), 2)
        for atom in atoms:
            self.assertEqual(tuple(atom)[1:], (
                "personal_memory", "user", "default", "private",
                "authoritative", "", "",
            ))
        self.assertEqual(
            [(row["evidence_id"], row["relation"]) for row in links],
            [(first_evidence, "supports"), (second_evidence, "supports")],
        )
        self.assertEqual(
            [(row["status"], row["operation"]) for row in proposals],
            [("applied", "remember_preview"), ("applied", "remember_preview")],
        )
        self.assertIsNotNone(book)
        self.assertEqual(book["knowledge_domain"], "personal_memory")
        self.assertEqual(book["scope_mode"], "authoritative")
        self.assertEqual((book["project"], book["app"]), ("", ""))
        self.assertIn("简洁自然", book["summary"])
        self.assertIn("机器化话术", book["summary"])
        self.assertEqual(len(json.loads(book["memory_atom_ids_json"])), 2)
        with self.core._connect() as conn:
            projection_status = personal_memory_book_projection_status(conn)
        self.assertTrue(projection_status["inSync"])
        self.assertEqual(projection_status["currentAtomCount"], 2)
        self.assertEqual(projection_status["activeBookCount"], 1)
        self.assertEqual(projection_status["unbookedAtomCount"], 0)

        with self.core._connect() as conn:
            rollback_memory_book_run(conn, run_id=second_run)
            archived = conn.execute(
                """
                SELECT status, archive_reason
                FROM memory_books
                WHERE knowledge_domain = 'personal_memory'
                """
            ).fetchone()
            remaining_links = conn.execute(
                "SELECT evidence_id FROM memory_atom_evidence_links ORDER BY evidence_id"
            ).fetchall()
            remaining_proposals = conn.execute(
                "SELECT proposal_id FROM memory_governance_proposals"
            ).fetchall()
            evidence_states = conn.execute(
                """
                SELECT evidence_id, admission_state
                FROM agent_memory_evidence
                WHERE evidence_id IN (?, ?)
                ORDER BY evidence_id
                """,
                (first_evidence, second_evidence),
            ).fetchall()
            rollback_projection_status = personal_memory_book_projection_status(conn)
        self.assertEqual(tuple(archived), ("archived", "membership_below_two"))
        self.assertEqual([row["evidence_id"] for row in remaining_links], [first_evidence])
        self.assertEqual(len(remaining_proposals), 1)
        self.assertEqual(
            {row["evidence_id"]: row["admission_state"] for row in evidence_states},
            {first_evidence: "admitted", second_evidence: "candidate"},
        )
        self.assertTrue(rollback_projection_status["inSync"])
        self.assertEqual(rollback_projection_status["currentAtomCount"], 1)
        self.assertEqual(rollback_projection_status["activeBookCount"], 0)
        self.assertEqual(rollback_projection_status["historicalBookCount"], 1)
        self.assertEqual(rollback_projection_status["unbookedAtomCount"], 1)
        self.assertNotEqual(first_run, second_run)

    def test_projector_folds_redirected_groups_and_drops_retired_members(self) -> None:
        from rag_ime.memory_book_compiler import _apply_memory_book_merge
        from rag_ime.personal_memory_books import project_personal_memory_books

        for ordinal, text in enumerate(
            [
                "用户希望回答简洁自然。",
                "用户希望解释有具体例子。",
                "用户希望提问过程自然。",
                "用户希望追问紧扣当前问题。",
            ],
            start=1,
        ):
            event_id, evidence_id = self._evidence(ordinal, text)
            self._apply_atom(
                ordinal=ordinal,
                event_id=event_id,
                evidence_id=evidence_id,
                claim_key=f"user:projector:{ordinal}",
                canonical=text,
            )

        with self.core._connect() as conn:
            conn.execute("DELETE FROM memory_atom_tags")
            for tag, members in (
                ("回答风格", [1, 2]),
                ("提问风格", [3, 4]),
            ):
                tag_id = conn.execute(
                    "INSERT INTO memory_tags(tag, normalized_tag, created_at_ms, updated_at_ms) "
                    "VALUES (?, ?, 1, 1)",
                    (tag, tag),
                ).lastrowid
                for ordinal in members:
                    conn.execute(
                        "INSERT INTO memory_atom_tags(memory_atom_id, tag_id) VALUES (?, ?)",
                        (f"atom:personal:{ordinal}", str(tag_id)),
                    )
            project_personal_memory_books(conn, current_ms=10_000)
            books = {
                str(row["title"]): dict(row)
                for row in conn.execute(
                    "SELECT * FROM memory_books WHERE status = 'active'"
                ).fetchall()
            }
            target = books["回答风格"]
            source = books["提问风格"]
            _apply_memory_book_merge(
                conn,
                {
                    "targetBookId": target["book_id"],
                    "sourceBookIds": [source["book_id"]],
                    "reason": "controlled projector regression",
                },
            )
            project_personal_memory_books(conn, current_ms=11_000)
            merged = conn.execute(
                "SELECT memory_atom_ids_json, summary, metadata_json FROM memory_books WHERE book_id = ?",
                (target["book_id"],),
            ).fetchone()
            self.assertEqual(
                set(json.loads(merged["memory_atom_ids_json"])),
                {f"atom:personal:{ordinal}" for ordinal in range(1, 5)},
            )
            self.assertIn(source["book_id"], json.loads(merged["metadata_json"])["mergedSourceBookIds"])
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM memory_books WHERE book_id = ?",
                    (source["book_id"],),
                ).fetchone()[0],
                "superseded",
            )
            self.assertTrue(personal_memory_book_projection_status(conn)["inSync"])

            conn.execute(
                "UPDATE memory_atoms SET status = 'retracted', claim_state = 'retracted' "
                "WHERE id = 'atom:personal:1'"
            )
            project_personal_memory_books(conn, current_ms=12_000)
            retired = conn.execute(
                "SELECT memory_atom_ids_json, summary FROM memory_books WHERE book_id = ?",
                (target["book_id"],),
            ).fetchone()
            self.assertNotIn("atom:personal:1", json.loads(retired["memory_atom_ids_json"]))
            self.assertNotIn("用户希望回答简洁自然。", retired["summary"])
            self.assertTrue(personal_memory_book_projection_status(conn)["inSync"])

    def test_catalog_audit_quarantines_derived_memory_but_keeps_evidence(self) -> None:
        first_event, first_evidence = self._evidence(
            1,
            "我长期偏好简洁自然的回答。",
        )
        self._apply_atom(
            ordinal=1,
            event_id=first_event,
            evidence_id=first_evidence,
            claim_key="user:answer-style",
            canonical="用户长期偏好简洁自然的回答。",
        )
        second_event, second_evidence = self._evidence(
            2,
            "我也希望提问过程不要太像机器话术。",
        )
        self._apply_atom(
            ordinal=2,
            event_id=second_event,
            evidence_id=second_evidence,
            claim_key="user:question-style",
            canonical="用户希望提问自然，不使用机器化话术。",
        )
        packet = build_historical_catalog_audit_packet(
            self.db_path,
            project="personal-agent-workbench",
        )
        rejected = next(
            item for item in packet["atoms"] if "简洁自然" in str(item["text"])
        )
        output = {
            "v": 1,
            "ok": 0,
            "catalogDigest": packet["catalogDigest"],
            "checkedAtomRefs": [item["ref"] for item in packet["atoms"]],
            "checkedBookRefs": [item["ref"] for item in packet["books"]],
            "findings": [
                {
                    "entity": "atom",
                    "ref": rejected["ref"],
                    "code": "unsupported",
                    "relatedRefs": list(rejected["evidenceRefs"]),
                }
            ],
            "errors": [],
        }

        repair = quarantine_historical_catalog_audit_atoms(
            self.db_path,
            project="personal-agent-workbench",
            audit_output=output,
            preverified_schema=True,
        )

        self.assertEqual(repair["quarantinedAtomCount"], 1)
        self.assertEqual(repair["remainingAtomCount"], 1)
        with self.core._connect() as conn:
            current_atoms = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM memory_atoms
                    WHERE status IN ('active', 'approved')
                      AND claim_state = 'current'
                    """
                ).fetchone()[0]
            )
            evidence_states = {
                str(row["evidence_id"]): str(row["admission_state"])
                for row in conn.execute(
                    """
                    SELECT evidence_id, admission_state
                    FROM agent_memory_evidence
                    WHERE evidence_id IN (?, ?)
                    """,
                    (first_evidence, second_evidence),
                ).fetchall()
            }
            quarantine_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_scope_quarantine
                    WHERE reason_code = 'historical_catalog_audit_rejected_atom'
                    """
                ).fetchone()[0]
            )
        self.assertEqual(current_atoms, 1)
        self.assertEqual(
            evidence_states,
            {first_evidence: "admitted", second_evidence: "admitted"},
        )
        self.assertEqual(quarantine_count, 1)

    def test_catalog_audit_rejects_orphaned_short_evidence_without_deleting_it(self) -> None:
        event_id, evidence_id = self._evidence(
            1,
            "蓝色是我长期保留的界面偏好。",
        )
        self._apply_atom(
            ordinal=1,
            event_id=event_id,
            evidence_id=evidence_id,
            claim_key="user:color-style",
            canonical="用户长期偏好蓝色界面。",
        )
        # Simulate an admitted legacy row from before the durable-signal gate.
        # The catalog repair must demote the short Evidence, not erase history.
        short_text = "蓝色。"
        with self.core._connect() as conn:
            conn.execute(
                """
                UPDATE agent_memory_evidence
                SET content_text = ?, content_sha256 = ?
                WHERE evidence_id = ?
                """,
                (
                    short_text,
                    hashlib.sha256(short_text.encode()).hexdigest(),
                    evidence_id,
                ),
            )
        packet = build_historical_catalog_audit_packet(
            self.db_path,
            project="personal-agent-workbench",
        )
        atom = packet["atoms"][0]
        output = {
            "v": 1,
            "ok": 0,
            "catalogDigest": packet["catalogDigest"],
            "checkedAtomRefs": [item["ref"] for item in packet["atoms"]],
            "checkedBookRefs": [item["ref"] for item in packet["books"]],
            "findings": [
                {
                    "entity": "atom",
                    "ref": atom["ref"],
                    "code": "short_fragment",
                    "relatedRefs": list(atom["evidenceRefs"]),
                }
            ],
            "errors": [],
        }

        repair = quarantine_historical_catalog_audit_atoms(
            self.db_path,
            project="personal-agent-workbench",
            audit_output=output,
            preverified_schema=True,
        )

        self.assertEqual(repair["rejectedOrphanedShortEvidenceCount"], 1)
        with self.core._connect() as conn:
            row = conn.execute(
                """
                SELECT content_text, admission_state, admission_reason
                FROM agent_memory_evidence
                WHERE evidence_id = ?
                """,
                (evidence_id,),
            ).fetchone()
        self.assertEqual(
            tuple(row),
            (
                short_text,
                "rejected",
                "catalog_audit_orphaned_short_fragment",
            ),
        )

    def _evidence(self, ordinal: int, text: str) -> tuple[int, str]:
        capture_id = f"capture:personal-apply:{ordinal}"
        metadata = {
            "schemaVersion": "rag-ime.input-capture.v2",
            "captureId": capture_id,
            "transactionId": f"transaction:personal-apply:{ordinal}",
            "sequence": ordinal,
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
            "appBundleId": "com.apple.TextEdit",
            "fieldIdentitySha256": hashlib.sha256(f"field:{ordinal}".encode()).hexdigest(),
            "privacyRevision": "foreground-privacy.v1",
            "occurredStartMs": ordinal * 1_000,
            "occurredEndMs": ordinal * 1_000 + 20,
            "contentSha256": hashlib.sha256(text.encode()).hexdigest(),
            "captureSource": "text_input_client",
            "fallbackReason": "",
            "fieldContextChars": len(text),
            "imeBufferChars": len(text),
            "selectionRule": "final_committed_segment",
        }
        event_ref, receipt = self.core.record_event_with_capture_receipt(
            InputEvent(
                event_id=None,
                created_at_ms=ordinal * 1_000,
                source="squirrel_input_segment",
                committed_text=text,
                privacy_disposition="allowed",
                app="com.apple.TextEdit",
                project="personal-agent-workbench",
                capture_metadata=metadata,
            )
        )
        event_id = int(event_ref.removeprefix("event:"))
        evidence_id = str(receipt["evidenceId"])
        with self.core._connect() as conn:
            transition_evidence_admission(
                conn,
                evidence_id,
                new_state="admitted",
                reason_code="luna_personal_memory_confirmed",
                actor_kind="luna",
                created_at_ms=ordinal * 1_000 + 100,
                run_id=f"memory-run:{ordinal}",
            )
        return event_id, evidence_id

    def _apply_atom(
        self,
        *,
        ordinal: int,
        event_id: int,
        evidence_id: str,
        claim_key: str,
        canonical: str,
    ) -> str:
        run_id = f"memory-run:{ordinal}"
        session = self.sessions.create(
            title=f"Memory curation {ordinal}",
            created_at_ms=ordinal * 1_000 + 50,
        )
        with self.core._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_curation_model_runs(
                    run_id, session_id, provider, model_id, thinking_level,
                    frozen_input_sha256, state, created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'openai-codex', 'gpt-5.6-luna', 'max', ?,
                          'completed', ?, ?)
                """,
                (
                    run_id,
                    session["id"],
                    hashlib.sha256(run_id.encode()).hexdigest(),
                    ordinal * 1_000 + 50,
                    ordinal * 1_000 + 50,
                ),
            )
            source = conn.execute(
                "SELECT source_id FROM agent_memory_sources WHERE input_event_id = ?",
                (event_id,),
            ).fetchone()
            compile_output = {
                "memoryAtoms": [
                    {
                        "atomId": f"atom:personal:{ordinal}",
                        "operation": "create",
                        "kind": "durable_preference",
                        "claimKey": claim_key,
                        "canonicalText": canonical,
                        "sourceEventIds": [event_id],
                        "evidenceIds": [evidence_id],
                        "tags": ["沟通风格"],
                        "confidence": 0.97,
                        "qualityScore": 0.97,
                        "project": "",
                        "app": "",
                        "ownerKind": "user",
                        "ownerId": "default",
                        "knowledgeDomain": "personal_memory",
                        "scopeKind": "user",
                        "scopeId": "default",
                        "visibility": "private",
                        "authorizationRevision": "memory-atom-v2",
                        "bindingId": "personal-memory:user:default",
                        "scopeMode": "authoritative",
                        "curationRunId": run_id,
                    }
                ],
                "topicBooks": [],
            }
            bundle = {
                "bundleHash": hashlib.sha256(f"bundle:{ordinal}".encode()).hexdigest(),
                "legalSourceEventIds": [event_id],
                "inputs": [
                    {
                        "sourceRef": "S1",
                        "sourceEventIds": [event_id],
                        "createdAtMs": ordinal * 1_000,
                        "text": canonical,
                    }
                ],
                "cursor": {"fromEventId": event_id - 1, "toEventId": event_id},
            }
            plan = memory_book_plan_from_compile_output(
                compile_output,
                project="personal-agent-workbench",
                provider="openai-codex",
                model="gpt-5.6-luna",
                source_bundle=bundle,
                owner_kind="user",
                owner_id="default",
                run_kind="daily_curation",
            )
            plan["runId"] = run_id
            plan["metadata"] = {
                **dict(plan.get("metadata") or {}),
                "ownerKind": "user",
                "ownerId": "default",
                "project": "personal-agent-workbench",
                "runKind": "daily_curation",
                "sourceIds": [str(source["source_id"])],
            }
            store_memory_book_plan(conn, plan)
            apply_stored_memory_book_run(conn, run_id=run_id)
        return run_id


if __name__ == "__main__":
    unittest.main()
