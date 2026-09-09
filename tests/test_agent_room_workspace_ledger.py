from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.rooms.workspace_ledger import (
    RoomWorkspaceLedgerConflict,
    RoomWorkspaceLedgerError,
    RoomWorkspaceLedgerStore,
)
from rag_ime.rooms.store import AgentRoomStore
from rag_ime.agent_sessions import AgentSessionStore


class RoomWorkspaceLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-workspace-ledger-")
        self.db_path = Path(self.tmp.name) / "room.sqlite"
        self.store = RoomWorkspaceLedgerStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _reserve(
        self,
        *,
        root_id: str = "root:a",
        task_id: str = "task:a",
        base_commit: str = "base-a",
        suffix: str = "a",
        now_ms: int = 1,
    ) -> tuple[dict[str, object], bool]:
        return self.store.reserve_binding(
            room_id="room:a",
            root_id=root_id,
            task_id=task_id,
            work_item_id=f"work-item:{suffix}",
            dispatch_id=f"dispatch:{suffix}",
            requirement_revision="sha256:" + "1" * 64,
            acceptance_aliases=["acceptance:one"],
            participant_id=f"participant:{suffix}",
            session_id=f"session:{suffix}",
            repository_id="a" * 64,
            base_root=str(Path(self.tmp.name) / "project"),
            base_commit=base_commit,
            workspace_root=str(Path(self.tmp.name) / "worktrees" / suffix / "project"),
            workspace_policy="isolated_writable",
            creation_reason=f"implement requirement {suffix}",
            now_ms=now_ms,
        )

    def _deliver(
        self,
        binding_id: str,
        *,
        suffix: str,
        now_ms: int,
        patch_sha256: str | None = None,
    ) -> None:
        self.store.mark_materialized(
            binding_id,
            workspace_snapshot_sha256="b" * 64,
            actor_ref=f"participant:{suffix}",
            now_ms=now_ms,
        )
        self.store.record_work_started(
            binding_id,
            dispatch_id=f"dispatch:{suffix}",
            actor_ref=f"participant:{suffix}",
            now_ms=now_ms + 1,
        )
        self.store.record_delivery(
            binding_id,
            delivery_revision="sha256:" + suffix[0] * 64,
            delivery_head="base-a",
            workspace_snapshot_sha256="c" * 64,
            patch_sha256=patch_sha256 or suffix[0] * 64,
            manifest_sha256="f" * 64,
            artifacts=["README.md"],
            verification_refs=["test:focused"],
            residual_risks=[],
            actor_ref=f"participant:{suffix}",
            now_ms=now_ms + 2,
        )
        binding = self.store.binding(binding_id)
        self.store.record_source_lease_revoked(
            binding_id,
            delivery_revision="sha256:" + suffix[0] * 64,
            workspace_snapshot_sha256="c" * 64,
            patch_sha256=patch_sha256 or suffix[0] * 64,
            patch_artifact_path=str(
                Path(self.tmp.name) / f"sealed-{binding_id[-8:]}.patch"
            ),
            patch_artifact_size=1,
            owner_session_id=str(binding["currentOwnerSessionId"]),
            revoked_policy_sha256="9" * 64,
            workspace_content_sha256="8" * 64,
            changed_files=["README.md"],
            actor_ref="system:workspace-coordinator",
            now_ms=now_ms + 2,
        )

    @staticmethod
    def _quiescence_receipt(
        request: dict[str, object],
    ) -> dict[str, object]:
        revision = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "schemaVersion": "wisdom-weasel.room-workspace-writer-quiescence.v1",
            "receiptRevision": f"test:{revision}",
            **request,
            "foregroundMutatingInvocations": {"known": True, "activeCount": 0},
            "backgroundWork": {"known": True, "activeCount": 0},
            "managedPiTurn": {
                "known": True,
                "settled": True,
                "sessionId": str(request.get("ownerSessionId") or ""),
                "dispatchId": str(request.get("dispatchId") or ""),
            },
        }

    def _record_abandonment_quiescence(
        self,
        binding_id: str,
        *,
        workspace_content_sha256: str,
        now_ms: int,
    ) -> None:
        binding = self.store.binding(binding_id)
        request = {
            "workspaceBindingId": binding_id,
            "rootId": binding["rootId"],
            "taskId": binding["taskId"],
            "dispatchId": binding["dispatchId"],
            "ownerSessionId": binding["currentOwnerSessionId"],
            "workspaceContentSha256": workspace_content_sha256,
            "revokedPolicySha256": "9" * 64,
        }
        self.store.record_abandonment_quiescence(
            binding_id,
            workspace_content_sha256=workspace_content_sha256,
            revoked_policy_sha256="9" * 64,
            receipt=self._quiescence_receipt(request),
            actor_ref="participant:facilitator",
            now_ms=now_ms,
        )

    def test_lifecycle_is_ordered_idempotent_and_survives_reopen(self) -> None:
        binding, created = self._reserve()
        self.assertTrue(created)
        replay, replay_created = self._reserve(now_ms=2)
        self.assertFalse(replay_created)
        self.assertEqual(replay["workspaceBindingId"], binding["workspaceBindingId"])

        binding_id = str(binding["workspaceBindingId"])
        self._deliver(binding_id, suffix="d", now_ms=3)
        started = self.store.begin_integration(
            binding_id,
            integration_ref="integration:a",
            patch_sha256="d" * 64,
            target_before_snapshot_sha256="e" * 64,
            actor_ref="participant:facilitator",
            now_ms=6,
        )
        self.assertEqual(started["workspaceLifecycleState"], "integration_started")

        # A crash retry observes a different current target, but must keep the
        # first target-before receipt instead of rewriting history.
        retried = self.store.begin_integration(
            binding_id,
            integration_ref="integration:a",
            patch_sha256="d" * 64,
            target_before_snapshot_sha256="f" * 64,
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        self.assertEqual(retried["lastEventSequence"], started["lastEventSequence"])
        start_payload = self.store.integration_start_payload(binding_id)
        self.assertIsNotNone(start_payload)
        assert start_payload is not None
        self.assertEqual(start_payload["integrationRef"], "integration:a")
        self.assertEqual(start_payload["deliveryHead"], "base-a")
        self.assertEqual(start_payload["deliveryManifestSha256"], "f" * 64)
        self.assertEqual(
            start_payload["deliveryRevision"],
            "sha256:" + "d" * 64,
        )
        self.assertEqual(start_payload["deliverySnapshotSha256"], "c" * 64)
        self.assertRegex(str(start_payload["sourceLeaseReceiptId"]), r"^room-workspace-event:")
        self.assertRegex(str(start_payload["sourceLeaseReceiptSha256"]), r"^[0-9a-f]{64}$")
        self.assertEqual(start_payload["patchSha256"], "d" * 64)
        self.assertEqual(start_payload["targetBeforeSnapshotSha256"], "e" * 64)

        self.store.record_target_applied(
            binding_id,
            integration_ref="integration:a",
            patch_sha256="d" * 64,
            target_before_snapshot_sha256="e" * 64,
            target_after_snapshot_sha256="f" * 64,
            target_snapshot_provider=lambda: "f" * 64,
            actor_ref="participant:facilitator",
            now_ms=8,
        )

        self.store.record_integrated(
            binding_id,
            integration_ref="integration:a",
            patch_sha256="d" * 64,
            integrated_revision="git:base-a:snapshot:" + "f" * 64,
            integrated_snapshot_sha256="f" * 64,
            changed_files=["README.md"],
            target_snapshot_provider=lambda: "f" * 64,
            actor_ref="participant:facilitator",
            now_ms=9,
        )
        with self.assertRaisesRegex(
            RoomWorkspaceLedgerError,
            "removal authorization",
        ):
            self.store.record_cleanup(
                binding_id,
                result="cleaned",
                reason="forged four-receipt cleanup chain",
                actor_ref="participant:facilitator",
                now_ms=10,
            )
        source = self.store.source_lease_receipt(binding_id)
        integrated = self.store.integrated_receipt(binding_id)
        assert source and integrated
        binding = self.store.binding(binding_id)
        writer_request = {
            "workspaceBindingId": binding_id,
            "rootId": binding["rootId"],
            "taskId": binding["taskId"],
            "dispatchId": binding["dispatchId"],
            "deliveryRevision": binding["deliveryRevision"],
            "ownerSessionId": binding["currentOwnerSessionId"],
            "sourceLeaseReceiptId": source["eventId"],
            "sourceLeaseReceiptSha256": source["payloadSha256"],
            "integratedReceiptId": integrated["eventId"],
            "integratedReceiptSha256": integrated["payloadSha256"],
        }
        self.store.record_writer_quiescence(
            binding_id,
            receipt=self._quiescence_receipt(writer_request),
            actor_ref="participant:facilitator",
            now_ms=10,
        )
        self.store.record_quarantined(
            binding_id,
            quarantined_workspace_root="/tmp/quarantine-a",
            workspace_content_sha256="8" * 64,
            target_snapshot_sha256="f" * 64,
            actor_ref="participant:facilitator",
            now_ms=10,
        )
        self.store.authorize_cleanup_removal(
            binding_id,
            quarantined_workspace_root="/tmp/quarantine-a",
            vault_workspace_root="/tmp/vault-a",
            workspace_content_sha256="8" * 64,
            target_snapshot_sha256="f" * 64,
            actor_ref="participant:facilitator",
            now_ms=10,
        )
        removal = self.store.cleanup_removal_authorization_receipt(binding_id)
        assert removal is not None

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            authorization_row = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE binding_id=? AND event_kind='cleanup_removal_authorized'
                """,
                (binding_id,),
            ).fetchone()
        assert authorization_row is not None
        authorization_payload_json = str(authorization_row["payload_json"])
        authorization_payload = json.loads(authorization_payload_json)
        authorization_payload["writerQuiescenceReceiptId"] = (
            "room-workspace-event:" + "0" * 32
        )
        tampered_authorization_json = json.dumps(
            authorization_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_json=? WHERE event_id=?",
                (tampered_authorization_json, authorization_row["event_id"]),
            )
        with self.subTest(case="cleanup authorization payload tamper"):
            with self.assertRaisesRegex(
                RoomWorkspaceLedgerConflict,
                "integrity",
            ):
                self.store.assert_cleanup_removal_authority(
                    binding_id,
                    receipt_id=str(removal["eventId"]),
                    receipt_sha256=str(removal["payloadSha256"]),
                    quarantined_workspace_root="/tmp/quarantine-a",
                    vault_workspace_root="/tmp/vault-a",
                    workspace_content_sha256="8" * 64,
                    target_snapshot_sha256="f" * 64,
                )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_json=? WHERE event_id=?",
                (authorization_payload_json, authorization_row["event_id"]),
            )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_sha256=? WHERE event_id=?",
                ("0" * 64, authorization_row["event_id"]),
            )
        with self.subTest(case="event row payload hash mismatch"):
            with self.assertRaisesRegex(
                RoomWorkspaceLedgerConflict,
                "integrity",
            ):
                self.store.cleanup_removal_authorization_receipt(binding_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_sha256=? WHERE event_id=?",
                (authorization_row["payload_sha256"], authorization_row["event_id"]),
            )

        mismatched_event_id = "room-workspace-event:" + "1" * 32
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET event_id=? WHERE event_id=?",
                (mismatched_event_id, authorization_row["event_id"]),
            )
        with self.subTest(case="event row identity mismatch"):
            with self.assertRaisesRegex(
                RoomWorkspaceLedgerConflict,
                "integrity",
            ):
                self.store.cleanup_removal_authorization_receipt(binding_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET event_id=? WHERE event_id=?",
                (authorization_row["event_id"], mismatched_event_id),
            )

        duplicate_sequence = int(authorization_row["sequence"]) + 1
        duplicate_idempotency_key = (
            str(authorization_row["idempotency_key"]) + ":duplicate"
        )
        duplicate_digest = hashlib.sha256(
            "\0".join(
                (
                    "room-workspace-event",
                    binding_id,
                    str(duplicate_sequence),
                    "cleanup_removal_authorized",
                    duplicate_idempotency_key,
                )
            ).encode("utf-8")
        ).hexdigest()
        duplicate_event_id = f"room-workspace-event:{duplicate_digest[:32]}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO room_workspace_events(
                    event_id, binding_id, sequence, event_kind, idempotency_key,
                    actor_ref, payload_sha256, payload_json, created_at_ms
                ) VALUES (?, ?, ?, 'cleanup_removal_authorized', ?, ?, ?, ?, ?)
                """,
                (
                    duplicate_event_id,
                    binding_id,
                    duplicate_sequence,
                    duplicate_idempotency_key,
                    authorization_row["actor_ref"],
                    authorization_row["payload_sha256"],
                    authorization_row["payload_json"],
                    authorization_row["created_at_ms"],
                ),
            )
            conn.execute(
                "UPDATE room_workspace_bindings SET last_event_sequence=? WHERE binding_id=?",
                (duplicate_sequence, binding_id),
            )
        with self.subTest(case="duplicate exact cleanup authority"):
            with self.assertRaisesRegex(
                RoomWorkspaceLedgerConflict,
                "duplicate",
            ):
                self.store.assert_cleanup_removal_authority(
                    binding_id,
                    receipt_id=duplicate_event_id,
                    receipt_sha256=str(authorization_row["payload_sha256"]),
                    quarantined_workspace_root="/tmp/quarantine-a",
                    vault_workspace_root="/tmp/vault-a",
                    workspace_content_sha256="8" * 64,
                    target_snapshot_sha256="f" * 64,
                )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM room_workspace_events WHERE event_id=?",
                (duplicate_event_id,),
            )
            conn.execute(
                "UPDATE room_workspace_bindings SET last_event_sequence=? WHERE binding_id=?",
                (authorization_row["sequence"], binding_id),
            )

        self.store.record_vaulted(
            binding_id,
            removal_authorization_receipt_id=str(removal["eventId"]),
            removal_authorization_receipt_sha256=str(removal["payloadSha256"]),
            quarantined_workspace_root="/tmp/quarantine-a",
            vault_workspace_root="/tmp/vault-a",
            authorized_workspace_content_sha256="8" * 64,
            vault_content_sha256="7" * 64,
            target_snapshot_sha256="f" * 64,
            actor_ref="system:guarded-workspace-cleanup",
            now_ms=10,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            vault_row = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE binding_id=? AND event_kind='vaulted'
                """,
                (binding_id,),
            ).fetchone()
        assert vault_row is not None
        vault_payload_json = str(vault_row["payload_json"])
        vault_payload = json.loads(vault_payload_json)
        vault_payload["ownerSessionId"] = "session:tampered"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_json=? WHERE event_id=?",
                (
                    json.dumps(
                        vault_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    vault_row["event_id"],
                ),
            )
        with self.subTest(case="vaulted payload tamper"):
            with self.assertRaisesRegex(
                RoomWorkspaceLedgerConflict,
                "integrity",
            ):
                self.store.vault_receipt(binding_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_json=? WHERE event_id=?",
                (vault_payload_json, vault_row["event_id"]),
            )

        final = self.store.record_cleanup(
            binding_id,
            result="cleaned",
            reason="exact receipted path removed",
            actor_ref="participant:facilitator",
            now_ms=10,
            retained_workspace_root="/tmp/vault-a",
        )
        self.assertEqual(final["workspaceLifecycleState"], "cleaned")
        self.assertEqual(final["cleanupState"], "cleaned")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cleaned_row = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE binding_id=? AND event_kind='cleaned'
                """,
                (binding_id,),
            ).fetchone()
        assert cleaned_row is not None
        cleaned_payload_json = str(cleaned_row["payload_json"])
        cleaned_payload = json.loads(cleaned_payload_json)
        cleaned_payload["vaultReceiptId"] = "room-workspace-event:" + "2" * 32
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_json=? WHERE event_id=?",
                (
                    json.dumps(
                        cleaned_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    cleaned_row["event_id"],
                ),
            )
        with self.subTest(case="cleaned payload tamper"):
            with self.assertRaisesRegex(
                RoomWorkspaceLedgerConflict,
                "integrity",
            ):
                self.store.cleanup_receipt(binding_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_json=? WHERE event_id=?",
                (cleaned_payload_json, cleaned_row["event_id"]),
            )

        self.assertEqual(
            [event["eventKind"] for event in self.store.events(binding_id)],
            [
                "reserved",
                "materialized",
                "work_started",
                "delivered",
                "source_lease_revoked",
                "integration_started",
                "target_applied",
                "integrated",
                "writer_quiescent",
                "quarantined",
                "cleanup_removal_authorized",
                "vaulted",
                "cleaned",
            ],
        )

        reopened = RoomWorkspaceLedgerStore(self.db_path)
        reopened.initialize()
        self.assertEqual(
            reopened.binding(binding_id)["integratedSnapshotSha256"],
            "f" * 64,
        )
        self.assertEqual(len(reopened.events(binding_id)), 13)

    def test_one_root_pins_one_repository_baseline(self) -> None:
        self._reserve()
        with self.assertRaisesRegex(
            RoomWorkspaceLedgerConflict,
            "same repository baseline",
        ):
            self._reserve(
                task_id="task:b",
                base_commit="base-b",
                suffix="b",
                now_ms=2,
            )

    def test_target_receipts_fail_closed_when_transactional_snapshot_moves(
        self,
    ) -> None:
        binding, _ = self._reserve(task_id="task:cas", suffix="c")
        binding_id = str(binding["workspaceBindingId"])
        self._deliver(
            binding_id,
            suffix="d",
            now_ms=3,
            patch_sha256="1" * 64,
        )
        self.store.begin_integration(
            binding_id,
            integration_ref="integration:cas",
            patch_sha256="1" * 64,
            target_before_snapshot_sha256="2" * 64,
            actor_ref="participant:facilitator",
            now_ms=6,
        )
        with self.assertRaisesRegex(
            RoomWorkspaceLedgerConflict,
            "changed before target-applied receipt",
        ):
            self.store.record_target_applied(
                binding_id,
                integration_ref="integration:cas",
                patch_sha256="1" * 64,
                target_before_snapshot_sha256="2" * 64,
                target_after_snapshot_sha256="3" * 64,
                target_snapshot_provider=lambda: "4" * 64,
                actor_ref="participant:facilitator",
                now_ms=7,
            )
        self.assertNotIn(
            "target_applied",
            [event["eventKind"] for event in self.store.events(binding_id)],
        )

        self.store.record_target_applied(
            binding_id,
            integration_ref="integration:cas",
            patch_sha256="1" * 64,
            target_before_snapshot_sha256="2" * 64,
            target_after_snapshot_sha256="3" * 64,
            target_snapshot_provider=lambda: "3" * 64,
            actor_ref="participant:facilitator",
            now_ms=8,
        )
        with self.assertRaisesRegex(
            RoomWorkspaceLedgerConflict,
            "changed before its durable receipt",
        ):
            self.store.record_integrated(
                binding_id,
                integration_ref="integration:cas",
                patch_sha256="1" * 64,
                integrated_revision="git:base-a:snapshot:" + "3" * 64,
                integrated_snapshot_sha256="3" * 64,
                changed_files=["README.md"],
                target_snapshot_provider=lambda: "4" * 64,
                actor_ref="participant:facilitator",
                now_ms=9,
            )
        self.assertEqual(
            self.store.binding(binding_id)["workspaceLifecycleState"],
            "integration_started",
        )
        self.assertNotIn(
            "integrated",
            [event["eventKind"] for event in self.store.events(binding_id)],
        )

    def test_only_one_work_item_holds_the_root_integration_lease(self) -> None:
        first, _ = self._reserve(task_id="task:a", suffix="a", now_ms=1)
        second, _ = self._reserve(task_id="task:b", suffix="b", now_ms=2)
        first_id = str(first["workspaceBindingId"])
        second_id = str(second["workspaceBindingId"])
        self._deliver(first_id, suffix="d", now_ms=3, patch_sha256="1" * 64)
        self._deliver(second_id, suffix="e", now_ms=6, patch_sha256="3" * 64)
        self.store.begin_integration(
            first_id,
            integration_ref="integration:a",
            patch_sha256="1" * 64,
            target_before_snapshot_sha256="2" * 64,
            actor_ref="participant:facilitator",
            now_ms=9,
        )
        with self.assertRaisesRegex(
            RoomWorkspaceLedgerConflict,
            "owns the Root integration workspace",
        ):
            self.store.begin_integration(
                second_id,
                integration_ref="integration:b",
                patch_sha256="3" * 64,
                target_before_snapshot_sha256="2" * 64,
                actor_ref="participant:facilitator",
                now_ms=10,
            )

        self.store.record_conflict(
            first_id,
            integration_ref="integration:a",
            patch_sha256="1" * 64,
            reason="synthetic conflict",
            changed_files=["README.md"],
            actor_ref="participant:facilitator",
            now_ms=11,
        )
        second_started = self.store.begin_integration(
            second_id,
            integration_ref="integration:b",
            patch_sha256="3" * 64,
            target_before_snapshot_sha256="2" * 64,
            actor_ref="participant:facilitator",
            now_ms=12,
        )
        self.assertEqual(second_started["workspaceLifecycleState"], "integration_started")

    def test_failure_is_retained_until_receipted_retry_or_abandonment(self) -> None:
        binding, _ = self._reserve()
        binding_id = str(binding["workspaceBindingId"])
        self.store.mark_materialized(
            binding_id,
            workspace_snapshot_sha256="b" * 64,
            actor_ref="participant:a",
            now_ms=2,
        )
        retained = self.store.retain(
            binding_id,
            reason="worker process exited",
            state="failed",
            workspace_snapshot_sha256="c" * 64,
            actor_ref="system:recovery",
            now_ms=3,
        )
        self.assertTrue(retained["attentionRequired"])
        self.assertEqual(retained["cleanupState"], "retained")
        retried = self.store.retry_binding(
            binding_id,
            participant_id="participant:b",
            participant_ref="@worker-b",
            session_id="session:b",
            workspace_snapshot_sha256="c" * 64,
            reason="retry after inspection",
            actor_ref="participant:facilitator",
            now_ms=4,
        )
        self.assertFalse(retried["attentionRequired"])
        self.assertEqual(retried["targetParticipantRef"], "@worker-b")
        with self.assertRaisesRegex(
            RoomWorkspaceLedgerError,
            "requires an attention-state binding",
        ):
            self.store.abandon(
                binding_id,
                reason="cannot abandon an active retry",
                workspace_snapshot_sha256="c" * 64,
                acceptance_aliases=["acceptance:one"],
                actor_ref="participant:facilitator",
                now_ms=5,
            )
        self.store.retain(
            binding_id,
            reason="conflict remains after retry",
            state="conflict",
            workspace_snapshot_sha256="d" * 64,
            actor_ref="participant:facilitator",
            now_ms=6,
        )
        self._record_abandonment_quiescence(
            binding_id,
            workspace_content_sha256="d" * 64,
            now_ms=7,
        )
        abandoned = self.store.abandon(
            binding_id,
            reason="user-approved scoped abandonment",
            workspace_snapshot_sha256="d" * 64,
            acceptance_aliases=["acceptance:one"],
            actor_ref="participant:facilitator",
            now_ms=8,
        )
        self.assertEqual(abandoned["workspaceLifecycleState"], "abandoned")
        self.assertEqual(abandoned["cleanupState"], "authorized")
        self.assertIn("abandoned", [item["eventKind"] for item in self.store.events(binding_id)])

    def test_late_failure_cannot_retain_an_abandoned_and_cleaned_binding(self) -> None:
        binding, _ = self._reserve()
        binding_id = str(binding["workspaceBindingId"])
        self.store.mark_materialized(
            binding_id,
            workspace_snapshot_sha256="b" * 64,
            actor_ref="participant:a",
            now_ms=2,
        )
        self.store.retain(
            binding_id,
            reason="worker blocked",
            state="blocked",
            workspace_snapshot_sha256="c" * 64,
            actor_ref="system:runtime",
            now_ms=3,
        )
        self._record_abandonment_quiescence(
            binding_id,
            workspace_content_sha256="c" * 64,
            now_ms=4,
        )
        self.store.abandon(
            binding_id,
            reason="Facilitator abandoned the retained attempt",
            workspace_snapshot_sha256="c" * 64,
            acceptance_aliases=["acceptance:one"],
            actor_ref="participant:facilitator",
            now_ms=5,
        )
        self.store.record_quarantined(
            binding_id,
            quarantined_workspace_root="/tmp/quarantine-abandoned",
            workspace_content_sha256="c" * 64,
            target_snapshot_sha256="e" * 64,
            actor_ref="participant:facilitator",
            now_ms=6,
        )
        self.store.authorize_cleanup_removal(
            binding_id,
            quarantined_workspace_root="/tmp/quarantine-abandoned",
            vault_workspace_root="/tmp/vault-abandoned",
            workspace_content_sha256="c" * 64,
            target_snapshot_sha256="e" * 64,
            actor_ref="participant:facilitator",
            now_ms=6,
        )
        removal = self.store.cleanup_removal_authorization_receipt(binding_id)
        assert removal is not None
        self.store.record_vaulted(
            binding_id,
            removal_authorization_receipt_id=str(removal["eventId"]),
            removal_authorization_receipt_sha256=str(removal["payloadSha256"]),
            quarantined_workspace_root="/tmp/quarantine-abandoned",
            vault_workspace_root="/tmp/vault-abandoned",
            authorized_workspace_content_sha256="c" * 64,
            vault_content_sha256="d" * 64,
            target_snapshot_sha256="e" * 64,
            actor_ref="system:guarded-workspace-cleanup",
            now_ms=6,
        )
        self.store.record_cleanup(
            binding_id,
            result="cleaned",
            reason="receipted cleanup completed",
            actor_ref="participant:facilitator",
            now_ms=7,
            retained_workspace_root="/tmp/vault-abandoned",
        )

        with self.assertRaisesRegex(
            RoomWorkspaceLedgerError,
            "terminal workspace binding cannot be retained",
        ):
            self.store.retain(
                binding_id,
                reason="late runtime failure",
                state="failed",
                workspace_snapshot_sha256="c" * 64,
                actor_ref="system:runtime",
                now_ms=8,
            )
        self.assertEqual(
            self.store.binding(binding_id)["workspaceLifecycleState"],
            "cleaned",
        )

    def test_room_deletion_does_not_delete_permanent_workspace_ledger(self) -> None:
        sessions = AgentSessionStore(self.db_path)
        sessions.initialize()
        session_a = sessions.create(title="澄·今", created_at_ms=1)
        session_b = sessions.create(title="澄·远", created_at_ms=1)
        rooms = AgentRoomStore(self.db_path, room_dir=Path(self.tmp.name) / "rooms")
        rooms.initialize()
        room = rooms.create(
            title="永久台账",
            routing_policy="manual_mentions",
            participants=[
                {
                    "sessionId": str(session_a["id"]),
                    "roleId": "companion-present-v1",
                    "roleVersion": "1",
                    "displayName": "澄·今",
                    "collaborationRole": "implementer",
                },
                {
                    "sessionId": str(session_b["id"]),
                    "roleId": "companion-future-v1",
                    "roleVersion": "1",
                    "displayName": "澄·远",
                    "collaborationRole": "coordinator",
                },
            ],
            created_at_ms=1,
        )
        binding, _ = self.store.reserve_binding(
            room_id=str(room["id"]),
            root_id="root:deleted-room",
            task_id="task:deleted-room",
            work_item_id="work-item:deleted-room",
            dispatch_id="dispatch:deleted-room",
            requirement_revision="sha256:" + "1" * 64,
            acceptance_aliases=["acceptance:one"],
            participant_id="participant:a",
            session_id=str(session_a["id"]),
            repository_id="a" * 64,
            base_root=str(Path(self.tmp.name) / "project"),
            base_commit="base-a",
            workspace_root=str(Path(self.tmp.name) / "worktrees" / "deleted" / "project"),
            workspace_policy="isolated_writable",
            creation_reason="prove Room deletion independence",
            now_ms=2,
        )
        binding_id = str(binding["workspaceBindingId"])

        rooms.archive(str(room["id"]), archived=True, updated_at_ms=3)
        rooms.delete(str(room["id"]))

        self.assertEqual(self.store.binding(binding_id)["roomId"], room["id"])
        self.assertEqual(
            [item["eventKind"] for item in self.store.events(binding_id)],
            ["reserved"],
        )


if __name__ == "__main__":
    unittest.main()
