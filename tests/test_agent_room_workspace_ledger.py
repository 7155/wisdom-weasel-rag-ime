from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_workspace_ledger import (
    RoomWorkspaceLedgerConflict,
    RoomWorkspaceLedgerError,
    RoomWorkspaceLedgerStore,
)
from rag_ime.agent_rooms import AgentRoomStore
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
        self.assertEqual(
            self.store.integration_start_payload(binding_id),
            {
                "integrationRef": "integration:a",
                "deliveryHead": "base-a",
                "deliveryManifestSha256": "f" * 64,
                "deliveryRevision": "sha256:" + "d" * 64,
                "deliverySnapshotSha256": "c" * 64,
                "leaseTokenSha256": self.store.integration_start_payload(binding_id)[
                    "leaseTokenSha256"
                ],
                "patchSha256": "d" * 64,
                "targetBeforeSnapshotSha256": "e" * 64,
            },
        )

        self.store.record_integrated(
            binding_id,
            integration_ref="integration:a",
            patch_sha256="d" * 64,
            integrated_revision="git:base-a:snapshot:" + "f" * 64,
            integrated_snapshot_sha256="f" * 64,
            changed_files=["README.md"],
            actor_ref="participant:facilitator",
            now_ms=8,
        )
        final = self.store.record_cleanup(
            binding_id,
            result="cleaned",
            reason="exact receipted path removed",
            actor_ref="participant:facilitator",
            now_ms=9,
        )
        self.assertEqual(final["workspaceLifecycleState"], "cleaned")
        self.assertEqual(final["cleanupState"], "cleaned")
        self.assertEqual(
            [event["eventKind"] for event in self.store.events(binding_id)],
            [
                "reserved",
                "materialized",
                "work_started",
                "delivered",
                "integration_started",
                "integrated",
                "cleaned",
            ],
        )

        reopened = RoomWorkspaceLedgerStore(self.db_path)
        reopened.initialize()
        self.assertEqual(
            reopened.binding(binding_id)["integratedSnapshotSha256"],
            "f" * 64,
        )
        self.assertEqual(len(reopened.events(binding_id)), 7)

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
            session_id="session:b",
            workspace_snapshot_sha256="c" * 64,
            reason="retry after inspection",
            actor_ref="participant:facilitator",
            now_ms=4,
        )
        self.assertFalse(retried["attentionRequired"])
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
        abandoned = self.store.abandon(
            binding_id,
            reason="user-approved scoped abandonment",
            workspace_snapshot_sha256="d" * 64,
            acceptance_aliases=["acceptance:one"],
            actor_ref="participant:facilitator",
            now_ms=7,
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
        self.store.abandon(
            binding_id,
            reason="Facilitator abandoned the retained attempt",
            workspace_snapshot_sha256="c" * 64,
            acceptance_aliases=["acceptance:one"],
            actor_ref="participant:facilitator",
            now_ms=4,
        )
        self.store.record_cleanup(
            binding_id,
            result="cleaned",
            reason="receipted cleanup completed",
            actor_ref="participant:facilitator",
            now_ms=5,
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
                now_ms=6,
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
