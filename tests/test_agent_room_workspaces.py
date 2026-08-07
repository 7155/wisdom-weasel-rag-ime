from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from collections.abc import Mapping
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from rag_ime.agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.agent_room_workspaces import (
    RoomWorkspaceCoordinator,
    RoomWorkspaceError,
)
from rag_ime.agent_room_workspace_ledger import RoomWorkspaceLedgerError
from rag_ime import agent_room_workspace_cleanup as workspace_cleanup
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.db import latest_migration_version


class RoomWorkspaceIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-workspaces-")
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "room-tests@example.invalid")
        self._git("config", "user.name", "Room Tests")
        (self.root / "README.md").write_text("A\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-qm", "initial")

        self.sessions = AgentSessionStore(Path(self.tmp.name) / "sessions.sqlite")
        self.sessions.initialize()
        self.owner_a = self.sessions.create(
            title="Owner A",
            mode="coordinator",
            execution_mode="workspace_managed",
            tool_profile_version="control-center-v1",
            workspace_roots=[str(self.root)],
            created_at_ms=1,
        )
        self.owner_b = self.sessions.create(
            title="Owner B",
            mode="coordinator",
            execution_mode="workspace_managed",
            tool_profile_version="control-center-v1",
            workspace_roots=[str(self.root)],
            created_at_ms=2,
        )
        self.coordinator = RoomWorkspaceCoordinator(
            root_dir=Path(self.tmp.name) / "room-workspaces",
            sessions=self.sessions,
            writer_quiescence_provider=self._writer_quiescence_receipt,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _writer_quiescence_receipt(
        request: Mapping[str, object],
    ) -> Mapping[str, object]:
        revision = hashlib.sha256(
            json.dumps(
                dict(request),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schemaVersion": "wisdom-weasel.room-workspace-writer-quiescence.v1",
            "receiptRevision": f"test:{revision}",
            **dict(request),
            "foregroundMutatingInvocations": {
                "known": True,
                "activeCount": 0,
                "registryRevision": "test:foreground-settled",
            },
            "backgroundWork": {
                "known": True,
                "activeCount": 0,
                "receiptRef": "test:background-quiescent",
            },
            "managedPiTurn": {
                "known": True,
                "settled": True,
                "sessionId": str(request.get("ownerSessionId") or ""),
                "dispatchId": str(request.get("dispatchId") or ""),
                "receiptRef": "test:managed-pi-settled",
            },
        }

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_snapshot_identity_changes_for_head_and_dirty_bytes(self) -> None:
        clean_a = self.coordinator.snapshot_digest([self.root])
        (self.root / "README.md").write_text("B\n", encoding="utf-8")
        clean_dirty = self.coordinator.snapshot_digest([self.root])
        self.assertNotEqual(clean_a, clean_dirty)
        self._git("add", "README.md")
        self._git("commit", "-qm", "second")
        clean_b = self.coordinator.snapshot_digest([self.root])
        self.assertNotEqual(clean_a, clean_b)

        (self.root / "README.md").write_text("C\n", encoding="utf-8")
        dirty_post_evidence = self.coordinator.snapshot_digest([self.root])
        self.assertNotEqual(clean_b, dirty_post_evidence)
        (self.root / "untracked.bin").write_bytes(b"private-bytes")
        untracked = self.coordinator.snapshot_digest([self.root])
        self.assertNotEqual(dirty_post_evidence, untracked)

    def test_snapshot_ignores_managed_work_document_materialization(self) -> None:
        managed = self.root / "docs/agent/work/active/room_work_item"
        managed.mkdir(parents=True)
        document = managed / "room.md"
        document.write_text("进度一\n", encoding="utf-8")
        before = self.coordinator.snapshot_digest([self.root])
        document.write_text("进度二\n", encoding="utf-8")
        after = self.coordinator.snapshot_digest([self.root])
        self.assertEqual(before, after)

        user_notes = self.root / "docs/user-notes.md"
        user_notes.parent.mkdir(parents=True, exist_ok=True)
        user_notes.write_text("用户文档改动\n", encoding="utf-8")
        self.assertNotEqual(after, self.coordinator.snapshot_digest([self.root]))

    def test_repository_file_lock_serializes_independent_descriptors(
        self,
    ) -> None:
        repository_id = self.coordinator._repository_identity(self.root)
        attempting = threading.Event()
        acquired = threading.Event()

        def contend() -> None:
            attempting.set()
            with self.coordinator._repository_integration_lock(
                self.root,
                expected_repository_id=repository_id,
            ):
                acquired.set()

        contender = threading.Thread(target=contend)
        with self.coordinator._repository_integration_lock(
            self.root,
            expected_repository_id=repository_id,
        ):
            contender.start()
            self.assertTrue(attempting.wait(timeout=1))
            self.assertFalse(acquired.wait(timeout=0.2))
        self.assertTrue(acquired.wait(timeout=2))
        contender.join(timeout=2)
        self.assertFalse(contender.is_alive())

    def test_non_git_review_root_fails_closed_before_session_binding(self) -> None:
        unsupported = Path(self.tmp.name) / "not-a-repository"
        unsupported.mkdir()
        with self.assertRaises(RoomWorkspaceError):
            self.coordinator.prepare(
                root_id="root:review",
                task_id="task:review",
                target_session_id=str(self.owner_b["id"]),
                base_roots=[str(unsupported)],
                policy="read_only",
            )
        self.assertEqual(
            self.sessions.get(str(self.owner_b["id"]))["workspaceRoots"],
            [str(self.root.resolve())],
        )

    def test_read_only_prepare_binds_readonly_profile_and_restores_owner(self) -> None:
        before = self.sessions.set_runtime_policy(
            str(self.owner_b["id"]),
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="workspace_managed",
            grant_workspace_scope=True,
            allowed_tools=["workspace_read", "workspace_search"],
            project_context_enabled=True,
            pi_skills_enabled=True,
            codex_skills_enabled=False,
            workspace_roots=[str(self.root)],
        )
        prepared = self.coordinator.prepare(
            root_id="root:review",
            task_id="task:review",
            target_session_id=str(self.owner_b["id"]),
            base_roots=[str(self.root)],
            policy="read_only",
        )
        self.assertRegex(
            str(prepared["workspaceSnapshotSha256"]),
            r"^[0-9a-f]{64}$",
        )
        bound = self.sessions.get(str(self.owner_b["id"]))
        self.assertEqual(bound["executionMode"], "read_only")
        self.assertEqual(bound["toolProfileVersion"], "subagent-readonly-v1")
        self.assertEqual(bound["workspaceRoots"], [str(self.root.resolve())])
        self.coordinator.restore(
            session_id=str(self.owner_b["id"]),
            base_roots=[str(self.root)],
            restore_policy=prepared["workspaceRestorePolicy"],
        )
        restored = self.sessions.get(str(self.owner_b["id"]))
        for field in (
            "mode",
            "toolProfileVersion",
            "executionMode",
            "workspaceScopeGranted",
            "workspaceScopeSha256",
            "toolAllowlistMode",
            "allowedTools",
            "projectContextEnabled",
            "piSkillsEnabled",
            "codexSkillsEnabled",
        ):
            self.assertEqual(restored[field], before[field], field)

    def test_dirty_base_allows_isolated_work_and_preserves_user_changes(
        self,
    ) -> None:
        user_draft = self.root / "user-notes.local"
        user_draft.write_text("keep my draft\n", encoding="utf-8")
        base_snapshot = self.coordinator.snapshot_digest([self.root])

        prepared = self.coordinator.prepare(
            root_id="root:dirty-base",
            task_id="task:dirty-base",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            room_id="room:dirty-base",
            work_item_id="work-item:dirty-base",
            dispatch_id="dispatch:dirty-base",
            creation_reason="implement an independent Room work item",
        )

        self.assertTrue(prepared["workspaceBaseDirty"])
        self.assertEqual(
            prepared["workspaceBaseSnapshotSha256"],
            base_snapshot,
        )
        self.assertEqual(
            prepared["workspaceBaseDirtyPaths"],
            ["user-notes.local"],
        )
        self.assertEqual(prepared["workspaceBaseDirtyPathCount"], 1)
        reservation = self.coordinator.ledger.reservation_receipt(
            str(prepared["workspaceBindingId"])
        )
        self.assertIsNotNone(reservation)
        assert reservation is not None
        self.assertEqual(
            reservation["payload"]["baseWorkspaceSnapshotSha256"],
            base_snapshot,
        )
        self.assertEqual(
            reservation["payload"]["baseDirtyPaths"],
            ["user-notes.local"],
        )

        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "ROOM.md").write_text(
            "independent delivery\n",
            encoding="utf-8",
        )
        task = {
            "taskId": "task:dirty-base",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(
            task,
            artifacts=["ROOM.md"],
            verification_refs=["test:dirty-base-independent"],
            actor_ref="participant:worker",
            now_ms=10,
        )
        integrated = self.coordinator.integrate(task, now_ms=11)

        self.assertTrue(integrated["integrated"])
        self.assertEqual(integrated["cleanupState"], "cleaned")
        self.assertEqual(
            user_draft.read_text(encoding="utf-8"),
            "keep my draft\n",
        )
        self.assertEqual(
            (self.root / "ROOM.md").read_text(encoding="utf-8"),
            "independent delivery\n",
        )

    def test_dirty_target_overlap_retains_child_without_touching_user_change(
        self,
    ) -> None:
        (self.root / "README.md").write_text(
            "user draft\n",
            encoding="utf-8",
        )
        prepared = self.coordinator.prepare(
            root_id="root:dirty-overlap",
            task_id="task:dirty-overlap",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            room_id="room:dirty-overlap",
            work_item_id="work-item:dirty-overlap",
            dispatch_id="dispatch:dirty-overlap",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text(
            "room delivery\n",
            encoding="utf-8",
        )
        task = {
            "taskId": "task:dirty-overlap",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(
            task,
            artifacts=["README.md"],
            verification_refs=["test:dirty-overlap"],
            actor_ref="participant:worker",
            now_ms=10,
        )
        integrated = self.coordinator.integrate(task, now_ms=11)

        self.assertFalse(integrated["integrated"])
        self.assertTrue(integrated["conflict"])
        self.assertIn("overlaps existing target changes", integrated["reason"])
        self.assertEqual(integrated["workspaceLifecycleState"], "conflict")
        self.assertTrue(worktree.is_dir())
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"),
            "user draft\n",
        )
        binding = self.coordinator.ledger.binding(
            str(prepared["workspaceBindingId"])
        )
        self.assertTrue(binding["attentionRequired"])
        self.assertEqual(binding["cleanupState"], "retained")

    def test_two_isolated_writers_from_one_dirty_baseline_integrate_in_order(
        self,
    ) -> None:
        (self.root / "user-notes.local").write_text(
            "keep my draft\n",
            encoding="utf-8",
        )
        prepared_a = self.coordinator.prepare(
            root_id="root:parallel-dirty",
            task_id="task:parallel-a",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            room_id="room:parallel-dirty",
            work_item_id="work-item:parallel-a",
            dispatch_id="dispatch:parallel-a",
        )
        prepared_b = self.coordinator.prepare(
            root_id="root:parallel-dirty",
            task_id="task:parallel-b",
            target_session_id=str(self.owner_b["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            room_id="room:parallel-dirty",
            work_item_id="work-item:parallel-b",
            dispatch_id="dispatch:parallel-b",
        )
        self.assertEqual(
            prepared_a["workspaceBaseCommit"],
            prepared_b["workspaceBaseCommit"],
        )
        self.assertNotEqual(
            prepared_a["workspaceRoot"],
            prepared_b["workspaceRoot"],
        )

        worktree_a = Path(str(prepared_a["workspaceRoot"]))
        worktree_b = Path(str(prepared_b["workspaceRoot"]))
        (worktree_a / "A.md").write_text("A delivery\n", encoding="utf-8")
        (worktree_b / "B.md").write_text("B delivery\n", encoding="utf-8")
        task_a = {
            "taskId": "task:parallel-a",
            "state": "completed",
            **prepared_a,
        }
        task_b = {
            "taskId": "task:parallel-b",
            "state": "completed",
            **prepared_b,
        }
        self.coordinator.record_delivery(
            task_a,
            artifacts=["A.md"],
            verification_refs=["test:parallel-a"],
            actor_ref="participant:a",
            now_ms=10,
        )
        self.coordinator.record_delivery(
            task_b,
            artifacts=["B.md"],
            verification_refs=["test:parallel-b"],
            actor_ref="participant:b",
            now_ms=10,
        )

        integrated_a = self.coordinator.integrate(task_a, now_ms=11)
        integrated_b = self.coordinator.integrate(task_b, now_ms=12)

        self.assertTrue(integrated_a["integrated"])
        self.assertTrue(integrated_b["integrated"])
        self.assertFalse(worktree_a.exists())
        self.assertFalse(worktree_b.exists())
        self.assertEqual(
            (self.root / "user-notes.local").read_text(encoding="utf-8"),
            "keep my draft\n",
        )
        self.assertEqual(
            (self.root / "A.md").read_text(encoding="utf-8"),
            "A delivery\n",
        )
        self.assertEqual(
            (self.root / "B.md").read_text(encoding="utf-8"),
            "B delivery\n",
        )
        for prepared in (prepared_a, prepared_b):
            event_kinds = [
                event["eventKind"]
                for event in self.coordinator.ledger.events(
                    str(prepared["workspaceBindingId"])
                )
            ]
            self.assertIn("integrated", event_kinds)
            self.assertIn("cleaned", event_kinds)

    def test_isolated_handoff_rebinds_exact_root_and_integrates_claimed_root(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:handoff",
            task_id="task:handoff",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        task = {
            "taskId": "task:handoff",
            "state": "completed",
            **prepared,
        }
        started = self.coordinator.record_work_started(
            task,
            dispatch_id="dispatch:handoff",
            actor_ref="participant:a",
            now_ms=9,
        )
        self.assertEqual(started["workspaceLifecycleState"], "work_started")
        transferred = self.coordinator.transfer_isolated_ownership(
            task=task,
            source_session_id=str(self.owner_a["id"]),
            target_session_id=str(self.owner_b["id"]),
            base_roots=[str(self.root)],
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        self.assertEqual(transferred["workspaceRoot"], str(worktree))
        self.assertEqual(
            self.sessions.get(str(self.owner_a["id"]))["workspaceRoots"],
            [str(self.root.resolve())],
        )
        self.assertEqual(
            self.sessions.get(str(self.owner_b["id"]))["workspaceRoots"],
            [str(worktree.resolve())],
        )
        (worktree / "README.md").write_text("handoff\n", encoding="utf-8")
        delivery = self.coordinator.record_delivery(
            task,
            artifacts=["README.md"],
            verification_refs=["test:readme"],
            actor_ref="participant:b",
            now_ms=10,
        )
        self.assertRegex(str(delivery["deliveryRevision"]), r"^sha256:[0-9a-f]{64}$")
        revoked_session = self.sessions.get(str(self.owner_b["id"]))
        self.assertEqual(revoked_session["executionMode"], "read_only")
        self.assertEqual(
            revoked_session["workspaceRoots"],
            [str(self.root.resolve())],
        )
        source_receipt = self.coordinator.ledger.source_lease_receipt(
            str(prepared["workspaceBindingId"])
        )
        self.assertIsNotNone(source_receipt)
        assert source_receipt is not None
        source_payload = source_receipt["payload"]
        self.assertEqual(
            hashlib.sha256(
                self.coordinator._read_patch_artifact(source_payload)
            ).hexdigest(),
            source_payload["patchSha256"],
        )
        integrated = self.coordinator.integrate(task)
        self.assertTrue(integrated["integrated"])
        self.assertEqual(integrated["cleanupState"], "cleaned")
        self.assertFalse(worktree.exists())
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"),
            "handoff\n",
        )

    def test_active_isolated_task_cannot_remove_its_worktree(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:active",
            task_id="task:active",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        task = {
            "taskId": "task:active",
            "state": "active",
            **prepared,
        }

        with self.assertRaisesRegex(
            RoomWorkspaceError,
            "workspace integration requires a completed child Task",
        ):
            self.coordinator.integrate(task)

        self.assertTrue(worktree.is_dir())
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"),
            "A\n",
        )
        self.coordinator.discard(prepared)

    def test_empty_delivery_uses_sealed_artifact_and_exact_target_receipt(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:empty-delivery",
            task_id="task:empty-delivery",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        task = {
            "taskId": "task:empty-delivery",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        replayed = self.coordinator.prepare(
            root_id="root:empty-delivery",
            task_id="task:empty-delivery",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            now_ms=10,
        )
        self.assertEqual(replayed["workspaceRoot"], str(worktree))
        revoked = self.sessions.get(str(self.owner_a["id"]))
        self.assertEqual(revoked["executionMode"], "read_only")
        self.assertEqual(revoked["workspaceRoots"], [str(self.root.resolve())])
        integrated = self.coordinator.integrate(task, now_ms=11)

        self.assertTrue(integrated["integrated"])
        self.assertTrue(integrated["noChanges"])
        self.assertEqual(integrated["cleanupState"], "cleaned")
        self.assertFalse(worktree.exists())
        self.assertEqual((self.root / "README.md").read_text(), "A\n")

    def test_delivery_revoke_receipt_failure_never_regrants_child_workspace(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:delivery-revoke-crash",
            task_id="task:delivery-revoke-crash",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("delivered\n", encoding="utf-8")
        task = {
            "taskId": "task:delivery-revoke-crash",
            "state": "completed",
            **prepared,
        }
        original_record = self.coordinator.ledger.record_source_lease_revoked

        def fail_revoke_receipt(
            *args: object,
            **kwargs: object,
        ) -> dict[str, object]:
            raise RoomWorkspaceLedgerError("injected source revoke receipt failure")

        self.coordinator.ledger.record_source_lease_revoked = fail_revoke_receipt  # type: ignore[method-assign]
        try:
            with self.assertRaisesRegex(
                RoomWorkspaceError,
                "injected source revoke receipt failure",
            ):
                self.coordinator.record_delivery(task, now_ms=10)
        finally:
            self.coordinator.ledger.record_source_lease_revoked = original_record  # type: ignore[method-assign]

        failed = self.coordinator.ledger.binding(
            str(prepared["workspaceBindingId"])
        )
        self.assertTrue(failed["attentionRequired"])
        revoked = self.sessions.get(str(self.owner_a["id"]))
        self.assertEqual(revoked["executionMode"], "read_only")
        self.assertEqual(revoked["workspaceRoots"], [str(self.root.resolve())])
        with self.assertRaises(RoomWorkspaceError):
            self.coordinator.prepare(
                root_id="root:delivery-revoke-crash",
                task_id="task:delivery-revoke-crash",
                target_session_id=str(self.owner_a["id"]),
                base_roots=[str(self.root)],
                policy="isolated_writable",
                now_ms=11,
            )
        still_revoked = self.sessions.get(str(self.owner_a["id"]))
        self.assertEqual(still_revoked["executionMode"], "read_only")
        self.assertNotIn(
            str(worktree.resolve()),
            still_revoked["workspaceRoots"],
        )

    def test_startup_recovers_crash_after_delivered_before_session_revoke(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:crash-before-revoke",
            task_id="task:crash-before-revoke",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("delivered\n", encoding="utf-8")
        task = {
            "taskId": "task:crash-before-revoke",
            "state": "completed",
            **prepared,
        }
        original_revoke = self.coordinator._revoke_source_write_lease
        original_fail_closed = self.coordinator._fail_closed_delivery_seal
        self.coordinator._revoke_source_write_lease = (  # type: ignore[method-assign]
            lambda **kwargs: (_ for _ in ()).throw(SystemExit("hard crash"))
        )
        self.coordinator._fail_closed_delivery_seal = (  # type: ignore[method-assign]
            lambda **kwargs: None
        )
        try:
            with self.assertRaises(SystemExit):
                self.coordinator.record_delivery(task, now_ms=10)
        finally:
            self.coordinator._revoke_source_write_lease = original_revoke  # type: ignore[method-assign]
            self.coordinator._fail_closed_delivery_seal = original_fail_closed  # type: ignore[method-assign]
        self.assertEqual(
            self.sessions.get(str(self.owner_a["id"]))["executionMode"],
            "workspace_managed",
        )
        recovered = RoomWorkspaceCoordinator(
            root_dir=Path(self.tmp.name) / "room-workspaces",
            sessions=self.sessions,
            writer_quiescence_provider=self._writer_quiescence_receipt,
        )
        uncertain = recovered.ledger.binding(str(prepared["workspaceBindingId"]))
        self.assertEqual(
            uncertain["workspaceLifecycleState"],
            "delivery_seal_uncertain",
        )
        self.assertTrue(uncertain["attentionRequired"])
        self.assertEqual(
            self.sessions.get(str(self.owner_a["id"]))["executionMode"],
            "read_only",
        )
        sealed = recovered.resume_delivery_seal(
            binding_id=str(prepared["workspaceBindingId"]),
            resume_ref="recovery:crash-before-revoke",
            actor_ref="participant:facilitator",
            now_ms=11,
        )
        self.assertTrue(sealed["sourceWriteLeaseRevoked"])
        self.assertFalse(sealed["attentionRequired"])

    def test_startup_recovers_crash_after_session_revoke_before_receipt(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:crash-after-revoke",
            task_id="task:crash-after-revoke",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("delivered\n", encoding="utf-8")
        task = {
            "taskId": "task:crash-after-revoke",
            "state": "completed",
            **prepared,
        }
        original_record = self.coordinator.ledger.record_source_lease_revoked
        original_fail_closed = self.coordinator._fail_closed_delivery_seal
        self.coordinator.ledger.record_source_lease_revoked = (  # type: ignore[method-assign]
            lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit("hard crash"))
        )
        self.coordinator._fail_closed_delivery_seal = (  # type: ignore[method-assign]
            lambda **kwargs: None
        )
        try:
            with self.assertRaises(SystemExit):
                self.coordinator.record_delivery(task, now_ms=10)
        finally:
            self.coordinator.ledger.record_source_lease_revoked = original_record  # type: ignore[method-assign]
            self.coordinator._fail_closed_delivery_seal = original_fail_closed  # type: ignore[method-assign]
        recovered = RoomWorkspaceCoordinator(
            root_dir=Path(self.tmp.name) / "room-workspaces",
            sessions=self.sessions,
            writer_quiescence_provider=self._writer_quiescence_receipt,
        )
        uncertain = recovered.ledger.binding(str(prepared["workspaceBindingId"]))
        self.assertEqual(
            uncertain["workspaceLifecycleState"],
            "delivery_seal_uncertain",
        )
        self.assertTrue(uncertain["attentionRequired"])
        with self.assertRaisesRegex(RoomWorkspaceError, "explicit delivery-seal resume"):
            recovered.prepare(
                root_id="root:crash-after-revoke",
                task_id="task:crash-after-revoke",
                target_session_id=str(self.owner_a["id"]),
                base_roots=[str(self.root)],
                policy="isolated_writable",
                now_ms=11,
            )

    def test_source_lease_revocation_seals_delivery_against_late_redelivery(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:sealed-delivery",
            task_id="task:sealed-delivery",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("first delivery\n", encoding="utf-8")
        task = {
            "taskId": "task:sealed-delivery",
            "state": "completed",
            **prepared,
        }
        first = self.coordinator.record_delivery(task, now_ms=10)
        (worktree / "README.md").write_text("late redelivery\n", encoding="utf-8")

        with self.assertRaisesRegex(
            RoomWorkspaceError,
            "sealed|delivery|delivered",
        ):
            self.coordinator.record_delivery(task, now_ms=11)

        binding_id = str(prepared["workspaceBindingId"])
        binding = self.coordinator.ledger.binding(binding_id)
        self.assertEqual(binding["deliveryRevision"], first["deliveryRevision"])
        events = self.coordinator.ledger.events(binding_id)
        self.assertEqual(
            sum(event["eventKind"] == "delivered" for event in events),
            1,
        )
        self.assertEqual(
            sum(event["eventKind"] == "source_lease_revoked" for event in events),
            1,
        )
        self.assertNotIn(
            str(worktree.resolve()),
            self.sessions.get(str(self.owner_a["id"]))["workspaceRoots"],
        )

    def test_concurrent_prepare_replay_cannot_orphan_live_materialization(self) -> None:
        original_run = self.coordinator._run
        materializing = threading.Event()
        release_materialization = threading.Event()
        block_guard = threading.Lock()
        blocked_once = False

        def delayed_run(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            nonlocal blocked_once
            should_block = False
            with block_guard:
                if (
                    not blocked_once
                    and "worktree" in command
                    and "add" in command
                ):
                    blocked_once = True
                    should_block = True
            if should_block:
                materializing.set()
                if not release_materialization.wait(timeout=5):
                    raise AssertionError("timed out releasing workspace materialization")
            return original_run(command, input_bytes=input_bytes, check=check)

        self.coordinator._run = delayed_run  # type: ignore[method-assign]
        contender = RoomWorkspaceCoordinator(
            root_dir=Path(self.tmp.name) / "room-workspaces",
            sessions=self.sessions,
            writer_quiescence_provider=self._writer_quiescence_receipt,
        )
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def prepare(coordinator: RoomWorkspaceCoordinator) -> None:
            try:
                results.append(coordinator.prepare(
                    root_id="root:concurrent-prepare",
                    task_id="task:concurrent-prepare",
                    target_session_id=str(self.owner_a["id"]),
                    base_roots=[str(self.root)],
                    policy="isolated_writable",
                ))
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=prepare, args=(self.coordinator,))
        second = threading.Thread(target=prepare, args=(contender,))
        first.start()
        self.assertTrue(materializing.wait(timeout=5))
        second.start()
        second.join(timeout=0.05)
        self.assertTrue(
            second.is_alive(),
            "a replay must wait until durable materialization is complete",
        )
        release_materialization.set()
        first.join(timeout=5)
        second.join(timeout=5)
        self.coordinator._run = original_run  # type: ignore[method-assign]

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(
            results[0]["workspaceBindingId"],
            results[1]["workspaceBindingId"],
        )
        self.assertEqual(
            results[0]["workspaceRestorePolicy"],
            results[1]["workspaceRestorePolicy"],
        )
        events = self.coordinator.ledger.events(
            str(results[0]["workspaceBindingId"]),
        )
        self.assertEqual(
            [event["eventKind"] for event in events],
            ["reserved", "materialized"],
        )

    def test_independent_startup_discovery_waits_for_materialization_lease(
        self,
    ) -> None:
        original_run = self.coordinator._run
        materializing = threading.Event()
        release_materialization = threading.Event()

        def delayed_run(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            if "worktree" in command and "add" in command:
                materializing.set()
                if not release_materialization.wait(timeout=5):
                    raise AssertionError("timed out releasing materialization")
            return original_run(command, input_bytes=input_bytes, check=check)

        self.coordinator._run = delayed_run  # type: ignore[method-assign]
        prepared: list[dict[str, object]] = []
        recovered: list[RoomWorkspaceCoordinator] = []

        creator = threading.Thread(
            target=lambda: prepared.append(
                self.coordinator.prepare(
                    root_id="root:startup-discovery-race",
                    task_id="task:startup-discovery-race",
                    target_session_id=str(self.owner_a["id"]),
                    base_roots=[str(self.root)],
                    policy="isolated_writable",
                )
            )
        )
        creator.start()
        self.assertTrue(materializing.wait(timeout=5))
        scanner = threading.Thread(
            target=lambda: recovered.append(
                RoomWorkspaceCoordinator(
                    root_dir=Path(self.tmp.name) / "room-workspaces",
                    sessions=self.sessions,
                    writer_quiescence_provider=self._writer_quiescence_receipt,
                )
            )
        )
        scanner.start()
        scanner.join(timeout=0.1)
        self.assertTrue(scanner.is_alive())
        release_materialization.set()
        creator.join(timeout=5)
        scanner.join(timeout=5)
        self.coordinator._run = original_run  # type: ignore[method-assign]
        self.assertFalse(creator.is_alive())
        self.assertFalse(scanner.is_alive())
        self.assertEqual(len(prepared), 1)
        self.assertEqual(len(recovered), 1)
        binding_id = str(prepared[0]["workspaceBindingId"])
        self.assertFalse(recovered[0].ledger.binding(binding_id)["attentionRequired"])
        self.assertEqual(
            [
                event["eventKind"]
                for event in recovered[0].ledger.events(binding_id)
            ],
            ["reserved", "materialized"],
        )

    def test_retry_recovers_patch_applied_before_integration_receipt(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:crash-recovery",
            task_id="task:crash-recovery",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("recovered once\n", encoding="utf-8")
        task = {"taskId": "task:crash-recovery", "state": "completed", **prepared}
        self.coordinator.record_delivery(
            task,
            artifacts=["README.md"],
            verification_refs=["test:crash-recovery"],
            actor_ref="participant:a",
            now_ms=10,
        )

        original_record_integrated = self.coordinator.ledger.record_integrated

        def fail_before_receipt(*args: object, **kwargs: object) -> dict[str, object]:
            raise RoomWorkspaceLedgerError("injected receipt write failure")

        self.coordinator.ledger.record_integrated = fail_before_receipt  # type: ignore[method-assign]
        with self.assertRaisesRegex(RoomWorkspaceError, "injected receipt write failure"):
            self.coordinator.integrate(
                task,
                integration_ref="integration:crash-recovery",
                actor_ref="participant:facilitator",
                now_ms=11,
            )
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"),
            "recovered once\n",
        )
        self.assertTrue(worktree.is_dir())
        binding = self.coordinator.ledger.binding(str(prepared["workspaceBindingId"]))
        self.assertEqual(binding["workspaceLifecycleState"], "integration_started")

        self.coordinator.ledger.record_integrated = original_record_integrated  # type: ignore[method-assign]
        recovered = self.coordinator.integrate(
            task,
            integration_ref="integration:crash-recovery",
            actor_ref="participant:facilitator",
            now_ms=12,
        )
        self.assertTrue(recovered["integrated"])
        self.assertTrue(recovered["idempotent"])
        self.assertEqual(recovered["cleanupState"], "cleaned")
        self.assertFalse(worktree.exists())
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"),
            "recovered once\n",
        )

    def test_post_delivery_mutations_fail_before_integration_begins(self) -> None:
        (self.root / "DELETE.md").write_text("delete me\n", encoding="utf-8")
        (self.root / "binary.bin").write_bytes(b"\x00base\xff")
        self._git("add", "DELETE.md", "binary.bin")
        self._git("commit", "-qm", "add mutation fixtures")

        def mutate_tracked(worktree: Path) -> None:
            (worktree / "README.md").write_text("mutated after delivery\n", encoding="utf-8")

        def mutate_untracked(worktree: Path) -> None:
            (worktree / "surprise.txt").write_text("not delivered\n", encoding="utf-8")

        def mutate_deletion(worktree: Path) -> None:
            (worktree / "DELETE.md").unlink()

        def mutate_binary(worktree: Path) -> None:
            (worktree / "binary.bin").write_bytes(b"\x00mutated-after-delivery\xfe")

        mutations = {
            "tracked": mutate_tracked,
            "untracked": mutate_untracked,
            "deletion": mutate_deletion,
            "binary": mutate_binary,
        }
        for index, (kind, mutate) in enumerate(mutations.items(), start=1):
            with self.subTest(kind=kind):
                prepared = self.coordinator.prepare(
                    root_id=f"root:post-delivery-{kind}",
                    task_id=f"task:post-delivery-{kind}",
                    target_session_id=str(self.owner_a["id"]),
                    base_roots=[str(self.root)],
                    policy="isolated_writable",
                )
                worktree = Path(str(prepared["workspaceRoot"]))
                (worktree / "README.md").write_text(
                    f"receipted {kind}\n",
                    encoding="utf-8",
                )
                if kind == "binary":
                    (worktree / "binary.bin").write_bytes(b"\x00delivered\xfd")
                task = {
                    "taskId": f"task:post-delivery-{kind}",
                    "state": "completed",
                    **prepared,
                }
                self.coordinator.record_delivery(
                    task,
                    actor_ref="participant:a",
                    now_ms=10 + index,
                )
                base_before = self.coordinator.snapshot_digest([self.root])
                mutate(worktree)

                with self.assertRaisesRegex(
                    RoomWorkspaceError,
                    "changed after its delivery receipt",
                ):
                    self.coordinator.integrate(
                        task,
                        integration_ref=f"integration:post-delivery-{kind}",
                        actor_ref="participant:facilitator",
                        now_ms=20 + index,
                    )

                self.assertEqual(
                    self.coordinator.snapshot_digest([self.root]),
                    base_before,
                )
                self.assertTrue(worktree.is_dir())
                binding = self.coordinator.ledger.binding(
                    str(prepared["workspaceBindingId"])
                )
                self.assertEqual(binding["workspaceLifecycleState"], "delivered")
                event_kinds = [
                    event["eventKind"]
                    for event in self.coordinator.ledger.events(
                        str(prepared["workspaceBindingId"])
                    )
                ]
                self.assertNotIn("integration_started", event_kinds)
                self.assertNotIn("integrated", event_kinds)
                self.assertNotIn("cleaned", event_kinds)

    def test_source_mutation_after_integration_lease_fails_closed(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:lease-race",
            task_id="task:lease-race",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("receipted\n", encoding="utf-8")
        task = {"taskId": "task:lease-race", "state": "completed", **prepared}
        self.coordinator.record_delivery(task, now_ms=10)
        original_begin = self.coordinator.ledger.begin_integration

        def begin_then_mutate(*args: object, **kwargs: object) -> dict[str, object]:
            result = original_begin(*args, **kwargs)
            (worktree / "README.md").write_text(
                "mutated after lease\n",
                encoding="utf-8",
            )
            return result

        self.coordinator.ledger.begin_integration = begin_then_mutate  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(
                task,
                integration_ref="integration:lease-race",
                now_ms=11,
            )
        finally:
            self.coordinator.ledger.begin_integration = original_begin  # type: ignore[method-assign]

        self.assertFalse(result["integrated"])
        self.assertTrue(result["conflict"])
        self.assertEqual((self.root / "README.md").read_text(), "A\n")
        self.assertTrue(worktree.is_dir())
        self.assertEqual(
            [
                event["eventKind"]
                for event in self.coordinator.ledger.events(
                    str(prepared["workspaceBindingId"])
                )
            ][-2:],
            ["integration_started", "conflict"],
        )

    def test_source_mutation_after_patch_apply_rolls_back_target(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:apply-race",
            task_id="task:apply-race",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("receipted\n", encoding="utf-8")
        task = {"taskId": "task:apply-race", "state": "completed", **prepared}
        self.coordinator.record_delivery(task, now_ms=10)
        original_run = self.coordinator._run
        mutated = False

        def apply_then_mutate(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            nonlocal mutated
            result = original_run(command, input_bytes=input_bytes, check=check)
            if (
                not mutated
                and "apply" in command
                and "--check" not in command
                and "--reverse" not in command
                and result.returncode == 0
            ):
                mutated = True
                (worktree / "README.md").write_text(
                    "mutated after apply\n",
                    encoding="utf-8",
                )
            return result

        self.coordinator._run = apply_then_mutate  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(
                task,
                integration_ref="integration:apply-race",
                now_ms=11,
            )
        finally:
            self.coordinator._run = original_run  # type: ignore[method-assign]

        self.assertTrue(mutated)
        self.assertFalse(result["integrated"])
        self.assertTrue(result["conflict"])
        self.assertEqual((self.root / "README.md").read_text(), "A\n")
        self.assertTrue(worktree.is_dir())
        event_kinds = [
            event["eventKind"]
            for event in self.coordinator.ledger.events(
                str(prepared["workspaceBindingId"])
            )
        ]
        self.assertEqual(event_kinds[-2:], ["integration_started", "conflict"])
        self.assertNotIn("integrated", event_kinds)
        self.assertNotIn("cleaned", event_kinds)

    def test_source_mutation_after_final_capture_is_retained_before_cleanup(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:final-source-cleanup-race",
            task_id="task:final-source-cleanup-race",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("receipted\n", encoding="utf-8")
        task = {
            "taskId": "task:final-source-cleanup-race",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        original_capture = self.coordinator._capture_delivered_workspace
        mutated = False

        def final_capture_then_mutate(
            source: Path,
            *,
            expected_commit: str,
            delivery_payload: dict[str, object],
        ) -> dict[str, object]:
            nonlocal mutated
            captured = original_capture(
                source,
                expected_commit=expected_commit,
                delivery_payload=delivery_payload,
            )
            if (
                not mutated
                and (self.root / "README.md").read_text(encoding="utf-8")
                == "receipted\n"
            ):
                mutated = True
                (worktree / "README.md").write_text(
                    "late worker mutation\n",
                    encoding="utf-8",
                )
            return captured

        self.coordinator._capture_delivered_workspace = final_capture_then_mutate  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(
                task,
                integration_ref="integration:final-source-cleanup-race",
                now_ms=11,
            )
        finally:
            self.coordinator._capture_delivered_workspace = original_capture  # type: ignore[method-assign]

        self.assertTrue(mutated)
        self.assertTrue(result["integrated"])
        self.assertEqual(result["cleanupState"], "failed")
        self.assertTrue(result["attentionRequired"])
        self.assertTrue(worktree.is_dir())
        self.assertEqual(
            (worktree / "README.md").read_text(encoding="utf-8"),
            "late worker mutation\n",
        )
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"),
            "receipted\n",
        )
        self.assertEqual(
            [
                event["eventKind"]
                for event in self.coordinator.ledger.events(
                    str(prepared["workspaceBindingId"])
                )
            ][-2:],
            ["integrated", "cleanup_failed"],
        )

    def test_target_mutation_after_snapshot_rejects_stale_integration_receipt(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:target-receipt-race",
            task_id="task:target-receipt-race",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("receipted\n", encoding="utf-8")
        task = {
            "taskId": "task:target-receipt-race",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        original_record_integrated = self.coordinator.ledger.record_integrated
        mutated = False

        def mutate_target_then_record(
            *args: object,
            **kwargs: object,
        ) -> dict[str, object]:
            nonlocal mutated
            mutated = True
            (self.root / "external-target.txt").write_text(
                "external mutation\n",
                encoding="utf-8",
            )
            return original_record_integrated(*args, **kwargs)

        self.coordinator.ledger.record_integrated = mutate_target_then_record  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(
                task,
                integration_ref="integration:target-receipt-race",
                now_ms=11,
            )
        finally:
            self.coordinator.ledger.record_integrated = original_record_integrated  # type: ignore[method-assign]

        self.assertTrue(mutated)
        self.assertFalse(result["integrated"])
        self.assertTrue(result["conflict"])
        self.assertTrue(worktree.is_dir())
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"),
            "A\n",
        )
        self.assertEqual(
            (self.root / "external-target.txt").read_text(encoding="utf-8"),
            "external mutation\n",
        )
        event_kinds = [
            event["eventKind"]
            for event in self.coordinator.ledger.events(
                str(prepared["workspaceBindingId"])
            )
        ]
        self.assertEqual(event_kinds[-2:], ["target_applied", "conflict"])
        self.assertNotIn("integrated", event_kinds)
        self.assertNotIn("cleaned", event_kinds)

    def test_source_mutation_after_cleanup_check_is_quarantined_not_deleted(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:cleanup-source-toctou",
            task_id="task:cleanup-source-toctou",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("receipted\n", encoding="utf-8")
        task = {
            "taskId": "task:cleanup-source-toctou",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        original_remove = self.coordinator._remove_worktree
        remove_called = False

        def remove_after_late_source_write(
            base: Path,
            source: Path,
        ) -> subprocess.CompletedProcess[bytes]:
            nonlocal remove_called
            remove_called = True
            (source / "late.txt").write_text("late source write\n", encoding="utf-8")
            return original_remove(base, source)

        self.coordinator._remove_worktree = remove_after_late_source_write  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(
                task,
                integration_ref="integration:cleanup-source-toctou",
                now_ms=11,
            )
        finally:
            self.coordinator._remove_worktree = original_remove  # type: ignore[method-assign]

        self.assertTrue(remove_called)
        self.assertTrue(result["integrated"])
        self.assertEqual(result["cleanupState"], "failed")
        self.assertTrue(result["attentionRequired"])
        retained = Path(str(result.get("retainedWorkspaceRoot") or worktree))
        self.assertTrue(retained.is_dir())
        self.assertEqual(
            (retained / "late.txt").read_text(encoding="utf-8"),
            "late source write\n",
        )
        event_kinds = [
            event["eventKind"]
            for event in self.coordinator.ledger.events(
                str(prepared["workspaceBindingId"])
            )
        ]
        self.assertEqual(event_kinds[-1], "cleanup_failed")
        self.assertNotIn("cleaned", event_kinds)

    def test_target_mutation_after_cleanup_check_retains_child_and_receipt(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:cleanup-target-toctou",
            task_id="task:cleanup-target-toctou",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("receipted\n", encoding="utf-8")
        task = {
            "taskId": "task:cleanup-target-toctou",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        original_remove = self.coordinator._remove_worktree
        remove_called = False

        def remove_after_late_target_write(
            base: Path,
            source: Path,
        ) -> subprocess.CompletedProcess[bytes]:
            nonlocal remove_called
            remove_called = True
            (base / "external.txt").write_text(
                "late target write\n",
                encoding="utf-8",
            )
            return original_remove(base, source)

        self.coordinator._remove_worktree = remove_after_late_target_write  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(
                task,
                integration_ref="integration:cleanup-target-toctou",
                now_ms=11,
            )
        finally:
            self.coordinator._remove_worktree = original_remove  # type: ignore[method-assign]

        self.assertTrue(remove_called)
        self.assertTrue(result["integrated"])
        self.assertEqual(result["cleanupState"], "failed")
        self.assertTrue(result["attentionRequired"])
        retained = Path(str(result.get("retainedWorkspaceRoot") or worktree))
        self.assertTrue(retained.is_dir())
        self.assertEqual(
            (self.root / "external.txt").read_text(encoding="utf-8"),
            "late target write\n",
        )
        event_kinds = [
            event["eventKind"]
            for event in self.coordinator.ledger.events(
                str(prepared["workspaceBindingId"])
            )
        ]
        self.assertEqual(event_kinds[-1], "cleanup_failed")
        self.assertNotIn("cleaned", event_kinds)

    def test_git_runner_target_drift_before_remove_preserves_quarantined_child(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:cleanup-runner-toctou",
            task_id="task:cleanup-runner-toctou",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("receipted\n", encoding="utf-8")
        task = {
            "taskId": "task:cleanup-runner-toctou",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        original_run = self.coordinator._run
        injected = False

        def mutate_at_git_runner(
            command: list[str] | tuple[str, ...],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            nonlocal injected
            normalized = list(command)
            if (
                normalized[-4:-2] == ["worktree", "remove"]
                or "rag_ime.agent_room_workspace_cleanup" in normalized
            ):
                injected = True
                (self.root / "external-runner-drift.txt").write_text(
                    "target changed before physical removal\n",
                    encoding="utf-8",
                )
            return original_run(command, input_bytes=input_bytes, check=check)

        self.coordinator._run = mutate_at_git_runner  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(
                task,
                integration_ref="integration:cleanup-runner-toctou",
                now_ms=11,
            )
        finally:
            self.coordinator._run = original_run  # type: ignore[method-assign]

        self.assertTrue(injected)
        self.assertTrue(result["integrated"])
        self.assertEqual(result["cleanupState"], "failed")
        self.assertTrue(result["attentionRequired"])
        retained = Path(str(result["retainedWorkspaceRoot"]))
        self.assertTrue(
            retained.is_dir(),
            "target drift must be detected before the exact child is removed",
        )
        self.assertTrue((retained / "README.md").is_file())

    def test_abandon_revokes_owner_and_receipts_quiescence_before_remove(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:abandon-quiescence",
            task_id="task:abandon-quiescence",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            dispatch_id="dispatch:abandon-quiescence",
            participant_id="participant:a",
        )
        binding_id = str(prepared["workspaceBindingId"])
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "draft.txt").write_text("retained evidence\n", encoding="utf-8")
        self.coordinator.retain_task(
            {"taskId": "task:abandon-quiescence", "state": "failed", **prepared},
            state="failed",
            reason="synthetic failed work",
            actor_ref="system:test",
            now_ms=10,
        )
        original_remove = self.coordinator._remove_worktree
        observed: dict[str, object] = {}

        def inspect_before_remove(
            base: Path,
            source: Path,
        ) -> subprocess.CompletedProcess[bytes]:
            owner = self.sessions.get(str(self.owner_a["id"]))
            observed["executionMode"] = owner["executionMode"]
            observed["workspaceRoots"] = list(owner["workspaceRoots"])
            observed["quiescenceReceipt"] = (
                self.coordinator.ledger.abandonment_quiescence_receipt(binding_id)
            )
            return subprocess.CompletedProcess(
                args=[str(base), str(source)],
                returncode=1,
                stdout=b"",
                stderr=b"keep test evidence",
            )

        self.coordinator._remove_worktree = inspect_before_remove  # type: ignore[method-assign]
        try:
            abandoned = self.coordinator.abandon_retained(
                binding_id=binding_id,
                reason="Facilitator accepted scoped abandonment",
                acceptance_aliases=["acceptance:one"],
                actor_ref="participant:facilitator",
                now_ms=11,
            )
        finally:
            self.coordinator._remove_worktree = original_remove  # type: ignore[method-assign]

        self.assertEqual(observed["executionMode"], "read_only")
        self.assertNotIn(str(worktree), observed["workspaceRoots"])
        self.assertIsNotNone(observed["quiescenceReceipt"])
        self.assertEqual(abandoned["cleanupState"], "failed")
        self.assertTrue(Path(str(abandoned["retainedWorkspaceRoot"])).is_dir())

    def test_abandon_without_quiescence_receipt_retains_child_red(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:abandon-missing-quiescence",
            task_id="task:abandon-missing-quiescence",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            dispatch_id="dispatch:abandon-missing-quiescence",
            participant_id="participant:a",
        )
        binding_id = str(prepared["workspaceBindingId"])
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "draft.txt").write_text(
            "must remain recoverable\n",
            encoding="utf-8",
        )
        self.coordinator.retain_task(
            {
                "taskId": "task:abandon-missing-quiescence",
                "state": "failed",
                **prepared,
            },
            state="failed",
            reason="synthetic failed work",
            actor_ref="system:test",
            now_ms=10,
        )
        provider = self.coordinator._writer_quiescence_provider
        self.coordinator._writer_quiescence_provider = None
        try:
            with self.assertRaisesRegex(
                RoomWorkspaceError,
                "writer-quiescence provider is unavailable",
            ):
                self.coordinator.abandon_retained(
                    binding_id=binding_id,
                    reason="must fail closed without runtime settlement",
                    acceptance_aliases=["acceptance:one"],
                    actor_ref="participant:facilitator",
                    now_ms=11,
                )
        finally:
            self.coordinator._writer_quiescence_provider = provider

        binding = self.coordinator.ledger.binding(binding_id)
        owner = self.sessions.get(str(self.owner_a["id"]))
        self.assertTrue(worktree.is_dir())
        self.assertEqual(binding["workspaceLifecycleState"], "failed")
        self.assertTrue(binding["attentionRequired"])
        self.assertEqual(owner["executionMode"], "read_only")
        self.assertNotIn(str(worktree), owner["workspaceRoots"])
        self.assertIsNone(
            self.coordinator.ledger.abandonment_quiescence_receipt(binding_id)
        )
        self.assertFalse(
            any(
                event["eventKind"] == "abandoned"
                for event in self.coordinator.ledger.events(binding_id)
            )
        )

    def test_old_path_write_after_quarantine_fails_before_final_remove(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:old-path-fence",
            task_id="task:old-path-fence",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        old_path = Path(str(prepared["workspaceRoot"]))
        (old_path / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {"taskId": "task:old-path-fence", "state": "completed", **prepared}
        self.coordinator.record_delivery(task, now_ms=10)
        original_remove = self.coordinator._remove_worktree
        old_write_failed = False

        def remove_after_old_path_probe(
            base: Path,
            quarantined: Path,
        ) -> subprocess.CompletedProcess[bytes]:
            nonlocal old_write_failed
            try:
                (old_path / "late.txt").write_text("must fail\n", encoding="utf-8")
            except FileNotFoundError:
                old_write_failed = True
            return original_remove(base, quarantined)

        self.coordinator._remove_worktree = remove_after_old_path_probe  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(task, now_ms=11)
        finally:
            self.coordinator._remove_worktree = original_remove  # type: ignore[method-assign]
        self.assertTrue(old_write_failed)
        self.assertEqual(result["cleanupState"], "cleaned")
        self.assertFalse(old_path.exists())

    def test_final_cleanup_boundary_late_file_is_vaulted_with_receipt(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:final-cleanup-vault",
            task_id="task:final-cleanup-vault",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        old_path = Path(str(prepared["workspaceRoot"]))
        (old_path / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {
            "taskId": "task:final-cleanup-vault",
            "state": "completed",
            **prepared,
        }
        unrelated_worktree = Path(self.tmp.name) / "unrelated-worktree"
        subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(self.root),
                "worktree",
                "add",
                "--detach",
                str(unrelated_worktree),
                "HEAD",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        )
        self.coordinator.record_delivery(task, now_ms=10)
        original_run = self.coordinator._run
        original_rename = workspace_cleanup.os.rename
        late_injected = False
        exec_result: subprocess.CompletedProcess[bytes] | None = None

        def inject_late_file(source: Path) -> None:
            nonlocal late_injected
            if late_injected:
                return
            late_injected = True
            (source / "late-boundary.txt").write_text(
                "arrived after the final cleanup check\n",
                encoding="utf-8",
            )

        def rename_after_late_write(
            source: str | bytes | int,
            target: str | bytes | int,
            *args: object,
            **kwargs: object,
        ) -> None:
            inject_late_file(Path(source))
            original_rename(source, target, *args, **kwargs)

        def exec_after_late_write(
            _program: str,
            arguments: list[str],
        ) -> None:
            nonlocal exec_result
            quarantine = Path(arguments[-1])
            inject_late_file(quarantine)
            exec_result = subprocess.run(
                ["/usr/bin/git", *arguments[1:]],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )

        def run_cleanup_in_process(
            command: list[str] | tuple[str, ...],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            normalized = list(command)
            if "rag_ime.agent_room_workspace_cleanup" not in normalized:
                return original_run(
                    command,
                    input_bytes=input_bytes,
                    check=check,
                )
            output = io.StringIO()
            with (
                mock.patch.object(
                    workspace_cleanup.os,
                    "rename",
                    side_effect=rename_after_late_write,
                ),
                mock.patch.object(
                    workspace_cleanup.os,
                    "execvp",
                    side_effect=exec_after_late_write,
                ),
                redirect_stdout(output),
            ):
                helper_result = workspace_cleanup._guarded_remove(normalized[3:])
            return subprocess.CompletedProcess(
                args=normalized,
                returncode=(
                    exec_result.returncode
                    if exec_result is not None
                    else helper_result
                ),
                stdout=output.getvalue().encode("utf-8"),
                stderr=(exec_result.stderr if exec_result is not None else b""),
            )

        self.coordinator._run = run_cleanup_in_process  # type: ignore[method-assign]
        try:
            result = self.coordinator.integrate(task, now_ms=11)
        finally:
            self.coordinator._run = original_run  # type: ignore[method-assign]

        self.assertTrue(late_injected)
        self.assertEqual(result["cleanupState"], "cleaned")
        self.assertFalse(old_path.exists())
        recovery_raw = str(result.get("retainedWorkspaceRoot") or "")
        self.assertTrue(
            recovery_raw,
            "cleaned ledger must expose the recoverable final-boundary bytes",
        )
        recovery_root = Path(recovery_raw)
        self.assertTrue(recovery_root.is_dir())
        self.assertEqual(
            (recovery_root / "late-boundary.txt").read_text(encoding="utf-8"),
            "arrived after the final cleanup check\n",
        )
        binding_id = str(prepared["workspaceBindingId"])
        quarantine_root = self.coordinator._quarantine_path(
            self.coordinator.ledger.binding(binding_id)
        )
        self.assertFalse(quarantine_root.exists())
        vault = self.coordinator.ledger.vault_receipt(binding_id)
        self.assertIsNotNone(vault)
        assert vault is not None
        vault_payload = vault["payload"]
        self.assertEqual(vault_payload["vaultWorkspaceRoot"], recovery_raw)
        self.assertEqual(
            vault_payload["vaultContentSha256"],
            self.coordinator._vault_content_digest(recovery_root),
        )
        self.assertNotEqual(
            vault_payload["authorizedWorkspaceContentSha256"],
            vault_payload["vaultContentSha256"],
        )
        cleanup = self.coordinator.ledger.cleanup_receipt(binding_id)
        self.assertIsNotNone(cleanup)
        assert cleanup is not None
        self.assertEqual(cleanup["payload"]["vaultReceiptId"], vault["eventId"])
        self.assertEqual(
            cleanup["payload"]["vaultReceiptSha256"],
            vault["payloadSha256"],
        )
        registered = subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(self.root),
                "worktree",
                "list",
                "--porcelain",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        ).stdout.decode("utf-8")
        self.assertIn(f"worktree {unrelated_worktree.resolve()}\n", registered)
        self.assertNotIn(f"worktree {old_path.resolve(strict=False)}\n", registered)
        self.assertNotIn(
            f"worktree {quarantine_root.resolve(strict=False)}\n",
            registered,
        )
        self.assertNotIn(f"worktree {recovery_root.resolve()}\n", registered)

    def test_pre_quarantine_open_fd_blocks_cleanup_and_preserves_late_write(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:open-fd",
            task_id="task:open-fd",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {"taskId": "task:open-fd", "state": "completed", **prepared}
        self.coordinator.record_delivery(task, now_ms=10)
        with (worktree / "README.md").open("r+", encoding="utf-8") as handle:
            result = self.coordinator.integrate(task, now_ms=11)
            retained = Path(str(result["retainedWorkspaceRoot"]))
            handle.seek(0)
            handle.write("late fd write\n")
            handle.truncate()
            handle.flush()
            self.assertEqual(
                (retained / "README.md").read_text(encoding="utf-8"),
                "late fd write\n",
            )
        self.assertEqual(result["cleanupState"], "failed")
        self.assertTrue(result["attentionRequired"])
        self.assertFalse(worktree.exists())
        self.assertTrue(retained.is_dir())

    def test_missing_handle_inspector_retains_quarantined_child(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:no-inspector",
            task_id="task:no-inspector",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {"taskId": "task:no-inspector", "state": "completed", **prepared}
        self.coordinator.record_delivery(task, now_ms=10)
        inspector = self.coordinator._handle_inspector
        self.coordinator._handle_inspector = None
        try:
            result = self.coordinator.integrate(task, now_ms=11)
        finally:
            self.coordinator._handle_inspector = inspector
        retained = Path(str(result["retainedWorkspaceRoot"]))
        self.assertEqual(result["cleanupState"], "failed")
        self.assertTrue(result["attentionRequired"])
        self.assertFalse(worktree.exists())
        self.assertTrue(retained.is_dir())

    def test_missing_writer_quiescence_provider_never_removes_child(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:no-quiescence-provider",
            task_id="task:no-quiescence-provider",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {
            "taskId": "task:no-quiescence-provider",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        provider = self.coordinator._writer_quiescence_provider
        self.coordinator._writer_quiescence_provider = None
        try:
            result = self.coordinator.integrate(task, now_ms=11)
        finally:
            self.coordinator._writer_quiescence_provider = provider
        self.assertEqual(result["cleanupState"], "failed")
        self.assertTrue(result["attentionRequired"])
        self.assertTrue(worktree.is_dir())

    def test_startup_defers_then_resumes_crash_after_quarantine_move(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:crash-after-quarantine",
            task_id="task:crash-after-quarantine",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {
            "taskId": "task:crash-after-quarantine",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        original_remove = self.coordinator._remove_worktree
        self.coordinator._remove_worktree = (  # type: ignore[method-assign]
            lambda base, source: (_ for _ in ()).throw(SystemExit("hard crash"))
        )
        try:
            with self.assertRaises(SystemExit):
                self.coordinator.integrate(task, now_ms=11)
        finally:
            self.coordinator._remove_worktree = original_remove  # type: ignore[method-assign]
        binding_id = str(prepared["workspaceBindingId"])
        self.assertIsNotNone(self.coordinator.ledger.quarantine_receipt(binding_id))
        recovered = RoomWorkspaceCoordinator(
            root_dir=Path(self.tmp.name) / "room-workspaces",
            sessions=self.sessions,
            writer_quiescence_provider=self._writer_quiescence_receipt,
        )
        deferred = recovered.ledger.binding(binding_id)
        self.assertEqual(deferred["workspaceLifecycleState"], "cleanup_failed")
        self.assertTrue(deferred["attentionRequired"])
        cleanup = recovered.recover_integrated_cleanups(now_ms=12)
        self.assertEqual(len(cleanup), 1)
        self.assertEqual(cleanup[0]["cleanupState"], "cleaned")

    def test_startup_receipts_missing_after_crash_post_remove(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:crash-after-remove",
            task_id="task:crash-after-remove",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {"taskId": "task:crash-after-remove", "state": "completed", **prepared}
        self.coordinator.record_delivery(task, now_ms=10)
        original_cleanup = self.coordinator.ledger.record_cleanup

        def crash_before_cleaned_receipt(
            *args: object,
            **kwargs: object,
        ) -> dict[str, object]:
            if kwargs.get("result") == "cleaned":
                raise SystemExit("hard crash")
            return original_cleanup(*args, **kwargs)

        self.coordinator.ledger.record_cleanup = crash_before_cleaned_receipt  # type: ignore[method-assign]
        try:
            with self.assertRaises(SystemExit):
                self.coordinator.integrate(task, now_ms=11)
        finally:
            self.coordinator.ledger.record_cleanup = original_cleanup  # type: ignore[method-assign]
        self.assertFalse(worktree.exists())
        binding_id = str(prepared["workspaceBindingId"])
        self.assertIsNotNone(self.coordinator.ledger.quarantine_receipt(binding_id))
        recovered = RoomWorkspaceCoordinator(
            root_dir=Path(self.tmp.name) / "room-workspaces",
            sessions=self.sessions,
            writer_quiescence_provider=self._writer_quiescence_receipt,
        )
        final = recovered.ledger.binding(binding_id)
        self.assertEqual(final["workspaceLifecycleState"], "cleaned")
        self.assertEqual(final["cleanupState"], "cleaned")
        self.assertFalse(final["attentionRequired"])
        cleanup = recovered.ledger.cleanup_receipt(binding_id)
        self.assertIsNotNone(cleanup)
        assert cleanup is not None
        vault = Path(str(cleanup["payload"]["retainedWorkspaceRoot"]))
        self.assertTrue(vault.is_dir())
        self.assertEqual(
            cleanup["payload"]["vaultContentSha256"],
            recovered._vault_content_digest(vault),
        )

    def test_cleanup_failure_retains_worktree_until_receipted_retry(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:cleanup-retry",
            task_id="task:cleanup-retry",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {"taskId": "task:cleanup-retry", "state": "completed", **prepared}
        self.coordinator.record_delivery(
            task,
            artifacts=["README.md"],
            verification_refs=["test:cleanup-retry"],
            actor_ref="participant:a",
            now_ms=10,
        )

        original_remove_worktree = self.coordinator._remove_worktree
        self.coordinator._remove_worktree = (  # type: ignore[method-assign]
            lambda base, source: subprocess.CompletedProcess(
                args=[str(base), str(source)],
                returncode=1,
                stdout=b"",
                stderr=b"injected cleanup failure",
            )
        )
        integrated = self.coordinator.integrate(
            task,
            integration_ref="integration:cleanup-retry",
            actor_ref="participant:facilitator",
            now_ms=11,
        )
        self.assertTrue(integrated["integrated"])
        self.assertEqual(integrated["workspaceLifecycleState"], "cleanup_failed")
        self.assertEqual(integrated["cleanupState"], "failed")
        self.assertTrue(integrated["attentionRequired"])
        retained = Path(str(integrated["retainedWorkspaceRoot"]))
        self.assertFalse(worktree.exists())
        self.assertTrue(retained.is_dir())

        self.coordinator._remove_worktree = original_remove_worktree  # type: ignore[method-assign]
        cleaned = self.coordinator.integrate(
            task,
            integration_ref="integration:cleanup-retry",
            actor_ref="participant:facilitator",
            now_ms=12,
        )
        self.assertTrue(cleaned["integrated"])
        self.assertTrue(cleaned["idempotent"])
        self.assertEqual(
            cleaned["integrationRef"],
            integrated["integrationRef"],
        )
        self.assertEqual(cleaned["workspaceLifecycleState"], "cleaned")
        self.assertEqual(cleaned["cleanupState"], "cleaned")
        self.assertFalse(worktree.exists())

    def test_integrated_cleanup_failure_cannot_be_rebound_for_retry(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:integrated-cleanup-retry",
            task_id="task:integrated-cleanup-retry",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("integrated\n", encoding="utf-8")
        task = {
            "taskId": "task:integrated-cleanup-retry",
            "state": "completed",
            **prepared,
        }
        self.coordinator.record_delivery(task, now_ms=10)
        original_remove = self.coordinator._remove_worktree
        self.coordinator._remove_worktree = (  # type: ignore[method-assign]
            lambda base, source: subprocess.CompletedProcess(
                args=[str(base), str(source)],
                returncode=1,
                stdout=b"",
                stderr=b"injected cleanup failure",
            )
        )
        try:
            integrated = self.coordinator.integrate(task, now_ms=11)
        finally:
            self.coordinator._remove_worktree = original_remove  # type: ignore[method-assign]
        self.assertEqual(integrated["cleanupState"], "failed")

        with self.assertRaisesRegex(
            RoomWorkspaceError,
            "integrated|cleanup",
        ):
            self.coordinator.retry_retained(
                binding_id=str(prepared["workspaceBindingId"]),
                participant_id="participant:b",
                participant_ref="@worker-b",
                session_id=str(self.owner_b["id"]),
                reason="must not resume integrated evidence",
                now_ms=12,
            )
        binding = self.coordinator.ledger.binding(
            str(prepared["workspaceBindingId"])
        )
        self.assertEqual(binding["workspaceLifecycleState"], "cleanup_failed")
        self.assertTrue(binding["attentionRequired"])
        self.assertNotIn(
            str(worktree.resolve()),
            self.sessions.get(str(self.owner_b["id"]))["workspaceRoots"],
        )

    def test_retry_restores_full_auto_policy_and_exact_isolated_root(self) -> None:
        owner_id = str(self.owner_a["id"])
        self.sessions.set_runtime_policy(
            owner_id,
            mode="coordinator",
            tool_profile_version="control-center-auto-approve-v1",
            execution_mode="full_trust",
            grant_workspace_scope=True,
            allowed_tools=None,
            workspace_roots=[str(self.root)],
            updated_at_ms=3,
        )
        prepared = self.coordinator.prepare(
            root_id="root:full-auto-retry",
            task_id="task:full-auto-retry",
            target_session_id=owner_id,
            base_roots=[str(self.root)],
            policy="isolated_writable",
            participant_id="participant:a",
            now_ms=4,
        )
        worktree = Path(str(prepared["workspaceRoot"])).resolve()
        task = {
            "taskId": "task:full-auto-retry",
            "state": "failed",
            **prepared,
        }
        self.coordinator.retain_task(
            task,
            state="failed",
            reason="synthetic runtime host exit",
            actor_ref="system:test",
            now_ms=5,
        )
        # Reproduce startup recovery clobbering the runtime Session before the
        # retained worktree is rebound.
        self.sessions.set_runtime_policy(
            owner_id,
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="per_action",
            grant_workspace_scope=False,
            allowed_tools=None,
            workspace_roots=[str(self.root)],
            updated_at_ms=6,
        )

        rebound = self.coordinator.retry_retained(
            binding_id=str(prepared["workspaceBindingId"]),
            participant_id="participant:a",
            participant_ref="@worker-a",
            session_id=owner_id,
            reason="automatic runtime recovery",
            now_ms=7,
        )

        session = self.sessions.get(owner_id)
        self.assertEqual(rebound["workspaceLifecycleState"], "retry_bound")
        self.assertEqual(session["executionMode"], "full_trust")
        self.assertEqual(
            [Path(value).resolve() for value in session["workspaceRoots"]],
            [worktree],
        )
        self.assertTrue(session["workspaceScopeGranted"])

    def test_concurrent_retry_uses_one_ledger_cas_and_one_session_lease(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:retry-cas",
            task_id="task:retry-cas",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        task = {
            "taskId": "task:retry-cas",
            "state": "failed",
            **prepared,
        }
        self.coordinator.retain_task(
            task,
            state="failed",
            reason="synthetic worker failure",
            actor_ref="system:test",
            now_ms=10,
        )
        self.coordinator.restore(
            session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            restore_policy=prepared["workspaceRestorePolicy"],
        )
        contender = RoomWorkspaceCoordinator(
            root_dir=Path(self.tmp.name) / "room-workspaces",
            sessions=self.sessions,
        )
        barrier = threading.Barrier(2)
        first_retry = self.coordinator.ledger.retry_binding
        second_retry = contender.ledger.retry_binding

        def wait_then_first(*args: object, **kwargs: object) -> dict[str, object]:
            barrier.wait(timeout=5)
            return first_retry(*args, **kwargs)

        def wait_then_second(*args: object, **kwargs: object) -> dict[str, object]:
            barrier.wait(timeout=5)
            return second_retry(*args, **kwargs)

        self.coordinator.ledger.retry_binding = wait_then_first  # type: ignore[method-assign]
        contender.ledger.retry_binding = wait_then_second  # type: ignore[method-assign]
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def retry(
            coordinator: RoomWorkspaceCoordinator,
            participant_id: str,
            session_id: str,
        ) -> None:
            try:
                results.append(
                    coordinator.retry_retained(
                        binding_id=str(prepared["workspaceBindingId"]),
                        participant_id=participant_id,
                        participant_ref=f"@{participant_id}",
                        session_id=session_id,
                        reason="concurrent retry",
                        now_ms=11,
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(
                target=retry,
                args=(
                    self.coordinator,
                    "participant:a",
                    str(self.owner_a["id"]),
                ),
            ),
            threading.Thread(
                target=retry,
                args=(
                    contender,
                    "participant:b",
                    str(self.owner_b["id"]),
                ),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.coordinator.ledger.retry_binding = first_retry  # type: ignore[method-assign]
        contender.ledger.retry_binding = second_retry  # type: ignore[method-assign]

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RoomWorkspaceError)
        binding_id = str(prepared["workspaceBindingId"])
        retry_events = [
            event
            for event in self.coordinator.ledger.events(binding_id)
            if event["eventKind"] == "retry_bound"
        ]
        self.assertEqual(len(retry_events), 1)
        winner_session = str(retry_events[0]["payload"]["sessionId"])
        loser_session = (
            str(self.owner_b["id"])
            if winner_session == str(self.owner_a["id"])
            else str(self.owner_a["id"])
        )
        self.assertIn(
            str(worktree.resolve()),
            self.sessions.get(winner_session)["workspaceRoots"],
        )
        self.assertNotIn(
            str(worktree.resolve()),
            self.sessions.get(loser_session)["workspaceRoots"],
        )

    def test_delivery_manifest_is_exact_bounded_redacted_and_hash_bound(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:delivery-manifest",
            task_id="task:delivery-manifest",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            room_id="room:delivery-manifest",
            work_item_id="work:delivery-manifest",
            dispatch_id="dispatch:delivery-manifest",
            participant_id="participant:a",
            now_ms=1,
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        (worktree / "README.md").write_text("changed\n", encoding="utf-8")
        (worktree / "asset.bin").write_bytes(b"\x00\x01\x02")
        (worktree / ".env").write_text("TOKEN=private\n", encoding="utf-8")
        (worktree / ".env.local").write_text(
            "TOKEN=also-private\n",
            encoding="utf-8",
        )
        (worktree / ".env.production").write_text(
            "TOKEN=production-private\n",
            encoding="utf-8",
        )
        (worktree / "secret-token.txt").write_text(
            "private\n",
            encoding="utf-8",
        )
        (worktree / "unsafe\nname.txt").write_text(
            "private path\n",
            encoding="utf-8",
        )
        (worktree / "dist").mkdir()
        (worktree / "dist" / "bundle.js").write_text(
            "generated();\n",
            encoding="utf-8",
        )
        # Dirt outside the exact receipted child worktree must never be
        # attributed to this participant's delivery.
        (self.root / "base-only.txt").write_text(
            "unrelated base dirt\n",
            encoding="utf-8",
        )
        task = {
            "taskId": "task:delivery-manifest",
            "rootId": "root:delivery-manifest",
            "currentOwnerParticipantId": "participant:a",
            **prepared,
        }
        delivery = self.coordinator.record_delivery(
            task,
            artifacts=["artifact:report"],
            verification_refs=["test:focused"],
            verification_results=[
                {
                    "label": "验收项 1",
                    "result": "pass",
                    "source": "quality_gate",
                }
            ],
            residual_risks=["binary line counts are unavailable"],
            result_summary="Implemented and verified the scoped change.",
            actor_ref="participant:a",
            now_ms=10,
        )
        model = delivery["workspaceDelivery"]
        self.assertEqual(model["ownerParticipantId"], "participant:a")
        self.assertEqual(model["ownerSessionId"], self.owner_a["id"])
        self.assertEqual(model["workItemId"], "work:delivery-manifest")
        self.assertEqual(model["taskId"], "task:delivery-manifest")
        self.assertEqual(model["deliveryRevision"], delivery["deliveryRevision"])
        self.assertEqual(model["deliveredAtMs"], 10)
        self.assertEqual(model["verificationCount"], 1)
        self.assertEqual(
            model["verifications"],
            [
                {
                    "label": "验收项 1",
                    "result": "pass",
                    "source": "quality_gate",
                }
            ],
        )
        public_verifications = json.dumps(
            model["verifications"], ensure_ascii=False
        )
        self.assertNotIn("AC-", public_verifications)
        self.assertNotIn("criterionId", public_verifications)
        self.assertRegex(str(model["manifestSha256"]), r"^[0-9a-f]{64}$")
        files = list(model["files"])
        by_path = {
            str(item["path"]): item
            for item in files
            if not item["redacted"]
        }
        self.assertEqual(by_path["README.md"]["additions"], 1)
        self.assertEqual(by_path["README.md"]["deletions"], 1)
        self.assertTrue(by_path["asset.bin"]["binary"])
        self.assertIsNone(by_path["asset.bin"]["additions"])
        self.assertTrue(by_path["dist/bundle.js"]["generated"])
        redacted = [item for item in files if item["redacted"]]
        self.assertEqual(len(redacted), 5)
        self.assertTrue(
            all(
                re.match(r"^\[redacted-file-\d+\]$", str(item["path"]))
                for item in redacted
            )
        )
        encoded = json.dumps(model, ensure_ascii=False)
        self.assertNotIn(".env", encoded)
        self.assertNotIn("secret-token", encoded)
        self.assertNotIn("unsafe\\nname", encoded)
        self.assertNotIn("TOKEN=private", encoded)
        self.assertNotIn("base-only.txt", encoded)
        delivered_event = next(
            event
            for event in self.coordinator.ledger.events(
                str(prepared["workspaceBindingId"])
            )
            if event["eventKind"] == "delivered"
        )
        self.assertEqual(
            delivered_event["payload"]["workspaceDelivery"],
            model,
        )

    def test_delivery_manifest_rejects_unbounded_changed_file_sets(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:delivery-bound",
            task_id="task:delivery-bound",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        original_git_bytes = self.coordinator._git_bytes
        self.coordinator._git_bytes = (  # type: ignore[method-assign]
            lambda root, *args: (
                b"".join(
                    f"1\t0\tfile-{index}.txt\0".encode("utf-8")
                    for index in range(513)
                )
                if "--numstat" in args
                else original_git_bytes(root, *args)
            )
        )
        try:
            with self.assertRaisesRegex(
                RoomWorkspaceError,
                "bounded changed-file limit",
            ):
                self.coordinator._delivery_manifest(
                    worktree,
                    baseline_commit=str(prepared["workspaceBaseCommit"]),
                )
        finally:
            self.coordinator._git_bytes = original_git_bytes  # type: ignore[method-assign]

    def test_abandonment_cleanup_failure_keeps_attention_and_authority_receipt(
        self,
    ) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:abandon-cleanup-failure",
            task_id="task:abandon-cleanup-failure",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
            participant_id="participant:a",
            now_ms=1,
        )
        worktree = Path(str(prepared["workspaceRoot"]))
        task = {
            "taskId": "task:abandon-cleanup-failure",
            "rootId": "root:abandon-cleanup-failure",
            **prepared,
        }
        self.coordinator.retain_task(
            task,
            state="failed",
            reason="implementation failed after preserving evidence",
            actor_ref="participant:a",
            now_ms=2,
        )

        original_remove_worktree = self.coordinator._remove_worktree
        self.coordinator._remove_worktree = (  # type: ignore[method-assign]
            lambda base, source: subprocess.CompletedProcess(
                args=[str(base), str(source)],
                returncode=1,
                stdout=b"",
                stderr=b"injected abandonment cleanup failure",
            )
        )
        try:
            abandoned = self.coordinator.abandon_retained(
                binding_id=str(prepared["workspaceBindingId"]),
                reason="Facilitator authorized scoped abandonment",
                acceptance_aliases=["criterion:one"],
                actor_ref="participant:facilitator",
                now_ms=3,
            )
            events_before_replay = self.coordinator.ledger.events(
                str(prepared["workspaceBindingId"])
            )
            replay = self.coordinator.abandon_retained(
                binding_id=str(prepared["workspaceBindingId"]),
                reason="Facilitator authorized scoped abandonment",
                acceptance_aliases=["criterion:one"],
                actor_ref="participant:facilitator",
                now_ms=4,
            )
        finally:
            self.coordinator._remove_worktree = original_remove_worktree  # type: ignore[method-assign]

        for result in (abandoned, replay):
            self.assertTrue(result["abandonmentAuthorized"])
            self.assertFalse(result["physicalCleanupCompleted"])
            self.assertEqual(
                result["workspaceLifecycleState"],
                "cleanup_failed",
            )
            self.assertEqual(result["cleanupState"], "failed")
            self.assertTrue(result["attentionRequired"])
            self.assertRegex(
                str(result["abandonmentReceiptId"]),
                r"^room-workspace-event:",
            )
            self.assertRegex(
                str(result["abandonmentReceiptSha256"]),
                r"^[0-9a-f]{64}$",
            )
        self.assertEqual(
            self.coordinator.ledger.events(
                str(prepared["workspaceBindingId"])
            ),
            events_before_replay,
        )
        event_kinds = [event["eventKind"] for event in events_before_replay]
        self.assertIn("abandonment_writer_quiescent", event_kinds)
        self.assertIn("abandoned", event_kinds)
        self.assertIn("quarantined", event_kinds)
        self.assertIn("cleanup_removal_authorized", event_kinds)
        self.assertEqual(event_kinds[-1], "cleanup_failed")
        binding = self.coordinator.ledger.binding(
            str(prepared["workspaceBindingId"])
        )
        self.assertEqual(binding["workspaceLifecycleState"], "cleanup_failed")
        self.assertTrue(binding["attentionRequired"])
        retained = Path(str(abandoned["retainedWorkspaceRoot"]))
        self.assertFalse(worktree.exists())
        self.assertTrue(retained.is_dir())

    def test_recovery_scan_records_unclaimed_physical_workspace(self) -> None:
        orphan = Path(self.tmp.name) / "room-workspaces" / "forgotten" / "project"
        orphan.mkdir(parents=True)
        (orphan / "unfinished.txt").write_text("preserve me\n", encoding="utf-8")

        discovered = self.coordinator.discover_orphans(now_ms=10)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["workspaceLifecycleState"], "orphaned")
        self.assertEqual(discovered[0]["workspaceRoot"], str(orphan.resolve()))
        self.assertTrue(discovered[0]["attentionRequired"])
        self.assertTrue(orphan.is_dir())

        replay = self.coordinator.discover_orphans(now_ms=11)
        self.assertEqual(replay, [])
        self.assertEqual(len(self.coordinator.ledger.attention_bindings()), 1)

    def test_delivery_rejects_task_payload_retargeting_durable_binding(self) -> None:
        prepared = self.coordinator.prepare(
            root_id="root:identity",
            task_id="task:identity",
            target_session_id=str(self.owner_a["id"]),
            base_roots=[str(self.root)],
            policy="isolated_writable",
        )
        task = {
            "taskId": "task:substituted",
            "rootId": "root:identity",
            "state": "completed",
            **prepared,
        }
        with self.assertRaisesRegex(
            RoomWorkspaceError,
            "does not match its durable binding",
        ):
            self.coordinator.record_delivery(
                task,
                actor_ref="participant:a",
                now_ms=10,
            )
        self.assertEqual(
            self.coordinator.ledger.binding(str(prepared["workspaceBindingId"]))[
                "workspaceLifecycleState"
            ],
            "materialized",
        )

    def test_lease_identity_binds_root_task_owner_revision_and_dispatch(self) -> None:
        db_path = Path(self.tmp.name) / "kernel.sqlite"
        kernel = RoomKernelStore(db_path, mode="test")
        self.assertEqual(kernel.initialize(), latest_migration_version())
        kernel.create_root(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:lease",
                "roomId": "room:lease",
                "generation": 0,
                "state": "running",
                "facilitatorParticipantId": "participant:a",
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": "requirement-anchor:lease",
                "createdByActorRef": "user:test",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "independentReviewRequired": False,
                "createdAtMs": 1,
            },
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        kernel.create_task(
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:lease",
                "rootId": "root:lease",
                "parentTaskId": None,
                "taskKind": "work",
                "currentOwnerParticipantId": "participant:a",
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
                "objective": "Lease identity",
                "expectedOutput": "A bounded result",
                "requirementItemIds": [],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "active",
            },
            now_ms=2,
        )
        kernel.enqueue_dispatch(
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": "dispatch:lease",
                "rootId": "root:lease",
                "taskId": "task:lease",
                "parentDispatchId": None,
                "generation": 0,
                "hopCount": 0,
                "depth": 0,
                "budgetCost": 1,
                "targetSessionId": "session:lease",
                "targetParticipantId": "participant:a",
                "triggerId": "trigger:lease",
                "intentKind": "execute",
                "idempotencyKey": "dispatch:lease",
                "attempt": 0,
                "capabilityEpoch": 1,
                "runtimeProfileRevision": "runtime-profile:test-v1",
                "state": "pending",
            },
            now_ms=3,
        )
        lease = kernel.lease_next(now_ms=4, ttl_ms=100)
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertEqual(
            {
                lease["rootId"],
                lease["taskId"],
                lease["ownershipRevision"],
                lease["dispatchId"],
            },
            {"root:lease", "task:lease", 0, "dispatch:lease"},
        )
        with sqlite3.connect(db_path) as conn:
            payload = json.loads(
                str(
                    conn.execute(
                        "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                        ("task:lease",),
                    ).fetchone()[0]
                )
            )
            payload["ownershipRevision"] = 1
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    "task:lease",
                ),
            )
        with self.assertRaisesRegex(RoomKernelFenceError, "stale Task ownership"):
            kernel.accept_runtime_receipt(
                lease_token=str(lease["leaseToken"]),
                runtime_receipt={
                    "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
                    "receiptKind": "dispatch_accepted",
                    "status": "accepted",
                    "rootId": "root:lease",
                    "dispatchId": "dispatch:lease",
                    "generation": 0,
                    "turnId": "turn:stale",
                },
                now_ms=5,
            )


if __name__ == "__main__":
    unittest.main()
