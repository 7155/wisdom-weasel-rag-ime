from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from rag_ime.agent_background_jobs import (
    AgentBackgroundJobError,
    AgentBackgroundJobService,
)
from rag_ime.agent_delegation import (
    AgentDelegationCoordinator,
    AgentDelegationStore,
    _ActiveDelegatedRun,
)
from rag_ime.agent_service import AgentService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_workspace import PreparedWorkspaceCommand, WorkspaceHarness
from rag_ime.contracts.json_schema import validate_contract
from rag_ime.db.migration_runner import apply_database_migrations, load_migrations


class _Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, dict[str, object], str]] = []

    def publish(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        turn_id: str = "",
    ) -> None:
        self.items.append((session_id, event_type, payload, turn_id))


class _Runtime:
    def __init__(self, callback=None, receipt=None, error: Exception | None = None) -> None:
        self.callback = callback
        self.receipt = receipt or {
            "schemaVersion": "rag-ime.pi-session-abort-receipt.v1",
            "turnId": "turn-provider-1",
            "pid": 999,
            "processHandle": "must-not-persist",
            "lifecycle": {"drained": True, "failedOperationIds": [], "pendingOperations": []},
        }
        self.error = error
        self.calls = 0

    def abort(self, session_id: str):
        self.calls += 1
        if self.callback is not None:
            self.callback(session_id)
        if self.error is not None:
            raise self.error
        return self.receipt


class _Jobs:
    def __init__(self, *, error: Exception | None = None, jobs=None, excluded=None) -> None:
        self.error = error
        self.jobs = list(jobs or [])
        self.excluded = list(excluded or [])
        self.calls = 0

    def cancel_causal(self, session_id: str, **payload):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {
            "schemaVersion": "rag-ime.agent-background-job-lifecycle-cancellation-summary.v1",
            "requestId": payload["request_id"],
            "sessionId": session_id,
            "scopeKind": payload["scope_kind"],
            "scopeId": payload["scope_id"],
            "sourceRevision": payload["source_revision"],
            "jobs": self.jobs,
            "excludedRoomBoundJobIds": self.excluded,
        }

    def list(self, _session_id: str, *, limit: int):
        del limit
        return {"items": []}


class _Delegation:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        state: str = "terminated",
    ) -> None:
        self.error = error
        self.state = state
        self.calls = 0

    def cancel_causal(self, session_id: str, **payload):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {
            "schemaVersion": "rag-ime.agent-delegation-lifecycle-cancellation-summary.v1",
            "requestId": payload["request_id"],
            "parentSessionId": session_id,
            "scopeKind": payload["scope_kind"],
            "scopeId": payload["scope_id"],
            "sourceRevision": payload["source_revision"],
            "state": self.state,
            "pendingRunIds": (
                ["subagent-run:pending"]
                if self.state == "requested"
                else []
            ),
            "batches": [],
            "excludedRoomBoundBatchIds": [],
        }


class _RoomTurns:
    def __init__(self, active: bool = False) -> None:
        self.active = active

    def session_turn_active(self, _session_id: str) -> bool:
        return self.active


class _WorkDocuments:
    def observe_authority(self, _kind: str, _identifier: str) -> None:
        return None


def _service(
    store: AgentSessionStore,
    *,
    runtime: _Runtime,
    jobs: _Jobs,
    delegation: _Delegation | None = None,
    room_active: bool = False,
) -> AgentService:
    service = AgentService.__new__(AgentService)
    service.sessions = store
    service.runtime = runtime
    service.background_jobs = jobs
    service.delegation = delegation or _Delegation()
    service.events = _Events()
    service.room_turns = _RoomTurns(room_active)
    service.work_documents = _WorkDocuments()
    service._active_room_dispatch_authorizes_work = lambda _session_id: room_active
    return service


class AgentLifecycleCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-lifecycle-cancel-")
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        self.store = AgentSessionStore(self.db_path)
        self.store.initialize()
        self.session = self.store.create(title="lifecycle")
        self.session_id = str(self.session["id"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _approved_plan(self) -> dict[str, object]:
        draft = self.store.agent_plan(self.session_id)
        saved = self.store.mutate_agent_plan(
            self.session_id,
            {
                "action": "save",
                "expectedRevision": draft["revision"],
                "items": [{"id": "step-1", "title": "run", "status": "pending"}],
            },
        )["plan"]
        reviewed = self.store.mutate_agent_plan(
            self.session_id,
            {"action": "submit_review", "expectedRevision": saved["revision"]},
        )["plan"]
        return self.store.mutate_agent_plan(
            self.session_id,
            {"action": "approve", "expectedRevision": reviewed["revision"]},
        )["plan"]

    def _latest_lifecycle_audit(
        self,
        *,
        action: str | None = None,
    ) -> dict[str, object]:
        audits = self.store.lifecycle_cancellation_audits(self.session_id, limit=100)
        matches = [
            audit
            for audit in audits
            if action is None or audit["action"] == action
        ]
        self.assertTrue(matches)
        return matches[0]

    def test_0123_corrects_0115_backfill_at_each_resource_causal_epoch(
        self,
    ) -> None:
        migrations_0114 = Path(self.tmp.name) / "migrations-0114"
        migrations_0114.mkdir()
        migrations_0122 = Path(self.tmp.name) / "migrations-0122"
        migrations_0122.mkdir()
        for migration in load_migrations():
            if migration.version <= 114:
                shutil.copy2(migration.path, migrations_0114 / migration.path.name)
            if migration.version <= 122:
                shutil.copy2(migration.path, migrations_0122 / migration.path.name)

        upgrade_db = Path(self.tmp.name) / "lifecycle-upgrade.sqlite"
        session_id = "session-lifecycle-upgrade"
        plan_id = f"plan:{session_id}"
        goal_id = "goal-created-later"
        digest = hashlib.sha256(b"echo migration").hexdigest()
        resources = (("old", 100), ("plan", 250), ("goal", 450))
        job_ids = {
            "old": "bg_" + "1" * 32,
            "plan": "bg_" + "2" * 32,
            "goal": "bg_" + "3" * 32,
        }
        with sqlite3.connect(upgrade_db) as conn:
            apply_database_migrations(conn, migrations_dir=migrations_0114)
            conn.execute(
                """
                INSERT INTO agent_sessions(
                    id, title, session_mode, role_id, role_version, model_profile,
                    tool_profile_version, created_at_ms, updated_at_ms,
                    last_opened_at_ms, status
                ) VALUES(
                    ?, 'Lifecycle upgrade', 'assistant', 'assistant', 'v1',
                    'pi/default', 'tool-profile-v1', 1, 1, 1, 'active'
                )
                """,
                (session_id,),
            )
            conn.execute(
                """
                INSERT INTO agent_plan_events(
                    event_id, session_id, sequence, item_id, title, status,
                    created_at_ms
                ) VALUES(
                    'plan-item-approved', ?, 1, 'step-1', 'Run',
                    'pending', 190
                )
                """,
                (session_id,),
            )
            conn.executemany(
                """
                INSERT INTO agent_plan_state_events(
                    event_id, session_id, sequence, title, status, actor,
                    created_at_ms
                ) VALUES(?, ?, ?, 'Lifecycle plan', ?, 'fixture', ?)
                """,
                (
                    ("plan-approved", session_id, 1, "approved", 200),
                    ("plan-executing-later", session_id, 2, "executing", 300),
                ),
            )
            conn.executemany(
                """
                INSERT INTO agent_thread_goal_events(
                    event_id, session_id, goal_id, sequence, objective, status,
                    actor, created_at_ms
                ) VALUES(
                    ?, ?, ?, ?, 'Lifecycle goal', ?, 'fixture', ?
                )
                """,
                (
                    ("goal-active", session_id, goal_id, 1, "active", 400),
                    ("goal-paused-later", session_id, goal_id, 2, "paused", 500),
                ),
            )
            for resource_name, created_at_ms in resources:
                conn.execute(
                    """
                    INSERT INTO agent_approvals(
                        approval_id, session_id, tool_name, operation,
                        payload_sha256, preview_json, risk_level, state,
                        requested_at_ms, expires_at_ms
                    ) VALUES(
                        ?, ?, 'workspace_write', 'apply', ?, '{}', 'R2',
                        'pending', ?, 1000
                    )
                    """,
                    (
                        f"approval-{resource_name}",
                        session_id,
                        "a" * 64,
                        created_at_ms,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO agent_background_jobs(
                        job_id, session_id, label, status, command,
                        command_sha256, cwd, network_allowed, max_run_seconds,
                        log_path, created_at_ms, updated_at_ms
                    ) VALUES(
                        ?, ?, ?, 'running', 'echo migration', ?, ?, 0, 60, ?,
                        ?, ?
                    )
                    """,
                    (
                        job_ids[resource_name],
                        session_id,
                        resource_name,
                        digest,
                        self.tmp.name,
                        str(Path(self.tmp.name) / f"job-{resource_name}.log"),
                        created_at_ms,
                        created_at_ms,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO agent_subagent_batches(
                        id, parent_session_id, context_mode, state, depth,
                        max_depth, created_at_ms, updated_at_ms
                    ) VALUES(?, ?, 'fresh', 'running', 1, 2, ?, ?)
                    """,
                    (
                        f"batch-{resource_name}",
                        session_id,
                        created_at_ms,
                        created_at_ms,
                    ),
                )

            legacy_backfill = apply_database_migrations(
                conn,
                migrations_dir=migrations_0122,
            )
            self.assertIn(115, legacy_backfill.applied_versions)
            self.assertEqual(
                conn.execute(
                    """
                    SELECT causal_plan_id, causal_plan_revision,
                           causal_goal_id, causal_goal_revision
                    FROM agent_approvals
                    WHERE approval_id = 'approval-old'
                    """
                ).fetchone(),
                (plan_id, 3, goal_id, 2),
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT causal_plan_id, causal_plan_revision,
                           causal_goal_id, causal_goal_revision
                    FROM agent_background_jobs
                    WHERE job_id = ?
                    """,
                    (job_ids["plan"],),
                ).fetchone(),
                ("", 0, "", 0),
            )

            corrected = apply_database_migrations(conn)
            replay = apply_database_migrations(conn)
            self.assertEqual(corrected.applied_versions, (123, 124, 125, 126))
            self.assertEqual(replay.applied_versions, ())
            expected = {
                "old": ("", 0, "", 0),
                "plan": (plan_id, 2, "", 0),
                "goal": (plan_id, 3, goal_id, 1),
            }
            for table, key, prefix in (
                ("agent_approvals", "approval_id", "approval-"),
                ("agent_background_jobs", "job_id", "job-"),
                ("agent_subagent_batches", "id", "batch-"),
            ):
                for resource_name, _created_at_ms in resources:
                    with self.subTest(table=table, resource=resource_name):
                        identifier = (
                            job_ids[resource_name]
                            if table == "agent_background_jobs"
                            else f"{prefix}{resource_name}"
                        )
                        row = conn.execute(
                            f"""
                            SELECT causal_plan_id, causal_plan_revision,
                                   causal_goal_id, causal_goal_revision
                            FROM {table}
                            WHERE {key} = ?
                            """,
                            (identifier,),
                        ).fetchone()
                        self.assertEqual(row, expected[resource_name])

        upgraded_store = AgentSessionStore(upgrade_db)
        plan_approvals = upgraded_store.cancel_causal_approvals(
            session_id,
            request_id="migration-plan-approval-cancel",
            scope_kind="plan",
            scope_id=plan_id,
            source_revision=2,
            reason="plan cancelled",
            decided_at_ms=600,
        )
        goal_approvals = upgraded_store.cancel_causal_approvals(
            session_id,
            request_id="migration-goal-approval-cancel",
            scope_kind="goal",
            scope_id=goal_id,
            source_revision=1,
            reason="goal cancelled",
            decided_at_ms=601,
        )
        self.assertEqual(
            plan_approvals["cancelledApprovalIds"],
            ["approval-plan"],
        )
        self.assertEqual(
            goal_approvals["cancelledApprovalIds"],
            ["approval-goal"],
        )

        jobs = AgentBackgroundJobService(
            upgrade_db,
            events=lambda *args, **kwargs: None,
            execution_owner=True,
        )
        plan_jobs = jobs.cancel_causal(
            session_id,
            request_id="migration-plan-job-cancel",
            scope_kind="plan",
            scope_id=plan_id,
            source_revision=2,
            reason="plan cancelled",
        )
        goal_jobs = jobs.cancel_causal(
            session_id,
            request_id="migration-goal-job-cancel",
            scope_kind="goal",
            scope_id=goal_id,
            source_revision=1,
            reason="goal cancelled",
        )
        jobs.close()
        self.assertEqual(
            [item["jobId"] for item in plan_jobs["jobs"]],
            [job_ids["plan"]],
        )
        self.assertEqual(
            [item["jobId"] for item in goal_jobs["jobs"]],
            [job_ids["goal"]],
        )

        delegation = AgentDelegationStore(upgrade_db)
        plan_batches = delegation.request_causal_abort(
            request_id="migration-plan-batch-cancel",
            scope_kind="plan",
            scope_id=plan_id,
            source_revision=2,
            reason="plan cancelled",
            requested_at_ms=602,
        )
        goal_batches = delegation.request_causal_abort(
            request_id="migration-goal-batch-cancel",
            scope_kind="goal",
            scope_id=goal_id,
            source_revision=1,
            reason="goal cancelled",
            requested_at_ms=603,
        )
        self.assertEqual(plan_batches["batchIds"], ["batch-plan"])
        self.assertEqual(goal_batches["batchIds"], ["batch-goal"])

        with sqlite3.connect(upgrade_db) as conn:
            self.assertEqual(
                dict(
                    conn.execute(
                        "SELECT approval_id, state FROM agent_approvals"
                    )
                ),
                {
                    "approval-old": "pending",
                    "approval-plan": "stale",
                    "approval-goal": "stale",
                },
            )
            self.assertEqual(
                dict(
                    conn.execute(
                        "SELECT job_id, status FROM agent_background_jobs"
                    )
                ),
                {
                    job_ids["old"]: "running",
                    job_ids["plan"]: "cancelling",
                    job_ids["goal"]: "cancelling",
                },
            )
            self.assertEqual(
                dict(
                    conn.execute(
                        "SELECT id, state FROM agent_subagent_batches"
                    )
                ),
                {
                    "batch-old": "running",
                    "batch-plan": "aborted",
                    "batch-goal": "aborted",
                },
            )

    def test_plan_cancel_closes_admission_before_provider_turn_and_approval_owners(self) -> None:
        plan = self._approved_plan()
        self.store.record_runtime_event(
            event_id="provider-started",
            session_id=self.session_id,
            turn_id="turn-provider-1",
            sequence=1,
            event_type="status_changed",
            created_at_ms=100,
        )
        approval = self.store.create_approval(
            session_id=self.session_id,
            tool_name="workspace_write",
            operation="apply",
            payload_sha256="a" * 64,
            preview={},
            risk_level="R2",
            requested_at_ms=101,
        )
        self.assertEqual(approval["causalMetadata"]["planId"], plan["id"])
        self.assertEqual(
            approval["causalMetadata"]["planRevision"],
            plan["revision"],
        )
        self.assertEqual(
            approval["causalMetadata"]["turnId"],
            "turn-provider-1",
        )

        def assert_store_transition_first(_session_id: str) -> None:
            self.assertEqual(self.store.agent_plan(self.session_id)["status"], "cancelled")

        runtime = _Runtime(callback=assert_store_transition_first)
        service = _service(self.store, runtime=runtime, jobs=_Jobs())
        state = service.mutate_plan(
            self.session_id,
            {"action": "cancel", "expectedRevision": plan["revision"]},
        )
        self.assertNotIn("lifecycleCancellationAudit", state)
        validate_contract(state, "agent-workflow-state.v1.json")

        audit = self._latest_lifecycle_audit()
        self.assertEqual(audit["sourceTurnId"], "turn-provider-1")
        self.assertEqual(audit["state"], "completed")
        self.assertEqual(
            audit["owners"]["delegation"]["status"],
            "succeeded",
        )
        self.assertEqual(self.store.get_approval(str(approval["approvalId"]))["state"], "stale")
        serialized = json.dumps(audit, sort_keys=True).casefold()
        self.assertNotIn('"pid"', serialized)
        self.assertNotIn("processhandle", serialized)
        self.assertEqual(service.events.items[-1][1], "workflow_changed")
        self.assertTrue(any(item[1] == "lifecycle_cancellation_changed" for item in service.events.items))

    def test_completed_retry_after_restart_replays_durable_owner_receipts(self) -> None:
        plan = self._approved_plan()
        first_runtime = _Runtime()
        first_jobs = _Jobs()
        first = _service(self.store, runtime=first_runtime, jobs=first_jobs)
        first.mutate_plan(
            self.session_id,
            {"action": "cancel", "expectedRevision": plan["revision"]},
        )
        initial = self._latest_lifecycle_audit()

        restarted_runtime = _Runtime(error=AssertionError("runtime owner replayed"))
        restarted_jobs = _Jobs(error=AssertionError("job owner replayed"))
        restarted = _service(
            AgentSessionStore(self.db_path),
            runtime=restarted_runtime,
            jobs=restarted_jobs,
        )
        restarted.mutate_plan(
            self.session_id,
            {"action": "cancel", "expectedRevision": plan["revision"]},
        )
        replay = self._latest_lifecycle_audit()

        self.assertEqual(replay["requestId"], initial["requestId"])
        self.assertEqual(replay["owners"], initial["owners"])
        self.assertEqual(restarted_runtime.calls, 0)
        self.assertEqual(restarted_jobs.calls, 0)

    def test_partial_and_unknown_owner_outcomes_are_durable(self) -> None:
        plan = self._approved_plan()
        runtime = _Runtime(
            receipt={
                "turnId": "turn-provider-1",
                "lifecycle": {
                    "drained": False,
                    "failedOperationIds": ["operation-1"],
                    "pendingOperations": [],
                },
            }
        )
        service = _service(
            self.store,
            runtime=runtime,
            jobs=_Jobs(error=RuntimeError("job gateway disconnected")),
        )
        service.mutate_plan(
            self.session_id,
            {"action": "cancel", "expectedRevision": plan["revision"]},
        )
        audit = self._latest_lifecycle_audit()

        self.assertEqual(audit["state"], "partial")
        self.assertEqual(audit["owners"]["runtime"]["status"], "partial")
        self.assertEqual(audit["owners"]["job"]["status"], "unknown")
        durable = self.store.lifecycle_cancellation_audit(str(audit["requestId"]))
        self.assertEqual(durable, audit)

    def test_pending_delegation_is_a_durable_partial_owner_outcome(self) -> None:
        plan = self._approved_plan()
        delegation = _Delegation(state="requested")
        service = _service(
            self.store,
            runtime=_Runtime(),
            jobs=_Jobs(),
            delegation=delegation,
        )
        service.mutate_plan(
            self.session_id,
            {"action": "cancel", "expectedRevision": plan["revision"]},
        )
        audit = self._latest_lifecycle_audit()
        self.assertEqual(
            audit["owners"]["delegation"]["status"],
            "partial",
        )
        self.assertEqual(audit["state"], "partial")
        self.assertEqual(delegation.calls, 1)

    def test_goal_pause_and_cancel_share_coordinator_without_goal_audit_duplication(self) -> None:
        goal = self.store.mutate_agent_goal(
            self.session_id,
            {
                "action": "confirm_setup",
                "expectedRevision": 0,
                "confirmed": True,
                "objective": "finish",
            },
        )["workflow"]["goal"]
        room_approval = self.store.create_approval(
            session_id=self.session_id,
            tool_name="workspace_write",
            operation="apply",
            payload_sha256="b" * 64,
            preview={"baseState": {"roomInvocationReceiptId": "room-invocation-1"}},
            risk_level="R2",
        )
        service = _service(
            self.store,
            runtime=_Runtime(error=AssertionError("Room Runtime must not be aborted")),
            jobs=_Jobs(excluded=["bg_room"]),
            room_active=True,
        )
        paused = service.mutate_goal(
            self.session_id,
            {"action": "pause", "expectedRevision": goal["revision"]},
        )
        pause_audit = self._latest_lifecycle_audit(action="pause")
        self.assertEqual(pause_audit["action"], "pause")
        self.assertEqual(pause_audit["owners"]["runtime"]["status"], "excluded")
        self.assertEqual(
            pause_audit["owners"]["delegation"]["status"],
            "excluded",
        )
        self.assertIsNone(paused["goal"]["cancellationAudit"])
        self.assertEqual(self.store.get_approval(str(room_approval["approvalId"]))["state"], "pending")

        resumed = self.store.mutate_agent_goal(
            self.session_id,
            {"action": "resume", "expectedRevision": paused["goal"]["revision"]},
        )["workflow"]["goal"]
        cancelled = service.mutate_goal(
            self.session_id,
            {
                "action": "cancel",
                "expectedRevision": resumed["revision"],
                "reason": "operator stopped the Goal",
            },
        )
        cancel_audit = self._latest_lifecycle_audit(action="cancel")
        self.assertEqual(cancel_audit["action"], "cancel")
        self.assertIsNotNone(cancelled["goal"]["cancellationAudit"])
        self.assertNotEqual(
            cancelled["goal"]["cancellationAudit"]["auditId"],
            cancel_audit["requestId"],
        )

    def test_background_job_inherits_causal_metadata_from_approval(self) -> None:
        plan = self._approved_plan()
        approval = self.store.create_approval(
            session_id=self.session_id,
            tool_name="workspace_job",
            operation="start",
            payload_sha256="c" * 64,
            preview={},
            risk_level="R2",
        )
        approval = self.store.decide_approval(
            str(approval["approvalId"]),
            approved=True,
            payload_sha256=str(approval["payloadSha256"]),
        )

        class FailingHarness:
            def spawn_background(self, _prepared):
                raise RuntimeError("launch deliberately stopped")

        jobs = AgentBackgroundJobService(
            self.db_path,
            events=lambda *args, **kwargs: None,
            workspace_harness=FailingHarness(),
            execution_owner=True,
        )
        prepared = PreparedWorkspaceCommand(
            command="echo causal",
            cwd=Path(self.tmp.name),
            roots=(Path(self.tmp.name),),
            timeout_seconds=60,
            allow_network=False,
        )
        with self.assertRaises(AgentBackgroundJobError):
            jobs.start(
                self.session_id,
                prepared,
                approval_id=str(approval["approvalId"]),
            )
        failed = jobs.list(self.session_id)["items"][0]
        self.assertEqual(failed["causalMetadata"]["planId"], plan["id"])
        self.assertEqual(
            failed["causalMetadata"]["planRevision"],
            plan["revision"],
        )

    def test_plan_cancellation_fences_start_blocked_after_process_spawn(self) -> None:
        plan = self._approved_plan()
        approval = self.store.create_approval(
            session_id=self.session_id,
            tool_name="workspace_job",
            operation="start",
            payload_sha256="d" * 64,
            preview={},
            risk_level="R2",
        )
        approval = self.store.decide_approval(
            str(approval["approvalId"]),
            approved=True,
            payload_sha256=str(approval["payloadSha256"]),
        )

        class BlockingHarness(WorkspaceHarness):
            def __init__(self) -> None:
                super().__init__()
                self.spawned = threading.Event()
                self.release = threading.Event()
                self.launched = None

            def spawn_background(self, prepared):
                self.launched = super().spawn_background(prepared)
                self.spawned.set()
                if not self.release.wait(timeout=5):
                    raise TimeoutError("cancellation race release timed out")
                return self.launched

        harness = BlockingHarness()
        jobs = AgentBackgroundJobService(
            self.db_path,
            events=lambda *_args, **_kwargs: None,
            workspace_harness=harness,
        )
        prepared = PreparedWorkspaceCommand(
            command="python3 -c \"import time; time.sleep(30)\"",
            cwd=Path(self.tmp.name),
            roots=(Path(self.tmp.name),),
            timeout_seconds=60,
            allow_network=False,
        )
        failures: list[BaseException] = []

        def start() -> None:
            try:
                jobs.start(
                    self.session_id,
                    prepared,
                    approval_id=str(approval["approvalId"]),
                )
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=start)
        thread.start()
        try:
            self.assertTrue(harness.spawned.wait(timeout=5))
            request = {
                "requestId": "lifecycle-race-plan-cancel",
                "scopeKind": "plan",
                "scopeId": str(plan["id"]),
                "sourceRevision": int(plan["revision"]),
                "action": "cancel",
                "reason": "race regression",
                "sourceTurnId": "",
            }
            self.store.mutate_agent_plan(
                self.session_id,
                {
                    "action": "cancel",
                    "expectedRevision": plan["revision"],
                },
                lifecycle_request=request,
            )
            jobs.cancel_causal(
                self.session_id,
                request_id=str(request["requestId"]),
                scope_kind="plan",
                scope_id=str(plan["id"]),
                source_revision=int(plan["revision"]),
                reason="race regression",
            )
        finally:
            harness.release.set()
            thread.join(timeout=5)
            jobs.close()

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], AgentBackgroundJobError)
        self.assertIn("causal lifecycle was cancelled", str(failures[0]))
        self.assertIsNotNone(harness.launched.process.poll())
        failed = jobs.list(self.session_id)["items"][0]
        self.assertEqual(failed["status"], "failed")
        self.assertGreater(failed["endedAtMs"], 0)

    def test_background_job_cancellation_is_causal_and_excludes_room_and_unrelated_jobs(self) -> None:
        plan_id = f"plan:{self.session_id}"
        digest = hashlib.sha256(b"echo test").hexdigest()
        rows = [
            ("bg_" + "1" * 32, plan_id, 7, 0),
            ("bg_" + "2" * 32, plan_id, 8, 0),
            ("bg_" + "3" * 32, plan_id, 7, 1),
        ]
        with sqlite3.connect(self.db_path) as conn:
            for index, (job_id, causal_plan_id, revision, room_bound) in enumerate(rows):
                conn.execute(
                    """
                    INSERT INTO agent_background_jobs(
                        job_id, session_id, label, status, command, command_sha256,
                        cwd, network_allowed, max_run_seconds, log_path,
                        causal_plan_id, causal_plan_revision, room_bound,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, 'running', 'echo test', ?, ?, 0, 60, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        self.session_id,
                        f"job-{index}",
                        digest,
                        self.tmp.name,
                        str(Path(self.tmp.name) / f"{job_id}.log"),
                        causal_plan_id,
                        revision,
                        room_bound,
                        200 + index,
                        200 + index,
                    ),
                )
        jobs = AgentBackgroundJobService(
            self.db_path,
            events=lambda *args, **kwargs: None,
            execution_owner=True,
        )
        receipt = jobs.cancel_causal(
            self.session_id,
            request_id="lifecycle:test-job",
            scope_kind="plan",
            scope_id=plan_id,
            source_revision=7,
            reason="plan_cancelled",
        )

        self.assertEqual(receipt["excludedRoomBoundJobIds"], ["bg_" + "3" * 32])
        self.assertEqual([item["jobId"] for item in receipt["jobs"]], ["bg_" + "1" * 32])
        replay = jobs.cancel_causal(
            self.session_id,
            request_id="lifecycle:test-job",
            scope_kind="plan",
            scope_id=plan_id,
            source_revision=7,
            reason="plan_cancelled",
        )
        self.assertEqual(replay["jobs"], receipt["jobs"])
        with sqlite3.connect(self.db_path) as conn:
            states = dict(conn.execute("SELECT job_id, status FROM agent_background_jobs"))
        self.assertEqual(states["bg_" + "1" * 32], "cancelling")
        self.assertEqual(states["bg_" + "2" * 32], "running")
        self.assertEqual(states["bg_" + "3" * 32], "running")

    def test_delegation_owner_aborts_matching_running_children_and_replays_receipt(self) -> None:
        plan_id = f"plan:{self.session_id}"
        delegation_store = AgentDelegationStore(self.db_path)
        delegation_store.initialize()

        def create_batch(*, revision: int, room_bound: bool):
            child = self.store.create(
                title=f"child-{revision}-{room_bound}",
                session_kind="subagent_runtime",
            )
            return delegation_store.create_batch(
                parent_session_id=self.session_id,
                parent_run_id="",
                context_mode="fresh",
                depth=1,
                max_depth=2,
                causal_metadata={
                    "planId": plan_id,
                    "planRevision": revision,
                    "goalId": "",
                    "goalRevision": 0,
                    "roomBound": room_bound,
                },
                runs=[
                    {
                        "childSessionId": child["id"],
                        "templateId": "worker",
                        "templateVersion": "1",
                        "task": "delegated lifecycle work",
                        "expectedOutput": "receipt",
                        "acceptanceCriteria": ["child is stopped"],
                        "outputSchema": {},
                        "planItemId": "step-1",
                        "planItemTitle": "run child",
                        "maxTurns": 1,
                        "maxToolCalls": 1,
                        "maxTotalTokens": 256,
                        "maxDurationMs": 1_000,
                        "maxOutputChars": 256,
                    }
                ],
            )

        target = create_batch(revision=7, room_bound=False)
        unrelated = create_batch(revision=8, room_bound=False)
        room_bound = create_batch(revision=7, room_bound=True)
        target_run = delegation_store.start_run(
            str(target["runs"][0]["id"])
        )
        terminal = threading.Event()

        class DelegatedRuntime:
            def __init__(self) -> None:
                self.calls = 0

            def abort(self, _session_id: str) -> None:
                self.calls += 1
                delegation_store.finish_run(
                    str(target_run["id"]),
                    state="aborted",
                    error="Parent lifecycle cancelled",
                )
                terminal.set()

            def stop(self) -> None:
                return None

        runtime = DelegatedRuntime()
        active = _ActiveDelegatedRun(
            runtime=runtime,
            child_session_id=str(target_run["childSessionId"]),
            terminal=terminal,
            forced=threading.Event(),
            lock=threading.RLock(),
        )
        coordinator = AgentDelegationCoordinator.__new__(
            AgentDelegationCoordinator
        )
        coordinator.store = delegation_store
        coordinator._lock = threading.RLock()
        coordinator._active_runs = {str(target_run["id"]): active}
        coordinator._cancellation_grace_ms = 50
        coordinator._schedule_pending_result_contexts = lambda: None

        receipt = coordinator.cancel_causal(
            self.session_id,
            request_id="lifecycle:test-delegation",
            scope_kind="plan",
            scope_id=plan_id,
            source_revision=7,
            reason="plan_cancelled",
        )
        self.assertEqual(receipt["state"], "terminated")
        self.assertEqual(runtime.calls, 1)
        self.assertEqual(
            delegation_store.get_run(str(target_run["id"]))["state"],
            "aborted",
        )
        self.assertEqual(
            delegation_store.get_batch(str(unrelated["id"]))["state"],
            "queued",
        )
        self.assertEqual(
            delegation_store.get_batch(str(room_bound["id"]))["state"],
            "queued",
        )
        self.assertEqual(
            receipt["excludedRoomBoundBatchIds"],
            [room_bound["id"]],
        )

        replay = coordinator.cancel_causal(
            self.session_id,
            request_id="lifecycle:test-delegation",
            scope_kind="plan",
            scope_id=plan_id,
            source_revision=7,
            reason="plan_cancelled",
        )
        self.assertEqual(replay["batches"], receipt["batches"])
        self.assertEqual(runtime.calls, 1)

    def test_reconnect_snapshot_projection_is_separate_from_goal_cancellation_audit(self) -> None:
        plan = self._approved_plan()
        service = _service(self.store, runtime=_Runtime(), jobs=_Jobs())
        service.mutate_plan(
            self.session_id,
            {"action": "cancel", "expectedRevision": plan["revision"]},
        )
        audit = self._latest_lifecycle_audit()
        projection = self.store.lifecycle_cancellation_audits(self.session_id)
        self.assertEqual(projection[0]["requestId"], audit["requestId"])
        self.assertNotIn("cancellationAudit", projection[0])


if __name__ == "__main__":
    unittest.main()
