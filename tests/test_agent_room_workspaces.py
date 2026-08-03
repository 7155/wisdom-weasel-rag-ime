from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

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
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

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
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def prepare() -> None:
            try:
                results.append(self.coordinator.prepare(
                    root_id="root:concurrent-prepare",
                    task_id="task:concurrent-prepare",
                    target_session_id=str(self.owner_a["id"]),
                    base_roots=[str(self.root)],
                    policy="isolated_writable",
                ))
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=prepare)
        second = threading.Thread(target=prepare)
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
        self.assertTrue(worktree.is_dir())

        self.coordinator._remove_worktree = original_remove_worktree  # type: ignore[method-assign]
        binding = self.coordinator.ledger.binding(str(prepared["workspaceBindingId"]))
        cleaned = self.coordinator._cleanup_receipted_worktree(
            binding,
            actor_ref="participant:facilitator",
            now_ms=12,
        )
        self.assertEqual(cleaned["workspaceLifecycleState"], "cleaned")
        self.assertEqual(cleaned["cleanupState"], "cleaned")
        self.assertFalse(worktree.exists())

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
        self.assertEqual(
            [event["eventKind"] for event in events_before_replay][-2:],
            ["abandoned", "cleanup_failed"],
        )
        binding = self.coordinator.ledger.binding(
            str(prepared["workspaceBindingId"])
        )
        self.assertEqual(binding["workspaceLifecycleState"], "cleanup_failed")
        self.assertTrue(binding["attentionRequired"])
        self.assertTrue(worktree.is_dir())

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
