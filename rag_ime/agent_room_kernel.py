from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from .agent_room_capabilities import (
    REVIEW_FINDING_BLOCKING_CATEGORIES,
    REVIEW_FINDING_GOVERNANCE_INVARIANTS,
    REVIEW_FINDING_RE_REVIEW_EXCEPTION_CATEGORIES,
    canonical_review_finding_fingerprint,
    runtime_evidence_refs_for_dispatch,
)
from .agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    KERNEL_RECEIPT_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOM_SCREEN_STATE_SCHEMA_VERSION,
    upcast_room_commit,
    upcast_room_root_execution,
    validate_kernel_contract,
)
from .agent_room_projection_identity import room_projection_hash
from .agent_room_quality_gate import (
    RoomQualityGateError,
    validate_quality_gate_receipt,
)
from .db import apply_database_migrations
from .room_domain.completion import CompletionFacts, evaluate_completion
from .room_domain.model import DomainPolicyError
from .room_domain.scheduling import (
    dependent_closure,
    dependency_ids as domain_dependency_ids,
    derived_task_waves,
    payload_depends_on as domain_payload_depends_on,
    runnable_frontier,
    validate_task_graph,
)
from .room_domain.waiting import (
    ManagedRetryWaitFacts,
    match_managed_retry_wait,
)
from .room_domain.settlement import SettlementFacts, settle_dispatch
from .room_domain.events import past_tense_event
from .room_application.repositories import RoomDomainEventRepository
from .room_application.plans import RoomPlanRepository


KernelMode = Literal["off", "shadow", "cohort", "test", "kernel_only"]
# Modes in which the Kernel is the single authoritative Room execution path.
# `test` runs the same machinery inside unit tests but never claims production
# authority; `shadow` observes legacy traffic; `off` disables the Kernel.
_AUTHORITATIVE_KERNEL_MODES = frozenset({"cohort", "kernel_only"})


def kernel_owns_room_execution(mode: object) -> bool:
    """True when the Kernel owns the authoritative Room execution path.

    Every caller used to spell this as `mode in {"cohort", "kernel_only"}`,
    which left eight copies of the same policy across five modules and no
    single place to answer "what does managed mean" when a mode is added.
    This predicate is that place; it is deliberately a pure function on the
    mode value, not state on the persistence store.
    """

    return str(mode) in _AUTHORITATIVE_KERNEL_MODES
_ACTIVE_DISPATCH_STATES = ("pending", "leased", "running", "retry_wait", "timer_wait")
_SESSION_OCCUPYING_DISPATCH_STATES = ("leased", "running")
_TERMINAL_TASK_STATES = ("completed", "failed", "cancelled")
SYSTEM_MAX_HOPS = 12
SYSTEM_MAX_DEPTH = 4
SYSTEM_MAX_BUDGET = 1_000
SYSTEM_MAX_WALL_CLOCK_MS = 14_400_000
SYSTEM_MAX_INPUT_TOKENS = 2_000_000
SYSTEM_MAX_OUTPUT_TOKENS = 500_000
SYSTEM_MAX_DISPATCHES = 64
SYSTEM_MAX_CONCURRENCY = 4
SYSTEM_MAX_TOOL_CALLS = 500
SYSTEM_MAX_TOOL_COST = 100_000
SYSTEM_MAX_RETRIES = 8
SYSTEM_MAX_REPAIRS = 4
RUNTIME_RETRY_BASE_DELAY_MS = 1_000
RUNTIME_RETRY_MAX_DELAY_MS = 30_000
DISPATCH_INPUT_TOKEN_RESERVATION = 64_000
DISPATCH_OUTPUT_TOKEN_RESERVATION = 16_000
DISPATCH_TOOL_CALL_RESERVATION = 64
DISPATCH_TOOL_COST_RESERVATION = 10_000
_ABORT_SURFACES = (
    "queued",
    "running",
    "provider",
    "tool",
    "exec",
    "process",
    "retry",
    "compaction",
    "branch_summary",
    "timer",
    "continuation",
    "session",
)
_RUNTIME_CANCEL_SURFACES = (
    "provider",
    "tool",
    "exec",
    "retry",
    "compaction",
    "branch_summary",
    "timer",
    "continuation",
    "session",
)
_WORKSPACE_INTEGRATION_RECEIPT_FIELDS = (
    "workspaceDeliveryReceiptId",
    "workspaceDeliveryReceiptSha256",
    "workspaceSourceLeaseReceiptId",
    "workspaceSourceLeaseReceiptSha256",
    "workspaceTargetAppliedReceiptId",
    "workspaceTargetAppliedReceiptSha256",
    "workspaceIntegratedReceiptId",
    "workspaceIntegratedReceiptSha256",
    "workspaceWriterQuiescenceReceiptId",
    "workspaceWriterQuiescenceReceiptSha256",
    "workspaceQuarantineReceiptId",
    "workspaceQuarantineReceiptSha256",
    "workspaceRemovalAuthorizationReceiptId",
    "workspaceRemovalAuthorizationReceiptSha256",
    "workspaceVaultReceiptId",
    "workspaceVaultReceiptSha256",
    "workspaceCleanupReceiptId",
    "workspaceCleanupReceiptSha256",
)


class RoomKernelFenceError(RuntimeError):
    pass


class RoomKernelStore:
    """Canonical durable Room state machine behind the product command bus.

    Production remains disabled until every release gate passes. Legacy
    Intercom, WorkItem, mention, and wake paths may normalize into this store,
    but they cannot become a second execution authority.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        mode: KernelMode = "shadow",
        enforce_test_delivery_gate: bool = False,
        commit_work_document_delta: Callable[
            [sqlite3.Connection, Mapping[str, object]], object
        ]
        | None = None,
    ) -> None:
        if mode not in {"off", "shadow", "cohort", "test", "kernel_only"}:
            raise ValueError("Room Kernel mode must be off, shadow, cohort, test, or kernel_only")
        self.db_path = Path(db_path)
        self.mode = mode
        self.enforce_test_delivery_gate = bool(enforce_test_delivery_gate)
        self.commit_work_document_delta = commit_work_document_delta
        if self.enforce_test_delivery_gate and self.mode != "cohort":
            raise ValueError("DeliveryGate enforcement is only valid for the explicit cohort mode")

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect(immediate=True) as conn:
            result = apply_database_migrations(conn)
            self._repair_cancelled_root_task_states(conn)
        return result.current_version

    @staticmethod
    def _repair_cancelled_root_task_states(conn: sqlite3.Connection) -> int:
        """Seal tasks resurrected by historical workspace lifecycle projection."""

        rows = conn.execute(
            """SELECT task.task_id,task.payload_json,root.updated_at_ms
               FROM room_kernel_tasks task
               JOIN room_kernel_roots root ON root.root_id=task.root_id
               WHERE root.state IN ('cancelled','cancelled_with_unknowns')
                 AND task.state NOT IN ('completed','failed','cancelled')"""
        ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                payload = {}
            payload["state"] = "cancelled"
            payload["revision"] = int(payload.get("revision") or 0) + 1
            conn.execute(
                """UPDATE room_kernel_tasks
                   SET state='cancelled',payload_json=?,updated_at_ms=?
                   WHERE task_id=?
                     AND state NOT IN ('completed','failed','cancelled')""",
                (
                    _json(payload),
                    int(row["updated_at_ms"]),
                    str(row["task_id"]),
                ),
            )
        return len(rows)

    def create_root(
        self,
        payload: Mapping[str, object],
        *,
        budget: int,
        max_hops: int,
        max_depth: int,
        acceptance_criteria: tuple[str, ...] = (),
        now_ms: int,
    ) -> dict[str, object]:
        """Create a non-atomic Root fixture in explicit test mode only.

        Product callers must use ``create_root_with_task`` so a Root can never
        become visible without its authoritative first Task.
        """

        if self.mode != "test":
            raise RoomKernelFenceError(
                "non-atomic create_root is test-only; use create_root_with_task"
            )
        validate_kernel_contract("rootExecution", payload)
        budget = _non_negative(budget, "budget")
        max_hops = _non_negative(max_hops, "max_hops")
        max_depth = _non_negative(max_depth, "max_depth")
        if budget > SYSTEM_MAX_BUDGET or max_hops > SYSTEM_MAX_HOPS or max_depth > SYSTEM_MAX_DEPTH:
            raise RoomKernelFenceError("Root limits exceed system safety ceiling")
        root_id = str(payload["rootId"])
        encoded = _json(payload)
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO room_kernel_roots(
                    root_id, room_id, generation, state,
                    facilitator_participant_id, reporter_participant_id,
                    reporter_selection_receipt_id, requirement_anchor_ref,
                    budget_remaining, budget_reserved, max_hops, max_depth,
                    acceptance_criteria_json, covered_criteria_json,
                    terminal_receipt_id, payload_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, '[]', NULL, ?, ?, ?)
                """,
                (
                    root_id,
                    str(payload["roomId"]),
                    int(payload["generation"]),
                    str(payload["state"]),
                    str(payload["facilitatorParticipantId"]),
                    payload.get("reporterParticipantId"),
                    payload.get("reporterSelectionReceiptId"),
                    str(payload["requirementAnchorRef"]),
                    budget,
                    max_hops,
                    max_depth,
                    _json(sorted(set(acceptance_criteria))),
                    encoded,
                    int(now_ms),
                    int(now_ms),
                ),
            )
            self._record_review_policy_locked(
                conn,
                root_id=root_id,
                required=bool(payload.get("independentReviewRequired")),
                source="root_creation",
                generation=int(payload["generation"]),
                now_ms=now_ms,
            )
            self._insert_root_limits(conn, root_id, now_ms=now_ms)
        return self.root(root_id)

    def create_task(self, payload: Mapping[str, object], *, now_ms: int) -> dict[str, object]:
        validate_kernel_contract("roomTask", payload)
        with self._connect(immediate=True) as conn:
            self._insert_task(conn, payload, now_ms=now_ms)
        return self.task(str(payload["taskId"]))

    def _insert_task(
        self,
        conn: sqlite3.Connection,
        payload: Mapping[str, object],
        *,
        now_ms: int,
    ) -> tuple[dict[str, object], bool]:
        validate_kernel_contract("roomTask", payload)
        root = self._root_row(conn, str(payload["rootId"]))
        task_criteria = _criteria(payload.get("acceptanceCriterionIds"))
        _assert_criteria_within(
            task_criteria,
            _criteria(json.loads(str(root["acceptance_criteria_json"]))),
            scope="Root",
        )
        parent_task_id = payload.get("parentTaskId")
        if parent_task_id is not None:
            parent = conn.execute(
                "SELECT root_id, payload_json FROM room_kernel_tasks WHERE task_id=?",
                (str(parent_task_id),),
            ).fetchone()
            if parent is None or str(parent["root_id"]) != str(root["root_id"]):
                raise RoomKernelFenceError("child Task parent belongs to another Root")
            parent_payload = json.loads(str(parent["payload_json"]))
            _assert_criteria_within(
                task_criteria,
                _criteria(parent_payload.get("acceptanceCriterionIds")),
                scope="parent Task",
            )
        encoded = _json(payload)
        existing = conn.execute(
            "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
            (str(payload["taskId"]),),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_json"]) != encoded:
                raise RoomKernelFenceError("Room Task identity was rebound")
            return dict(payload), False
        conn.execute(
            """
            INSERT INTO room_kernel_tasks(
                task_id, root_id, parent_task_id, state,
                current_owner_participant_id, ownership_revision,
                ownership_receipt_id, task_kind, invitation_id, review_state,
                payload_json, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload["taskId"]),
                str(payload["rootId"]),
                parent_task_id,
                str(payload["state"]),
                str(payload["currentOwnerParticipantId"]),
                int(payload["ownershipRevision"]),
                payload.get("ownershipReceiptId"),
                # ``task_kind`` predates typed integration/report semantics and
                # is an unused compatibility projection with a legacy CHECK.
                # ``payload_json.taskKind`` is the contract authority.
                (
                    "work"
                    if str(payload["taskKind"]) in {"report", "integration"}
                    else str(payload["taskKind"])
                ),
                payload.get("invitationId"),
                str(payload["reviewState"]),
                encoded,
                int(now_ms),
            ),
        )
        return dict(payload), True

    def _apply_task_transfer(
        self,
        conn: sqlite3.Connection,
        *,
        task_payload: Mapping[str, object],
        task_transfer: Mapping[str, object],
        dispatch: sqlite3.Row,
        root: sqlite3.Row,
        commit_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        task_id = str(task_transfer["taskId"])
        from_participant_id = str(task_transfer["fromParticipantId"])
        to_participant_id = str(task_transfer["toParticipantId"])
        ownership_revision = int(task_transfer["ownershipRevision"])
        if task_id != str(task_payload["taskId"]):
            raise RoomKernelFenceError("Task transfer targets another Task")
        if from_participant_id == to_participant_id:
            raise RoomKernelFenceError("Task transfer must change the current owner")
        if from_participant_id != str(
            task_payload["currentOwnerParticipantId"]
        ):
            raise RoomKernelFenceError("Task transfer source is not the current owner")
        if ownership_revision != int(task_payload["ownershipRevision"]) + 1:
            raise RoomKernelFenceError("Task transfer ownership revision is stale")
        acceptance_criteria = _criteria(
            task_transfer.get("acceptanceCriterionIds")
        )
        _assert_criteria_within(
            acceptance_criteria,
            _criteria(task_payload.get("acceptanceCriterionIds")),
            scope="transferred Task",
        )
        context_evidence_refs = _unique_text(
            [
                *(task_payload.get("contextEvidenceRefs") or []),
                *(task_transfer.get("contextEvidenceRefs") or []),
            ]
        )[:32]
        stale_dispatch_ids = [
            str(row["dispatch_id"])
            for row in conn.execute(
                f"""
                SELECT dispatch_id
                FROM room_kernel_dispatches
                WHERE task_id=? AND dispatch_id!=?
                  AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})
                ORDER BY dispatch_id
                """,
                (
                    task_id,
                    dispatch["dispatch_id"],
                    *_ACTIVE_DISPATCH_STATES,
                ),
            ).fetchall()
        ]
        runtime_targets = (
            conn.execute(
                f"""
                SELECT dispatch_id, session_id
                FROM room_kernel_runtime_effects
                WHERE root_id=?
                  AND dispatch_id IN (
                      {','.join('?' for _ in stale_dispatch_ids)}
                  )
                  AND state IN ('intent','accepted','unknown')
                """,
                (root["root_id"], *stale_dispatch_ids),
            ).fetchall()
            if stale_dispatch_ids
            else []
        )
        if stale_dispatch_ids:
            self._cancel_dispatch_ids(
                conn,
                stale_dispatch_ids,
                now_ms=now_ms,
            )
        runtime_dispatch_ids = {
            str(target["dispatch_id"]) for target in runtime_targets
        }
        for target in runtime_targets:
            self._enqueue_cancel(
                conn,
                root_id=str(root["root_id"]),
                dispatch_id=str(target["dispatch_id"]),
                session_id=str(target["session_id"]),
                generation=int(root["generation"]),
                terminalize_root=False,
                now_ms=now_ms,
            )
        for stale_dispatch_id in (
            set(stale_dispatch_ids) - runtime_dispatch_ids
        ):
            conn.execute(
                "UPDATE room_kernel_abort_scopes "
                "SET state='cancelled',updated_at_ms=? WHERE dispatch_id=? "
                "AND state IN ('registered','cancelling','unknown')",
                (int(now_ms), stale_dispatch_id),
            )
            self._settle_dispatch_limits(
                conn,
                stale_dispatch_id,
                usage=None,
                consumed=False,
                now_ms=now_ms,
            )
        receipt = self._receipt(
            conn,
            root_id=str(root["root_id"]),
            command_id=None,
            receipt_kind="accepted",
            status="applied",
            generation=int(root["generation"]),
            details={
                "operation": "task_owner_transfer",
                "taskId": task_id,
                "fromParticipantId": from_participant_id,
                "toParticipantId": to_participant_id,
                "ownershipRevision": ownership_revision,
                "sourceDispatchId": str(dispatch["dispatch_id"]),
                "sourceCommitId": commit_id,
                "supersededDispatchIds": stale_dispatch_ids,
                "cancelIntents": len(runtime_targets),
            },
            now_ms=now_ms,
        )
        updated = dict(task_payload)
        updated.update(
            {
                "currentOwnerParticipantId": to_participant_id,
                "ownershipRevision": ownership_revision,
                "ownershipReceiptId": receipt["receiptId"],
                "objective": str(task_transfer["objective"]),
                "expectedOutput": str(task_transfer["expectedOutput"]),
                "acceptanceCriterionIds": list(acceptance_criteria),
                "contextEvidenceRefs": context_evidence_refs,
                "revision": int(task_payload.get("revision") or 0) + 1,
                "state": "active",
            }
        )
        validate_kernel_contract("roomTask", updated)
        conn.execute(
            """
            INSERT INTO room_kernel_task_owner_transitions(
                receipt_id, root_id, task_id, ownership_revision,
                from_participant_id, to_participant_id,
                source_dispatch_id, source_commit_id, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt["receiptId"],
                root["root_id"],
                task_id,
                ownership_revision,
                from_participant_id,
                to_participant_id,
                dispatch["dispatch_id"],
                commit_id,
                int(now_ms),
            ),
        )
        conn.execute(
            """
            UPDATE room_kernel_tasks
            SET state=?, current_owner_participant_id=?,
                ownership_revision=?, ownership_receipt_id=?,
                payload_json=?, updated_at_ms=?
            WHERE task_id=?
            """,
            (
                "active",
                to_participant_id,
                ownership_revision,
                receipt["receiptId"],
                _json(updated),
                int(now_ms),
                task_id,
            ),
        )
        return receipt

    def create_root_with_task(
        self,
        root_payload: Mapping[str, object],
        task_payload: Mapping[str, object],
        *,
        budget: int,
        max_hops: int,
        max_depth: int,
        acceptance_criteria: tuple[str, ...] = (),
        now_ms: int,
    ) -> dict[str, object]:
        """Create the product Root and its first Task in one transaction."""

        validate_kernel_contract("rootExecution", root_payload)
        validate_kernel_contract("roomTask", task_payload)
        if task_payload.get("rootId") != root_payload.get("rootId"):
            raise RoomKernelFenceError("initial Task belongs to another Root")
        _assert_criteria_within(
            _criteria(task_payload.get("acceptanceCriterionIds")),
            _criteria(acceptance_criteria),
            scope="Root",
        )
        budget = _non_negative(budget, "budget")
        max_hops = _non_negative(max_hops, "max_hops")
        max_depth = _non_negative(max_depth, "max_depth")
        if budget > SYSTEM_MAX_BUDGET or max_hops > SYSTEM_MAX_HOPS or max_depth > SYSTEM_MAX_DEPTH:
            raise RoomKernelFenceError("Root limits exceed system safety ceiling")
        root_id = str(root_payload["rootId"])
        task_id = str(task_payload["taskId"])
        with self._connect(immediate=True) as conn:
            existing_root = conn.execute(
                """SELECT payload_json,budget_remaining,budget_reserved,max_hops,max_depth,
                          acceptance_criteria_json
                   FROM room_kernel_roots WHERE root_id=?""",
                (root_id,),
            ).fetchone()
            existing_task = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if existing_root is not None or existing_task is not None:
                existing_payload = (
                    json.loads(str(existing_root["payload_json"]))
                    if existing_root is not None
                    else None
                )
                incoming_payload = dict(root_payload)
                if (
                    isinstance(existing_payload, dict)
                    and incoming_payload.get("reporterParticipantId")
                    and existing_payload.get("reporterParticipantId")
                ):
                    # The selection receipt is generated durably below; it is
                    # deliberately excluded from the caller's replay identity.
                    existing_payload["reporterSelectionReceiptId"] = None
                    incoming_payload["reporterSelectionReceiptId"] = None
                if (
                    existing_root is None
                    or existing_task is None
                    or existing_payload != incoming_payload
                    or json.loads(str(existing_task["payload_json"]))
                    != dict(task_payload)
                    or int(existing_root["budget_remaining"]) != budget
                    or int(existing_root["budget_reserved"]) != 0
                    or int(existing_root["max_hops"]) != max_hops
                    or int(existing_root["max_depth"]) != max_depth
                    or json.loads(str(existing_root["acceptance_criteria_json"]))
                    != sorted(set(acceptance_criteria))
                ):
                    raise RoomKernelFenceError(
                        "Root/Task creation identity conflicts with durable state"
                    )
                return {"root": self.root(root_id), "task": self.task(task_id)}
            conn.execute(
                """
                INSERT INTO room_kernel_roots(
                    root_id, room_id, generation, state,
                    facilitator_participant_id, reporter_participant_id,
                    reporter_selection_receipt_id, requirement_anchor_ref,
                    budget_remaining, budget_reserved, max_hops, max_depth,
                    acceptance_criteria_json, covered_criteria_json,
                    terminal_receipt_id, payload_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, '[]', NULL, ?, ?, ?)
                """,
                (
                    root_id,
                    str(root_payload["roomId"]),
                    int(root_payload["generation"]),
                    str(root_payload["state"]),
                    str(root_payload["facilitatorParticipantId"]),
                    root_payload.get("reporterParticipantId"),
                    root_payload.get("reporterSelectionReceiptId"),
                    str(root_payload["requirementAnchorRef"]),
                    budget,
                    max_hops,
                    max_depth,
                    _json(sorted(set(acceptance_criteria))),
                    _json(root_payload),
                    int(now_ms),
                    int(now_ms),
                ),
            )
            reporter_id = str(root_payload.get("reporterParticipantId") or "").strip()
            if reporter_id:
                selection_receipt = self._receipt(
                    conn,
                    root_id=root_id,
                    command_id=None,
                    receipt_kind="accepted",
                    status="applied",
                    generation=int(root_payload["generation"]),
                    details={
                        "purpose": "reporter_selection",
                        "reporterParticipantId": reporter_id,
                        "facilitatorParticipantId": str(
                            root_payload["facilitatorParticipantId"]
                        ),
                    },
                    now_ms=int(now_ms),
                )
                payload_with_receipt = dict(root_payload)
                payload_with_receipt["reporterSelectionReceiptId"] = (
                    selection_receipt["receiptId"]
                )
                conn.execute(
                    """
                    UPDATE room_kernel_roots
                    SET reporter_selection_receipt_id = ?, payload_json = ?
                    WHERE root_id = ?
                    """,
                    (
                        selection_receipt["receiptId"],
                        _json(payload_with_receipt),
                        root_id,
                    ),
                )
            self._record_review_policy_locked(
                conn,
                root_id=root_id,
                required=bool(root_payload.get("independentReviewRequired")),
                source="root_creation",
                generation=int(root_payload["generation"]),
                now_ms=now_ms,
            )
            self._record_intake_phase_locked(
                conn,
                root_id=root_id,
                phase="aligning",
                clarification_occurred=False,
                source="root_creation",
                generation=int(root_payload["generation"]),
                details={},
                now_ms=now_ms,
            )
            self._insert_task(conn, task_payload, now_ms=now_ms)
            self._insert_root_limits(conn, root_id, now_ms=now_ms)
        return {"root": self.root(root_id), "task": self.task(task_id)}

    def normalize_legacy_dispatch(
        self,
        dispatch: Mapping[str, object],
        *,
        source_kind: str,
        source_id: str,
        now_ms: int,
    ) -> tuple[dict[str, object], bool]:
        """Normalize every old entry path to one shadow command and outbox row."""

        validate_kernel_contract("dispatchEnvelope", dispatch)
        root_id = str(dispatch["rootId"])
        idempotency_key = str(dispatch["idempotencyKey"])
        command_id = _stable_id("room-command", root_id, idempotency_key)
        command = {
            "schemaVersion": KERNEL_COMMAND_SCHEMA_VERSION,
            "commandId": command_id,
            "rootId": root_id,
            "roomId": str(self.root(root_id)["roomId"]),
            "commandKind": "dispatch",
            "targetKind": "dispatch",
            "targetId": str(dispatch["dispatchId"]),
            "sourceKind": _required(source_kind, "source_kind"),
            "sourceId": _required(source_id, "source_id"),
            "idempotencyKey": idempotency_key,
            "generation": int(dispatch["generation"]),
            "payload": dict(dispatch),
            "createdAtMs": int(now_ms),
        }
        validate_kernel_contract("kernelCommand", command)
        if self.mode == "off":
            return command, False

        with self._connect(immediate=True) as conn:
            existing_ref = conn.execute(
                """SELECT command_id FROM room_kernel_compatibility_refs
                   WHERE source_kind = ? AND source_id = ?""",
                (source_kind, source_id),
            ).fetchone()
            if existing_ref is not None and str(existing_ref["command_id"]) != command_id:
                raise RoomKernelFenceError("legacy source identity changed canonical command")
            existing = conn.execute(
                "SELECT payload_json FROM room_kernel_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            created = existing is None
            if existing is None:
                conn.execute(
                    """INSERT INTO room_kernel_commands(
                       command_id, root_id, room_id, idempotency_key, command_kind,
                       payload_json, created_at_ms) VALUES (?, ?, ?, ?, 'dispatch', ?, ?)""",
                    (command_id, root_id, command["roomId"], idempotency_key, _json(command), int(now_ms)),
                )
                self._enqueue_dispatch(
                    conn,
                    dispatch,
                    shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
                    now_ms=now_ms,
                )
            conn.execute(
                """INSERT INTO room_kernel_compatibility_refs(
                   source_kind, source_id, command_id, observed_at_ms)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source_kind, source_id) DO UPDATE SET
                     observed_at_ms = MAX(observed_at_ms, excluded.observed_at_ms)
                   WHERE command_id = excluded.command_id""",
                (source_kind, source_id, command_id, int(now_ms)),
            )
        return command, created

    def normalize_compatibility_entry(
        self,
        dispatch: Mapping[str, object],
        *,
        room_binding_ref: Mapping[str, object] | None,
        source_kind: Literal["intercom", "work_item", "mention", "wake", "tool_executor"],
        source_id: str,
        now_ms: int,
    ) -> tuple[dict[str, object] | None, bool]:
        """Fail closed for ordinary sessions and normalize bound legacy paths."""

        if room_binding_ref is None:
            return None, False
        if self.mode == "kernel_only":
            raise RoomKernelFenceError("legacy Room execution is forbidden in kernel_only mode")
        if str(room_binding_ref.get("schemaVersion") or "") != "wisdom-weasel.room-binding.v2":
            raise RoomKernelFenceError("compatibility entry requires canonical RoomBinding")
        return self.normalize_legacy_dispatch(
            dispatch,
            source_kind=source_kind,
            source_id=source_id,
            now_ms=now_ms,
        )

    def enqueue_dispatch(
        self,
        payload: Mapping[str, object],
        *,
        now_ms: int,
    ) -> tuple[dict[str, object], bool]:
        """Enqueue through the canonical outbox; only cohort/test can lease it."""

        validate_kernel_contract("dispatchEnvelope", payload)
        with self._connect(immediate=True) as conn:
            return self._enqueue_dispatch(
                conn,
                payload,
                shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
                now_ms=now_ms,
            )

    def enqueue_dispatches(
        self,
        payloads: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
        *,
        now_ms: int,
    ) -> list[tuple[dict[str, object], bool]]:
        """Atomically enqueue one user-triggered fan-out.

        A multi-mention is one semantic command. Publishing each Dispatch in a
        separate transaction lets the worker observe a partial fan-out and
        makes retry/cancel accounting ambiguous. Validate the complete batch
        first, then insert every Dispatch and reservation under one lock.
        """

        values = tuple(payloads)
        if not values:
            raise ValueError("dispatch batch must not be empty")
        for payload in values:
            validate_kernel_contract("dispatchEnvelope", payload)
        identities = [
            (
                str(payload["rootId"]),
                str(payload["dispatchId"]),
                str(payload["idempotencyKey"]),
                str(payload["targetSessionId"]),
            )
            for payload in values
        ]
        if len(identities) != len(set(identities)):
            raise RoomKernelFenceError("dispatch batch contains duplicate identities")
        root_ids = {identity[0] for identity in identities}
        if len(root_ids) != 1:
            raise RoomKernelFenceError("dispatch batch must belong to one Root")
        dispatches_by_id = {
            str(payload["dispatchId"]): payload
            for payload in values
        }
        session_predecessors: dict[str, list[str]] = {}
        for payload in values:
            session_id = str(payload["targetSessionId"])
            predecessors = session_predecessors.setdefault(session_id, [])
            if predecessors and not any(
                _payload_depends_on(
                    payload,
                    predecessor_id,
                    dispatches_by_id=dispatches_by_id,
                )
                for predecessor_id in predecessors
            ):
                raise RoomKernelFenceError(
                    "dispatch batch targets one Session without an ordered dependency"
                )
            predecessors.append(str(payload["dispatchId"]))

        with self._connect(immediate=True) as conn:
            return [
                self._enqueue_dispatch(
                    conn,
                    payload,
                    shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
                    now_ms=now_ms,
                )
                for payload in values
            ]

    def _enqueue_dispatch(
        self,
        conn: sqlite3.Connection,
        payload: Mapping[str, object],
        *,
        shadow_only: bool,
        now_ms: int,
    ) -> tuple[dict[str, object], bool]:
        root_id = str(payload["rootId"])
        dispatch_id = str(payload["dispatchId"])
        idempotency_key = str(payload["idempotencyKey"])
        existing_by_key = conn.execute(
            """SELECT * FROM room_kernel_dispatches
               WHERE root_id = ? AND idempotency_key = ?""",
            (root_id, idempotency_key),
        ).fetchone()
        existing_by_id = conn.execute(
            "SELECT * FROM room_kernel_dispatches WHERE dispatch_id = ?",
            (dispatch_id,),
        ).fetchone()
        if existing_by_key is not None or existing_by_id is not None:
            if (
                existing_by_key is None
                or existing_by_id is None
                or str(existing_by_key["dispatch_id"])
                != str(existing_by_id["dispatch_id"])
            ):
                raise RoomKernelFenceError(
                    "Dispatch idempotency identity was rebound"
                )
            stored_payload = json.loads(str(existing_by_key["payload_json"]))
            if _dispatch_idempotency_identity(stored_payload) != (
                _dispatch_idempotency_identity(payload)
            ):
                raise RoomKernelFenceError(
                    "Dispatch idempotency payload was rebound"
                )
            return _dispatch_payload(existing_by_key), False

        root = self._root_row(conn, root_id)
        generation = int(payload["generation"])
        if generation != int(root["generation"]):
            raise RoomKernelFenceError("dispatch generation is stale")
        if str(root["state"]) in {"cancelling", "cancelled", "cancelled_with_unknowns", "completed", "failed"}:
            raise RoomKernelFenceError("root is terminal or cancelling")
        hop = int(payload["hopCount"])
        depth = int(payload["depth"])
        cost = int(payload["budgetCost"])
        if hop > int(root["max_hops"]):
            raise RoomKernelFenceError("dispatch hop limit exceeded")
        if depth > int(root["max_depth"]):
            raise RoomKernelFenceError("dispatch depth limit exceeded")
        if (
            not shadow_only
            and cost
            > int(root["budget_remaining"]) - int(root["budget_reserved"])
        ):
            raise RoomKernelFenceError("dispatch budget exhausted")
        parent_id = payload.get("parentDispatchId")
        if parent_id is not None:
            parent = self._dispatch_row(conn, str(parent_id))
            if str(parent["root_id"]) != str(root["root_id"]):
                raise RoomKernelFenceError("parent dispatch belongs to another root")
            if hop != int(parent["hop_count"]) + 1:
                raise RoomKernelFenceError("dispatch hop must advance exactly once")
            if depth < int(parent["depth"]):
                raise RoomKernelFenceError("dispatch depth cannot move backwards")

        task = conn.execute(
            """
            SELECT root_id, state, current_owner_participant_id, payload_json
            FROM room_kernel_tasks
            WHERE task_id=?
            """,
            (str(payload["taskId"]),),
        ).fetchone()
        if task is None or str(task["root_id"]) != str(root["root_id"]):
            raise RoomKernelFenceError("dispatch Task belongs to another Root")
        if str(task["state"]) in _TERMINAL_TASK_STATES:
            raise RoomKernelFenceError("dispatch Task is terminal")
        if str(task["current_owner_participant_id"]) != str(
            payload["targetParticipantId"]
        ):
            raise RoomKernelFenceError(
                "dispatch target is not the current Task owner"
            )
        direct_dependencies = _dispatch_dependency_ids(payload)
        for dependency_id in direct_dependencies:
            if dependency_id == str(payload["dispatchId"]):
                raise RoomKernelFenceError("Dispatch cannot depend on itself")
            try:
                dependency = self._dispatch_row(conn, dependency_id)
            except KeyError as exc:
                raise RoomKernelFenceError(
                    "Dispatch dependency is missing or ordered after its consumer"
                ) from exc
            if str(dependency["root_id"]) != str(root["root_id"]):
                raise RoomKernelFenceError(
                    "Dispatch dependency belongs to another Root"
                )
        conn.execute(
            """INSERT INTO room_kernel_dispatches(
               dispatch_id, root_id, task_id, parent_dispatch_id, generation,
               hop_count, depth, budget_cost, target_session_id,
               target_participant_id, trigger_id, intent_kind, idempotency_key,
               state, payload_json, created_at_ms, updated_at_ms
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                str(payload["dispatchId"]), str(payload["rootId"]), str(payload["taskId"]),
                payload.get("parentDispatchId"), generation, hop, depth, cost,
                str(payload["targetSessionId"]), str(payload["targetParticipantId"]),
                str(payload["triggerId"]), str(payload["intentKind"]),
                str(payload["idempotencyKey"]), _json(payload), int(now_ms), int(now_ms),
            ),
        )
        try:
            task_authority = json.loads(str(task["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RoomKernelFenceError(
                "Dispatch Task authority payload is corrupt"
            ) from exc
        if not isinstance(task_authority, Mapping):
            raise RoomKernelFenceError(
                "Dispatch Task authority payload is corrupt"
            )
        self._receipt(
            conn,
            root_id=str(root["root_id"]),
            command_id=None,
            receipt_kind="accepted",
            status="applied",
            generation=generation,
            details={
                "purpose": "dispatch_acceptance_scope",
                "dispatchId": str(payload["dispatchId"]),
                "taskId": str(payload["taskId"]),
                "taskRevision": int(task_authority.get("revision") or 0),
                "intentKind": str(payload["intentKind"]),
                "attempt": int(payload.get("attempt") or 0),
                "acceptanceCriterionIds": sorted(
                    _criteria(
                        task_authority.get("acceptanceCriterionIds")
                    )
                ),
            },
            now_ms=now_ms,
        )
        if not shadow_only:
            # Live Dispatches reserve both the compatibility budget and the
            # typed resource limits. Shadow observations are never leaseable,
            # so reserving production capacity for them would leak capacity
            # without any execution path that could settle the reservation.
            self._reserve_dispatch_limits(
                conn,
                root_id=str(root["root_id"]),
                dispatch_id=str(payload["dispatchId"]),
                defer_concurrency=bool(direct_dependencies),
                now_ms=now_ms,
            )
            conn.execute(
                """UPDATE room_kernel_roots
                   SET budget_reserved = budget_reserved + ?, updated_at_ms = ?
                   WHERE root_id = ?""",
                (cost, int(now_ms), root["root_id"]),
            )
        conn.execute(
            """INSERT INTO room_kernel_outbox(
               outbox_id, root_id, dispatch_id, generation, state, shadow_only,
               available_at_ms, payload_json, updated_at_ms
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"outbox:{payload['dispatchId']}", str(payload["rootId"]),
                str(payload["dispatchId"]), generation,
                "shadowed" if shadow_only else "pending", 1 if shadow_only else 0,
                int(now_ms), _json(payload), int(now_ms),
            ),
        )
        conn.execute(
            """INSERT INTO room_kernel_abort_scopes(
               dispatch_id,root_id,session_id,generation,state,surfaces_json,updated_at_ms)
               VALUES (?,?,?,?,'registered',?,?)""",
            (
                str(payload["dispatchId"]), str(payload["rootId"]),
                str(payload["targetSessionId"]), generation,
                _json(list(_ABORT_SURFACES)), int(now_ms),
            ),
        )
        return self.dispatch(str(payload["dispatchId"]), conn=conn), True

    def set_dispatch_wait_state(
        self, dispatch_id: str, state: Literal["running", "retry_wait", "timer_wait"], *, now_ms: int
    ) -> None:
        if self.mode != "test":
            raise RoomKernelFenceError("fault-injection transitions require test mode")
        with self._connect(immediate=True) as conn:
            self._dispatch_row(conn, dispatch_id)
            conn.execute(
                "UPDATE room_kernel_dispatches SET state = ?, updated_at_ms = ? WHERE dispatch_id = ?",
                (state, int(now_ms), dispatch_id),
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state = ?, updated_at_ms = ? WHERE dispatch_id = ?",
                (state, int(now_ms), dispatch_id),
            )

    def pending_dispatch(self, *, now_ms: int) -> dict[str, object] | None:
        if self.mode not in {"cohort", "test", "kernel_only"}:
            return None
        with self._connect(immediate=True) as conn:
            waiting_roots = conn.execute(
                """SELECT DISTINCT root.root_id,root.generation
                   FROM room_kernel_continuations continuation
                   JOIN room_kernel_roots root
                     ON root.root_id=continuation.root_id
                   WHERE continuation.state='applied'
                     AND continuation.decision IN ('wait','dispatch')
                     AND root.state IN ('running','waiting','blocked')
                   ORDER BY root.root_id"""
            ).fetchall()
            for waiting_root in waiting_roots:
                self._resume_ready_participant_waits(
                    conn,
                    root_id=str(waiting_root["root_id"]),
                    generation=int(waiting_root["generation"]),
                    now_ms=now_ms,
                )
            row = self._first_ready_outbox(
                conn,
                now_ms=now_ms,
            )
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        payload["state"] = str(row["dispatch_state"])
        return payload

    def dispatch_enqueued_at(self, dispatch_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at_ms FROM room_kernel_dispatches WHERE dispatch_id = ?",
                (_required(dispatch_id, "dispatch_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(dispatch_id)
        return int(row["created_at_ms"])

    def lease_next(
        self,
        *,
        now_ms: int,
        ttl_ms: int,
        dispatch_id: str = "",
        prepared_session_id: str = "",
        prepared_manifest_hash: str = "",
    ) -> dict[str, object] | None:
        if self.mode not in {"cohort", "test", "kernel_only"}:
            return None
        with self._connect(immediate=True) as conn:
            row = self._first_ready_outbox(
                conn,
                now_ms=now_ms,
                dispatch_id=dispatch_id,
            )
            if row is None:
                return None
            root = self._root_row(conn, str(row["root_id"]))
            if int(row["generation"]) != int(root["generation"]):
                conn.execute("UPDATE room_kernel_outbox SET state = 'cancelled' WHERE outbox_id = ?", (row["outbox_id"],))
                return None
            if not self._acquire_dispatch_concurrency(
                conn,
                root_id=str(root["root_id"]),
                dispatch_id=str(row["dispatch_id"]),
                now_ms=now_ms,
            ):
                return None
            if prepared_session_id or prepared_manifest_hash:
                if str(row["target_session_id"]) != prepared_session_id:
                    raise RoomKernelFenceError("prepared capability belongs to another Session")
                activated = conn.execute(
                    """UPDATE room_v2_capability_runtime_bindings
                       SET state = 'active', updated_at_ms = ?
                       WHERE session_id = ? AND manifest_hash = ? AND state = 'prepared'""",
                    (int(now_ms), prepared_session_id, prepared_manifest_hash),
                )
                if activated.rowcount != 1:
                    raise RoomKernelFenceError("Dispatch has no matching prepared Capability Manifest")
                requirement_activated = conn.execute(
                    """UPDATE room_v2_dispatch_requirement_bindings
                       SET state = 'active', updated_at_ms = ?
                       WHERE dispatch_id = ? AND session_id = ? AND generation = ?
                         AND state = 'prepared'""",
                    (
                        int(now_ms), row["dispatch_id"], prepared_session_id,
                        int(row["generation"]),
                    ),
                )
                if requirement_activated.rowcount != 1:
                    raise RoomKernelFenceError(
                        "Dispatch has no matching prepared requirement observation"
                    )
            dispatch_record = self._dispatch_row(
                conn,
                str(row["dispatch_id"]),
            )
            task_record = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                (dispatch_record["task_id"],),
            ).fetchone()
            if task_record is None:
                raise RoomKernelFenceError(
                    "Dispatch lease has no authoritative Task identity"
                )
            task_payload = json.loads(str(task_record["payload_json"]))
            task_id = str(dispatch_record["task_id"])
            ownership_revision = int(
                task_payload.get("ownershipRevision") or 0
            )
            root_id = str(row["root_id"])
            dispatch_identity = str(row["dispatch_id"])
            expected_lease_id = _stable_id(
                "room-lease",
                root_id,
                task_id,
                str(ownership_revision),
                dispatch_identity,
            )
            prior_lease = conn.execute(
                "SELECT lease_id FROM room_kernel_leases WHERE dispatch_id = ?",
                (row["dispatch_id"],),
            ).fetchone()
            if prior_lease is not None and str(
                prior_lease["lease_id"]
            ) != expected_lease_id:
                raise RoomKernelFenceError(
                    "Dispatch lease identity no longer matches its Task owner"
                )
            lease_id = expected_lease_id
            token = _stable_id(
                "room-lease-token",
                lease_id,
                root_id,
                task_id,
                str(ownership_revision),
                dispatch_identity,
                str(row["generation"]),
            )
            if prior_lease is not None:
                token = _stable_id(
                    "room-lease-token",
                    lease_id,
                    root_id,
                    task_id,
                    str(ownership_revision),
                    dispatch_identity,
                    str(row["generation"]),
                    str(now_ms),
                )
            expires = int(now_ms) + max(1, int(ttl_ms))
            if prior_lease is None:
                conn.execute(
                    """INSERT INTO room_kernel_leases(
                       lease_id, root_id, dispatch_id, generation, lease_token,
                       state, expires_at_ms, updated_at_ms
                       ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                    (
                        lease_id,
                        row["root_id"],
                        row["dispatch_id"],
                        row["generation"],
                        token,
                        expires,
                        int(now_ms),
                    ),
                )
            else:
                conn.execute(
                    """UPDATE room_kernel_leases
                       SET lease_token=?, state='active', expires_at_ms=?,
                           updated_at_ms=?
                       WHERE dispatch_id=?""",
                    (
                        token,
                        expires,
                        int(now_ms),
                        row["dispatch_id"],
                    ),
                )
            conn.execute("UPDATE room_kernel_dispatches SET state = 'leased', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), row["dispatch_id"]))
            conn.execute("UPDATE room_kernel_outbox SET state = 'leased', updated_at_ms = ? WHERE outbox_id = ?", (int(now_ms), row["outbox_id"]))
            return {
                "leaseId": lease_id,
                "leaseToken": token,
                "rootId": root_id,
                "taskId": task_id,
                "ownershipRevision": ownership_revision,
                "dispatchId": dispatch_identity,
                "generation": int(row["generation"]),
                "expiresAtMs": expires,
            }
    def _assert_lease_identity(
        self,
        conn: sqlite3.Connection,
        lease: sqlite3.Row,
    ) -> tuple[sqlite3.Row, dict[str, object]]:
        dispatch = self._dispatch_row(conn, str(lease["dispatch_id"]))
        task_record = conn.execute(
            "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
            (dispatch["task_id"],),
        ).fetchone()
        if task_record is None:
            raise RoomKernelFenceError(
                "Dispatch lease has no authoritative Task identity"
            )
        task_payload = json.loads(str(task_record["payload_json"]))
        expected_lease_id = _stable_id(
            "room-lease",
            str(lease["root_id"]),
            str(dispatch["task_id"]),
            str(int(task_payload.get("ownershipRevision") or 0)),
            str(lease["dispatch_id"]),
        )
        if (
            str(dispatch["root_id"]) != str(lease["root_id"])
            or int(dispatch["generation"]) != int(lease["generation"])
            or str(lease["lease_id"]) != expected_lease_id
        ):
            raise RoomKernelFenceError(
                "runtime receipt references a lease with stale Task ownership"
            )
        return dispatch, _dispatch_payload(dispatch)

    def _first_ready_outbox(
        self,
        conn: sqlite3.Connection,
        *,
        now_ms: int,
        dispatch_id: str = "",
    ) -> sqlite3.Row | None:
        rows = conn.execute(
            f"""SELECT o.*, d.state AS dispatch_state, d.target_session_id
               FROM room_kernel_outbox o
               JOIN room_kernel_dispatches d USING(dispatch_id)
               WHERE o.state IN ('pending','retry_wait')
                 AND o.shadow_only = 0
                 AND o.available_at_ms <= ?
                 AND d.state IN ('pending','retry_wait')
                 AND (? = '' OR o.dispatch_id = ?)
                 AND NOT EXISTS (
                   SELECT 1
                   FROM room_kernel_dispatches occupied
                   JOIN room_kernel_roots occupied_root
                     ON occupied_root.root_id = occupied.root_id
                   WHERE occupied.target_session_id = d.target_session_id
                     AND occupied.dispatch_id != d.dispatch_id
                     AND occupied_root.state NOT IN (
                       'cancelled','cancelled_with_unknowns','completed','failed'
                     )
                     AND occupied.state IN (
                       {','.join('?' for _ in _SESSION_OCCUPYING_DISPATCH_STATES)}
                     )
                 )
               ORDER BY o.available_at_ms, o.outbox_id""",
            (
                int(now_ms),
                dispatch_id,
                dispatch_id,
                *_SESSION_OCCUPYING_DISPATCH_STATES,
            ),
        ).fetchall()
        seen_sessions: set[str] = set()
        for row in rows:
            if not self._dispatch_dependencies_ready(
                conn,
                str(row["dispatch_id"]),
            ):
                continue
            if not self._dispatch_concurrency_available(
                conn,
                root_id=str(row["root_id"]),
                dispatch_id=str(row["dispatch_id"]),
            ):
                continue
            session_id = str(row["target_session_id"])
            if session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)
            return row
        return None

    def _dispatch_dependencies_ready(
        self,
        conn: sqlite3.Connection,
        dispatch_id: str,
    ) -> bool:
        dispatch = self._dispatch_row(conn, dispatch_id)
        dispatch_payload = json.loads(str(dispatch["payload_json"]))
        dependency_ids = _dispatch_dependency_ids(dispatch_payload)
        continuation = conn.execute(
            """SELECT *
               FROM room_kernel_continuations
               WHERE child_dispatch_id = ?
                 AND decision IN ('dispatch','wait')""",
            (dispatch_id,),
        ).fetchone()
        if continuation is not None:
            if not self._commit_result_is_public(
                conn,
                str(continuation["commit_id"]),
            ):
                return False
            payload = _room_continuation_payload(conn, continuation)
            raw_dependencies = payload.get("waitForDispatchIds")
            if raw_dependencies is None:
                raw_dependencies = []
            if not isinstance(raw_dependencies, list):
                raise RoomKernelFenceError(
                    "Dispatch continuation dependencies are invalid"
                )
            waiting_for_dispatch = str(
                payload.get("waitingForDispatchId") or ""
            ).strip()
            terminal_outcome_dispatch = str(
                payload.get("dependencyOutcomeDispatchId") or ""
            ).strip()
            terminal_outcome_state = str(
                payload.get("dependencyOutcomeState") or ""
            ).strip()
            if (
                waiting_for_dispatch
                and terminal_outcome_dispatch == waiting_for_dispatch
                and terminal_outcome_state
                in {"failed", "cancelled", "unknown", "blocked"}
            ):
                # The participant dependency cannot become committed/public
                # after a terminal outcome.  The durable outcome receipt is
                # the resume trigger, so do not retain the impossible Dispatch
                # dependency on the Facilitator wake-up.
                waiting_for_dispatch = ""
            dependency_ids = list(
                dict.fromkeys(
                    [
                        *dependency_ids,
                        *(
                            str(value).strip()
                            for value in raw_dependencies
                        ),
                        *(
                            [waiting_for_dispatch]
                            if waiting_for_dispatch
                            and waiting_for_dispatch != dispatch_id
                            else []
                        ),
                    ]
                )
            )
        if not dependency_ids:
            return True
        if any(not value for value in dependency_ids):
            raise RoomKernelFenceError(
                "Dispatch dependency is invalid"
            )
        placeholders = ",".join("?" for _ in dependency_ids)
        rows = conn.execute(
            f"""SELECT dispatch_id, root_id, state
                FROM room_kernel_dispatches
                WHERE dispatch_id IN ({placeholders})""",
            dependency_ids,
        ).fetchall()
        states = {
            str(row["dispatch_id"]): (
                str(row["root_id"]),
                str(row["state"]),
            )
            for row in rows
        }
        if set(states) != set(dependency_ids):
            raise RoomKernelFenceError(
                "Dispatch dependency is missing"
            )
        if any(
            states[value][0] != str(dispatch["root_id"])
            for value in dependency_ids
        ):
            raise RoomKernelFenceError(
                "Dispatch dependency belongs to another Root"
            )
        if any(states[value][1] != "committed" for value in dependency_ids):
            return False
        return all(
            self._dispatch_result_is_public(conn, dependency_id)
            and self._dispatch_dependency_releases(conn, dependency_id)
            for dependency_id in dependency_ids
        )

    @staticmethod
    def _dispatch_dependency_releases(
        conn: sqlite3.Connection,
        dispatch_id: str,
    ) -> bool:
        dispatch = RoomKernelStore._dispatch_row(conn, dispatch_id)
        if str(dispatch["intent_kind"]) != "align":
            return True
        commit = conn.execute(
            "SELECT payload_json FROM room_kernel_commits WHERE dispatch_id=?",
            (dispatch_id,),
        ).fetchone()
        if commit is None:
            if RoomKernelStore._definition_fences_dispatch_locked(
                conn,
                dispatch_id,
            ):
                return True
            raise RoomKernelFenceError(
                "committed alignment Dispatch has no canonical RoomCommit"
            )
        payload = _room_commit_payload(conn, commit["payload_json"])
        continuation = payload.get("continuation")
        return (
            isinstance(continuation, Mapping)
            and continuation.get("decision") == "complete"
        )

    @staticmethod
    def _dispatch_result_is_public(
        conn: sqlite3.Connection,
        dispatch_id: str,
    ) -> bool:
        commit = conn.execute(
            """SELECT commit_id,payload_json
               FROM room_kernel_commits
               WHERE dispatch_id=?""",
            (dispatch_id,),
        ).fetchone()
        if commit is None:
            if RoomKernelStore._definition_fences_dispatch_locked(
                conn,
                dispatch_id,
            ):
                return True
            raise RoomKernelFenceError(
                "committed Dispatch has no canonical RoomCommit"
            )
        return RoomKernelStore._commit_result_is_public(
            conn,
            str(commit["commit_id"]),
            payload=_room_commit_payload(conn, commit["payload_json"]),
        )

    @staticmethod
    def _definition_fences_dispatch_locked(
        conn: sqlite3.Connection,
        dispatch_id: str,
    ) -> bool:
        rows = conn.execute(
            """SELECT payload_json FROM room_kernel_receipts
               WHERE receipt_kind='accepted'
               ORDER BY created_at_ms DESC,rowid DESC"""
        ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            details = payload.get("details") if isinstance(payload, Mapping) else None
            if (
                isinstance(details, Mapping)
                and details.get("operation") == "room_define"
                and str(details.get("dispatchId") or "") == dispatch_id
            ):
                return True
        return False

    @staticmethod
    def _commit_result_is_public(
        conn: sqlite3.Connection,
        commit_id: str,
        *,
        payload: Mapping[str, object] | None = None,
    ) -> bool:
        if payload is None:
            commit = conn.execute(
                """SELECT payload_json FROM room_kernel_commits
                   WHERE commit_id=?""",
                (commit_id,),
            ).fetchone()
            if commit is None:
                raise RoomKernelFenceError(
                    "continuation has no canonical RoomCommit"
                )
            payload = _room_commit_payload(conn, commit["payload_json"])
        if payload.get("action") != "post":
            return False
        published = conn.execute(
            """SELECT 1 FROM room_v2_posts
               WHERE publication_source_kind='room_commit'
                 AND publication_source_ref=?
               LIMIT 1""",
            (commit_id,),
        ).fetchone()
        return published is not None

    def reconcile_expired_leases(self, *, now_ms: int) -> list[dict[str, object]]:
        receipts: list[dict[str, object]] = []
        with self._connect(immediate=True) as conn:
            rows = conn.execute(
                "SELECT * FROM room_kernel_leases WHERE state = 'active' AND expires_at_ms <= ?",
                (int(now_ms),),
            ).fetchall()
            for lease in rows:
                dispatch_id = str(lease["dispatch_id"])
                conn.execute("UPDATE room_kernel_leases SET state = 'expired', updated_at_ms = ? WHERE lease_id = ?", (int(now_ms), lease["lease_id"]))
                conn.execute("UPDATE room_kernel_dispatches SET state = 'unknown', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), dispatch_id))
                conn.execute("UPDATE room_kernel_runtime_effects SET state='unknown',updated_at_ms=? WHERE dispatch_id=? AND state IN ('intent','accepted','unknown')", (int(now_ms), dispatch_id))
                conn.execute("UPDATE room_kernel_abort_scopes SET state='unknown',updated_at_ms=? WHERE dispatch_id=? AND state IN ('registered','cancelling','unknown')", (int(now_ms), dispatch_id))
                conn.execute("UPDATE room_kernel_outbox SET state = 'dead_letter', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), dispatch_id))
                dead_id = f"dead-letter:{dispatch_id}"
                conn.execute(
                    """INSERT OR IGNORE INTO room_kernel_dead_letters(
                       dead_letter_id, root_id, dispatch_id, reason_code, payload_json, created_at_ms
                       ) VALUES (?, ?, ?, 'lease_expired_result_unknown', ?, ?)""",
                    (dead_id, lease["root_id"], dispatch_id, _json({"leaseId": lease["lease_id"]}), int(now_ms)),
                )
                root = self._root_row(conn, str(lease["root_id"]))
                if str(root["state"]) == "cancelling":
                    cancel_generation = int(root["generation"])
                else:
                    cancel_generation = int(root["generation"]) + 1
                    conn.execute("UPDATE room_kernel_roots SET generation=?,state='cancelling',updated_at_ms=? WHERE root_id=?", (cancel_generation, int(now_ms), lease["root_id"]))
                conn.execute("UPDATE room_kernel_tasks SET state='cancelled',updated_at_ms=? WHERE root_id=? AND state NOT IN ('completed','failed','cancelled')", (int(now_ms), lease["root_id"]))
                self._enqueue_cancel(conn, root_id=str(lease["root_id"]), dispatch_id=dispatch_id,
                    session_id=str(self._dispatch_row(conn, dispatch_id)["target_session_id"]), generation=cancel_generation,
                    terminalize_root=True, now_ms=now_ms)
                receipts.append(self._receipt(conn, root_id=str(lease["root_id"]), command_id=None, receipt_kind="dispatch_unknown", status="unknown", generation=int(lease["generation"]), details={"dispatchId": dispatch_id, "deadLetterId": dead_id}, now_ms=now_ms))
        return receipts

    def cancel_expired_roots(self, *, now_ms: int) -> list[dict[str, object]]:
        """Turn hard wall-clock deadlines into the same durable cancel path."""

        with self._connect(immediate=True) as conn:
            root_ids = [
                str(row[0])
                for row in conn.execute(
                    """SELECT limits.root_id FROM room_kernel_root_limits limits
                       JOIN room_kernel_roots root USING(root_id)
                       WHERE limits.deadline_at_ms<=?
                         AND root.state NOT IN ('cancelling','cancelled','completed','failed')""",
                    (int(now_ms),),
                )
            ]
            return [
                self._cancel_root(
                    conn, root_id, command_id=None, now_ms=now_ms,
                    receipt_kind="root_cancelled",
                )
                for root_id in root_ids
            ]

    def reconcile_exhausted_cancels(
        self,
        *,
        now_ms: int,
    ) -> list[dict[str, object]]:
        with self._connect(immediate=True) as conn:
            return self._finalize_exhausted_cancel_roots(conn, now_ms=now_ms)

    def lease_cancel(self, *, now_ms: int, ttl_ms: int = 30_000) -> dict[str, object] | None:
        with self._connect(immediate=True) as conn:
            row = conn.execute("""SELECT cancel.*,effect.state AS runtime_effect_state,
                       effect.runtime_receipt_json AS active_runtime_receipt_json
                FROM room_kernel_cancel_outbox cancel
                JOIN room_kernel_runtime_effects effect
                  ON effect.dispatch_id=cancel.dispatch_id
                WHERE effect.state IN ('intent','accepted','unknown')
                  AND ((cancel.state IN ('pending','retry_wait') AND cancel.available_at_ms<=?)
                    OR (cancel.state='leased' AND cancel.lease_until_ms<=?))
                ORDER BY cancel.created_at_ms,cancel.cancel_id LIMIT 1""", (int(now_ms), int(now_ms))).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE room_kernel_cancel_outbox SET state='leased',attempt_count=attempt_count+1,lease_until_ms=? WHERE cancel_id=?", (int(now_ms)+max(1,int(ttl_ms)), row["cancel_id"]))
            active_runtime_receipt = json.loads(
                str(row["active_runtime_receipt_json"] or "{}")
            )
            return {
                "cancelId": str(row["cancel_id"]),
                "rootId": str(row["root_id"]),
                "dispatchId": str(row["dispatch_id"]),
                "sessionId": str(row["session_id"]),
                "generation": int(row["generation"]),
                "turnId": str(active_runtime_receipt.get("turnId") or ""),
                "capabilityEpoch": int(
                    active_runtime_receipt.get("capabilityEpoch", -1)
                ),
            }

    def complete_cancel(self, cancel_id: str, runtime_receipt: Mapping[str, object], *, now_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            row = conn.execute("SELECT * FROM room_kernel_cancel_outbox WHERE cancel_id=? AND state='leased'", (cancel_id,)).fetchone()
            if row is None:
                raise RoomKernelFenceError("cancel lease is missing or stale")
            effect = conn.execute(
                """SELECT state,root_id,session_id,dispatch_generation,
                          runtime_receipt_json
                   FROM room_kernel_runtime_effects WHERE dispatch_id=?""",
                (row["dispatch_id"],),
            ).fetchone()
            active_runtime_receipt = (
                json.loads(str(effect["runtime_receipt_json"] or "{}"))
                if effect is not None
                else {}
            )
            try:
                receipt_generation = int(runtime_receipt.get("generation", -1))
                receipt_capability_epoch = int(
                    runtime_receipt.get("capabilityEpoch", -1)
                )
                active_generation = int(
                    active_runtime_receipt.get("generation", -1)
                )
                active_capability_epoch = int(
                    active_runtime_receipt.get("capabilityEpoch", -1)
                )
            except (TypeError, ValueError) as exc:
                raise RoomKernelFenceError(
                    "runtime cancel receipt does not match durable intent"
                ) from exc
            active_turn_id = str(
                active_runtime_receipt.get("turnId") or ""
            ).strip()
            if (
                effect is None
                or str(effect["state"]) not in {"accepted", "unknown"}
                or effect["root_id"] != row["root_id"]
                or effect["session_id"] != row["session_id"]
                or active_runtime_receipt.get("rootId") != row["root_id"]
                or active_runtime_receipt.get("dispatchId") != row["dispatch_id"]
                or active_runtime_receipt.get("sessionId") != row["session_id"]
                or active_generation != int(effect["dispatch_generation"])
                or not active_turn_id
                or active_capability_epoch < 0
                or runtime_receipt.get("schemaVersion")
                != "wisdom-weasel.room-runtime-receipt.v1"
                or runtime_receipt.get("receiptKind") != "cancel_applied"
                or runtime_receipt.get("status") not in {"applied", "cancelled"}
                or runtime_receipt.get("cancelId") != row["cancel_id"]
                or runtime_receipt.get("rootId") != row["root_id"]
                or runtime_receipt.get("dispatchId") != row["dispatch_id"]
                or runtime_receipt.get("sessionId") != row["session_id"]
                or receipt_generation != int(row["generation"])
                or str(runtime_receipt.get("turnId") or "").strip()
                != active_turn_id
                or receipt_capability_epoch != active_capability_epoch
            ):
                raise RoomKernelFenceError("runtime cancel receipt does not match durable intent")
            surfaces = runtime_receipt.get("cancellationSurfaces")
            required_surfaces = set(_RUNTIME_CANCEL_SURFACES)
            if not isinstance(surfaces, Mapping) or set(surfaces) != required_surfaces:
                raise RoomKernelFenceError("runtime cancel receipt lacks per-surface termination proof")
            allowed_surface_states = {"requested", "acknowledged", "terminated", "unknown"}
            typed_surfaces: dict[str, dict[str, object]] = {}
            for surface, raw_proof in surfaces.items():
                if not isinstance(raw_proof, Mapping):
                    raise RoomKernelFenceError("runtime cancel receipt lacks typed surface proof")
                proof = dict(raw_proof)
                if (
                    proof.get("schemaVersion")
                    != "wisdom-weasel.runtime-surface-termination-receipt.v1"
                    or proof.get("surface") != surface
                    or str(proof.get("state")) not in allowed_surface_states
                    or not isinstance(proof.get("targetIds", []), list)
                ):
                    raise RoomKernelFenceError("runtime cancel receipt has invalid surface proof")
                typed_surfaces[str(surface)] = proof
            pending_targets = sorted(
                surface for surface, proof in typed_surfaces.items()
                if proof["state"] in {"requested", "acknowledged", "unknown"}
            )
            declared_pending = sorted(
                str(value) for value in runtime_receipt.get("pendingTargets") or []
                if str(value).strip()
            )
            if pending_targets != declared_pending:
                raise RoomKernelFenceError("runtime cancel pendingTargets mismatch surface proof")
            for surface, proof in typed_surfaces.items():
                conn.execute(
                    """INSERT INTO room_v2_runtime_cancel_surface_receipts(
                       cancel_id,surface,state,target_ref,detail_json,updated_at_ms)
                       VALUES (?,?,?,'',?,?)
                       ON CONFLICT(cancel_id,surface) DO UPDATE SET
                       state=excluded.state,detail_json=excluded.detail_json,updated_at_ms=excluded.updated_at_ms""",
                    (cancel_id, surface, str(proof["state"]), _json(proof), int(now_ms)),
                )
            if pending_targets:
                if bool(row["terminalize_root"]) and any(
                    proof["state"] == "unknown"
                    for proof in typed_surfaces.values()
                ):
                    conn.execute(
                        "UPDATE room_kernel_roots SET state='cancelled_with_unknowns',updated_at_ms=? WHERE root_id=?",
                        (int(now_ms), row["root_id"]),
                    )
                conn.execute(
                    """UPDATE room_kernel_cancel_outbox SET state='retry_wait',lease_until_ms=0,
                       available_at_ms=?,runtime_receipt_json=? WHERE cancel_id=?""",
                    (int(now_ms) + 500, _json(runtime_receipt), cancel_id),
                )
                return {
                    "cancelId": cancel_id,
                    "state": "pending",
                    "pendingTargets": pending_targets,
                    "terminalReceipt": None,
                }
            conn.execute("UPDATE room_kernel_cancel_outbox SET state='applied',lease_until_ms=0,runtime_receipt_json=? WHERE cancel_id=?", (_json(runtime_receipt), cancel_id))
            conn.execute("UPDATE room_kernel_runtime_effects SET state='cancelled',runtime_receipt_json=?,updated_at_ms=? WHERE dispatch_id=? AND state IN ('intent','accepted','unknown')", (_json(runtime_receipt), int(now_ms), row["dispatch_id"]))
            conn.execute("UPDATE room_kernel_abort_scopes SET state='cancelled',cancel_receipt_json=?,updated_at_ms=? WHERE dispatch_id=? AND state IN ('registered','cancelling','unknown')", (_json(runtime_receipt), int(now_ms), row["dispatch_id"]))
            conn.execute("UPDATE room_kernel_dispatches SET state='cancelled',updated_at_ms=? WHERE dispatch_id=? AND state IN ('unknown','leased','running')", (int(now_ms), row["dispatch_id"]))
            self._settle_dispatch_limits(
                conn, str(row["dispatch_id"]), usage=None, consumed=False, now_ms=now_ms
            )
            remaining = int(conn.execute("SELECT COUNT(*) FROM room_kernel_cancel_outbox WHERE root_id=? AND terminalize_root=1 AND state!='applied'", (row["root_id"],)).fetchone()[0])
            terminal = None
            if bool(row["terminalize_root"]) and remaining == 0:
                unknowns = int(conn.execute(
                    """SELECT COUNT(*) FROM room_v2_runtime_cancel_surface_receipts surface
                       JOIN room_kernel_cancel_outbox cancel USING(cancel_id)
                       WHERE cancel.root_id=? AND surface.state='unknown'""",
                    (row["root_id"],),
                ).fetchone()[0])
                terminal = self._terminal_cancel(
                    conn, str(row["root_id"]), now_ms=now_ms,
                    cancellation_outcome="cancelled_with_unknowns" if unknowns else "cancelled",
                )
            return {
                "cancelId": cancel_id,
                "state": "applied",
                "pendingTargets": [],
                "terminalReceipt": terminal,
            }

    def fail_cancel(
        self,
        cancel_id: str,
        reason: str,
        *,
        now_ms: int,
    ) -> list[dict[str, object]]:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM room_kernel_cancel_outbox WHERE cancel_id=?",
                (cancel_id,),
            ).fetchone()
            attempts = int(row["attempt_count"]) if row else 1
            state = "dead_letter" if attempts >= 5 else "retry_wait"
            compact_reason = reason[:500]
            conn.execute(
                """UPDATE room_kernel_cancel_outbox
                   SET state=?,available_at_ms=?,lease_until_ms=0,last_error=?
                   WHERE cancel_id=?""",
                (
                    state,
                    int(now_ms) + min(60_000, 1000 * (2**attempts)),
                    compact_reason,
                    cancel_id,
                ),
            )
            if state == "dead_letter" and row is not None:
                session_id = str(row["session_id"])
                for surface in _RUNTIME_CANCEL_SURFACES:
                    detail = {
                        "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                        "surface": surface,
                        "state": "unknown",
                        "targetIds": [session_id],
                        "errors": [compact_reason],
                    }
                    conn.execute(
                        """UPDATE room_v2_runtime_cancel_surface_receipts
                           SET state='unknown',detail_json=?,updated_at_ms=?
                           WHERE cancel_id=? AND surface=?""",
                        (_json(detail), int(now_ms), cancel_id, surface),
                    )
                return self._finalize_exhausted_cancel_roots(conn, now_ms=now_ms)
            return []

    def _finalize_exhausted_cancel_roots(
        self,
        conn: sqlite3.Connection,
        *,
        now_ms: int,
    ) -> list[dict[str, object]]:
        receipts: list[dict[str, object]] = []
        root_ids = [
            str(row["root_id"])
            for row in conn.execute(
                """SELECT DISTINCT cancel.root_id
                   FROM room_kernel_cancel_outbox cancel
                   JOIN room_kernel_roots root USING(root_id)
                   WHERE cancel.terminalize_root=1
                     AND cancel.state='dead_letter'
                     AND root.state IN ('cancelling','cancelled_with_unknowns')
                     AND root.terminal_receipt_id IS NULL"""
            ).fetchall()
        ]
        for root_id in root_ids:
            pending = int(
                conn.execute(
                    """SELECT COUNT(*) FROM room_kernel_cancel_outbox
                       WHERE root_id=? AND terminalize_root=1
                         AND state NOT IN ('applied','dead_letter')""",
                    (root_id,),
                ).fetchone()[0]
            )
            if pending:
                continue
            dispatch_ids = [
                str(row["dispatch_id"])
                for row in conn.execute(
                    """SELECT dispatch_id FROM room_kernel_cancel_outbox
                       WHERE root_id=? AND terminalize_root=1
                         AND state='dead_letter'""",
                    (root_id,),
                ).fetchall()
            ]
            for dispatch_id in dispatch_ids:
                conn.execute(
                    """UPDATE room_kernel_runtime_effects
                       SET state='unknown',updated_at_ms=?
                       WHERE dispatch_id=?
                         AND state IN ('intent','accepted','unknown')""",
                    (int(now_ms), dispatch_id),
                )
                conn.execute(
                    """UPDATE room_kernel_abort_scopes
                       SET state='unknown',updated_at_ms=?
                       WHERE dispatch_id=?
                         AND state IN ('registered','cancelling','unknown')""",
                    (int(now_ms), dispatch_id),
                )
                self._settle_dispatch_limits(
                    conn,
                    dispatch_id,
                    usage=None,
                    consumed=False,
                    now_ms=now_ms,
                )
            receipts.append(
                self._terminal_cancel(
                    conn,
                    root_id,
                    now_ms=now_ms,
                    cancellation_outcome="cancelled_with_unknowns",
                )
            )
        return receipts

    @staticmethod
    def _enqueue_cancel(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        dispatch_id: str,
        session_id: str,
        generation: int,
        terminalize_root: bool,
        now_ms: int,
    ) -> None:
        effect = conn.execute(
            "SELECT state FROM room_kernel_runtime_effects WHERE dispatch_id=?",
            (dispatch_id,),
        ).fetchone()
        if effect is None or str(effect["state"]) not in {
            "intent",
            "accepted",
            "unknown",
        }:
            return
        cancel_id = _stable_id("room-cancel", root_id, dispatch_id, str(generation))
        conn.execute("""INSERT OR IGNORE INTO room_kernel_cancel_outbox(
            cancel_id,root_id,dispatch_id,session_id,generation,terminalize_root,state,available_at_ms,created_at_ms)
            VALUES (?,?,?,?,?,?,'pending',?,?)""", (
                cancel_id, root_id, dispatch_id, session_id, int(generation),
                int(terminalize_root), int(now_ms), int(now_ms),
            ))
        conn.execute(
            "UPDATE room_kernel_abort_scopes SET state='cancelling',updated_at_ms=? WHERE dispatch_id=? AND state IN ('registered','cancelling','unknown')",
            (int(now_ms), dispatch_id),
        )
        for surface in _RUNTIME_CANCEL_SURFACES:
            detail = {
                "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                "surface": surface,
                "state": "requested",
                "targetIds": [session_id],
            }
            conn.execute(
                """INSERT OR IGNORE INTO room_v2_runtime_cancel_surface_receipts(
                   cancel_id,surface,state,target_ref,detail_json,updated_at_ms)
                   VALUES (?,?,'requested',?,?,?)""",
                (cancel_id, surface, session_id, _json(detail), int(now_ms)),
            )

    def _terminal_cancel(
        self,
        conn: sqlite3.Connection,
        root_id: str,
        *,
        now_ms: int,
        cancellation_outcome: str = "cancelled",
    ) -> dict[str, object]:
        if cancellation_outcome not in {
            "cancelled",
            "cancelled_with_unknowns",
        }:
            raise RoomKernelFenceError(
                "terminal cancellation outcome is invalid"
            )
        root = self._root_row(conn, root_id)
        receipt = self._receipt(conn, root_id=root_id, command_id=None, receipt_kind="terminal", status="applied",
            generation=int(root["generation"]), details={"terminalState": cancellation_outcome, "quiescent": True}, now_ms=now_ms)
        conn.execute(
            """UPDATE room_kernel_roots
               SET state=?,terminal_receipt_id=?,updated_at_ms=?
               WHERE root_id=?""",
            (
                cancellation_outcome,
                receipt["receiptId"],
                int(now_ms),
                root_id,
            ),
        )
        return receipt

    def accept_runtime_receipt(
        self,
        *,
        lease_token: str,
        runtime_receipt: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Fence the cross-process ACK before work is considered running."""

        with self._connect(immediate=True) as conn:
            lease = conn.execute(
                "SELECT * FROM room_kernel_leases WHERE lease_token = ?",
                (lease_token,),
            ).fetchone()
            if lease is None or str(lease["state"]) != "active":
                raise RoomKernelFenceError("runtime receipt references an inactive lease")
            root = self._root_row(conn, str(lease["root_id"]))
            dispatch, dispatch_payload = self._assert_lease_identity(
                conn,
                lease,
            )
            generation = int(lease["generation"])
            if generation != int(root["generation"]) or generation != int(dispatch["generation"]):
                raise RoomKernelFenceError("runtime receipt generation is stale")
            accepted_turn_id = str(
                runtime_receipt.get("turnId") or ""
            ).strip()
            if (
                runtime_receipt.get("schemaVersion")
                != "wisdom-weasel.room-runtime-receipt.v1"
                or runtime_receipt.get("receiptKind") != "dispatch_accepted"
                or runtime_receipt.get("status") != "accepted"
                or runtime_receipt.get("rootId") != lease["root_id"]
                or runtime_receipt.get("dispatchId") != lease["dispatch_id"]
                or runtime_receipt.get("sessionId")
                != dispatch["target_session_id"]
                or int(runtime_receipt.get("generation", -1)) != generation
                or int(runtime_receipt.get("capabilityEpoch", -1))
                != int(dispatch_payload.get("capabilityEpoch", -1))
                or not accepted_turn_id
            ):
                raise RoomKernelFenceError("runtime receipt does not match the leased Dispatch")
            accepted_attempt = int(dispatch_payload.get("attempt") or 0)
            accepted_runtime = dict(runtime_receipt)
            accepted_runtime["turnId"] = accepted_turn_id
            accepted_runtime["dispatchAttempt"] = accepted_attempt
            conn.execute(
                """UPDATE room_kernel_runtime_effects SET state='accepted',runtime_receipt_json=?,updated_at_ms=?
                   WHERE dispatch_id=?""",
                (_json(accepted_runtime), int(now_ms), lease["dispatch_id"]),
            )
            conn.execute(
                "UPDATE room_kernel_dispatches SET state = 'running', updated_at_ms = ? WHERE dispatch_id = ? AND state = 'leased'",
                (int(now_ms), lease["dispatch_id"]),
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state = 'running', updated_at_ms = ? WHERE dispatch_id = ? AND state = 'leased'",
                (int(now_ms), lease["dispatch_id"]),
            )
            # The 30-second lease fences delivery to Pi, not the lifetime of
            # the Agent run. Once Pi has returned the typed dispatch ACK, the
            # Root deadline and cancel scope own execution liveness.
            conn.execute(
                "UPDATE room_kernel_leases SET state = 'accepted', updated_at_ms = ? WHERE lease_id = ? AND state = 'active'",
                (int(now_ms), lease["lease_id"]),
            )
            return self._receipt(
                conn, root_id=str(lease["root_id"]), command_id=None,
                receipt_kind="runtime_accepted", status="applied", generation=generation,
                details={"dispatchId": str(lease["dispatch_id"]), "leaseId": str(lease["lease_id"]), "runtimeReceipt": dict(runtime_receipt)},
                now_ms=now_ms,
            )

    def record_runtime_preflight_failure(
        self,
        *,
        lease_token: str,
        now_ms: int,
        reason_code: str = "runtime_dispatch_preflight_failed",
    ) -> dict[str, object]:
        """Retry a failure proven to have happened before ``room.dispatch``.

        The worker may call this only when its runtime intent callback was not
        invoked. No Pi turn can therefore exist for this lease, so completing
        the lease and retrying is safe; expiry reconciliation is reserved for
        failures after the callback, where delivery is genuinely unknown.
        """

        normalized_reason = (
            str(reason_code or "").strip()[:120]
            or "runtime_dispatch_preflight_failed"
        )
        with self._connect(immediate=True) as conn:
            lease = conn.execute(
                "SELECT * FROM room_kernel_leases WHERE lease_token=?",
                (_required(lease_token, "lease_token"),),
            ).fetchone()
            if lease is None:
                raise RoomKernelFenceError("runtime preflight lease is unknown")
            dispatch, _task_payload = self._assert_lease_identity(
                conn,
                lease,
            )
            root = self._root_row(conn, str(lease["root_id"]))
            if (
                str(lease["state"]) != "active"
                or str(dispatch["state"]) != "leased"
                or int(lease["generation"]) != int(dispatch["generation"])
                or int(dispatch["generation"]) != int(root["generation"])
            ):
                raise RoomKernelFenceError(
                    "runtime preflight failure lost its active Dispatch fence"
                )
            retry_limits = conn.execute(
                """SELECT retry_limit,retry_used,deadline_at_ms
                   FROM room_kernel_root_limits WHERE root_id=?""",
                (root["root_id"],),
            ).fetchone()
            can_retry = (
                str(root["state"]) == "running"
                and retry_limits is not None
                and int(retry_limits["retry_used"])
                < int(retry_limits["retry_limit"])
            )
            if can_retry:
                retry_budget_used = int(retry_limits["retry_used"]) + 1
                delay_ms = min(
                    RUNTIME_RETRY_MAX_DELAY_MS,
                    RUNTIME_RETRY_BASE_DELAY_MS
                    * (2 ** min(retry_budget_used - 1, 5)),
                )
                available_at_ms = int(now_ms) + delay_ms
                if available_at_ms < int(retry_limits["deadline_at_ms"]):
                    retry_payload = json.loads(str(dispatch["payload_json"]))
                    retry_payload["attempt"] = (
                        int(retry_payload.get("attempt") or 0) + 1
                    )
                    validate_kernel_contract(
                        "dispatchEnvelope",
                        retry_payload,
                    )
                    receipt = self._receipt(
                        conn,
                        root_id=str(root["root_id"]),
                        command_id=None,
                        receipt_kind="runtime_retry_scheduled",
                        status="applied",
                        generation=int(dispatch["generation"]),
                        details={
                            "dispatchId": str(dispatch["dispatch_id"]),
                            "leaseId": str(lease["lease_id"]),
                            "reasonCode": normalized_reason,
                            "attempt": int(retry_payload["attempt"]),
                            "retryBudgetUsed": retry_budget_used,
                            "availableAtMs": available_at_ms,
                            "hadRuntimeIntent": False,
                        },
                        now_ms=now_ms,
                    )
                    conn.execute(
                        """UPDATE room_kernel_root_limits
                           SET retry_used=retry_used+1,updated_at_ms=?
                           WHERE root_id=?""",
                        (int(now_ms), root["root_id"]),
                    )
                    conn.execute(
                        """UPDATE room_kernel_dispatches
                           SET state='retry_wait',payload_json=?,updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (
                            _json(retry_payload),
                            int(now_ms),
                            dispatch["dispatch_id"],
                        ),
                    )
                    conn.execute(
                        """UPDATE room_kernel_outbox
                           SET state='retry_wait',available_at_ms=?,
                               payload_json=?,updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (
                            available_at_ms,
                            _json(retry_payload),
                            int(now_ms),
                            dispatch["dispatch_id"],
                        ),
                    )
                    conn.execute(
                        """UPDATE room_kernel_leases
                           SET state='completed',updated_at_ms=?
                           WHERE lease_id=? AND state='active'""",
                        (int(now_ms), lease["lease_id"]),
                    )
                    conn.execute(
                        """UPDATE room_kernel_runtime_effects
                           SET state='intent',runtime_receipt_json='{}',
                               updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (int(now_ms), dispatch["dispatch_id"]),
                    )
                    conn.execute(
                        """UPDATE room_kernel_abort_scopes
                           SET state='registered',cancel_receipt_json='{}',
                               updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (int(now_ms), dispatch["dispatch_id"]),
                    )
                    return receipt
            receipt = self._receipt(
                conn,
                root_id=str(root["root_id"]),
                command_id=None,
                receipt_kind="runtime_failed",
                status="applied",
                generation=int(dispatch["generation"]),
                details={
                    "dispatchId": str(dispatch["dispatch_id"]),
                    "leaseId": str(lease["lease_id"]),
                    "reasonCode": normalized_reason,
                    "hadRuntimeIntent": False,
                },
                now_ms=now_ms,
            )
            runtime_receipt = {
                "schemaVersion": "wisdom-weasel.room-runtime-failure.v1",
                "status": "failed",
                "reasonCode": normalized_reason,
                "hadRuntimeIntent": False,
            }
            self._block_failed_dispatch(
                conn,
                dispatch=dispatch,
                root=root,
                now_ms=now_ms,
                resource_usage=None,
                runtime_receipt=runtime_receipt,
            )
            dead_letter_id = _stable_id(
                "room-dead-letter",
                str(dispatch["dispatch_id"]),
                normalized_reason,
            )
            conn.execute(
                """INSERT INTO room_kernel_dead_letters(
                   dead_letter_id,root_id,dispatch_id,reason_code,
                   payload_json,created_at_ms)
                   VALUES (?,?,?,?,?,?)""",
                (
                    dead_letter_id,
                    root["root_id"],
                    dispatch["dispatch_id"],
                    normalized_reason,
                    _json(
                        {
                            "leaseId": str(lease["lease_id"]),
                            "kernelReceipt": receipt,
                        }
                    ),
                    int(now_ms),
                ),
            )
            return receipt

    def record_runtime_dispatch_intent(self, dispatch_id: str, *, now_ms: int) -> None:
        """Persist the cancellable target before crossing the Pi process boundary."""
        with self._connect(immediate=True) as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            conn.execute(
                """INSERT INTO room_kernel_runtime_effects(dispatch_id,root_id,session_id,dispatch_generation,state,updated_at_ms)
                   VALUES (?,?,?,?,'intent',?)
                   ON CONFLICT(dispatch_id) DO UPDATE SET
                     state='intent',
                     runtime_receipt_json='{}',
                     updated_at_ms=excluded.updated_at_ms""",
                (dispatch_id, dispatch["root_id"], dispatch["target_session_id"], dispatch["generation"], int(now_ms)),
            )
            conn.execute(
                """INSERT INTO room_kernel_abort_scopes(
                   dispatch_id,root_id,session_id,generation,state,surfaces_json,updated_at_ms)
                   VALUES (?,?,?,?,'registered',?,?)
                   ON CONFLICT(dispatch_id) DO UPDATE SET
                     state='registered',
                     cancel_receipt_json='{}',
                     updated_at_ms=excluded.updated_at_ms""",
                (
                    dispatch_id, dispatch["root_id"], dispatch["target_session_id"],
                    dispatch["generation"], _json(list(_ABORT_SURFACES)), int(now_ms),
                ),
            )

    def abort_scope(self, dispatch_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_kernel_abort_scopes WHERE dispatch_id=?", (dispatch_id,)
            ).fetchone()
        if row is None:
            raise KeyError(dispatch_id)
        return {
            "dispatchId": str(row["dispatch_id"]),
            "rootId": str(row["root_id"]),
            "sessionId": str(row["session_id"]),
            "generation": int(row["generation"]),
            "state": str(row["state"]),
            "surfaces": json.loads(str(row["surfaces_json"])),
            "cancelReceipt": json.loads(str(row["cancel_receipt_json"])),
        }

    def active_runtime_targets(
        self,
        root_id: str,
        *,
        target_kind: str = "root",
        target_id: str = "",
    ) -> list[dict[str, object]]:
        with self._connect() as conn:
            clauses = ["d.root_id = ?", "d.state IN ('leased','running','retry_wait','timer_wait')"]
            values: list[object] = [root_id]
            if target_kind == "dispatch":
                clauses.append("d.dispatch_id = ?")
                values.append(_required(target_id, "target_id"))
            elif target_kind == "task":
                clauses.append("d.task_id = ?")
                values.append(_required(target_id, "target_id"))
            elif target_kind != "root":
                raise ValueError("runtime target kind must be root, task, or dispatch")
            rows = conn.execute(
                """SELECT d.dispatch_id, d.target_session_id, d.generation
                   FROM room_kernel_dispatches d
                   WHERE """ + " AND ".join(clauses) + " ORDER BY d.dispatch_id",
                values,
            ).fetchall()
            return [
                {
                    "dispatchId": str(row["dispatch_id"]),
                    "sessionId": str(row["target_session_id"]),
                    "generation": int(row["generation"]),
                }
                for row in rows
            ]

    def room_active_runtime_targets(self, room_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT d.dispatch_id, d.root_id, d.target_session_id, d.generation,
                          d.updated_at_ms
                   FROM room_kernel_dispatches d
                   JOIN room_kernel_roots r ON r.root_id = d.root_id
                   WHERE r.room_id = ?
                     AND r.state NOT IN ('cancelled','cancelled_with_unknowns','completed','failed')
                     AND d.state IN ('leased','running','retry_wait','timer_wait')
                   ORDER BY d.root_id, d.dispatch_id""",
                (room_id,),
            ).fetchall()
            return [
                {
                    "dispatchId": str(row["dispatch_id"]),
                    "rootId": str(row["root_id"]),
                    "sessionId": str(row["target_session_id"]),
                    "generation": int(row["generation"]),
                    "updatedAtMs": int(row["updated_at_ms"]),
                }
                for row in rows
            ]

    def session_binding(self, session_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT d.dispatch_id, d.root_id, d.generation, d.state,
                          d.payload_json, r.room_id,
                          effects.state AS runtime_state,
                          effects.runtime_receipt_json
                   FROM room_kernel_dispatches d
                   JOIN room_kernel_roots r ON r.root_id = d.root_id
                   LEFT JOIN room_kernel_runtime_effects effects
                     ON effects.dispatch_id = d.dispatch_id
                   WHERE d.target_session_id = ?
                     AND r.state NOT IN ('cancelled','cancelled_with_unknowns','completed','failed')
                     AND d.state IN ('pending','leased','running','retry_wait','timer_wait')
                   ORDER BY
                     CASE d.state
                       WHEN 'running' THEN 0
                       WHEN 'leased' THEN 1
                       WHEN 'retry_wait' THEN 2
                       WHEN 'timer_wait' THEN 3
                       ELSE 4
                     END,
                     d.updated_at_ms DESC,
                     d.dispatch_id DESC
                   LIMIT 1""",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            runtime_receipt = (
                json.loads(str(row["runtime_receipt_json"] or "{}"))
                if str(row["runtime_state"] or "") == "accepted"
                else {}
            )
            dispatch_payload = json.loads(str(row["payload_json"]))
            return {
                "roomId": str(row["room_id"]),
                "rootId": str(row["root_id"]),
                "dispatchId": str(row["dispatch_id"]),
                "taskId": str(dispatch_payload.get("taskId") or ""),
                "intentKind": str(
                    dispatch_payload.get("intentKind") or ""
                ),
                "generation": int(row["generation"]),
                "state": str(row["state"]),
                "runtimeTurnId": str(
                    runtime_receipt.get("turnId") or ""
                ),
                "attempt": int(
                    runtime_receipt.get(
                        "dispatchAttempt",
                        dispatch_payload.get("attempt") or 0,
                    )
                ),
            }

    def is_managed_runtime_turn(
        self,
        session_id: str,
        runtime_turn_id: str,
    ) -> bool:
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(runtime_turn_id or "").strip()
        if not normalized_session_id or not normalized_turn_id:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1
                   FROM room_kernel_receipts receipts
                   JOIN room_kernel_dispatches dispatches
                     ON dispatches.dispatch_id = json_extract(
                        receipts.payload_json,
                        '$.details.dispatchId'
                     )
                   WHERE receipts.receipt_kind = 'runtime_accepted'
                     AND dispatches.target_session_id = ?
                     AND json_extract(
                        receipts.payload_json,
                        '$.details.runtimeReceipt.turnId'
                     ) = ?
                   LIMIT 1""",
                (normalized_session_id, normalized_turn_id),
            ).fetchone()
        return row is not None

    def response_provenance_binding(
        self,
        session_id: str,
        runtime_turn_id: str,
        tool_call_id: str,
    ) -> dict[str, object] | None:
        """Resolve one settled response to its exact applied ``room_commit``.

        ``session_binding`` deliberately exposes only live ownership.  A
        Tool-only response receipt is emitted after settlement, when that live
        binding has already been retired, so provenance needs a separate
        historical lookup fenced by Session, runtime turn, Tool call,
        capability manifest, successful execution receipt, and committed
        Dispatch.  Never use this method to authorize new work.
        """

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(runtime_turn_id or "").strip()
        normalized_tool_call_id = str(tool_call_id or "").strip()
        if (
            not normalized_session_id
            or not normalized_turn_id
            or not normalized_tool_call_id
        ):
            return None
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT
                          dispatches.dispatch_id,
                          dispatches.root_id,
                          dispatches.generation,
                          dispatches.state,
                          dispatches.payload_json,
                          roots.room_id,
                          effects.runtime_receipt_json
                   FROM room_kernel_dispatches dispatches
                   JOIN room_kernel_roots roots
                     ON roots.root_id = dispatches.root_id
                   JOIN room_kernel_runtime_effects effects
                     ON effects.dispatch_id = dispatches.dispatch_id
                   JOIN room_v2_capability_manifests manifests
                     ON manifests.dispatch_id = dispatches.dispatch_id
                    AND manifests.root_id = dispatches.root_id
                    AND manifests.generation = dispatches.generation
                   JOIN room_v2_tool_invocation_receipts invocations
                     ON invocations.manifest_id = manifests.manifest_id
                    AND invocations.manifest_hash = manifests.manifest_hash
                   JOIN room_v2_tool_execution_receipts executions
                     ON executions.invocation_receipt_id = invocations.receipt_id
                   WHERE dispatches.target_session_id = ?
                     AND dispatches.state = 'committed'
                     AND json_extract(
                       effects.runtime_receipt_json,
                       '$.turnId'
                     ) = ?
                     AND invocations.invocation_key = ?
                     AND invocations.canonical_tool_name = 'room_commit'
                     AND invocations.authorization_state = 'authorized'
                     AND executions.session_id = ?
                     AND executions.tool_name = 'room_commit'
                     AND executions.status = 'applied'
                   ORDER BY dispatches.updated_at_ms DESC,
                            dispatches.dispatch_id DESC
                   LIMIT 2""",
                (
                    normalized_session_id,
                    normalized_turn_id,
                    normalized_tool_call_id,
                    normalized_session_id,
                ),
            ).fetchall()
        if len(rows) != 1:
            return None
        row = rows[0]
        dispatch_payload = json.loads(str(row["payload_json"]))
        runtime_receipt = json.loads(
            str(row["runtime_receipt_json"] or "{}")
        )
        return {
            "roomId": str(row["room_id"]),
            "rootId": str(row["root_id"]),
            "dispatchId": str(row["dispatch_id"]),
            "taskId": str(dispatch_payload.get("taskId") or ""),
            "intentKind": str(dispatch_payload.get("intentKind") or ""),
            "generation": int(row["generation"]),
            "state": str(row["state"]),
            "runtimeTurnId": normalized_turn_id,
            "attempt": int(
                runtime_receipt.get(
                    "dispatchAttempt",
                    dispatch_payload.get("attempt") or 0,
                )
            ),
            "toolCallId": normalized_tool_call_id,
        }

    def room_ids(self) -> list[str]:
        with self._connect() as conn:
            return [
                str(row[0])
                for row in conn.execute(
                    "SELECT DISTINCT room_id FROM room_kernel_roots ORDER BY room_id"
                ).fetchall()
            ]

    def root_ids(self, room_id: str) -> list[str]:
        with self._connect() as conn:
            return [
                str(row[0])
                for row in conn.execute(
                    "SELECT root_id FROM room_kernel_roots WHERE room_id = ? ORDER BY root_id",
                    (room_id,),
                ).fetchall()
            ]

    def screen_state(
        self,
        room_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        """Project one authoritative Room screen state from one Kernel read.

        This is the only backend owner for active-Root selection, lifecycle
        phase, typed waiting, runnable work, governance readiness, and final
        delivery identity.  Callers may pass their projection transaction so
        the snapshot and its SSE event cannot mix facts from different commits.
        """

        def read(active: sqlite3.Connection) -> dict[str, object]:
            normalized_room_id = _required(room_id, "room_id")
            root = active.execute(
                """SELECT * FROM room_kernel_roots
                   WHERE room_id=?
                   ORDER BY updated_at_ms DESC,generation DESC,
                            created_at_ms DESC,root_id DESC
                   LIMIT 1""",
                (normalized_room_id,),
            ).fetchone()
            if root is None:
                state = {
                    "schemaVersion": ROOM_SCREEN_STATE_SCHEMA_VERSION,
                    "roomId": normalized_room_id,
                    "activeRootId": None,
                    "activeRootGeneration": None,
                    "phase": "idle",
                    "waitReason": None,
                    "runnableFrontier": {
                        "taskIds": [],
                        "dispatchIds": [],
                    },
                    "integrationReadiness": {
                        "ready": True,
                        "reason": None,
                        "pendingTaskIds": [],
                    },
                    "reviewReadiness": {
                        "ready": True,
                        "reason": None,
                        "pendingTaskIds": [],
                    },
                    "finalDeliveryPostId": None,
                    "recommendedNextAction": "align_requirement",
                }
                validate_kernel_contract("roomScreenState", state)
                return state

            root_id = str(root["root_id"])
            generation = int(root["generation"])
            root_state = str(root["state"])
            intake = self._intake_phase_state_locked(
                active,
                root_id=root_id,
            )
            phase = _room_screen_phase(
                root_state=root_state,
                intake_phase=str((intake or {}).get("phase") or ""),
            )
            wait_reason = self._screen_wait_reason_locked(
                active,
                root_id=root_id,
                generation=generation,
                root_state=root_state,
                intake_phase=str((intake or {}).get("phase") or ""),
            )
            frontier_rows = active.execute(
                """SELECT dispatch_id,task_id
                   FROM room_kernel_dispatches
                   WHERE root_id=? AND generation=?
                     AND state IN ('pending','retry_wait','timer_wait')
                   ORDER BY created_at_ms,dispatch_id""",
                (root_id, generation),
            ).fetchall()
            dispatch_ids = [str(row["dispatch_id"]) for row in frontier_rows]
            task_ids = list(
                dict.fromkeys(str(row["task_id"]) for row in frontier_rows)
            )

            governance = self._terminal_governance_fences(
                active,
                root_id=root_id,
            )
            if governance["pendingInterventions"]:
                phase = "waiting"
                wait_reason = {
                    "kind": "managed",
                    "reason": "正在把你的最新修正纳入当前任务",
                    "requiresUserAction": False,
                }
            pending_integrations = list(governance["pendingIntegrations"])
            integration_task_ids = sorted(
                {
                    str(item.get("taskId") or "")
                    for item in pending_integrations
                    if str(item.get("taskId") or "").strip()
                }
            )
            integration_ready = not pending_integrations
            integration = {
                "ready": integration_ready,
                "reason": (
                    None
                    if integration_ready
                    else f"还有 {len(pending_integrations)} 项成果等待安全集成"
                ),
                "pendingTaskIds": integration_task_ids,
            }

            review_blocks = [
                *list(governance["reviewFences"]),
                *list(governance["unresolvedBlockingFindings"]),
                *list(governance["reviewEvidenceMismatches"]),
            ]
            review_task_ids = sorted(
                {
                    str(
                        item.get("taskId")
                        or item.get("reviewedTaskId")
                        or ""
                    )
                    for item in review_blocks
                    if str(
                        item.get("taskId")
                        or item.get("reviewedTaskId")
                        or ""
                    ).strip()
                }
            )
            review_ready = not review_blocks
            review = {
                "ready": review_ready,
                "reason": (
                    None
                    if review_ready
                    else "独立复核尚未满足最终交付条件"
                ),
                "pendingTaskIds": review_task_ids,
            }
            final_post_id = self._screen_final_delivery_post_id_locked(
                active,
                root=root,
            )
            next_action = _room_screen_next_action(
                phase=phase,
                wait_reason=wait_reason,
                has_frontier=bool(dispatch_ids),
                integration_ready=integration_ready,
                review_ready=review_ready,
            )
            state = {
                "schemaVersion": ROOM_SCREEN_STATE_SCHEMA_VERSION,
                "roomId": normalized_room_id,
                "activeRootId": root_id,
                "activeRootGeneration": generation,
                "phase": phase,
                "waitReason": wait_reason,
                "runnableFrontier": {
                    "taskIds": task_ids,
                    "dispatchIds": dispatch_ids,
                },
                "integrationReadiness": integration,
                "reviewReadiness": review,
                "finalDeliveryPostId": final_post_id,
                "recommendedNextAction": next_action,
            }
            validate_kernel_contract("roomScreenState", state)
            return state

        if conn is not None:
            return read(conn)
        with self._connect() as active:
            return read(active)

    @staticmethod
    def _screen_wait_reason_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        generation: int,
        root_state: str,
        intake_phase: str,
    ) -> dict[str, object] | None:
        if root_state == "blocked":
            return {
                "kind": "blocked",
                "reason": "任务遇到需要处理的阻塞",
                "requiresUserAction": True,
            }
        if root_state != "waiting":
            return None
        rows = conn.execute(
            """SELECT continuation.*
               FROM room_kernel_continuations AS continuation
               JOIN room_kernel_dispatches AS dispatch
                 ON dispatch.dispatch_id=continuation.parent_dispatch_id
               WHERE continuation.root_id=?
                 AND dispatch.generation=?
                 AND continuation.state IN ('applied','retry_required')
                 AND continuation.decision='wait'
               ORDER BY continuation.created_at_ms DESC,
                        continuation.continuation_id DESC""",
            (root_id, generation),
        ).fetchall()
        for row in rows:
            payload = _room_continuation_payload(conn, row)
            waiting_for = str(payload.get("waitingFor") or "").strip()
            if waiting_for not in {"user", "participant", "external"}:
                continue
            reason = str(
                payload.get("question")
                or payload.get("resumeCondition")
                or ""
            ).strip()
            if not reason:
                reason = {
                    "user": "正在等你补充一个决定",
                    "participant": "正在等待伙伴完成当前工作",
                    "external": "正在等待外部条件满足，满足后会自动继续",
                }[waiting_for]
            return {
                "kind": waiting_for,
                "reason": reason,
                "requiresUserAction": waiting_for == "user",
            }
        if intake_phase == "awaiting_start":
            return {
                "kind": "user",
                "reason": "分工已经准备好，等你确认并点击“开始行动”",
                "requiresUserAction": True,
            }
        return {
            "kind": "managed",
            "reason": "任务正在安全等待，满足继续条件后会自动推进",
            "requiresUserAction": False,
        }

    def _screen_final_delivery_post_id_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root: sqlite3.Row,
    ) -> str | None:
        if str(root["state"]) != "completed":
            return None
        try:
            report = self._report_dispatch_locked(
                conn,
                root_id=str(root["root_id"]),
            )
        except (KeyError, RoomKernelFenceError, TypeError, ValueError):
            return None
        terminal = (
            report.get("reporterTerminalReceipt")
            if isinstance(report, Mapping)
            else None
        )
        details = terminal.get("details") if isinstance(terminal, Mapping) else None
        post_id = (
            str(details.get("finalPostId") or "").strip()
            if isinstance(details, Mapping)
            else ""
        )
        if not post_id:
            return None
        row = conn.execute(
            "SELECT payload_json FROM room_kernel_posts WHERE post_id=? AND room_id=?",
            (post_id, str(root["room_id"])),
        ).fetchone()
        if row is None:
            return None
        try:
            post = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(post, Mapping):
            return None
        reporter_id = str(root["reporter_participant_id"] or "").strip()
        post_generation = post.get("generation")
        if any(
            (
                post.get("rootId") != str(root["root_id"]),
                not isinstance(post_generation, int),
                post_generation != int(root["generation"]),
                post.get("kind") != "result",
                post.get("authorActorRef") != reporter_id,
                not isinstance(post.get("publicationSource"), Mapping),
                post.get("publicationSource", {}).get("kind") != "room_commit",
            )
        ):
            return None
        return post_id

    def mark_runtime_cancel_unknown(
        self,
        *,
        root_id: str,
        dispatch_ids: list[str],
        reason: str,
        now_ms: int,
    ) -> list[dict[str, object]]:
        receipts: list[dict[str, object]] = []
        with self._connect(immediate=True) as conn:
            root = self._root_row(conn, root_id)
            for dispatch_id in sorted(set(dispatch_ids)):
                dispatch = self._dispatch_row(conn, dispatch_id)
                if str(dispatch["root_id"]) != root_id:
                    raise RoomKernelFenceError("unknown cancellation target belongs to another Root")
                conn.execute(
                    "UPDATE room_kernel_dispatches SET state = 'unknown', updated_at_ms = ? WHERE dispatch_id = ?",
                    (int(now_ms), dispatch_id),
                )
                conn.execute(
                    "UPDATE room_kernel_outbox SET state = 'dead_letter', updated_at_ms = ? WHERE dispatch_id = ?",
                    (int(now_ms), dispatch_id),
                )
                dead_id = f"dead-letter:{dispatch_id}:cancel"
                conn.execute(
                    """INSERT OR IGNORE INTO room_kernel_dead_letters(
                       dead_letter_id, root_id, dispatch_id, reason_code, payload_json, created_at_ms
                       ) VALUES (?, ?, ?, 'runtime_cancel_result_unknown', ?, ?)""",
                    (dead_id, root_id, dispatch_id, _json({"reason": reason}), int(now_ms)),
                )
                receipts.append(
                    self._receipt(
                        conn,
                        root_id=root_id,
                        command_id=None,
                        receipt_kind="dispatch_unknown",
                        status="unknown",
                        generation=int(root["generation"]),
                        details={"dispatchId": dispatch_id, "deadLetterId": dead_id, "reason": reason},
                        now_ms=now_ms,
                    )
                )
            conn.execute(
                "UPDATE room_kernel_roots SET state = 'cancelled_with_unknowns', updated_at_ms = ? WHERE root_id = ?",
                (int(now_ms), root_id),
            )
        return receipts

    def record_learning_signal(
        self,
        *,
        root_id: str,
        dispatch_id: str,
        receipt_kind: str,
        status: str,
        reason: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Persist a Kernel-lineage receipt before governance observes a failure."""

        with self._connect(immediate=True) as conn:
            root = self._root_row(conn, root_id)
            dispatch = self._dispatch_row(conn, dispatch_id)
            if str(dispatch["root_id"]) != root_id:
                raise RoomKernelFenceError("learning signal Dispatch belongs to another Root")
            return self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind=receipt_kind,
                status=status,
                generation=int(root["generation"]),
                details={"dispatchId": dispatch_id, "reason": reason},
                now_ms=now_ms,
            )

    def enqueue_collaboration(
        self,
        *,
        parent_dispatch_id: str,
        child_task: Mapping[str, object],
        child_dispatch: Mapping[str, object],
        generation: int,
        invocation_receipt_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Atomically spawn one bounded child Task while the parent keeps running."""

        validate_kernel_contract("roomTask", child_task)
        validate_kernel_contract("dispatchEnvelope", child_dispatch)
        with self._connect(immediate=True) as conn:
            parent = self._dispatch_row(conn, parent_dispatch_id)
            root = self._root_row(conn, str(parent["root_id"]))
            invocation = conn.execute(
                """SELECT i.*, b.session_id AS bound_session_id,
                          b.state AS bound_state
                   FROM room_v2_tool_invocation_receipts i
                   JOIN room_v2_capability_runtime_bindings b
                     ON b.manifest_id=i.manifest_id
                    AND b.manifest_hash=i.manifest_hash
                   WHERE i.receipt_id=?""",
                (invocation_receipt_id,),
            ).fetchone()
            if invocation is None:
                raise RoomKernelFenceError(
                    "Room collaboration invocation receipt is missing"
                )
            command = json.loads(str(invocation["command_json"]))
            if (
                command.get("tool") != "room_collaborate"
                or command.get("dispatchId") != parent_dispatch_id
                or command.get("rootId") != root["root_id"]
                or int(command.get("generation", -1)) != generation
                or str(invocation["bound_session_id"])
                != str(parent["target_session_id"])
                or str(invocation["bound_state"]) != "active"
            ):
                raise RoomKernelFenceError(
                    "Room collaboration invocation lost its parent Dispatch fence"
                )
            if (
                int(root["generation"]) != generation
                or int(parent["generation"]) != generation
            ):
                raise RoomKernelFenceError(
                    "Room collaboration generation is stale"
                )
            if str(parent["state"]) != "running":
                raise RoomKernelFenceError(
                    "Room collaboration parent Dispatch is not running"
                )
            if (
                child_task.get("rootId") != root["root_id"]
                or child_task.get("parentTaskId") != parent["task_id"]
                or child_dispatch.get("rootId") != root["root_id"]
                or child_dispatch.get("taskId") != child_task.get("taskId")
                or child_dispatch.get("parentDispatchId") != parent_dispatch_id
                or int(child_dispatch.get("generation", -1)) != generation
                or int(child_dispatch.get("hopCount", -1))
                != int(parent["hop_count"]) + 1
                or int(child_dispatch.get("depth", -1))
                != int(parent["depth"]) + 1
                or child_task.get("currentOwnerParticipantId")
                != child_dispatch.get("targetParticipantId")
            ):
                raise RoomKernelFenceError(
                    "Room collaboration child does not match parent fences"
                )
            if str(child_dispatch["intentKind"]) == "review":
                desired_criteria = set(
                    _criteria(child_task.get("acceptanceCriterionIds"))
                )
                desired_review_targets = {
                    str(item)
                    for item in child_task.get("reviewOfTaskIds", ())
                    if str(item)
                }
                active_review_rows = conn.execute(
                    """
                    SELECT d.*, t.payload_json AS child_task_payload_json
                    FROM room_kernel_dispatches AS d
                    JOIN room_kernel_tasks AS t ON t.task_id=d.task_id
                    WHERE d.parent_dispatch_id=?
                      AND d.target_participant_id=?
                      AND d.generation=?
                      AND d.intent_kind='review'
                      AND d.state IN ('pending','leased','running')
                    ORDER BY d.created_at_ms,d.dispatch_id
                    """,
                    (
                        parent_dispatch_id,
                        str(child_dispatch["targetParticipantId"]),
                        generation,
                    ),
                ).fetchall()
                for active_review in active_review_rows:
                    active_task = json.loads(
                        str(active_review["child_task_payload_json"])
                    )
                    if set(
                        _criteria(active_task.get("acceptanceCriterionIds"))
                    ) != desired_criteria or {
                        str(item)
                        for item in active_task.get("reviewOfTaskIds", ())
                        if str(item)
                    } != desired_review_targets:
                        continue
                    return self._receipt(
                        conn,
                        root_id=str(root["root_id"]),
                        command_id=None,
                        receipt_kind="duplicate",
                        status="noop",
                        generation=generation,
                        details={
                            "parentTaskId": str(parent["task_id"]),
                            "parentDispatchId": parent_dispatch_id,
                            "childTaskId": str(active_review["task_id"]),
                            "childDispatchId": str(
                                active_review["dispatch_id"]
                            ),
                            "invocationReceiptId": invocation_receipt_id,
                        },
                        now_ms=now_ms,
                    )

            self._insert_task(conn, child_task, now_ms=now_ms)
            dispatch, created = self._enqueue_dispatch(
                conn,
                child_dispatch,
                shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
                now_ms=now_ms,
            )
            return self._receipt(
                conn,
                root_id=str(root["root_id"]),
                command_id=None,
                receipt_kind="accepted" if created else "duplicate",
                status="applied" if created else "noop",
                generation=generation,
                details={
                    "parentTaskId": str(parent["task_id"]),
                    "parentDispatchId": parent_dispatch_id,
                    "childTaskId": str(child_task["taskId"]),
                    "childDispatchId": str(dispatch["dispatchId"]),
                    "invocationReceiptId": invocation_receipt_id,
                },
                now_ms=now_ms,
            )

    @staticmethod
    def project_task_result_payload(
        task_payload: Mapping[str, object],
        *,
        result_kind: str,
        post_proposal: Mapping[str, object] | None,
        quality_gate_receipt: Mapping[str, object],
        evidence_refs: Sequence[object],
        now_ms: int,
    ) -> dict[str, object]:
        """Project one public-safe Task outcome without changing its work revision."""

        result_summary = (
            " ".join(str(post_proposal.get("content") or "").split())[
                :2_000
            ]
            if isinstance(post_proposal, Mapping)
            else ""
        )
        verification_refs = _unique_text(evidence_refs)[:128]
        quality_items = [
            dict(item)
            for item in quality_gate_receipt.get("items") or []
            if isinstance(item, Mapping)
        ]
        public_verifications = [
            {
                "label": f"验收项 {index + 1}",
                "result": str(item.get("status") or "not_verified"),
                "source": "quality_gate",
            }
            for index, item in enumerate(quality_items[:64])
        ]
        artifact_refs = _unique_text(
            [
                str(
                    item.get("receiptId")
                    or item.get("attachmentId")
                    or item.get("mediaId")
                    or item.get("id")
                    or ""
                )
                for item in (
                    post_proposal.get("attachments") or []
                    if isinstance(post_proposal, Mapping)
                    else []
                )
                if isinstance(item, Mapping)
            ]
        )[:128]
        residual_risks = _unique_text(
            quality_gate_receipt.get("residualRisks") or []
        )[:32]
        return {
            **task_payload,
            "resultSummary": result_summary,
            "resultKind": _required(result_kind, "result_kind"),
            "resultAtMs": int(now_ms),
            "verificationCount": len(verification_refs),
            "verifications": public_verifications,
            "artifactRefs": artifact_refs,
            "residualRisks": residual_risks,
        }

    def apply_commit(
        self,
        payload: Mapping[str, object],
        *,
        generation: int,
        now_ms: int,
        post_proposal: Mapping[str, object] | None = None,
        invocation_receipt_id: str = "",
        resource_usage: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        payload = dict(payload)
        validate_kernel_contract("roomCommit", payload)
        quality_gate_receipt = payload.get("qualityGateReceipt")
        if not isinstance(quality_gate_receipt, Mapping):
            raise RoomKernelFenceError(
                "RoomCommit requires a structured qualityGateReceipt"
            )
        if post_proposal is not None:
            validate_kernel_contract("roomPost", post_proposal)
        if (payload.get("action") == "post") != (post_proposal is not None):
            raise RoomKernelFenceError("RoomCommit post action and RoomPost proposal must agree")
        action = str(payload["action"])
        continuation = payload.get("continuation")
        if continuation is not None and not isinstance(continuation, Mapping):
            raise RoomKernelFenceError("RoomCommit continuation must be an object")
        decision = action
        task_transfer_payload: Mapping[str, object] | None = None
        child_task_payload: Mapping[str, object] | None = None
        child_payload: Mapping[str, object] | None = None
        if action == "dispatch":
            if (
                not isinstance(continuation, Mapping)
                or continuation.get("decision") != "dispatch"
            ):
                raise RoomKernelFenceError(
                    "dispatch Commit requires a deterministic continuation"
                )
            task_transfer = continuation.get("taskTransfer")
            child_task = continuation.get("childTask")
            child = continuation.get("childDispatch")
            if (
                not isinstance(child, Mapping)
                or isinstance(task_transfer, Mapping)
                == isinstance(child_task, Mapping)
            ):
                raise RoomKernelFenceError(
                    "dispatch continuation requires childDispatch and exactly "
                    "one of taskTransfer or childTask"
                )
            validate_kernel_contract("dispatchEnvelope", child)
            if isinstance(task_transfer, Mapping):
                task_transfer_payload = task_transfer
            if isinstance(child_task, Mapping):
                validate_kernel_contract("roomTask", child_task)
                child_task_payload = child_task
            child_payload = child
        elif action == "post":
            decision = str(
                continuation.get("decision")
                if isinstance(continuation, Mapping)
                else "wait"
            )
            if decision not in {"dispatch", "wait", "block", "complete"}:
                raise RoomKernelFenceError(
                    "post continuation decision is invalid"
                )
            if decision == "dispatch":
                task_transfer = (
                    continuation.get("taskTransfer")
                    if isinstance(continuation, Mapping)
                    else None
                )
                child_task = (
                    continuation.get("childTask")
                    if isinstance(continuation, Mapping)
                    else None
                )
                child = (
                    continuation.get("childDispatch")
                    if isinstance(continuation, Mapping)
                    else None
                )
                if (
                    not isinstance(child, Mapping)
                    or isinstance(task_transfer, Mapping)
                    == isinstance(child_task, Mapping)
                ):
                    raise RoomKernelFenceError(
                        "post dispatch continuation requires childDispatch and "
                        "exactly one of taskTransfer or childTask"
                    )
                validate_kernel_contract("dispatchEnvelope", child)
                if isinstance(task_transfer, Mapping):
                    task_transfer_payload = task_transfer
                if isinstance(child_task, Mapping):
                    validate_kernel_contract("roomTask", child_task)
                    child_task_payload = child_task
                child_payload = child
        elif (
            isinstance(continuation, Mapping)
            and continuation.get("decision") != action
        ):
            raise RoomKernelFenceError(
                "RoomCommit continuation contradicts its action"
            )
        with self._connect(immediate=True) as conn:
            dispatch = self._dispatch_row(conn, str(payload["dispatchId"]))
            root = self._root_row(conn, str(dispatch["root_id"]))
            task_row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id = ?",
                (str(dispatch["task_id"]),),
            ).fetchone()
            if task_row is None:
                raise RoomKernelFenceError(
                    "RoomCommit Task is missing"
                )
            task_payload = json.loads(str(task_row["payload_json"]))
            if (
                decision == "wait"
                and isinstance(continuation, Mapping)
                and continuation.get("waitingFor") == "user"
                and str(dispatch["target_participant_id"])
                != str(root["facilitator_participant_id"] or "")
            ):
                raise RoomKernelFenceError(
                    "only the Root Facilitator may wait for user input"
                )
            existing = conn.execute(
                "SELECT commit_id FROM room_kernel_commits WHERE dispatch_id = ?",
                (payload["dispatchId"],),
            ).fetchone()
            intake = self._intake_phase_state_locked(
                conn,
                root_id=str(root["root_id"]),
            )
            if (
                intake is not None
                and self._is_active_alignment_dispatch_chain(
                    conn,
                    dispatch,
                    root,
                )
                and decision != "wait"
            ):
                raise RoomKernelFenceError(
                    "authoritative Room alignment may only wait for one "
                    "clarification answer; use room_define to finish alignment"
                )
            if (
                task_payload.get("taskKind") == "review"
                and existing is None
            ):
                submitted_findings = payload.get("reviewFindings", ())
                payload["reviewFindings"] = (
                    self._canonical_review_finding_lineage_locked(
                        conn,
                        root_id=str(root["root_id"]),
                        task_payload=task_payload,
                        submitted_findings=submitted_findings,
                    )
                )
                if submitted_findings:
                    authoritative_evidence_refs = (
                        self._review_finding_evidence_authority_locked(
                            conn,
                            task_payload=task_payload,
                            dispatch=dispatch,
                            commit_payload=payload,
                        )
                    )
                    for finding in submitted_findings:
                        if not isinstance(finding, Mapping):
                            continue
                        finding_evidence_refs = {
                            str(value).strip()
                            for value in finding.get("evidenceRefs", ())
                            if str(value or "").strip()
                        }
                        if (
                            not finding_evidence_refs
                            or not finding_evidence_refs.issubset(
                                authoritative_evidence_refs
                            )
                        ):
                            raise RoomKernelFenceError(
                                "Review Finding cites stale or foreign evidence"
                            )
                # The Kernel-derived lineage is the durable Commit authority,
                # so validate the complete canonical payload again before any
                # state or receipt is written.
                validate_kernel_contract("roomCommit", payload)
            report = self._report_dispatch_locked(
                conn,
                root_id=str(root["root_id"]),
            )
            is_report_dispatch = bool(
                report is not None
                and str(report["dispatch"]["dispatchId"])
                == str(dispatch["dispatch_id"])
            )
            if (
                kernel_owns_room_execution(self.mode)
                and str(dispatch["intent_kind"]) == "close"
                and not is_report_dispatch
            ):
                raise RoomKernelFenceError(
                    "close is reserved for the Root's canonical ReportDispatch"
                )
            if is_report_dispatch:
                root_payload = json.loads(str(root["payload_json"]))
                reporter_id = str(
                    root_payload.get("reporterParticipantId")
                    or root_payload.get("facilitatorParticipantId")
                    or ""
                )
                if (
                    str(dispatch["target_participant_id"]) != reporter_id
                    or task_payload.get("workspacePolicy") != "read_only"
                ):
                    raise RoomKernelFenceError(
                        "ReportDispatch lost its Reporter or read-only fence"
                    )
                if decision == "complete" and post_proposal is None:
                    raise RoomKernelFenceError(
                        "Reporter completion requires one canonical public final reply"
                    )
                if (
                    decision == "complete"
                    and post_proposal is not None
                    and post_proposal.get("kind") != "result"
                ):
                    raise RoomKernelFenceError(
                        "Reporter completion must publish the canonical result"
                    )
            elif (
                kernel_owns_room_execution(self.mode)
                and post_proposal is not None
                and post_proposal.get("kind") == "result"
            ):
                raise RoomKernelFenceError(
                    "only the canonical ReportDispatch may publish a final result"
                )
            try:
                validate_quality_gate_receipt(
                    quality_gate_receipt,
                    decision=decision,
                    root_id=str(root["root_id"]),
                    task_id=str(dispatch["task_id"]),
                    dispatch_id=str(dispatch["dispatch_id"]),
                    generation=int(generation),
                    task_criteria=[
                        str(item)
                        for item in task_payload.get(
                            "acceptanceCriterionIds",
                            [],
                        )
                        if str(item).strip()
                    ],
                    evidence_refs=[
                        str(item)
                        for item in payload.get("evidenceRefs", [])
                    ],
                    requirement_coverage=[
                        str(item)
                        for item in payload.get("requirementCoverage", [])
                    ],
                )
            except RoomQualityGateError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
            dispatch_authority = _dispatch_payload(dispatch)
            if (
                str(dispatch["intent_kind"]) in {"revise", "retry"}
                or int(dispatch_authority.get("attempt") or 0) > 1
            ):
                prior_evidence = (
                    self._prior_acceptance_evidence_refs_locked(
                        conn,
                        root_id=str(root["root_id"]),
                        exclude_dispatch_id=str(dispatch["dispatch_id"]),
                    )
                )
                reused: dict[str, list[str]] = {}
                for item in quality_gate_receipt.get("items") or ():
                    if (
                        not isinstance(item, Mapping)
                        or item.get("status") != "pass"
                    ):
                        continue
                    criterion_id = str(
                        item.get("criterionId") or ""
                    ).strip()
                    stale_refs = prior_evidence.get(criterion_id, set())
                    overlap = sorted(
                        {
                            str(value).strip()
                            for value in item.get("evidenceRefs") or ()
                            if str(value or "").strip() in stale_refs
                        }
                    )
                    if overlap:
                        reused[criterion_id] = overlap
                if reused:
                    raise RoomKernelFenceError(
                        "retry/revision quality evidence must come from the "
                        "current attempt; prior accepted evidence was reused: "
                        + ", ".join(sorted(reused))
                    )
            acceptance_evidence_authority = (
                self._acceptance_evidence_authority_locked(
                    conn,
                    root=root,
                    task_payload=task_payload,
                    dispatch=dispatch,
                    quality_gate_receipt=quality_gate_receipt,
                    commit_payload=payload,
                )
            )
            invocation = None
            if invocation_receipt_id:
                invocation = conn.execute(
                    """SELECT i.*, b.session_id AS bound_session_id, b.state AS bound_state
                       FROM room_v2_tool_invocation_receipts i
                       JOIN room_v2_capability_runtime_bindings b
                         ON b.manifest_id = i.manifest_id AND b.manifest_hash = i.manifest_hash
                       WHERE i.receipt_id = ?""",
                    (invocation_receipt_id,),
                ).fetchone()
                if invocation is None:
                    raise RoomKernelFenceError("RoomCommit invocation receipt is missing")
                command = json.loads(str(invocation["command_json"]))
                if (
                    command.get("dispatchId") != payload["dispatchId"]
                    or command.get("rootId") != root["root_id"]
                    or int(command.get("generation", -1)) != int(generation)
                    or command.get("tool") not in {"room_post", "room_commit"}
                ):
                    raise RoomKernelFenceError("RoomCommit invocation receipt does not match Dispatch fences")
            if generation != int(root["generation"]) or generation != int(dispatch["generation"]):
                return self._receipt(conn, root_id=str(root["root_id"]), command_id=None, receipt_kind="rejected", status="rejected", generation=int(root["generation"]), details={"reason": "stale_generation", "dispatchId": payload["dispatchId"]}, now_ms=now_ms)
            if existing is not None:
                if invocation is not None:
                    execution = conn.execute(
                        "SELECT payload_json FROM room_v2_tool_execution_receipts WHERE invocation_receipt_id = ?",
                        (invocation_receipt_id,),
                    ).fetchone()
                    if execution is None:
                        raise RoomKernelFenceError(
                            "RoomCommit exists without its execution receipt; result is unknown"
                        )
                    replay = json.loads(str(execution["payload_json"]))
                    if replay.get("commitId") != existing["commit_id"]:
                        raise RoomKernelFenceError("invocation receipt was rebound to another RoomCommit")
                    kernel_receipt = replay.get("kernelReceipt")
                    if not isinstance(kernel_receipt, Mapping):
                        raise RoomKernelFenceError("execution receipt has no canonical Kernel receipt")
                    return dict(kernel_receipt)
                return self._receipt(conn, root_id=str(root["root_id"]), command_id=None, receipt_kind="duplicate", status="noop", generation=int(root["generation"]), details={"commitId": str(existing["commit_id"])}, now_ms=now_ms)
            if invocation is not None and str(invocation["bound_state"]) != "active":
                raise RoomKernelFenceError("RoomCommit capability was revoked before execution")
            if str(dispatch["state"]) != "running":
                return self._receipt(conn, root_id=str(root["root_id"]), command_id=None, receipt_kind="rejected", status="rejected", generation=int(root["generation"]), details={"reason": "dispatch_not_running", "dispatchId": payload["dispatchId"], "dispatchState": str(dispatch["state"])}, now_ms=now_ms)
            try:
                settlement = settle_dispatch(
                    SettlementFacts(
                        room_id=str(root["room_id"]),
                        root_id=str(root["root_id"]),
                        task_id=str(dispatch["task_id"]),
                        dispatch_id=str(dispatch["dispatch_id"]),
                        generation=int(generation),
                        dispatch_state=str(dispatch["state"]),
                        task_state=str(task_payload.get("state") or ""),
                        decision=decision,
                        idempotency_key=str(payload["commitId"]),
                    )
                )
            except DomainPolicyError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
            if child_payload is not None:
                if (
                    child_payload.get("rootId") != root["root_id"]
                    or child_payload.get("parentDispatchId")
                    != dispatch["dispatch_id"]
                    or int(child_payload.get("generation", -1)) != generation
                ):
                    raise RoomKernelFenceError(
                        "continuation child Dispatch does not match parent fences"
                    )
                if task_transfer_payload is not None:
                    if (
                        task_transfer_payload.get("taskId")
                        != dispatch["task_id"]
                        or task_transfer_payload.get("fromParticipantId")
                        != task_payload.get("currentOwnerParticipantId")
                        or task_transfer_payload.get("fromParticipantId")
                        != dispatch["target_participant_id"]
                        or int(
                            task_transfer_payload.get(
                                "ownershipRevision",
                                -1,
                            )
                        )
                        != int(task_payload.get("ownershipRevision") or 0) + 1
                        or child_payload.get("taskId")
                        != task_transfer_payload.get("taskId")
                        or task_transfer_payload.get("toParticipantId")
                        != child_payload.get("targetParticipantId")
                    ):
                        raise RoomKernelFenceError(
                            "continuation Task transfer does not match parent fences"
                        )
                else:
                    is_review_handoff = (
                        child_payload.get("intentKind") == "review"
                        and child_task_payload is not None
                        and child_task_payload.get("taskKind") == "review"
                    )
                    is_revision_handoff = (
                        task_payload.get("taskKind") == "review"
                        and child_payload.get("intentKind") == "revise"
                        and child_task_payload is not None
                        and child_task_payload.get("taskKind") == "work"
                    )
                    if child_task_payload is None or (
                        not (is_review_handoff or is_revision_handoff)
                        or child_task_payload.get("rootId") != root["root_id"]
                        or child_task_payload.get("parentTaskId")
                        != dispatch["task_id"]
                        or child_task_payload.get("taskId")
                        != child_payload.get("taskId")
                        or child_task_payload.get("currentOwnerParticipantId")
                        != child_payload.get("targetParticipantId")
                        or child_task_payload.get("state") != "active"
                        or not isinstance(continuation, Mapping)
                        or continuation.get("waitingFor") != "participant"
                        or continuation.get("waitingForParticipantId")
                        != child_payload.get("targetParticipantId")
                        or continuation.get("waitingForDispatchId")
                        != child_payload.get("dispatchId")
                    ):
                        raise RoomKernelFenceError(
                            "review continuation does not match parent wait fences"
                        )
            if post_proposal is not None:
                if (
                    post_proposal.get("roomId") != root["room_id"]
                    or post_proposal.get("rootId") != root["root_id"]
                    or post_proposal.get("dispatchId") != dispatch["dispatch_id"]
                    or int(post_proposal.get("generation", -1)) != int(root["generation"])
                ):
                    raise RoomKernelFenceError("RoomPost does not match the committing Dispatch")
                encoded_post = _json(post_proposal)
                prior_post = conn.execute(
                    "SELECT payload_json FROM room_kernel_posts WHERE room_id = ? AND idempotency_key = ?",
                    (post_proposal["roomId"], post_proposal["idempotencyKey"]),
                ).fetchone()
                if prior_post is not None and str(prior_post["payload_json"]) != encoded_post:
                    raise RoomKernelFenceError("RoomPost idempotency key was rebound")
            conn.execute(
                """INSERT INTO room_kernel_commits(
                   commit_id, root_id, dispatch_id, generation, payload_json, created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (payload["commitId"], root["root_id"], payload["dispatchId"], generation, _json(payload), int(now_ms)),
            )
            conn.execute(
                "UPDATE room_kernel_settle_guards SET state='resolved',updated_at_ms=? WHERE dispatch_id=?",
                (int(now_ms), payload["dispatchId"]),
            )
            conn.execute("UPDATE room_kernel_dispatches SET state = 'committed', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), payload["dispatchId"]))
            conn.execute("UPDATE room_kernel_outbox SET state = 'committed', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), payload["dispatchId"]))
            conn.execute("UPDATE room_kernel_leases SET state = 'completed', updated_at_ms = ? WHERE dispatch_id = ? AND state IN ('active','accepted')", (int(now_ms), payload["dispatchId"]))
            conn.execute(
                """UPDATE room_kernel_runtime_effects
                   SET state='completed',updated_at_ms=?
                   WHERE dispatch_id=? AND state IN ('intent','accepted','unknown')""",
                (int(now_ms), payload["dispatchId"]),
            )
            conn.execute(
                """UPDATE room_kernel_abort_scopes
                   SET state='completed',updated_at_ms=?
                   WHERE dispatch_id=?
                     AND state IN ('registered','cancelling','unknown')""",
                (int(now_ms), payload["dispatchId"]),
            )
            self._settle_dispatch_limits(
                conn, str(payload["dispatchId"]), usage=resource_usage,
                consumed=True, now_ms=now_ms,
            )
            remaining = max(0, int(root["budget_remaining"]) - int(dispatch["budget_cost"]))
            reserved = max(0, int(root["budget_reserved"]) - int(dispatch["budget_cost"]))
            covered = set(json.loads(str(root["covered_criteria_json"])))
            covered.update(str(item) for item in payload["requirementCoverage"])
            conn.execute("UPDATE room_kernel_roots SET budget_remaining = ?, budget_reserved = ?, covered_criteria_json = ?, updated_at_ms = ? WHERE root_id = ?", (remaining, reserved, _json(sorted(covered)), int(now_ms), root["root_id"]))
            next_state = {
                "wait": "waiting",
                "post": "waiting",
                "block": "blocked",
                "complete": "completed",
                "dispatch": "active",
            }[decision]
            task_payload = self.project_task_result_payload(
                task_payload,
                result_kind=decision,
                post_proposal=post_proposal,
                quality_gate_receipt=quality_gate_receipt,
                evidence_refs=payload.get("evidenceRefs") or [],
                now_ms=now_ms,
            )
            ownership_receipt: dict[str, object] | None = None
            if task_transfer_payload is not None:
                ownership_receipt = self._apply_task_transfer(
                    conn,
                    task_payload=task_payload,
                    task_transfer=task_transfer_payload,
                    dispatch=dispatch,
                    root=root,
                    commit_id=str(payload["commitId"]),
                    now_ms=now_ms,
                )
            else:
                task_state = (
                    "waiting"
                    if child_task_payload is not None
                    else next_state
                )
                if task_payload.get("taskKind") == "review":
                    review_findings = [
                        dict(item)
                        for item in payload.get("reviewFindings", ())
                        if isinstance(item, Mapping)
                    ]
                    unresolved_blocking = any(
                        item.get("gateEffect") == "blocking"
                        and item.get("state")
                        in {"open", "contested", "escalated"}
                        for item in review_findings
                    )
                    unresolved_advisory = any(
                        item.get("gateEffect") == "advisory"
                        and item.get("state") == "open"
                        for item in review_findings
                    )
                    has_advisory = any(
                        item.get("gateEffect") == "advisory"
                        for item in review_findings
                    )
                    if decision == "complete":
                        if unresolved_blocking:
                            raise RoomKernelFenceError(
                                "Reviewer cannot accept with an unresolved "
                                "Blocking Finding"
                            )
                        if unresolved_advisory:
                            raise RoomKernelFenceError(
                                "Reviewer cannot accept with an unresolved "
                                "Advisory Finding"
                            )
                        review_state = (
                            "accepted_with_notes"
                            if has_advisory
                            else "accepted"
                        )
                    elif decision == "dispatch":
                        review_state = "changes_requested"
                    elif decision == "block" and any(
                        item.get("state") == "escalated"
                        for item in review_findings
                    ):
                        review_state = "escalated"
                    else:
                        review_state = "in_review"
                    updated_task = {
                        **task_payload,
                        "reviewState": review_state,
                        "reviewFindings": review_findings,
                        "revision": int(task_payload.get("revision") or 0) + 1,
                        "state": task_state,
                    }
                    validate_kernel_contract("roomTask", updated_task)
                    conn.execute(
                        "UPDATE room_kernel_tasks SET state=?,payload_json=?,updated_at_ms=? "
                        "WHERE task_id=?",
                        (
                            task_state,
                            _json(updated_task),
                            int(now_ms),
                            dispatch["task_id"],
                        ),
                    )
                else:
                    updated_task = {
                        **task_payload,
                        "state": task_state,
                    }
                    validate_kernel_contract("roomTask", updated_task)
                    conn.execute(
                        "UPDATE room_kernel_tasks SET state=?,payload_json=?,updated_at_ms=? "
                        "WHERE task_id=?",
                        (
                            task_state,
                            _json(updated_task),
                            int(now_ms),
                            dispatch["task_id"],
                        ),
                    )
            root_state = {
                "wait": "waiting",
                "post": "waiting",
                "block": "blocked",
            }.get(decision, "running")
            conn.execute(
                "UPDATE room_kernel_roots SET state=?,updated_at_ms=? "
                "WHERE root_id=?",
                (root_state, int(now_ms), root["root_id"]),
            )
            child_dispatch = None
            if child_task_payload is not None:
                self._insert_task(
                    conn,
                    child_task_payload,
                    now_ms=now_ms,
                )
            if child_payload is not None:
                child_dispatch, _ = self._enqueue_dispatch(
                    conn,
                    child_payload,
                    shadow_only=self.mode not in {
                        "cohort",
                        "test",
                        "kernel_only",
                    },
                    now_ms=now_ms,
                )
                if str(child_payload.get("intentKind") or "") == "review":
                    updated_root_payload = json.loads(
                        str(root["payload_json"])
                    )
                    updated_root_payload["independentReviewRequired"] = True
                    validate_kernel_contract(
                        "rootExecution",
                        updated_root_payload,
                    )
                    conn.execute(
                        """UPDATE room_kernel_roots
                           SET payload_json=?,updated_at_ms=? WHERE root_id=?""",
                        (
                            _json(updated_root_payload),
                            int(now_ms),
                            root["root_id"],
                        ),
                    )
                    self._record_review_policy_locked(
                        conn,
                        root_id=str(root["root_id"]),
                        required=True,
                        source="facilitator_review_handoff",
                        generation=generation,
                        dispatch_id=str(child_dispatch["dispatchId"]),
                        now_ms=now_ms,
                    )
            continuation_id = _stable_id("room-continuation", str(payload["commitId"]), decision)
            conn.execute(
                """INSERT INTO room_kernel_continuations(
                   continuation_id,root_id,task_id,parent_dispatch_id,child_dispatch_id,
                   commit_id,decision,state,payload_json,created_at_ms)
                   VALUES (?,?,?,?,?,?,?,'applied',?,?)""",
                (
                    continuation_id, root["root_id"], dispatch["task_id"], dispatch["dispatch_id"],
                    child_dispatch["dispatchId"] if child_dispatch is not None else None,
                    payload["commitId"], decision, _json(dict(continuation or {})), int(now_ms),
                ),
            )
            if post_proposal is not None and prior_post is None:
                conn.execute(
                    """INSERT INTO room_kernel_posts(
                       post_id, room_id, root_id, generation, idempotency_key,
                       payload_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        post_proposal["postId"], post_proposal["roomId"],
                        post_proposal["rootId"], post_proposal["generation"],
                        post_proposal["idempotencyKey"], encoded_post,
                        post_proposal["createdAtMs"],
                ),
            )
            resumed_dispatch_ids, blocked_waits = (
                self._resume_ready_participant_waits(
                    conn,
                    root_id=str(root["root_id"]),
                    generation=generation,
                    now_ms=now_ms,
                )
            )
            receipt = self._receipt(
                conn,
                root_id=str(root["root_id"]),
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=generation,
                details={
                    "commitId": payload["commitId"],
                    "settleDecision": decision,
                    "continuationId": continuation_id,
                    "transferredTaskId": (
                        task_transfer_payload["taskId"]
                        if task_transfer_payload is not None
                        else None
                    ),
                    "ownershipReceiptId": (
                        ownership_receipt["receiptId"]
                        if ownership_receipt is not None
                        else None
                    ),
                    "childTaskId": (
                        child_task_payload["taskId"]
                        if child_task_payload is not None
                        else None
                    ),
                    "childDispatchId": (
                        child_dispatch["dispatchId"]
                        if child_dispatch is not None
                        else None
                    ),
                    "resumedDispatchIds": resumed_dispatch_ids,
                    "blockedWaitContinuations": blocked_waits,
                    "qualityGateReceiptId": quality_gate_receipt[
                        "receiptId"
                    ],
                    "qualityGateVerdict": quality_gate_receipt["verdict"],
                    "acceptanceEvidenceAuthority": (
                        acceptance_evidence_authority
                    ),
                },
                now_ms=now_ms,
            )
            if self.commit_work_document_delta is not None:
                self.commit_work_document_delta(
                    conn,
                    {
                        "rootId": str(root["root_id"]),
                        "taskId": str(dispatch["task_id"]),
                        "commitId": str(payload["commitId"]),
                        "decision": decision,
                        "summary": str(
                            payload.get("publicSummary")
                            or payload.get("summary")
                            or ""
                        ),
                        "evidenceRefs": [
                            str(value)
                            for value in payload.get("evidenceRefs") or []
                            if str(value).strip()
                        ],
                        "createdAtMs": int(now_ms),
                    },
                )
            if is_report_dispatch and decision == "complete":
                self._receipt(
                    conn,
                    root_id=str(root["root_id"]),
                    command_id=None,
                    receipt_kind="accepted",
                    status="applied",
                    generation=generation,
                    details={
                        "purpose": "reporter_terminal",
                        "reportTaskId": str(dispatch["task_id"]),
                        "reportDispatchId": str(dispatch["dispatch_id"]),
                        "reportCommitId": str(payload["commitId"]),
                        "finalPostId": str(post_proposal["postId"]),
                        "reporterParticipantId": str(
                            dispatch["target_participant_id"]
                        ),
                    },
                    now_ms=now_ms,
                )
            if invocation is not None:
                execution_payload = {
                    "schemaVersion": "wisdom-weasel.room-tool-execution-receipt.v1",
                    "executionReceiptId": f"execution:{invocation_receipt_id}",
                    "invocationReceiptId": invocation_receipt_id,
                    "kernelReceiptId": receipt["receiptId"],
                    "commitId": payload["commitId"],
                    "sessionId": str(invocation["bound_session_id"]),
                    "toolName": str(json.loads(str(invocation["command_json"]))["tool"]),
                    "status": "applied",
                    "kernelReceipt": receipt,
                    "createdAtMs": int(now_ms),
                }
                conn.execute(
                    """INSERT INTO room_v2_tool_execution_receipts(
                       execution_receipt_id, invocation_receipt_id, kernel_receipt_id,
                       session_id, tool_name, status, result_hash, payload_json, created_at_ms
                       ) VALUES (?, ?, ?, ?, ?, 'applied', ?, ?, ?)""",
                    (
                        execution_payload["executionReceiptId"], invocation_receipt_id,
                        receipt["receiptId"], execution_payload["sessionId"],
                        execution_payload["toolName"],
                        hashlib.sha256(_json(execution_payload).encode("utf-8")).hexdigest(),
                        _json(execution_payload), int(now_ms),
                    ),
                )
            RoomDomainEventRepository.append(
                conn,
                settlement.event,
                created_at_ms=int(now_ms),
            )
            if (
                decision == "wait"
                and isinstance(continuation, Mapping)
                and continuation.get("waitingFor") == "user"
                and str(dispatch["intent_kind"]) in {"align", "resume"}
            ):
                self._record_intake_phase_locked(
                    conn,
                    root_id=str(root["root_id"]),
                    phase="clarifying",
                    clarification_occurred=True,
                    source="facilitator_question",
                    generation=generation,
                    details={
                        "dispatchId": str(dispatch["dispatch_id"]),
                        "continuationId": continuation_id,
                        "commitId": str(payload["commitId"]),
                    },
                    now_ms=now_ms,
                )
            return receipt

    def _resume_ready_participant_waits(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        generation: int,
        now_ms: int,
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Resume exact participant waits once, without model polling."""

        root = self._root_row(conn, root_id)
        if (
            int(root["generation"]) != int(generation)
            or str(root["state"])
            not in {"running", "waiting", "blocked"}
        ):
            return [], []
        rows = conn.execute(
            """SELECT * FROM room_kernel_continuations
               WHERE root_id=? AND decision IN ('wait','dispatch')
                 AND state='applied'
               ORDER BY created_at_ms,continuation_id""",
            (root_id,),
        ).fetchall()
        resumed: list[str] = []
        blocked: list[dict[str, str]] = []
        for continuation in rows:
            try:
                payload = _room_continuation_payload(conn, continuation)
            except (RoomKernelFenceError, TypeError, ValueError) as exc:
                reason = f"participant wait payload is invalid: {exc}"[:500]
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reason": reason,
                    }
                )
                continue
            if payload.get("resumeDispatchId"):
                continue
            if (
                str(continuation["decision"]) == "wait"
                and continuation["child_dispatch_id"] is not None
            ):
                # Compatibility with waits resumed before resumeDispatchId was
                # persisted in the continuation payload.
                continue
            managed_external_dependency = (
                _managed_external_retry_wait_dependency(
                    conn,
                    continuation,
                    payload,
                )
                or _managed_integration_external_wait_dependency(
                    conn,
                    continuation,
                    payload,
                )
            )
            if payload.get("waitingFor") != "participant":
                if managed_external_dependency is None:
                    continue
                payload = {
                    **payload,
                    "waitingFor": "participant",
                    "waitingForParticipantId": managed_external_dependency[
                        "participantId"
                    ],
                    "waitingForDispatchId": managed_external_dependency[
                        "dispatchId"
                    ],
                }
            runtime_authorized = (
                managed_external_dependency is not None
                or _participant_wait_runtime_authorized(
                    conn,
                    continuation,
                    payload,
                )
            )
            historical_recovery_required = (
                _historical_participant_wait_requires_recovery(
                    conn,
                    continuation,
                    payload,
                )
            )
            if not runtime_authorized and not historical_recovery_required:
                # Historical projections without an exact persisted
                # participant/dependency identity remain display-only.
                continue
            dependency_id = str(
                payload.get("waitingForDispatchId") or ""
            ).strip()
            participant_id = str(
                payload.get("waitingForParticipantId") or ""
            ).strip()
            unresolved_identity = any(
                value.startswith("legacy-unresolved-")
                for value in (participant_id, dependency_id)
            )
            if (
                not dependency_id
                or not participant_id
                or unresolved_identity
            ):
                reason = (
                    "historical participant wait identity is unresolved; "
                    "explicit recovery is required"
                )
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reason": reason,
                    }
                )
                continue
            dependency = conn.execute(
                """SELECT * FROM room_kernel_dispatches
                   WHERE dispatch_id=? AND root_id=? AND generation=?""",
                (dependency_id, root_id, int(generation)),
            ).fetchone()
            if dependency is None:
                reason = "participant wait dependency is missing or stale"
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reason": reason,
                    }
                )
                continue
            if str(dependency["target_participant_id"]) != participant_id:
                reason = "participant wait dependency identity does not match"
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reason": reason,
                    }
                )
                continue
            if str(dependency["task_id"]) == str(continuation["task_id"]):
                reason = "participant wait dependency must belong to another Task"
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reason": reason,
                    }
                )
                continue
            dependency_task = conn.execute(
                """SELECT state,payload_json FROM room_kernel_tasks
                   WHERE task_id=? AND root_id=?""",
                (dependency["task_id"], root_id),
            ).fetchone()
            if dependency_task is None:
                reason = "participant wait dependency Task is missing"
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reason": reason,
                    }
                )
                continue
            dependency_dispatch_state = str(dependency["state"])
            dependency_task_state = str(dependency_task["state"])
            dependency_terminal = (
                dependency_dispatch_state in {"failed", "cancelled", "unknown"}
                or (
                    dependency_dispatch_state == "committed"
                    and dependency_task_state
                    in {"blocked", "failed", "cancelled"}
                )
            )
            dependency_completed = (
                dependency_dispatch_state == "committed"
                and dependency_task_state == "completed"
            )
            if not dependency_terminal and not dependency_completed:
                # A public intermediate result (for example, Reviewer findings
                # handed back for revision) does not settle the participant
                # wait. Resume only after that child Task reaches its accepted
                # completion or a durable terminal outcome must be handled.
                continue
            if historical_recovery_required:
                reason_code = (
                    "historical_continuation_recovery_required"
                )
                reason = (
                    "historical v3 participant wait reached its exact "
                    "dependency outcome but lacks executable v4 authority; "
                    "explicit recovery is required"
                )
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    reason_code=reason_code,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reasonCode": reason_code,
                        "reason": reason,
                    }
                )
                continue
            task_row = conn.execute(
                """SELECT state,payload_json FROM room_kernel_tasks
                   WHERE task_id=? AND root_id=?""",
                (continuation["task_id"], root_id),
            ).fetchone()
            if task_row is None or str(task_row["state"]) != "waiting":
                reason = "participant wait task is no longer resumable"
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": str(
                            continuation["continuation_id"]
                        ),
                        "reason": reason,
                    }
                )
                continue
            resumed_task_payload: dict[str, object] | None = None
            task_payload = json.loads(str(task_row["payload_json"]))
            if (
                task_payload.get("taskKind") == "review"
                and not dependency_terminal
            ):
                dependency_commit_row = conn.execute(
                    """SELECT payload_json FROM room_kernel_commits
                       WHERE dispatch_id=?""",
                    (dependency_id,),
                ).fetchone()
                if dependency_commit_row is None:
                    reason = "review revision has no durable Commit"
                    self._block_wait_continuation(
                        conn,
                        continuation,
                        reason=reason,
                        now_ms=now_ms,
                    )
                    blocked.append(
                        {
                            "continuationId": str(
                                continuation["continuation_id"]
                            ),
                            "reason": reason,
                        }
                    )
                    continue
                dependency_commit = _room_commit_payload(
                    conn,
                    dependency_commit_row["payload_json"],
                )
                responses = {
                    str(item.get("findingId") or ""): item
                    for item in dependency_commit.get(
                        "reviewFindingResponses", ()
                    )
                    if isinstance(item, Mapping)
                }
                findings = [
                    {
                        **dict(item),
                        "response": (
                            dict(responses[str(item.get("findingId") or "")])
                            if str(item.get("findingId") or "") in responses
                            else item.get("response")
                        ),
                    }
                    for item in task_payload.get("reviewFindings", ())
                    if isinstance(item, Mapping)
                ]
                review_task_ids = list(
                    dict.fromkeys(
                        [
                            *(
                                str(value)
                                for value in task_payload.get(
                                    "reviewOfTaskIds", ()
                                )
                                if str(value or "").strip()
                            ),
                            str(dependency["task_id"]),
                        ]
                    )
                )
                review_authors = sorted(
                    {
                        *(
                            str(value)
                            for value in task_payload.get(
                                "reviewAuthorParticipantIds", ()
                            )
                            if str(value or "").strip()
                        ),
                        str(dependency["target_participant_id"]),
                    }
                )
                resumed_task_payload = {
                    **task_payload,
                    "reviewOfTaskIds": review_task_ids,
                    "reviewAuthorParticipantIds": review_authors,
                    "reviewTargetRevision": str(
                        task_payload.get("reviewTargetRevision") or ""
                    ),
                    "reviewEvidenceNotBeforeMs": int(now_ms),
                    "reviewRound": int(
                        task_payload.get("reviewRound") or 1
                    )
                    + 1,
                    "reviewFindings": findings,
                    "reviewState": "in_review",
                    "revision": int(task_payload.get("revision") or 0) + 1,
                    "state": "active",
                }
                resumed_task_payload["reviewTargetRevision"] = (
                    self._review_target_revision_locked(
                        conn,
                        root_id=root_id,
                        task_ids=review_task_ids,
                        review_snapshot=resumed_task_payload,
                    )
                )
                validate_kernel_contract("roomTask", resumed_task_payload)
            parent = self._dispatch_row(
                conn,
                str(continuation["parent_dispatch_id"]),
            )
            parent_payload = _dispatch_payload(parent)
            parent_epoch = int(parent_payload["capabilityEpoch"])
            active_same_wave = self._capability_peer_dispatch_ids(
                conn,
                parent,
                states=_ACTIVE_DISPATCH_STATES,
            )
            epoch_rows = conn.execute(
                """SELECT payload_json FROM room_kernel_dispatches
                   WHERE root_id=? AND generation=?""",
                (root_id, int(generation)),
            ).fetchall()
            latest_root_epoch = max(
                (
                    int(
                        json.loads(str(row["payload_json"])).get(
                            "capabilityEpoch",
                            0,
                        )
                    )
                    for row in epoch_rows
                ),
                default=parent_epoch,
            )
            latest_root_epoch = max(parent_epoch, latest_root_epoch)
            capability_epoch = (
                parent_epoch
                if active_same_wave and latest_root_epoch == parent_epoch
                else latest_root_epoch + 1
            )
            continuation_id = str(continuation["continuation_id"])
            resume_dispatch_id = _stable_id(
                "room-dispatch-resume",
                continuation_id,
                dependency_id,
            )
            outcome_state = (
                dependency_dispatch_state
                if dependency_dispatch_state
                in {"failed", "cancelled", "unknown"}
                else dependency_task_state
            )
            conn.execute("SAVEPOINT room_participant_wait_resume")
            try:
                recovery_receipt: dict[str, object] | None = None
                if managed_external_dependency is not None:
                    recovery_receipt = self._receipt(
                        conn,
                        root_id=root_id,
                        command_id=None,
                        receipt_kind="accepted",
                        status="applied",
                        generation=int(generation),
                        details={
                            "purpose": "managed_external_wait_recovered",
                            "continuationId": continuation_id,
                            "dependencyDispatchId": dependency_id,
                            "dependencyParticipantId": participant_id,
                        },
                        now_ms=now_ms,
                    )
                outcome_receipt: dict[str, object] | None = None
                if dependency_terminal:
                    outcome_receipt = self._receipt(
                        conn,
                        root_id=root_id,
                        command_id=None,
                        receipt_kind="accepted",
                        status="applied",
                        generation=int(generation),
                        details={
                            "purpose": "participant_wait_dependency_terminal",
                            "continuationId": continuation_id,
                            "dependencyDispatchId": dependency_id,
                            "dependencyDispatchState": dependency_dispatch_state,
                            "dependencyTaskId": str(dependency["task_id"]),
                            "dependencyTaskState": dependency_task_state,
                        },
                        now_ms=now_ms,
                    )
                resume_dispatch = {
                    "schemaVersion": parent_payload["schemaVersion"],
                    "dispatchId": resume_dispatch_id,
                    "rootId": root_id,
                    "taskId": str(continuation["task_id"]),
                    "parentDispatchId": str(parent["dispatch_id"]),
                    "generation": int(generation),
                    "hopCount": int(parent_payload["hopCount"]) + 1,
                    "depth": int(parent_payload["depth"]),
                    "budgetCost": 1,
                    "targetSessionId": str(parent["target_session_id"]),
                    "targetParticipantId": str(
                        parent["target_participant_id"]
                    ),
                    "triggerId": (
                        str(outcome_receipt["receiptId"])
                        if outcome_receipt is not None
                        else str(recovery_receipt["receiptId"])
                        if recovery_receipt is not None
                        else continuation_id
                    ),
                    "intentKind": "resume",
                    "idempotencyKey": (
                        f"room-resume:{continuation_id}:{dependency_id}"
                    ),
                    "attempt": int(parent_payload.get("attempt") or 0) + 1,
                    "capabilityEpoch": capability_epoch,
                    "runtimeProfileRevision": str(
                        parent_payload["runtimeProfileRevision"]
                    ),
                    "state": "pending",
                }
                child, _ = self._enqueue_dispatch(
                    conn,
                    resume_dispatch,
                    shadow_only=self.mode
                    not in {"cohort", "test", "kernel_only"},
                    now_ms=now_ms,
                )
                materialized_payload = _decode_room_continuation_payload(
                    continuation["payload_json"]
                )
                materialized_payload["resumeDispatchId"] = str(
                    child["dispatchId"]
                )
                if recovery_receipt is not None:
                    materialized_payload["managedWaitRecoveryReceiptId"] = str(
                        recovery_receipt["receiptId"]
                    )
                if outcome_receipt is not None:
                    materialized_payload.update(
                        {
                            "dependencyOutcomeDispatchId": dependency_id,
                            "dependencyOutcomeState": outcome_state,
                            "dependencyOutcomeReceiptId": str(
                                outcome_receipt["receiptId"]
                            ),
                        }
                    )
                if str(continuation["decision"]) == "wait":
                    updated = conn.execute(
                        """UPDATE room_kernel_continuations
                           SET state='resumed',child_dispatch_id=?,payload_json=?
                           WHERE continuation_id=? AND child_dispatch_id IS NULL
                             AND state='applied'""",
                        (
                            child["dispatchId"],
                            _json(materialized_payload),
                            continuation_id,
                        ),
                    )
                else:
                    updated = conn.execute(
                        """UPDATE room_kernel_continuations
                           SET state='resumed',payload_json=?
                           WHERE continuation_id=? AND state='applied'""",
                        (_json(materialized_payload), continuation_id),
                    )
                if updated.rowcount != 1:
                    raise RoomKernelFenceError(
                        "participant wait continuation is no longer resumable"
                    )
                if resumed_task_payload is not None:
                    resumed_task = conn.execute(
                        """UPDATE room_kernel_tasks
                           SET state='active',payload_json=?,updated_at_ms=?
                           WHERE task_id=? AND state='waiting'""",
                        (
                            _json(resumed_task_payload),
                            int(now_ms),
                            continuation["task_id"],
                        ),
                    )
                else:
                    resumed_task = conn.execute(
                        """UPDATE room_kernel_tasks
                           SET state='active',updated_at_ms=?
                           WHERE task_id=? AND state='waiting'""",
                        (int(now_ms), continuation["task_id"]),
                    )
                if resumed_task.rowcount != 1:
                    raise RoomKernelFenceError(
                        "participant wait Task is no longer resumable"
                    )
                conn.execute(
                    """UPDATE room_kernel_roots
                       SET state='running',updated_at_ms=?
                       WHERE root_id=?
                         AND state IN ('running','waiting','blocked')""",
                    (int(now_ms), root_id),
                )
                conn.execute("RELEASE SAVEPOINT room_participant_wait_resume")
            except RoomKernelFenceError as exc:
                conn.execute("ROLLBACK TO SAVEPOINT room_participant_wait_resume")
                conn.execute("RELEASE SAVEPOINT room_participant_wait_resume")
                reason = str(exc)[:500]
                self._block_wait_continuation(
                    conn,
                    continuation,
                    reason=reason,
                    now_ms=now_ms,
                )
                blocked.append(
                    {
                        "continuationId": continuation_id,
                        "reason": reason,
                    }
                )
                continue
            resumed.append(str(child["dispatchId"]))
        return resumed, blocked

    @staticmethod
    def _block_wait_continuation(
        conn: sqlite3.Connection,
        continuation: sqlite3.Row,
        *,
        reason: str,
        reason_code: str = "wait_resume_blocked",
        now_ms: int,
    ) -> None:
        conn.execute(
            """UPDATE room_kernel_continuations
               SET state='blocked' WHERE continuation_id=?""",
            (continuation["continuation_id"],),
        )
        conn.execute(
            """UPDATE room_kernel_tasks
               SET state='blocked',updated_at_ms=? WHERE task_id=?""",
            (int(now_ms), continuation["task_id"]),
        )
        conn.execute(
            """UPDATE room_kernel_roots
               SET state='blocked',updated_at_ms=?
               WHERE root_id=? AND state IN ('running','waiting','blocked')""",
            (int(now_ms), continuation["root_id"]),
        )
        normalized_reason_code = _required(
            reason_code,
            "wait continuation reason_code",
        )
        conn.execute(
            """INSERT OR IGNORE INTO room_kernel_dead_letters(
               dead_letter_id,root_id,dispatch_id,reason_code,
               payload_json,created_at_ms)
               VALUES (?,?,?,?,?,?)""",
            (
                _stable_id(
                    "room-dead-letter",
                    str(continuation["parent_dispatch_id"]),
                    normalized_reason_code,
                ),
                continuation["root_id"],
                continuation["parent_dispatch_id"],
                normalized_reason_code,
                _json(
                    {
                        "continuationId": continuation["continuation_id"],
                        "reasonCode": normalized_reason_code,
                        "reason": reason,
                    }
                ),
                int(now_ms),
            ),
        )

    def cancel_target(
        self, *, root_id: str, target_kind: Literal["task", "dispatch"], target_id: str, now_ms: int
    ) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            return self._cancel_target(conn, root_id=root_id, target_kind=target_kind, target_id=target_id, command_id=None, now_ms=now_ms)

    def cancel_root(self, root_id: str, *, now_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            return self._cancel_root(conn, root_id, command_id=None, now_ms=now_ms, receipt_kind="root_cancelled")

    def panic(self, room_id: str, *, now_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            return self._panic(conn, room_id=room_id, command_id=None, now_ms=now_ms)

    def apply_control_command(self, command: Mapping[str, object]) -> dict[str, object]:
        """Apply typed operator controls through the single Kernel command path."""

        validate_kernel_contract("kernelCommand", command)
        kind = str(command["commandKind"])
        if kind not in {"cancel_target", "cancel_root", "retry_root", "panic"}:
            raise ValueError(
                "control command must be cancel_target, cancel_root, retry_root, or panic"
            )
        if self.mode == "off":
            raise RoomKernelFenceError("Room Kernel feature flag is off")
        with self._connect(immediate=True) as conn:
            existing_by_key = conn.execute(
                """SELECT * FROM room_kernel_commands
                   WHERE room_id = ? AND idempotency_key = ?""",
                (command["roomId"], command["idempotencyKey"]),
            ).fetchone()
            existing_by_id = conn.execute(
                "SELECT * FROM room_kernel_commands WHERE command_id = ?",
                (command["commandId"],),
            ).fetchone()
            if existing_by_key is not None or existing_by_id is not None:
                if (
                    existing_by_key is None
                    or existing_by_id is None
                    or str(existing_by_key["command_id"])
                    != str(existing_by_id["command_id"])
                    or json.loads(str(existing_by_key["payload_json"]))
                    != dict(command)
                ):
                    raise RoomKernelFenceError(
                        "control command idempotency identity was rebound"
                    )
                if kind == "panic":
                    receipt = conn.execute(
                        """SELECT payload_json FROM room_kernel_receipts
                           WHERE command_id = ? AND root_id IS NULL
                             AND receipt_kind = 'panic'
                           ORDER BY created_at_ms, receipt_id LIMIT 1""",
                        (existing_by_key["command_id"],),
                    ).fetchone()
                else:
                    receipt = conn.execute(
                        """SELECT payload_json FROM room_kernel_receipts
                           WHERE command_id = ? AND root_id = ?
                           ORDER BY created_at_ms, receipt_id LIMIT 1""",
                        (
                            existing_by_key["command_id"],
                            command.get("rootId"),
                        ),
                    ).fetchone()
                if receipt is not None:
                    return json.loads(str(receipt["payload_json"]))
                raise RoomKernelFenceError("duplicate command is missing its authoritative receipt")
            if kind != "panic":
                root_id = _required(command.get("rootId"), "rootId")
                root = self._root_row(conn, root_id)
                if str(root["room_id"]) != str(command["roomId"]):
                    raise RoomKernelFenceError("control command Room does not match Root")
                if int(command["generation"]) != int(root["generation"]):
                    raise RoomKernelFenceError("control command generation is stale")
                if kind in {"cancel_root", "retry_root"} and (
                    command.get("targetKind") != "root" or command.get("targetId") != root_id
                ):
                    raise RoomKernelFenceError(f"{kind} target does not match Root")
                if kind == "cancel_target" and command.get("targetKind") not in {"task", "dispatch"}:
                    raise RoomKernelFenceError("cancel_target requires a task or dispatch target")
            conn.execute(
                """INSERT INTO room_kernel_commands(
                   command_id, root_id, room_id, idempotency_key, command_kind,
                   payload_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (command["commandId"], command.get("rootId"), command["roomId"], command["idempotencyKey"], kind, _json(command), int(command["createdAtMs"])),
            )
            if kind == "panic":
                return self._panic(conn, room_id=str(command["roomId"]), command_id=str(command["commandId"]), now_ms=int(command["createdAtMs"]))
            root_id = _required(command.get("rootId"), "rootId")
            if kind == "cancel_root":
                return self._cancel_root(conn, root_id, command_id=str(command["commandId"]), now_ms=int(command["createdAtMs"]), receipt_kind="root_cancelled")
            if kind == "retry_root":
                return self._retry_blocked_root(
                    conn,
                    root_id=root_id,
                    command_id=str(command["commandId"]),
                    now_ms=int(command["createdAtMs"]),
                    allow_manual_budget_extension=(
                        str(command.get("sourceKind") or "") == "control_center"
                    ),
                )
            return self._cancel_target(conn, root_id=root_id, target_kind=str(command["targetKind"]), target_id=_required(command.get("targetId"), "targetId"), command_id=str(command["commandId"]), now_ms=int(command["createdAtMs"]))

    def _retry_blocked_root(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        command_id: str,
        now_ms: int,
        allow_manual_budget_extension: bool = False,
    ) -> dict[str, object]:
        root = self._root_row(conn, root_id)
        if str(root["state"]) != "blocked":
            raise RoomKernelFenceError("only a blocked Root can be continued")
        rows = conn.execute(
            """SELECT dispatch.*
               FROM room_kernel_dispatches dispatch
               JOIN room_kernel_tasks task ON task.task_id=dispatch.task_id
               WHERE dispatch.root_id=? AND dispatch.state='failed'
                 AND task.state='blocked'
               ORDER BY dispatch.updated_at_ms DESC,dispatch.created_at_ms DESC""",
            (root_id,),
        ).fetchall()
        selected: list[sqlite3.Row] = []
        task_ids: set[str] = set()
        for row in rows:
            task_id = str(row["task_id"])
            if task_id in task_ids:
                continue
            task_ids.add(task_id)
            selected.append(row)
        if not selected:
            raise RoomKernelFenceError(
                "blocked Root has no failed Dispatch that can be continued"
            )
        active_epoch_rows = conn.execute(
            f"""SELECT payload_json FROM room_kernel_dispatches
                WHERE root_id=?
                  AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})""",
            (root_id, *_ACTIVE_DISPATCH_STATES),
        ).fetchall()
        active_capability_epochs = {
            int(json.loads(str(row["payload_json"])).get("capabilityEpoch") or 0)
            for row in active_epoch_rows
        }
        if len(active_capability_epochs) > 1:
            raise RoomKernelFenceError(
                "active parallel Dispatches disagree on capability epoch"
            )
        retry_capability_epoch = (
            next(iter(active_capability_epochs))
            if active_capability_epochs
            else max(
                int(
                    json.loads(str(row["payload_json"])).get(
                        "capabilityEpoch"
                    )
                    or 0
                )
                for row in selected
            )
            + 1
        )
        limits = conn.execute(
            """SELECT retry_limit,retry_used,deadline_at_ms
               FROM room_kernel_root_limits WHERE root_id=?""",
            (root_id,),
        ).fetchone()
        if limits is None:
            raise RoomKernelFenceError("Root resource limits are missing")
        if int(now_ms) >= int(limits["deadline_at_ms"]):
            raise RoomKernelFenceError("Root wall-clock deadline exceeded")
        retry_used_before = int(limits["retry_used"])
        retry_limit_before = int(limits["retry_limit"])
        retry_limit_after = retry_limit_before
        manual_budget_extension = 0
        required_retry_total = retry_used_before + len(selected)
        if required_retry_total > retry_limit_before:
            if not allow_manual_budget_extension:
                raise RoomKernelFenceError("Root retry limit exhausted")
            manual_budget_extension = required_retry_total - retry_limit_before
            retry_limit_after = retry_limit_before + manual_budget_extension
            conn.execute(
                """UPDATE room_kernel_root_limits
                   SET retry_limit=?,updated_at_ms=? WHERE root_id=?""",
                (retry_limit_after, int(now_ms), root_id),
            )

        conn.execute(
            "UPDATE room_kernel_roots SET state='running',updated_at_ms=? WHERE root_id=?",
            (int(now_ms), root_id),
        )
        retried_dispatch_ids: list[str] = []
        retry_lineage: list[dict[str, object]] = []
        for retry_index, failed in enumerate(selected, start=1):
            task_id = str(failed["task_id"])
            conn.execute(
                "UPDATE room_kernel_tasks SET state='active',updated_at_ms=? WHERE task_id=?",
                (int(now_ms), task_id),
            )
            payload = json.loads(str(failed["payload_json"]))
            failed_attempt = int(payload.get("attempt") or 0)
            retried_attempt = failed_attempt + 1
            dispatch_id = _stable_id(
                "room-dispatch-retry",
                command_id,
                str(failed["dispatch_id"]),
            )
            payload.update(
                {
                    "dispatchId": dispatch_id,
                    "idempotencyKey": _stable_id(
                        "room-dispatch-retry-key",
                        command_id,
                        str(failed["dispatch_id"]),
                    ),
                    "triggerId": command_id,
                    "attempt": retried_attempt,
                    # A partial retry remains in the active parallel wave.
                    # Only a quiescent Root advances the shared capability
                    # epoch; Dispatch identity and revoked Session bindings
                    # still fence the failed attempt.
                    "capabilityEpoch": retry_capability_epoch,
                }
            )
            validate_kernel_contract("dispatchEnvelope", payload)
            self._enqueue_dispatch(
                conn,
                payload,
                shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
                now_ms=now_ms,
            )
            retried_dispatch_ids.append(dispatch_id)
            retry_lineage.append(
                {
                    "failedDispatchId": str(failed["dispatch_id"]),
                    "failedDispatchAttempt": failed_attempt,
                    "retriedDispatchId": dispatch_id,
                    "retriedDispatchAttempt": retried_attempt,
                    "taskId": task_id,
                    "rootGeneration": int(root["generation"]),
                    "rootRetryOrdinal": retry_used_before + retry_index,
                }
            )
        conn.execute(
            """UPDATE room_kernel_root_limits
               SET retry_used=retry_used+?,updated_at_ms=? WHERE root_id=?""",
            (len(retried_dispatch_ids), int(now_ms), root_id),
        )
        details: dict[str, object] = {
            "retriedDispatchIds": retried_dispatch_ids,
            "retriedTaskIds": sorted(task_ids),
            "retryLineage": retry_lineage,
        }
        if manual_budget_extension:
            details.update(
                {
                    "manualRetryBudgetExtension": manual_budget_extension,
                    "retryLimitBefore": retry_limit_before,
                    "retryLimitAfter": retry_limit_after,
                }
            )
        return self._receipt(
            conn,
            root_id=root_id,
            command_id=command_id,
            receipt_kind="root_retried",
            status="applied",
            generation=int(root["generation"]),
            details=details,
            now_ms=now_ms,
        )

    def _cancel_target(self, conn: sqlite3.Connection, *, root_id: str, target_kind: str, target_id: str, command_id: str | None, now_ms: int) -> dict[str, object]:
        if target_kind not in {"task", "dispatch"}:
            raise ValueError("target_kind must be task or dispatch")
        root = self._root_row(conn, root_id)
        if target_kind == "dispatch":
            predicate, value = "dispatch_id = ?", target_id
        else:
            predicate, value = "task_id = ?", target_id
            conn.execute("UPDATE room_kernel_tasks SET state = 'cancelled', updated_at_ms = ? WHERE root_id = ? AND task_id = ? AND state NOT IN ('completed','failed','cancelled')", (int(now_ms), root_id, target_id))
        ids = [str(row[0]) for row in conn.execute(f"SELECT dispatch_id FROM room_kernel_dispatches WHERE root_id = ? AND {predicate}", (root_id, value))]
        count = self._cancel_dispatch_ids(conn, ids, now_ms=now_ms)
        targets = conn.execute(
            f"""SELECT dispatch_id,session_id FROM room_kernel_runtime_effects
                WHERE root_id=? AND dispatch_id IN ({','.join('?' for _ in ids)})
                  AND state IN ('intent','accepted','unknown')""",
            (root_id, *ids),
        ).fetchall() if ids else []
        for target in targets:
            self._enqueue_cancel(
                conn,
                root_id=root_id,
                dispatch_id=str(target["dispatch_id"]),
                session_id=str(target["session_id"]),
                generation=int(root["generation"]),
                terminalize_root=False,
                now_ms=now_ms,
            )
        runtime_ids = {str(target["dispatch_id"]) for target in targets}
        for dispatch_id in set(ids) - runtime_ids:
            conn.execute(
                "UPDATE room_kernel_abort_scopes SET state='cancelled',updated_at_ms=? WHERE dispatch_id=? AND state IN ('registered','cancelling','unknown')",
                (int(now_ms), dispatch_id),
            )
            self._settle_dispatch_limits(
                conn, dispatch_id, usage=None, consumed=False, now_ms=now_ms
            )
        return self._receipt(conn, root_id=root_id, command_id=command_id, receipt_kind="target_cancelled", status="applied" if count else "noop", generation=int(root["generation"]), details={"targetKind": target_kind, "targetId": target_id, "cancelledDispatches": count, "cancelIntents": len(targets)}, now_ms=now_ms)

    def _panic(self, conn: sqlite3.Connection, *, room_id: str, command_id: str | None, now_ms: int) -> dict[str, object]:
        roots = [str(row[0]) for row in conn.execute("SELECT root_id FROM room_kernel_roots WHERE room_id = ? AND state NOT IN ('completed','cancelled','failed') ORDER BY root_id", (room_id,))]
        cancelled = 0
        unknown = 0
        root_receipt_ids: list[str] = []
        for root_id in roots:
            receipt = self._cancel_root(conn, root_id, command_id=None, now_ms=now_ms, receipt_kind="panic")
            root_receipt_ids.append(str(receipt["receiptId"]))
            cancelled += int(receipt["details"]["cancelledDispatches"])
            unknown += int(receipt["details"]["unknownDispatches"])
        return self._receipt(conn, root_id=None, command_id=command_id, receipt_kind="panic", status="applied" if roots else "noop", generation=0, details={"roomId": room_id, "rootCount": len(roots), "rootReceiptIds": root_receipt_ids, "cancelledDispatches": cancelled, "unknownDispatches": unknown}, now_ms=now_ms)

    def _cancel_root(self, conn: sqlite3.Connection, root_id: str, *, command_id: str | None, now_ms: int, receipt_kind: str) -> dict[str, object]:
        root = self._root_row(conn, root_id)
        root_state = str(root["state"])
        if root_state in {"cancelling", "cancelled_with_unknowns"}:
            pending = int(conn.execute(
                "SELECT COUNT(*) FROM room_kernel_cancel_outbox WHERE root_id=? AND terminalize_root=1 AND state!='applied'",
                (root_id,),
            ).fetchone()[0])
            return self._receipt(
                conn, root_id=root_id, command_id=command_id, receipt_kind=receipt_kind,
                status="noop", generation=int(root["generation"]),
                details={"reason": "already_cancelling", "cancelledDispatches": 0, "unknownDispatches": int(root_state == "cancelled_with_unknowns"), "cancelIntents": pending}, now_ms=now_ms,
            )
        if root_state in {"cancelled", "completed", "failed"}:
            return self._receipt(
                conn, root_id=root_id, command_id=command_id, receipt_kind=receipt_kind,
                status="noop", generation=int(root["generation"]),
                details={"reason": f"already_{root_state}", "cancelledDispatches": 0, "unknownDispatches": 0, "cancelIntents": 0}, now_ms=now_ms,
            )
        generation = int(root["generation"]) + 1
        unknown = int(conn.execute("SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id = ? AND state = 'unknown'", (root_id,)).fetchone()[0])
        ids = [str(row[0]) for row in conn.execute(f"SELECT dispatch_id FROM room_kernel_dispatches WHERE root_id = ? AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})", (root_id, *_ACTIVE_DISPATCH_STATES))]
        cancelled = self._cancel_dispatch_ids(conn, ids, now_ms=now_ms)
        targets = conn.execute("""SELECT e.dispatch_id,e.session_id FROM room_kernel_runtime_effects e
            WHERE e.root_id=? AND e.state IN ('intent','accepted','unknown')""", (root_id,)).fetchall()
        for target in targets:
            self._enqueue_cancel(conn, root_id=root_id, dispatch_id=str(target["dispatch_id"]), session_id=str(target["session_id"]), generation=generation, terminalize_root=True, now_ms=now_ms)
        runtime_ids = {str(target["dispatch_id"]) for target in targets}
        for dispatch_id in set(ids) - runtime_ids:
            conn.execute(
                "UPDATE room_kernel_abort_scopes SET state='cancelled',updated_at_ms=? WHERE dispatch_id=? AND state IN ('registered','cancelling','unknown')",
                (int(now_ms), dispatch_id),
            )
            self._settle_dispatch_limits(
                conn, dispatch_id, usage=None, consumed=False, now_ms=now_ms
            )
        conn.execute("UPDATE room_kernel_tasks SET state='cancelled',updated_at_ms=? WHERE root_id=? AND state NOT IN ('completed','failed','cancelled')", (int(now_ms), root_id))
        state = "cancelling" if targets else "cancelled"
        conn.execute("UPDATE room_kernel_roots SET generation = ?, state = ?, updated_at_ms = ? WHERE root_id = ?", (generation, state, int(now_ms), root_id))
        terminal = self._terminal_cancel(conn, root_id, now_ms=now_ms) if not targets else None
        return self._receipt(conn, root_id=root_id, command_id=command_id, receipt_kind=receipt_kind, status="applied", generation=generation, details={"cancelledDispatches": cancelled, "unknownDispatches": unknown, "cancelIntents": len(targets), "terminalReceiptId": terminal["receiptId"] if terminal else None}, now_ms=now_ms)

    def _cancel_dispatch_ids(self, conn: sqlite3.Connection, ids: list[str], *, now_ms: int) -> int:
        released_by_root: dict[str, int] = {}
        for dispatch_id in ids:
            row = self._dispatch_row(conn, dispatch_id)
            if str(row["state"]) in _ACTIVE_DISPATCH_STATES:
                root_id = str(row["root_id"])
                released_by_root[root_id] = released_by_root.get(root_id, 0) + int(row["budget_cost"])
            conn.execute("UPDATE room_kernel_dispatches SET state = 'cancelled', updated_at_ms = ? WHERE dispatch_id = ? AND state IN ('pending','leased','running','retry_wait','timer_wait')", (int(now_ms), dispatch_id))
            conn.execute("UPDATE room_kernel_outbox SET state = 'cancelled', updated_at_ms = ? WHERE dispatch_id = ? AND state NOT IN ('committed','dead_letter')", (int(now_ms), dispatch_id))
            conn.execute("UPDATE room_kernel_leases SET state = 'cancelled', updated_at_ms = ? WHERE dispatch_id = ? AND state IN ('active','accepted')", (int(now_ms), dispatch_id))
        for root_id, released in released_by_root.items():
            conn.execute(
                """UPDATE room_kernel_roots
                   SET budget_reserved = MAX(0, budget_reserved - ?), updated_at_ms = ?
                   WHERE root_id = ?""",
                (released, int(now_ms), root_id),
            )
        return len(ids)

    def _acceptance_evidence_authority_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root: sqlite3.Row,
        task_payload: Mapping[str, object],
        dispatch: sqlite3.Row,
        quality_gate_receipt: Mapping[str, object],
        commit_payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Seal the exact Task/attempt/revision that admitted evidence."""

        definition = self.definition_fence(
            root_id=str(root["root_id"]),
            conn=conn,
        ) or {}
        dispatch_payload = _dispatch_payload(dispatch)
        criteria = [
            {
                "criterionId": str(item.get("criterionId") or ""),
                "status": str(item.get("status") or ""),
                "evidenceRefs": sorted(
                    {
                        str(value).strip()
                        for value in item.get("evidenceRefs") or ()
                        if str(value or "").strip()
                    }
                ),
            }
            for item in quality_gate_receipt.get("items") or ()
            if isinstance(item, Mapping)
        ]
        root_payload = json.loads(str(root["payload_json"]))
        workspace_delivery = task_payload.get("workspaceDelivery")
        if not isinstance(workspace_delivery, Mapping):
            workspace_delivery = {}
        canonical_commit_content_hash = "sha256:" + hashlib.sha256(
            _json(dict(commit_payload)).encode("utf-8")
        ).hexdigest()
        material: dict[str, object] = {
            "schemaVersion": (
                "wisdom-weasel.acceptance-evidence-authority.v1"
            ),
            "rootId": str(root["root_id"]),
            "taskId": str(task_payload.get("taskId") or ""),
            "taskRevision": int(task_payload.get("revision") or 0),
            "dispatchId": str(dispatch["dispatch_id"]),
            "dispatchAttempt": int(dispatch_payload.get("attempt") or 0),
            "generation": int(dispatch["generation"]),
            "requirementCatalogRevisionId": (
                str(definition.get("catalogRevisionId") or "") or None
            ),
            "requirementAnchorRef": (
                str(root_payload.get("requirementAnchorRef") or "") or None
                if isinstance(root_payload, Mapping)
                else None
            ),
            "workspacePolicy": task_payload.get("workspacePolicy"),
            "workspaceBindingId": task_payload.get("workspaceBindingId"),
            "workspaceDeliveryRevision": task_payload.get(
                "workspaceDeliveryRevision"
            ),
            "workspaceDeliveryHead": task_payload.get(
                "workspaceDeliveryHead"
            ),
            "workspaceDeliverySnapshotSha256": task_payload.get(
                "workspaceDeliverySnapshotSha256"
            ),
            "workspaceIntegratedRevision": task_payload.get(
                "workspaceIntegratedRevision"
            ),
            "workspaceIntegratedSnapshotSha256": task_payload.get(
                "workspaceIntegratedSnapshotSha256"
            ),
            "workspaceIntegrationPatchSha256": task_payload.get(
                "workspaceIntegrationPatchSha256"
            ),
            "workspaceIntegrationRef": task_payload.get(
                "workspaceIntegrationRef"
            ),
            "workspaceSnapshotSha256": task_payload.get(
                "workspaceSnapshotSha256"
            ),
            "qualityGateReceiptId": str(
                quality_gate_receipt.get("receiptId") or ""
            ),
            "taskAcceptanceCriterionIds": sorted(
                _criteria(task_payload.get("acceptanceCriterionIds"))
            ),
            "criteria": criteria,
            "evidenceRefs": [
                str(value)
                for value in commit_payload.get("evidenceRefs") or ()
                if str(value or "").strip()
            ],
            "requirementCoverage": [
                str(value)
                for value in commit_payload.get("requirementCoverage") or ()
                if str(value or "").strip()
            ],
            "workspaceDeliveryManifestSha256": (
                workspace_delivery.get("manifestSha256")
            ),
            "workspaceDeliveryPatchSha256": (
                workspace_delivery.get("patchSha256")
            ),
            "commitId": str(commit_payload.get("commitId") or ""),
            "commitDeclaredContentHash": str(
                commit_payload.get("contentHash") or ""
            ),
            "commitCanonicalContentHash": (
                canonical_commit_content_hash
            ),
        }
        encoded = json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            **material,
            "bindingId": "acceptance-evidence-authority:"
            + hashlib.sha256(encoded).hexdigest(),
        }

    @staticmethod
    def _kernel_receipt_row_is_canonical_locked(
        row: sqlite3.Row,
        payload: Mapping[str, object],
    ) -> bool:
        """Verify that mutable receipt JSON still matches its hashed row key."""

        try:
            validate_kernel_contract("kernelReceipt", payload)
        except (TypeError, ValueError):
            return False
        details = payload.get("details")
        if not isinstance(details, Mapping):
            return False
        expected_receipt_id = _stable_id(
            "room-receipt",
            str(payload.get("rootId") or "global"),
            str(payload.get("receiptKind") or ""),
            str(payload.get("status") or ""),
            _json(dict(details)),
            str(payload.get("createdAtMs")),
        )
        return bool(
            str(row["receipt_id"]) == expected_receipt_id
            and str(payload.get("receiptId") or "") == expected_receipt_id
            and (payload.get("rootId") or None) == (row["root_id"] or None)
            and (payload.get("commandId") or None)
            == (row["command_id"] or None)
            and str(payload.get("receiptKind") or "")
            == str(row["receipt_kind"])
            and str(payload.get("status") or "") == str(row["status"])
            and int(payload.get("generation") or 0)
            == int(row["generation"])
            and int(payload.get("createdAtMs") or 0)
            == int(row["created_at_ms"])
        )

    @classmethod
    def _canonical_definition_catalog_revision_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> tuple[bool, str | None]:
        rows = conn.execute(
            """SELECT * FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='accepted'
               ORDER BY created_at_ms,receipt_id""",
            (root_id,),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            details = payload.get("details")
            if not isinstance(details, Mapping):
                continue
            if details.get("operation") != "room_define":
                continue
            if not cls._kernel_receipt_row_is_canonical_locked(row, payload):
                return False, None
            return True, str(details.get("catalogRevisionId") or "") or None
        return True, None

    @classmethod
    def _canonical_acceptance_authority_receipt_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        commit_id: str,
    ) -> tuple[sqlite3.Row, Mapping[str, object], Mapping[str, object]] | None:
        """Return the one canonical receipt that admitted one Commit."""

        receipt_rows = conn.execute(
            """SELECT * FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='accepted'
               ORDER BY created_at_ms,receipt_id""",
            (root_id,),
        ).fetchall()
        candidates: list[
            tuple[sqlite3.Row, Mapping[str, object], Mapping[str, object]]
        ] = []
        for row in receipt_rows:
            try:
                receipt = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(receipt, Mapping):
                continue
            details = receipt.get("details")
            if not isinstance(details, Mapping):
                continue
            authority = details.get("acceptanceEvidenceAuthority")
            authority_commit_id = (
                str(authority.get("commitId") or "")
                if isinstance(authority, Mapping)
                else ""
            )
            if (
                str(details.get("commitId") or "") == commit_id
                or authority_commit_id == commit_id
            ) and isinstance(authority, Mapping):
                candidates.append((row, receipt, authority))
        if len(candidates) != 1:
            return None
        row, receipt, authority = candidates[0]
        if not cls._kernel_receipt_row_is_canonical_locked(row, receipt):
            return None
        return row, receipt, authority

    @classmethod
    def _acceptance_commit_authority_valid_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_payload: Mapping[str, object],
        dispatch: sqlite3.Row,
        commit_id: str,
        raw_commit: Mapping[str, object],
        require_integration: bool | None = True,
    ) -> bool:
        """Consume one exact authority receipt before projecting evidence."""

        candidate = cls._canonical_acceptance_authority_receipt_locked(
            conn,
            root_id=root_id,
            commit_id=commit_id,
        )
        if candidate is None:
            return False
        receipt_row, receipt, authority = candidate
        details = receipt.get("details")
        if not isinstance(details, Mapping):
            return False
        binding_id = str(authority.get("bindingId") or "")
        material = {
            key: value
            for key, value in authority.items()
            if key != "bindingId"
        }
        expected_binding_id = "acceptance-evidence-authority:" + hashlib.sha256(
            _json(material).encode("utf-8")
        ).hexdigest()
        if binding_id != expected_binding_id:
            return False
        required_keys = {
            "schemaVersion",
            "rootId",
            "taskId",
            "taskRevision",
            "dispatchId",
            "dispatchAttempt",
            "generation",
            "requirementCatalogRevisionId",
            "requirementAnchorRef",
            "workspacePolicy",
            "workspaceBindingId",
            "workspaceDeliveryRevision",
            "workspaceDeliveryHead",
            "workspaceDeliverySnapshotSha256",
            "workspaceIntegratedRevision",
            "workspaceIntegratedSnapshotSha256",
            "workspaceIntegrationPatchSha256",
            "workspaceIntegrationRef",
            "workspaceSnapshotSha256",
            "qualityGateReceiptId",
            "taskAcceptanceCriterionIds",
            "criteria",
            "evidenceRefs",
            "requirementCoverage",
            "workspaceDeliveryManifestSha256",
            "workspaceDeliveryPatchSha256",
            "commitId",
            "commitDeclaredContentHash",
            "commitCanonicalContentHash",
            "bindingId",
        }
        if set(authority) != required_keys:
            return False
        dispatch_payload = _dispatch_payload(dispatch)
        gate = raw_commit.get("qualityGateReceipt")
        if not isinstance(gate, Mapping):
            return False
        gate_criteria = [
            {
                "criterionId": str(item.get("criterionId") or ""),
                "status": str(item.get("status") or ""),
                "evidenceRefs": sorted(
                    {
                        str(value).strip()
                        for value in item.get("evidenceRefs") or ()
                        if str(value or "").strip()
                    }
                ),
            }
            for item in gate.get("items") or ()
            if isinstance(item, Mapping)
        ]
        definition_valid, catalog_revision_id = (
            cls._canonical_definition_catalog_revision_locked(
                conn,
                root_id=root_id,
            )
        )
        if not definition_valid:
            return False
        root_row = cls._root_row(conn, root_id)
        try:
            root_payload = json.loads(str(root_row["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(root_payload, Mapping):
            return False
        canonical_commit_content_hash = "sha256:" + hashlib.sha256(
            _json(dict(raw_commit)).encode("utf-8")
        ).hexdigest()
        immutable_expected = {
            "schemaVersion": "wisdom-weasel.acceptance-evidence-authority.v1",
            "rootId": root_id,
            "taskId": str(dispatch["task_id"]),
            "dispatchId": str(dispatch["dispatch_id"]),
            "dispatchAttempt": int(dispatch_payload.get("attempt") or 0),
            "generation": int(dispatch["generation"]),
            "requirementCatalogRevisionId": catalog_revision_id,
            "requirementAnchorRef": (
                str(root_payload.get("requirementAnchorRef") or "") or None
            ),
            "qualityGateReceiptId": str(gate.get("receiptId") or ""),
            "taskAcceptanceCriterionIds": sorted(
                {
                    str(item.get("criterionId") or "").strip()
                    for item in gate.get("items") or ()
                    if isinstance(item, Mapping)
                    and str(item.get("criterionId") or "").strip()
                }
            ),
            "criteria": gate_criteria,
            "evidenceRefs": [
                str(value)
                for value in raw_commit.get("evidenceRefs") or ()
                if str(value or "").strip()
            ],
            "requirementCoverage": [
                str(value)
                for value in raw_commit.get("requirementCoverage") or ()
                if str(value or "").strip()
            ],
            "commitId": commit_id,
            "commitDeclaredContentHash": str(
                raw_commit.get("contentHash") or ""
            ),
            "commitCanonicalContentHash": canonical_commit_content_hash,
        }
        if any(
            authority.get(key) != value
            for key, value in immutable_expected.items()
        ):
            return False
        if (
            str(raw_commit.get("commitId") or "") != commit_id
            or str(raw_commit.get("dispatchId") or "")
            != str(dispatch["dispatch_id"])
            or str(details.get("commitId") or "") != commit_id
            or str(details.get("qualityGateReceiptId") or "")
            != str(gate.get("receiptId") or "")
        ):
            return False
        try:
            authority_revision = int(authority.get("taskRevision"))
            current_revision = int(task_payload.get("revision") or 0)
        except (TypeError, ValueError):
            return False
        task_kind = str(task_payload.get("taskKind") or "work")
        if not (
            authority_revision >= 0
            and authority_revision <= current_revision
        ):
            return False
        if task_payload.get("workspacePolicy") != "isolated_writable":
            maximum_revision_delta = 1 if task_kind == "review" else 0
            if current_revision - authority_revision > maximum_revision_delta:
                return False
        workspace_delivery = task_payload.get("workspaceDelivery")
        if not isinstance(workspace_delivery, Mapping):
            workspace_delivery = {}
        stable_workspace_fields = {
            "workspacePolicy": task_payload.get("workspacePolicy"),
            "workspaceBindingId": task_payload.get("workspaceBindingId"),
            "workspaceDeliveryRevision": task_payload.get(
                "workspaceDeliveryRevision"
            ),
            "workspaceDeliveryHead": task_payload.get(
                "workspaceDeliveryHead"
            ),
            "workspaceDeliverySnapshotSha256": task_payload.get(
                "workspaceDeliverySnapshotSha256"
            ),
            "workspaceSnapshotSha256": task_payload.get(
                "workspaceSnapshotSha256"
            ),
            "workspaceDeliveryManifestSha256": workspace_delivery.get(
                "manifestSha256"
            ),
            "workspaceDeliveryPatchSha256": workspace_delivery.get(
                "patchSha256"
            ),
        }
        if any(
            authority.get(key) != value
            for key, value in stable_workspace_fields.items()
        ):
            return False
        integration_fields = (
            "workspaceIntegratedRevision",
            "workspaceIntegratedSnapshotSha256",
            "workspaceIntegrationPatchSha256",
            "workspaceIntegrationRef",
        )
        if task_payload.get("workspacePolicy") != "isolated_writable":
            return all(
                authority.get(key) == task_payload.get(key)
                for key in integration_fields
            )
        # A Worker Commit is accepted before the Facilitator integrates it.
        # Those four nulls describe that exact pre-integration state; they are
        # never wildcard authority for a later mutable Task projection.
        if any(authority.get(key) is not None for key in integration_fields):
            return False
        if require_integration is None:
            return True
        if not require_integration:
            return bool(
                task_payload.get("workspaceIntegrationState") == "pending"
                and all(
                    task_payload.get(key) is None
                    for key in integration_fields
                    if key != "workspaceIntegrationRef"
                )
            )
        return cls._workspace_integration_authority_valid_locked(
            conn,
            root_id=root_id,
            task_payload=task_payload,
            dispatch=dispatch,
            commit_id=commit_id,
            raw_commit=raw_commit,
            acceptance_receipt_row=receipt_row,
            acceptance_receipt=receipt,
            acceptance_authority=authority,
        )

    @staticmethod
    def _current_committed_task_attempt_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_id: str,
    ) -> sqlite3.Row | None:
        rows = conn.execute(
            """SELECT d.*,c.commit_id,c.payload_json AS commit_payload_json,
                      c.created_at_ms AS commit_created_at_ms
               FROM room_kernel_dispatches d
               LEFT JOIN room_kernel_commits c ON c.dispatch_id=d.dispatch_id
               WHERE d.root_id=? AND d.task_id=? AND d.intent_kind!='close'
               ORDER BY d.updated_at_ms,d.created_at_ms,d.dispatch_id""",
            (root_id, task_id),
        ).fetchall()
        if not rows:
            return None

        def rank(row: sqlite3.Row) -> tuple[int, int, int, str]:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            return (
                int(
                    payload.get("attempt") or 0
                    if isinstance(payload, Mapping)
                    else 0
                ),
                int(row["updated_at_ms"] or 0),
                int(row["created_at_ms"] or 0),
                str(row["dispatch_id"]),
            )

        current = max(rows, key=rank)
        if (
            str(current["state"]) != "committed"
            or current["commit_id"] is None
            or current["commit_payload_json"] is None
        ):
            return None
        return current

    @staticmethod
    def _workspace_integration_receipt_refs(
        workspace_result: Mapping[str, object],
    ) -> dict[str, str]:
        return {
            field: str(workspace_result.get(field) or "").strip()
            for field in _WORKSPACE_INTEGRATION_RECEIPT_FIELDS
            if str(workspace_result.get(field) or "").strip()
        }

    @staticmethod
    def _workspace_integration_receipt_refs_valid(
        refs: Mapping[str, object],
        *,
        cleanup_state: str,
    ) -> bool:
        keys = set(refs)
        if keys - set(_WORKSPACE_INTEGRATION_RECEIPT_FIELDS):
            return False
        base_prefixes = (
            "Delivery",
            "SourceLease",
            "TargetApplied",
            "Integrated",
            "Cleanup",
        )
        optional_prefixes = (
            "WriterQuiescence",
            "Quarantine",
            "RemovalAuthorization",
            "Vault",
        )
        for prefix in (*base_prefixes, *optional_prefixes):
            pair = {
                f"workspace{prefix}ReceiptId",
                f"workspace{prefix}ReceiptSha256",
            }
            if bool(keys & pair) != bool(pair <= keys):
                return False
        if any(
            not str(value or "").strip()
            for value in refs.values()
        ):
            return False
        required = {
            f"workspace{prefix}Receipt{suffix}"
            for prefix in base_prefixes
            for suffix in ("Id", "Sha256")
        }
        if cleanup_state in {"cleaned", "missing"}:
            required.update(
                f"workspace{prefix}Receipt{suffix}"
                for prefix in (
                    "WriterQuiescence",
                    "Quarantine",
                    "RemovalAuthorization",
                )
                for suffix in ("Id", "Sha256")
            )
        if cleanup_state == "cleaned":
            required.update(
                {
                    "workspaceVaultReceiptId",
                    "workspaceVaultReceiptSha256",
                }
            )
        return required <= keys

    @classmethod
    def _workspace_integration_authority_locked(
        cls,
        *,
        task_payload: Mapping[str, object],
        workspace_result: Mapping[str, object],
        acceptance_receipt_row: sqlite3.Row,
        acceptance_receipt: Mapping[str, object],
        acceptance_authority: Mapping[str, object],
    ) -> dict[str, object]:
        delivery = task_payload.get("workspaceDelivery")
        if not isinstance(delivery, Mapping):
            raise RoomKernelFenceError(
                "workspace integration authority requires delivered evidence"
            )
        refs = cls._workspace_integration_receipt_refs(workspace_result)
        cleanup_state = _required(
            workspace_result.get("cleanupState"),
            "workspace cleanup state",
        )
        if not cls._workspace_integration_receipt_refs_valid(
            refs,
            cleanup_state=cleanup_state,
        ):
            raise RoomKernelFenceError(
                "workspace integration authority has an incomplete receipt chain"
            )
        task_revision = int(task_payload.get("revision") or 0)
        material: dict[str, object] = {
            "schemaVersion": (
                "wisdom-weasel.workspace-integration-authority.v1"
            ),
            "rootId": _required(task_payload.get("rootId"), "root_id"),
            "taskId": _required(task_payload.get("taskId"), "task_id"),
            "acceptanceTaskRevision": int(
                acceptance_authority.get("taskRevision") or 0
            ),
            "taskRevisionBeforeIntegration": task_revision - 1,
            "taskRevision": task_revision,
            "workspaceBindingId": _required(
                task_payload.get("workspaceBindingId"),
                "workspace_binding_id",
            ),
            "workspaceDeliveryRevision": _required(
                task_payload.get("workspaceDeliveryRevision"),
                "workspace_delivery_revision",
            ),
            "workspaceDeliverySnapshotSha256": _required(
                task_payload.get("workspaceDeliverySnapshotSha256"),
                "workspace_delivery_snapshot_sha256",
            ),
            "workspaceDeliveryPatchSha256": _required(
                delivery.get("patchSha256"),
                "workspace_delivery_patch_sha256",
            ),
            "workspaceDeliveryManifestSha256": _required(
                delivery.get("manifestSha256"),
                "workspace_delivery_manifest_sha256",
            ),
            "workspaceIntegrationRef": _required(
                workspace_result.get("integrationRef"),
                "workspace_integration_ref",
            ),
            "workspaceIntegratedRevision": _required(
                workspace_result.get("integratedRevision"),
                "workspace_integrated_revision",
            ),
            "workspaceIntegratedSnapshotSha256": _required(
                workspace_result.get("integratedSnapshotSha256"),
                "workspace_integrated_snapshot_sha256",
            ),
            "workspaceIntegrationPatchSha256": _required(
                workspace_result.get("integrationPatchSha256"),
                "workspace_integration_patch_sha256",
            ),
            "workspaceLifecycleState": _required(
                workspace_result.get("workspaceLifecycleState"),
                "workspace_lifecycle_state",
            ),
            "workspaceCleanupState": cleanup_state,
            "workspaceAttentionRequired": bool(
                workspace_result.get("attentionRequired")
            ),
            "workspaceReceiptRefs": refs,
            "acceptanceAuthorityBindingId": _required(
                acceptance_authority.get("bindingId"),
                "acceptance_authority_binding_id",
            ),
            "acceptanceAuthorityReceiptId": str(
                acceptance_receipt_row["receipt_id"]
            ),
            "acceptanceAuthorityReceiptSha256": hashlib.sha256(
                _json(dict(acceptance_receipt)).encode("utf-8")
            ).hexdigest(),
            "commitId": _required(
                acceptance_authority.get("commitId"),
                "commit_id",
            ),
            "commitCanonicalContentHash": _required(
                acceptance_authority.get("commitCanonicalContentHash"),
                "commit_canonical_content_hash",
            ),
            "qualityGateReceiptId": _required(
                acceptance_authority.get("qualityGateReceiptId"),
                "quality_gate_receipt_id",
            ),
            "criteria": acceptance_authority.get("criteria"),
            "evidenceRefs": acceptance_authority.get("evidenceRefs"),
            "requirementCoverage": acceptance_authority.get(
                "requirementCoverage"
            ),
        }
        if material["taskRevisionBeforeIntegration"] < 0:
            raise RoomKernelFenceError(
                "workspace integration authority has an invalid Task revision"
            )
        if (
            material["workspaceDeliveryPatchSha256"]
            != material["workspaceIntegrationPatchSha256"]
        ):
            raise RoomKernelFenceError(
                "workspace integration patch does not match the delivered patch"
            )
        encoded = _json(material).encode("utf-8")
        return {
            **material,
            "bindingId": "workspace-integration-authority:"
            + hashlib.sha256(encoded).hexdigest(),
        }

    @classmethod
    def _workspace_integration_authority_candidates_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_id: str,
        receipt_kind: str,
        operation: str,
    ) -> list[tuple[sqlite3.Row, Mapping[str, object], Mapping[str, object]]]:
        rows = conn.execute(
            """SELECT * FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind=?
               ORDER BY created_at_ms,receipt_id""",
            (root_id, receipt_kind),
        ).fetchall()
        candidates: list[
            tuple[sqlite3.Row, Mapping[str, object], Mapping[str, object]]
        ] = []
        for row in rows:
            try:
                receipt = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(receipt, Mapping):
                continue
            details = receipt.get("details")
            if not isinstance(details, Mapping):
                continue
            authority = details.get("integrationAuthority")
            if details.get("operation") != operation:
                continue
            authority_task_id = (
                str(authority.get("taskId") or "")
                if isinstance(authority, Mapping)
                else ""
            )
            if (
                str(details.get("taskId") or "") == task_id
                or authority_task_id == task_id
            ) and isinstance(authority, Mapping):
                candidates.append((row, receipt, authority))
        return candidates

    @classmethod
    def _workspace_integration_authority_candidate_valid_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_payload: Mapping[str, object],
        dispatch: sqlite3.Row,
        commit_id: str,
        raw_commit: Mapping[str, object],
        acceptance_receipt_row: sqlite3.Row,
        acceptance_receipt: Mapping[str, object],
        acceptance_authority: Mapping[str, object],
        candidate: tuple[
            sqlite3.Row,
            Mapping[str, object],
            Mapping[str, object],
        ],
        operation: str,
        receipt_kind: str,
        status: str,
        successful_cleanup: bool,
    ) -> bool:
        row, receipt, authority = candidate
        if not cls._kernel_receipt_row_is_canonical_locked(row, receipt):
            return False
        details = receipt.get("details")
        if not isinstance(details, Mapping) or set(details) != {
            "operation",
            "taskId",
            "integrationRef",
            "integrated",
            "workspaceLifecycleState",
            "workspaceCleanupState",
            "integrationAuthority",
        }:
            return False
        required_keys = {
            "schemaVersion",
            "rootId",
            "taskId",
            "acceptanceTaskRevision",
            "taskRevisionBeforeIntegration",
            "taskRevision",
            "workspaceBindingId",
            "workspaceDeliveryRevision",
            "workspaceDeliverySnapshotSha256",
            "workspaceDeliveryPatchSha256",
            "workspaceDeliveryManifestSha256",
            "workspaceIntegrationRef",
            "workspaceIntegratedRevision",
            "workspaceIntegratedSnapshotSha256",
            "workspaceIntegrationPatchSha256",
            "workspaceLifecycleState",
            "workspaceCleanupState",
            "workspaceAttentionRequired",
            "workspaceReceiptRefs",
            "acceptanceAuthorityBindingId",
            "acceptanceAuthorityReceiptId",
            "acceptanceAuthorityReceiptSha256",
            "commitId",
            "commitCanonicalContentHash",
            "qualityGateReceiptId",
            "criteria",
            "evidenceRefs",
            "requirementCoverage",
            "bindingId",
        }
        if set(authority) != required_keys:
            return False
        cleanup_state = str(authority.get("workspaceCleanupState") or "")
        authority_attention = authority.get("workspaceAttentionRequired")
        cleanup_is_successful = cleanup_state in {"cleaned", "missing"}
        if (
            not isinstance(authority_attention, bool)
            or cleanup_is_successful is not successful_cleanup
            or authority_attention is successful_cleanup
        ):
            return False
        task_expected = {
            "rootId": task_payload.get("rootId"),
            "taskId": task_payload.get("taskId"),
            "taskRevision": int(task_payload.get("revision") or 0),
            "workspaceBindingId": task_payload.get("workspaceBindingId"),
            "workspaceDeliveryRevision": task_payload.get(
                "workspaceDeliveryRevision"
            ),
            "workspaceDeliverySnapshotSha256": task_payload.get(
                "workspaceDeliverySnapshotSha256"
            ),
            "workspaceIntegrationRef": task_payload.get(
                "workspaceIntegrationRef"
            ),
            "workspaceIntegratedRevision": task_payload.get(
                "workspaceIntegratedRevision"
            ),
            "workspaceIntegratedSnapshotSha256": task_payload.get(
                "workspaceIntegratedSnapshotSha256"
            ),
            "workspaceIntegrationPatchSha256": task_payload.get(
                "workspaceIntegrationPatchSha256"
            ),
            "workspaceLifecycleState": task_payload.get(
                "workspaceLifecycleState"
            ),
            "workspaceCleanupState": task_payload.get(
                "workspaceCleanupState"
            ),
            "workspaceAttentionRequired": task_payload.get(
                "workspaceAttentionRequired"
            ),
        }
        if any(
            authority.get(key) != value
            for key, value in task_expected.items()
        ):
            return False
        refs = authority.get("workspaceReceiptRefs")
        if not isinstance(refs, Mapping) or not cls._workspace_integration_receipt_refs_valid(
            refs,
            cleanup_state=str(authority.get("workspaceCleanupState") or ""),
        ):
            return False
        workspace_result: dict[str, object] = {
            "integrated": True,
            "workspaceBindingId": authority.get("workspaceBindingId"),
            "integrationRef": authority.get("workspaceIntegrationRef"),
            "integrationPatchSha256": authority.get(
                "workspaceIntegrationPatchSha256"
            ),
            "integratedRevision": authority.get("workspaceIntegratedRevision"),
            "integratedSnapshotSha256": authority.get(
                "workspaceIntegratedSnapshotSha256"
            ),
            "workspaceLifecycleState": authority.get(
                "workspaceLifecycleState"
            ),
            "cleanupState": authority.get("workspaceCleanupState"),
            "attentionRequired": authority.get("workspaceAttentionRequired"),
            **dict(refs),
        }
        try:
            cls._assert_workspace_integration_receipts(
                conn,
                task=task_payload,
                result=workspace_result,
                integration_ref=str(
                    authority.get("workspaceIntegrationRef") or ""
                ),
                require_binding_projection=successful_cleanup,
            )
            expected = cls._workspace_integration_authority_locked(
                task_payload=task_payload,
                workspace_result=workspace_result,
                acceptance_receipt_row=acceptance_receipt_row,
                acceptance_receipt=acceptance_receipt,
                acceptance_authority=acceptance_authority,
            )
        except (RoomKernelFenceError, TypeError, ValueError, KeyError):
            return False
        return bool(
            dict(authority) == expected
            and receipt.get("receiptKind") == receipt_kind
            and receipt.get("status") == status
            and details.get("operation") == operation
            and details.get("taskId") == task_payload.get("taskId")
            and details.get("integrationRef")
            == authority.get("workspaceIntegrationRef")
            and details.get("integrated") is True
            and details.get("workspaceLifecycleState")
            == authority.get("workspaceLifecycleState")
            and details.get("workspaceCleanupState")
            == authority.get("workspaceCleanupState")
            and authority.get("rootId") == root_id
            and authority.get("commitId") == commit_id
            and str(raw_commit.get("commitId") or "") == commit_id
            and str(dispatch["dispatch_id"])
            == str(raw_commit.get("dispatchId") or "")
        )

    @classmethod
    def _workspace_integration_authority_valid_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_payload: Mapping[str, object],
        dispatch: sqlite3.Row,
        commit_id: str,
        raw_commit: Mapping[str, object],
        acceptance_receipt_row: sqlite3.Row,
        acceptance_receipt: Mapping[str, object],
        acceptance_authority: Mapping[str, object],
    ) -> bool:
        if (
            task_payload.get("workspaceIntegrationState") != "applied"
            or not str(task_payload.get("workspaceIntegrationRef") or "").strip()
            or str(task_payload.get("workspaceCleanupState") or "")
            not in {"cleaned", "missing"}
            or task_payload.get("workspaceAttentionRequired") is not False
        ):
            return False
        candidates = cls._workspace_integration_authority_candidates_locked(
            conn,
            root_id=root_id,
            task_id=str(task_payload.get("taskId") or ""),
            receipt_kind="accepted",
            operation="room_integrate",
        )
        return bool(
            len(candidates) == 1
            and cls._workspace_integration_authority_candidate_valid_locked(
                conn,
                root_id=root_id,
                task_payload=task_payload,
                dispatch=dispatch,
                commit_id=commit_id,
                raw_commit=raw_commit,
                acceptance_receipt_row=acceptance_receipt_row,
                acceptance_receipt=acceptance_receipt,
                acceptance_authority=acceptance_authority,
                candidate=candidates[0],
                operation="room_integrate",
                receipt_kind="accepted",
                status="applied",
                successful_cleanup=True,
            )
        )

    @classmethod
    def _pending_workspace_integration_authority_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_payload: Mapping[str, object],
        dispatch: sqlite3.Row,
        commit_id: str,
        raw_commit: Mapping[str, object],
        acceptance_receipt_row: sqlite3.Row,
        acceptance_receipt: Mapping[str, object],
        acceptance_authority: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        if (
            task_payload.get("workspaceIntegrationState") != "applied"
            or not str(task_payload.get("workspaceIntegrationRef") or "").strip()
            or str(task_payload.get("workspaceCleanupState") or "")
            in {"cleaned", "missing"}
            or task_payload.get("workspaceAttentionRequired") is not True
        ):
            return None
        candidates = cls._workspace_integration_authority_candidates_locked(
            conn,
            root_id=root_id,
            task_id=str(task_payload.get("taskId") or ""),
            receipt_kind="rejected",
            operation="room_integrate_pending_cleanup",
        )
        if len(candidates) != 1 or not (
            cls._workspace_integration_authority_candidate_valid_locked(
                conn,
                root_id=root_id,
                task_payload=task_payload,
                dispatch=dispatch,
                commit_id=commit_id,
                raw_commit=raw_commit,
                acceptance_receipt_row=acceptance_receipt_row,
                acceptance_receipt=acceptance_receipt,
                acceptance_authority=acceptance_authority,
                candidate=candidates[0],
                operation="room_integrate_pending_cleanup",
                receipt_kind="rejected",
                status="rejected",
                successful_cleanup=False,
            )
        ):
            return None
        return candidates[0][2]

    @classmethod
    def _workspace_task_integration_authority_state_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Re-derive one isolated Task's exact integration authority state."""

        integration_ref = str(
            task_payload.get("workspaceIntegrationRef") or ""
        ).strip()
        state = {
            "status": "invalid",
            "integrationRef": integration_ref or None,
            "taskRevision": int(task_payload.get("revision") or 0),
        }
        if (
            task_payload.get("workspacePolicy") != "isolated_writable"
            or str(task_payload.get("rootId") or "") != root_id
        ):
            return state
        task_id = str(task_payload.get("taskId") or "").strip()
        attempt = cls._current_committed_task_attempt_locked(
            conn,
            root_id=root_id,
            task_id=task_id,
        )
        if attempt is None:
            return state
        try:
            raw_commit = json.loads(str(attempt["commit_payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return state
        if not isinstance(raw_commit, Mapping):
            return state
        commit_id = str(attempt["commit_id"] or "")
        acceptance_candidate = (
            cls._canonical_acceptance_authority_receipt_locked(
                conn,
                root_id=root_id,
                commit_id=commit_id,
            )
        )
        if acceptance_candidate is None or not (
            cls._acceptance_commit_authority_valid_locked(
                conn,
                root_id=root_id,
                task_payload=task_payload,
                dispatch=attempt,
                commit_id=commit_id,
                raw_commit=raw_commit,
                require_integration=None,
            )
        ):
            return state
        if task_payload.get("workspaceIntegrationState") != "applied":
            if cls._acceptance_commit_authority_valid_locked(
                conn,
                root_id=root_id,
                task_payload=task_payload,
                dispatch=attempt,
                commit_id=commit_id,
                raw_commit=raw_commit,
                require_integration=False,
            ):
                state["status"] = "ready"
            return state
        (
            acceptance_receipt_row,
            acceptance_receipt,
            acceptance_authority,
        ) = acceptance_candidate
        if cls._workspace_integration_authority_valid_locked(
            conn,
            root_id=root_id,
            task_payload=task_payload,
            dispatch=attempt,
            commit_id=commit_id,
            raw_commit=raw_commit,
            acceptance_receipt_row=acceptance_receipt_row,
            acceptance_receipt=acceptance_receipt,
            acceptance_authority=acceptance_authority,
        ):
            state["status"] = "accepted"
            return state
        if cls._pending_workspace_integration_authority_locked(
            conn,
            root_id=root_id,
            task_payload=task_payload,
            dispatch=attempt,
            commit_id=commit_id,
            raw_commit=raw_commit,
            acceptance_receipt_row=acceptance_receipt_row,
            acceptance_receipt=acceptance_receipt,
            acceptance_authority=acceptance_authority,
        ) is not None:
            state["status"] = "pending_cleanup"
        return state

    def workspace_integration_authority(
        self,
        task_id: str,
    ) -> dict[str, object]:
        """Read the canonical integration state consumed by application replay."""

        normalized_task_id = _required(task_id, "task_id")
        with self._connect() as conn:
            task = self.task(normalized_task_id, conn=conn)
            return self._workspace_task_integration_authority_state_locked(
                conn,
                root_id=str(task.get("rootId") or ""),
                task_payload=task,
            )

    def _prior_review_findings_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_payload: Mapping[str, object],
    ) -> list[dict[str, object]]:
        """Merge Finding history across Review Tasks for one target set.

        A replacement Review Task is a new persistence identity, not a new
        Finding universe.  Blocking identity and stable content therefore
        remain sticky across every Review Task that names the exact same
        reviewed-Task set.
        """

        target_ids = tuple(
            sorted(
                {
                    str(value).strip()
                    for value in task_payload.get("reviewOfTaskIds", ())
                    if str(value or "").strip()
                }
            )
        )
        if not target_ids:
            return [
                dict(item)
                for item in task_payload.get("reviewFindings", ())
                if isinstance(item, Mapping)
            ]
        rows = conn.execute(
            """SELECT task_id,payload_json,updated_at_ms
               FROM room_kernel_tasks
               WHERE root_id=?
               ORDER BY updated_at_ms,task_id""",
            (_required(root_id, "root_id"),),
        ).fetchall()
        history: list[
            tuple[tuple[int, int, int, str], dict[str, object], dict[str, object]]
        ] = []
        for row in rows:
            try:
                candidate_task = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(candidate_task, Mapping):
                continue
            candidate_targets = tuple(
                sorted(
                    {
                        str(value).strip()
                        for value in candidate_task.get(
                            "reviewOfTaskIds",
                            (),
                        )
                        if str(value or "").strip()
                    }
                )
            )
            if (
                candidate_targets != target_ids
                or str(candidate_task.get("taskKind") or "") != "review"
            ):
                continue
            review_round = max(
                1,
                int(candidate_task.get("reviewRound") or 1),
            )
            revision = int(candidate_task.get("revision") or 0)
            commit_rows = conn.execute(
                """SELECT c.commit_id,c.payload_json,c.created_at_ms
                   FROM room_kernel_commits c
                   JOIN room_kernel_dispatches d
                     ON d.dispatch_id=c.dispatch_id
                   WHERE c.root_id=? AND d.task_id=?
                     AND d.intent_kind IN ('review','resume')
                   ORDER BY c.created_at_ms,c.commit_id""",
                (root_id, str(row["task_id"])),
            ).fetchall()
            for commit_row in commit_rows:
                commit = _room_commit_payload(
                    conn,
                    commit_row["payload_json"],
                )
                commit_source = dict(candidate_task)
                binding = commit.get("reviewEvidenceBinding")
                if isinstance(binding, Mapping) and str(
                    binding.get("reviewTargetRevision") or ""
                ).strip():
                    commit_source["reviewTargetRevision"] = str(
                        binding["reviewTargetRevision"]
                    )
                commit_rank = (
                    review_round,
                    int(commit_row["created_at_ms"] or 0),
                    revision,
                    f"commit:{commit_row['commit_id']}",
                )
                for finding in commit.get("reviewFindings", ()):
                    if isinstance(finding, Mapping):
                        history.append(
                            (
                                commit_rank,
                                dict(finding),
                                commit_source,
                            )
                        )
            rank = (
                review_round,
                int(row["updated_at_ms"] or 0),
                revision,
                f"task:{row['task_id']}",
            )
            for finding in candidate_task.get("reviewFindings", ()):
                if isinstance(finding, Mapping):
                    history.append((rank, dict(finding), dict(candidate_task)))
        history.sort(key=lambda value: value[0])
        by_id: dict[str, dict[str, object]] = {}
        by_fingerprint: dict[str, str] = {}
        stable_fields = (
            "category",
            "scope",
            "observation",
            "expected",
            "userImpact",
        )
        for _rank, finding, source_task in history:
            finding_id = str(finding.get("findingId") or "").strip()
            fingerprint = str(finding.get("fingerprint") or "").strip()
            if not finding_id or not fingerprint:
                raise RoomKernelFenceError(
                    "Review Finding history has no stable identity"
                )
            prior = by_id.get(finding_id)
            prior_id_for_fingerprint = by_fingerprint.get(fingerprint)
            if (
                prior is not None
                and str(prior.get("fingerprint") or "") != fingerprint
            ) or (
                prior_id_for_fingerprint is not None
                and prior_id_for_fingerprint != finding_id
            ):
                raise RoomKernelFenceError(
                    "Review Finding history changed findingId or fingerprint"
                )
            if prior is None:
                by_id[finding_id] = finding
                by_fingerprint[fingerprint] = finding_id
                continue
            if any(
                finding.get(field) != prior.get(field)
                for field in stable_fields
            ):
                raise RoomKernelFenceError(
                    "Review Finding history changed stable scope or content"
                )
            if prior.get("gateEffect") == "blocking":
                if finding.get("gateEffect") != "blocking":
                    # Preserve the blocker so the next Commit is rejected and
                    # a corrupt historical advisory cannot pop it in scanning.
                    continue
                state = str(finding.get("state") or "")
                if state == "resolved":
                    response = finding.get("response")
                    target_revision = str(
                        source_task.get("reviewTargetRevision") or ""
                    )
                    if (
                        isinstance(response, Mapping)
                        and response.get("findingId") == finding_id
                        and response.get("action") == "fixed"
                        and str(finding.get("firstSeenRevision") or "")
                        != str(finding.get("lastCheckedRevision") or "")
                        and str(finding.get("lastCheckedRevision") or "")
                        == target_revision
                    ):
                        by_id[finding_id] = finding
                    continue
                if state == "dismissed":
                    resolution = self._independent_finding_resolution_locked(
                        conn,
                        root_id=root_id,
                        review_target_revision=str(
                            finding.get("lastCheckedRevision")
                            or source_task.get("reviewTargetRevision")
                            or ""
                        ),
                        finding_id=finding_id,
                    )
                    if resolution is not None:
                        by_id[finding_id] = finding
                    continue
                if state in {"open", "contested", "escalated"}:
                    by_id[finding_id] = finding
                continue
            by_id[finding_id] = finding
        return list(by_id.values())

    def _review_finding_evidence_authority_locked(
        self,
        conn: sqlite3.Connection,
        *,
        task_payload: Mapping[str, object],
        dispatch: sqlite3.Row,
        commit_payload: Mapping[str, object],
    ) -> frozenset[str]:
        """Bind one new Finding set to this ReviewDispatch's runtime receipts."""

        dispatch_payload = _dispatch_payload(dispatch)
        commit_refs = {
            str(value).strip()
            for value in commit_payload.get("evidenceRefs", ())
            if str(value or "").strip()
        }
        binding = commit_payload.get("reviewEvidenceBinding")
        gate = commit_payload.get("qualityGateReceipt")
        if not isinstance(binding, Mapping) or not isinstance(gate, Mapping):
            raise RoomKernelFenceError(
                "Review Finding evidence lacks its canonical Commit binding"
            )
        raw_bound_refs = binding.get("evidenceRefs")
        if not isinstance(raw_bound_refs, list):
            raise RoomKernelFenceError(
                "Review Finding evidence lacks its canonical Commit binding"
            )
        bound_refs = {
            str(value).strip()
            for value in raw_bound_refs
            if str(value or "").strip()
        }
        gate_refs = {
            str(value).strip()
            for item in gate.get("items", ())
            if isinstance(item, Mapping)
            for value in item.get("evidenceRefs", ())
            if str(value or "").strip()
        }
        review_target_revision = str(
            task_payload.get("reviewTargetRevision") or ""
        )
        not_before_ms = int(
            task_payload.get("reviewEvidenceNotBeforeMs") or 0
        )
        binding_material = {
            "reviewTargetRevision": review_target_revision,
            "taskId": str(dispatch["task_id"]),
            "dispatchId": str(dispatch["dispatch_id"]),
            "evidenceRefs": sorted(commit_refs),
            "notBeforeMs": not_before_ms,
        }
        expected_binding_id = (
            "review-evidence-binding:"
            + hashlib.sha256(
                _json(binding_material).encode("utf-8")
            ).hexdigest()
        )
        try:
            binding_not_before_ms = int(
                binding.get("notBeforeMs") or -1
            )
        except (TypeError, ValueError):
            binding_not_before_ms = -1
        if (
            binding.get("schemaVersion")
            != "wisdom-weasel.review-evidence-binding.v1"
            or binding.get("reviewTargetRevision")
            != review_target_revision
            or binding.get("taskId") != str(dispatch["task_id"])
            or binding.get("dispatchId") != str(dispatch["dispatch_id"])
            or binding_not_before_ms != not_before_ms
            or list(raw_bound_refs) != sorted(commit_refs)
            or bound_refs != commit_refs
            or gate_refs != commit_refs
            or binding.get("bindingId") != expected_binding_id
        ):
            raise RoomKernelFenceError(
                "Review Finding evidence lacks its canonical Commit binding"
            )
        runtime_not_before_ms = max(
            not_before_ms,
            int(dispatch_payload.get("createdAtMs") or 0),
        ) + 1
        runtime_refs = runtime_evidence_refs_for_dispatch(
            conn,
            session_id=str(dispatch_payload["targetSessionId"]),
            root_id=str(dispatch["root_id"]),
            task_id=str(dispatch["task_id"]),
            dispatch_id=str(dispatch["dispatch_id"]),
            generation=int(dispatch["generation"]),
            capability_epoch=int(dispatch_payload["capabilityEpoch"]),
            not_before_ms=runtime_not_before_ms,
        )
        if not commit_refs.issubset(runtime_refs):
            raise RoomKernelFenceError(
                "Review Finding cites stale or foreign evidence"
            )
        return frozenset(commit_refs)

    def _canonical_review_finding_lineage_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_payload: Mapping[str, object],
        submitted_findings: object,
    ) -> list[dict[str, object]]:
        """Merge one re-review with the Task's canonical Finding lineage.

        Settlement normally constructs these fields, but the Kernel is the
        authority that persists them.  A direct or replayed Commit must not be
        able to erase a blocker, rebind its stable identity, reset its recheck
        counter, or invent a fix/arbiter disposition.
        """

        if not isinstance(submitted_findings, Sequence) or isinstance(
            submitted_findings,
            (str, bytes),
        ):
            raise RoomKernelFenceError(
                "Reviewer Commit reviewFindings must be an array"
            )
        target_revision = str(
            task_payload.get("reviewTargetRevision") or ""
        ).strip()
        if not target_revision:
            raise RoomKernelFenceError(
                "Reviewer Task is missing reviewTargetRevision"
            )
        review_round = max(1, int(task_payload.get("reviewRound") or 1))
        previous_findings = self._prior_review_findings_locked(
            conn,
            root_id=root_id,
            task_payload=task_payload,
        )
        previous_by_id = {
            str(item.get("findingId") or "").strip(): item
            for item in previous_findings
            if str(item.get("findingId") or "").strip()
        }
        previous_by_fingerprint = {
            str(item.get("fingerprint") or "").strip(): item
            for item in previous_findings
            if str(item.get("fingerprint") or "").strip()
        }
        previous_blocking_scopes = {
            _review_finding_scope_key(item.get("scope"))
            for item in previous_findings
            if item.get("gateEffect") == "blocking"
        }
        previous_blocking_scopes.discard(None)
        unresolved_previous_ids = {
            str(item.get("findingId") or "").strip()
            for item in previous_findings
            if (
                item.get("gateEffect") == "blocking"
                and item.get("state")
                in {"open", "contested", "escalated"}
            )
            or (
                item.get("gateEffect") == "advisory"
                and item.get("state") == "open"
            )
        }
        unresolved_previous_ids.discard("")
        acceptance_criteria = {
            str(value).strip()
            for value in task_payload.get("acceptanceCriterionIds", ())
            if str(value or "").strip()
        }
        canonical: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        seen_fingerprints: set[str] = set()
        matched_previous_ids: set[str] = set()
        for index, item in enumerate(submitted_findings):
            if not isinstance(item, Mapping):
                raise RoomKernelFenceError(
                    f"reviewFindings[{index}] must be an object"
                )
            incoming = dict(item)
            finding_id = str(incoming.get("findingId") or "").strip()
            fingerprint = str(incoming.get("fingerprint") or "").strip()
            try:
                canonical_fingerprint = canonical_review_finding_fingerprint(
                    category=incoming.get("category"),
                    scope=incoming.get("scope"),
                    observation=incoming.get("observation"),
                    expected=incoming.get("expected"),
                    user_impact=incoming.get("userImpact"),
                )
            except ValueError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
            if fingerprint != canonical_fingerprint:
                raise RoomKernelFenceError(
                    "Review Finding fingerprint does not match its canonical content"
                )
            if finding_id in seen_ids or fingerprint in seen_fingerprints:
                raise RoomKernelFenceError(
                    "Reviewer Commit contains duplicate Finding identity"
                )
            seen_ids.add(finding_id)
            seen_fingerprints.add(fingerprint)
            prior_by_id = previous_by_id.get(finding_id)
            prior_by_fingerprint = previous_by_fingerprint.get(fingerprint)
            if (
                prior_by_id is not None
                and str(prior_by_id.get("fingerprint") or "")
                != fingerprint
            ) or (
                prior_by_fingerprint is not None
                and str(prior_by_fingerprint.get("findingId") or "")
                != finding_id
            ):
                raise RoomKernelFenceError(
                    "re-review must preserve each Finding findingId and fingerprint"
                )
            prior = prior_by_id or prior_by_fingerprint
            if prior is not None:
                matched_previous_ids.add(finding_id)
                for stable_field in (
                    "category",
                    "scope",
                    "observation",
                    "expected",
                    "userImpact",
                ):
                    if incoming.get(stable_field) != prior.get(stable_field):
                        raise RoomKernelFenceError(
                            "re-review cannot rebind a Finding's stable scope or content"
                        )
                if incoming.get("response") != prior.get("response"):
                    raise RoomKernelFenceError(
                        "re-review Finding response lacks exact revision lineage"
                    )
                incoming["firstSeenRevision"] = str(
                    prior.get("firstSeenRevision") or target_revision
                )
                incoming["lastCheckedRevision"] = target_revision
                incoming["ownerParticipantId"] = (
                    incoming.get("ownerParticipantId")
                    or prior.get("ownerParticipantId")
                )
                prior_gate = str(prior.get("gateEffect") or "")
                prior_state = str(prior.get("state") or "")
                requested_state = str(incoming.get("state") or "")
                if prior_gate == "blocking":
                    if incoming.get("gateEffect") != "blocking":
                        raise RoomKernelFenceError(
                            "a prior Blocking Finding cannot be downgraded"
                        )
                    if requested_state == "accepted_risk":
                        raise RoomKernelFenceError(
                            "a Blocking Finding cannot be accepted as risk"
                        )
                    if requested_state == "resolved":
                        response = prior.get("response")
                        if (
                            not isinstance(response, Mapping)
                            or response.get("findingId") != finding_id
                            or response.get("action") != "fixed"
                            or incoming["firstSeenRevision"]
                            == target_revision
                        ):
                            raise RoomKernelFenceError(
                                "a resolved Blocking Finding requires exact fix lineage"
                            )
                    elif requested_state == "dismissed":
                        resolution = (
                            self._independent_finding_resolution_locked(
                                conn,
                                root_id=root_id,
                                review_target_revision=target_revision,
                                finding_id=finding_id,
                            )
                        )
                        if resolution is None:
                            raise RoomKernelFenceError(
                                "a dismissed Blocking Finding requires an exact "
                                "independent arbiter resolution"
                            )
                        if not str(
                            incoming.get("dispositionRationale") or ""
                        ).strip():
                            raise RoomKernelFenceError(
                                "a dismissed Finding requires disposition rationale"
                            )
                    else:
                        failed_rechecks = min(
                            2,
                            int(prior.get("failedRechecks") or 0)
                            + (
                                1
                                if prior_state in {"open", "contested"}
                                and requested_state
                                in {"open", "contested", "escalated"}
                                else 0
                            ),
                        )
                        response = prior.get("response")
                        next_state = (
                            "contested"
                            if prior_state == "contested"
                            or (
                                isinstance(response, Mapping)
                                and response.get("action") == "contest"
                            )
                            else "open"
                        )
                        if prior_state == "escalated" or failed_rechecks >= 2:
                            next_state = "escalated"
                            failed_rechecks = 2
                        incoming["state"] = next_state
                        incoming["failedRechecks"] = failed_rechecks
                    if incoming.get("state") in {"resolved", "dismissed"}:
                        incoming["failedRechecks"] = int(
                            prior.get("failedRechecks") or 0
                        )
                else:
                    incoming["failedRechecks"] = int(
                        prior.get("failedRechecks") or 0
                    )
                    if (
                        incoming.get("state")
                        in {"dismissed", "accepted_risk"}
                        and not str(
                            incoming.get("dispositionRationale") or ""
                        ).strip()
                    ):
                        raise RoomKernelFenceError(
                            "an Advisory disposition requires rationale"
                        )
            else:
                incoming["firstSeenRevision"] = target_revision
                incoming["lastCheckedRevision"] = target_revision
                incoming["failedRechecks"] = 0
                incoming["response"] = None
                if incoming.get("gateEffect") == "blocking":
                    scope_key = _review_finding_scope_key(
                        incoming.get("scope")
                    )
                    category = str(incoming.get("category") or "")
                    if (
                        review_round > 1
                        and scope_key not in previous_blocking_scopes
                        and category
                        not in REVIEW_FINDING_RE_REVIEW_EXCEPTION_CATEGORIES
                    ):
                        incoming["gateEffect"] = "advisory"
                        incoming["impact"] = "normal"
                        incoming["dispositionRationale"] = (
                            str(
                                incoming.get("dispositionRationale") or ""
                            ).strip()
                            or "Late re-review scope is advisory for this Root."
                        )
                    else:
                        scope = incoming.get("scope")
                        criterion_id = (
                            str(scope.get("criterionId") or "").strip()
                            if isinstance(scope, Mapping)
                            else ""
                        )
                        invariant_id = (
                            str(scope.get("invariantId") or "").strip()
                            if isinstance(scope, Mapping)
                            else ""
                        )
                        if (
                            incoming.get("impact")
                            not in {"critical", "high"}
                            or category
                            not in REVIEW_FINDING_BLOCKING_CATEGORIES
                            or (
                                criterion_id not in acceptance_criteria
                                and invariant_id
                                not in REVIEW_FINDING_GOVERNANCE_INVARIANTS
                            )
                        ):
                            raise RoomKernelFenceError(
                                "Review Finding is not admissible as blocking"
                            )
                        if incoming.get("state") in {
                            "resolved",
                            "dismissed",
                            "accepted_risk",
                        }:
                            raise RoomKernelFenceError(
                                "a new Blocking Finding cannot start disposed"
                            )
            canonical.append(incoming)

        missing_unresolved = unresolved_previous_ids - matched_previous_ids
        if missing_unresolved:
            kinds = {
                str(previous_by_id[finding_id].get("gateEffect") or "")
                for finding_id in missing_unresolved
                if finding_id in previous_by_id
            }
            label = (
                "Blocking Finding"
                if kinds == {"blocking"}
                else "Review Finding"
            )
            raise RoomKernelFenceError(
                f"re-review cannot omit a prior unresolved {label}: "
                + ", ".join(sorted(missing_unresolved))
            )

        # Keep already-disposed history even when the caller omits it.  Active
        # findings fail closed above; historical findings are merged so a
        # later Task projection cannot destroy the audit trail.
        canonical.extend(
            dict(prior)
            for prior in previous_findings
            if str(prior.get("findingId") or "")
            not in matched_previous_ids
        )
        return canonical

    @staticmethod
    def _independent_finding_resolution_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        review_target_revision: str,
        finding_id: str,
    ) -> dict[str, object] | None:
        """Find an immutable independent-arbiter receipt for one Finding.

        The peer-review round is the lineage boundary: it must target the
        exact review revision, belong to this Root, and its conflict matrix
        must name the Finding code. A generic or unrelated pass receipt cannot
        dismiss a blocking ReviewFinding.
        """

        rows = conn.execute(
            """SELECT resolution.resolution_receipt_id,
                      resolution.authority_kind,
                      resolution.authority_ref,
                      resolution.resolution_verdict,
                      resolution.matrix_revision_id,
                      resolution.created_at_ms,
                      round.root_id,round.target_commit,
                      matrix.entries_json
               FROM room_v2_conflict_resolution_receipts resolution
               JOIN room_v2_peer_judgment_rounds round
                 ON round.round_id=resolution.round_id
               JOIN room_v2_conflict_matrix_revisions matrix
                 ON matrix.matrix_revision_id=resolution.matrix_revision_id
               WHERE round.root_id=? AND round.target_commit=?
                 AND resolution.authority_kind='independent_arbiter'
                 AND resolution.resolution_verdict='pass'
               ORDER BY resolution.created_at_ms DESC,
                        resolution.resolution_receipt_id DESC""",
            (
                _required(root_id, "root_id"),
                _required(
                    review_target_revision,
                    "review_target_revision",
                ),
            ),
        ).fetchall()
        for row in rows:
            try:
                matrix_payload = json.loads(str(row["entries_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            entries = (
                matrix_payload.get("entries")
                if isinstance(matrix_payload, Mapping)
                else matrix_payload
            )
            if not isinstance(entries, list):
                continue
            finding_codes = {
                str(code).strip()
                for entry in entries
                if isinstance(entry, Mapping)
                for code in (
                    entry.get("findingCodes")
                    if isinstance(entry.get("findingCodes"), list)
                    else ()
                )
                if str(code or "").strip()
            }
            if finding_id not in finding_codes:
                continue
            return {
                "resolutionReceiptId": str(
                    row["resolution_receipt_id"]
                ),
                "authorityKind": str(row["authority_kind"]),
                "authorityRef": str(row["authority_ref"]),
                "resolutionVerdict": str(
                    row["resolution_verdict"]
                ),
                "matrixRevisionId": str(row["matrix_revision_id"]),
                "createdAtMs": int(row["created_at_ms"]),
            }
        return None

    def independent_finding_resolution(
        self,
        *,
        root_id: str,
        review_target_revision: str,
        finding_id: str,
    ) -> dict[str, object] | None:
        """Return the exact arbiter lineage that may dismiss one blocker."""

        with self._connect() as conn:
            return self._independent_finding_resolution_locked(
                conn,
                root_id=root_id,
                review_target_revision=review_target_revision,
                finding_id=_required(finding_id, "finding_id"),
            )

    def _review_attempt_independence_fence_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        lineage_id: str,
        attempt: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Recheck every accepted review, including superseded Task IDs."""

        payload = attempt.get("payload")
        dispatch = attempt.get("dispatch")
        if not isinstance(payload, Mapping) or not isinstance(
            dispatch,
            Mapping,
        ):
            return None
        if (
            attempt.get("taskState") != "completed"
            or payload.get("reviewState")
            not in {"accepted", "accepted_with_notes"}
            or dispatch.get("state") != "committed"
        ):
            return None
        target_ids = {
            str(value).strip()
            for value in payload.get("reviewOfTaskIds", ())
            if str(value or "").strip()
        }
        reviewer_id = str(
            dispatch.get("targetParticipantId") or ""
        ).strip()
        authors = {
            str(value).strip()
            for value in payload.get("reviewAuthorParticipantIds", ())
            if str(value or "").strip()
        }
        implementers: set[str] = set()
        integration_seen = False
        for reviewed_task_id in target_ids:
            reviewed_task = conn.execute(
                """SELECT payload_json FROM room_kernel_tasks
                   WHERE root_id=? AND task_id=?""",
                (root_id, reviewed_task_id),
            ).fetchone()
            if reviewed_task is not None:
                try:
                    reviewed_payload = json.loads(
                        str(reviewed_task["payload_json"])
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    reviewed_payload = {}
                if isinstance(reviewed_payload, Mapping):
                    owner_id = str(
                        reviewed_payload.get("currentOwnerParticipantId")
                        or ""
                    ).strip()
                    if owner_id:
                        implementers.add(owner_id)
            implementer_rows = conn.execute(
                """SELECT target_participant_id
                   FROM room_kernel_dispatches
                   WHERE root_id=? AND task_id=?
                     AND intent_kind IN ('execute','revise','retry')""",
                (root_id, reviewed_task_id),
            ).fetchall()
            implementers.update(
                str(row["target_participant_id"] or "").strip()
                for row in implementer_rows
                if str(row["target_participant_id"] or "").strip()
            )
            integration_rows = conn.execute(
                """SELECT * FROM room_kernel_receipts
                   WHERE root_id=? AND receipt_kind='accepted'
                   ORDER BY created_at_ms,receipt_id""",
                (root_id,),
            ).fetchall()
            for integration_row in integration_rows:
                try:
                    receipt = json.loads(
                        str(integration_row["payload_json"])
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(receipt, Mapping):
                    continue
                details = receipt.get("details")
                if (
                    isinstance(details, Mapping)
                    and details.get("operation") == "room_integrate"
                    and details.get("integrated") is True
                    and str(details.get("taskId") or "")
                    == reviewed_task_id
                    and self._kernel_receipt_row_is_canonical_locked(
                        integration_row,
                        receipt,
                    )
                ):
                    integration_seen = True
                    break
        if integration_seen:
            root = self._root_row(conn, root_id)
            facilitator_id = str(
                root["facilitator_participant_id"] or ""
            ).strip()
            if facilitator_id:
                implementers.add(facilitator_id)
        if (
            reviewer_id
            and authors
            and reviewer_id not in authors
            and reviewer_id not in implementers
        ):
            return None
        return {
            "reason": "reviewer_not_independent",
            "reviewedTaskId": lineage_id,
            "taskId": str(attempt.get("taskId") or ""),
            "reviewerParticipantId": reviewer_id or None,
            "reviewAuthorParticipantIds": sorted(authors),
            "implementationParticipantIds": sorted(implementers),
        }

    def _review_lineage_fences_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, list[dict[str, object]]]:
        """Validate every reviewed-Task lineage, not one global newest Task."""

        candidates = self._review_attempt_candidates_locked(
            conn,
            root_id=root_id,
        )
        histories: dict[str, list[dict[str, object]]] = {}
        for candidate in candidates:
            lineage_ids = candidate.get("reviewOfTaskIds")
            if not isinstance(lineage_ids, list) or not lineage_ids:
                lineage_ids = [f"review-task:{candidate['taskId']}"]
            for lineage_id in lineage_ids:
                histories.setdefault(str(lineage_id), []).append(candidate)
        review_fences: list[dict[str, object]] = []
        unresolved: list[dict[str, object]] = []
        evidence_mismatches: list[dict[str, object]] = []
        for lineage_id, history in sorted(histories.items()):
            history.sort(key=lambda value: tuple(value["_authorityRank"]))
            for historical_attempt in history:
                independence_fence = (
                    self._review_attempt_independence_fence_locked(
                        conn,
                        root_id=root_id,
                        lineage_id=lineage_id,
                        attempt=historical_attempt,
                    )
                )
                if (
                    independence_fence is not None
                    and independence_fence not in review_fences
                ):
                    review_fences.append(independence_fence)
            authoritative = history[-1]
            payload = authoritative.get("payload")
            dispatch = authoritative.get("dispatch")
            if not isinstance(payload, Mapping):
                payload = {}
            if not isinstance(dispatch, Mapping):
                dispatch = {}
            task_id = str(authoritative.get("taskId") or "")
            dispatch_id = str(dispatch.get("dispatchId") or "")
            review_state = str(payload.get("reviewState") or "")
            if (
                authoritative.get("taskState") != "completed"
                or review_state not in {"accepted", "accepted_with_notes"}
                or dispatch.get("state") != "committed"
            ):
                review_fences.append(
                    {
                        "reason": "review_lineage_not_accepted",
                        "reviewedTaskId": lineage_id,
                        "taskId": task_id,
                        "dispatchId": dispatch_id or None,
                    }
                )
                continue
            target_ids = [
                str(value)
                for value in payload.get("reviewOfTaskIds", ())
                if str(value or "").strip()
            ]
            expected_revision = str(
                payload.get("reviewTargetRevision") or ""
            )
            try:
                current_revision = self._review_target_revision_locked(
                    conn,
                    root_id=root_id,
                    task_ids=target_ids,
                    review_snapshot=payload,
                )
            except (RoomKernelFenceError, KeyError, TypeError, ValueError):
                current_revision = ""
            if (
                not expected_revision
                or expected_revision != current_revision
            ):
                evidence_mismatches.append(
                    {
                        "reason": "review_revision_mismatch",
                        "reviewedTaskId": lineage_id,
                        "taskId": task_id,
                        "expectedRevision": expected_revision or None,
                        "currentRevision": current_revision or None,
                    }
                )

            commit = authoritative.get("commit")
            binding = (
                commit.get("reviewEvidenceBinding")
                if isinstance(commit, Mapping)
                else None
            )
            gate = (
                commit.get("qualityGateReceipt")
                if isinstance(commit, Mapping)
                else None
            )
            bound_refs = {
                str(value).strip()
                for value in (
                    binding.get("evidenceRefs", ())
                    if isinstance(binding, Mapping)
                    else ()
                )
                if str(value or "").strip()
            }
            gate_refs = {
                str(value).strip()
                for item in (
                    gate.get("items", ())
                    if isinstance(gate, Mapping)
                    else ()
                )
                if isinstance(item, Mapping)
                and item.get("status") == "pass"
                for value in (
                    item.get("evidenceRefs")
                    if isinstance(item.get("evidenceRefs"), list)
                    else ()
                )
                if str(value or "").strip()
            }
            try:
                not_before_ms = int(
                    payload.get("reviewEvidenceNotBeforeMs") or 0
                )
            except (TypeError, ValueError):
                not_before_ms = 0
            binding_material = {
                "reviewTargetRevision": expected_revision,
                "taskId": task_id,
                "dispatchId": dispatch_id,
                "evidenceRefs": sorted(bound_refs),
                "notBeforeMs": not_before_ms,
            }
            expected_binding_id = (
                "review-evidence-binding:"
                + hashlib.sha256(
                    json.dumps(
                        binding_material,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            )
            if (
                not isinstance(binding, Mapping)
                or not isinstance(gate, Mapping)
                or binding.get("schemaVersion")
                != "wisdom-weasel.review-evidence-binding.v1"
                or binding.get("reviewTargetRevision")
                != expected_revision
                or binding.get("taskId") != task_id
                or binding.get("dispatchId") != dispatch_id
                or int(binding.get("notBeforeMs") or -1)
                != not_before_ms
                or not bound_refs
                or bound_refs != gate_refs
                or binding.get("bindingId") != expected_binding_id
            ):
                evidence_mismatches.append(
                    {
                        "reason": "review_evidence_binding_mismatch",
                        "reviewedTaskId": lineage_id,
                        "taskId": task_id,
                        "dispatchId": dispatch_id or None,
                    }
                )

            open_findings: dict[
                tuple[str, str], dict[str, object]
            ] = {}
            finding_by_id: dict[str, dict[str, object]] = {}
            finding_id_by_fingerprint: dict[str, str] = {}
            stable_finding_fields = (
                "category",
                "scope",
                "observation",
                "expected",
                "userImpact",
            )
            finding_history = list(history)
            try:
                merged_findings = self._prior_review_findings_locked(
                    conn,
                    root_id=root_id,
                    task_payload=payload,
                )
            except RoomKernelFenceError as exc:
                review_fences.append(
                    {
                        "reason": "review_finding_history_invalid",
                        "reviewedTaskId": lineage_id,
                        "taskId": task_id,
                        "detail": str(exc)[:1000],
                    }
                )
                merged_findings = []
            if merged_findings:
                # Task payloads are mutable projections.  Append the merged
                # immutable Commit ledger as the final scanner authority so a
                # corrupt/new advisory projection cannot erase an older
                # blocker from the same exact reviewed-Task set.
                finding_history.append(
                    {
                        "taskId": task_id,
                        "payload": {
                            **dict(payload),
                            "reviewFindings": merged_findings,
                        },
                    }
                )
            for attempt in finding_history:
                attempt_payload = attempt.get("payload")
                if not isinstance(attempt_payload, Mapping):
                    continue
                findings = attempt_payload.get("reviewFindings")
                if not isinstance(findings, list):
                    continue
                for finding in findings:
                    if not isinstance(finding, Mapping):
                        continue
                    finding_id = str(
                        finding.get("findingId") or ""
                    ).strip()
                    fingerprint = str(
                        finding.get("fingerprint") or ""
                    ).strip()
                    if not finding_id or not fingerprint:
                        continue
                    key = (finding_id, fingerprint)
                    gate_effect = str(
                        finding.get("gateEffect") or ""
                    )
                    state = str(finding.get("state") or "")
                    prior = finding_by_id.get(finding_id)
                    prior_id_for_fingerprint = (
                        finding_id_by_fingerprint.get(fingerprint)
                    )
                    if (
                        prior is not None
                        and str(prior.get("fingerprint") or "")
                        != fingerprint
                    ) or (
                        prior_id_for_fingerprint is not None
                        and prior_id_for_fingerprint != finding_id
                    ):
                        review_fences.append(
                            {
                                "reason": "review_finding_identity_changed",
                                "reviewedTaskId": lineage_id,
                                "taskId": str(attempt.get("taskId") or ""),
                                "findingId": finding_id,
                            }
                        )
                        continue
                    if prior is not None and any(
                        finding.get(field) != prior.get(field)
                        for field in stable_finding_fields
                    ):
                        review_fences.append(
                            {
                                "reason": "review_finding_content_changed",
                                "reviewedTaskId": lineage_id,
                                "taskId": str(attempt.get("taskId") or ""),
                                "findingId": finding_id,
                            }
                        )
                        continue
                    if (
                        prior is not None
                        and prior.get("gateEffect") == "blocking"
                        and gate_effect != "blocking"
                    ):
                        review_fences.append(
                            {
                                "reason": "review_blocker_downgraded",
                                "reviewedTaskId": lineage_id,
                                "taskId": str(attempt.get("taskId") or ""),
                                "findingId": finding_id,
                            }
                        )
                        # The old blocker deliberately remains in
                        # ``open_findings``.  An advisory disposition can
                        # never pop a blocking lineage.
                        continue
                    finding_by_id[finding_id] = dict(finding)
                    finding_id_by_fingerprint[fingerprint] = finding_id
                    if gate_effect == "blocking":
                        scope = finding.get("scope")
                        criterion_id = (
                            str(scope.get("criterionId") or "").strip()
                            if isinstance(scope, Mapping)
                            else ""
                        )
                        invariant_id = (
                            str(scope.get("invariantId") or "").strip()
                            if isinstance(scope, Mapping)
                            else ""
                        )
                        admissible = (
                            finding.get("impact") in {"critical", "high"}
                            and finding.get("category")
                            in REVIEW_FINDING_BLOCKING_CATEGORIES
                            and (
                                criterion_id
                                in set(
                                    str(value)
                                    for value in payload.get(
                                        "acceptanceCriterionIds",
                                        (),
                                    )
                                )
                                or invariant_id
                                in REVIEW_FINDING_GOVERNANCE_INVARIANTS
                            )
                        )
                        if not admissible:
                            review_fences.append(
                                {
                                    "reason": "review_blocker_not_admissible",
                                    "reviewedTaskId": lineage_id,
                                    "taskId": str(
                                        attempt.get("taskId") or ""
                                    ),
                                    "findingId": finding_id,
                                }
                            )
                        if state in {"open", "contested", "escalated"}:
                            open_findings[key] = dict(finding)
                        elif state == "resolved":
                            response = finding.get("response")
                            has_internal_lineage = (
                                str(
                                    finding.get("firstSeenRevision") or ""
                                )
                                != str(
                                    finding.get("lastCheckedRevision") or ""
                                )
                                and isinstance(response, Mapping)
                                and response.get("findingId") == finding_id
                                and response.get("action") == "fixed"
                                and str(
                                    finding.get("lastCheckedRevision") or ""
                                )
                                == str(
                                    attempt_payload.get(
                                        "reviewTargetRevision"
                                    )
                                    or ""
                                )
                            )
                            if has_internal_lineage and (
                                key in open_findings
                                or str(
                                    finding.get("firstSeenRevision") or ""
                                )
                                != str(
                                    finding.get("lastCheckedRevision") or ""
                                )
                            ):
                                open_findings.pop(key, None)
                            else:
                                review_fences.append(
                                    {
                                        "reason": (
                                            "review_resolution_without_lineage"
                                        ),
                                        "reviewedTaskId": lineage_id,
                                        "findingId": finding_id,
                                    }
                                )
                        elif state == "dismissed":
                            resolution = (
                                self._independent_finding_resolution_locked(
                                    conn,
                                    root_id=root_id,
                                    review_target_revision=str(
                                        finding.get("lastCheckedRevision")
                                        or expected_revision
                                    ),
                                    finding_id=finding_id,
                                )
                            )
                            if resolution is None:
                                review_fences.append(
                                    {
                                        "reason": (
                                            "review_arbiter_resolution_missing"
                                        ),
                                        "reviewedTaskId": lineage_id,
                                        "findingId": finding_id,
                                    }
                                )
                            else:
                                open_findings.pop(key, None)
                        else:
                            review_fences.append(
                                {
                                    "reason": "review_blocker_state_invalid",
                                    "reviewedTaskId": lineage_id,
                                    "findingId": finding_id,
                                    "state": state,
                                }
                            )
                    elif gate_effect == "advisory":
                        if state == "open":
                            open_findings[key] = dict(finding)
                        elif state in {
                            "resolved",
                            "dismissed",
                            "accepted_risk",
                        }:
                            open_findings.pop(key, None)
            for finding in open_findings.values():
                projected = {
                    "taskId": task_id,
                    "reviewedTaskId": lineage_id,
                    "findingId": str(
                        finding.get("findingId") or ""
                    ),
                    "state": str(finding.get("state") or ""),
                    "category": str(
                        finding.get("category") or ""
                    ),
                    "gateEffect": str(
                        finding.get("gateEffect") or ""
                    ),
                }
                if finding.get("gateEffect") == "advisory":
                    review_fences.append(
                        {
                            "reason": "review_advisory_undisposed",
                            **projected,
                        }
                    )
                else:
                    unresolved.append(projected)
        return {
            "reviewFences": review_fences,
            "unresolvedFindings": unresolved,
            "reviewEvidenceMismatches": evidence_mismatches,
        }

    def _review_attempt_governance_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        attempt: Mapping[str, object],
        task_rows: Sequence[sqlite3.Row],
        dispatches_by_task: Mapping[str, Sequence[sqlite3.Row]],
    ) -> dict[str, list[dict[str, object]]]:
        """Validate one scoped Review Task against its exact current target."""

        task_id = str(attempt.get("taskId") or "")
        task_state = str(attempt.get("taskState") or "")
        payload = attempt.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        dispatch = attempt.get("dispatch")
        if not isinstance(dispatch, Mapping):
            dispatch = {}
        commit = attempt.get("commit")
        if not isinstance(commit, Mapping):
            commit = {}
        dispatch_id = str(dispatch.get("dispatchId") or "")
        dispatch_state = str(dispatch.get("state") or "")
        review_state = str(payload.get("reviewState") or "not_required")
        review_fences: list[dict[str, object]] = []
        unresolved_findings: list[dict[str, object]] = []
        evidence_mismatches: list[dict[str, object]] = []

        if not dispatch_id:
            review_fences.append(
                {
                    "reason": (
                        "review_cancelled"
                        if task_state == "cancelled"
                        else "review_dispatch_missing"
                    ),
                    "taskId": task_id,
                    **(
                        {"replacementRequired": True}
                        if task_state == "cancelled"
                        else {}
                    ),
                }
            )
            return {
                "reviewFences": review_fences,
                "unresolvedFindings": unresolved_findings,
                "reviewEvidenceMismatches": evidence_mismatches,
            }
        if dispatch_state in {
            "pending",
            "leased",
            "running",
            "retry_wait",
            "timer_wait",
        }:
            review_fences.append(
                {
                    "reason": "review_dispatch_pending",
                    "taskId": task_id,
                    "dispatchId": dispatch_id,
                    "dispatchState": dispatch_state,
                }
            )
        elif task_state == "cancelled" or dispatch_state in {
            "cancelled",
            "unknown",
            "dead_letter",
        }:
            review_fences.append(
                {
                    "reason": "review_cancelled",
                    "taskId": task_id,
                    "dispatchId": dispatch_id,
                    "replacementRequired": True,
                }
            )
        elif (
            task_state != "completed"
            or review_state not in {"accepted", "accepted_with_notes"}
        ):
            review_fences.append(
                {
                    "reason": (
                        f"review_{review_state}"
                        if review_state != "not_required"
                        else "review_not_accepted"
                    ),
                    "taskId": task_id,
                    "taskState": task_state,
                    "reviewState": review_state,
                }
            )

        reviewed_task_ids = {
            str(value).strip()
            for value in payload.get("reviewOfTaskIds", ())
            if str(value or "").strip()
        }
        authors = {
            str(value).strip()
            for value in payload.get("reviewAuthorParticipantIds", ())
            if str(value or "").strip()
        }
        implementers: set[str] = set()
        for candidate_task in task_rows:
            candidate_task_id = str(candidate_task["task_id"])
            if candidate_task_id not in reviewed_task_ids:
                continue
            try:
                candidate_payload = json.loads(
                    str(candidate_task["payload_json"])
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                candidate_payload = {}
            if isinstance(candidate_payload, Mapping):
                owner_id = str(
                    candidate_payload.get("currentOwnerParticipantId") or ""
                ).strip()
                if owner_id:
                    implementers.add(owner_id)
            for candidate_dispatch in dispatches_by_task.get(
                candidate_task_id,
                (),
            ):
                if str(candidate_dispatch["intent_kind"]) not in {
                    "execute",
                    "revise",
                    "retry",
                }:
                    continue
                participant_id = str(
                    candidate_dispatch["target_participant_id"] or ""
                ).strip()
                if participant_id:
                    implementers.add(participant_id)
        reviewer_id = str(dispatch.get("targetParticipantId") or "").strip()
        if (
            not reviewer_id
            or not authors
            or not reviewed_task_ids
            or reviewer_id in authors
            or reviewer_id in implementers
        ):
            review_fences.append(
                {
                    "reason": "reviewer_not_independent",
                    "taskId": task_id,
                    "reviewerParticipantId": reviewer_id or None,
                    "reviewAuthorParticipantIds": sorted(authors),
                    "implementationParticipantIds": sorted(implementers),
                }
            )

        findings = payload.get("reviewFindings")
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, Mapping):
                    continue
                if (
                    finding.get("gateEffect") == "blocking"
                    and finding.get("state")
                    in {"open", "contested", "escalated"}
                ):
                    unresolved_findings.append(
                        {
                            "taskId": task_id,
                            "findingId": str(finding.get("findingId") or ""),
                            "state": str(finding.get("state") or ""),
                            "category": str(finding.get("category") or ""),
                        }
                    )
                elif (
                    finding.get("gateEffect") == "advisory"
                    and finding.get("state") == "open"
                ):
                    review_fences.append(
                        {
                            "reason": "review_advisory_undisposed",
                            "taskId": task_id,
                            "findingId": str(finding.get("findingId") or ""),
                        }
                    )
        elif task_state == "completed" and review_state in {
            "accepted",
            "accepted_with_notes",
        }:
            review_fences.append(
                {
                    "reason": "review_findings_missing",
                    "taskId": task_id,
                }
            )

        if (
            task_state == "completed"
            and review_state in {"accepted", "accepted_with_notes"}
            and dispatch_state == "committed"
        ):
            expected_revision = str(payload.get("reviewTargetRevision") or "")
            current_revision = ""
            if reviewed_task_ids:
                try:
                    current_revision = self._review_target_revision_locked(
                        conn,
                        root_id=root_id,
                        task_ids=sorted(reviewed_task_ids),
                        review_snapshot=payload,
                    )
                except (RoomKernelFenceError, KeyError, TypeError, ValueError):
                    current_revision = ""
            if not expected_revision or current_revision != expected_revision:
                evidence_mismatches.append(
                    {
                        "reason": "review_revision_mismatch",
                        "taskId": task_id,
                        "expectedRevision": expected_revision or None,
                        "currentRevision": current_revision or None,
                    }
                )
            binding = commit.get("reviewEvidenceBinding")
            gate = commit.get("qualityGateReceipt")
            mismatch_reason = ""
            if not isinstance(binding, Mapping):
                mismatch_reason = "review_evidence_binding_missing"
            elif not isinstance(gate, Mapping):
                mismatch_reason = "review_quality_gate_missing"
            else:
                bound_evidence = {
                    str(value).strip()
                    for value in binding.get("evidenceRefs", ())
                    if str(value or "").strip()
                }
                gate_evidence = {
                    str(value).strip()
                    for item in gate.get("items", ())
                    if isinstance(item, Mapping) and item.get("status") == "pass"
                    for value in item.get("evidenceRefs", ())
                    if str(value or "").strip()
                }
                not_before_ms = int(
                    payload.get("reviewEvidenceNotBeforeMs") or 0
                )
                binding_material = {
                    "reviewTargetRevision": expected_revision,
                    "taskId": task_id,
                    "dispatchId": dispatch_id,
                    "evidenceRefs": sorted(bound_evidence),
                    "notBeforeMs": not_before_ms,
                }
                expected_binding_id = (
                    "review-evidence-binding:"
                    + hashlib.sha256(
                        json.dumps(
                            binding_material,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                )
                try:
                    binding_not_before_ms = int(
                        binding.get("notBeforeMs") or -1
                    )
                except (TypeError, ValueError):
                    binding_not_before_ms = -1
                if (
                    binding.get("schemaVersion")
                    != "wisdom-weasel.review-evidence-binding.v1"
                    or binding.get("reviewTargetRevision")
                    != expected_revision
                    or binding.get("taskId") != task_id
                    or binding.get("dispatchId") != dispatch_id
                    or binding_not_before_ms != not_before_ms
                    or not bound_evidence
                    or bound_evidence != gate_evidence
                    or binding.get("bindingId") != expected_binding_id
                ):
                    mismatch_reason = "review_evidence_binding_mismatch"
            if mismatch_reason:
                evidence_mismatches.append(
                    {
                        "reason": mismatch_reason,
                        "taskId": task_id,
                        "dispatchId": dispatch_id,
                    }
                )

        return {
            "reviewFences": review_fences,
            "unresolvedFindings": unresolved_findings,
            "reviewEvidenceMismatches": evidence_mismatches,
        }

    def _terminal_governance_fences(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object]:
        """Re-derive durable review and workspace obligations for completion.

        This deliberately reads the task/dispatch/commit ledgers in the same
        transaction as ``finalize_root``.  Projected collaboration receipts
        are useful for model context, but they are not authoritative enough to
        decide whether a Root may become terminal.
        """
        pending_interventions = [
            {
                "interventionId": str(row["intervention_id"]),
                "interventionKind": str(row["intervention_kind"]),
                "requiresPlanRevision": bool(row["requires_plan_revision"]),
            }
            for row in conn.execute(
                """SELECT intervention_id,intervention_kind,
                          requires_plan_revision
                   FROM room_interventions
                   WHERE root_id=? AND state='pending_reconciliation'
                   ORDER BY created_at_ms,intervention_id""",
                (root_id,),
            ).fetchall()
        ]
        try:
            decoded_root = json.loads(
                str(self._root_row(conn, root_id)["payload_json"])
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded_root = None
        independent_review_required = (
            decoded_root.get("independentReviewRequired")
            if isinstance(decoded_root, Mapping)
            else None
        )
        review_policy_receipt = self._latest_review_policy_locked(
            conn,
            root_id=root_id,
        )
        review_policy_details = (
            review_policy_receipt.get("details")
            if isinstance(review_policy_receipt, Mapping)
            else None
        )
        review_policy_invalid = (
            not isinstance(independent_review_required, bool)
            or not isinstance(review_policy_details, Mapping)
            or review_policy_details.get("purpose")
            != "independent_review_policy"
            or not isinstance(review_policy_details.get("required"), bool)
            or review_policy_details.get("required")
            is not independent_review_required
        )
        if review_policy_invalid:
            independent_review_required = False

        task_rows = conn.execute(
            """SELECT task_id,state,payload_json,updated_at_ms
               FROM room_kernel_tasks
               WHERE root_id=?
               ORDER BY updated_at_ms,task_id""",
            (root_id,),
        ).fetchall()
        dispatch_rows = conn.execute(
            """SELECT dispatch_id,task_id,intent_kind,state,
                      target_participant_id,
                      created_at_ms,updated_at_ms
               FROM room_kernel_dispatches
               WHERE root_id=?
               ORDER BY created_at_ms,dispatch_id""",
            (root_id,),
        ).fetchall()
        dispatches_by_task: dict[str, list[sqlite3.Row]] = {}
        for dispatch in dispatch_rows:
            dispatches_by_task.setdefault(str(dispatch["task_id"]), []).append(
                dispatch
            )

        pending_integrations: list[dict[str, object]] = []
        review_candidates: list[dict[str, object]] = []
        for task_row in task_rows:
            try:
                payload = json.loads(str(task_row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, Mapping):
                payload = {}
            task_id = str(task_row["task_id"])
            task_state = str(task_row["state"])
            policy = str(payload.get("workspacePolicy") or "")
            integration_state = str(
                payload.get("workspaceIntegrationState") or ""
            )
            integration_ref = str(
                payload.get("workspaceIntegrationRef") or ""
            ).strip()
            workspace_lifecycle = str(
                payload.get("workspaceLifecycleState") or ""
            )
            workspace_cleanup = str(
                payload.get("workspaceCleanupState") or ""
            )
            workspace_attention = payload.get("workspaceAttentionRequired")
            integration_authority_status = "not_applicable"
            if (
                policy == "isolated_writable"
                and workspace_lifecycle != "abandoned"
            ):
                integration_authority_status = str(
                    self._workspace_task_integration_authority_state_locked(
                        conn,
                        root_id=root_id,
                        task_payload=payload,
                    ).get("status")
                    or "invalid"
                )
            if (
                policy == "isolated_writable"
                and workspace_lifecycle != "abandoned"
                and (
                    integration_state != "applied"
                    or not integration_ref
                    or workspace_cleanup not in {"cleaned", "missing"}
                    or workspace_attention is not False
                    or integration_authority_status != "accepted"
                )
            ):
                pending_integrations.append(
                    {
                        "taskId": task_id,
                        "taskState": task_state,
                        "workspaceIntegrationState": integration_state,
                        "hasIntegrationRef": bool(integration_ref),
                    }
                )

            task_dispatches = dispatches_by_task.get(task_id, [])
            review_dispatches = [
                dispatch
                for dispatch in task_dispatches
                if str(dispatch["intent_kind"]) in {"review", "resume"}
            ]
            review_state = str(payload.get("reviewState") or "not_required")
            is_review = (
                payload.get("taskKind") == "review"
                or review_state != "not_required"
            )
            if not is_review:
                continue
            latest_dispatch = (
                max(
                    review_dispatches,
                    key=lambda value: (
                        int(value["updated_at_ms"] or 0),
                        int(value["created_at_ms"] or 0),
                        str(value["dispatch_id"]),
                    ),
                )
                if review_dispatches
                else None
            )
            review_candidates.append(
                {
                    "taskId": task_id,
                    "taskState": task_state,
                    "payload": dict(payload),
                    "updatedAtMs": int(task_row["updated_at_ms"] or 0),
                    "dispatch": latest_dispatch,
                }
            )

        review_candidates.sort(
            key=lambda value: (
                max(
                    int(value["updatedAtMs"]),
                    (
                        int(value["dispatch"]["updated_at_ms"] or 0)
                        if value["dispatch"] is not None
                        else 0
                    ),
                    (
                        int(value["dispatch"]["created_at_ms"] or 0)
                        if value["dispatch"] is not None
                        else 0
                    ),
                ),
                str(value["taskId"]),
            )
        )
        review_fences: list[dict[str, object]] = []
        if review_policy_invalid:
            review_fences.append(
                {
                    "reason": "independent_review_policy_missing_or_invalid",
                }
            )
        elif independent_review_required and not review_candidates:
            review_fences.append(
                {
                    "reason": "independent_review_required",
                }
            )
        unresolved_blocking_findings: list[dict[str, object]] = []
        review_evidence_mismatches: list[dict[str, object]] = []
        for attempt in self._latest_review_attempts_locked(
            conn,
            root_id=root_id,
        ):
            scoped = self._review_attempt_governance_locked(
                conn,
                root_id=root_id,
                attempt=attempt,
                task_rows=task_rows,
                dispatches_by_task=dispatches_by_task,
            )
            for item in scoped["reviewFences"]:
                if item not in review_fences:
                    review_fences.append(item)
            for item in scoped["unresolvedFindings"]:
                if item not in unresolved_blocking_findings:
                    unresolved_blocking_findings.append(item)
            for item in scoped["reviewEvidenceMismatches"]:
                if item not in review_evidence_mismatches:
                    review_evidence_mismatches.append(item)
        authoritative_attempt = self._latest_review_attempt_locked(
            conn,
            root_id=root_id,
        )
        latest_review = review_candidates[-1] if review_candidates else None
        if authoritative_attempt is not None:
            authoritative_dispatch = authoritative_attempt.get("dispatch")
            latest_review = {
                "taskId": str(authoritative_attempt["taskId"]),
                "taskState": str(authoritative_attempt["taskState"]),
                "payload": dict(authoritative_attempt["payload"]),
                "updatedAtMs": int(authoritative_attempt["updatedAtMs"]),
                "dispatch": (
                    {
                        "dispatch_id": str(
                            authoritative_dispatch["dispatchId"]
                        ),
                        "state": str(authoritative_dispatch["state"]),
                        "target_participant_id": str(
                            authoritative_dispatch.get(
                                "targetParticipantId"
                            )
                            or ""
                        ),
                    }
                    if isinstance(authoritative_dispatch, Mapping)
                    else None
                ),
            }
        if latest_review is not None:
            task_id = str(latest_review["taskId"])
            task_state = str(latest_review["taskState"])
            payload = latest_review["payload"]
            review_state = str(payload.get("reviewState") or "not_required")
            latest_dispatch = latest_review["dispatch"]
            dispatch_state = (
                str(latest_dispatch["state"])
                if latest_dispatch is not None
                else ""
            )
            if (
                task_state == "completed"
                and review_state in {"accepted", "accepted_with_notes"}
                and dispatch_state == "committed"
            ):
                reviewer_id = str(
                    latest_dispatch["target_participant_id"]
                    if latest_dispatch is not None
                    else ""
                ).strip()
                authors = {
                    str(value).strip()
                    for value in payload.get(
                        "reviewAuthorParticipantIds",
                        (),
                    )
                    if str(value or "").strip()
                }
                reviewed_task_ids = {
                    str(value).strip()
                    for value in payload.get("reviewOfTaskIds", ())
                    if str(value or "").strip()
                }
                implementers: set[str] = set()
                for candidate_task in task_rows:
                    candidate_task_id = str(candidate_task["task_id"])
                    if candidate_task_id not in reviewed_task_ids:
                        continue
                    try:
                        candidate_payload = json.loads(
                            str(candidate_task["payload_json"])
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        candidate_payload = {}
                    if isinstance(candidate_payload, Mapping):
                        owner_id = str(
                            candidate_payload.get(
                                "currentOwnerParticipantId"
                            )
                            or ""
                        ).strip()
                        if owner_id:
                            implementers.add(owner_id)
                    for candidate_dispatch in dispatches_by_task.get(
                        candidate_task_id,
                        (),
                    ):
                        if str(candidate_dispatch["intent_kind"]) not in {
                            "execute",
                            "revise",
                            "retry",
                        }:
                            continue
                        implementer_id = str(
                            candidate_dispatch["target_participant_id"]
                            or ""
                        ).strip()
                        if implementer_id:
                            implementers.add(implementer_id)
                if (
                    not reviewer_id
                    or not authors
                    or reviewer_id in authors
                    or reviewer_id in implementers
                ):
                    review_fences.append(
                        {
                            "reason": "reviewer_not_independent",
                            "taskId": task_id,
                            "reviewerParticipantId": reviewer_id or None,
                            "reviewAuthorParticipantIds": sorted(authors),
                            "implementationParticipantIds": sorted(
                                implementers
                            ),
                        }
                    )
            cancelled = task_state == "cancelled" or dispatch_state in {
                "cancelled",
                "unknown",
                "dead_letter",
            }
            if cancelled:
                review_fences.append(
                    {
                        "reason": "review_cancelled",
                        "taskId": task_id,
                        "dispatchId": (
                            str(latest_dispatch["dispatch_id"])
                            if latest_dispatch is not None
                            else None
                        ),
                        "replacementRequired": True,
                    }
                )
            elif dispatch_state in {
                "pending",
                "leased",
                "running",
                "retry_wait",
                "timer_wait",
            }:
                review_fences.append(
                    {
                        "reason": "review_dispatch_pending",
                        "taskId": task_id,
                        "dispatchId": str(latest_dispatch["dispatch_id"]),
                        "dispatchState": dispatch_state,
                    }
                )
            elif (
                task_state != "completed"
                or review_state not in {"accepted", "accepted_with_notes"}
            ):
                review_fences.append(
                    {
                        "reason": (
                            f"review_{review_state}"
                            if review_state != "not_required"
                            else "review_not_accepted"
                        ),
                        "taskId": task_id,
                        "taskState": task_state,
                        "reviewState": review_state,
                    }
                )

            findings = payload.get("reviewFindings")
            if isinstance(findings, list):
                for finding in findings:
                    if not isinstance(finding, Mapping):
                        continue
                    if (
                        finding.get("gateEffect") == "blocking"
                        and finding.get("state")
                        in {"open", "contested", "escalated"}
                    ):
                        unresolved_blocking_findings.append(
                            {
                                "taskId": task_id,
                                "findingId": str(
                                    finding.get("findingId") or ""
                                ),
                                "state": str(finding.get("state") or ""),
                                "category": str(
                                    finding.get("category") or ""
                                ),
                            }
                        )
                    elif (
                        finding.get("gateEffect") == "advisory"
                        and finding.get("state") == "open"
                    ):
                        review_fences.append(
                            {
                                "reason": "review_advisory_undisposed",
                                "taskId": task_id,
                                "findingId": str(
                                    finding.get("findingId") or ""
                                ),
                            }
                        )
            elif (
                task_state == "completed"
                and review_state in {"accepted", "accepted_with_notes"}
            ):
                review_fences.append(
                    {
                        "reason": "review_findings_missing",
                        "taskId": task_id,
                    }
                )

            if (
                task_state == "completed"
                and review_state in {"accepted", "accepted_with_notes"}
                and not cancelled
                and dispatch_state == "committed"
            ):
                expected_revision = str(
                    payload.get("reviewTargetRevision") or ""
                )
                raw_target_ids = payload.get("reviewOfTaskIds")
                target_ids = [
                    str(value)
                    for value in (
                        raw_target_ids
                        if isinstance(raw_target_ids, (list, tuple))
                        else ()
                    )
                    if str(value or "").strip()
                ]
                current_revision = ""
                if target_ids:
                    try:
                        current_revision = self._review_target_revision_locked(
                            conn,
                            root_id=root_id,
                            task_ids=target_ids,
                            review_snapshot=payload,
                        )
                    except (RoomKernelFenceError, KeyError, TypeError, ValueError):
                        current_revision = ""
                if not expected_revision or current_revision != expected_revision:
                    review_evidence_mismatches.append(
                        {
                            "reason": "review_revision_mismatch",
                            "taskId": task_id,
                            "expectedRevision": expected_revision or None,
                            "currentRevision": current_revision or None,
                        }
                    )
                commit_row = conn.execute(
                    """SELECT payload_json
                       FROM room_kernel_commits
                       WHERE root_id=? AND dispatch_id=?""",
                    (root_id, str(latest_dispatch["dispatch_id"])),
                ).fetchone()
                commit_payload: Mapping[str, object] = {}
                if commit_row is not None:
                    try:
                        decoded_commit = _room_commit_payload(
                            conn,
                            commit_row["payload_json"],
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        decoded_commit = {}
                    if isinstance(decoded_commit, Mapping):
                        commit_payload = decoded_commit
                binding = commit_payload.get("reviewEvidenceBinding")
                gate = commit_payload.get("qualityGateReceipt")
                mismatch_reason = ""
                if not isinstance(binding, Mapping):
                    mismatch_reason = "review_evidence_binding_missing"
                elif not isinstance(gate, Mapping):
                    mismatch_reason = "review_quality_gate_missing"
                else:
                    bound_refs = binding.get("evidenceRefs")
                    if not isinstance(bound_refs, list):
                        bound_refs = []
                    bound_evidence = {
                        str(value).strip()
                        for value in bound_refs
                        if str(value or "").strip()
                    }
                    gate_items = gate.get("items")
                    if not isinstance(gate_items, list):
                        gate_items = []
                    gate_evidence = {
                        str(value).strip()
                        for item in gate_items
                        if isinstance(item, Mapping)
                        and item.get("status") == "pass"
                        for value in (
                            item.get("evidenceRefs")
                            if isinstance(item.get("evidenceRefs"), list)
                            else ()
                        )
                        if str(value or "").strip()
                    }
                    try:
                        not_before_ms = int(
                            payload.get("reviewEvidenceNotBeforeMs") or 0
                        )
                        binding_not_before_ms = int(
                            binding.get("notBeforeMs") or -1
                        )
                    except (TypeError, ValueError):
                        not_before_ms = 0
                        binding_not_before_ms = -1
                    binding_material = {
                        "reviewTargetRevision": expected_revision,
                        "taskId": task_id,
                        "dispatchId": str(latest_dispatch["dispatch_id"]),
                        "evidenceRefs": sorted(bound_evidence),
                        "notBeforeMs": not_before_ms,
                    }
                    expected_binding_id = (
                        "review-evidence-binding:"
                        + hashlib.sha256(
                            json.dumps(
                                binding_material,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                    )
                    if (
                        binding.get("schemaVersion")
                        != "wisdom-weasel.review-evidence-binding.v1"
                        or binding.get("reviewTargetRevision")
                        != expected_revision
                        or binding.get("taskId") != task_id
                        or binding.get("dispatchId")
                        != str(latest_dispatch["dispatch_id"])
                        or binding_not_before_ms != not_before_ms
                        or not bound_evidence
                        or bound_evidence != gate_evidence
                        or binding.get("bindingId") != expected_binding_id
                    ):
                        mismatch_reason = "review_evidence_binding_mismatch"
                if mismatch_reason:
                    review_evidence_mismatches.append(
                        {
                            "reason": mismatch_reason,
                            "taskId": task_id,
                            "dispatchId": str(latest_dispatch["dispatch_id"]),
                        }
                    )
            elif (
                task_state == "completed"
                and review_state in {"accepted", "accepted_with_notes"}
                and not cancelled
            ):
                review_evidence_mismatches.append(
                    {
                        "reason": "review_dispatch_missing",
                        "taskId": task_id,
                    }
                )

        lineage = self._review_lineage_fences_locked(
            conn,
            root_id=root_id,
        )
        for item in lineage["reviewFences"]:
            if item not in review_fences:
                review_fences.append(item)
        for item in lineage["unresolvedFindings"]:
            if item not in unresolved_blocking_findings:
                unresolved_blocking_findings.append(item)
        for item in lineage["reviewEvidenceMismatches"]:
            if item not in review_evidence_mismatches:
                review_evidence_mismatches.append(item)

        return {
            "pendingInterventions": pending_interventions[:64],
            "pendingIntegrations": pending_integrations[:64],
            "reviewFences": review_fences[:64],
            "unresolvedBlockingFindings": unresolved_blocking_findings[:64],
            "reviewEvidenceMismatches": review_evidence_mismatches[:64],
        }

    @staticmethod
    def _semantic_receipt_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        purpose: str,
        dispatch_id: str = "",
    ) -> dict[str, object] | None:
        rows = conn.execute(
            """SELECT payload_json FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='accepted'
               ORDER BY created_at_ms,receipt_id""",
            (root_id,),
        ).fetchall()
        selected: dict[str, object] | None = None
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            details = payload.get("details")
            if not isinstance(details, Mapping) or details.get("purpose") != purpose:
                continue
            if dispatch_id and str(details.get("reportDispatchId") or "") != dispatch_id:
                continue
            selected = payload
        return selected

    def _report_dispatch_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object] | None:
        receipt = self._semantic_receipt_locked(
            conn,
            root_id=root_id,
            purpose="report_dispatch",
        )
        if receipt is None:
            return None
        details = receipt.get("details")
        if not isinstance(details, Mapping):
            raise RoomKernelFenceError("ReportDispatch receipt is corrupt")
        dispatch_id = _required(
            details.get("reportDispatchId"),
            "report dispatch id",
        )
        task_id = _required(details.get("reportTaskId"), "report task id")
        dispatch = self._dispatch_row(conn, dispatch_id)
        task = self.task(task_id, conn=conn)
        if (
            str(dispatch["root_id"]) != root_id
            or str(dispatch["task_id"]) != task_id
            or str(dispatch["intent_kind"]) != "close"
            or task.get("rootId") != root_id
            or task.get("parentTaskId") is not None
            or task.get("workspacePolicy") != "read_only"
        ):
            raise RoomKernelFenceError(
                "ReportDispatch receipt no longer matches its Task and Dispatch"
            )
        terminal = self._semantic_receipt_locked(
            conn,
            root_id=root_id,
            purpose="reporter_terminal",
            dispatch_id=dispatch_id,
        )
        return {
            "receipt": receipt,
            "task": task,
            "dispatch": _dispatch_payload(dispatch),
            "reporterTerminalReceipt": terminal,
            "created": False,
            "readyForTerminal": (
                str(dispatch["state"]) == "committed"
                and task.get("state") == "completed"
                and terminal is not None
            ),
        }

    def is_report_dispatch(self, dispatch_id: str) -> bool:
        """Return whether a Dispatch owns the Root's unique final report lane."""

        with self._connect() as conn:
            dispatch = self._dispatch_row(conn, _required(dispatch_id, "dispatch_id"))
            report = self._report_dispatch_locked(
                conn,
                root_id=str(dispatch["root_id"]),
            )
            return bool(
                report is not None
                and str(report["dispatch"]["dispatchId"]) == dispatch_id
            )

    def _defined_lane_fences_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object]:
        """Bind report readiness to the work lanes actually split at runtime."""

        definition = self.definition_fence(root_id=root_id, conn=conn)
        if definition is None:
            intake = self._intake_phase_state_locked(
                conn,
                root_id=root_id,
            )
            if intake is not None:
                # A product Root is born with an authoritative intake receipt.
                # Missing room_define state is therefore a broken gate, not a
                # legacy compatibility Root that may proceed to Report.
                return {
                    "definitionRequired": True,
                    "lanePlanDispatchIds": [],
                    "workerDeliveryDispatchIds": [],
                    "fences": [{"reason": "definition_required"}],
                }
            # Compatibility roots created directly through the old typed
            # Kernel API predate authoritative intake and room_define. Only
            # the proven absence of an intake receipt may use this path.
            return {
                "definitionRequired": False,
                "lanePlanDispatchIds": [],
                "workerDeliveryDispatchIds": [],
                "fences": [],
            }
        task_rows = conn.execute(
            """SELECT task_id,state,payload_json
               FROM room_kernel_tasks
               WHERE root_id=? AND parent_task_id IS NOT NULL
               ORDER BY updated_at_ms,task_id""",
            (root_id,),
        ).fetchall()
        lane_ids: list[str] = []
        delivered_ids: list[str] = []
        fences: list[dict[str, object]] = []
        for task_row in task_rows:
            try:
                task_payload = json.loads(str(task_row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                task_payload = {}
            if (
                not isinstance(task_payload, Mapping)
                or task_payload.get("taskKind")
                not in {"work", "integration"}
            ):
                continue
            rows = conn.execute(
                """SELECT * FROM room_kernel_dispatches
                   WHERE root_id=? AND task_id=?
                     AND intent_kind IN ('execute','revise','retry')
                   ORDER BY updated_at_ms,created_at_ms,dispatch_id""",
                (root_id, str(task_row["task_id"])),
            ).fetchall()
            if not rows:
                fences.append(
                    {
                        "reason": "worker_lane_dispatch_missing",
                        "taskId": str(task_row["task_id"]),
                    }
                )
                continue
            row = max(
                rows,
                key=lambda value: (
                    int(value["updated_at_ms"] or 0),
                    int(value["created_at_ms"] or 0),
                    str(value["dispatch_id"]),
                ),
            )
            dispatch_id = str(row["dispatch_id"])
            lane_ids.append(dispatch_id)
            try:
                is_public = (
                    str(row["state"]) == "committed"
                    and self._dispatch_result_is_public(conn, dispatch_id)
                )
            except RoomKernelFenceError:
                is_public = False
            if is_public and str(task_row["state"]) == "completed":
                delivered_ids.append(dispatch_id)
            else:
                fences.append(
                    {
                        "reason": "worker_delivery_missing",
                        "taskId": str(task_row["task_id"]),
                        "dispatchId": dispatch_id,
                        "dispatchState": str(row["state"]),
                        "taskState": str(task_row["state"]),
                    }
                )
        return {
            "definitionRequired": True,
            "lanePlanDispatchIds": lane_ids[:64],
            "workerDeliveryDispatchIds": delivered_ids[:64],
            "fences": fences[:64],
        }

    def _unresolved_dispatch_failures_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Return only failures still authoritative in their retry lineage."""

        failed_rows = conn.execute(
            """SELECT dispatch_id,task_id,state,created_at_ms,updated_at_ms
               FROM room_kernel_dispatches
               WHERE root_id=? AND state IN ('unknown','dead_letter','failed')
               ORDER BY updated_at_ms,created_at_ms,dispatch_id""",
            (root_id,),
        ).fetchall()
        if not failed_rows:
            return []
        receipt_rows = conn.execute(
            """SELECT receipt_id,receipt_kind,command_id,generation,
                      payload_json,created_at_ms
               FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind IN (
                   'accepted','root_retried','runtime_retry_scheduled'
               )
               ORDER BY created_at_ms,rowid""",
            (root_id,),
        ).fetchall()
        latest_retry_by_task: dict[
            str, tuple[int, str]
        ] = {}
        replaced_report_dispatch_ids: set[str] = set()
        control_retry_edges: dict[str, list[dict[str, object]]] = {}
        retry_ordinals: list[int] = []
        retry_ledger_valid = True
        for receipt_row in receipt_rows:
            receipt_kind = str(receipt_row["receipt_kind"])
            try:
                receipt = json.loads(str(receipt_row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                if receipt_kind in {
                    "root_retried",
                    "runtime_retry_scheduled",
                }:
                    retry_ledger_valid = False
                continue
            details = (
                receipt.get("details")
                if isinstance(receipt, Mapping)
                else None
            )
            if not isinstance(details, Mapping):
                if receipt_kind in {
                    "root_retried",
                    "runtime_retry_scheduled",
                }:
                    retry_ledger_valid = False
                continue
            if receipt_kind == "runtime_retry_scheduled":
                if (
                    receipt.get("receiptKind")
                    != "runtime_retry_scheduled"
                    or receipt.get("status") not in {"applied", "noop"}
                ):
                    retry_ledger_valid = False
                    continue
                if receipt.get("status") == "applied":
                    try:
                        retry_ordinal = int(details["retryBudgetUsed"])
                    except (KeyError, TypeError, ValueError):
                        retry_ledger_valid = False
                        continue
                    if retry_ordinal < 1:
                        retry_ledger_valid = False
                        continue
                    retry_ordinals.append(retry_ordinal)
                continue
            if receipt_kind == "root_retried":
                command_id = str(receipt_row["command_id"] or "").strip()
                command_row = (
                    conn.execute(
                        """SELECT root_id,command_kind,payload_json
                           FROM room_kernel_commands WHERE command_id=?""",
                        (command_id,),
                    ).fetchone()
                    if command_id
                    else None
                )
                if command_row is None:
                    retry_ledger_valid = False
                    continue
                try:
                    command_payload = json.loads(
                        str(command_row["payload_json"])
                    )
                    if not isinstance(command_payload, Mapping):
                        retry_ledger_valid = False
                        continue
                    receipt_generation = int(receipt_row["generation"])
                    payload_generation = int(receipt.get("generation", -1))
                    command_generation = int(
                        command_payload.get("generation", -1)
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    retry_ledger_valid = False
                    continue
                if (
                    receipt.get("receiptKind") != "root_retried"
                    or receipt.get("status") != "applied"
                    or receipt.get("commandId") != command_id
                    or payload_generation != receipt_generation
                    or str(command_row["root_id"] or "") != root_id
                    or str(command_row["command_kind"]) != "retry_root"
                    or command_payload.get("commandId") != command_id
                    or command_payload.get("rootId") != root_id
                    or command_payload.get("targetKind") != "root"
                    or command_payload.get("targetId") != root_id
                    or command_generation != receipt_generation
                ):
                    retry_ledger_valid = False
                    continue
                lineage = details.get("retryLineage")
                raw_retried_ids = details.get("retriedDispatchIds")
                raw_retried_task_ids = details.get("retriedTaskIds")
                if (
                    not isinstance(lineage, list)
                    or not isinstance(raw_retried_ids, list)
                    or not isinstance(raw_retried_task_ids, list)
                ):
                    retry_ledger_valid = False
                    continue
                retried_ids = {
                    str(value)
                    for value in raw_retried_ids
                    if str(value or "").strip()
                }
                retried_task_ids = {
                    str(value)
                    for value in raw_retried_task_ids
                    if str(value or "").strip()
                }
                receipt_edges: list[tuple[str, dict[str, object]]] = []
                receipt_ordinals: list[int] = []
                failed_ids: set[str] = set()
                lineage_valid = bool(lineage)
                for item in lineage:
                    if not isinstance(item, Mapping):
                        lineage_valid = False
                        continue
                    failed_dispatch_id = str(
                        item.get("failedDispatchId") or ""
                    ).strip()
                    retried_dispatch_id = str(
                        item.get("retriedDispatchId") or ""
                    ).strip()
                    task_id = str(item.get("taskId") or "").strip()
                    try:
                        failed_attempt = int(
                            item.get("failedDispatchAttempt", -1)
                        )
                        retried_attempt = int(
                            item.get("retriedDispatchAttempt", -1)
                        )
                        root_generation = int(
                            item.get("rootGeneration", -1)
                        )
                        retry_ordinal = int(
                            item.get("rootRetryOrdinal", 0)
                        )
                    except (TypeError, ValueError):
                        lineage_valid = False
                        continue
                    if (
                        not failed_dispatch_id
                        or not retried_dispatch_id
                        or not task_id
                        or failed_dispatch_id == retried_dispatch_id
                        or retried_dispatch_id not in retried_ids
                        or task_id not in retried_task_ids
                        or failed_attempt < 0
                        or retried_attempt != failed_attempt + 1
                        or root_generation != receipt_generation
                        or retry_ordinal < 1
                    ):
                        lineage_valid = False
                        continue
                    if (
                        failed_dispatch_id in failed_ids
                        or any(
                            edge[1]["retriedDispatchId"]
                            == retried_dispatch_id
                            for edge in receipt_edges
                        )
                    ):
                        lineage_valid = False
                        continue
                    failed_ids.add(failed_dispatch_id)
                    receipt_ordinals.append(retry_ordinal)
                    receipt_edges.append(
                        (
                            failed_dispatch_id,
                            {
                                "commandId": command_id,
                                "failedAttempt": failed_attempt,
                                "retriedDispatchId": retried_dispatch_id,
                                "retriedAttempt": retried_attempt,
                                "taskId": task_id,
                                "generation": root_generation,
                                "createdAtMs": int(
                                    receipt_row["created_at_ms"] or 0
                                ),
                            },
                        )
                    )
                if (
                    len(receipt_edges) != len(lineage)
                    or len(receipt_edges) != len(retried_ids)
                    or len(receipt_edges) != len(retried_task_ids)
                    or {
                        str(edge[1]["retriedDispatchId"])
                        for edge in receipt_edges
                    }
                    != retried_ids
                    or {
                        str(edge[1]["taskId"])
                        for edge in receipt_edges
                    }
                    != retried_task_ids
                ):
                    lineage_valid = False
                if not lineage_valid:
                    retry_ledger_valid = False
                    continue
                retry_ordinals.extend(receipt_ordinals)
                for failed_dispatch_id, edge in receipt_edges:
                    control_retry_edges.setdefault(
                        failed_dispatch_id,
                        [],
                    ).append(edge)
                continue
            purpose = str(details.get("purpose") or "")
            if purpose == "workspace_retry":
                task_id = str(
                    details.get("childTaskId") or ""
                ).strip()
                dispatch_id = str(
                    details.get("childDispatchId") or ""
                ).strip()
                if task_id and dispatch_id:
                    latest_retry_by_task[task_id] = (
                        int(receipt.get("createdAtMs") or 0),
                        dispatch_id,
                    )
            elif purpose == "report_dispatch":
                replaced = str(
                    details.get("replacesReportDispatchId") or ""
                ).strip()
                if replaced:
                    replaced_report_dispatch_ids.add(replaced)

        limits = conn.execute(
            "SELECT retry_used FROM room_kernel_root_limits WHERE root_id=?",
            (root_id,),
        ).fetchone()
        retry_used = int(limits["retry_used"]) if limits is not None else -1
        if (
            not retry_ledger_valid
            or retry_ordinals != list(range(1, retry_used + 1))
        ):
            # A retry Receipt can suppress an earlier durable failure only
            # when every consumed retry-budget ordinal is accounted for in
            # persisted order. Any tamper, duplicate, gap, or legacy partial
            # lineage leaves all failures authoritative.
            control_retry_edges.clear()

        def control_retry_resolved(
            failed_dispatch_id: str,
            *,
            visited: set[str],
        ) -> bool:
            if failed_dispatch_id in visited:
                return False
            source = conn.execute(
                """SELECT d.*,t.state AS task_state
                   FROM room_kernel_dispatches d
                   JOIN room_kernel_tasks t ON t.task_id=d.task_id
                   WHERE d.root_id=? AND d.dispatch_id=?""",
                (root_id, failed_dispatch_id),
            ).fetchone()
            if source is None:
                return False
            try:
                source_payload = json.loads(str(source["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
            if not isinstance(source_payload, Mapping):
                return False
            for edge in reversed(
                control_retry_edges.get(failed_dispatch_id, ())
            ):
                retry_dispatch_id = str(edge["retriedDispatchId"])
                retry = conn.execute(
                    """SELECT d.*,t.state AS task_state
                       FROM room_kernel_dispatches d
                       JOIN room_kernel_tasks t ON t.task_id=d.task_id
                       WHERE d.root_id=? AND d.dispatch_id=?""",
                    (root_id, retry_dispatch_id),
                ).fetchone()
                if retry is None:
                    continue
                try:
                    retry_payload = json.loads(str(retry["payload_json"]))
                    if not isinstance(retry_payload, Mapping):
                        continue
                    source_attempt = int(source_payload.get("attempt") or 0)
                    retry_attempt = int(retry_payload.get("attempt") or 0)
                    source_generation = int(source["generation"])
                    retry_generation = int(retry["generation"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if (
                    str(source["task_id"]) != str(edge["taskId"])
                    or str(retry["task_id"]) != str(edge["taskId"])
                    or source_generation != int(edge["generation"])
                    or retry_generation != int(edge["generation"])
                    or source_attempt != int(edge["failedAttempt"])
                    or retry_attempt != int(edge["retriedAttempt"])
                    or retry_payload.get("triggerId") != edge["commandId"]
                    or int(edge["createdAtMs"])
                    < int(source["updated_at_ms"] or 0)
                    or int(retry["created_at_ms"] or 0)
                    < int(source["updated_at_ms"] or 0)
                ):
                    continue
                retry_state = str(retry["state"])
                if (
                    retry_state == "committed"
                    and str(retry["task_state"]) == "completed"
                ):
                    return True
                if retry_state in {"unknown", "dead_letter", "failed"} and (
                    control_retry_resolved(
                        retry_dispatch_id,
                        visited={*visited, failed_dispatch_id},
                    )
                ):
                    return True
            return False

        unresolved: list[dict[str, object]] = []
        for failed in failed_rows:
            dispatch_id = str(failed["dispatch_id"])
            task_id = str(failed["task_id"])
            if dispatch_id in replaced_report_dispatch_ids:
                continue
            if control_retry_resolved(dispatch_id, visited=set()):
                continue
            retry = latest_retry_by_task.get(task_id)
            if retry is not None:
                receipt_created_at, retry_dispatch_id = retry
                retry_row = conn.execute(
                    """SELECT d.state,d.created_at_ms,t.state AS task_state
                       FROM room_kernel_dispatches d
                       JOIN room_kernel_tasks t ON t.task_id=d.task_id
                       WHERE d.root_id=? AND d.task_id=?
                         AND d.dispatch_id=?""",
                    (root_id, task_id, retry_dispatch_id),
                ).fetchone()
                if (
                    retry_dispatch_id != dispatch_id
                    and retry_row is not None
                    and receipt_created_at
                    >= int(failed["updated_at_ms"] or 0)
                    and int(retry_row["created_at_ms"] or 0)
                    >= int(failed["created_at_ms"] or 0)
                    and str(retry_row["state"]) == "committed"
                    and str(retry_row["task_state"]) == "completed"
                ):
                    continue
            unresolved.append(
                {
                    "dispatchId": dispatch_id,
                    "taskId": task_id,
                    "state": str(failed["state"]),
                }
            )
        return unresolved

    def _report_readiness_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object]:
        root = self._root_row(conn, root_id)
        existing = self._report_dispatch_locked(conn, root_id=root_id)
        replaceable_report: dict[str, object] | None = None
        if existing is not None:
            existing_dispatch = existing.get("dispatch")
            existing_task = existing.get("task")
            dispatch_state = (
                str(existing_dispatch.get("state") or "")
                if isinstance(existing_dispatch, Mapping)
                else ""
            )
            task_state = (
                str(existing_task.get("state") or "")
                if isinstance(existing_task, Mapping)
                else ""
            )
            if dispatch_state in {
                "failed",
                "unknown",
                "dead_letter",
                "cancelled",
            } or task_state in {"failed", "cancelled"}:
                replaceable_report = dict(existing)
            else:
                return {"ready": True, "existing": existing}
        active = int(
            conn.execute(
                f"SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id=? "
                f"AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})",
                (root_id, *_ACTIVE_DISPATCH_STATES),
            ).fetchone()[0]
        )
        unresolved_failures = self._unresolved_dispatch_failures_locked(
            conn,
            root_id=root_id,
        )
        if replaceable_report is not None:
            replaced_dispatch = replaceable_report.get("dispatch")
            replaced_dispatch_id = (
                str(replaced_dispatch.get("dispatchId") or "")
                if isinstance(replaced_dispatch, Mapping)
                else ""
            )
            unresolved_failures = [
                failure
                for failure in unresolved_failures
                if failure.get("dispatchId") != replaced_dispatch_id
            ]
        unknown = len(unresolved_failures)
        open_outbox = int(
            conn.execute(
                "SELECT COUNT(*) FROM room_kernel_outbox WHERE root_id=? "
                "AND state IN ('pending','leased','running','retry_wait','timer_wait')",
                (root_id,),
            ).fetchone()[0]
        )
        active_leases = int(
            conn.execute(
                "SELECT COUNT(*) FROM room_kernel_leases WHERE root_id=? "
                "AND state='active'",
                (root_id,),
            ).fetchone()[0]
        )
        replaceable_task_id = ""
        if replaceable_report is not None:
            replaced_task = replaceable_report.get("task")
            if isinstance(replaced_task, Mapping):
                replaceable_task_id = str(
                    replaced_task.get("taskId") or ""
                ).strip()
        open_tasks = int(
            conn.execute(
                f"SELECT COUNT(*) FROM room_kernel_tasks WHERE root_id=? "
                f"AND state NOT IN ({','.join('?' for _ in _TERMINAL_TASK_STATES)}) "
                "AND (?='' OR task_id!=?)",
                (
                    root_id,
                    *_TERMINAL_TASK_STATES,
                    replaceable_task_id,
                    replaceable_task_id,
                ),
            ).fetchone()[0]
        )
        expected = set(json.loads(str(root["acceptance_criteria_json"])))
        covered = set(json.loads(str(root["covered_criteria_json"])))
        missing = sorted(expected - covered)
        governance = self._terminal_governance_fences(conn, root_id=root_id)
        lane = self._defined_lane_fences_locked(conn, root_id=root_id)
        proven = self._acceptance_evidence(conn, root_id, expected)
        unproven = sorted(expected - set(proven))
        reasons: list[str] = []
        if str(root["state"]) not in {"running", "waiting"} and not (
            replaceable_report is not None
            and str(root["state"]) == "blocked"
        ):
            reasons.append("root_not_reportable")
        if active or unknown or open_outbox or active_leases or open_tasks:
            reasons.append("root_not_quiescent")
        if governance["pendingInterventions"]:
            reasons.append("user_intervention_pending_reconciliation")
        elif governance["reviewFences"]:
            reasons.append(str(governance["reviewFences"][0].get("reason")))
        elif governance["unresolvedBlockingFindings"]:
            reasons.append("review_blocking_findings")
        elif governance["reviewEvidenceMismatches"]:
            reasons.append(
                str(governance["reviewEvidenceMismatches"][0].get("reason"))
            )
        elif governance["pendingIntegrations"]:
            reasons.append("workspace_integration_pending")
        if lane["fences"]:
            reasons.append(str(lane["fences"][0].get("reason")))
        if missing:
            reasons.append("acceptance_coverage_missing")
        if not expected or unproven:
            reasons.append("acceptance_evidence_missing")
        return {
            "ready": not reasons,
            "reason": reasons[0] if reasons else None,
            "reasons": list(dict.fromkeys(reasons)),
            "activeDispatches": active,
            "unknownDispatches": unknown,
            "unresolvedDispatchFailures": unresolved_failures[:64],
            "replaceableReport": replaceable_report,
            "openOutbox": open_outbox,
            "activeLeases": active_leases,
            "openTasks": open_tasks,
            "missingAcceptanceCriteria": missing,
            "unprovenAcceptanceCriteria": unproven,
            "governance": governance,
            "lanePlan": lane,
        }

    def report_readiness(self, root_id: str) -> dict[str, object]:
        with self._connect() as conn:
            return self._report_readiness_locked(
                conn,
                root_id=_required(root_id, "root_id"),
            )

    def ensure_report_dispatch(
        self,
        root_id: str,
        *,
        reporter_participant_id: str,
        reporter_session_id: str,
        workspace: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Create the Root's one fresh read-only ReportDispatch atomically."""

        with self._connect(immediate=True) as conn:
            root = self._root_row(conn, _required(root_id, "root_id"))
            readiness = self._report_readiness_locked(conn, root_id=root_id)
            existing = readiness.get("existing")
            if isinstance(existing, Mapping):
                return dict(existing)
            if readiness.get("ready") is not True:
                return {
                    "receipt": self._receipt(
                        conn,
                        root_id=root_id,
                        command_id=None,
                        receipt_kind="rejected",
                        status="rejected",
                        generation=int(root["generation"]),
                        details={
                            "reason": readiness.get("reason"),
                            "reportReadiness": readiness,
                        },
                        now_ms=now_ms,
                    ),
                    "task": None,
                    "dispatch": None,
                    "reporterTerminalReceipt": None,
                    "created": False,
                    "readyForTerminal": False,
                }
            root_payload = json.loads(str(root["payload_json"]))
            expected_reporter = str(
                root_payload.get("reporterParticipantId")
                or root_payload.get("facilitatorParticipantId")
                or ""
            ).strip()
            reporter_id = _required(
                reporter_participant_id,
                "reporter participant id",
            )
            if reporter_id != expected_reporter:
                raise RoomKernelFenceError(
                    "ReportDispatch target does not match the Root Reporter"
                )
            if workspace.get("workspacePolicy") != "read_only":
                raise RoomKernelFenceError(
                    "ReportDispatch requires a fresh read_only workspace snapshot"
                )
            replaceable_report = readiness.get("replaceableReport")
            replaced_dispatch_id = ""
            replaced_task_id = ""
            report_attempt = 0
            if isinstance(replaceable_report, Mapping):
                replaced_dispatch = replaceable_report.get("dispatch")
                replaced_task = replaceable_report.get("task")
                replaced_receipt = replaceable_report.get("receipt")
                replaced_details = (
                    replaced_receipt.get("details")
                    if isinstance(replaced_receipt, Mapping)
                    else None
                )
                replaced_dispatch_id = (
                    str(replaced_dispatch.get("dispatchId") or "")
                    if isinstance(replaced_dispatch, Mapping)
                    else ""
                )
                replaced_task_id = (
                    str(replaced_task.get("taskId") or "")
                    if isinstance(replaced_task, Mapping)
                    else ""
                )
                report_attempt = (
                    int(replaced_details.get("reportAttempt") or 0) + 1
                    if isinstance(replaced_details, Mapping)
                    else 1
                )
                if not replaced_dispatch_id or not replaced_task_id:
                    raise RoomKernelFenceError(
                        "replaceable ReportDispatch lost its identity"
                    )
                exact_obsolete = conn.execute(
                    """SELECT d.state AS dispatch_state,
                              d.task_id,t.state AS task_state
                       FROM room_kernel_dispatches d
                       JOIN room_kernel_tasks t ON t.task_id=d.task_id
                       WHERE d.root_id=? AND d.dispatch_id=?
                         AND t.root_id=? AND t.task_id=?""",
                    (
                        root_id,
                        replaced_dispatch_id,
                        root_id,
                        replaced_task_id,
                    ),
                ).fetchone()
                if (
                    exact_obsolete is None
                    or str(exact_obsolete["task_id"]) != replaced_task_id
                    or str(exact_obsolete["dispatch_state"])
                    not in {
                        "failed",
                        "unknown",
                        "dead_letter",
                        "cancelled",
                    }
                ):
                    raise RoomKernelFenceError(
                        "replaceable ReportDispatch is no longer terminal"
                    )
                # Historical builds left a failed Report Task blocked.  Seal
                # that exact obsolete Task in the same transaction that
                # creates its replacement; no other blocked work is consumed.
                conn.execute(
                    """UPDATE room_kernel_tasks
                       SET state='failed',updated_at_ms=?
                       WHERE root_id=? AND task_id=?
                         AND state NOT IN ('completed','failed','cancelled')""",
                    (int(now_ms), root_id, replaced_task_id),
                )
            report_identity_parts = (
                (root_id, str(root["generation"]))
                if report_attempt == 0
                else (
                    root_id,
                    str(root["generation"]),
                    str(report_attempt),
                )
            )
            report_task_id = _stable_id(
                "room-report-task",
                *report_identity_parts,
            )
            report_dispatch_id = _stable_id(
                "room-report-dispatch",
                *report_identity_parts,
            )
            task_rows = conn.execute(
                """SELECT payload_json FROM room_kernel_tasks
                   WHERE root_id=? ORDER BY updated_at_ms,task_id""",
                (root_id,),
            ).fetchall()
            requirement_ids: list[str] = []
            work_item_ids: list[str] = []
            for task_row in task_rows:
                task_payload = json.loads(str(task_row["payload_json"]))
                work_item_id = str(
                    task_payload.get("workItemId") or ""
                ).strip()
                if work_item_id and work_item_id not in work_item_ids:
                    work_item_ids.append(work_item_id)
                for value in task_payload.get("requirementItemIds") or []:
                    normalized = str(value).strip()
                    if normalized and normalized not in requirement_ids:
                        requirement_ids.append(normalized)
            criteria = [
                str(value)
                for value in json.loads(str(root["acceptance_criteria_json"]))
                if str(value).strip()
            ]
            evidence = self._acceptance_evidence(conn, root_id, set(criteria))
            evidence_refs = sorted(
                {
                    ref
                    for refs in evidence.values()
                    for ref in refs
                    if str(ref).strip()
                }
            )
            task_payload = {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": report_task_id,
                "rootId": root_id,
                "parentTaskId": None,
                "taskKind": "report",
                "currentOwnerParticipantId": reporter_id,
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "objective": (
                    "结合伙伴们已经完成的工作、验收证据和复核结论，保持你自己的伙伴人格，"
                    "向用户给出一份自然、简洁且诚实的最终回复。不要暴露内部协议、编号或运行细节。"
                ),
                "expectedOutput": (
                    "一条自然语言最终回复，说明结果、已验证内容和仍需用户知道的风险；"
                    "不要冒充其他伙伴，也不要使用统一主持人口吻。"
                ),
                "requirementItemIds": requirement_ids,
                "acceptanceCriterionIds": criteria,
                "contextEvidenceRefs": evidence_refs,
                "invitationId": None,
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "reviewState": "not_required",
                "revision": 0,
                "state": "active",
                **dict(workspace),
            }
            if len(work_item_ids) == 1:
                task_payload["workItemId"] = work_item_ids[0]
            validate_kernel_contract("roomTask", task_payload)
            latest_dispatch = conn.execute(
                """SELECT payload_json FROM room_kernel_dispatches
                   WHERE root_id=? ORDER BY created_at_ms DESC,dispatch_id DESC
                   LIMIT 1""",
                (root_id,),
            ).fetchone()
            if latest_dispatch is None:
                raise RoomKernelFenceError(
                    "ReportDispatch requires a completed execution lane"
                )
            latest_payload = json.loads(str(latest_dispatch["payload_json"]))
            max_epoch = max(
                (
                    int(
                        json.loads(str(row["payload_json"])).get(
                            "capabilityEpoch", -1
                        )
                    )
                    for row in conn.execute(
                        "SELECT payload_json FROM room_kernel_dispatches WHERE root_id=?",
                        (root_id,),
                    ).fetchall()
                ),
                default=-1,
            )
            dispatch_payload = {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": report_dispatch_id,
                "rootId": root_id,
                "taskId": report_task_id,
                "parentDispatchId": None,
                "generation": int(root["generation"]),
                "hopCount": 0,
                "depth": 0,
                "budgetCost": 0,
                "targetSessionId": _required(
                    reporter_session_id,
                    "reporter session id",
                ),
                "targetParticipantId": reporter_id,
                "triggerId": _stable_id(
                    "room-report-trigger",
                    *report_identity_parts,
                ),
                "intentKind": "close",
                "idempotencyKey": _stable_id(
                    "room-report",
                    *report_identity_parts,
                ),
                "attempt": report_attempt,
                "capabilityEpoch": max_epoch + 1,
                "runtimeProfileRevision": _required(
                    latest_payload.get("runtimeProfileRevision"),
                    "runtime profile revision",
                ),
                "state": "pending",
            }
            validate_kernel_contract("dispatchEnvelope", dispatch_payload)
            self._insert_task(conn, task_payload, now_ms=now_ms)
            dispatch, created = self._enqueue_dispatch(
                conn,
                dispatch_payload,
                shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
                now_ms=now_ms,
            )
            if not created:
                raise RoomKernelFenceError(
                    "ReportDispatch identity existed without its semantic receipt"
                )
            if report_attempt:
                conn.execute(
                    "UPDATE room_kernel_roots SET state='running',updated_at_ms=? "
                    "WHERE root_id=? AND state='blocked'",
                    (int(now_ms), root_id),
                )
            lane = readiness["lanePlan"]
            receipt = self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "purpose": "report_dispatch",
                    "reportTaskId": report_task_id,
                    "reportDispatchId": report_dispatch_id,
                    "reporterParticipantId": reporter_id,
                    "reportAttempt": report_attempt,
                    "replacesReportDispatchId": (
                        replaced_dispatch_id or None
                    ),
                    "replacesReportTaskId": replaced_task_id or None,
                    "lanePlanDispatchIds": list(lane["lanePlanDispatchIds"]),
                    "workerDeliveryDispatchIds": list(
                        lane["workerDeliveryDispatchIds"]
                    ),
                },
                now_ms=now_ms,
            )
            return {
                "receipt": receipt,
                "task": task_payload,
                "dispatch": dispatch,
                "reporterTerminalReceipt": None,
                "created": True,
                "readyForTerminal": False,
            }

    def finalize_root(self, root_id: str, *, now_ms: int, delivery_gate_preview: Mapping[str, object] | None = None) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            root = self._root_row(conn, root_id)
            if root["terminal_receipt_id"]:
                terminal = conn.execute(
                    "SELECT payload_json FROM room_kernel_receipts WHERE receipt_id = ?",
                    (root["terminal_receipt_id"],),
                ).fetchone()
                if terminal is None:
                    raise RoomKernelFenceError(
                        "completed Root is missing its canonical terminal receipt"
                    )
                return json.loads(str(terminal["payload_json"]))
            report = (
                self._report_dispatch_locked(conn, root_id=root_id)
                if kernel_owns_room_execution(self.mode)
                else None
            )
            active = int(conn.execute(f"SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id = ? AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})", (root_id, *_ACTIVE_DISPATCH_STATES)).fetchone()[0])
            unknown = len(
                self._unresolved_dispatch_failures_locked(
                    conn,
                    root_id=root_id,
                )
            )
            open_outbox = int(conn.execute("SELECT COUNT(*) FROM room_kernel_outbox WHERE root_id = ? AND state IN ('pending','leased','running','retry_wait','timer_wait')", (root_id,)).fetchone()[0])
            active_leases = int(conn.execute("SELECT COUNT(*) FROM room_kernel_leases WHERE root_id = ? AND state = 'active'", (root_id,)).fetchone()[0])
            open_tasks = int(conn.execute(f"SELECT COUNT(*) FROM room_kernel_tasks WHERE root_id = ? AND state NOT IN ({','.join('?' for _ in _TERMINAL_TASK_STATES)})", (root_id, *_TERMINAL_TASK_STATES)).fetchone()[0])
            expected = set(json.loads(str(root["acceptance_criteria_json"])))
            covered = set(json.loads(str(root["covered_criteria_json"])))
            missing = sorted(expected - covered)
            governance = self._terminal_governance_fences(
                conn,
                root_id=root_id,
            )
            pending_interventions = governance["pendingInterventions"]
            review_fences = governance["reviewFences"]
            unresolved_findings = governance["unresolvedBlockingFindings"]
            evidence_mismatches = governance["reviewEvidenceMismatches"]
            pending_integrations = governance["pendingIntegrations"]
            # A Root without acceptance criteria cannot be delivered by vacuous
            # truth, and a covered criterion is only real when a durable Commit
            # carries a passing quality gate item with at least one evidence
            # ref. `covered_criteria_json` is bookkeeping; the Commits are the
            # authority, so terminal transition re-derives them here.
            proven = self._acceptance_evidence(conn, root_id, expected)
            unproven = sorted(expected - set(proven))
            if pending_interventions:
                governance_reason = "user_intervention_pending_reconciliation"
            elif review_fences:
                governance_reason = str(review_fences[0].get("reason"))
            elif unresolved_findings:
                governance_reason = "review_blocking_findings"
            elif evidence_mismatches:
                governance_reason = str(
                    evidence_mismatches[0].get("reason")
                )
            elif pending_integrations:
                governance_reason = "workspace_integration_pending"
            else:
                governance_reason = None
            completion = evaluate_completion(
                CompletionFacts(
                    governance_reason=governance_reason,
                    active_dispatches=active,
                    unknown_dispatches=unknown,
                    open_outbox=open_outbox,
                    active_leases=active_leases,
                    # Covered criteria are bookkeeping, but an incomplete
                    # bookkeeping fence still means the Root is not quiescent.
                    open_tasks=open_tasks + (1 if missing else 0),
                    acceptance_criteria=tuple(sorted(expected)),
                    proven_acceptance_criteria=tuple(sorted(proven)),
                    reporter_terminal_ready=(
                        not kernel_owns_room_execution(self.mode)
                        or (
                            isinstance(report, Mapping)
                            and report.get("readyForTerminal") is True
                        )
                    ),
                )
            )
            if not completion.ready:
                details: dict[str, object] = {
                    "reason": str(completion.reason or "completion_blocked"),
                    "activeDispatches": active,
                    "unknownDispatches": unknown,
                    "openOutbox": open_outbox,
                    "activeLeases": active_leases,
                    "openTasks": open_tasks,
                    "missingAcceptanceCriteria": missing,
                }
                if completion.reason == "acceptance_evidence_missing":
                    details.update(
                        {
                            "acceptanceCriteria": sorted(expected),
                            "unprovenAcceptanceCriteria": unproven,
                        }
                    )
                if completion.reason == "reporter_terminal_missing":
                    details["reportDispatchId"] = (
                        report["dispatch"]["dispatchId"]
                        if isinstance(report, Mapping)
                        and isinstance(report.get("dispatch"), Mapping)
                        else None
                    )
                if governance_reason:
                    details["governance"] = governance
                return self._receipt(
                    conn,
                    root_id=root_id,
                    command_id=None,
                    receipt_kind="rejected",
                    status="rejected",
                    generation=int(root["generation"]),
                    details=details,
                    now_ms=now_ms,
                )
            if self.enforce_test_delivery_gate:
                gate_preview = delivery_gate_preview or {}
                if (
                    gate_preview.get("rootId") != root_id
                    or int(gate_preview.get("generation", -1)) != int(root["generation"])
                    or gate_preview.get("environment") != "room-v2-test"
                    or gate_preview.get("mode") != "room_v2_test_enforce_preview"
                    or gate_preview.get("terminalAllowed") is not True
                    or gate_preview.get("valid") is not True
                    or bool(gate_preview.get("validationReasons"))
                ):
                    return self._receipt(conn, root_id=root_id, command_id=None, receipt_kind="rejected", status="rejected", generation=int(root["generation"]), details={"reason": "delivery_gate_rejected", "previewReceiptId": gate_preview.get("previewReceiptId"), "validationReasons": list(gate_preview.get("validationReasons") or ["delivery_gate_preview_missing_or_invalid"])}, now_ms=now_ms)
            gate = conn.execute(
                """SELECT * FROM room_v2_delivery_gate_receipts
                   WHERE root_id = ? ORDER BY created_at_ms DESC, gate_receipt_id DESC LIMIT 1""",
                (root_id,),
            ).fetchone()
            delivery_observation = {
                "gateObservationRef": str(gate["gate_receipt_id"]) if gate is not None else None,
                "gateStatus": str(gate["gate_status"]) if gate is not None else "not_observed",
                "mode": str(gate["mode"]) if gate is not None else "observe_warn",
                "enforcementApplied": self.enforce_test_delivery_gate,
                "reasons": json.loads(str(gate["reasons_json"])) if gate is not None else ["delivery_gate_not_observed"],
            }
            conn.execute(
                """UPDATE room_v2_dispatch_requirement_bindings
                   SET state = 'terminal', gate_observation_ref = ?, updated_at_ms = ?
                   WHERE root_id = ? AND state = 'active'""",
                (delivery_observation["gateObservationRef"], int(now_ms), root_id),
            )
            receipt = self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind="terminal",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "quiescent": True,
                    "acceptanceSatisfied": True,
                    "finalReportReceiptId": (
                        report["reporterTerminalReceipt"]["receiptId"]
                        if isinstance(report, Mapping)
                        and isinstance(
                            report.get("reporterTerminalReceipt"), Mapping
                        )
                        else None
                    ),
                    "acceptanceEvidenceRefCounts": {
                        criterion_id: len(refs)
                        for criterion_id, refs in sorted(proven.items())
                    },
                    "governance": governance,
                    "deliveryGateObservation": delivery_observation,
                },
                now_ms=now_ms,
            )
            conn.execute("UPDATE room_kernel_roots SET state = 'completed', terminal_receipt_id = ?, updated_at_ms = ? WHERE root_id = ?", (receipt["receiptId"], int(now_ms), root_id))
            RoomDomainEventRepository.append(
                conn,
                past_tense_event(
                    kind="root_completed",
                    room_id=str(root["room_id"]),
                    root_id=root_id,
                    entity_id=root_id,
                    generation=int(root["generation"]),
                    idempotency_key=str(receipt["receiptId"]),
                    payload={
                        "terminalReceiptId": str(receipt["receiptId"]),
                        "finalReportReceiptId": receipt["details"].get(
                            "finalReportReceiptId"
                        ),
                    },
                ),
                created_at_ms=int(now_ms),
            )
            return receipt

    def _receipt(self, conn: sqlite3.Connection, *, root_id: str | None, command_id: str | None, receipt_kind: str, status: str, generation: int, details: Mapping[str, object], now_ms: int) -> dict[str, object]:
        receipt_id = _stable_id("room-receipt", root_id or "global", receipt_kind, status, _json(details), str(now_ms))
        payload = {"schemaVersion": KERNEL_RECEIPT_SCHEMA_VERSION, "receiptId": receipt_id, "rootId": root_id, "commandId": command_id, "receiptKind": receipt_kind, "status": status, "generation": generation, "details": dict(details), "createdAtMs": int(now_ms)}
        validate_kernel_contract("kernelReceipt", payload)
        conn.execute("INSERT OR IGNORE INTO room_kernel_receipts(receipt_id, root_id, command_id, receipt_kind, status, generation, payload_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (receipt_id, root_id, command_id, receipt_kind, status, generation, _json(payload), int(now_ms)))
        return payload

    def _record_review_policy_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        required: bool,
        source: str,
        generation: int,
        now_ms: int,
        dispatch_id: str = "",
    ) -> dict[str, object]:
        return self._receipt(
            conn,
            root_id=root_id,
            command_id=None,
            receipt_kind="accepted",
            status="applied",
            generation=generation,
            details={
                "purpose": "independent_review_policy",
                "required": bool(required),
                "source": _required(source, "review policy source"),
                "dispatchId": str(dispatch_id or ""),
            },
            now_ms=now_ms,
        )

    def _latest_review_policy_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object] | None:
        rows = conn.execute(
            """SELECT payload_json FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='accepted'
               ORDER BY created_at_ms DESC,rowid DESC""",
            (root_id,),
        ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            details = payload.get("details") if isinstance(payload, dict) else None
            if (
                isinstance(details, Mapping)
                and details.get("purpose") == "independent_review_policy"
            ):
                return payload
        return None

    @staticmethod
    def _intake_phase_state_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object] | None:
        rows = conn.execute(
            """SELECT payload_json FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='accepted'
               ORDER BY created_at_ms DESC,rowid DESC""",
            (_required(root_id, "root_id"),),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RoomKernelFenceError(
                    "Room Root accepted receipt payload is corrupt"
                ) from exc
            if not isinstance(payload, Mapping):
                raise RoomKernelFenceError(
                    "Room Root accepted receipt payload is corrupt"
                )
            details = payload.get("details")
            if (
                isinstance(details, Mapping)
                and details.get("purpose") == "intake_phase"
            ):
                return {"receipt": payload, **dict(details)}
        return None

    def _record_intake_phase_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        phase: str,
        clarification_occurred: bool,
        source: str,
        generation: int,
        details: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        if phase not in {
            "aligning",
            "clarifying",
            "awaiting_start",
            "execution_ready",
            "executing",
        }:
            raise ValueError("unsupported Room intake phase")
        return self._receipt(
            conn,
            root_id=root_id,
            command_id=None,
            receipt_kind="accepted",
            status="applied",
            generation=generation,
            details=_authoritative_receipt_details(
                {
                    "purpose": "intake_phase",
                    "phase": phase,
                    "clarificationOccurred": bool(clarification_occurred),
                    "source": _required(source, "intake phase source"),
                },
                details,
                scope="intake phase",
            ),
            now_ms=now_ms,
        )

    def intake_state(
        self,
        root_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        def read(active: sqlite3.Connection) -> dict[str, object]:
            state = self._intake_phase_state_locked(
                active,
                root_id=root_id,
            )
            if state is not None:
                return state
            raise RoomKernelFenceError(
                "Room Root has no authoritative intake phase receipt"
            )

        if conn is not None:
            return read(conn)
        with self._connect() as active:
            return read(active)

    def root(
        self,
        root_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        def read(active: sqlite3.Connection) -> dict[str, object]:
            row = self._root_row(active, root_id)
            decoded = json.loads(str(row["payload_json"]))
            if not isinstance(decoded, Mapping):
                raise RoomKernelFenceError("Room Root payload is corrupt")
            payload = upcast_room_root_execution(
                decoded,
                facilitator_participant_id=(
                    row["facilitator_participant_id"]
                ),
                reporter_participant_id=row["reporter_participant_id"],
                reporter_selection_receipt_id=(
                    row["reporter_selection_receipt_id"]
                ),
            )
            payload.update({
                "generation": int(row["generation"]),
                "state": str(row["state"]),
                "budgetRemaining": int(row["budget_remaining"]),
                "budgetReserved": int(row["budget_reserved"]),
                "acceptanceCriteria": json.loads(
                    str(row["acceptance_criteria_json"])
                ),
                "coveredCriteria": json.loads(
                    str(row["covered_criteria_json"])
                ),
                "terminalReceiptId": row["terminal_receipt_id"],
            })
            return payload

        if conn is not None:
            return read(conn)
        with self._connect() as active:
            return read(active)

    def is_root_terminal(self, root_id: str) -> bool:
        """Return the durable Root fence without reopening execution state."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM room_kernel_roots WHERE root_id = ?",
                (str(root_id),),
            ).fetchone()
        return row is not None and str(row["state"]) in {
            "completed",
            "cancelled",
            "cancelled_with_unknowns",
            "failed",
        }

    def cancellation_surface_projection(self, room_id: str) -> list[dict[str, object]]:
        """Read-only per-surface cancellation evidence for control projections."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT cancel.cancel_id,cancel.root_id,cancel.dispatch_id,
                          surface.surface,surface.state,surface.target_ref,
                          surface.detail_json,surface.updated_at_ms
                   FROM room_v2_runtime_cancel_surface_receipts surface
                   JOIN room_kernel_cancel_outbox cancel USING(cancel_id)
                   JOIN room_kernel_roots root ON root.root_id=cancel.root_id
                   WHERE root.room_id=?
                   ORDER BY surface.updated_at_ms,cancel.cancel_id,surface.surface""",
                (room_id,),
            ).fetchall()
        return [{
            "cancelId": str(row["cancel_id"]),
            "rootId": str(row["root_id"]),
            "dispatchId": str(row["dispatch_id"]),
            "surface": str(row["surface"]),
            "state": str(row["state"]),
            "targetRef": str(row["target_ref"]),
            "detail": json.loads(str(row["detail_json"])),
            "updatedAtMs": int(row["updated_at_ms"]),
        } for row in rows]
    def task(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        def read(active: sqlite3.Connection) -> dict[str, object]:
            row = active.execute(
                "SELECT * FROM room_kernel_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            payload = json.loads(str(row["payload_json"]))
            payload["state"] = str(row["state"])
            return payload

        if conn is not None:
            return read(conn)
        with self._connect() as active:
            return read(active)

    @staticmethod
    def _root_has_unresolved_blockers_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> bool:
        """Return whether a Root still has a concrete non-terminal blocker.

        Workspace abandonment is scoped to one Task.  It may release the
        Root only after every other blocked Task/continuation and every
        unknown or failed Dispatch attached to non-terminal work is gone.
        """

        blocked_task = conn.execute(
            "SELECT 1 FROM room_kernel_tasks "
            "WHERE root_id=? AND state='blocked' LIMIT 1",
            (root_id,),
        ).fetchone()
        if blocked_task is not None:
            return True
        blocked_continuation = conn.execute(
            "SELECT 1 FROM room_kernel_continuations "
            "WHERE root_id=? AND state='blocked' LIMIT 1",
            (root_id,),
        ).fetchone()
        if blocked_continuation is not None:
            return True
        unresolved_dispatch = conn.execute(
            """SELECT 1
               FROM room_kernel_dispatches dispatch
               JOIN room_kernel_tasks task ON task.task_id=dispatch.task_id
               WHERE dispatch.root_id=?
                 AND dispatch.state IN ('unknown','dead_letter','failed')
                 AND task.state NOT IN ('completed','failed','cancelled')
               LIMIT 1""",
            (root_id,),
        ).fetchone()
        return unresolved_dispatch is not None

    def record_workspace_lifecycle(
        self,
        task_id: str,
        *,
        operation: str,
        workspace_result: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Project a receipted retain/retry/abandon transition onto one Task."""

        if operation not in {"retain", "retry", "abandon"}:
            raise RoomKernelFenceError(
                "workspace lifecycle operation is invalid"
            )
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json,state FROM room_kernel_tasks WHERE task_id=?",
                (_required(task_id, "task_id"),),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = json.loads(str(row["payload_json"]))
            if task.get("workspacePolicy") != "isolated_writable":
                raise RoomKernelFenceError(
                    "workspace lifecycle projection requires an isolated Task"
                )
            # The SQL state is the authoritative task lifecycle. Cancellation
            # intentionally updates it before the retained-worktree receipt is
            # projected, while the JSON payload can still contain the prior
            # active state. Never let that stale payload resurrect a task after
            # its Root has stopped.
            task["state"] = str(row["state"])
            result = dict(workspace_result)
            if str(result.get("workspaceBindingId") or "") != str(
                task.get("workspaceBindingId") or ""
            ):
                raise RoomKernelFenceError(
                    "workspace lifecycle receipt belongs to another Task binding"
                )
            current_lifecycle = str(
                task.get("workspaceLifecycleState") or ""
            )
            desired_lifecycle = str(
                result.get("workspaceLifecycleState") or ""
            )
            if operation == "retry" and (
                desired_lifecycle != "retry_bound"
                or result.get("attentionRequired") is not False
            ):
                raise RoomKernelFenceError(
                    "workspace retry projection requires an active retry lease"
                )
            if current_lifecycle in {"integrated", "cleaned", "abandoned"}:
                if current_lifecycle != desired_lifecycle:
                    return task
            cleanup_state = str(result.get("cleanupState") or "")
            attention = bool(result.get("attentionRequired"))
            reason = str(
                result.get("terminalReason")
                or result.get("reason")
                or ""
            )[:2_000]
            desired = {
                "workspaceLifecycleState": desired_lifecycle,
                "workspaceCleanupState": cleanup_state,
                "workspaceAttentionRequired": attention,
                "workspaceTerminalReason": reason,
            }
            if all(task.get(key) == value for key, value in desired.items()):
                return task
            task.update(desired)
            if operation == "retry":
                task["workspaceIntegrationState"] = "pending"
                task["workspaceTerminalReason"] = ""
            task["revision"] = int(task.get("revision") or 0) + 1
            if operation == "abandon" and str(row["state"]) in {
                "pending",
                "active",
                "review",
                "waiting",
                "blocked",
            }:
                task["state"] = "cancelled"
            validate_kernel_contract("roomTask", task)
            conn.execute(
                "UPDATE room_kernel_tasks SET state=?,payload_json=?,updated_at_ms=? "
                "WHERE task_id=?",
                (task["state"], _json(task), int(now_ms), task_id),
            )
            root = self._root_row(conn, str(task["rootId"]))
            if (
                operation == "abandon"
                and str(root["state"]) == "blocked"
                and not self._root_has_unresolved_blockers_locked(
                    conn,
                    root_id=str(task["rootId"]),
                )
            ):
                conn.execute(
                    "UPDATE room_kernel_roots SET state='running',updated_at_ms=? "
                    "WHERE root_id=?",
                    (int(now_ms), task["rootId"]),
                )
            self._receipt(
                conn,
                root_id=str(task["rootId"]),
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "purpose": f"workspace_{operation}",
                    "taskId": task_id,
                    "workspaceBindingId": str(task["workspaceBindingId"]),
                    "workspaceLifecycleState": desired_lifecycle,
                    "workspaceCleanupState": cleanup_state,
                    "workspaceAttentionRequired": attention,
                    "abandonmentReceiptId": result.get(
                        "abandonmentReceiptId"
                    ),
                    "abandonmentReceiptSha256": result.get(
                        "abandonmentReceiptSha256"
                    ),
                    "abandonmentSnapshotSha256": result.get(
                        "abandonmentSnapshotSha256"
                    ),
                },
                now_ms=now_ms,
            )
            return task

    def recover_workspace_retry(
        self,
        *,
        parent_dispatch_id: str,
        task_id: str,
        retry_dispatch: Mapping[str, object] | None,
        invocation_receipt_id: str,
    ) -> dict[str, object] | None:
        """Recover a committed retry when runtime execution receipt write crashed."""

        if retry_dispatch is not None:
            validate_kernel_contract("dispatchEnvelope", retry_dispatch)
        with self._connect() as conn:
            return self._workspace_retry_replay_locked(
                conn,
                parent_dispatch_id=parent_dispatch_id,
                task_id=task_id,
                retry_dispatch=retry_dispatch,
                invocation_receipt_id=invocation_receipt_id,
            )

    def _workspace_retry_replay_locked(
        self,
        conn: sqlite3.Connection,
        *,
        parent_dispatch_id: str,
        task_id: str,
        retry_dispatch: Mapping[str, object] | None,
        invocation_receipt_id: str,
    ) -> dict[str, object] | None:
        parent = self._dispatch_row(conn, parent_dispatch_id)
        root_id = str(parent["root_id"])
        rows = conn.execute(
            "SELECT payload_json FROM room_kernel_receipts WHERE root_id=?",
            (root_id,),
        ).fetchall()
        matches: list[dict[str, object]] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            details = payload.get("details") if isinstance(payload, Mapping) else None
            if not isinstance(details, Mapping):
                continue
            expected_details = {
                "purpose": "workspace_retry",
                "parentDispatchId": parent_dispatch_id,
                "childTaskId": task_id,
                "invocationReceiptId": invocation_receipt_id,
            }
            if retry_dispatch is not None:
                expected_details["childDispatchId"] = str(
                    retry_dispatch.get("dispatchId") or ""
                )
            if all(
                str(details.get(key) or "") == str(expected)
                for key, expected in expected_details.items()
            ):
                matches.append(dict(payload))
        if not matches:
            return None
        if len(matches) != 1:
            raise RoomKernelFenceError(
                "workspace retry has multiple canonical Kernel receipts"
            )
        canonical = matches[0]
        canonical_details = canonical.get("details")
        canonical_outcome = (
            canonical_details.get("retryOutcome")
            if isinstance(canonical_details, Mapping)
            else None
        )
        child_dispatch_id = str(
            canonical_details.get("childDispatchId") or ""
        )
        if not child_dispatch_id:
            raise RoomKernelFenceError(
                "workspace retry canonical receipt lost its child Dispatch"
            )
        dispatch_row = self._dispatch_row(conn, child_dispatch_id)
        stored_dispatch = json.loads(str(dispatch_row["payload_json"]))
        if retry_dispatch is not None and _dispatch_idempotency_identity(
            stored_dispatch
        ) != _dispatch_idempotency_identity(retry_dispatch):
            raise RoomKernelFenceError(
                "workspace retry replay changed its Dispatch identity"
            )
        if (
            canonical.get("schemaVersion") != KERNEL_RECEIPT_SCHEMA_VERSION
            or canonical.get("rootId") != root_id
            or stored_dispatch.get("rootId") != root_id
            or stored_dispatch.get("taskId") != task_id
            or stored_dispatch.get("parentDispatchId")
            != parent_dispatch_id
            or stored_dispatch.get("triggerId") != invocation_receipt_id
            or stored_dispatch.get("intentKind") != "retry"
            or int(canonical.get("generation", -1))
            != int(stored_dispatch.get("generation", -2))
            or (
                canonical.get("receiptKind"),
                canonical.get("status"),
            )
            not in {("accepted", "applied"), ("duplicate", "noop")}
            or not isinstance(canonical_details, Mapping)
            or canonical_details.get("targetParticipantId")
            != stored_dispatch.get("targetParticipantId")
            or canonical_details.get("targetSessionId")
            != stored_dispatch.get("targetSessionId")
            or not str(
                canonical_details.get("targetParticipantRef") or ""
            ).strip()
            or not isinstance(canonical_outcome, Mapping)
            or canonical_outcome.get("taskState") != "active"
            or canonical_outcome.get("workspaceLifecycleState")
            != "retry_bound"
            or canonical_outcome.get("workspaceAttentionRequired") is not False
            or canonical_outcome.get("dispatchState") != "pending"
            or isinstance(canonical_outcome.get("taskRevision"), bool)
            or not isinstance(canonical_outcome.get("taskRevision"), int)
            or int(canonical_outcome["taskRevision"]) < 0
            or isinstance(canonical_outcome.get("ownershipRevision"), bool)
            or not isinstance(
                canonical_outcome.get("ownershipRevision"), int
            )
            or int(canonical_outcome["ownershipRevision"]) < 0
        ):
            raise RoomKernelFenceError(
                "workspace retry canonical receipt changed its exact outcome"
            )
        task_row = conn.execute(
            "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
            (_required(task_id, "task_id"),),
        ).fetchone()
        if task_row is None:
            raise RoomKernelFenceError("workspace retry replay lost its Task")
        current_task = json.loads(str(task_row["payload_json"]))
        if int(current_task.get("revision") or 0) < int(
            canonical_outcome["taskRevision"]
        ):
            raise RoomKernelFenceError(
                "workspace retry Task regressed behind its canonical receipt"
            )
        canonical_task = {
            **current_task,
            "state": canonical_outcome["taskState"],
            "revision": int(canonical_outcome["taskRevision"]),
            "ownershipRevision": int(
                canonical_outcome["ownershipRevision"]
            ),
            "workspaceLifecycleState": canonical_outcome[
                "workspaceLifecycleState"
            ],
            "workspaceAttentionRequired": canonical_outcome[
                "workspaceAttentionRequired"
            ],
        }
        canonical_dispatch = {
            **_dispatch_payload(dispatch_row),
            "state": canonical_outcome["dispatchState"],
        }
        return {
            "receipt": canonical,
            "task": canonical_task,
            "dispatch": canonical_dispatch,
        }

    def enqueue_workspace_retry(
        self,
        *,
        parent_dispatch_id: str,
        task_id: str,
        retry_dispatch: Mapping[str, object],
        workspace_result: Mapping[str, object],
        invocation_receipt_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Re-open one retained Task and enqueue its exact retry atomically."""

        validate_kernel_contract("dispatchEnvelope", retry_dispatch)
        with self._connect(immediate=True) as conn:
            parent = self._dispatch_row(conn, parent_dispatch_id)
            parent_payload = json.loads(str(parent["payload_json"]))
            root = self._root_row(conn, str(parent["root_id"]))
            root_payload = json.loads(str(root["payload_json"]))
            if (
                str(parent["state"]) != "running"
                or str(parent["target_participant_id"])
                != str(root_payload.get("facilitatorParticipantId") or "")
            ):
                raise RoomKernelFenceError(
                    "workspace retry requires the active Root Facilitator"
                )
            invocation = conn.execute(
                """SELECT invocation.*,
                          binding.session_id AS bound_session_id,
                          binding.state AS bound_state,
                          binding.capability_epoch AS bound_capability_epoch
                   FROM room_v2_tool_invocation_receipts invocation
                   JOIN room_v2_capability_runtime_bindings binding
                     ON binding.manifest_id=invocation.manifest_id
                    AND binding.manifest_hash=invocation.manifest_hash
                   WHERE invocation.receipt_id=?""",
                (_required(invocation_receipt_id, "invocation_receipt_id"),),
            ).fetchone()
            if invocation is None:
                raise RoomKernelFenceError(
                    "workspace retry invocation receipt is missing"
                )
            command = json.loads(str(invocation["command_json"]))
            arguments = (
                command.get("arguments")
                if isinstance(command, Mapping)
                else None
            )
            command_material = (
                {
                    key: value
                    for key, value in command.items()
                    if key != "commandHash"
                }
                if isinstance(command, Mapping)
                else {}
            )
            command_hash = hashlib.sha256(
                _json(command_material).encode("utf-8")
            ).hexdigest()
            if (
                not isinstance(command, Mapping)
                or not isinstance(arguments, Mapping)
                or str(invocation["canonical_tool_name"])
                != "room_integrate"
                or command.get("tool") != "room_integrate"
                or arguments.get("action", "integrate") != "retry"
                or arguments.get("childTaskId") != task_id
                or command.get("rootId") != root["root_id"]
                or command.get("taskId") != parent["task_id"]
                or command.get("dispatchId") != parent_dispatch_id
                or int(command.get("generation", -1))
                != int(root["generation"])
                or int(command.get("capabilityEpoch", -1))
                != int(parent_payload.get("capabilityEpoch", -1))
                or int(invocation["bound_capability_epoch"])
                != int(parent_payload.get("capabilityEpoch", -1))
                or str(invocation["bound_session_id"])
                != str(parent["target_session_id"])
                or str(invocation["bound_state"]) != "active"
                or str(invocation["authorization_state"])
                != "authorized"
                or command.get("commandHash") != command_hash
                or str(invocation["command_hash"]) != command_hash
            ):
                raise RoomKernelFenceError(
                    "workspace retry invocation does not match its exact "
                    "Facilitator command fences"
                )
            row = conn.execute(
                "SELECT payload_json,state FROM room_kernel_tasks WHERE task_id=?",
                (_required(task_id, "task_id"),),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = json.loads(str(row["payload_json"]))
            binding_id = str(task.get("workspaceBindingId") or "")
            if (
                task.get("workspacePolicy") != "isolated_writable"
                or task.get("rootId") != root["root_id"]
                or workspace_result.get("workspaceLifecycleState")
                != "retry_bound"
                or workspace_result.get("attentionRequired") is not False
                or str(workspace_result.get("workspaceBindingId") or "")
                != binding_id
            ):
                raise RoomKernelFenceError(
                    "workspace retry lost its retained Task binding"
                )
            if (
                retry_dispatch.get("rootId") != root["root_id"]
                or retry_dispatch.get("taskId") != task_id
                or retry_dispatch.get("parentDispatchId")
                != parent_dispatch_id
                or retry_dispatch.get("intentKind") != "retry"
                or int(retry_dispatch.get("generation", -1))
                != int(root["generation"])
                or int(retry_dispatch.get("hopCount", -1))
                != int(parent["hop_count"]) + 1
                or int(retry_dispatch.get("depth", -1))
                < int(parent["depth"])
                or retry_dispatch.get("triggerId")
                != invocation_receipt_id
                or int(retry_dispatch.get("capabilityEpoch", -1))
                != int(command["capabilityEpoch"])
            ):
                raise RoomKernelFenceError(
                    "workspace retry Dispatch does not match its parent fences"
                )
            replay = self._workspace_retry_replay_locked(
                conn,
                parent_dispatch_id=parent_dispatch_id,
                task_id=task_id,
                retry_dispatch=retry_dispatch,
                invocation_receipt_id=invocation_receipt_id,
            )
            if replay is not None:
                return replay
            target_participant_id = str(
                retry_dispatch.get("targetParticipantId") or ""
            )
            target_session_id = str(
                retry_dispatch.get("targetSessionId") or ""
            )
            requested_target_participant_ref = str(
                arguments.get("targetParticipantRef") or ""
            ).strip()
            target_participant_ref = str(
                workspace_result.get("targetParticipantRef") or ""
            ).strip()
            retry_receipt_id = str(
                workspace_result.get("retryBoundReceiptId") or ""
            )
            retry_receipt_sha256 = str(
                workspace_result.get("retryBoundReceiptSha256") or ""
            )
            retry_event = conn.execute(
                """SELECT * FROM room_workspace_events
                   WHERE event_id=? AND binding_id=? AND event_kind='retry_bound'""",
                (retry_receipt_id, binding_id),
            ).fetchone()
            workspace_binding = conn.execute(
                "SELECT * FROM room_workspace_bindings WHERE binding_id=?",
                (binding_id,),
            ).fetchone()
            retry_payload = (
                json.loads(str(retry_event["payload_json"]))
                if retry_event is not None
                else None
            )
            retry_token = str(workspace_result.get("retryLeaseToken") or "")
            retry_token_sha256 = hashlib.sha256(
                retry_token.encode("utf-8")
            ).hexdigest()
            if (
                workspace_binding is None
                or retry_event is None
                or not isinstance(retry_payload, Mapping)
                or str(retry_event["payload_sha256"]) != retry_receipt_sha256
                or int(retry_event["sequence"])
                != int(workspace_binding["last_event_sequence"])
                or str(workspace_binding["root_id"]) != str(root["root_id"])
                or str(workspace_binding["task_id"]) != task_id
                or str(workspace_binding["state"]) != "retry_bound"
                or bool(workspace_binding["attention_required"])
                or str(workspace_binding["current_owner_participant_id"])
                != target_participant_id
                or str(workspace_binding["current_owner_session_id"])
                != target_session_id
                or str(retry_payload.get("participantId") or "")
                != target_participant_id
                or str(retry_payload.get("participantRef") or "")
                != target_participant_ref
                or str(retry_payload.get("sessionId") or "")
                != target_session_id
                or int(retry_payload.get("retryEpoch") or -1)
                != int(workspace_result.get("retryEpoch") or -2)
                or str(retry_payload.get("retryLeaseToken") or "")
                != retry_token
                or str(retry_payload.get("retryLeaseTokenSha256") or "")
                != retry_token_sha256
                or str(workspace_result.get("retryLeaseTokenSha256") or "")
                != retry_token_sha256
                or not target_participant_ref
                or (
                    requested_target_participant_ref
                    and requested_target_participant_ref
                    != target_participant_ref
                )
                or (
                    not requested_target_participant_ref
                    and target_participant_id
                    != str(task.get("currentOwnerParticipantId") or "")
                )
            ):
                raise RoomKernelFenceError(
                    "workspace retry is not bound to its exact durable retry lease"
                )
            owner_changed = (
                target_participant_id
                != str(task.get("currentOwnerParticipantId") or "")
            )
            ownership_receipt = None
            if owner_changed:
                ownership_receipt = self._receipt(
                    conn,
                    root_id=str(root["root_id"]),
                    command_id=None,
                    receipt_kind="accepted",
                    status="applied",
                    generation=int(root["generation"]),
                    details={
                        "purpose": "workspace_retry_ownership",
                        "taskId": task_id,
                        "fromParticipantId": task.get(
                            "currentOwnerParticipantId"
                        ),
                        "toParticipantId": target_participant_id,
                        "invocationReceiptId": invocation_receipt_id,
                    },
                    now_ms=now_ms,
                )
            task.update(
                {
                    "currentOwnerParticipantId": target_participant_id,
                    "ownershipRevision": int(
                        task.get("ownershipRevision") or 0
                    )
                    + int(owner_changed),
                    "ownershipReceiptId": (
                        ownership_receipt["receiptId"]
                        if ownership_receipt is not None
                        else task.get("ownershipReceiptId")
                    ),
                    "workspaceLifecycleState": "retry_bound",
                    "workspaceCleanupState": "not_authorized",
                    "workspaceAttentionRequired": False,
                    "workspaceTerminalReason": "",
                    "workspaceIntegrationState": "pending",
                    "revision": int(task.get("revision") or 0) + 1,
                    "state": "active",
                }
            )
            validate_kernel_contract("roomTask", task)
            conn.execute(
                "UPDATE room_kernel_tasks SET state='active',payload_json=?,updated_at_ms=? "
                "WHERE task_id=?",
                (_json(task), int(now_ms), task_id),
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='running',updated_at_ms=? "
                "WHERE root_id=?",
                (int(now_ms), root["root_id"]),
            )
            dispatch, created = self._enqueue_dispatch(
                conn,
                retry_dispatch,
                shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
                now_ms=now_ms,
            )
            receipt = self._receipt(
                conn,
                root_id=str(root["root_id"]),
                command_id=None,
                receipt_kind="accepted" if created else "duplicate",
                status="applied" if created else "noop",
                generation=int(root["generation"]),
                details={
                    "purpose": "workspace_retry",
                    "parentTaskId": str(parent["task_id"]),
                    "parentDispatchId": parent_dispatch_id,
                    "childTaskId": task_id,
                    "childDispatchId": str(dispatch["dispatchId"]),
                    "workspaceBindingId": binding_id,
                    "invocationReceiptId": invocation_receipt_id,
                    "retryBoundReceiptId": retry_receipt_id,
                    "retryBoundReceiptSha256": retry_receipt_sha256,
                    "retryEpoch": int(retry_payload["retryEpoch"]),
                    "retryLeaseTokenSha256": retry_token_sha256,
                    "targetParticipantId": target_participant_id,
                    "targetSessionId": target_session_id,
                    "targetParticipantRef": target_participant_ref,
                    "retryOutcome": {
                        "taskState": str(task["state"]),
                        "taskRevision": int(task["revision"]),
                        "ownershipRevision": int(
                            task.get("ownershipRevision") or 0
                        ),
                        "workspaceLifecycleState": str(
                            task["workspaceLifecycleState"]
                        ),
                        "workspaceAttentionRequired": bool(
                            task["workspaceAttentionRequired"]
                        ),
                        "dispatchState": str(dispatch["state"]),
                    },
                },
                now_ms=now_ms,
            )
            return {"receipt": receipt, "task": task, "dispatch": dispatch}

    def record_workspace_integration(
        self,
        task_id: str,
        *,
        integration_ref: str,
        now_ms: int,
        workspace_result: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Seal one successful isolated-worktree merge on its child Task."""

        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json,state FROM room_kernel_tasks WHERE task_id=?",
                (_required(task_id, "task_id"),),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = json.loads(str(row["payload_json"]))
            if task.get("workspacePolicy") != "isolated_writable":
                raise RoomKernelFenceError(
                    "workspace integration requires an isolated_writable Task"
                )
            if not isinstance(workspace_result, Mapping):
                raise RoomKernelFenceError(
                    "workspace integration requires an exact coordinator result"
                )
            result = dict(workspace_result)
            if result.get("integrated") is not True:
                raise RoomKernelFenceError(
                    "workspace integration cannot apply without integrated=true"
                )
            current_integration_ref = str(
                task.get("workspaceIntegrationRef") or ""
            ).strip()
            if (
                current_integration_ref
                and current_integration_ref != integration_ref
            ):
                raise RoomKernelFenceError(
                    "workspace integration retry changed its integrationRef"
                )
            self._assert_workspace_integration_receipts(
                conn,
                task=task,
                result=result,
                integration_ref=_required(integration_ref, "integration_ref"),
            )
            if task.get("workspaceIntegrationState") == "applied":
                attempt = self._current_committed_task_attempt_locked(
                    conn,
                    root_id=str(task.get("rootId") or ""),
                    task_id=task_id,
                )
                if attempt is None:
                    raise RoomKernelFenceError(
                        "applied workspace integration has no authoritative Worker Commit"
                    )
                try:
                    raw_commit = json.loads(
                        str(attempt["commit_payload_json"])
                    )
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RoomKernelFenceError(
                        "workspace integration Worker Commit is corrupt"
                    ) from exc
                if not isinstance(raw_commit, Mapping):
                    raise RoomKernelFenceError(
                        "applied workspace integration lacks canonical authority"
                    )
                root_id = str(task.get("rootId") or "")
                commit_id = str(attempt["commit_id"])
                acceptance_candidate = (
                    self._canonical_acceptance_authority_receipt_locked(
                        conn,
                        root_id=root_id,
                        commit_id=commit_id,
                    )
                )
                if acceptance_candidate is None or not (
                    self._acceptance_commit_authority_valid_locked(
                        conn,
                        root_id=root_id,
                        task_payload=task,
                        dispatch=attempt,
                        commit_id=commit_id,
                        raw_commit=raw_commit,
                        require_integration=None,
                    )
                ):
                    raise RoomKernelFenceError(
                        "applied workspace integration lost its Commit authority"
                    )
                (
                    acceptance_receipt_row,
                    acceptance_receipt,
                    acceptance_authority,
                ) = acceptance_candidate
                successful_cleanup = str(
                    result.get("cleanupState") or ""
                ) in {"cleaned", "missing"}
                exact_integration_projection = {
                    "workspaceBindingId": task.get("workspaceBindingId"),
                    "integrationRef": task.get("workspaceIntegrationRef"),
                    "integrationPatchSha256": task.get(
                        "workspaceIntegrationPatchSha256"
                    ),
                    "integratedRevision": task.get(
                        "workspaceIntegratedRevision"
                    ),
                    "integratedSnapshotSha256": task.get(
                        "workspaceIntegratedSnapshotSha256"
                    ),
                }
                if any(
                    result.get(key) != expected
                    for key, expected in exact_integration_projection.items()
                ):
                    raise RoomKernelFenceError(
                        "workspace cleanup retry changed its applied integration"
                    )
                if str(task.get("workspaceCleanupState") or "") in {
                    "cleaned",
                    "missing",
                }:
                    if not successful_cleanup or not (
                        self._acceptance_commit_authority_valid_locked(
                            conn,
                            root_id=root_id,
                            task_payload=task,
                            dispatch=attempt,
                            commit_id=commit_id,
                            raw_commit=raw_commit,
                        )
                    ):
                        raise RoomKernelFenceError(
                            "applied workspace integration lacks canonical authority"
                        )
                    if any(
                        result.get(source) != task.get(destination)
                        for source, destination in {
                            "workspaceLifecycleState": "workspaceLifecycleState",
                            "cleanupState": "workspaceCleanupState",
                            "attentionRequired": "workspaceAttentionRequired",
                        }.items()
                    ):
                        raise RoomKernelFenceError(
                            "workspace integration replay changed its cleanup outcome"
                        )
                    return task
                pending_authority = (
                    self._pending_workspace_integration_authority_locked(
                        conn,
                        root_id=root_id,
                        task_payload=task,
                        dispatch=attempt,
                        commit_id=commit_id,
                        raw_commit=raw_commit,
                        acceptance_receipt_row=acceptance_receipt_row,
                        acceptance_receipt=acceptance_receipt,
                        acceptance_authority=acceptance_authority,
                    )
                )
                if pending_authority is None:
                    raise RoomKernelFenceError(
                        "workspace cleanup retry lacks its pending integration authority"
                    )
                if not successful_cleanup:
                    if any(
                        result.get(source) != task.get(destination)
                        for source, destination in {
                            "workspaceLifecycleState": "workspaceLifecycleState",
                            "cleanupState": "workspaceCleanupState",
                            "attentionRequired": "workspaceAttentionRequired",
                        }.items()
                    ):
                        raise RoomKernelFenceError(
                            "workspace cleanup retry did not resolve attention"
                        )
                    return task
                if self._workspace_integration_authority_candidates_locked(
                    conn,
                    root_id=root_id,
                    task_id=task_id,
                    receipt_kind="accepted",
                    operation="room_integrate",
                ):
                    raise RoomKernelFenceError(
                        "workspace cleanup retry found a duplicate success authority"
                    )
                task.update(
                    {
                        "workspaceLifecycleState": result.get(
                            "workspaceLifecycleState"
                        ),
                        "workspaceCleanupState": result.get("cleanupState"),
                        "workspaceAttentionRequired": result.get(
                            "attentionRequired"
                        ),
                        "revision": int(task.get("revision") or 0) + 1,
                    }
                )
                if result.get("reason") not in {None, ""}:
                    task["workspaceTerminalReason"] = str(
                        result.get("reason")
                    )[:2_000]
                validate_kernel_contract("roomTask", task)
                integration_authority = (
                    self._workspace_integration_authority_locked(
                        task_payload=task,
                        workspace_result=result,
                        acceptance_receipt_row=acceptance_receipt_row,
                        acceptance_receipt=acceptance_receipt,
                        acceptance_authority=acceptance_authority,
                    )
                )
                conn.execute(
                    "UPDATE room_kernel_tasks SET payload_json=?,updated_at_ms=? "
                    "WHERE task_id=?",
                    (_json(task), int(now_ms), task_id),
                )
                root = self._root_row(conn, root_id)
                self._receipt(
                    conn,
                    root_id=root_id,
                    command_id=None,
                    receipt_kind="accepted",
                    status="applied",
                    generation=int(root["generation"]),
                    details={
                        "operation": "room_integrate",
                        "taskId": task_id,
                        "integrationRef": integration_ref,
                        "integrated": True,
                        "workspaceLifecycleState": task.get(
                            "workspaceLifecycleState"
                        ),
                        "workspaceCleanupState": task.get(
                            "workspaceCleanupState"
                        ),
                        "integrationAuthority": integration_authority,
                    },
                    now_ms=now_ms,
                )
                return task
            if str(row["state"]) != "completed":
                raise RoomKernelFenceError(
                    "workspace integration requires a completed child Task"
                )
            attempt = self._current_committed_task_attempt_locked(
                conn,
                root_id=str(task.get("rootId") or ""),
                task_id=task_id,
            )
            if attempt is None:
                raise RoomKernelFenceError(
                    "workspace integration requires an authoritative Worker Commit"
                )
            try:
                raw_commit = json.loads(str(attempt["commit_payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RoomKernelFenceError(
                    "workspace integration Worker Commit is corrupt"
                ) from exc
            if not isinstance(raw_commit, Mapping) or not (
                self._acceptance_commit_authority_valid_locked(
                    conn,
                    root_id=str(task.get("rootId") or ""),
                    task_payload=task,
                    dispatch=attempt,
                    commit_id=str(attempt["commit_id"]),
                    raw_commit=raw_commit,
                    require_integration=False,
                )
            ):
                raise RoomKernelFenceError(
                    "workspace integration requires canonical Worker Commit evidence"
                )
            acceptance_candidate = (
                self._canonical_acceptance_authority_receipt_locked(
                    conn,
                    root_id=str(task.get("rootId") or ""),
                    commit_id=str(attempt["commit_id"]),
                )
            )
            if acceptance_candidate is None:
                raise RoomKernelFenceError(
                    "workspace integration lost its acceptance authority"
                )
            (
                acceptance_receipt_row,
                acceptance_receipt,
                acceptance_authority,
            ) = acceptance_candidate
            task.update(
                {
                    "workspaceIntegrationState": "applied",
                    "workspaceIntegrationRef": _required(
                        integration_ref,
                        "integration_ref",
                    ),
                    "revision": int(task.get("revision") or 0) + 1,
                    "state": "completed",
                }
            )
            field_map = {
                "integrationPatchSha256": "workspaceIntegrationPatchSha256",
                "integratedRevision": "workspaceIntegratedRevision",
                "integratedSnapshotSha256": "workspaceIntegratedSnapshotSha256",
                "workspaceLifecycleState": "workspaceLifecycleState",
                "cleanupState": "workspaceCleanupState",
                "reason": "workspaceTerminalReason",
            }
            for source, destination in field_map.items():
                value = result.get(source)
                if value not in {None, ""}:
                    task[destination] = value
            task["workspaceAttentionRequired"] = result.get(
                "attentionRequired"
            )
            validate_kernel_contract("roomTask", task)
            integration_authority = (
                self._workspace_integration_authority_locked(
                    task_payload=task,
                    workspace_result=result,
                    acceptance_receipt_row=acceptance_receipt_row,
                    acceptance_receipt=acceptance_receipt,
                    acceptance_authority=acceptance_authority,
                )
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=?,updated_at_ms=? "
                "WHERE task_id=?",
                (_json(task), int(now_ms), task_id),
            )
            root = self._root_row(conn, str(task["rootId"]))
            successful_cleanup = str(
                task.get("workspaceCleanupState") or ""
            ) in {"cleaned", "missing"}
            self._receipt(
                conn,
                root_id=str(task["rootId"]),
                command_id=None,
                receipt_kind=("accepted" if successful_cleanup else "rejected"),
                status=("applied" if successful_cleanup else "rejected"),
                generation=int(root["generation"]),
                details={
                    "operation": (
                        "room_integrate"
                        if successful_cleanup
                        else "room_integrate_pending_cleanup"
                    ),
                    "taskId": task_id,
                    "integrationRef": integration_ref,
                    "integrated": True,
                    "workspaceLifecycleState": task.get(
                        "workspaceLifecycleState"
                    ),
                    "workspaceCleanupState": task.get(
                        "workspaceCleanupState"
                    ),
                    "integrationAuthority": integration_authority,
                },
                now_ms=now_ms,
            )
            return task

    @staticmethod
    def _assert_workspace_integration_receipts(
        conn: sqlite3.Connection,
        *,
        task: Mapping[str, object],
        result: Mapping[str, object],
        integration_ref: str,
        require_binding_projection: bool = True,
    ) -> None:
        binding_id = _required(
            result.get("workspaceBindingId"),
            "workspace_binding_id",
        )
        if binding_id != str(task.get("workspaceBindingId") or ""):
            raise RoomKernelFenceError(
                "workspace integration result belongs to another binding"
            )
        if str(result.get("integrationRef") or "") != integration_ref:
            raise RoomKernelFenceError(
                "workspace integration result changed its integrationRef"
            )
        patch_sha256 = _required(
            result.get("integrationPatchSha256"),
            "integration_patch_sha256",
        )
        integrated_revision = _required(
            result.get("integratedRevision"),
            "integrated_revision",
        )
        integrated_snapshot = _required(
            result.get("integratedSnapshotSha256"),
            "integrated_snapshot_sha256",
        )
        for field, value in {
            "integrationPatchSha256": patch_sha256,
            "integratedSnapshotSha256": integrated_snapshot,
        }.items():
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise RoomKernelFenceError(f"{field} is not a lowercase SHA-256")
        cleanup_state = str(result.get("cleanupState") or "")
        successful_cleanup = cleanup_state in {"cleaned", "missing"}
        attention_required = result.get("attentionRequired")
        if not isinstance(attention_required, bool) or (
            attention_required is successful_cleanup
        ):
            raise RoomKernelFenceError(
                "workspace cleanup state and attention flag are inconsistent"
            )
        receipt_fields = {
            "delivery": (
                "delivered",
                "workspaceDeliveryReceiptId",
                "workspaceDeliveryReceiptSha256",
            ),
            "source": (
                "source_lease_revoked",
                "workspaceSourceLeaseReceiptId",
                "workspaceSourceLeaseReceiptSha256",
            ),
            "target": (
                "target_applied",
                "workspaceTargetAppliedReceiptId",
                "workspaceTargetAppliedReceiptSha256",
            ),
            "integrated": (
                "integrated",
                "workspaceIntegratedReceiptId",
                "workspaceIntegratedReceiptSha256",
            ),
            "cleanup": (
                None,
                "workspaceCleanupReceiptId",
                "workspaceCleanupReceiptSha256",
            ),
        }
        if successful_cleanup:
            receipt_fields.update(
                {
                    "writer_quiescence": (
                        "writer_quiescent",
                        "workspaceWriterQuiescenceReceiptId",
                        "workspaceWriterQuiescenceReceiptSha256",
                    ),
                    "quarantine": (
                        "quarantined",
                        "workspaceQuarantineReceiptId",
                        "workspaceQuarantineReceiptSha256",
                    ),
                    "removal_authorization": (
                        "cleanup_removal_authorized",
                        "workspaceRemovalAuthorizationReceiptId",
                        "workspaceRemovalAuthorizationReceiptSha256",
                    ),
                }
            )
        if cleanup_state == "cleaned":
            receipt_fields["vault"] = (
                "vaulted",
                "workspaceVaultReceiptId",
                "workspaceVaultReceiptSha256",
            )
        receipts: dict[str, tuple[sqlite3.Row, dict[str, object]]] = {}
        for name, (expected_kind, id_field, sha_field) in receipt_fields.items():
            receipt_id = _required(result.get(id_field), id_field)
            receipt_sha256 = _required(result.get(sha_field), sha_field)
            row = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE event_id=? AND binding_id=?
                """,
                (receipt_id, binding_id),
            ).fetchone()
            if row is None:
                raise RoomKernelFenceError(
                    f"workspace {name} receipt is not in the durable ledger"
                )
            if (
                expected_kind is not None
                and str(row["event_kind"]) != expected_kind
            ) or str(row["payload_sha256"]) != receipt_sha256:
                raise RoomKernelFenceError(
                    f"workspace {name} receipt kind or digest does not match"
                )
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                raise RoomKernelFenceError(
                    f"workspace {name} receipt payload is corrupt"
                )
            canonical_payload = _json(payload)
            canonical_payload_sha256 = hashlib.sha256(
                canonical_payload.encode("utf-8")
            ).hexdigest()
            workspace_event_material = "\0".join(
                (
                    "room-workspace-event",
                    binding_id,
                    str(row["sequence"]),
                    str(row["event_kind"]),
                    str(row["idempotency_key"]),
                )
            ).encode("utf-8")
            canonical_event_id = "room-workspace-event:" + hashlib.sha256(
                workspace_event_material
            ).hexdigest()[:32]
            if (
                canonical_payload_sha256 != str(row["payload_sha256"])
                or canonical_event_id != str(row["event_id"])
            ):
                raise RoomKernelFenceError(
                    f"workspace {name} receipt is not canonical"
                )
            receipts[name] = (row, payload)
        delivery_row, delivered_payload = receipts["delivery"]
        source_row, source = receipts["source"]
        target_row, target = receipts["target"]
        integrated_row, integrated_payload = receipts["integrated"]
        cleanup_row, cleanup = receipts["cleanup"]
        expected_cleanup_kind = (
            "cleaned" if cleanup_state in {"cleaned", "missing"} else "cleanup_failed"
        )
        if (
            str(cleanup_row["event_kind"]) != expected_cleanup_kind
            or str(cleanup.get("result") or "") != cleanup_state
        ):
            raise RoomKernelFenceError(
                "workspace cleanup receipt does not match the projected cleanup state"
            )
        if any(
            str(source.get(key) or "") != expected
            for key, expected in {"patchSha256": patch_sha256}.items()
        ):
            raise RoomKernelFenceError(
                "workspace source receipt does not match the integration patch"
            )
        if any(
            str(target.get(key) or "") != str(expected)
            for key, expected in {
                "patchSha256": patch_sha256,
                "sourceLeaseReceiptId": source_row["event_id"],
                "sourceLeaseReceiptSha256": source_row["payload_sha256"],
            }.items()
        ):
            raise RoomKernelFenceError(
                "workspace target receipt is not bound to its source receipt"
            )
        if any(
            str(integrated_payload.get(key) or "") != str(expected)
            for key, expected in {
                "integrationRef": integration_ref,
                "patchSha256": patch_sha256,
                "integratedRevision": integrated_revision,
                "integratedSnapshotSha256": integrated_snapshot,
                "sourceLeaseReceiptId": source_row["event_id"],
                "sourceLeaseReceiptSha256": source_row["payload_sha256"],
                "targetAppliedReceiptId": target_row["event_id"],
                "targetAppliedReceiptSha256": target_row["payload_sha256"],
            }.items()
        ):
            raise RoomKernelFenceError(
                "workspace integrated receipt chain is incomplete or mismatched"
            )
        binding = conn.execute(
            "SELECT * FROM room_workspace_bindings WHERE binding_id=?",
            (binding_id,),
        ).fetchone()
        if binding is None:
            raise RoomKernelFenceError(
                "workspace integration binding is missing from the durable ledger"
            )
        delivery = task.get("workspaceDelivery")
        if not isinstance(delivery, Mapping):
            raise RoomKernelFenceError(
                "workspace integration Task has no delivered evidence"
            )
        delivery_rows = conn.execute(
            """SELECT * FROM room_workspace_events
               WHERE binding_id=? AND event_kind='delivered'
               ORDER BY sequence,event_id""",
            (binding_id,),
        ).fetchall()
        matching_deliveries: list[sqlite3.Row] = []
        expected_delivery = {
            "deliveryRevision": task.get("workspaceDeliveryRevision"),
            "deliveryHead": task.get("workspaceDeliveryHead"),
            "workspaceSnapshotSha256": task.get(
                "workspaceDeliverySnapshotSha256"
            ),
            "patchSha256": delivery.get("patchSha256"),
            "manifestSha256": delivery.get("manifestSha256"),
        }
        for candidate in delivery_rows:
            try:
                candidate_payload = json.loads(
                    str(candidate["payload_json"])
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RoomKernelFenceError(
                    "workspace delivered receipt payload is corrupt"
                ) from exc
            if not isinstance(candidate_payload, Mapping):
                raise RoomKernelFenceError(
                    "workspace delivered receipt payload is corrupt"
                )
            canonical_payload = _json(dict(candidate_payload))
            event_material = "\0".join(
                (
                    "room-workspace-event",
                    binding_id,
                    str(candidate["sequence"]),
                    str(candidate["event_kind"]),
                    str(candidate["idempotency_key"]),
                )
            ).encode("utf-8")
            if (
                hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
                != str(candidate["payload_sha256"])
                or "room-workspace-event:"
                + hashlib.sha256(event_material).hexdigest()[:32]
                != str(candidate["event_id"])
            ):
                raise RoomKernelFenceError(
                    "workspace delivery receipt is not canonical"
                )
            if all(
                str(candidate_payload.get(key) or "")
                == str(expected or "")
                for key, expected in expected_delivery.items()
            ):
                matching_deliveries.append(candidate)
        if (
            len(matching_deliveries) != 1
            or str(matching_deliveries[0]["event_id"])
            != str(delivery_row["event_id"])
            or any(
            str(delivered_payload.get(key) or "") != str(expected or "")
                for key, expected in expected_delivery.items()
            )
        ):
            raise RoomKernelFenceError(
                "workspace Task delivery does not have one exact durable receipt"
            )
        if successful_cleanup:
            writer_row, writer = receipts["writer_quiescence"]
            quarantine_row, quarantine = receipts["quarantine"]
            removal_row, removal = receipts["removal_authorization"]
            if any(
                str(writer.get(key) or "") != str(expected)
                for key, expected in {
                    "workspaceBindingId": binding_id,
                    "rootId": task.get("rootId"),
                    "taskId": task.get("taskId"),
                    "dispatchId": binding["dispatch_id"],
                    "sourceLeaseReceiptId": source_row["event_id"],
                    "sourceLeaseReceiptSha256": source_row["payload_sha256"],
                    "integratedReceiptId": integrated_row["event_id"],
                    "integratedReceiptSha256": integrated_row["payload_sha256"],
                }.items()
            ):
                raise RoomKernelFenceError(
                    "workspace writer-quiescence receipt is outside the exact integration lineage"
                )
            source_content = str(source.get("workspaceContentSha256") or "")
            if any(
                str(quarantine.get(key) or "") != str(expected)
                for key, expected in {
                    "authorityKind": "integration",
                    "workspaceContentSha256": source_content,
                    "targetSnapshotSha256": integrated_snapshot,
                    "sourceLeaseReceiptId": source_row["event_id"],
                    "sourceLeaseReceiptSha256": source_row["payload_sha256"],
                    "integratedReceiptId": integrated_row["event_id"],
                    "integratedReceiptSha256": integrated_row["payload_sha256"],
                    "writerQuiescenceReceiptId": writer_row["event_id"],
                    "writerQuiescenceReceiptSha256": writer_row["payload_sha256"],
                }.items()
            ):
                raise RoomKernelFenceError(
                    "workspace quarantine receipt is outside the exact integration lineage"
                )
            if any(
                str(removal.get(key) or "") != str(expected)
                for key, expected in {
                    "workspaceContentSha256": source_content,
                    "targetSnapshotSha256": integrated_snapshot,
                    "quarantineReceiptId": quarantine_row["event_id"],
                    "quarantineReceiptSha256": quarantine_row["payload_sha256"],
                    "writerQuiescenceReceiptId": writer_row["event_id"],
                    "writerQuiescenceReceiptSha256": writer_row["payload_sha256"],
                }.items()
            ):
                raise RoomKernelFenceError(
                    "workspace removal authorization is outside the exact integration lineage"
                )
            if any(
                str(cleanup.get(key) or "") != str(expected)
                for key, expected in {
                    "removalAuthorizationReceiptId": removal_row["event_id"],
                    "removalAuthorizationReceiptSha256": removal_row["payload_sha256"],
                    "quarantineReceiptId": quarantine_row["event_id"],
                    "quarantineReceiptSha256": quarantine_row["payload_sha256"],
                    "writerQuiescenceReceiptId": writer_row["event_id"],
                    "writerQuiescenceReceiptSha256": writer_row["payload_sha256"],
                }.items()
            ):
                raise RoomKernelFenceError(
                    "workspace cleanup receipt is outside the exact removal lineage"
                )
        if cleanup_state == "cleaned":
            vault_row, vault = receipts["vault"]
            removal_row, removal = receipts["removal_authorization"]
            if any(
                str(vault.get(key) or "") != str(expected)
                for key, expected in {
                    "removalAuthorizationReceiptId": removal_row["event_id"],
                    "removalAuthorizationReceiptSha256": removal_row[
                        "payload_sha256"
                    ],
                    "rootId": task.get("rootId"),
                    "taskId": task.get("taskId"),
                }.items()
            ):
                raise RoomKernelFenceError(
                    "workspace vault receipt is outside the exact removal lineage"
                )
            if any(
                str(cleanup.get(key) or "") != str(expected)
                for key, expected in {
                    "vaultReceiptId": vault_row["event_id"],
                    "vaultReceiptSha256": vault_row["payload_sha256"],
                    "vaultWorkspaceRoot": vault.get("vaultWorkspaceRoot"),
                    "vaultContentSha256": vault.get("vaultContentSha256"),
                }.items()
            ):
                raise RoomKernelFenceError(
                    "workspace cleanup receipt is outside the exact vault lineage"
                )
        if require_binding_projection and any(
            str(binding[column]) != expected
            for column, expected in {
                "integration_ref": integration_ref,
                "integration_patch_sha256": patch_sha256,
                "integrated_revision": integrated_revision,
                "integrated_snapshot_sha256": integrated_snapshot,
                "state": str(result.get("workspaceLifecycleState") or ""),
                "cleanup_state": cleanup_state,
            }.items()
        ):
            raise RoomKernelFenceError(
                "workspace binding projection does not match its receipt chain"
            )

    def record_workspace_integration_failure(
        self,
        task_id: str,
        *,
        integration_ref: str,
        workspace_result: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Project retained/conflict evidence without granting applied authority."""

        if workspace_result.get("integrated") is not False:
            raise RoomKernelFenceError(
                "workspace integration failure requires integrated=false"
            )
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json,state FROM room_kernel_tasks WHERE task_id=?",
                (_required(task_id, "task_id"),),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = json.loads(str(row["payload_json"]))
            if (
                task.get("workspacePolicy") != "isolated_writable"
                or str(row["state"]) != "completed"
            ):
                raise RoomKernelFenceError(
                    "workspace integration failure requires a completed isolated Task"
                )
            binding_id = _required(
                workspace_result.get("workspaceBindingId"),
                "workspace_binding_id",
            )
            if binding_id != str(task.get("workspaceBindingId") or ""):
                raise RoomKernelFenceError(
                    "workspace integration failure belongs to another binding"
                )
            task.update(
                {
                    "workspaceIntegrationState": "pending",
                    "workspaceIntegrationRef": _required(
                        integration_ref,
                        "integration_ref",
                    ),
                    "workspaceLifecycleState": str(
                        workspace_result.get("workspaceLifecycleState")
                        or "retained"
                    ),
                    "workspaceCleanupState": str(
                        workspace_result.get("cleanupState") or "retained"
                    ),
                    "workspaceTerminalReason": str(
                        workspace_result.get("reason") or ""
                    )[:2000],
                    "workspaceAttentionRequired": True,
                    "revision": int(task.get("revision") or 0) + 1,
                    "state": "completed",
                }
            )
            validate_kernel_contract("roomTask", task)
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=?,updated_at_ms=? "
                "WHERE task_id=?",
                (_json(task), int(now_ms), task_id),
            )
            root = self._root_row(conn, str(task["rootId"]))
            self._receipt(
                conn,
                root_id=str(task["rootId"]),
                command_id=None,
                receipt_kind="rejected",
                status="rejected",
                generation=int(root["generation"]),
                details={
                    "operation": "room_integrate",
                    "taskId": task_id,
                    "integrationRef": integration_ref,
                    "integrated": False,
                    "workspaceBindingId": binding_id,
                },
                now_ms=now_ms,
            )
            return task

    def record_workspace_delivery(
        self,
        task_id: str,
        *,
        delivery: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Bind the physical workspace delivery receipt to its canonical Task."""

        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json,state FROM room_kernel_tasks WHERE task_id=?",
                (_required(task_id, "task_id"),),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = json.loads(str(row["payload_json"]))
            if task.get("workspacePolicy") != "isolated_writable":
                raise RoomKernelFenceError(
                    "workspace delivery requires an isolated_writable Task"
                )
            workspace_delivery = delivery.get("workspaceDelivery")
            if workspace_delivery is not None and not isinstance(
                workspace_delivery,
                Mapping,
            ):
                raise RoomKernelFenceError(
                    "workspace delivery read model is invalid"
                )
            mapped = {
                "workspaceDeliveryRevision": _required(
                    delivery.get("deliveryRevision"),
                    "delivery revision",
                ),
                "workspaceDeliveryHead": _required(
                    delivery.get("deliveryHead"),
                    "delivery head",
                ),
                "workspaceDeliverySnapshotSha256": _required(
                    delivery.get("deliverySnapshotSha256"),
                    "delivery snapshot",
                ),
                "workspaceLifecycleState": str(
                    delivery.get("workspaceLifecycleState") or "delivered"
                ),
                "workspaceAttentionRequired": False,
            }
            if isinstance(workspace_delivery, Mapping):
                work_item_id = _required(
                    workspace_delivery.get("workItemId"),
                    "workspace delivery WorkItem",
                )
                owner_participant_id = _required(
                    workspace_delivery.get("ownerParticipantId"),
                    "workspace delivery owner",
                )
                if (
                    str(workspace_delivery.get("taskId") or "") != task_id
                    or owner_participant_id
                    != str(task.get("currentOwnerParticipantId") or "")
                    or str(
                        workspace_delivery.get("deliveryRevision") or ""
                    )
                    != mapped["workspaceDeliveryRevision"]
                    or (
                        str(task.get("workItemId") or "")
                        and str(task.get("workItemId")) != work_item_id
                    )
                ):
                    raise RoomKernelFenceError(
                        "workspace delivery read model does not match its Task"
                    )
                mapped["workItemId"] = work_item_id
                mapped["workspaceDelivery"] = dict(workspace_delivery)
            if all(task.get(key) == value for key, value in mapped.items()):
                return task
            task.update(mapped)
            task["revision"] = int(task.get("revision") or 0) + 1
            validate_kernel_contract("roomTask", task)
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=?,updated_at_ms=? "
                "WHERE task_id=?",
                (_json(task), int(now_ms), task_id),
            )
            root = self._root_row(conn, str(task["rootId"]))
            self._receipt(
                conn,
                root_id=str(task["rootId"]),
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "operation": "room_workspace_delivery",
                    "taskId": task_id,
                    "workspaceDeliveryRevision": mapped[
                        "workspaceDeliveryRevision"
                    ],
                    "workspaceDeliveryHead": mapped[
                        "workspaceDeliveryHead"
                    ],
                    "workspaceDeliverySnapshotSha256": mapped[
                        "workspaceDeliverySnapshotSha256"
                    ],
                    "workspaceLifecycleState": mapped[
                        "workspaceLifecycleState"
                    ],
                    "workspaceAttentionRequired": False,
                    "workspaceDeliveryManifestSha256": (
                        workspace_delivery.get("manifestSha256")
                        if isinstance(workspace_delivery, Mapping)
                        else None
                    ),
                    "workspaceDeliveredAtMs": (
                        workspace_delivery.get("deliveredAtMs")
                        if isinstance(workspace_delivery, Mapping)
                        else None
                    ),
                },
                now_ms=now_ms,
            )
            return task

    def record_workspace_work_started(
        self,
        task_id: str,
        *,
        lifecycle: Mapping[str, object],
        dispatch_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Project the durable workspace start receipt onto its canonical Task."""

        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                (_required(task_id, "task_id"),),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = json.loads(str(row["payload_json"]))
            if task.get("workspacePolicy") != "isolated_writable":
                return task
            mapped = {
                "workspaceLifecycleState": _required(
                    lifecycle.get("workspaceLifecycleState"),
                    "workspace lifecycle state",
                ),
                "workspaceAttentionRequired": bool(
                    lifecycle.get("workspaceAttentionRequired")
                ),
            }
            binding_id = str(lifecycle.get("workspaceBindingId") or "").strip()
            if binding_id and binding_id != str(
                task.get("workspaceBindingId") or ""
            ):
                raise RoomKernelFenceError(
                    "workspace start receipt does not match the Task binding"
                )
            if all(task.get(key) == value for key, value in mapped.items()):
                return task
            task.update(mapped)
            task["revision"] = int(task.get("revision") or 0) + 1
            validate_kernel_contract("roomTask", task)
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=?,updated_at_ms=? "
                "WHERE task_id=?",
                (_json(task), int(now_ms), task_id),
            )
            root = self._root_row(conn, str(task["rootId"]))
            self._receipt(
                conn,
                root_id=str(task["rootId"]),
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "operation": "room_workspace_work_started",
                    "taskId": task_id,
                    "dispatchId": _required(dispatch_id, "dispatch_id"),
                    **mapped,
                },
                now_ms=now_ms,
            )
            return task

    def dispatch(self, dispatch_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, object]:
        if conn is not None:
            return _dispatch_payload(self._dispatch_row(conn, dispatch_id))
        with self._connect() as owned:
            return _dispatch_payload(self._dispatch_row(owned, dispatch_id))

    def dispatch_is_active_alignment(self, dispatch_id: str) -> bool:
        """Return whether this live Dispatch is the Root's alignment or its resume chain."""

        with self._connect() as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            root = self._root_row(conn, str(dispatch["root_id"]))
            return self._is_active_alignment_dispatch_chain(
                conn,
                dispatch,
                root,
            )

    def dispatch_is_preparable_alignment(self, dispatch_id: str) -> bool:
        """Classify a queued Dispatch before its Runtime capability is prepared.

        Preparation happens before the Kernel leases the Dispatch, so the leaf
        is still pending. The stricter active classifier intentionally remains
        running-only for Tool and settlement fences.
        """

        with self._connect() as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            root = self._root_row(conn, str(dispatch["root_id"]))
            return self._is_alignment_dispatch_chain(
                conn,
                dispatch,
                root,
                leaf_states=("pending",),
            )

    def dispatch_is_runtime_alignment(self, dispatch_id: str) -> bool:
        """Classify the leased-to-running Runtime delivery window."""

        with self._connect() as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            root = self._root_row(conn, str(dispatch["root_id"]))
            return self._is_alignment_dispatch_chain(
                conn,
                dispatch,
                root,
                leaf_states=("leased", "running"),
            )


    def active_capability_peer_dispatch_ids(
        self,
        dispatch_id: str,
    ) -> list[str]:
        """Return live peer Dispatches in the current capability wave."""

        with self._connect() as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            return self._capability_peer_dispatch_ids(
                conn,
                dispatch,
                states=_ACTIVE_DISPATCH_STATES,
            )

    def close_barrier_dispatch_ids(self, dispatch_id: str) -> list[str]:
        """Return same-wave work whose public result must precede a closer."""

        with self._connect() as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            return self._capability_peer_dispatch_ids(
                conn,
                dispatch,
                states=(*_ACTIVE_DISPATCH_STATES, "committed"),
            )

    @staticmethod
    def _capability_peer_dispatch_ids(
        conn: sqlite3.Connection,
        dispatch: sqlite3.Row,
        *,
        states: tuple[str, ...],
    ) -> list[str]:
        current = _dispatch_payload(dispatch)
        rows = conn.execute(
            f"""SELECT dispatch_id,payload_json
                FROM room_kernel_dispatches
                WHERE root_id=? AND dispatch_id!=?
                  AND state IN ({','.join('?' for _ in states)})
                ORDER BY created_at_ms,dispatch_id""",
            (
                dispatch["root_id"],
                dispatch["dispatch_id"],
                *states,
            ),
        ).fetchall()
        epoch = int(current["capabilityEpoch"])
        return [
            str(row["dispatch_id"])
            for row in rows
            if int(
                json.loads(str(row["payload_json"]))["capabilityEpoch"]
            )
            == epoch
        ][:32]

    def has_active_capability_peer(self, dispatch_id: str) -> bool:
        """Return whether another live Dispatch shares this Root execution wave."""

        return bool(self.active_capability_peer_dispatch_ids(dispatch_id))

    def wait_target_dispatch(
        self,
        *,
        root_id: str,
        participant_id: str,
        generation: int,
        exclude_dispatch_id: str = "",
    ) -> dict[str, object]:
        """Bind a participant wait to one exact active or latest result."""

        root_id = _required(root_id, "root_id")
        participant_id = _required(participant_id, "participant_id")
        with self._connect() as conn:
            root = self._root_row(conn, root_id)
            if int(root["generation"]) != int(generation):
                raise RoomKernelFenceError(
                    "wait target generation is stale"
                )
            row = conn.execute(
                f"""SELECT * FROM room_kernel_dispatches
                    WHERE root_id=? AND target_participant_id=?
                      AND dispatch_id!=?
                      AND generation=?
                      AND state IN (
                        {','.join('?' for _ in (*_ACTIVE_DISPATCH_STATES, 'committed'))}
                      )
                    ORDER BY
                      CASE state
                        WHEN 'pending' THEN 0
                        WHEN 'leased' THEN 0
                        WHEN 'running' THEN 0
                        WHEN 'retry_wait' THEN 0
                        WHEN 'timer_wait' THEN 0
                        ELSE 1
                      END,
                      updated_at_ms DESC,
                      dispatch_id DESC
                    LIMIT 1""",
                (
                    root_id,
                    participant_id,
                    str(exclude_dispatch_id or ""),
                    int(generation),
                    *_ACTIVE_DISPATCH_STATES,
                    "committed",
                ),
            ).fetchone()
        if row is None:
            raise RoomKernelFenceError(
                "wait target has no active or committed Dispatch"
            )
        return _dispatch_payload(row)

    def commit(self, commit_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM room_kernel_commits WHERE commit_id = ?", (commit_id,)).fetchone()
            if row is None:
                raise KeyError(commit_id)
            return _room_commit_payload(conn, row["payload_json"])

    @staticmethod
    def _review_target_revision_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        task_ids: Sequence[str],
        pending_commit_ids: Mapping[str, str] | None = None,
        pending_task_snapshots: Mapping[
            str, Mapping[str, object]
        ] | None = None,
        review_snapshot: Mapping[str, object] | None = None,
        commit_not_after_ms: int | None = None,
    ) -> str:
        """Hash the exact durable or explicitly projected Task/Commit identity."""

        normalized_ids = sorted(
            {_required(value, "review task id") for value in task_ids}
        )
        if not normalized_ids:
            raise RoomKernelFenceError("Reviewer Task has no review target")
        target: list[dict[str, object]] = []
        for task_id in normalized_ids:
            row = conn.execute(
                """
                SELECT payload_json
                FROM room_kernel_tasks
                WHERE task_id=? AND root_id=?
                """,
                (task_id, _required(root_id, "root_id")),
            ).fetchone()
            if row is None:
                raise RoomKernelFenceError(
                    f"Reviewer target Task {task_id!r} is not in this Root"
                )
            payload = json.loads(str(row["payload_json"]))
            pending_commit_id = str(
                (pending_commit_ids or {}).get(task_id) or ""
            ).strip()
            pending_task = (pending_task_snapshots or {}).get(task_id)
            if pending_commit_id and pending_task is None:
                raise RoomKernelFenceError(
                    "pending review Commit requires its post-commit Task snapshot"
                )
            if pending_task is not None:
                if not pending_commit_id:
                    raise RoomKernelFenceError(
                        "pending review Task snapshot requires its pending Commit"
                    )
                if (
                    str(pending_task.get("taskId") or "") != task_id
                    or str(pending_task.get("rootId") or "")
                    != _required(root_id, "root_id")
                ):
                    raise RoomKernelFenceError(
                        "pending review Task snapshot identity does not match"
                    )
                validate_kernel_contract("roomTask", pending_task)
                target_payload = pending_task
            else:
                target_payload = payload
            if pending_commit_id:
                latest_commit_id: str | None = pending_commit_id
            else:
                commit = conn.execute(
                    """
                    SELECT c.commit_id
                    FROM room_kernel_commits c
                    JOIN room_kernel_dispatches dispatch
                      ON dispatch.dispatch_id = c.dispatch_id
                    WHERE dispatch.task_id = ?
                      AND dispatch.intent_kind IN ('execute','revise','retry')
                      AND (? IS NULL OR c.created_at_ms <= ?)
                    ORDER BY c.created_at_ms DESC, c.commit_id DESC
                    LIMIT 1
                    """,
                    (task_id, commit_not_after_ms, commit_not_after_ms),
                ).fetchone()
                latest_commit_id = (
                    str(commit["commit_id"]) if commit is not None else None
                )
            target.append(
                {
                    "taskId": task_id,
                    "revision": int(target_payload.get("revision") or 0),
                    "workspaceSnapshotSha256": str(
                        target_payload.get("workspaceSnapshotSha256") or ""
                    ),
                    "workspaceIntegrationRef": str(
                        target_payload.get("workspaceIntegrationRef") or ""
                    ),
                    "latestCommitId": latest_commit_id,
                }
            )
        if review_snapshot is not None:
            if str(review_snapshot.get("rootId") or "") != _required(
                root_id,
                "root_id",
            ):
                raise RoomKernelFenceError(
                    "Reviewer handoff snapshot belongs to another Root"
                )
            if review_snapshot.get("workspacePolicy") != "read_only":
                raise RoomKernelFenceError(
                    "Reviewer handoff snapshot must be read_only"
                )
            snapshot_sha256 = str(
                review_snapshot.get("workspaceSnapshotSha256") or ""
            ).strip()
            if not snapshot_sha256:
                raise RoomKernelFenceError(
                    "Reviewer handoff snapshot identity is missing"
                )
            snapshot_task_id = str(
                review_snapshot.get("taskId") or ""
            ).strip()
            if not snapshot_task_id:
                raise RoomKernelFenceError(
                    "Reviewer handoff snapshot Task identity is missing"
                )
            target.append(
                {
                    "taskId": str(review_snapshot.get("taskId") or ""),
                    "workspaceSnapshotSha256": snapshot_sha256,
                    "workspaceIntegrationRef": str(
                        review_snapshot.get("workspaceIntegrationRef") or ""
                    ),
                    "reviewHandoffSnapshot": True,
                }
            )
        digest = hashlib.sha256(
            json.dumps(
                target,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return f"sha256:{digest}"

    def review_target_revision(
        self,
        *,
        root_id: str,
        task_ids: Sequence[str],
        pending_commit_ids: Mapping[str, str] | None = None,
        pending_task_snapshots: Mapping[
            str, Mapping[str, object]
        ] | None = None,
        review_snapshot: Mapping[str, object] | None = None,
    ) -> str:
        """Return the immutable revision token for one review target."""

        with self._connect() as conn:
            return self._review_target_revision_locked(
                conn,
                root_id=root_id,
                task_ids=task_ids,
                pending_commit_ids=pending_commit_ids,
                pending_task_snapshots=pending_task_snapshots,
                review_snapshot=review_snapshot,
            )

    @staticmethod
    def _review_attempt_candidates_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Load each Review Task's exact newest review/resume attempt.

        A resumed review keeps the same Task identity but is dispatched with
        ``intentKind=resume``.  The attempt, its public-result bit, and its
        evidence must therefore be selected from the exact newest
        ``review``/``resume`` Dispatch rather than from the first collaboration
        child or the newest Commit for the Task by itself.
        """

        task_rows = conn.execute(
            """SELECT task_id,state,payload_json,updated_at_ms
               FROM room_kernel_tasks
               WHERE root_id=?
               ORDER BY updated_at_ms,task_id""",
            (_required(root_id, "root_id"),),
        ).fetchall()
        candidates: list[dict[str, object]] = []
        for task_row in task_rows:
            try:
                payload = json.loads(str(task_row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, Mapping):
                payload = {}
            review_state = str(payload.get("reviewState") or "not_required")
            if (
                str(payload.get("taskKind") or "") != "review"
                and review_state == "not_required"
            ):
                continue
            dispatch_rows = conn.execute(
                """SELECT *
                   FROM room_kernel_dispatches
                   WHERE root_id=? AND task_id=?
                     AND intent_kind IN ('review','resume')
                   ORDER BY created_at_ms,dispatch_id""",
                (root_id, str(task_row["task_id"])),
            ).fetchall()
            dispatch_row = (
                max(
                    dispatch_rows,
                    key=lambda value: (
                        int(value["updated_at_ms"] or 0),
                        int(value["created_at_ms"] or 0),
                        str(value["dispatch_id"]),
                    ),
                )
                if dispatch_rows
                else None
            )
            candidates.append(
                {
                    "taskId": str(task_row["task_id"]),
                    "taskState": str(task_row["state"]),
                    "payload": dict(payload),
                    "updatedAtMs": int(task_row["updated_at_ms"] or 0),
                    "dispatchRow": dispatch_row,
                    "reviewOfTaskIds": sorted(
                        {
                            str(value).strip()
                            for value in payload.get(
                                "reviewOfTaskIds",
                                (),
                            )
                            if str(value or "").strip()
                        }
                    ),
                }
            )
        attempts: list[dict[str, object]] = []
        for candidate in candidates:
            dispatch_row = candidate["dispatchRow"]
            dispatch_payload = (
                _dispatch_payload(dispatch_row)
                if isinstance(dispatch_row, sqlite3.Row)
                else None
            )
            commit_payload: dict[str, object] | None = None
            commit_id: str | None = None
            result_public = False
            if dispatch_row is not None:
                commit_row = conn.execute(
                    """SELECT commit_id,payload_json
                       FROM room_kernel_commits
                       WHERE root_id=? AND dispatch_id=?""",
                    (root_id, str(dispatch_row["dispatch_id"])),
                ).fetchone()
                if commit_row is not None:
                    decoded_commit = _room_commit_payload(
                        conn,
                        commit_row["payload_json"],
                    )
                    if not isinstance(decoded_commit, dict):
                        raise RoomKernelFenceError(
                            "review Dispatch Commit payload is corrupt"
                        )
                    commit_payload = decoded_commit
                    commit_id = str(commit_row["commit_id"])
                    if str(dispatch_row["state"]) == "committed":
                        result_public = (
                            RoomKernelStore._commit_result_is_public(
                                conn,
                                commit_id,
                                payload=decoded_commit,
                            )
                        )
            payload = dict(candidate["payload"])
            authority_rank = (
                max(1, int(payload.get("reviewRound") or 1)),
                int(payload.get("revision") or 0),
                max(
                    int(candidate["updatedAtMs"]),
                    (
                        int(dispatch_row["updated_at_ms"] or 0)
                        if dispatch_row is not None
                        else 0
                    ),
                    (
                        int(dispatch_row["created_at_ms"] or 0)
                        if dispatch_row is not None
                        else 0
                    ),
                ),
                str(candidate["taskId"]),
            )
            attempts.append(
                {
                    "taskId": str(candidate["taskId"]),
                    "taskState": str(candidate["taskState"]),
                    "payload": payload,
                    "updatedAtMs": int(candidate["updatedAtMs"]),
                    "dispatch": dispatch_payload,
                    "commit": commit_payload,
                    "commitId": commit_id,
                    "resultPublic": result_public,
                    "reviewOfTaskIds": list(
                        candidate["reviewOfTaskIds"]
                    ),
                    "_authorityRank": authority_rank,
                }
            )
        return attempts

    @staticmethod
    def _latest_review_attempts_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Resolve one latest Review attempt per reviewed Task lineage."""

        candidates = RoomKernelStore._review_attempt_candidates_locked(
            conn,
            root_id=root_id,
        )
        latest_by_reviewed_task: dict[str, dict[str, object]] = {}
        for candidate in candidates:
            lineage_ids = candidate.get("reviewOfTaskIds")
            if not isinstance(lineage_ids, list) or not lineage_ids:
                lineage_ids = [f"review-task:{candidate['taskId']}"]
            for reviewed_task_id in lineage_ids:
                key = str(reviewed_task_id)
                current = latest_by_reviewed_task.get(key)
                if current is None or tuple(
                    candidate["_authorityRank"]
                ) > tuple(current["_authorityRank"]):
                    latest_by_reviewed_task[key] = candidate
        selected: dict[tuple[str, str], dict[str, object]] = {}
        for candidate in latest_by_reviewed_task.values():
            dispatch = candidate.get("dispatch")
            dispatch_id = (
                str(dispatch.get("dispatchId") or "")
                if isinstance(dispatch, Mapping)
                else ""
            )
            selected[(str(candidate["taskId"]), dispatch_id)] = candidate
        return sorted(
            selected.values(),
            key=lambda value: tuple(value["_authorityRank"]),
        )

    @staticmethod
    def _latest_review_attempt_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object] | None:
        attempts = RoomKernelStore._latest_review_attempts_locked(
            conn,
            root_id=root_id,
        )
        return attempts[-1] if attempts else None

    def latest_review_attempt(
        self,
        root_id: str,
    ) -> dict[str, object] | None:
        """Return the newest review/resume Dispatch and its exact Commit."""

        with self._connect() as conn:
            attempt = self._latest_review_attempt_locked(
                conn,
                root_id=root_id,
            )
        if attempt is None:
            return None
        return {
            key: value
            for key, value in attempt.items()
            if not key.startswith("_")
        }

    def latest_review_attempts(
        self,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Return one authoritative Review attempt per reviewed Task."""

        with self._connect() as conn:
            attempts = self._latest_review_attempts_locked(
                conn,
                root_id=root_id,
            )
        return [
            {
                key: value
                for key, value in attempt.items()
                if not key.startswith("_")
            }
            for attempt in attempts
        ]

    def latest_task_commit(self, task_id: str) -> dict[str, object] | None:
        """Return the newest durable Commit produced for one Task."""

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT room_commit.payload_json
                FROM room_kernel_commits room_commit
                JOIN room_kernel_dispatches dispatch
                  ON dispatch.dispatch_id = room_commit.dispatch_id
                WHERE dispatch.task_id = ?
                ORDER BY room_commit.created_at_ms DESC,room_commit.commit_id DESC
                LIMIT 1
                """,
                (_required(task_id, "task_id"),),
            ).fetchone()
            if row is None:
                return None
            return _room_commit_payload(conn, row["payload_json"])

    def post_for_dispatch(
        self,
        dispatch_id: str,
    ) -> dict[str, object] | None:
        """Return the immutable public response owned by one Dispatch."""

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT p.payload_json
                   FROM room_kernel_posts p
                   JOIN room_kernel_dispatches d ON d.root_id = p.root_id
                   WHERE d.dispatch_id = ?
                   ORDER BY p.created_at_ms DESC, p.post_id DESC""",
                (_required(dispatch_id, "dispatch_id"),),
            ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if str(payload.get("dispatchId") or "") == dispatch_id:
                return payload
        return None

    @classmethod
    def _dispatch_acceptance_scope_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        dispatch: sqlite3.Row,
        dispatch_payload: Mapping[str, object],
    ) -> tuple[bool, set[str]]:
        rows = conn.execute(
            """SELECT * FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='accepted'
               ORDER BY created_at_ms,receipt_id""",
            (root_id,),
        ).fetchall()
        candidates: list[tuple[sqlite3.Row, Mapping[str, object]]] = []
        for row in rows:
            try:
                receipt = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(receipt, Mapping):
                continue
            details = receipt.get("details")
            if (
                isinstance(details, Mapping)
                and details.get("purpose")
                == "dispatch_acceptance_scope"
                and str(details.get("dispatchId") or "")
                == str(dispatch["dispatch_id"])
            ):
                candidates.append((row, receipt))
        if len(candidates) != 1:
            return False, set()
        row, receipt = candidates[0]
        if not cls._kernel_receipt_row_is_canonical_locked(row, receipt):
            return False, set()
        details = receipt.get("details")
        if not isinstance(details, Mapping):
            return False, set()
        criteria = _criteria(details.get("acceptanceCriterionIds"))
        valid = bool(
            str(receipt.get("rootId") or "") == root_id
            and str(details.get("taskId") or "")
            == str(dispatch["task_id"])
            and str(details.get("intentKind") or "")
            == str(dispatch["intent_kind"])
            and int(details.get("attempt") or 0)
            == int(dispatch_payload.get("attempt") or 0)
            and int(receipt.get("generation") or 0)
            == int(dispatch["generation"])
            and criteria
        )
        return valid, criteria if valid else set()

    @classmethod
    def _acceptance_evidence_owner_tasks_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, str]:
        """Return the Task that owns fresh evidence after a retry/revision.

        A ``revise`` handoff creates a new Task instead of another attempt on
        the original Task.  Selecting the latest attempt *per Task* therefore
        is not enough: without this criterion-level supersession, the parent
        Task's accepted evidence remains usable while the revision is pending
        or even after it fails.  The newest explicit retry/revision wave owns
        every criterion it covers until that exact Task produces a current
        Commit (and, when applicable, an integrated workspace revision).
        """

        rows = conn.execute(
            """SELECT d.rowid AS dispatch_sequence,d.*
               FROM room_kernel_dispatches d
               WHERE d.root_id=?
               ORDER BY d.created_at_ms,d.updated_at_ms,d.dispatch_id""",
            (_required(root_id, "root_id"),),
        ).fetchall()
        owners: dict[
            str,
            tuple[tuple[int, int, int, int, int, str], str],
        ] = {}
        root = cls._root_row(conn, _required(root_id, "root_id"))
        root_criteria = _criteria(
            json.loads(str(root["acceptance_criteria_json"]))
        )
        for row in rows:
            try:
                dispatch_payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(dispatch_payload, Mapping):
                continue
            attempt = int(dispatch_payload.get("attempt") or 0)
            intent = str(row["intent_kind"] or "")
            if intent not in {"revise", "retry"} and attempt <= 1:
                continue
            scope_valid, scope_criteria = (
                cls._dispatch_acceptance_scope_locked(
                    conn,
                    root_id=root_id,
                    dispatch=row,
                    dispatch_payload=dispatch_payload,
                )
            )
            # A missing/corrupt immutable scope must invalidate more evidence,
            # never less.  Conservatively take ownership of every Root AC.
            effective_criteria = (
                scope_criteria if scope_valid else root_criteria
            )
            rank = (
                # Task revisions are local to one Task identity.  A newly
                # created revise child can legitimately start at revision 0
                # after an older sibling reached revision 9, so durable
                # insertion chronology must decide cross-Task supersession.
                int(row["dispatch_sequence"] or 0),
                int(row["created_at_ms"] or 0),
                int(dispatch_payload.get("capabilityEpoch") or 0),
                attempt,
                int(row["updated_at_ms"] or 0),
                str(row["dispatch_id"]),
            )
            for criterion_id in effective_criteria:
                current = owners.get(criterion_id)
                if current is None or rank > current[0]:
                    owners[criterion_id] = (
                        rank,
                        str(row["task_id"]),
                    )
        return {
            criterion_id: owner_task_id
            for criterion_id, (_rank, owner_task_id) in owners.items()
        }

    @staticmethod
    def _prior_acceptance_evidence_refs_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        exclude_dispatch_id: str,
    ) -> dict[str, set[str]]:
        """Collect evidence already spent before a new evidence wave."""

        rows = conn.execute(
            """SELECT c.payload_json
               FROM room_kernel_commits c
               JOIN room_kernel_dispatches d ON d.dispatch_id=c.dispatch_id
               WHERE c.root_id=? AND d.dispatch_id!=?
               ORDER BY c.created_at_ms,c.commit_id""",
            (
                _required(root_id, "root_id"),
                _required(exclude_dispatch_id, "exclude_dispatch_id"),
            ),
        ).fetchall()
        stale: dict[str, set[str]] = {}
        for row in rows:
            try:
                payload = _room_commit_payload(conn, row["payload_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            gate = payload.get("qualityGateReceipt")
            if not isinstance(gate, Mapping):
                continue
            for item in gate.get("items") or ():
                if not isinstance(item, Mapping) or item.get("status") != "pass":
                    continue
                criterion_id = str(item.get("criterionId") or "").strip()
                if not criterion_id:
                    continue
                stale.setdefault(criterion_id, set()).update(
                    str(value).strip()
                    for value in item.get("evidenceRefs") or ()
                    if str(value or "").strip()
                )
        return stale

    @classmethod
    def _authoritative_acceptance_commit_payloads_locked(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Select current-attempt evidence under criterion supersession."""

        evidence_owners = (
            cls._acceptance_evidence_owner_tasks_locked(
                conn,
                root_id=root_id,
            )
        )
        task_rows = conn.execute(
            """SELECT task_id,state,payload_json
               FROM room_kernel_tasks WHERE root_id=?
               ORDER BY task_id""",
            (root_id,),
        ).fetchall()
        selected: list[
            tuple[int, str, str, dict[str, object], dict[str, object]]
        ] = []
        for task_row in task_rows:
            try:
                task_payload = json.loads(str(task_row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(task_payload, Mapping):
                continue
            task_kind = str(task_payload.get("taskKind") or "work")
            if task_kind == "report" or str(task_row["state"]) != "completed":
                continue
            if (
                task_payload.get("workspacePolicy") == "isolated_writable"
                and (
                    task_payload.get("workspaceIntegrationState") != "applied"
                    or not str(
                        task_payload.get("workspaceIntegrationRef") or ""
                    ).strip()
                )
            ):
                continue
            if task_kind == "review":
                if task_payload.get("reviewState") not in {
                    "accepted",
                    "accepted_with_notes",
                }:
                    continue
                target_ids = [
                    str(value)
                    for value in task_payload.get("reviewOfTaskIds", ())
                    if str(value or "").strip()
                ]
                try:
                    current_revision = (
                        RoomKernelStore._review_target_revision_locked(
                            conn,
                            root_id=root_id,
                            task_ids=target_ids,
                            review_snapshot=task_payload,
                        )
                    )
                except (
                    RoomKernelFenceError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue
                if current_revision != str(
                    task_payload.get("reviewTargetRevision") or ""
                ):
                    continue
            dispatch_rows = conn.execute(
                """SELECT d.*,c.commit_id,c.payload_json AS commit_payload_json,
                          c.created_at_ms AS commit_created_at_ms
                   FROM room_kernel_dispatches d
                   LEFT JOIN room_kernel_commits c
                     ON c.dispatch_id=d.dispatch_id
                   WHERE d.root_id=? AND d.task_id=?
                     AND d.intent_kind!='close'
                   ORDER BY d.updated_at_ms,d.created_at_ms,d.dispatch_id""",
                (root_id, str(task_row["task_id"])),
            ).fetchall()
            if not dispatch_rows:
                continue

            def authority_rank(row: sqlite3.Row) -> tuple[int, int, int, str]:
                try:
                    dispatch_payload = json.loads(str(row["payload_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    dispatch_payload = {}
                return (
                    int(
                        dispatch_payload.get("attempt") or 0
                        if isinstance(dispatch_payload, Mapping)
                        else 0
                    ),
                    int(row["updated_at_ms"] or 0),
                    int(row["created_at_ms"] or 0),
                    str(row["dispatch_id"]),
                )

            dispatch = max(dispatch_rows, key=authority_rank)
            if (
                str(dispatch["state"]) != "committed"
                or dispatch["commit_id"] is None
                or dispatch["commit_payload_json"] is None
            ):
                continue
            try:
                raw_commit = json.loads(
                    str(dispatch["commit_payload_json"])
                )
                if not isinstance(raw_commit, Mapping):
                    continue
                commit_payload = _room_commit_payload(
                    conn,
                    dispatch["commit_payload_json"],
                )
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
                RoomKernelFenceError,
            ):
                continue
            if not cls._acceptance_commit_authority_valid_locked(
                conn,
                root_id=root_id,
                task_payload=task_payload,
                dispatch=dispatch,
                commit_id=str(dispatch["commit_id"]),
                raw_commit=raw_commit,
            ):
                continue
            selected.append(
                (
                    int(dispatch["commit_created_at_ms"] or 0),
                    str(dispatch["commit_id"]),
                    str(task_row["task_id"]),
                    dict(task_payload),
                    commit_payload,
                )
            )
        authoritative: list[dict[str, object]] = []
        for (
            _created_at_ms,
            _commit_id,
            task_id,
            task_payload,
            payload,
        ) in sorted(selected):
            gate = payload.get("qualityGateReceipt")
            if not isinstance(gate, Mapping):
                authoritative.append(payload)
                continue
            task_kind = str(task_payload.get("taskKind") or "work")
            review_targets = {
                str(value).strip()
                for value in task_payload.get("reviewOfTaskIds", ())
                if str(value or "").strip()
            }
            items: list[dict[str, object]] = []
            allowed_refs: list[str] = []
            allowed_criteria: list[str] = []
            for item in gate.get("items") or ():
                if not isinstance(item, Mapping):
                    continue
                criterion_id = str(item.get("criterionId") or "").strip()
                owner_task_id = evidence_owners.get(criterion_id)
                allowed = (
                    owner_task_id is None
                    or task_id == owner_task_id
                    or (
                        task_kind == "review"
                        and owner_task_id in review_targets
                    )
                )
                if not allowed:
                    continue
                copied = dict(item)
                items.append(copied)
                if copied.get("status") == "pass":
                    allowed_criteria.append(criterion_id)
                    allowed_refs.extend(
                        str(value).strip()
                        for value in copied.get("evidenceRefs") or ()
                        if str(value or "").strip()
                    )
            authoritative.append(
                {
                    **payload,
                    "qualityGateReceipt": {**dict(gate), "items": items},
                    "evidenceRefs": list(dict.fromkeys(allowed_refs)),
                    "requirementCoverage": list(
                        dict.fromkeys(allowed_criteria)
                    ),
                }
            )
        return authoritative

    @staticmethod
    def _acceptance_evidence(
        conn: sqlite3.Connection,
        root_id: str,
        criteria: set[str],
    ) -> dict[str, set[str]]:
        """Unbounded criterion -> evidence refs derived from durable Commits.

        `accepted_evidence_by_criterion` is a bounded model-facing projection
        and must never be used as a gate. This one keeps every ref so terminal
        decisions cannot be changed by a truncation limit.
        """

        proven: dict[str, set[str]] = {}
        if not criteria:
            return proven
        payloads = (
            RoomKernelStore._authoritative_acceptance_commit_payloads_locked(
                conn,
                root_id=root_id,
            )
        )
        for payload in payloads:
            gate = payload.get("qualityGateReceipt")
            if not isinstance(gate, Mapping):
                continue
            for item in gate.get("items") or []:
                if not isinstance(item, Mapping) or item.get("status") != "pass":
                    continue
                criterion_id = str(item.get("criterionId") or "").strip()
                if criterion_id not in criteria:
                    continue
                refs = {
                    str(value).strip()
                    for value in item.get("evidenceRefs") or []
                    if str(value or "").strip()
                }
                if refs:
                    proven.setdefault(criterion_id, set()).update(refs)
        return proven

    def accepted_evidence_by_criterion(
        self,
        root_id: str,
    ) -> dict[str, list[str]]:
        """Project evidence already accepted by the Kernel for one Root."""

        with self._connect() as conn:
            root = self._root_row(conn, root_id)
            criterion_order = [
                str(value)
                for value in json.loads(
                    str(root["acceptance_criteria_json"])
                )
                if str(value).strip()
            ]
            accepted_criteria = set(criterion_order)
            payloads = self._authoritative_acceptance_commit_payloads_locked(
                conn,
                root_id=root_id,
            )
            collected: dict[str, list[str]] = {}
            for payload in payloads:
                gate = payload.get("qualityGateReceipt")
                if not isinstance(gate, Mapping):
                    continue
                for item in gate.get("items") or []:
                    if (
                        not isinstance(item, Mapping)
                        or item.get("status") != "pass"
                    ):
                        continue
                    criterion_id = str(item.get("criterionId") or "").strip()
                    if criterion_id not in accepted_criteria:
                        continue
                    target = collected.setdefault(criterion_id, [])
                    for raw_ref in item.get("evidenceRefs") or []:
                        evidence_ref = str(raw_ref or "").strip()
                        if evidence_ref and evidence_ref not in target:
                            target.append(evidence_ref)
                            if len(target) > 64:
                                del target[0]
        projected: dict[str, list[str]] = {}
        remaining = 32
        for ref_index in range(4):
            for criterion_id in criterion_order:
                refs = collected.get(criterion_id, ())[-4:]
                if ref_index >= len(refs) or remaining <= 0:
                    continue
                projected.setdefault(criterion_id, []).append(
                    refs[ref_index]
                )
                remaining -= 1
        return projected

    def continuation(self, commit_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_kernel_continuations WHERE commit_id=?", (commit_id,)
            ).fetchone()
            if row is None:
                raise KeyError(commit_id)
            payload = _room_continuation_payload(conn, row)
        task_transfer = (
            payload.get("taskTransfer")
            if isinstance(payload, Mapping)
            else None
        )
        return {
            "continuationId": str(row["continuation_id"]),
            "rootId": str(row["root_id"]),
            "taskId": str(row["task_id"]),
            "parentDispatchId": str(row["parent_dispatch_id"]),
            "transferredTaskId": (
                task_transfer.get("taskId")
                if isinstance(task_transfer, Mapping)
                else None
            ),
            "childDispatchId": row["child_dispatch_id"],
            "commitId": str(row["commit_id"]),
            "decision": str(row["decision"]),
            "state": str(row["state"]),
            "payload": payload,
        }

    def collaboration_receipt(
        self,
        *,
        parent_dispatch_id: str,
        invocation_receipt_id: str,
    ) -> dict[str, object] | None:
        """Return the original enqueue receipt for an idempotent Tool replay."""

        with self._connect() as conn:
            parent = self._dispatch_row(conn, parent_dispatch_id)
            rows = conn.execute(
                """SELECT payload_json FROM room_kernel_receipts
                   WHERE root_id=? AND receipt_kind IN ('accepted','duplicate')
                   ORDER BY created_at_ms, receipt_id""",
                (str(parent["root_id"]),),
            ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            details = payload.get("details")
            if (
                isinstance(details, Mapping)
                and details.get("parentDispatchId") == parent_dispatch_id
                and details.get("invocationReceiptId")
                == invocation_receipt_id
            ):
                return payload
        return None
    def pending_user_wait(
        self,
        room_id: str,
        *,
        root_id: str = "",
        question_post_id: str = "",
    ) -> dict[str, object] | None:
        """Return the one unresolved wait-for-user continuation in a Room."""

        expected_root_id = str(root_id or "").strip()
        expected_question_post_id = str(question_post_id or "").strip()
        if bool(expected_root_id) != bool(expected_question_post_id):
            raise ValueError(
                "pending user wait lookup requires Root and question identity"
            )

        with self._connect() as conn:
            if expected_root_id:
                state_fence = (
                    "r.state IN ('waiting','running') "
                    "AND c.state IN ('applied','resumed') AND c.root_id = ?"
                )
                parameters: tuple[object, ...] = (
                    _required(room_id, "room_id"),
                    expected_root_id,
                )
            else:
                state_fence = "r.state = 'waiting' AND c.state = 'applied'"
                parameters = (_required(room_id, "room_id"),)
            rows = conn.execute(
                f"""
                SELECT c.*, r.generation AS root_generation,
                       d.target_participant_id, d.target_session_id,
                       d.generation AS dispatch_generation,
                       d.hop_count AS parent_hop_count,
                       d.depth AS parent_depth
                FROM room_kernel_continuations c
                JOIN room_kernel_roots r ON r.root_id = c.root_id
                JOIN room_kernel_dispatches d ON d.dispatch_id = c.parent_dispatch_id
                WHERE r.room_id = ? AND c.decision = 'wait'
                  AND d.target_participant_id = r.facilitator_participant_id
                  AND {state_fence}
                ORDER BY c.created_at_ms DESC, c.continuation_id DESC
                """,
                parameters,
            ).fetchall()
            for row in rows:
                payload = _room_continuation_payload(conn, row)
                if payload.get("waitingFor") != "user":
                    continue
                candidate_root_id = str(row["root_id"])
                candidate_question_post_id = (
                    _room_continuation_question_post_id(conn, row)
                )
                if expected_root_id and (
                    candidate_root_id != expected_root_id
                    or candidate_question_post_id
                    != expected_question_post_id
                ):
                    continue
                return {
                    "continuationId": str(row["continuation_id"]),
                    "questionPostId": candidate_question_post_id,
                    "rootId": candidate_root_id,
                    "taskId": str(row["task_id"]),
                    "parentDispatchId": str(row["parent_dispatch_id"]),
                    "generation": int(row["dispatch_generation"]),
                    "parentHopCount": int(row["parent_hop_count"]),
                    "parentDepth": int(row["parent_depth"]),
                    "targetParticipantId": str(row["target_participant_id"]),
                    "targetSessionId": str(row["target_session_id"]),
                    "state": str(row["state"]),
                    "payload": payload,
                }
        return None
    def resume_user_wait(
        self,
        *,
        continuation_id: str,
        dispatch_payload: Mapping[str, object],
        question_post_id: str,
        answer_root_id: str,
        answer_post_id: str,
        answer_anchor_id: str,
        now_ms: int,
        _conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        """Atomically consume a user wait and enqueue its one resume Dispatch."""

        validate_kernel_contract("dispatchEnvelope", dispatch_payload)
        with self._write_connection(_conn) as conn:
            continuation = conn.execute(
                "SELECT * FROM room_kernel_continuations "
                "WHERE continuation_id = ?",
                (_required(continuation_id, "continuation_id"),),
            ).fetchone()
            if continuation is None:
                raise RoomKernelFenceError("user wait continuation is missing")
            continuation_state = str(continuation["state"])
            if continuation_state not in {"applied", "resumed"}:
                raise RoomKernelFenceError("user wait continuation was already resumed")
            continuation_payload = _room_continuation_payload(
                conn,
                continuation,
            )
            if (
                not isinstance(continuation_payload, Mapping)
                or continuation_payload.get("waitingFor") != "user"
            ):
                raise RoomKernelFenceError(
                    "continuation is not a wait-for-user"
                )
            parent = self._dispatch_row(
                conn,
                str(continuation["parent_dispatch_id"]),
            )
            root = self._root_row(conn, str(continuation["root_id"]))
            expected_question_post_id = (
                _room_continuation_question_post_id(conn, continuation)
            )
            if (
                _required(question_post_id, "question_post_id")
                != expected_question_post_id
                or _required(answer_root_id, "answer_root_id")
                != str(root["root_id"])
            ):
                raise RoomKernelFenceError(
                    "clarification answer does not match its question and Root"
                )
            if (
                dispatch_payload.get("rootId") != root["root_id"]
                or dispatch_payload.get("taskId") != continuation["task_id"]
                or dispatch_payload.get("parentDispatchId")
                != parent["dispatch_id"]
                or dispatch_payload.get("targetParticipantId")
                != parent["target_participant_id"]
                or int(dispatch_payload.get("generation", -1))
                != int(parent["generation"])
            ):
                raise RoomKernelFenceError(
                    "user wait resume Dispatch does not match its parent"
                )
            normalized_answer_post_id = _required(
                answer_post_id,
                "answer_post_id",
            )
            normalized_answer_anchor_id = _required(
                answer_anchor_id,
                "answer_anchor_id",
            )
            if continuation_state == "resumed":
                if (
                    continuation_payload.get("answerPostId")
                    != normalized_answer_post_id
                    or continuation_payload.get("answerAnchorId")
                    != normalized_answer_anchor_id
                    or continuation_payload.get("resumeDispatchId")
                    != dispatch_payload.get("dispatchId")
                ):
                    raise RoomKernelFenceError(
                        "user wait resume identity was rebound"
                    )
                resumed, _ = self._enqueue_dispatch(
                    conn,
                    dispatch_payload,
                    shadow_only=self.mode
                    not in {"cohort", "test", "kernel_only"},
                    now_ms=now_ms,
                )
                receipt_row = None
                resume_receipt_id = str(
                    continuation_payload.get("resumeReceiptId") or ""
                ).strip()
                if resume_receipt_id:
                    receipt_row = conn.execute(
                        "SELECT payload_json FROM room_kernel_receipts "
                        "WHERE receipt_id=?",
                        (resume_receipt_id,),
                    ).fetchone()
                if receipt_row is None:
                    candidates = conn.execute(
                        """SELECT payload_json FROM room_kernel_receipts
                           WHERE root_id=? AND receipt_kind='accepted'
                           ORDER BY created_at_ms,receipt_id""",
                        (root["root_id"],),
                    ).fetchall()
                    for candidate in candidates:
                        candidate_payload = json.loads(
                            str(candidate["payload_json"])
                        )
                        candidate_details = candidate_payload.get("details")
                        if (
                            isinstance(candidate_details, Mapping)
                            and candidate_details.get("continuationId")
                            == continuation_id
                            and candidate_details.get("resumedDispatchId")
                            == resumed["dispatchId"]
                            and candidate_details.get("answerPostId")
                            == normalized_answer_post_id
                            and candidate_details.get("answerAnchorId")
                            == normalized_answer_anchor_id
                        ):
                            receipt_row = candidate
                            break
                if receipt_row is None:
                    raise RoomKernelFenceError(
                        "resumed user wait is missing its authoritative receipt"
                    )
                return {
                    "receipt": json.loads(str(receipt_row["payload_json"])),
                    "dispatch": dict(resumed),
                    "continuationId": continuation_id,
                }

            resumed, _ = self._enqueue_dispatch(
                conn,
                dispatch_payload,
                shadow_only=self.mode
                not in {"cohort", "test", "kernel_only"},
                now_ms=now_ms,
            )
            updated_payload = _decode_room_continuation_payload(
                continuation["payload_json"]
            )
            updated_payload.update(
                {
                    "answerPostId": normalized_answer_post_id,
                    "answerAnchorId": normalized_answer_anchor_id,
                    "resumeDispatchId": str(resumed["dispatchId"]),
                }
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='active',updated_at_ms=? "
                "WHERE task_id=?",
                (int(now_ms), continuation["task_id"]),
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='running',updated_at_ms=? "
                "WHERE root_id=?",
                (int(now_ms), root["root_id"]),
            )
            self._record_intake_phase_locked(
                conn,
                root_id=str(root["root_id"]),
                phase="aligning",
                clarification_occurred=True,
                source="user_answer",
                generation=int(parent["generation"]),
                details={
                    "continuationId": continuation_id,
                    "questionPostId": expected_question_post_id,
                    "answerPostId": normalized_answer_post_id,
                    "resumeDispatchId": str(resumed["dispatchId"]),
                },
                now_ms=now_ms,
            )
            receipt = self._receipt(
                conn,
                root_id=str(root["root_id"]),
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(parent["generation"]),
                details={
                    "continuationId": continuation_id,
                    "parentDispatchId": str(parent["dispatch_id"]),
                    "questionPostId": expected_question_post_id,
                    "resumedDispatchId": str(resumed["dispatchId"]),
                    "answerPostId": normalized_answer_post_id,
                    "answerAnchorId": normalized_answer_anchor_id,
                },
                now_ms=now_ms,
            )
            updated_payload["resumeReceiptId"] = str(receipt["receiptId"])
            conn.execute(
                """UPDATE room_kernel_continuations
                   SET state='resumed',payload_json=?
                   WHERE continuation_id=? AND state='applied'""",
                (
                    _json(updated_payload),
                    continuation_id,
                ),
            )
            return {
                "receipt": receipt,
                "dispatch": dict(resumed),
                "continuationId": continuation_id,
            }

    def resume_user_wait_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        continuation_id: str,
        dispatch_payload: Mapping[str, object],
        question_post_id: str,
        answer_root_id: str,
        answer_post_id: str,
        answer_anchor_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Consume a user wait inside a caller-owned Room transaction."""

        return self.resume_user_wait(
            continuation_id=continuation_id,
            dispatch_payload=dispatch_payload,
            question_post_id=question_post_id,
            answer_root_id=answer_root_id,
            answer_post_id=answer_post_id,
            answer_anchor_id=answer_anchor_id,
            now_ms=now_ms,
            _conn=conn,
        )

    @staticmethod
    def _user_wait_answer_preparation_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        continuation_id: str,
    ) -> tuple[dict[str, object], Mapping[str, object]] | None:
        rows = conn.execute(
            """SELECT payload_json FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='accepted'
               ORDER BY created_at_ms,rowid""",
            (root_id,),
        ).fetchall()
        for row in rows:
            receipt = json.loads(str(row["payload_json"]))
            details = (
                receipt.get("details")
                if isinstance(receipt, Mapping)
                else None
            )
            if (
                isinstance(details, Mapping)
                and details.get("purpose")
                == "user_wait_answer_prepared"
                and details.get("continuationId") == continuation_id
            ):
                return receipt, details
        return None

    def user_wait_answer_preparation_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        continuation_id: str,
    ) -> dict[str, object] | None:
        """Read a prepared clarification answer under the caller's write lock."""

        prepared = self._user_wait_answer_preparation_locked(
            conn,
            root_id=_required(root_id, "root_id"),
            continuation_id=_required(
                continuation_id,
                "continuation_id",
            ),
        )
        if prepared is None:
            return None
        receipt, details = prepared
        return {
            "receipt": dict(receipt),
            "details": dict(details),
        }

    def prepare_user_wait_answer_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        continuation_id: str,
        dispatch_payload: Mapping[str, object],
        question_post_id: str,
        answer_root_id: str,
        answer_post_id: str,
        answer_anchor_id: str,
        client_message_id: str,
        answer_display_text: str,
        answer_kind: str,
        topic_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Reserve one canonical answer identity without releasing work."""

        validate_kernel_contract("dispatchEnvelope", dispatch_payload)
        continuation_id = _required(continuation_id, "continuation_id")
        answer_root_id = _required(answer_root_id, "answer_root_id")
        continuation = conn.execute(
            "SELECT * FROM room_kernel_continuations WHERE continuation_id=?",
            (continuation_id,),
        ).fetchone()
        if continuation is None:
            raise RoomKernelFenceError("user wait continuation is missing")
        root = self._root_row(conn, str(continuation["root_id"]))
        parent = self._dispatch_row(
            conn,
            str(continuation["parent_dispatch_id"]),
        )
        expected_details = {
            "purpose": "user_wait_answer_prepared",
            "continuationId": continuation_id,
            "questionPostId": _required(
                question_post_id,
                "question_post_id",
            ),
            "clientMessageId": _required(
                client_message_id,
                "client_message_id",
            ),
            "answerPostId": _required(answer_post_id, "answer_post_id"),
            "answerAnchorId": _required(
                answer_anchor_id,
                "answer_anchor_id",
            ),
            "answerDisplayText": _required(
                answer_display_text,
                "answer_display_text",
            ),
            "answerKind": answer_kind,
            "topicId": str(topic_id or ""),
            "plannedResumeDispatch": dict(dispatch_payload),
        }
        prior = self.user_wait_answer_preparation_in_transaction(
            conn,
            root_id=str(root["root_id"]),
            continuation_id=continuation_id,
        )
        if prior is not None:
            receipt = prior["receipt"]
            details = prior["details"]
            if dict(details) != expected_details:
                raise RoomKernelFenceError(
                    "user wait already has a different prepared answer"
                )
            return {"receipt": receipt, "created": False}
        continuation_payload = _room_continuation_payload(
            conn,
            continuation,
        )
        expected_question_post_id = (
            _room_continuation_question_post_id(conn, continuation)
        )
        if (
            str(continuation["state"]) != "applied"
            or str(root["state"]) != "waiting"
            or not isinstance(continuation_payload, Mapping)
            or continuation_payload.get("waitingFor") != "user"
            or str(root["root_id"]) != answer_root_id
            or expected_details["questionPostId"]
            != expected_question_post_id
            or str(parent["target_participant_id"])
            != str(root["facilitator_participant_id"])
            or dispatch_payload.get("rootId") != root["root_id"]
            or dispatch_payload.get("taskId") != continuation["task_id"]
            or dispatch_payload.get("parentDispatchId")
            != parent["dispatch_id"]
            or dispatch_payload.get("targetParticipantId")
            != parent["target_participant_id"]
            or int(dispatch_payload.get("generation", -1))
            != int(parent["generation"])
            or answer_kind not in {"option", "custom"}
        ):
            raise RoomKernelFenceError(
                "clarification answer preparation lost its waiting fence"
            )
        answer_post = conn.execute(
            "SELECT root_id FROM room_kernel_posts WHERE post_id=?",
            (expected_details["answerPostId"],),
        ).fetchone()
        answer_anchor = conn.execute(
            """SELECT root_id FROM room_v2_requirement_anchors
               WHERE anchor_id=?""",
            (expected_details["answerAnchorId"],),
        ).fetchone()
        if (
            answer_post is None
            or str(answer_post["root_id"]) != answer_root_id
            or answer_anchor is None
            or str(answer_anchor["root_id"]) != answer_root_id
        ):
            raise RoomKernelFenceError(
                "clarification answer preparation has no durable Post and anchor"
            )
        receipt = self._receipt(
            conn,
            root_id=answer_root_id,
            command_id=None,
            receipt_kind="accepted",
            status="applied",
            generation=int(parent["generation"]),
            details=expected_details,
            now_ms=now_ms,
        )
        return {"receipt": receipt, "created": True}

    def resume_user_wait_after_public_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        continuation_id: str,
        dispatch_payload: Mapping[str, object],
        question_post_id: str,
        answer_root_id: str,
        answer_post: Mapping[str, object],
        answer_anchor_id: str,
        client_message_id: str,
        answer_display_text: str,
        answer_kind: str,
        topic_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Release one resume Dispatch only after its answer is public."""

        answer_post_id = _required(
            answer_post.get("postId"),
            "answer Post id",
        )
        room_id = _required(answer_post.get("roomId"), "answer Room")
        publication_source = answer_post.get("publicationSource")
        client_message_id = _required(
            client_message_id,
            "answer client message id",
        )
        stored_post_row = conn.execute(
            "SELECT payload_json FROM room_kernel_posts WHERE post_id=?",
            (answer_post_id,),
        ).fetchone()
        stored_anchor_row = conn.execute(
            """SELECT root_id FROM room_v2_requirement_anchors
               WHERE anchor_id=?""",
            (_required(answer_anchor_id, "answer anchor id"),),
        ).fetchone()
        stored_post = (
            json.loads(str(stored_post_row["payload_json"]))
            if stored_post_row is not None
            else None
        )
        preparation = self._user_wait_answer_preparation_locked(
            conn,
            root_id=answer_root_id,
            continuation_id=continuation_id,
        )
        expected_preparation = {
            "purpose": "user_wait_answer_prepared",
            "continuationId": continuation_id,
            "questionPostId": question_post_id,
            "clientMessageId": client_message_id,
            "answerPostId": answer_post_id,
            "answerAnchorId": answer_anchor_id,
            "answerDisplayText": answer_display_text,
            "answerKind": answer_kind,
            "topicId": str(topic_id or ""),
            "plannedResumeDispatch": dict(dispatch_payload),
        }
        if (
            preparation is None
            or dict(preparation[1]) != expected_preparation
            or not isinstance(stored_post, Mapping)
            or any(
                answer_post.get(key) != value
                for key, value in stored_post.items()
            )
            or stored_anchor_row is None
            or str(stored_anchor_row["root_id"] or "") != answer_root_id
            or str(answer_post.get("roomId") or "") != room_id
            or str(answer_post.get("rootId") or "") != answer_root_id
            or str(answer_post.get("content") or "")
            != answer_display_text
            or not isinstance(publication_source, Mapping)
            or str(publication_source.get("kind") or "")
            != "user"
            or str(publication_source.get("ref") or "")
            != client_message_id
            or answer_kind not in {"option", "custom"}
        ):
            raise RoomKernelFenceError(
                "durable clarification answer does not match its public authorization"
            )
        authorization = self._public_user_message_authorization_locked(
            conn,
            room_id=room_id,
            root_id=answer_root_id,
            topic_id=str(topic_id or ""),
            post_id=answer_post_id,
            client_message_id=client_message_id,
            content=answer_display_text,
            created_at_ms=int(answer_post["createdAtMs"]),
            attachment_receipts=tuple(answer_post.get("attachments") or ()),
            answer_to_post_id=question_post_id,
            answer_display_text=answer_display_text,
            answer_kind=answer_kind,
            error_subject="clarification answer",
        )
        resumed = self.resume_user_wait_in_transaction(
            conn,
            continuation_id=continuation_id,
            dispatch_payload=dispatch_payload,
            question_post_id=question_post_id,
            answer_root_id=answer_root_id,
            answer_post_id=answer_post_id,
            answer_anchor_id=answer_anchor_id,
            now_ms=now_ms,
        )
        return {**resumed, "authorization": authorization}

    def definition_fence(
        self,
        *,
        root_id: str,
        dispatch_id: str = "",
        invocation_receipt_id: str = "",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object] | None:
        """Read the explicit post-definition context fence, if one exists."""

        def read(active: sqlite3.Connection) -> dict[str, object] | None:
            rows = active.execute(
                """SELECT payload_json FROM room_kernel_receipts
                   WHERE root_id=? AND receipt_kind='accepted'
                   ORDER BY created_at_ms,receipt_id""",
                (_required(root_id, "root_id"),),
            ).fetchall()
            for row in rows:
                payload = json.loads(str(row["payload_json"]))
                details = payload.get("details")
                if not isinstance(details, Mapping):
                    continue
                if details.get("operation") != "room_define":
                    continue
                if dispatch_id and str(details.get("dispatchId") or "") != dispatch_id:
                    continue
                if (
                    invocation_receipt_id
                    and str(details.get("invocationReceiptId") or "")
                    != invocation_receipt_id
                ):
                    continue
                return {"receipt": payload, **dict(details)}
            return None

        if conn is not None:
            return read(conn)
        with self._connect() as active:
            return read(active)

    def revise_definition_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        dispatch_id: str,
        invocation_receipt_id: str,
        task_payload: Mapping[str, object],
        acceptance_criteria: Sequence[str],
        independent_review_required: bool,
        execute_dispatch_payload: Mapping[str, object],
        details: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Fence alignment and atomically publish the next intake phase."""

        root = self._root_row(conn, _required(root_id, "root_id"))
        dispatch = self._dispatch_row(conn, _required(dispatch_id, "dispatch_id"))
        existing = self.definition_fence(
            root_id=str(root["root_id"]),
            invocation_receipt_id=invocation_receipt_id,
            conn=conn,
        )
        if existing is not None:
            execute_dispatch_id = str(
                existing.get("executionDispatchId") or ""
            )
            return {
                "receipt": existing["receipt"],
                "root": self.root(str(root["root_id"]), conn=conn),
                "task": self.task(str(dispatch["task_id"]), conn=conn),
                "dispatch": (
                    self.dispatch(execute_dispatch_id, conn=conn)
                    if execute_dispatch_id
                    else None
                ),
                "intake": self.intake_state(str(root["root_id"]), conn=conn),
                "idempotent": True,
            }
        if not self._is_active_alignment_dispatch_chain(conn, dispatch, root):
            raise RoomKernelFenceError(
                "room_define requires the active facilitator alignment Dispatch"
            )
        if (
            str(task_payload.get("rootId") or "") != str(root["root_id"])
            or str(task_payload.get("taskId") or "") != str(dispatch["task_id"])
            or str(task_payload.get("currentOwnerParticipantId") or "")
            != str(root["facilitator_participant_id"])
        ):
            raise RoomKernelFenceError(
                "room_define Task binding does not match the alignment Dispatch"
            )
        criteria = tuple(
            dict.fromkeys(str(value).strip() for value in acceptance_criteria if str(value).strip())
        )
        if not criteria:
            raise RoomKernelFenceError("room_define requires acceptance criteria")
        validate_kernel_contract("roomTask", task_payload)
        if _criteria(task_payload.get("acceptanceCriterionIds")) != set(criteria):
            raise RoomKernelFenceError(
                "room_define Task criteria must exactly match definition Root criteria"
            )
        current_task = conn.execute(
            "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
            (str(dispatch["task_id"]),),
        ).fetchone()
        if current_task is None:
            raise RoomKernelFenceError("definition Task is missing")
        current_payload = json.loads(str(current_task["payload_json"]))
        if int(current_payload.get("revision") or 0) >= int(task_payload.get("revision") or 0):
            raise RoomKernelFenceError(
                "Root has already been defined by another invocation"
            )
        updated_root_criteria = list(criteria)
        updated_root_payload = json.loads(str(root["payload_json"]))
        if (
            bool(updated_root_payload.get("independentReviewRequired"))
            and not bool(independent_review_required)
        ):
            raise RoomKernelFenceError(
                "room_define cannot downgrade independent review policy"
            )
        review_policy_changed = bool(
            updated_root_payload.get("independentReviewRequired")
        ) != bool(independent_review_required)
        updated_root_payload["independentReviewRequired"] = bool(
            independent_review_required
        )
        validate_kernel_contract("rootExecution", updated_root_payload)
        intake = self.intake_state(str(root["root_id"]), conn=conn)
        clarification_occurred = bool(intake["clarificationOccurred"])
        approval_required = (
            clarification_occurred
            or isinstance(details.get("executionPlan"), Mapping)
        )
        # Current Room definitions carry the visible plan; only typed Start
        # authorizes them. Plan-less calls remain a legacy compatibility path.
        execution_authorized = not approval_required
        planned_execute = dict(execute_dispatch_payload)
        validate_kernel_contract("dispatchEnvelope", planned_execute)
        if (
            planned_execute.get("rootId") != root["root_id"]
            or planned_execute.get("taskId") != dispatch["task_id"]
            or planned_execute.get("parentDispatchId") != dispatch["dispatch_id"]
            or planned_execute.get("targetParticipantId")
            != root["facilitator_participant_id"]
            or planned_execute.get("targetSessionId")
            != dispatch["target_session_id"]
            or planned_execute.get("intentKind") != "execute"
            or int(planned_execute.get("generation", -1))
            != int(root["generation"])
            or int(planned_execute.get("hopCount", -1))
            != int(dispatch["hop_count"]) + 1
            or int(planned_execute.get("capabilityEpoch", -1))
            != int(_dispatch_payload(dispatch)["capabilityEpoch"]) + 1
        ):
            raise RoomKernelFenceError(
                "room_define ExecuteDispatch does not advance the alignment fence"
            )
        task_state = "active" if execution_authorized else "waiting"
        updated_task_payload = {**dict(task_payload), "state": task_state}
        validate_kernel_contract("roomTask", updated_task_payload)
        conn.execute(
            """UPDATE room_kernel_roots
               SET acceptance_criteria_json=?,payload_json=?,updated_at_ms=?
               WHERE root_id=?""",
            (
                _json(updated_root_criteria),
                _json(updated_root_payload),
                int(now_ms),
                str(root["root_id"]),
            ),
        )
        if review_policy_changed:
            self._record_review_policy_locked(
                conn,
                root_id=str(root["root_id"]),
                required=bool(independent_review_required),
                source="facilitator_definition",
                generation=int(root["generation"]),
                dispatch_id=str(dispatch["dispatch_id"]),
                now_ms=now_ms,
            )
        conn.execute(
            """UPDATE room_kernel_tasks
               SET state=?,current_owner_participant_id=?,payload_json=?,updated_at_ms=?
               WHERE task_id=?""",
            (
                task_state,
                str(updated_task_payload["currentOwnerParticipantId"]),
                _json(updated_task_payload),
                int(now_ms),
                str(dispatch["task_id"]),
            ),
        )
        # room_define is itself the authoritative terminal action for the old
        # alignment lease.  It consumes that reservation but deliberately does
        # not forge a RoomCommit or quality-gate result.
        conn.execute(
            "UPDATE room_kernel_dispatches SET state='committed',updated_at_ms=? "
            "WHERE dispatch_id=?",
            (int(now_ms), dispatch["dispatch_id"]),
        )
        conn.execute(
            "UPDATE room_kernel_outbox SET state='committed',updated_at_ms=? "
            "WHERE dispatch_id=?",
            (int(now_ms), dispatch["dispatch_id"]),
        )
        conn.execute(
            "UPDATE room_kernel_leases SET state='completed',updated_at_ms=? "
            "WHERE dispatch_id=? AND state IN ('active','accepted')",
            (int(now_ms), dispatch["dispatch_id"]),
        )
        conn.execute(
            """UPDATE room_kernel_runtime_effects
               SET state='completed',updated_at_ms=?
               WHERE dispatch_id=?
                 AND state IN ('intent','accepted','unknown')""",
            (int(now_ms), dispatch["dispatch_id"]),
        )
        conn.execute(
            """UPDATE room_kernel_abort_scopes
               SET state='completed',updated_at_ms=?
               WHERE dispatch_id=?
                 AND state IN ('registered','cancelling','unknown')""",
            (int(now_ms), dispatch["dispatch_id"]),
        )
        self._settle_dispatch_limits(
            conn,
            str(dispatch["dispatch_id"]),
            usage=None,
            consumed=True,
            now_ms=now_ms,
        )
        remaining = max(
            0,
            int(root["budget_remaining"]) - int(dispatch["budget_cost"]),
        )
        reserved = max(
            0,
            int(root["budget_reserved"]) - int(dispatch["budget_cost"]),
        )
        root_state = "running" if execution_authorized else "waiting"
        conn.execute(
            """UPDATE room_kernel_roots
               SET state=?,budget_remaining=?,budget_reserved=?,updated_at_ms=?
               WHERE root_id=?""",
            (
                root_state,
                remaining,
                reserved,
                int(now_ms),
                root["root_id"],
            ),
        )
        execute_dispatch: dict[str, object] | None = None
        if execution_authorized:
            self._record_intake_phase_locked(
                conn,
                root_id=str(root["root_id"]),
                phase="execution_ready",
                clarification_occurred=False,
                source="definition_committed",
                generation=int(root["generation"]),
                details={"definitionDispatchId": str(dispatch["dispatch_id"])},
                now_ms=now_ms,
            )
            execute_dispatch, _ = self._enqueue_dispatch(
                conn,
                planned_execute,
                shadow_only=self.mode not in {
                    "cohort",
                    "test",
                    "kernel_only",
                },
                now_ms=now_ms,
            )
            self._record_intake_phase_locked(
                conn,
                root_id=str(root["root_id"]),
                phase="executing",
                clarification_occurred=False,
                source="execute_dispatch_enqueued",
                generation=int(root["generation"]),
                details={"executionDispatchId": str(execute_dispatch["dispatchId"])},
                now_ms=now_ms,
            )
        else:
            self._record_intake_phase_locked(
                conn,
                root_id=str(root["root_id"]),
                phase="awaiting_start",
                clarification_occurred=clarification_occurred,
                source="definition_committed",
                generation=int(root["generation"]),
                details={"definitionDispatchId": str(dispatch["dispatch_id"])},
                now_ms=now_ms,
            )
        receipt = self._receipt(
            conn,
            root_id=str(root["root_id"]),
            command_id=None,
            receipt_kind="accepted",
            status="applied",
            generation=int(root["generation"]),
            details=_authoritative_receipt_details(
                {
                    "operation": "room_define",
                    "dispatchId": str(dispatch["dispatch_id"]),
                    "taskId": str(dispatch["task_id"]),
                    "invocationReceiptId": _required(
                        invocation_receipt_id,
                        "invocation_receipt_id",
                    ),
                    "plannedExecuteDispatch": planned_execute,
                    "executionDispatchId": (
                        str(execute_dispatch["dispatchId"])
                        if execute_dispatch is not None
                        else ""
                    ),
                    "requiresStartAction": not execution_authorized,
                },
                details,
                scope="room_define",
            ),
            now_ms=now_ms,
        )
        return {
            "receipt": receipt,
            "root": self.root(str(root["root_id"]), conn=conn),
            "task": self.task(str(dispatch["task_id"]), conn=conn),
            "dispatch": execute_dispatch,
            "intake": self.intake_state(str(root["root_id"]), conn=conn),
            "idempotent": False,
        }

    @staticmethod
    def _typed_start_preparation_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        receipt_id: str,
    ) -> tuple[dict[str, object], Mapping[str, object]]:
        row = conn.execute(
            """SELECT payload_json FROM room_kernel_receipts
               WHERE receipt_id=? AND root_id=?
                 AND receipt_kind='accepted'""",
            (_required(receipt_id, "prepare receipt"), root_id),
        ).fetchone()
        if row is None:
            raise RoomKernelFenceError(
                "typed start preparation receipt is missing"
            )
        prepared = json.loads(str(row["payload_json"]))
        details = (
            prepared.get("details")
            if isinstance(prepared, Mapping)
            else None
        )
        if (
            not isinstance(details, Mapping)
            or details.get("purpose")
            != "typed_start_authorization_prepared"
        ):
            raise RoomKernelFenceError(
                "typed start preparation receipt is invalid"
            )
        return prepared, details

    @staticmethod
    def _public_user_message_authorization_locked(
        conn: sqlite3.Connection,
        *,
        room_id: str,
        root_id: str,
        topic_id: str,
        post_id: str,
        client_message_id: str,
        content: str,
        created_at_ms: int,
        attachment_receipts: Sequence[object] = (),
        answer_to_post_id: str = "",
        answer_display_text: str = "",
        answer_kind: str = "",
        chronology_after_post_id: str = "",
        error_subject: str = "Room user message",
    ) -> dict[str, object]:
        projection_key = f"room-post:{post_id}"
        expected_event_payload = {
            "messageId": post_id,
            "clientMessageId": client_message_id,
            "text": content,
            "rootId": root_id,
            "postId": post_id,
            "attachmentReceipts": list(attachment_receipts),
            **(
                {"answerToPostId": answer_to_post_id}
                if answer_to_post_id
                else {}
            ),
            **(
                {"displayText": answer_display_text}
                if answer_display_text
                and answer_display_text != content
                else {}
            ),
            **({"answerKind": answer_kind} if answer_kind else {}),
            **(
                {"afterPostId": chronology_after_post_id}
                if chronology_after_post_id
                else {}
            ),
        }
        expected_hash = room_projection_hash(
            room_id=room_id,
            event_type="user_message",
            payload=expected_event_payload,
            turn_id=root_id,
            participant_id=None,
            source_session_id="",
            topic_id=topic_id,
        )
        authorization_row = conn.execute(
            """
            SELECT receipt.room_id AS receipt_room_id,
                   receipt.event_id AS receipt_event_id,
                   receipt.payload_hash AS receipt_payload_hash,
                   receipt.created_at_ms AS receipt_created_at_ms,
                   event.event_id AS retained_event_id,
                   event.sequence AS retained_sequence,
                   event.turn_id,event.event_type,event.participant_id,
                   event.source_session_id,event.topic_id,
                   event.created_at_ms AS event_created_at_ms,
                   event.payload_json
            FROM agent_room_public_projection_receipts AS receipt
            LEFT JOIN agent_room_events AS event
              ON event.event_id=receipt.event_id
            WHERE receipt.projection_key=?
            """,
            (projection_key,),
        ).fetchone()
        if authorization_row is None:
            raise RoomKernelFenceError(
                f"{error_subject} authorization is not durably public"
            )
        event_id = str(authorization_row["receipt_event_id"] or "")
        event_room_id, separator, event_ordinal = event_id.rpartition(":")
        try:
            event_sequence = int(event_ordinal)
        except ValueError as exc:
            raise RoomKernelFenceError(
                f"{error_subject} authorization event identity is invalid"
            ) from exc
        if (
            separator != ":"
            or event_room_id != room_id
            or event_sequence <= 0
            or str(authorization_row["receipt_room_id"] or "") != room_id
            or str(authorization_row["receipt_payload_hash"] or "")
            != expected_hash
            or int(authorization_row["receipt_created_at_ms"])
            != int(created_at_ms)
        ):
            raise RoomKernelFenceError(
                f"{error_subject} authorization projection was rebound"
            )
        retained = authorization_row["retained_event_id"] is not None
        if retained:
            actual_event_payload = json.loads(
                str(authorization_row["payload_json"])
            )
            if (
                str(authorization_row["retained_event_id"]) != event_id
                or int(authorization_row["retained_sequence"])
                != event_sequence
                or str(authorization_row["event_type"]) != "user_message"
                or str(authorization_row["turn_id"]) != root_id
                or authorization_row["participant_id"] is not None
                or str(authorization_row["source_session_id"] or "")
                or str(authorization_row["topic_id"] or "") != topic_id
                or int(authorization_row["event_created_at_ms"])
                != int(created_at_ms)
                or actual_event_payload != expected_event_payload
            ):
                raise RoomKernelFenceError(
                    f"{error_subject} authorization event was rebound"
                )
        return {
            "eventId": event_id,
            "sequence": event_sequence,
            "eventType": "user_message",
            "roomId": room_id,
            "turnId": root_id,
            "topicId": topic_id,
            "createdAtMs": int(created_at_ms),
            "payload": expected_event_payload,
            "retained": retained,
            "projectionKey": projection_key,
            "payloadHash": expected_hash,
        }

    @staticmethod
    def _typed_start_authorization_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        prepared: Mapping[str, object],
        prepared_details: Mapping[str, object],
    ) -> dict[str, object]:
        room_id = _required(prepared_details.get("roomId"), "prepared Room")
        client_action_id = _required(
            prepared_details.get("clientActionId"),
            "prepared client action",
        )
        user_post_id = _required(
            prepared_details.get("userPostId"),
            "prepared user Post",
        )
        projection_key = _required(
            prepared_details.get("projectionKey"),
            "prepared projection key",
        )
        if projection_key != f"room-post:{user_post_id}":
            raise RoomKernelFenceError(
                "typed start authorization projection identity was rebound"
            )
        chronology_after_post_id = str(
            prepared_details.get("chronologyAfterPostId") or ""
        )
        topic_id = str(prepared_details.get("topicId") or "")
        created_at_ms = int(prepared["createdAtMs"])
        return RoomKernelStore._public_user_message_authorization_locked(
            conn,
            room_id=room_id,
            root_id=root_id,
            topic_id=topic_id,
            post_id=user_post_id,
            client_message_id=client_action_id,
            content="开始行动",
            created_at_ms=created_at_ms,
            chronology_after_post_id=chronology_after_post_id,
            error_subject="typed start",
        )

    def defined_execution_start_authorization(
        self,
        *,
        root_id: str,
        prepare_receipt_id: str,
    ) -> dict[str, object]:
        """Resolve a start authorization from its permanent projection proof."""

        root_id = _required(root_id, "root_id")
        with self._connect() as conn:
            prepared, details = self._typed_start_preparation_locked(
                conn,
                root_id=root_id,
                receipt_id=prepare_receipt_id,
            )
            return self._typed_start_authorization_locked(
                conn,
                root_id=root_id,
                prepared=prepared,
                prepared_details=details,
            )

    def prepare_defined_execution_start(
        self,
        *,
        root_id: str,
        client_action_id: str,
        user_post_id: str,
        room_id: str,
        topic_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Durably freeze one typed start identity without releasing work."""

        root_id = _required(root_id, "root_id")
        client_action_id = _required(client_action_id, "client_action_id")
        user_post_id = _required(user_post_id, "user_post_id")
        room_id = _required(room_id, "room_id")
        with self._connect(immediate=True) as conn:
            root = self._root_row(conn, root_id)
            if str(root["room_id"]) != room_id:
                raise RoomKernelFenceError(
                    "typed start Room does not match its Root"
                )
            prior_prepare: dict[str, object] | None = None
            prior_final: dict[str, object] | None = None
            prior_rows = conn.execute(
                """SELECT payload_json FROM room_kernel_receipts
                   WHERE root_id=? AND receipt_kind='accepted'
                   ORDER BY created_at_ms,rowid""",
                (root_id,),
            ).fetchall()
            for row in prior_rows:
                receipt = json.loads(str(row["payload_json"]))
                details = (
                    receipt.get("details")
                    if isinstance(receipt, Mapping)
                    else None
                )
                if not isinstance(details, Mapping):
                    continue
                if details.get("purpose") == "typed_start_action":
                    prior_final = receipt
                    break
                if (
                    prior_prepare is None
                    and details.get("purpose")
                    == "typed_start_authorization_prepared"
                ):
                    prior_prepare = receipt
            if prior_final is not None:
                final_details = prior_final["details"]
                dispatch_id = _required(
                    final_details.get("executionDispatchId"),
                    "execution dispatch id",
                )
                dispatch = self.dispatch(dispatch_id, conn=conn)
                legacy_projection = conn.execute(
                    """
                    SELECT receipt.event_id,
                           event.event_id AS retained_event_id,
                           event.topic_id
                    FROM agent_room_public_projection_receipts AS receipt
                    LEFT JOIN agent_room_events AS event
                      ON event.event_id=receipt.event_id
                    WHERE receipt.projection_key=?
                    """,
                    (
                        f"room-post:{str(final_details.get('userPostId') or '')}",
                    ),
                ).fetchone()
                if legacy_projection is None:
                    raise RoomKernelFenceError(
                        "legacy typed start has execution but no durable public "
                        "authorization; explicit incident repair is required"
                    )
                final_prepare_receipt_id = str(
                    final_details.get("prepareReceiptId") or ""
                )
                prepared_topic_id = ""
                replay_planned_dispatch: Mapping[str, object] = dispatch
                if final_prepare_receipt_id:
                    _prepared_receipt, prepared_details = (
                        self._typed_start_preparation_locked(
                            conn,
                            root_id=root_id,
                            receipt_id=final_prepare_receipt_id,
                        )
                    )
                    prepared_topic_id = str(
                        prepared_details.get("topicId") or ""
                    )
                    authorization_event_id = str(
                        final_details.get("authorizationEventId") or ""
                    )
                    if (
                        authorization_event_id
                        and authorization_event_id
                        != str(legacy_projection["event_id"] or "")
                    ):
                        raise RoomKernelFenceError(
                            "typed start final receipt authorization was rebound"
                        )
                    definition = self.definition_fence(
                        root_id=root_id,
                        conn=conn,
                    )
                    definition_planned = (
                        definition.get("plannedExecuteDispatch")
                        if isinstance(definition, Mapping)
                        else None
                    )
                    if (
                        isinstance(definition_planned, Mapping)
                        and str(definition_planned.get("dispatchId") or "")
                        == str(
                            prepared_details.get(
                                "plannedExecutionDispatchId"
                            )
                            or ""
                        )
                    ):
                        # The public Start Post is authorized against the
                        # original definition Task.  A PlanRevision may release
                        # different feature Dispatches, so replay must not use
                        # an execution Dispatch as the authorization template.
                        replay_planned_dispatch = definition_planned
                elif legacy_projection["retained_event_id"] is None:
                    raise RoomKernelFenceError(
                        "legacy typed start authorization was retained only as "
                        "an unverifiable projection; explicit incident repair "
                        "is required"
                    )
                return {
                    "receipt": prior_final,
                    "plannedDispatch": dict(replay_planned_dispatch),
                    "created": False,
                    "finalized": True,
                    "prepareReceiptId": (
                        final_prepare_receipt_id
                        or str(prior_final["receiptId"])
                    ),
                    "topicId": (
                        prepared_topic_id
                        or str(legacy_projection["topic_id"] or "")
                        or str(topic_id or "")
                    ),
                }
            intake = self.intake_state(root_id, conn=conn)
            if (
                intake.get("phase") != "awaiting_start"
                or str(root["state"]) != "waiting"
            ):
                raise RoomKernelFenceError(
                    "typed start is allowed only after an approved definition"
                )
            definition = self.definition_fence(root_id=root_id, conn=conn)
            if definition is None:
                raise RoomKernelFenceError(
                    "typed start requires a durable room_define fence"
                )
            planned = definition.get("plannedExecuteDispatch")
            if not isinstance(planned, Mapping):
                raise RoomKernelFenceError(
                    "room_define fence has no planned ExecuteDispatch"
                )
            task_id = _required(planned.get("taskId"), "definition task id")
            task_row = conn.execute(
                """SELECT state,payload_json FROM room_kernel_tasks
                   WHERE task_id=?""",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise RoomKernelFenceError("defined Task is missing")
            if str(task_row["state"]) != "waiting":
                raise RoomKernelFenceError(
                    "typed start requires its defined Task to be waiting"
                )
            if prior_prepare is not None:
                prepared_details = prior_prepare["details"]
                if (
                    str(prepared_details.get("roomId") or "") != room_id
                    or str(prepared_details.get("taskId") or "") != task_id
                    or str(
                        prepared_details.get("plannedExecutionDispatchId")
                        or ""
                    )
                    != str(planned.get("dispatchId") or "")
                    or int(
                        prepared_details.get("generation")
                        if prepared_details.get("generation") is not None
                        else -1
                    )
                    != int(root["generation"])
                ):
                    raise RoomKernelFenceError(
                        "typed start preparation no longer matches its definition"
                    )
                return {
                    "receipt": prior_prepare,
                    "plannedDispatch": dict(planned),
                    "created": False,
                    "finalized": False,
                    "topicId": str(prepared_details.get("topicId") or ""),
                }
            prior_post = conn.execute(
                """
                SELECT post_id FROM room_kernel_posts
                WHERE root_id=?
                ORDER BY created_at_ms DESC, post_id DESC
                LIMIT 1
                """,
                (root_id,),
            ).fetchone()
            chronology_after_post_id = (
                str(prior_post["post_id"])
                if prior_post is not None
                else ""
            )
            definition_receipt = definition.get("receipt")
            if not isinstance(definition_receipt, Mapping):
                raise RoomKernelFenceError(
                    "room_define fence has no authoritative receipt"
                )
            receipt = self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "purpose": "typed_start_authorization_prepared",
                    "clientActionId": client_action_id,
                    "userPostId": user_post_id,
                    "projectionKey": f"room-post:{user_post_id}",
                    "roomId": room_id,
                    "topicId": str(topic_id or ""),
                    "chronologyAfterPostId": chronology_after_post_id,
                    "taskId": task_id,
                    "plannedExecutionDispatchId": str(
                        planned.get("dispatchId") or ""
                    ),
                    "definitionReceiptId": str(
                        definition_receipt.get("receiptId") or ""
                    ),
                    "generation": int(root["generation"]),
                },
                now_ms=now_ms,
            )
            return {
                "receipt": receipt,
                "plannedDispatch": dict(planned),
                "created": True,
                "finalized": False,
                "topicId": str(topic_id or ""),
            }

    def start_defined_execution(
        self,
        *,
        root_id: str,
        prepare_receipt_id: str,
        user_post: Mapping[str, object],
        now_ms: int,
        _conn: sqlite3.Connection | None = None,
        work_document_ref: Mapping[str, object] | None = None,
        plan_revision: Mapping[str, object] | None = None,
        planned_tasks: Sequence[Mapping[str, object]] = (),
        frontier_dispatches: Sequence[Mapping[str, object]] = (),
    ) -> dict[str, object]:
        """CAS-release work only after its public typed authorization exists."""

        root_id = _required(root_id, "root_id")
        prepare_receipt_id = _required(
            prepare_receipt_id,
            "prepare_receipt_id",
        )
        with self._write_connection(_conn) as conn:
            root = self._root_row(conn, root_id)
            prior_rows = conn.execute(
                """SELECT payload_json FROM room_kernel_receipts
                   WHERE root_id=? AND receipt_kind='accepted'
                   ORDER BY created_at_ms,rowid""",
                (root_id,),
            ).fetchall()
            for row in prior_rows:
                receipt = json.loads(str(row["payload_json"]))
                details = (
                    receipt.get("details")
                    if isinstance(receipt, Mapping)
                    else None
                )
                if (
                    isinstance(details, Mapping)
                    and details.get("purpose") == "typed_start_action"
                ):
                    raw_dispatch_ids = details.get("executionDispatchIds")
                    dispatch_ids = [
                        str(value)
                        for value in (
                            raw_dispatch_ids
                            if isinstance(raw_dispatch_ids, list)
                            else [details.get("executionDispatchId")]
                        )
                        if str(value or "").strip()
                    ]
                    if not dispatch_ids:
                        raise RoomKernelFenceError(
                            "typed start receipt has no execution Dispatch"
                        )
                    raw_task_ids = details.get("plannedTaskIds")
                    task_ids = [
                        str(value)
                        for value in (
                            raw_task_ids
                            if isinstance(raw_task_ids, list)
                            else [self.dispatch(dispatch_ids[0], conn=conn)["taskId"]]
                        )
                        if str(value or "").strip()
                    ]
                    dispatches = [
                        self.dispatch(dispatch_id, conn=conn)
                        for dispatch_id in dispatch_ids
                    ]
                    stored_plan = RoomPlanRepository.latest(conn, root_id)
                    return {
                        "receipt": receipt,
                        "dispatch": dispatches[0],
                        "dispatches": dispatches,
                        "tasks": [
                            self.task(task_id, conn=conn)
                            for task_id in task_ids
                        ],
                        "intake": self.intake_state(root_id, conn=conn),
                        "created": False,
                        **(
                            {"planRevision": stored_plan}
                            if isinstance(stored_plan, Mapping)
                            else {}
                        ),
                    }
            prepared, prepared_details = (
                self._typed_start_preparation_locked(
                    conn,
                    root_id=root_id,
                    receipt_id=prepare_receipt_id,
                )
            )
            intake = self.intake_state(root_id, conn=conn)
            if (
                intake.get("phase") != "awaiting_start"
                or str(root["state"]) != "waiting"
            ):
                raise RoomKernelFenceError(
                    "typed start release lost its waiting definition fence"
                )
            generation = int(root["generation"])
            if int(
                prepared_details.get("generation")
                if prepared_details.get("generation") is not None
                else -1
            ) != generation:
                raise RoomKernelFenceError(
                    "typed start preparation generation is stale"
                )
            room_id = _required(prepared_details.get("roomId"), "prepared Room")
            if str(root["room_id"]) != room_id:
                raise RoomKernelFenceError(
                    "typed start preparation belongs to another Room"
                )
            client_action_id = _required(
                prepared_details.get("clientActionId"),
                "prepared client action",
            )
            user_post_id = _required(
                prepared_details.get("userPostId"),
                "prepared user Post",
            )
            projection_key = _required(
                prepared_details.get("projectionKey"),
                "prepared projection key",
            )
            chronology_after_post_id = str(
                prepared_details.get("chronologyAfterPostId") or ""
            )
            authorization = self._typed_start_authorization_locked(
                conn,
                root_id=root_id,
                prepared=prepared,
                prepared_details=prepared_details,
            )
            event_id = str(authorization["eventId"])
            event_sequence = int(authorization["sequence"])
            expected_chronology = {
                "schemaVersion": "wisdom-weasel.room-post-chronology.v1",
                "roomEventId": event_id,
                "roomEventSequence": event_sequence,
                "createdAtMs": int(prepared["createdAtMs"]),
                "afterPostId": chronology_after_post_id or None,
                "orderKey": f"room-event:{event_sequence:020d}",
            }
            task_id = _required(
                prepared_details.get("taskId"),
                "prepared definition task",
            )
            expected_post_fields = {
                "postId": user_post_id,
                "roomId": room_id,
                "rootId": root_id,
                "generation": generation,
                "taskId": task_id,
                "authorActorRef": "user:local",
                "kind": "request",
                "visibility": "room",
                "content": "开始行动",
                "idempotencyKey": f"typed-start:{root_id}:{client_action_id}",
                "publicationSource": {
                    "kind": "user",
                    "ref": client_action_id,
                },
                "createdAtMs": int(prepared["createdAtMs"]),
                "chronology": expected_chronology,
            }
            if any(
                user_post.get(key) != value
                for key, value in expected_post_fields.items()
            ):
                raise RoomKernelFenceError(
                    "typed start Room Post does not match its authorization"
                )
            definition = self.definition_fence(root_id=root_id, conn=conn)
            if definition is None:
                raise RoomKernelFenceError(
                    "typed start release lost its room_define fence"
                )
            planned = definition.get("plannedExecuteDispatch")
            if not isinstance(planned, Mapping):
                raise RoomKernelFenceError(
                    "room_define fence has no planned ExecuteDispatch"
                )
            if (
                str(planned.get("taskId") or "") != task_id
                or str(planned.get("dispatchId") or "")
                != str(
                    prepared_details.get("plannedExecutionDispatchId") or ""
                )
            ):
                raise RoomKernelFenceError(
                    "typed start release no longer matches its definition"
                )
            definition_receipt = definition.get("receipt")
            definition_details = (
                definition_receipt.get("details")
                if isinstance(definition_receipt, Mapping)
                and isinstance(definition_receipt.get("details"), Mapping)
                else {}
            )
            definition_plan_id = str(
                definition_details.get("planRevisionId") or ""
            )
            plan_enabled = bool(definition_plan_id)
            if plan_enabled != (plan_revision is not None):
                raise RoomKernelFenceError(
                    "typed start PlanRevision no longer matches its definition"
                )
            planned_task_values = [dict(value) for value in planned_tasks]
            frontier_values = [dict(value) for value in frontier_dispatches]
            stored_plan: dict[str, object] | None = None
            if plan_enabled:
                if work_document_ref is None or plan_revision is None:
                    raise RoomKernelFenceError(
                        "approved plan Start requires its WorkDocument"
                    )
                stored_plan = RoomPlanRepository.latest(conn, root_id)
                if (
                    not isinstance(stored_plan, Mapping)
                    or str(stored_plan.get("planRevisionId") or "")
                    != definition_plan_id
                    or _json(stored_plan) != _json(dict(plan_revision))
                    or str(stored_plan.get("state") or "") != "proposed"
                ):
                    raise RoomKernelFenceError(
                        "typed start PlanRevision lost its proposed authority"
                    )
                plan_specs = [
                    dict(value)
                    for value in stored_plan.get("tasks", [])
                    if isinstance(value, Mapping)
                ]
                plan_task_ids = [str(value["taskId"]) for value in plan_specs]
                materialized_task_ids = [
                    str(value.get("taskId") or "")
                    for value in planned_task_values
                ]
                if (
                    len(plan_task_ids) != len(set(plan_task_ids))
                    or materialized_task_ids != plan_task_ids
                ):
                    raise RoomKernelFenceError(
                        "typed start must materialize every approved Task exactly once"
                    )
                graph = {
                    str(value["taskId"]): [
                        str(dependency)
                        for dependency in value.get("dependencyTaskIds") or []
                    ]
                    for value in plan_specs
                }
                expected_frontier = set(
                    runnable_frontier(graph, completed=set())
                )
                actual_frontier = [
                    str(value.get("taskId") or "")
                    for value in frontier_values
                ]
                if (
                    not actual_frontier
                    or len(actual_frontier) != len(set(actual_frontier))
                    or set(actual_frontier) != expected_frontier
                ):
                    raise RoomKernelFenceError(
                        "typed start may release only the approved runnable frontier"
                    )
                task_by_id = {
                    str(value.get("taskId") or ""): value
                    for value in planned_task_values
                }
                for spec in plan_specs:
                    materialized = task_by_id[str(spec["taskId"])]
                    if (
                        str(materialized.get("planRevisionId") or "")
                        != definition_plan_id
                        or str(materialized.get("planTaskKind") or "")
                        != str(spec.get("kind") or "")
                        or list(materialized.get("dependencyTaskIds") or [])
                        != list(spec.get("dependencyTaskIds") or [])
                        or str(materialized.get("currentOwnerParticipantId") or "")
                        != str(spec.get("ownerParticipantId") or "")
                    ):
                        raise RoomKernelFenceError(
                            "materialized Task diverges from its approved PlanRevision"
                        )
            elif planned_task_values or frontier_values or work_document_ref:
                raise RoomKernelFenceError(
                    "legacy typed start cannot smuggle a PlanRevision payload"
                )
            task_row = conn.execute(
                """SELECT state,payload_json FROM room_kernel_tasks
                   WHERE task_id=?""",
                (task_id,),
            ).fetchone()
            if task_row is None or str(task_row["state"]) != "waiting":
                raise RoomKernelFenceError(
                    "typed start release requires its Task to be waiting"
                )
            task_payload = json.loads(str(task_row["payload_json"]))
            primary_task_state = "completed" if plan_enabled else "active"
            task_payload["state"] = primary_task_state
            if plan_enabled:
                task_payload.update(
                    {
                        "resultKind": "dispatch",
                        "resultSummary": "用户已确认任务图，首个可运行波次已经释放。",
                        "resultAtMs": int(now_ms),
                    }
                )
            validate_kernel_contract("roomTask", task_payload)
            root_update = conn.execute(
                """UPDATE room_kernel_roots
                   SET state='running',updated_at_ms=?
                   WHERE root_id=? AND generation=? AND state='waiting'""",
                (int(now_ms), root_id, generation),
            )
            if root_update.rowcount != 1:
                raise RoomKernelFenceError(
                    "typed start Root compare-and-set failed"
                )
            task_update = conn.execute(
                """UPDATE room_kernel_tasks
                   SET state=?,payload_json=?,updated_at_ms=?
                   WHERE task_id=? AND state='waiting'""",
                (
                    primary_task_state,
                    _json(task_payload),
                    int(now_ms),
                    task_id,
                ),
            )
            if task_update.rowcount != 1:
                raise RoomKernelFenceError(
                    "typed start Task compare-and-set failed"
                )
            created_tasks: list[dict[str, object]] = []
            for task_value in planned_task_values:
                created_task, was_created = self._insert_task(
                    conn,
                    task_value,
                    now_ms=now_ms,
                )
                if not was_created:
                    raise RoomKernelFenceError(
                        "approved Plan Task already exists without a final Start receipt"
                    )
                created_tasks.append(created_task)
            self._record_intake_phase_locked(
                conn,
                root_id=root_id,
                phase="execution_ready",
                clarification_occurred=bool(intake.get("clarificationOccurred")),
                source="typed_start_action",
                generation=generation,
                details={
                    "clientActionId": client_action_id,
                    "userPostId": user_post_id,
                    "chronologyAfterPostId": chronology_after_post_id,
                    "authorizationEventId": event_id,
                },
                now_ms=now_ms,
            )
            dispatch_inputs = frontier_values if plan_enabled else [dict(planned)]
            created_dispatches: list[dict[str, object]] = []
            for dispatch_value in dispatch_inputs:
                created_dispatch, dispatch_created = self._enqueue_dispatch(
                    conn,
                    dispatch_value,
                    shadow_only=self.mode not in {
                        "cohort",
                        "test",
                        "kernel_only",
                    },
                    now_ms=now_ms,
                )
                if not dispatch_created:
                    raise RoomKernelFenceError(
                        "typed start ExecuteDispatch already exists without a final receipt"
                    )
                created_dispatches.append(created_dispatch)
            dispatch = created_dispatches[0]
            activated_plan: dict[str, object] | None = None
            if plan_enabled:
                activated_plan = RoomPlanRepository.activate(
                    conn,
                    plan_revision_id=definition_plan_id,
                    work_document_ref=work_document_ref or {},
                    activated_at_ms=int(now_ms),
                )
            self._record_intake_phase_locked(
                conn,
                root_id=root_id,
                phase="executing",
                clarification_occurred=bool(intake.get("clarificationOccurred")),
                source=(
                    "approved_plan_frontier_enqueued"
                    if plan_enabled
                    else "execute_dispatch_enqueued"
                ),
                generation=generation,
                details={
                    "clientActionId": client_action_id,
                    "userPostId": user_post_id,
                    "chronologyAfterPostId": chronology_after_post_id,
                    "executionDispatchId": str(dispatch["dispatchId"]),
                    "executionDispatchIds": [
                        str(value["dispatchId"])
                        for value in created_dispatches
                    ],
                    "plannedTaskIds": [
                        str(value["taskId"])
                        for value in created_tasks
                    ],
                    **(
                        {"planRevisionId": definition_plan_id}
                        if plan_enabled
                        else {}
                    ),
                    "authorizationEventId": event_id,
                },
                now_ms=now_ms,
            )
            receipt = self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=generation,
                details={
                    "purpose": "typed_start_action",
                    "prepareReceiptId": prepare_receipt_id,
                    "authorizationProjectionKey": projection_key,
                    "authorizationEventId": event_id,
                    "authorizationEventSequence": event_sequence,
                    "clientActionId": client_action_id,
                    "userPostId": user_post_id,
                    "chronologyAfterPostId": chronology_after_post_id,
                    "executionDispatchId": str(dispatch["dispatchId"]),
                    "executionDispatchIds": [
                        str(value["dispatchId"])
                        for value in created_dispatches
                    ],
                    "plannedTaskIds": [
                        str(value["taskId"])
                        for value in created_tasks
                    ],
                    **(
                        {
                            "planRevisionId": definition_plan_id,
                            "workDocumentId": str(
                                (work_document_ref or {}).get("documentId") or ""
                            ),
                        }
                        if plan_enabled
                        else {}
                    ),
                },
                now_ms=now_ms,
            )
            RoomDomainEventRepository.append(
                conn,
                past_tense_event(
                    kind="plan_started" if plan_enabled else "execution_started",
                    room_id=room_id,
                    root_id=root_id,
                    entity_id=definition_plan_id or root_id,
                    generation=generation,
                    idempotency_key=str(receipt["receiptId"]),
                    payload={
                        "receiptId": str(receipt["receiptId"]),
                        "executionDispatchIds": [
                            str(value["dispatchId"])
                            for value in created_dispatches
                        ],
                        "plannedTaskIds": [
                            str(value["taskId"])
                            for value in created_tasks
                        ],
                    },
                ),
                created_at_ms=int(now_ms),
            )
            returned_tasks = (
                [
                    self.task(str(value["taskId"]), conn=conn)
                    for value in created_tasks
                ]
                if plan_enabled
                else [self.task(task_id, conn=conn)]
            )
            return {
                "receipt": receipt,
                "dispatch": dispatch,
                "dispatches": created_dispatches,
                "tasks": returned_tasks,
                "intake": self.intake_state(root_id, conn=conn),
                "created": True,
                **(
                    {"planRevision": activated_plan}
                    if activated_plan is not None
                    else {}
                ),
            }

    def plan_runnable_frontier(
        self,
        root_id: str,
    ) -> dict[str, object]:
        """Return only the next dependency-proven Tasks of the active plan."""

        with self._connect() as conn:
            return self._plan_runnable_frontier_locked(conn, root_id)

    def reconcile_active_plan(
        self,
        root_id: str,
        *,
        expected_plan_revision_id: str,
        replacement_plan: Mapping[str, object],
        affected_task_ids: Sequence[str],
        source_dispatch_id: str,
        intervention_id: str,
        now_ms: int,
        _conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        """Supersede one plan and restart only its affected dependency closure."""

        with self._write_connection(_conn) as conn:
            root = self._root_row(conn, _required(root_id, "root_id"))
            current = RoomPlanRepository.latest(conn, root_id)
            if (
                not isinstance(current, Mapping)
                or current.get("state") != "active"
                or str(current.get("planRevisionId") or "")
                != str(expected_plan_revision_id)
            ):
                raise RoomKernelFenceError(
                    "active PlanRevision changed before reconciliation"
                )
            specs = [
                dict(value)
                for value in replacement_plan.get("tasks", [])
                if isinstance(value, Mapping)
            ]
            graph = {
                str(value.get("taskId") or ""): [
                    str(item)
                    for item in value.get("dependencyTaskIds") or []
                ]
                for value in specs
            }
            waves = derived_task_waves(graph)
            if any(
                int(value.get("wave") or 0) != waves[str(value["taskId"])]
                for value in specs
            ):
                raise RoomKernelFenceError(
                    "replacement Plan wave is not derived from its dependency graph"
                )
            affected = dependent_closure(
                graph,
                affected={str(value) for value in affected_task_ids},
            )
            if not affected:
                raise RoomKernelFenceError(
                    "Plan reconciliation requires at least one affected Task"
                )
            source_dispatch = self.dispatch(source_dispatch_id, conn=conn)
            source_task_id = str(source_dispatch.get("taskId") or "")
            if (
                str(source_dispatch.get("rootId") or "") != root_id
                or str(source_dispatch.get("state") or "") not in _ACTIVE_DISPATCH_STATES
            ):
                raise RoomKernelFenceError(
                    "Plan reconciliation source Dispatch is no longer active"
                )
            reset_ids = [
                task_id for task_id in affected if task_id != source_task_id
            ]
            active_dispatch_rows = (
                conn.execute(
                    f"""SELECT dispatch_id FROM room_kernel_dispatches
                       WHERE root_id=? AND task_id IN ({','.join('?' for _ in reset_ids)})
                         AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})
                       ORDER BY dispatch_id""",
                    (root_id, *reset_ids, *_ACTIVE_DISPATCH_STATES),
                ).fetchall()
                if reset_ids
                else []
            )
            cancelled_dispatch_ids = [
                str(row["dispatch_id"]) for row in active_dispatch_rows
            ]
            runtime_targets = (
                conn.execute(
                    f"""SELECT dispatch_id,session_id
                       FROM room_kernel_runtime_effects
                       WHERE root_id=?
                         AND dispatch_id IN ({','.join('?' for _ in cancelled_dispatch_ids)})
                         AND state IN ('intent','accepted','unknown')""",
                    (root_id, *cancelled_dispatch_ids),
                ).fetchall()
                if cancelled_dispatch_ids
                else []
            )
            if cancelled_dispatch_ids:
                self._cancel_dispatch_ids(
                    conn,
                    cancelled_dispatch_ids,
                    now_ms=now_ms,
                )
            runtime_ids = {str(row["dispatch_id"]) for row in runtime_targets}
            for target in runtime_targets:
                self._enqueue_cancel(
                    conn,
                    root_id=root_id,
                    dispatch_id=str(target["dispatch_id"]),
                    session_id=str(target["session_id"]),
                    generation=int(root["generation"]),
                    terminalize_root=False,
                    now_ms=now_ms,
                )
            for dispatch_id in set(cancelled_dispatch_ids) - runtime_ids:
                conn.execute(
                    """UPDATE room_kernel_abort_scopes
                       SET state='cancelled',updated_at_ms=?
                       WHERE dispatch_id=?
                         AND state IN ('registered','cancelling','unknown')""",
                    (int(now_ms), dispatch_id),
                )
                self._settle_dispatch_limits(
                    conn,
                    dispatch_id,
                    usage=None,
                    consumed=False,
                    now_ms=now_ms,
                )
            replacement_id = str(replacement_plan["planRevisionId"])
            spec_by_id = {str(value["taskId"]): value for value in specs}
            for task_id in graph:
                task = self.task(task_id, conn=conn)
                next_state = str(task.get("state") or "")
                if task_id in reset_ids:
                    if next_state in {"failed", "cancelled"}:
                        raise RoomKernelFenceError(
                            "terminal failed Task requires explicit recovery before replanning"
                        )
                    next_state = "pending"
                updated_task = {
                    **task,
                    "planRevisionId": replacement_id,
                    "planWave": int(spec_by_id[task_id]["wave"]),
                    "revision": int(task.get("revision") or 0) + 1,
                    "state": next_state,
                    "contextEvidenceRefs": list(
                        dict.fromkeys(
                            [
                                *(task.get("contextEvidenceRefs") or []),
                                replacement_id,
                                intervention_id,
                            ]
                        )
                    )[:32],
                }
                if task_id in reset_ids:
                    if updated_task.get("workspacePolicy") == "isolated_writable":
                        updated_task["workspaceIntegrationState"] = "pending"
                        updated_task["workspaceIntegrationRef"] = None
                    if updated_task.get("taskKind") == "review":
                        updated_task["reviewState"] = "required"
                validate_kernel_contract("roomTask", updated_task)
                conn.execute(
                    """UPDATE room_kernel_tasks
                       SET state=?,payload_json=?,updated_at_ms=?
                       WHERE task_id=?""",
                    (
                        next_state,
                        _json(updated_task),
                        int(now_ms),
                        task_id,
                    ),
                )
            active_plan = RoomPlanRepository.replace_active(
                conn,
                expected_plan_revision_id=expected_plan_revision_id,
                payload=replacement_plan,
            )
            receipt = self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "purpose": "plan_revision_reconciled",
                    "interventionId": intervention_id,
                    "previousPlanRevisionId": expected_plan_revision_id,
                    "planRevisionId": replacement_id,
                    "affectedTaskIds": affected,
                    "cancelledDispatchIds": cancelled_dispatch_ids,
                    "pendingCancelDispatchIds": sorted(runtime_ids),
                    "sourceDispatchId": source_dispatch_id,
                },
                now_ms=now_ms,
            )
            RoomDomainEventRepository.append(
                conn,
                past_tense_event(
                    kind="plan_revision_reconciled",
                    room_id=str(root["room_id"]),
                    root_id=root_id,
                    entity_id=replacement_id,
                    generation=int(root["generation"]),
                    idempotency_key=str(receipt["receiptId"]),
                    payload=dict(receipt["details"]),
                ),
                created_at_ms=int(now_ms),
            )
            return {
                "planRevision": active_plan,
                "affectedTaskIds": affected,
                "cancelledDispatchIds": cancelled_dispatch_ids,
                "pendingCancelDispatchIds": sorted(runtime_ids),
                "receipt": receipt,
            }

    def _plan_runnable_frontier_locked(
        self,
        conn: sqlite3.Connection,
        root_id: str,
    ) -> dict[str, object]:
        plan = RoomPlanRepository.latest(conn, _required(root_id, "root_id"))
        if not isinstance(plan, Mapping) or plan.get("state") != "active":
            return {"planRevision": None, "tasks": [], "nextCapabilityEpoch": 0}
        specs = [
            dict(value)
            for value in plan.get("tasks", [])
            if isinstance(value, Mapping)
        ]
        graph = {
            str(value["taskId"]): [
                str(dependency)
                for dependency in value.get("dependencyTaskIds") or []
            ]
            for value in specs
        }
        tasks: dict[str, dict[str, object]] = {}
        committed: set[str] = set()
        fully_applied_ids: set[str] = set()
        for task_id in graph:
            task = self.task(task_id, conn=conn)
            tasks[task_id] = task
            task_fully_applied = (
                str(task.get("state") or "") == "completed"
                and (
                    task.get("workspacePolicy") != "isolated_writable"
                    or task.get("workspaceIntegrationState") == "applied"
                )
            )
            if str(task.get("state") or "") == "completed":
                committed.add(task_id)
            if task_fully_applied:
                fully_applied_ids.add(task_id)
        validate_task_graph(graph)
        spec_by_id = {str(value["taskId"]): value for value in specs}

        def dependencies_ready(task_id: str) -> bool:
            spec = spec_by_id[task_id]
            dependencies = graph[task_id]
            if spec.get("kind") != "integration":
                return all(
                    dependency_id in fully_applied_ids
                    for dependency_id in dependencies
                )
            # One integration Task owns the full writable scope across waves.
            # Release its first attempt as soon as that scope has an actual
            # delivered worktree; it stays open until every scoped feature is
            # integrated, while each accepted integration can release the next
            # dependency-ready feature.
            return any(
                dependency_id in committed
                and tasks[dependency_id].get("workspacePolicy")
                == "isolated_writable"
                and tasks[dependency_id].get("workspaceIntegrationState")
                != "applied"
                for dependency_id in dependencies
            )

        ready_ids = [
            task_id
            for task_id in sorted(graph)
            if str(tasks[task_id].get("state") or "") == "pending"
            and dependencies_ready(task_id)
        ]
        ready: list[dict[str, object]] = []
        for task_id in ready_ids:
            if str(tasks[task_id].get("state") or "") != "pending":
                continue
            dependency_dispatch_ids: list[str] = []
            dependency_task_ids = (
                [
                    dependency_task_id
                    for dependency_task_id in graph[task_id]
                    if dependency_task_id in committed
                ]
                if spec_by_id[task_id].get("kind") == "integration"
                else graph[task_id]
            )
            for dependency_task_id in dependency_task_ids:
                row = conn.execute(
                    """SELECT dispatch_id FROM room_kernel_dispatches
                       WHERE root_id=? AND task_id=? AND state='committed'
                       ORDER BY updated_at_ms DESC,dispatch_id DESC LIMIT 1""",
                    (root_id, dependency_task_id),
                ).fetchone()
                if row is None:
                    raise RoomKernelFenceError(
                        "completed Plan Task has no committed Dispatch authority"
                    )
                dependency_dispatch_ids.append(str(row["dispatch_id"]))
            ready.append(
                {
                    "spec": spec_by_id[task_id],
                    "task": tasks[task_id],
                    "dependencyDispatchIds": dependency_dispatch_ids,
                }
            )
        capability_epochs = []
        for row in conn.execute(
            "SELECT payload_json FROM room_kernel_dispatches WHERE root_id=?",
            (root_id,),
        ).fetchall():
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, Mapping):
                capability_epochs.append(int(payload.get("capabilityEpoch") or 0))
        return {
            "planRevision": dict(plan),
            "tasks": ready,
            "nextCapabilityEpoch": max(capability_epochs, default=0) + 1,
        }

    def release_plan_frontier(
        self,
        root_id: str,
        *,
        tasks: Sequence[Mapping[str, object]],
        dispatches: Sequence[Mapping[str, object]],
        now_ms: int,
    ) -> dict[str, object]:
        """Atomically bind workspaces and release exactly one ready wave."""

        task_values = [dict(value) for value in tasks]
        dispatch_values = [dict(value) for value in dispatches]
        with self._connect(immediate=True) as conn:
            frontier = self._plan_runnable_frontier_locked(conn, root_id)
            plan = frontier.get("planRevision")
            expected = [
                str(value["task"]["taskId"])
                for value in frontier.get("tasks", [])
                if isinstance(value, Mapping)
                and isinstance(value.get("task"), Mapping)
            ]
            actual_tasks = [str(value.get("taskId") or "") for value in task_values]
            actual_dispatches = [
                str(value.get("taskId") or "") for value in dispatch_values
            ]
            if (
                not isinstance(plan, Mapping)
                or not expected
                or actual_tasks != expected
                or actual_dispatches != expected
            ):
                raise RoomKernelFenceError(
                    "Plan frontier changed before its atomic release"
                )
            ready_by_id = {
                str(value["task"]["taskId"]): value
                for value in frontier["tasks"]
            }
            for task_value in task_values:
                task_id = str(task_value["taskId"])
                prior = ready_by_id[task_id]["task"]
                for field in (
                    "rootId",
                    "planRevisionId",
                    "planTaskKind",
                    "dependencyTaskIds",
                    "currentOwnerParticipantId",
                ):
                    if task_value.get(field) != prior.get(field):
                        raise RoomKernelFenceError(
                            "released Plan Task changed its approved identity"
                        )
                task_value["state"] = "active"
                validate_kernel_contract("roomTask", task_value)
                updated = conn.execute(
                    """UPDATE room_kernel_tasks
                       SET state='active',payload_json=?,updated_at_ms=?
                       WHERE task_id=? AND state='pending'""",
                    (_json(task_value), int(now_ms), task_id),
                )
                if updated.rowcount != 1:
                    raise RoomKernelFenceError(
                        "Plan Task activation lost its compare-and-set"
                    )
            created_dispatches: list[dict[str, object]] = []
            for dispatch_value in dispatch_values:
                task_id = str(dispatch_value.get("taskId") or "")
                ready = ready_by_id[task_id]
                if (
                    str(dispatch_value.get("triggerId") or "")
                    != str(plan["planRevisionId"])
                    or list(dispatch_value.get("dependsOnDispatchIds") or [])
                    != list(ready["dependencyDispatchIds"])
                ):
                    raise RoomKernelFenceError(
                        "Plan Dispatch changed its dependency authority"
                    )
                created_dispatch, created = self._enqueue_dispatch(
                    conn,
                    dispatch_value,
                    shadow_only=self.mode not in {
                        "cohort",
                        "test",
                        "kernel_only",
                    },
                    now_ms=now_ms,
                )
                if not created:
                    raise RoomKernelFenceError(
                        "Plan frontier Dispatch already exists without its receipt"
                    )
                created_dispatches.append(created_dispatch)
            root = self._root_row(conn, root_id)
            receipt = self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "purpose": "plan_frontier_released",
                    "planRevisionId": str(plan["planRevisionId"]),
                    "taskIds": actual_tasks,
                    "dispatchIds": [
                        str(value["dispatchId"])
                        for value in created_dispatches
                    ],
                },
                now_ms=now_ms,
            )
            RoomDomainEventRepository.append(
                conn,
                past_tense_event(
                    kind="plan_frontier_released",
                    room_id=str(root["room_id"]),
                    root_id=root_id,
                    entity_id=str(plan["planRevisionId"]),
                    generation=int(root["generation"]),
                    idempotency_key=str(receipt["receiptId"]),
                    payload=dict(receipt["details"]),
                ),
                created_at_ms=int(now_ms),
            )
            return {
                "receipt": receipt,
                "tasks": [self.task(task_id, conn=conn) for task_id in actual_tasks],
                "dispatches": created_dispatches,
            }


    def requirement_alignment_dispatches(
        self,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Project the ordered, durable requirement-alignment gate."""

        normalized_root_id = str(root_id or "").strip()
        if not normalized_root_id:
            raise ValueError("root_id must not be empty")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM room_kernel_dispatches
                   WHERE root_id=? AND intent_kind='align'
                   ORDER BY created_at_ms,dispatch_id""",
                (normalized_root_id,),
            ).fetchall()
            return [_dispatch_payload(row) for row in rows[:16]]
    def collaboration_children(
        self,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Project distinct child Dispatches proven by collaboration receipts."""

        normalized_root_id = str(root_id or "").strip()
        if not normalized_root_id:
            raise ValueError("root_id must not be empty")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT receipt_id,payload_json
                   FROM room_kernel_receipts
                   WHERE root_id=? AND receipt_kind IN ('accepted','duplicate')
                   ORDER BY created_at_ms,receipt_id""",
                (normalized_root_id,),
            ).fetchall()
            children: list[dict[str, object]] = []
            seen: set[str] = set()
            for row in rows:
                receipt = json.loads(str(row["payload_json"]))
                details = receipt.get("details")
                if not isinstance(details, Mapping):
                    continue
                child_dispatch_id = str(
                    details.get("childDispatchId") or ""
                )
                invocation_receipt_id = str(
                    details.get("invocationReceiptId") or ""
                )
                if (
                    not child_dispatch_id
                    or not invocation_receipt_id
                    or child_dispatch_id in seen
                ):
                    continue
                invocation = conn.execute(
                    """SELECT canonical_tool_name
                       FROM room_v2_tool_invocation_receipts
                       WHERE receipt_id=?""",
                    (invocation_receipt_id,),
                ).fetchone()
                if invocation is None or str(
                    invocation["canonical_tool_name"]
                ) not in {"room_collaborate", "room_commit"}:
                    continue
                try:
                    child_row = self._dispatch_row(
                        conn,
                        child_dispatch_id,
                    )
                except KeyError:
                    continue
                if str(child_row["root_id"]) != normalized_root_id:
                    continue
                child = _dispatch_payload(child_row)
                child["collaborationReceiptId"] = str(
                    row["receipt_id"]
                )
                child["invocationReceiptId"] = invocation_receipt_id
                child["resultPublic"] = (
                    str(child_row["state"]) == "committed"
                    and self._dispatch_result_is_public(
                        conn,
                        child_dispatch_id,
                    )
                )
                children.append(child)
                seen.add(child_dispatch_id)
                if len(children) >= 32:
                    break
        return children

    def initial_peer_dispatches(
        self,
        root_id: str,
    ) -> list[dict[str, object]]:
        """Project the direct wave plus proven first-level peer work."""

        normalized_root_id = str(root_id or "").strip()
        if not normalized_root_id:
            raise ValueError("root_id must not be empty")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM room_kernel_dispatches
                   WHERE root_id=? AND parent_dispatch_id IS NULL
                     AND intent_kind='execute'
                   ORDER BY created_at_ms,dispatch_id""",
                (normalized_root_id,),
            ).fetchall()
            initial: list[dict[str, object]] = []
            seen = set()
            for row in rows[:32]:
                dispatch = _dispatch_payload(row)
                dispatch_id = str(dispatch["dispatchId"])
                dispatch["resultPublic"] = (
                    str(row["state"]) == "committed"
                    and self._dispatch_result_is_public(
                        conn,
                        dispatch_id,
                    )
                )
                initial.append(dispatch)
                seen.add(dispatch_id)
        if len(initial) >= 32:
            return initial
        for child in self.collaboration_children(normalized_root_id):
            dispatch_id = str(child["dispatchId"])
            if (
                dispatch_id in seen
                or child.get("intentKind") != "execute"
                or int(child.get("depth") or 0) != 1
            ):
                continue
            initial.append(child)
            seen.add(dispatch_id)
            if len(initial) >= 32:
                break
        return initial

    def record_runtime_failure(
        self,
        dispatch_id: str,
        *,
        generation: int,
        source_event_id: str,
        runtime_turn_id: str,
        dispatch_attempt: int,
        now_ms: int,
        resource_usage: Mapping[str, object] | None = None,
        retryable: bool = False,
        had_tool_activity: bool = True,
        reason_code: str = "",
    ) -> dict[str, object]:
        """Close one failed or uncommitted Pi turn through a bounded outcome."""

        event_id = _required(source_event_id, "source_event_id")
        normalized_reason = (
            str(reason_code or "").strip()[:120]
            or "provider_failure_unclassified"
        )
        terminal_reason = (
            "room_commit_missing"
            if normalized_reason == "room_commit_missing"
            else "runtime_turn_failed"
        )
        with self._connect(immediate=True) as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            root = self._root_row(conn, str(dispatch["root_id"]))
            prior_retry = self._runtime_retry_receipt(
                conn,
                root_id=str(root["root_id"]),
                dispatch_id=dispatch_id,
                source_event_id=event_id,
            )
            if prior_retry is not None:
                return prior_retry
            existing = conn.execute(
                """SELECT reason_code,payload_json
                   FROM room_kernel_dead_letters
                   WHERE dispatch_id=?""",
                (dispatch_id,),
            ).fetchone()
            if existing is not None:
                payload = json.loads(str(existing["payload_json"]))
                if (
                    str(existing["reason_code"]) == terminal_reason
                    and payload.get("sourceEventId") == event_id
                    and isinstance(payload.get("kernelReceipt"), Mapping)
                ):
                    return dict(payload["kernelReceipt"])
                raise RoomKernelFenceError(
                    "Dispatch already has another dead-letter outcome"
                )
            if (
                generation != int(dispatch["generation"])
                or generation != int(root["generation"])
            ):
                raise RoomKernelFenceError(
                    "runtime failure generation is stale"
                )
            self._require_active_runtime_attempt(
                conn,
                dispatch=dispatch,
                runtime_turn_id=runtime_turn_id,
                dispatch_attempt=dispatch_attempt,
                candidate_kind="runtime failure",
            )
            retry_limits = conn.execute(
                """SELECT retry_limit,retry_used,deadline_at_ms
                   FROM room_kernel_root_limits WHERE root_id=?""",
                (root["root_id"],),
            ).fetchone()
            if str(dispatch["state"]) == "retry_wait":
                retry_outbox = conn.execute(
                    """SELECT available_at_ms FROM room_kernel_outbox
                       WHERE dispatch_id=?""",
                    (dispatch_id,),
                ).fetchone()
                retry_payload = json.loads(str(dispatch["payload_json"]))
                return self._receipt(
                    conn,
                    root_id=str(root["root_id"]),
                    command_id=None,
                    receipt_kind="runtime_retry_scheduled",
                    status="noop",
                    generation=generation,
                    details={
                        "dispatchId": dispatch_id,
                        "sourceEventId": event_id,
                        "reasonCode": normalized_reason,
                        "attempt": int(retry_payload.get("attempt") or 0),
                        "availableAtMs": (
                            int(retry_outbox["available_at_ms"])
                            if retry_outbox is not None
                            else int(now_ms)
                        ),
                        "hadToolActivity": False,
                        "previousState": "retry_wait",
                    },
                    now_ms=now_ms,
                )
            can_retry = (
                bool(retryable)
                # Once a managed turn has invoked a Tool, a missing
                # RoomCommit cannot prove that replay is side-effect free.
                # Fail closed and require recovery instead of running the
                # same turn a second time.
                and not bool(had_tool_activity)
                and str(root["state"]) == "running"
                and retry_limits is not None
                and int(retry_limits["retry_used"])
                < int(retry_limits["retry_limit"])
            )
            if can_retry:
                attempt = int(retry_limits["retry_used"]) + 1
                delay_ms = min(
                    RUNTIME_RETRY_MAX_DELAY_MS,
                    RUNTIME_RETRY_BASE_DELAY_MS
                    * (2 ** min(attempt - 1, 5)),
                )
                available_at_ms = int(now_ms) + delay_ms
                if available_at_ms < int(
                    retry_limits["deadline_at_ms"]
                ):
                    retry_payload = json.loads(str(dispatch["payload_json"]))
                    retry_payload["attempt"] = (
                        int(retry_payload.get("attempt") or 0) + 1
                    )
                    validate_kernel_contract(
                        "dispatchEnvelope",
                        retry_payload,
                    )
                    receipt = self._receipt(
                        conn,
                        root_id=str(root["root_id"]),
                        command_id=None,
                        receipt_kind="runtime_retry_scheduled",
                        status="applied",
                        generation=generation,
                        details={
                            "dispatchId": dispatch_id,
                            "sourceEventId": event_id,
                            "reasonCode": normalized_reason,
                            "attempt": int(retry_payload["attempt"]),
                            "retryBudgetUsed": attempt,
                            "availableAtMs": available_at_ms,
                            "hadToolActivity": bool(had_tool_activity),
                        },
                        now_ms=now_ms,
                    )
                    conn.execute(
                        """UPDATE room_kernel_root_limits
                           SET retry_used=retry_used+1,updated_at_ms=?
                           WHERE root_id=?""",
                        (int(now_ms), root["root_id"]),
                    )
                    conn.execute(
                        """UPDATE room_kernel_dispatches
                           SET state='retry_wait',payload_json=?,
                               updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (
                            _json(retry_payload),
                            int(now_ms),
                            dispatch_id,
                        ),
                    )
                    conn.execute(
                        """UPDATE room_kernel_outbox
                           SET state='retry_wait',available_at_ms=?,
                               payload_json=?,updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (
                            available_at_ms,
                            _json(retry_payload),
                            int(now_ms),
                            dispatch_id,
                        ),
                    )
                    conn.execute(
                        """UPDATE room_kernel_leases
                           SET state='completed',updated_at_ms=?
                           WHERE dispatch_id=?
                             AND state IN ('active','accepted')""",
                        (int(now_ms), dispatch_id),
                    )
                    conn.execute(
                        """UPDATE room_kernel_runtime_effects
                           SET state='intent',runtime_receipt_json='{}',
                               updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (int(now_ms), dispatch_id),
                    )
                    conn.execute(
                        """UPDATE room_kernel_abort_scopes
                           SET state='registered',cancel_receipt_json='{}',
                               updated_at_ms=?
                           WHERE dispatch_id=?""",
                        (int(now_ms), dispatch_id),
                    )
                    return receipt
            if str(dispatch["state"]) not in _ACTIVE_DISPATCH_STATES:
                return self._receipt(
                    conn,
                    root_id=str(root["root_id"]),
                    command_id=None,
                    receipt_kind="runtime_failed",
                    status="noop",
                    generation=generation,
                    details={
                        "dispatchId": dispatch_id,
                        "sourceEventId": event_id,
                        "reasonCode": terminal_reason,
                        "previousState": str(dispatch["state"]),
                    },
                    now_ms=now_ms,
                )
            receipt = self._receipt(
                conn,
                root_id=str(root["root_id"]),
                command_id=None,
                receipt_kind="runtime_failed",
                status="applied",
                generation=generation,
                details={
                    "dispatchId": dispatch_id,
                    "sourceEventId": event_id,
                    "reasonCode": terminal_reason,
                },
                now_ms=now_ms,
            )
            self._block_failed_dispatch(
                conn,
                dispatch=dispatch,
                root=root,
                now_ms=now_ms,
                resource_usage=resource_usage,
                runtime_receipt={
                    "schemaVersion": (
                        "wisdom-weasel.room-runtime-failure.v1"
                    ),
                    "status": "failed",
                    "reasonCode": terminal_reason,
                    "sourceEventId": event_id,
                },
            )
            dead_letter_id = _stable_id(
                "room-dead-letter",
                dispatch_id,
                terminal_reason,
            )
            conn.execute(
                """INSERT INTO room_kernel_dead_letters(
                   dead_letter_id,root_id,dispatch_id,reason_code,
                   payload_json,created_at_ms)
                   VALUES (?,?,?,?,?,?)""",
                (
                    dead_letter_id,
                    root["root_id"],
                    dispatch_id,
                    terminal_reason,
                    _json(
                        {
                            "sourceEventId": event_id,
                            "kernelReceipt": receipt,
                        }
                    ),
                    int(now_ms),
                ),
            )
            return receipt

    @staticmethod
    def _runtime_retry_receipt(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        dispatch_id: str,
        source_event_id: str,
    ) -> dict[str, object] | None:
        rows = conn.execute(
            """SELECT payload_json FROM room_kernel_receipts
               WHERE root_id=? AND receipt_kind='runtime_retry_scheduled'
               ORDER BY created_at_ms DESC""",
            (root_id,),
        ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            details = payload.get("details")
            if (
                isinstance(details, Mapping)
                and details.get("dispatchId") == dispatch_id
                and details.get("sourceEventId") == source_event_id
            ):
                return payload
        return None

    @staticmethod
    def _require_active_runtime_attempt(
        conn: sqlite3.Connection,
        *,
        dispatch: sqlite3.Row,
        runtime_turn_id: str,
        dispatch_attempt: int,
        candidate_kind: str,
    ) -> None:
        effect = conn.execute(
            """SELECT state,runtime_receipt_json
               FROM room_kernel_runtime_effects
               WHERE dispatch_id=?""",
            (dispatch["dispatch_id"],),
        ).fetchone()
        active = (
            json.loads(str(effect["runtime_receipt_json"] or "{}"))
            if effect is not None and str(effect["state"]) == "accepted"
            else {}
        )
        dispatch_payload = json.loads(str(dispatch["payload_json"]))
        active_turn_id = str(active.get("turnId") or "")
        active_attempt = int(active.get("dispatchAttempt", -1))
        current_attempt = int(dispatch_payload.get("attempt") or 0)
        if (
            not active_turn_id
            or active_attempt != current_attempt
            or str(runtime_turn_id or "").strip() != active_turn_id
            or int(dispatch_attempt) != active_attempt
        ):
            raise RoomKernelFenceError(
                f"{candidate_kind} does not match the active runtime turn"
            )

    def record_uncommitted_settle(
        self,
        dispatch_id: str,
        *,
        generation: int,
        runtime_turn_id: str,
        dispatch_attempt: int,
        now_ms: int,
        max_attempts: int = 3,
        settle_receipt_id: str = "",
        reason: str = "missing_room_commit",
        resource_usage: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Bound missing-commit retries, then block instead of silently settling."""

        with self._connect(immediate=True) as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            root = self._root_row(conn, str(dispatch["root_id"]))
            request_id = str(settle_receipt_id or "").strip()
            if request_id:
                replay = conn.execute(
                    """SELECT dispatch_id, kernel_receipt_json
                       FROM room_kernel_settle_attempt_receipts
                       WHERE settle_receipt_id = ?""",
                    (request_id,),
                ).fetchone()
                if replay is not None:
                    if str(replay["dispatch_id"]) != dispatch_id:
                        raise RoomKernelFenceError(
                            "settle receipt was rebound to another Dispatch"
                        )
                    payload = json.loads(str(replay["kernel_receipt_json"]))
                    if not isinstance(payload, dict):
                        raise RuntimeError("settle attempt receipt is corrupt")
                    return payload
            if generation != int(dispatch["generation"]) or generation != int(root["generation"]):
                raise RoomKernelFenceError("uncommitted settle generation is stale")
            self._require_active_runtime_attempt(
                conn,
                dispatch=dispatch,
                runtime_turn_id=runtime_turn_id,
                dispatch_attempt=dispatch_attempt,
                candidate_kind="uncommitted settle",
            )
            row = conn.execute(
                "SELECT attempt_count,state FROM room_kernel_settle_guards WHERE dispatch_id=?",
                (dispatch_id,),
            ).fetchone()
            attempts = int(row["attempt_count"]) + 1 if row is not None else 1
            blocked = attempts >= max(1, int(max_attempts))
            receipt = self._receipt(
                conn,
                root_id=str(root["root_id"]),
                command_id=None,
                receipt_kind="settle_blocked" if blocked else "settle_retry_required",
                status="rejected",
                generation=generation,
                details={
                    "dispatchId": dispatch_id,
                    "reason": str(reason or "missing_room_commit")[:500],
                    "attempt": attempts,
                    "maxAttempts": max(1, int(max_attempts)),
                },
                now_ms=now_ms,
            )
            state = "blocked" if blocked else "retry_required"
            conn.execute(
                """INSERT INTO room_kernel_settle_guards(
                   dispatch_id,attempt_count,state,last_receipt_id,updated_at_ms)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(dispatch_id) DO UPDATE SET
                     attempt_count=excluded.attempt_count,state=excluded.state,
                     last_receipt_id=excluded.last_receipt_id,updated_at_ms=excluded.updated_at_ms""",
                (dispatch_id, attempts, state, receipt["receiptId"], int(now_ms)),
            )
            if blocked:
                self._block_failed_dispatch(
                    conn,
                    dispatch=dispatch,
                    root=root,
                    now_ms=now_ms,
                    resource_usage=resource_usage,
                    runtime_receipt={
                        "schemaVersion": (
                            "wisdom-weasel.room-runtime-failure.v1"
                        ),
                        "status": "failed",
                        "reasonCode": "missing_room_commit",
                    },
                )
            if request_id:
                conn.execute(
                    """INSERT INTO room_kernel_settle_attempt_receipts(
                       settle_receipt_id, dispatch_id, kernel_receipt_json,
                       created_at_ms
                       ) VALUES (?, ?, ?, ?)""",
                    (request_id, dispatch_id, _json(receipt), int(now_ms)),
                )
            return receipt

    def settle_attempt_receipt(
        self,
        settle_receipt_id: str,
        *,
        dispatch_id: str,
    ) -> dict[str, object] | None:
        """Read one exact pre-settle attempt without advancing its guard."""

        with self._connect() as conn:
            row = conn.execute(
                """SELECT dispatch_id, kernel_receipt_json
                   FROM room_kernel_settle_attempt_receipts
                   WHERE settle_receipt_id = ?""",
                (settle_receipt_id,),
            ).fetchone()
        if row is None:
            return None
        if str(row["dispatch_id"]) != dispatch_id:
            raise RoomKernelFenceError(
                "settle receipt was rebound to another Dispatch"
            )
        payload = json.loads(str(row["kernel_receipt_json"]))
        if not isinstance(payload, dict):
            raise RuntimeError("settle attempt receipt is corrupt")
        return payload

    def outbox(self, dispatch_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM room_kernel_outbox WHERE dispatch_id = ?", (dispatch_id,)).fetchone()
            if row is None:
                raise KeyError(dispatch_id)
            return {"outboxId": str(row["outbox_id"]), "rootId": str(row["root_id"]), "dispatchId": dispatch_id, "generation": int(row["generation"]), "state": str(row["state"]), "shadowOnly": bool(row["shadow_only"]), "availableAtMs": int(row["available_at_ms"]), "payload": json.loads(str(row["payload_json"]))}

    def lease(self, dispatch_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_kernel_leases WHERE dispatch_id = ?",
                (dispatch_id,),
            ).fetchone()
            if row is None:
                raise KeyError(dispatch_id)
            task_row = conn.execute(
                """SELECT t.payload_json
                   FROM room_kernel_tasks t
                   JOIN room_kernel_dispatches d ON d.task_id=t.task_id
                   WHERE d.dispatch_id=?""",
                (dispatch_id,),
            ).fetchone()
            if task_row is None:
                raise RoomKernelFenceError(
                    "Dispatch lease has no authoritative Task identity"
                )
            task_payload = json.loads(str(task_row["payload_json"]))
            return {
                "leaseId": str(row["lease_id"]),
                "rootId": str(row["root_id"]),
                "taskId": str(task_payload["taskId"]),
                "ownershipRevision": int(
                    task_payload.get("ownershipRevision") or 0
                ),
                "dispatchId": dispatch_id,
                "generation": int(row["generation"]),
                "leaseToken": str(row["lease_token"]),
                "state": str(row["state"]),
                "expiresAtMs": int(row["expires_at_ms"]),
            }

    def receipt(self, receipt_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM room_kernel_receipts WHERE receipt_id = ?", (receipt_id,)).fetchone()
            if row is None:
                raise KeyError(receipt_id)
            return json.loads(str(row["payload_json"]))

    def counts(self, root_id: str) -> dict[str, int]:
        with self._connect() as conn:
            names = {"commands": "room_kernel_commands", "tasks": "room_kernel_tasks", "dispatches": "room_kernel_dispatches", "commits": "room_kernel_commits", "outbox": "room_kernel_outbox", "leases": "room_kernel_leases", "receipts": "room_kernel_receipts", "deadLetters": "room_kernel_dead_letters"}
            return {key: int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE root_id = ?", (root_id,)).fetchone()[0]) for key, table in names.items()}

    def resource_limits(self, root_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_kernel_root_limits WHERE root_id=?", (root_id,)
            ).fetchone()
        if row is None:
            raise KeyError(root_id)
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def _insert_root_limits(
        conn: sqlite3.Connection, root_id: str, *, now_ms: int
    ) -> None:
        conn.execute(
            """INSERT INTO room_kernel_root_limits(
               root_id,deadline_at_ms,input_token_limit,output_token_limit,
               dispatch_limit,concurrency_limit,tool_call_limit,tool_cost_limit,
               retry_limit,repair_limit,updated_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                root_id, int(now_ms) + SYSTEM_MAX_WALL_CLOCK_MS,
                SYSTEM_MAX_INPUT_TOKENS, SYSTEM_MAX_OUTPUT_TOKENS,
                SYSTEM_MAX_DISPATCHES, SYSTEM_MAX_CONCURRENCY,
                SYSTEM_MAX_TOOL_CALLS, SYSTEM_MAX_TOOL_COST,
                SYSTEM_MAX_RETRIES, SYSTEM_MAX_REPAIRS, int(now_ms),
            ),
        )

    @staticmethod
    def _reserve_dispatch_limits(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        dispatch_id: str,
        defer_concurrency: bool,
        now_ms: int,
    ) -> None:
        limits = conn.execute(
            "SELECT * FROM room_kernel_root_limits WHERE root_id=?", (root_id,)
        ).fetchone()
        if limits is None:
            raise RoomKernelFenceError("Root resource limits are missing")
        if int(now_ms) >= int(limits["deadline_at_ms"]):
            raise RoomKernelFenceError("Root wall-clock deadline exceeded")
        checks = (
            ("dispatch", 1, "dispatch_limit", "dispatch_used", "dispatch_reserved"),
            ("input token", DISPATCH_INPUT_TOKEN_RESERVATION, "input_token_limit", "input_token_used", "input_token_reserved"),
            ("output token", DISPATCH_OUTPUT_TOKEN_RESERVATION, "output_token_limit", "output_token_used", "output_token_reserved"),
            ("tool call", DISPATCH_TOOL_CALL_RESERVATION, "tool_call_limit", "tool_call_used", "tool_call_reserved"),
            ("tool cost", DISPATCH_TOOL_COST_RESERVATION, "tool_cost_limit", "tool_cost_used", "tool_cost_reserved"),
        )
        for label, requested, limit_key, used_key, reserved_key in checks:
            used = int(limits[used_key])
            if used + int(limits[reserved_key]) + requested > int(limits[limit_key]):
                raise RoomKernelFenceError(f"Root {label} limit exhausted")
        concurrency_acquired = 0 if defer_concurrency else 1
        if (
            int(limits["concurrency_reserved"]) + concurrency_acquired
            > int(limits["concurrency_limit"])
        ):
            raise RoomKernelFenceError("Root concurrency limit exhausted")
        conn.execute(
            """INSERT INTO room_kernel_dispatch_resource_reservations(
               dispatch_id,root_id,input_tokens,output_tokens,tool_calls,tool_cost,
               concurrency_acquired,state,created_at_ms,updated_at_ms)
               VALUES (?,?,?,?,?,?,?,'reserved',?,?)""",
            (
                dispatch_id, root_id, DISPATCH_INPUT_TOKEN_RESERVATION,
                DISPATCH_OUTPUT_TOKEN_RESERVATION, DISPATCH_TOOL_CALL_RESERVATION,
                DISPATCH_TOOL_COST_RESERVATION, concurrency_acquired,
                int(now_ms), int(now_ms),
            ),
        )
        conn.execute(
            """UPDATE room_kernel_root_limits SET
               dispatch_reserved=dispatch_reserved+1,
               concurrency_reserved=concurrency_reserved+?,
               input_token_reserved=input_token_reserved+?,
               output_token_reserved=output_token_reserved+?,
               tool_call_reserved=tool_call_reserved+?,
               tool_cost_reserved=tool_cost_reserved+?,updated_at_ms=?
               WHERE root_id=?""",
            (
                concurrency_acquired, DISPATCH_INPUT_TOKEN_RESERVATION,
                DISPATCH_OUTPUT_TOKEN_RESERVATION,
                DISPATCH_TOOL_CALL_RESERVATION, DISPATCH_TOOL_COST_RESERVATION,
                int(now_ms), root_id,
            ),
        )

    @staticmethod
    def _dispatch_concurrency_available(
        conn: sqlite3.Connection,
        *,
        root_id: str,
        dispatch_id: str,
    ) -> bool:
        reservation = conn.execute(
            """SELECT root_id,state,concurrency_acquired
               FROM room_kernel_dispatch_resource_reservations
               WHERE dispatch_id=?""",
            (dispatch_id,),
        ).fetchone()
        if (
            reservation is None
            or str(reservation["root_id"]) != root_id
            or str(reservation["state"]) != "reserved"
        ):
            raise RoomKernelFenceError(
                "Dispatch resource reservation is missing or inactive"
            )
        if int(reservation["concurrency_acquired"]) == 1:
            return True
        limits = conn.execute(
            """SELECT concurrency_limit,concurrency_reserved
               FROM room_kernel_root_limits WHERE root_id=?""",
            (root_id,),
        ).fetchone()
        if limits is None:
            raise RoomKernelFenceError("Root resource limits are missing")
        return int(limits["concurrency_reserved"]) < int(
            limits["concurrency_limit"]
        )

    @classmethod
    def _acquire_dispatch_concurrency(
        cls,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        dispatch_id: str,
        now_ms: int,
    ) -> bool:
        if not cls._dispatch_concurrency_available(
            conn,
            root_id=root_id,
            dispatch_id=dispatch_id,
        ):
            return False
        reservation = conn.execute(
            """SELECT concurrency_acquired
               FROM room_kernel_dispatch_resource_reservations
               WHERE dispatch_id=?""",
            (dispatch_id,),
        ).fetchone()
        if reservation is None:
            raise RoomKernelFenceError("Dispatch resource reservation is missing")
        if int(reservation["concurrency_acquired"]) == 1:
            return True
        acquired = conn.execute(
            """UPDATE room_kernel_dispatch_resource_reservations
               SET concurrency_acquired=1,updated_at_ms=?
               WHERE dispatch_id=? AND state='reserved'
                 AND concurrency_acquired=0""",
            (int(now_ms), dispatch_id),
        )
        if acquired.rowcount != 1:
            raise RoomKernelFenceError(
                "Dispatch concurrency reservation changed during acquisition"
            )
        conn.execute(
            """UPDATE room_kernel_root_limits
               SET concurrency_reserved=concurrency_reserved+1,
                   updated_at_ms=?
               WHERE root_id=?""",
            (int(now_ms), root_id),
        )
        return True

    def _block_failed_dispatch(
        self,
        conn: sqlite3.Connection,
        *,
        dispatch: sqlite3.Row,
        root: sqlite3.Row,
        now_ms: int,
        resource_usage: Mapping[str, object] | None,
        runtime_receipt: Mapping[str, object],
    ) -> None:
        """Apply the one durable transition shared by failed settle paths."""

        dispatch_id = str(dispatch["dispatch_id"])
        report = self._report_dispatch_locked(
            conn,
            root_id=str(root["root_id"]),
        )
        is_report_dispatch = bool(
            report is not None
            and str(report["dispatch"]["dispatchId"]) == dispatch_id
            and str(report["task"]["taskId"]) == str(dispatch["task_id"])
        )
        conn.execute(
            """UPDATE room_kernel_tasks
               SET state=?,updated_at_ms=? WHERE task_id=?""",
            (
                "failed" if is_report_dispatch else "blocked",
                int(now_ms),
                dispatch["task_id"],
            ),
        )
        conn.execute(
            """UPDATE room_kernel_roots
               SET state='blocked',
                   budget_remaining=MAX(0,budget_remaining-?),
                   budget_reserved=MAX(0,budget_reserved-?),
                   updated_at_ms=?
               WHERE root_id=?""",
            (
                int(dispatch["budget_cost"]),
                int(dispatch["budget_cost"]),
                int(now_ms),
                root["root_id"],
            ),
        )
        conn.execute(
            """UPDATE room_kernel_dispatches
               SET state='failed',updated_at_ms=? WHERE dispatch_id=?""",
            (int(now_ms), dispatch_id),
        )
        conn.execute(
            """UPDATE room_kernel_outbox
               SET state='dead_letter',updated_at_ms=? WHERE dispatch_id=?""",
            (int(now_ms), dispatch_id),
        )
        conn.execute(
            """UPDATE room_kernel_leases
               SET state='completed',updated_at_ms=?
               WHERE dispatch_id=? AND state IN ('active','accepted')""",
            (int(now_ms), dispatch_id),
        )
        conn.execute(
            """UPDATE room_kernel_runtime_effects
               SET state='failed',runtime_receipt_json=?,updated_at_ms=?
               WHERE dispatch_id=?""",
            (_json(runtime_receipt), int(now_ms), dispatch_id),
        )
        conn.execute(
            """UPDATE room_kernel_abort_scopes
               SET state='failed',cancel_receipt_json=?,updated_at_ms=?
               WHERE dispatch_id=?""",
            (_json(runtime_receipt), int(now_ms), dispatch_id),
        )
        RoomKernelStore._settle_dispatch_limits(
            conn,
            dispatch_id,
            usage=resource_usage,
            consumed=True,
            now_ms=now_ms,
        )

    @staticmethod
    def _settle_dispatch_limits(
        conn: sqlite3.Connection,
        dispatch_id: str,
        *,
        usage: Mapping[str, object] | None,
        consumed: bool,
        now_ms: int,
    ) -> None:
        reservation = conn.execute(
            """SELECT * FROM room_kernel_dispatch_resource_reservations
               WHERE dispatch_id=? AND state='reserved'""",
            (dispatch_id,),
        ).fetchone()
        if reservation is None:
            return
        actual = {key: max(0, int((usage or {}).get(key, 0))) for key in (
            "inputTokens", "outputTokens", "toolCalls", "toolCost", "retryCount", "repairCount"
        )}
        if not consumed:
            actual = {key: 0 for key in actual}
        limits = conn.execute(
            "SELECT * FROM room_kernel_root_limits WHERE root_id=?", (reservation["root_id"],)
        ).fetchone()
        for actual_key, limit_key, used_key, reserved_key, reservation_key in (
            ("inputTokens", "input_token_limit", "input_token_used", "input_token_reserved", "input_tokens"),
            ("outputTokens", "output_token_limit", "output_token_used", "output_token_reserved", "output_tokens"),
            ("toolCalls", "tool_call_limit", "tool_call_used", "tool_call_reserved", "tool_calls"),
            ("toolCost", "tool_cost_limit", "tool_cost_used", "tool_cost_reserved", "tool_cost"),
            ("retryCount", "retry_limit", "retry_used", None, None),
            ("repairCount", "repair_limit", "repair_used", None, None),
        ):
            other_reserved = (
                max(0, int(limits[reserved_key]) - int(reservation[reservation_key]))
                if reserved_key and reservation_key
                else 0
            )
            if int(limits[used_key]) + other_reserved + actual[actual_key] > int(limits[limit_key]):
                raise RoomKernelFenceError(f"Root {actual_key} usage exceeds hard limit")
        conn.execute(
            """UPDATE room_kernel_root_limits SET
               input_token_reserved=MAX(0,input_token_reserved-?),
               output_token_reserved=MAX(0,output_token_reserved-?),
               tool_call_reserved=MAX(0,tool_call_reserved-?),
               tool_cost_reserved=MAX(0,tool_cost_reserved-?),
               dispatch_reserved=MAX(0,dispatch_reserved-1),
               concurrency_reserved=MAX(0,concurrency_reserved-?),
               dispatch_used=dispatch_used+?,input_token_used=input_token_used+?,
               output_token_used=output_token_used+?,tool_call_used=tool_call_used+?,
               tool_cost_used=tool_cost_used+?,retry_used=retry_used+?,repair_used=repair_used+?,
               updated_at_ms=? WHERE root_id=?""",
            (
                reservation["input_tokens"], reservation["output_tokens"],
                reservation["tool_calls"], reservation["tool_cost"],
                reservation["concurrency_acquired"],
                1 if consumed else 0, actual["inputTokens"], actual["outputTokens"],
                actual["toolCalls"], actual["toolCost"], actual["retryCount"],
                actual["repairCount"], int(now_ms), reservation["root_id"],
            ),
        )
        conn.execute(
            """UPDATE room_kernel_dispatch_resource_reservations
               SET state=?,actual_usage_json=?,updated_at_ms=? WHERE dispatch_id=?""",
            ("consumed" if consumed else "released", _json(actual), int(now_ms), dispatch_id),
        )

    @classmethod
    def _is_active_alignment_dispatch_chain(
        cls,
        conn: sqlite3.Connection,
        dispatch: sqlite3.Row,
        root: sqlite3.Row,
    ) -> bool:
        """Fence room_define to one live facilitator chain rooted at intent=align."""

        return cls._is_alignment_dispatch_chain(
            conn,
            dispatch,
            root,
            leaf_states=("running",),
        )

    @classmethod
    def _is_alignment_dispatch_chain(
        cls,
        conn: sqlite3.Connection,
        dispatch: sqlite3.Row,
        root: sqlite3.Row,
        *,
        leaf_states: Sequence[str],
    ) -> bool:
        """Verify immutable alignment lineage at one explicit lifecycle state."""

        root_id = str(root["root_id"])
        task_id = str(dispatch["task_id"])
        generation = int(root["generation"])
        facilitator_id = str(root["facilitator_participant_id"])
        current = dispatch
        is_leaf = True
        seen: set[str] = set()
        while True:
            current_id = str(current["dispatch_id"])
            if current_id in seen:
                return False
            seen.add(current_id)
            if (
                str(current["root_id"]) != root_id
                or str(current["task_id"]) != task_id
                or int(current["generation"]) != generation
                or str(current["target_participant_id"]) != facilitator_id
                or str(current["state"])
                not in (leaf_states if is_leaf else ("committed",))
            ):
                return False
            intent = str(current["intent_kind"])
            parent_id = str(current["parent_dispatch_id"] or "")
            if intent == "align":
                return not parent_id
            if intent != "resume" or not parent_id:
                return False
            try:
                parent = cls._dispatch_row(conn, parent_id)
            except KeyError:
                return False
            if (
                int(current["hop_count"]) != int(parent["hop_count"]) + 1
                or int(current["depth"]) != int(parent["depth"])
            ):
                return False
            current = parent
            is_leaf = False

    @staticmethod
    def _root_row(conn: sqlite3.Connection, root_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM room_kernel_roots WHERE root_id = ?", (root_id,)).fetchone()
        if row is None:
            raise KeyError(root_id)
        return row

    @staticmethod
    def _dispatch_row(conn: sqlite3.Connection, dispatch_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM room_kernel_dispatches WHERE dispatch_id = ?", (dispatch_id,)).fetchone()
        if row is None:
            raise KeyError(dispatch_id)
        return row

    @contextmanager
    def _write_connection(
        self,
        conn: sqlite3.Connection | None,
    ):
        if conn is not None:
            yield conn
            return
        with self._connect(immediate=True) as owned:
            yield owned

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if immediate:
                conn.commit()
        except Exception:
            if immediate:
                conn.rollback()
            raise
        finally:
            conn.close()


def _room_screen_phase(*, root_state: str, intake_phase: str) -> str:
    terminal = {
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "cancelled_with_unknowns": "cancelled",
        "cancelling": "cancelling",
        "blocked": "blocked",
    }
    if root_state in terminal:
        return terminal[root_state]
    if intake_phase in {"aligning", "clarifying"}:
        return "alignment"
    if intake_phase in {"awaiting_start", "execution_ready"}:
        return "planning"
    if root_state == "waiting":
        return "waiting"
    if root_state == "pending":
        return "planning"
    return "execution"


def _room_screen_next_action(
    *,
    phase: str,
    wait_reason: Mapping[str, object] | None,
    has_frontier: bool,
    integration_ready: bool,
    review_ready: bool,
) -> str:
    if phase == "alignment":
        return "align_requirement"
    if phase == "planning":
        return "confirm_plan"
    if phase in {"completed", "failed", "cancelled"}:
        return "start_new_task"
    if phase == "blocked":
        return "resolve_blocker"
    if wait_reason is not None and wait_reason.get("kind") == "user":
        return "answer_question"
    if has_frontier:
        return "continue_execution"
    if not integration_ready:
        return "integrate_results"
    if not review_ready:
        return "complete_independent_review"
    return "wait_for_progress"


def _dispatch_dependency_ids(payload: Mapping[str, object]) -> list[str]:
    try:
        return domain_dependency_ids(payload)
    except DomainPolicyError as exc:
        raise RoomKernelFenceError(f"Dispatch {exc}") from exc


def _payload_depends_on(
    payload: Mapping[str, object],
    target_dispatch_id: str,
    *,
    dispatches_by_id: Mapping[str, Mapping[str, object]],
    visited: set[str] | None = None,
) -> bool:
    try:
        return domain_payload_depends_on(
            payload,
            target_dispatch_id,
            dispatches_by_id=dispatches_by_id,
            visited=visited,
        )
    except DomainPolicyError as exc:
        raise RoomKernelFenceError(f"Dispatch {exc}") from exc


def _dispatch_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = json.loads(str(row["payload_json"]))
    payload["state"] = str(row["state"])
    return payload


def _room_commit_payload(
    conn: sqlite3.Connection,
    encoded: object,
) -> dict[str, object]:
    """Decode one immutable Commit row through the current read contract."""

    decoded = json.loads(str(encoded))
    if not isinstance(decoded, Mapping):
        raise RoomKernelFenceError("Room Commit payload is corrupt")
    dispatch_id = str(decoded.get("dispatchId") or "").strip()
    if not dispatch_id:
        raise RoomKernelFenceError("Room Commit Dispatch identity is missing")
    dispatch = RoomKernelStore._dispatch_row(conn, dispatch_id)
    return upcast_room_commit(
        decoded,
        root_id=dispatch["root_id"],
        task_id=dispatch["task_id"],
        generation=int(dispatch["generation"]),
    )


def _decode_room_continuation_payload(encoded: object) -> dict[str, object]:
    decoded = json.loads(str(encoded))
    if not isinstance(decoded, Mapping):
        raise RoomKernelFenceError("Room continuation payload is corrupt")
    return dict(decoded)


def _room_continuation_payload(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, object]:
    """Project a materialized continuation through its immutable Commit.

    Historical continuation rows store only the continuation fragment and do
    not carry a schema version.  The immutable Commit is the version authority;
    its existing read upcaster supplies current semantic fields.  Materialized
    runtime state (for example a resume Dispatch or user-answer identity) is
    retained without rewriting the stored historical fragment.

    The table has no foreign key to Commits, so an orphan row is possible.  It
    is rejected instead of being guessed into a current-looking, auto-resumable
    wait.
    """

    materialized = _decode_room_continuation_payload(row["payload_json"])
    commit_id = str(row["commit_id"] or "").strip()
    if not commit_id:
        raise RoomKernelFenceError("Room continuation Commit identity is missing")
    commit_row = conn.execute(
        "SELECT payload_json FROM room_kernel_commits WHERE commit_id=?",
        (commit_id,),
    ).fetchone()
    if commit_row is None:
        raise RoomKernelFenceError(
            "Room continuation has no authoritative Commit"
        )
    commit = _room_commit_payload(conn, commit_row["payload_json"])
    canonical = commit.get("continuation")
    if canonical is None:
        if materialized:
            raise RoomKernelFenceError(
                "Room continuation has no authoritative Commit continuation"
            )
        return materialized
    if not isinstance(canonical, Mapping):
        raise RoomKernelFenceError("Room Commit continuation is corrupt")
    result = {**materialized, **dict(canonical)}
    table_decision = str(row["decision"] or "").strip()
    canonical_decision = str(result.get("decision") or "").strip()
    if not canonical_decision or canonical_decision != table_decision:
        raise RoomKernelFenceError(
            "Room continuation decision does not match its Commit"
        )
    return result


def _room_continuation_question_post_id(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> str:
    """Return the durable public question identity for one user wait.

    The settlement and Kernel modules intentionally have different generic
    stable-ID widths.  A question answer must therefore follow the immutable
    RoomCommit/Post identity that was actually persisted and shown to the
    user, never reconstruct that identity with a module-local hash helper.
    """

    commit_id = str(row["commit_id"] or "").strip()
    if not commit_id:
        raise RoomKernelFenceError(
            "Room continuation Commit identity is missing"
        )
    commit_row = conn.execute(
        "SELECT payload_json FROM room_kernel_commits WHERE commit_id=?",
        (commit_id,),
    ).fetchone()
    if commit_row is None:
        raise RoomKernelFenceError(
            "Room continuation has no authoritative Commit"
        )
    try:
        raw_commit = json.loads(str(commit_row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RoomKernelFenceError("Room Commit is corrupt") from exc
    if not isinstance(raw_commit, Mapping):
        raise RoomKernelFenceError("Room Commit is corrupt")
    commit = _room_commit_payload(conn, commit_row["payload_json"])
    proposal = commit.get("postProposal")
    publication_source = (
        proposal.get("publicationSource")
        if isinstance(proposal, Mapping)
        else None
    )
    question = (
        proposal.get("question")
        if isinstance(proposal, Mapping)
        else None
    )
    if commit.get("action") == "wait" and proposal is None:
        # Builds predating durable question Posts exposed the Kernel's own
        # deterministic 32-character identity directly from a materialized
        # wait continuation.  Those immutable rows cannot be rewritten, and
        # changing the identity strands a Room that is already waiting for an
        # answer.  Recover only that exact historical shape; current `post`
        # commits must pass the strict durable-Post fence below.
        raw_continuation = raw_commit.get("continuation")
        canonical_continuation = commit.get("continuation")
        if (
            raw_commit.get("action") == "wait"
            and raw_commit.get("postProposal") is None
            and isinstance(raw_continuation, Mapping)
            and isinstance(canonical_continuation, Mapping)
            and raw_continuation.get("decision") == "wait"
            and raw_continuation.get("waitingFor") == "user"
            and canonical_continuation.get("decision") == "wait"
            and canonical_continuation.get("waitingFor") == "user"
            and bool(str(canonical_continuation.get("question") or "").strip())
        ):
            return _stable_id("room-post", commit_id)
        raise RoomKernelFenceError(
            "legacy user wait has no authoritative question identity"
        )
    if (
        commit.get("action") != "post"
        or not isinstance(proposal, Mapping)
        or str(proposal.get("rootId") or "") != str(row["root_id"])
        or str(proposal.get("taskId") or "") != str(row["task_id"])
        or proposal.get("kind") != "wait"
        or not isinstance(question, Mapping)
        or not isinstance(publication_source, Mapping)
        or publication_source.get("kind") != "room_commit"
        or str(publication_source.get("ref") or "") != commit_id
    ):
        raise RoomKernelFenceError(
            "user wait has no authoritative question Post"
        )
    post_id = str(proposal.get("postId") or "").strip()
    if not post_id:
        raise RoomKernelFenceError(
            "user wait question Post identity is missing"
        )
    stored_row = conn.execute(
        "SELECT payload_json FROM room_kernel_posts WHERE post_id=?",
        (post_id,),
    ).fetchone()
    if stored_row is None:
        raise RoomKernelFenceError(
            "user wait question Post is not durable"
        )
    try:
        stored_post = json.loads(str(stored_row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RoomKernelFenceError(
            "user wait question Post is corrupt"
        ) from exc
    if not isinstance(stored_post, Mapping):
        raise RoomKernelFenceError(
            "user wait question Post is corrupt"
        )
    try:
        validate_kernel_contract("roomPost", stored_post)
    except ValueError as exc:
        raise RoomKernelFenceError(
            "user wait question Post is invalid"
        ) from exc
    # Authorized rich blocks are normalized between the immutable Tool
    # proposal and the durable Post.  Bind only the immutable question and
    # publication semantics here; whole-object equality would reject that
    # legitimate normalization.
    identity_fields = (
        "schemaVersion",
        "postId",
        "roomId",
        "rootId",
        "generation",
        "taskId",
        "dispatchId",
        "authorActorRef",
        "kind",
        "visibility",
        "content",
        "idempotencyKey",
        "publicationSource",
        "createdAtMs",
        "question",
    )
    if any(
        stored_post.get(field) != proposal.get(field)
        for field in identity_fields
    ):
        raise RoomKernelFenceError(
            "user wait question Post does not match its Commit"
        )
    return post_id


def _participant_wait_runtime_authorized(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    payload: Mapping[str, object],
) -> bool:
    """True only for an explicit participant wait written by current v4.

    Historical Commit upcasters intentionally make older data readable.  That
    projection is not authority to execute a synthesized continuation.  The
    immutable raw Commit must itself contain the current participant and
    Dispatch identities before the Kernel may auto-resume it.
    """

    commit_id = str(row["commit_id"] or "").strip()
    if not commit_id:
        return False
    commit_row = conn.execute(
        "SELECT payload_json FROM room_kernel_commits WHERE commit_id=?",
        (commit_id,),
    ).fetchone()
    if commit_row is None:
        return False
    try:
        raw_commit = json.loads(str(commit_row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(raw_commit, Mapping):
        return False
    if raw_commit.get("schemaVersion") != ROOM_COMMIT_SCHEMA_VERSION:
        return False
    raw_continuation = raw_commit.get("continuation")
    if not isinstance(raw_continuation, Mapping):
        return False
    return (
        str(raw_continuation.get("decision") or "").strip()
        == str(row["decision"] or "").strip()
        and raw_continuation.get("waitingFor") == "participant"
        and str(
            raw_continuation.get("waitingForParticipantId") or ""
        ).strip()
        == str(payload.get("waitingForParticipantId") or "").strip()
        and str(
            raw_continuation.get("waitingForDispatchId") or ""
        ).strip()
        == str(payload.get("waitingForDispatchId") or "").strip()
        and bool(
            str(
                raw_continuation.get("waitingForParticipantId") or ""
            ).strip()
        )
        and bool(
            str(raw_continuation.get("waitingForDispatchId") or "").strip()
        )
    )


def _managed_external_retry_wait_dependency(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    payload: Mapping[str, object],
) -> dict[str, str] | None:
    """Load persisted facts; the pure waiting policy owns the match."""

    commit_row = conn.execute(
        "SELECT payload_json FROM room_kernel_commits WHERE commit_id=?",
        (row["commit_id"],),
    ).fetchone()
    if commit_row is None:
        return None
    try:
        raw_commit = json.loads(str(commit_row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    raw_continuation = (
        raw_commit.get("continuation")
        if isinstance(raw_commit, Mapping)
        else None
    )
    parent = conn.execute(
        """SELECT * FROM room_kernel_dispatches
           WHERE dispatch_id=? AND root_id=?""",
        (row["parent_dispatch_id"], row["root_id"]),
    ).fetchone()
    root = conn.execute(
        "SELECT facilitator_participant_id,generation FROM room_kernel_roots WHERE root_id=?",
        (row["root_id"],),
    ).fetchone()
    task = conn.execute(
        "SELECT payload_json FROM room_kernel_tasks WHERE task_id=? AND root_id=?",
        (row["task_id"], row["root_id"]),
    ).fetchone()
    if parent is None or root is None or task is None:
        return None
    try:
        parent_payload = _dispatch_payload(parent)
        task_payload = json.loads(str(task["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(task_payload, Mapping):
        return None
    candidates = conn.execute(
        """SELECT dispatch.*, task.state AS task_state
           FROM room_kernel_dispatches dispatch
           JOIN room_kernel_tasks task ON task.task_id=dispatch.task_id
           WHERE dispatch.root_id=?
             AND dispatch.parent_dispatch_id=?
             AND dispatch.intent_kind='retry'
           ORDER BY dispatch.created_at_ms,dispatch.dispatch_id""",
        (
            row["root_id"],
            row["parent_dispatch_id"],
        ),
    ).fetchall()
    candidate_facts: list[dict[str, object]] = []
    for candidate in candidates:
        try:
            candidate_payload = _dispatch_payload(candidate)
        except (RoomKernelFenceError, TypeError, ValueError):
            continue
        candidate_facts.append(
            {
                "dispatchId": str(candidate["dispatch_id"]),
                "participantId": str(candidate["target_participant_id"]),
                "taskId": str(candidate["task_id"]),
                "generation": int(candidate["generation"]),
                "capabilityEpoch": int(
                    candidate_payload.get("capabilityEpoch") or 0
                ),
                "createdAtMs": int(candidate["created_at_ms"]),
                "updatedAtMs": int(candidate["updated_at_ms"]),
                "state": str(candidate["state"]),
                "taskState": str(candidate["task_state"]),
            }
        )
    return match_managed_retry_wait(
        ManagedRetryWaitFacts(
            continuation_decision=str(row["decision"] or ""),
            waiting_for=str(payload.get("waitingFor") or ""),
            child_dispatch_id=(
                str(row["child_dispatch_id"])
                if row["child_dispatch_id"] is not None
                else None
            ),
            commit_schema_version=(
                str(raw_commit.get("schemaVersion") or "")
                if isinstance(raw_commit, Mapping)
                else ""
            ),
            commit_dispatch_id=(
                str(raw_commit.get("dispatchId") or "")
                if isinstance(raw_commit, Mapping)
                else ""
            ),
            commit_continuation_decision=(
                str(raw_continuation.get("decision") or "")
                if isinstance(raw_continuation, Mapping)
                else ""
            ),
            commit_waiting_for=(
                str(raw_continuation.get("waitingFor") or "")
                if isinstance(raw_continuation, Mapping)
                else ""
            ),
            parent_dispatch_id=str(row["parent_dispatch_id"] or ""),
            parent_intent_kind=str(parent["intent_kind"] or ""),
            parent_participant_id=str(
                parent["target_participant_id"] or ""
            ),
            facilitator_participant_id=str(
                root["facilitator_participant_id"] or ""
            ),
            parent_task_id=str(row["task_id"] or ""),
            task_parent_id=(
                str(task_payload.get("parentTaskId"))
                if task_payload.get("parentTaskId") is not None
                else None
            ),
            root_generation=int(root["generation"]),
            parent_generation=int(parent["generation"]),
            parent_capability_epoch=int(
                parent_payload.get("capabilityEpoch") or 0
            ),
            continuation_created_at_ms=int(row["created_at_ms"]),
            candidates=tuple(candidate_facts),
        )
    )


def _managed_integration_external_wait_dependency(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    payload: Mapping[str, object],
) -> dict[str, str] | None:
    """Recover an old integration wait from its exact delivered dependency.

    Current settlement rejects this shape before it can be persisted.  Older
    installed versions could nevertheless let an Integration Task wait for an
    unspecified external signal while already-completed peer work was waiting
    in its dependency graph.  The durable Task and committed Dispatch provide
    the exact signal needed to resume that same Integration Task once.
    """

    if (
        str(row["decision"] or "") != "wait"
        or payload.get("waitingFor") != "external"
        or row["child_dispatch_id"] is not None
    ):
        return None
    commit_row = conn.execute(
        "SELECT payload_json FROM room_kernel_commits WHERE commit_id=?",
        (row["commit_id"],),
    ).fetchone()
    parent = conn.execute(
        "SELECT * FROM room_kernel_dispatches WHERE dispatch_id=? AND root_id=?",
        (row["parent_dispatch_id"], row["root_id"]),
    ).fetchone()
    root = conn.execute(
        "SELECT generation FROM room_kernel_roots WHERE root_id=?",
        (row["root_id"],),
    ).fetchone()
    task = conn.execute(
        "SELECT state,payload_json FROM room_kernel_tasks "
        "WHERE task_id=? AND root_id=?",
        (row["task_id"], row["root_id"]),
    ).fetchone()
    if commit_row is None or parent is None or root is None or task is None:
        return None
    try:
        raw_commit = json.loads(str(commit_row["payload_json"]))
        parent_payload = _dispatch_payload(parent)
        task_payload = json.loads(str(task["payload_json"]))
    except (RoomKernelFenceError, TypeError, ValueError, json.JSONDecodeError):
        return None
    raw_continuation = (
        raw_commit.get("continuation")
        if isinstance(raw_commit, Mapping)
        else None
    )
    if (
        not isinstance(raw_commit, Mapping)
        or raw_commit.get("schemaVersion") != ROOM_COMMIT_SCHEMA_VERSION
        or raw_commit.get("dispatchId") != row["parent_dispatch_id"]
        or not isinstance(raw_continuation, Mapping)
        or raw_continuation.get("decision") != "wait"
        or raw_continuation.get("waitingFor") != "external"
        or not isinstance(task_payload, Mapping)
        or task_payload.get("planTaskKind") != "integration"
        or str(task["state"]) != "waiting"
        or int(parent["generation"]) != int(root["generation"])
        or int(parent_payload.get("capabilityEpoch") or 0) < 0
    ):
        return None
    dependency_ids = sorted(
        {
            str(value)
            for value in task_payload.get("dependencyTaskIds") or []
            if str(value or "").strip()
        }
    )
    for dependency_id in dependency_ids:
        dependency = conn.execute(
            "SELECT state,payload_json FROM room_kernel_tasks "
            "WHERE task_id=? AND root_id=?",
            (dependency_id, row["root_id"]),
        ).fetchone()
        if dependency is None or str(dependency["state"]) != "completed":
            continue
        try:
            dependency_payload = json.loads(
                str(dependency["payload_json"])
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            not isinstance(dependency_payload, Mapping)
            or dependency_payload.get("workspacePolicy")
            != "isolated_writable"
            or dependency_payload.get("workspaceIntegrationState")
            != "pending"
        ):
            continue
        dependency_dispatch = conn.execute(
            """SELECT * FROM room_kernel_dispatches
               WHERE root_id=? AND task_id=? AND generation=?
                 AND state='committed'
               ORDER BY updated_at_ms DESC,created_at_ms DESC,dispatch_id DESC
               LIMIT 1""",
            (row["root_id"], dependency_id, int(root["generation"])),
        ).fetchone()
        if dependency_dispatch is None:
            continue
        return {
            "dispatchId": str(dependency_dispatch["dispatch_id"]),
            "participantId": str(
                dependency_dispatch["target_participant_id"]
            ),
        }
    return None


def _historical_participant_wait_requires_recovery(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    payload: Mapping[str, object],
) -> bool:
    """Recognize exact late-v3 identity without granting execute authority."""

    commit_id = str(row["commit_id"] or "").strip()
    if not commit_id:
        return False
    commit_row = conn.execute(
        "SELECT payload_json FROM room_kernel_commits WHERE commit_id=?",
        (commit_id,),
    ).fetchone()
    if commit_row is None:
        return False
    try:
        raw_commit = json.loads(str(commit_row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if (
        not isinstance(raw_commit, Mapping)
        or raw_commit.get("schemaVersion")
        != "wisdom-weasel.room-commit.v3"
    ):
        return False
    continuation = raw_commit.get("continuation")
    if not isinstance(continuation, Mapping):
        return False
    participant_id = str(
        continuation.get("waitingForParticipantId") or ""
    ).strip()
    dispatch_id = str(
        continuation.get("waitingForDispatchId") or ""
    ).strip()
    return bool(
        continuation.get("waitingFor") == "participant"
        and participant_id
        and dispatch_id
        and str(continuation.get("decision") or "").strip()
        == str(row["decision"] or "").strip()
        and participant_id
        == str(payload.get("waitingForParticipantId") or "").strip()
        and dispatch_id
        == str(payload.get("waitingForDispatchId") or "").strip()
    )


def _review_finding_scope_key(value: object) -> tuple[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    criterion_id = str(value.get("criterionId") or "").strip()
    if criterion_id:
        return ("criterion", criterion_id)
    invariant_id = str(value.get("invariantId") or "").strip()
    if invariant_id:
        return ("invariant", invariant_id)
    return None


def _criteria(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {str(item).strip() for item in value if str(item or "").strip()}


def _authoritative_receipt_details(
    authoritative: Mapping[str, object],
    additional: Mapping[str, object],
    *,
    scope: str,
) -> dict[str, object]:
    """Merge receipt metadata without allowing reserved fields to drift."""

    extra = dict(additional)
    conflicts = sorted(
        key
        for key, value in authoritative.items()
        if key in extra and extra[key] != value
    )
    if conflicts:
        raise RoomKernelFenceError(
            f"{scope} reserved receipt detail fields cannot be overridden: "
            + ", ".join(conflicts)
        )
    return {**extra, **dict(authoritative)}


def _dispatch_idempotency_identity(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Return the immutable Dispatch identity, excluding retry runtime fields."""

    return {
        key: value
        for key, value in dict(payload).items()
        if key not in {"attempt", "state"}
    }

def _unique_text(values: Sequence[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _assert_criteria_within(
    criteria: set[str],
    allowed: set[str],
    *,
    scope: str,
) -> None:
    """A Task may only carry acceptance criteria it inherited.

    Without this fence the application layer is the only thing stopping a
    model-proposed continuation from inventing a criterion ID, or from
    claiming a sibling's criterion and closing the Root early.
    """

    outside = sorted(criteria - allowed)
    if outside:
        shown = ", ".join(outside[:8])
        raise RoomKernelFenceError(
            f"Task acceptance criteria are outside its {scope}: {shown}"
        )


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(material).hexdigest()[:32]}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _non_negative(value: object, field: str) -> int:
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized
