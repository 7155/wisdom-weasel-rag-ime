from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from .agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    KERNEL_RECEIPT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    validate_kernel_contract,
)
from .agent_room_quality_gate import (
    RoomQualityGateError,
    validate_quality_gate_receipt,
)
from .db import apply_database_migrations


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


class RoomKernelFenceError(RuntimeError):
    pass


class RoomKernelStore:
    """Canonical durable Room state machine behind the product command bus.

    Production remains disabled until every release gate passes. Legacy
    Intercom, WorkItem, mention, and wake paths may normalize into this store,
    but they cannot become a second execution authority.
    """

    def __init__(self, db_path: str | Path, *, mode: KernelMode = "shadow", enforce_test_delivery_gate: bool = False) -> None:
        if mode not in {"off", "shadow", "cohort", "test", "kernel_only"}:
            raise ValueError("Room Kernel mode must be off, shadow, cohort, test, or kernel_only")
        self.db_path = Path(db_path)
        self.mode = mode
        self.enforce_test_delivery_gate = bool(enforce_test_delivery_gate)
        if self.enforce_test_delivery_gate and self.mode != "cohort":
            raise ValueError("DeliveryGate enforcement is only valid for the explicit cohort mode")

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            result = apply_database_migrations(conn)
        return result.current_version

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
                # ``task_kind`` predates the typed ReportDispatch semantic and
                # is an unused compatibility projection with a legacy CHECK.
                # ``payload_json.taskKind`` is the contract authority.
                (
                    "work"
                    if str(payload["taskKind"]) == "report"
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
                "SET state='cancelled',updated_at_ms=? WHERE dispatch_id=?",
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
        root = self._root_row(conn, str(payload["rootId"]))
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
        if cost > int(root["budget_remaining"]) - int(root["budget_reserved"]):
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

        existing = conn.execute(
            """SELECT * FROM room_kernel_dispatches
               WHERE root_id = ? AND idempotency_key = ?""",
            (str(payload["rootId"]), str(payload["idempotencyKey"])),
        ).fetchone()
        if existing is not None:
            return _dispatch_payload(existing), False
        task = conn.execute(
            """
            SELECT root_id, state, current_owner_participant_id
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
        # The reservation row is fenced by a foreign key to the dispatch. Keep
        # both writes in the same transaction, but create the dispatch first.
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
        with self._connect() as conn:
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
            """SELECT commit_id,payload_json
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
            payload = json.loads(str(continuation["payload_json"]))
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
        payload = json.loads(str(commit["payload_json"]))
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
            payload=json.loads(str(commit["payload_json"])),
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
            payload = json.loads(str(commit["payload_json"]))
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
                conn.execute("UPDATE room_kernel_runtime_effects SET state='unknown',updated_at_ms=? WHERE dispatch_id=?", (int(now_ms), dispatch_id))
                conn.execute("UPDATE room_kernel_abort_scopes SET state='unknown',updated_at_ms=? WHERE dispatch_id=?", (int(now_ms), dispatch_id))
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
            row = conn.execute("""SELECT * FROM room_kernel_cancel_outbox
                WHERE ((state IN ('pending','retry_wait') AND available_at_ms<=?) OR (state='leased' AND lease_until_ms<=?))
                ORDER BY created_at_ms,cancel_id LIMIT 1""", (int(now_ms), int(now_ms))).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE room_kernel_cancel_outbox SET state='leased',attempt_count=attempt_count+1,lease_until_ms=? WHERE cancel_id=?", (int(now_ms)+max(1,int(ttl_ms)), row["cancel_id"]))
            return {"cancelId": str(row["cancel_id"]), "rootId": str(row["root_id"]), "dispatchId": str(row["dispatch_id"]), "sessionId": str(row["session_id"]), "generation": int(row["generation"])}

    def complete_cancel(self, cancel_id: str, runtime_receipt: Mapping[str, object], *, now_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            row = conn.execute("SELECT * FROM room_kernel_cancel_outbox WHERE cancel_id=? AND state='leased'", (cancel_id,)).fetchone()
            if row is None:
                raise RoomKernelFenceError("cancel lease is missing or stale")
            if (runtime_receipt.get("schemaVersion") != "wisdom-weasel.room-runtime-receipt.v1"
                or runtime_receipt.get("receiptKind") != "cancel_applied"
                or runtime_receipt.get("status") not in {"applied", "cancelled"}
                or runtime_receipt.get("rootId") != row["root_id"]
                or runtime_receipt.get("sessionId") != row["session_id"]
                or int(runtime_receipt.get("generation", -1)) != int(row["generation"])):
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
                if any(proof["state"] == "unknown" for proof in typed_surfaces.values()):
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
            conn.execute("UPDATE room_kernel_runtime_effects SET state='cancelled',runtime_receipt_json=?,updated_at_ms=? WHERE dispatch_id=?", (_json(runtime_receipt), int(now_ms), row["dispatch_id"]))
            conn.execute("UPDATE room_kernel_abort_scopes SET state='cancelled',cancel_receipt_json=?,updated_at_ms=? WHERE dispatch_id=?", (_json(runtime_receipt), int(now_ms), row["dispatch_id"]))
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
                       WHERE dispatch_id=? AND state!='cancelled'""",
                    (int(now_ms), dispatch_id),
                )
                conn.execute(
                    """UPDATE room_kernel_abort_scopes
                       SET state='unknown',updated_at_ms=?
                       WHERE dispatch_id=? AND state!='cancelled'""",
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
        cancel_id = _stable_id("room-cancel", root_id, dispatch_id, str(generation))
        conn.execute("""INSERT OR IGNORE INTO room_kernel_cancel_outbox(
            cancel_id,root_id,dispatch_id,session_id,generation,terminalize_root,state,available_at_ms,created_at_ms)
            VALUES (?,?,?,?,?,?,'pending',?,?)""", (
                cancel_id, root_id, dispatch_id, session_id, int(generation),
                int(terminalize_root), int(now_ms), int(now_ms),
            ))
        conn.execute(
            "UPDATE room_kernel_abort_scopes SET state='cancelling',updated_at_ms=? WHERE dispatch_id=? AND state!='cancelled'",
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
        root = self._root_row(conn, root_id)
        receipt = self._receipt(conn, root_id=root_id, command_id=None, receipt_kind="terminal", status="applied",
            generation=int(root["generation"]), details={"terminalState": cancellation_outcome, "quiescent": True}, now_ms=now_ms)
        conn.execute("UPDATE room_kernel_roots SET state='cancelled',terminal_receipt_id=?,updated_at_ms=? WHERE root_id=?", (receipt["receiptId"], int(now_ms), root_id))
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
                or int(runtime_receipt.get("generation", -1)) != generation
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
                """SELECT d.dispatch_id, d.root_id, d.target_session_id, d.generation
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
            existing = conn.execute("SELECT commit_id FROM room_kernel_commits WHERE dispatch_id = ?", (payload["dispatchId"],)).fetchone()
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
                    if decision == "complete":
                        if unresolved_blocking:
                            raise RoomKernelFenceError(
                                "Reviewer cannot accept with an unresolved "
                                "Blocking Finding"
                            )
                        review_state = (
                            "accepted_with_notes"
                            if unresolved_advisory
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
                },
                now_ms=now_ms,
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
            not in {"running", "waiting"}
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
            payload = json.loads(str(continuation["payload_json"]))
            if payload.get("resumeDispatchId"):
                continue
            if (
                str(continuation["decision"]) == "wait"
                and continuation["child_dispatch_id"] is not None
            ):
                # Compatibility with waits resumed before resumeDispatchId was
                # persisted in the continuation payload.
                continue
            dependency_id = str(
                payload.get("waitingForDispatchId") or ""
            ).strip()
            if (
                payload.get("waitingFor") != "participant"
                or not dependency_id
            ):
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
                break
            if str(dependency["state"]) != "committed":
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
                break
            if str(dependency_task["state"]) != "completed":
                # A public intermediate result (for example, Reviewer findings
                # handed back for revision) does not settle the participant
                # wait. Resume only after that child Task reaches its accepted
                # terminal state.
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
                break
            resumed_task_payload: dict[str, object] | None = None
            task_payload = json.loads(str(task_row["payload_json"]))
            if task_payload.get("taskKind") == "review":
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
                    break
                dependency_commit = json.loads(
                    str(dependency_commit_row["payload_json"])
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
                "triggerId": continuation_id,
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
            try:
                child, _ = self._enqueue_dispatch(
                    conn,
                    resume_dispatch,
                    shadow_only=self.mode
                    not in {"cohort", "test", "kernel_only"},
                    now_ms=now_ms,
                )
            except RoomKernelFenceError as exc:
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
                break
            payload["resumeDispatchId"] = str(child["dispatchId"])
            if str(continuation["decision"]) == "wait":
                conn.execute(
                    """UPDATE room_kernel_continuations
                       SET child_dispatch_id=?,payload_json=?
                       WHERE continuation_id=? AND child_dispatch_id IS NULL""",
                    (
                        child["dispatchId"],
                        _json(payload),
                        continuation_id,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE room_kernel_continuations
                       SET payload_json=? WHERE continuation_id=?""",
                    (_json(payload), continuation_id),
                )
            if resumed_task_payload is not None:
                conn.execute(
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
                conn.execute(
                    """UPDATE room_kernel_tasks
                       SET state='active',updated_at_ms=?
                       WHERE task_id=? AND state='waiting'""",
                    (int(now_ms), continuation["task_id"]),
                )
            conn.execute(
                """UPDATE room_kernel_roots
                   SET state='running',updated_at_ms=?
                   WHERE root_id=? AND state IN ('running','waiting')""",
                (int(now_ms), root_id),
            )
            resumed.append(str(child["dispatchId"]))
        return resumed, blocked

    @staticmethod
    def _block_wait_continuation(
        conn: sqlite3.Connection,
        continuation: sqlite3.Row,
        *,
        reason: str,
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
               SET state='blocked',updated_at_ms=? WHERE root_id=?""",
            (int(now_ms), continuation["root_id"]),
        )
        conn.execute(
            """INSERT OR IGNORE INTO room_kernel_dead_letters(
               dead_letter_id,root_id,dispatch_id,reason_code,
               payload_json,created_at_ms)
               VALUES (?,?,?,'wait_resume_blocked',?,?)""",
            (
                _stable_id(
                    "room-dead-letter",
                    str(continuation["parent_dispatch_id"]),
                    "wait_resume_blocked",
                ),
                continuation["root_id"],
                continuation["parent_dispatch_id"],
                _json(
                    {
                        "continuationId": continuation["continuation_id"],
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
            existing = conn.execute(
                "SELECT command_id FROM room_kernel_commands WHERE room_id = ? AND idempotency_key = ?",
                (command["roomId"], command["idempotencyKey"]),
            ).fetchone()
            if existing is not None:
                receipt = conn.execute(
                    """SELECT payload_json FROM room_kernel_receipts
                       WHERE command_id = ? ORDER BY created_at_ms, receipt_id LIMIT 1""",
                    (existing["command_id"],),
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
                )
            return self._cancel_target(conn, root_id=root_id, target_kind=str(command["targetKind"]), target_id=_required(command.get("targetId"), "targetId"), command_id=str(command["commandId"]), now_ms=int(command["createdAtMs"]))

    def _retry_blocked_root(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        command_id: str,
        now_ms: int,
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
        limits = conn.execute(
            """SELECT retry_limit,retry_used,deadline_at_ms
               FROM room_kernel_root_limits WHERE root_id=?""",
            (root_id,),
        ).fetchone()
        if limits is None:
            raise RoomKernelFenceError("Root resource limits are missing")
        if int(now_ms) >= int(limits["deadline_at_ms"]):
            raise RoomKernelFenceError("Root wall-clock deadline exceeded")
        if int(limits["retry_used"]) + len(selected) > int(limits["retry_limit"]):
            raise RoomKernelFenceError("Root retry limit exhausted")

        conn.execute(
            "UPDATE room_kernel_roots SET state='running',updated_at_ms=? WHERE root_id=?",
            (int(now_ms), root_id),
        )
        retried_dispatch_ids: list[str] = []
        for failed in selected:
            task_id = str(failed["task_id"])
            conn.execute(
                "UPDATE room_kernel_tasks SET state='active',updated_at_ms=? WHERE task_id=?",
                (int(now_ms), task_id),
            )
            payload = json.loads(str(failed["payload_json"]))
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
                    "attempt": int(payload.get("attempt") or 0) + 1,
                    "capabilityEpoch": int(payload.get("capabilityEpoch") or 0) + 1,
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
        conn.execute(
            """UPDATE room_kernel_root_limits
               SET retry_used=retry_used+?,updated_at_ms=? WHERE root_id=?""",
            (len(retried_dispatch_ids), int(now_ms), root_id),
        )
        return self._receipt(
            conn,
            root_id=root_id,
            command_id=command_id,
            receipt_kind="root_retried",
            status="applied",
            generation=int(root["generation"]),
            details={
                "retriedDispatchIds": retried_dispatch_ids,
                "retriedTaskIds": sorted(task_ids),
            },
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
            conn.execute("UPDATE room_kernel_tasks SET state = 'cancelled', updated_at_ms = ? WHERE root_id = ? AND task_id = ?", (int(now_ms), root_id, target_id))
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
                "UPDATE room_kernel_abort_scopes SET state='cancelled',updated_at_ms=? WHERE dispatch_id=?",
                (int(now_ms), dispatch_id),
            )
            self._settle_dispatch_limits(
                conn, dispatch_id, usage=None, consumed=False, now_ms=now_ms
            )
        return self._receipt(conn, root_id=root_id, command_id=command_id, receipt_kind="target_cancelled", status="applied" if count else "noop", generation=int(root["generation"]), details={"targetKind": target_kind, "targetId": target_id, "cancelledDispatches": count, "cancelIntents": len(targets)}, now_ms=now_ms)

    def _panic(self, conn: sqlite3.Connection, *, room_id: str, command_id: str | None, now_ms: int) -> dict[str, object]:
        roots = [str(row[0]) for row in conn.execute("SELECT root_id FROM room_kernel_roots WHERE room_id = ? AND state NOT IN ('completed','cancelled','failed')", (room_id,))]
        cancelled = 0
        unknown = 0
        for root_id in roots:
            receipt = self._cancel_root(conn, root_id, command_id=command_id, now_ms=now_ms, receipt_kind="panic")
            cancelled += int(receipt["details"]["cancelledDispatches"])
            unknown += int(receipt["details"]["unknownDispatches"])
        return self._receipt(conn, root_id=None, command_id=command_id, receipt_kind="panic", status="applied" if roots else "noop", generation=0, details={"roomId": room_id, "rootCount": len(roots), "cancelledDispatches": cancelled, "unknownDispatches": unknown}, now_ms=now_ms)

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
                "UPDATE room_kernel_abort_scopes SET state='cancelled',updated_at_ms=? WHERE dispatch_id=?",
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
            if (
                policy == "isolated_writable"
                and workspace_lifecycle != "abandoned"
                and (
                integration_state != "applied" or not integration_ref
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
                if str(dispatch["intent_kind"]) == "review"
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
                            commit_not_after_ms=(
                                int(payload.get("reviewEvidenceNotBeforeMs") or 0)
                                or None
                            ),
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
                        decoded_commit = json.loads(
                            str(commit_row["payload_json"])
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

        return {
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
        """Bind report readiness to the defined worker lane and real deliveries."""

        definition = self.definition_fence(root_id=root_id, conn=conn)
        if definition is None:
            # Compatibility roots created directly through the typed Kernel API
            # predate room_define. Authoritative intake always has this fence.
            return {
                "definitionRequired": False,
                "lanePlanDispatchIds": [],
                "workerDeliveryDispatchIds": [],
                "fences": [],
            }
        planned = definition.get("plannedExecuteDispatch")
        execution_dispatch_id = str(
            definition.get("executionDispatchId")
            or (
                planned.get("dispatchId")
                if isinstance(planned, Mapping)
                else ""
            )
            or ""
        )
        implementation_id = str(
            definition.get("implementationParticipantId") or ""
        ).strip()
        rows = conn.execute(
            """SELECT d.*,t.parent_task_id,t.state AS task_state
               FROM room_kernel_dispatches d
               JOIN room_kernel_tasks t ON t.task_id=d.task_id
               WHERE d.root_id=? AND t.parent_task_id IS NOT NULL
                 AND d.intent_kind IN ('execute','revise')
               ORDER BY d.created_at_ms,d.dispatch_id""",
            (root_id,),
        ).fetchall()
        lane_ids: list[str] = []
        delivered_ids: list[str] = []
        fences: list[dict[str, object]] = []
        required_lane_delivered = False
        for row in rows:
            dispatch_id = str(row["dispatch_id"])
            lane_ids.append(dispatch_id)
            is_public = (
                str(row["state"]) == "committed"
                and self._dispatch_result_is_public(conn, dispatch_id)
            )
            if is_public and str(row["task_state"]) == "completed":
                delivered_ids.append(dispatch_id)
            else:
                fences.append(
                    {
                        "reason": "worker_delivery_missing",
                        "dispatchId": dispatch_id,
                        "dispatchState": str(row["state"]),
                        "taskState": str(row["task_state"]),
                    }
                )
            if (
                implementation_id
                and str(row["intent_kind"]) == "execute"
                and str(row["target_participant_id"]) == implementation_id
                and (
                    not execution_dispatch_id
                    or str(row["parent_dispatch_id"]) == execution_dispatch_id
                )
                and is_public
                and str(row["task_state"]) == "completed"
            ):
                required_lane_delivered = True
        if not implementation_id or not execution_dispatch_id:
            fences.append({"reason": "defined_worker_lane_missing"})
        elif not required_lane_delivered:
            fences.append(
                {
                    "reason": "defined_worker_delivery_missing",
                    "implementationParticipantId": implementation_id,
                }
            )
        return {
            "definitionRequired": True,
            "lanePlanDispatchIds": lane_ids[:64],
            "workerDeliveryDispatchIds": delivered_ids[:64],
            "fences": fences[:64],
        }

    def _report_readiness_locked(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object]:
        root = self._root_row(conn, root_id)
        existing = self._report_dispatch_locked(conn, root_id=root_id)
        if existing is not None:
            return {"ready": True, "existing": existing}
        active = int(
            conn.execute(
                f"SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id=? "
                f"AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})",
                (root_id, *_ACTIVE_DISPATCH_STATES),
            ).fetchone()[0]
        )
        unknown = int(
            conn.execute(
                "SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id=? "
                "AND state IN ('unknown','dead_letter','failed')",
                (root_id,),
            ).fetchone()[0]
        )
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
        open_tasks = int(
            conn.execute(
                f"SELECT COUNT(*) FROM room_kernel_tasks WHERE root_id=? "
                f"AND state NOT IN ({','.join('?' for _ in _TERMINAL_TASK_STATES)})",
                (root_id, *_TERMINAL_TASK_STATES),
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
        if str(root["state"]) not in {"running", "waiting"}:
            reasons.append("root_not_reportable")
        if active or unknown or open_outbox or active_leases or open_tasks:
            reasons.append("root_not_quiescent")
        if governance["reviewFences"]:
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
            report_task_id = _stable_id(
                "room-report-task",
                root_id,
                str(root["generation"]),
            )
            report_dispatch_id = _stable_id(
                "room-report-dispatch",
                root_id,
                str(root["generation"]),
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
                "triggerId": _stable_id("room-report-trigger", root_id),
                "intentKind": "close",
                "idempotencyKey": _stable_id("room-report", root_id),
                "attempt": 0,
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
            unknown = int(conn.execute("SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id = ? AND state IN ('unknown','dead_letter')", (root_id,)).fetchone()[0])
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
            review_fences = governance["reviewFences"]
            unresolved_findings = governance["unresolvedBlockingFindings"]
            evidence_mismatches = governance["reviewEvidenceMismatches"]
            pending_integrations = governance["pendingIntegrations"]
            if (
                review_fences
                or unresolved_findings
                or evidence_mismatches
                or pending_integrations
            ):
                if review_fences:
                    reason = str(review_fences[0].get("reason"))
                elif unresolved_findings:
                    reason = "review_blocking_findings"
                elif evidence_mismatches:
                    reason = str(evidence_mismatches[0].get("reason"))
                else:
                    reason = "workspace_integration_pending"
                return self._receipt(
                    conn,
                    root_id=root_id,
                    command_id=None,
                    receipt_kind="rejected",
                    status="rejected",
                    generation=int(root["generation"]),
                    details={
                        "reason": reason,
                        "activeDispatches": active,
                        "unknownDispatches": unknown,
                        "openOutbox": open_outbox,
                        "activeLeases": active_leases,
                        "openTasks": open_tasks,
                        "missingAcceptanceCriteria": missing,
                        "governance": governance,
                    },
                    now_ms=now_ms,
                )
            if active or unknown or open_outbox or active_leases or open_tasks or missing:
                return self._receipt(conn, root_id=root_id, command_id=None, receipt_kind="rejected", status="rejected", generation=int(root["generation"]), details={"reason": "root_not_quiescent", "activeDispatches": active, "unknownDispatches": unknown, "openOutbox": open_outbox, "activeLeases": active_leases, "openTasks": open_tasks, "missingAcceptanceCriteria": missing}, now_ms=now_ms)
            # A Root without acceptance criteria cannot be delivered by vacuous
            # truth, and a covered criterion is only real when a durable Commit
            # carries a passing quality gate item with at least one evidence
            # ref. `covered_criteria_json` is bookkeeping; the Commits are the
            # authority, so terminal transition re-derives them here.
            proven = self._acceptance_evidence(conn, root_id, expected)
            unproven = sorted(expected - set(proven))
            if not expected or unproven:
                return self._receipt(
                    conn, root_id=root_id, command_id=None, receipt_kind="rejected",
                    status="rejected", generation=int(root["generation"]),
                    details={
                        "reason": "acceptance_evidence_missing",
                        "acceptanceCriteria": sorted(expected),
                        "unprovenAcceptanceCriteria": unproven,
                    },
                    now_ms=now_ms,
                )
            # Reporting is the last gate. Preserve the more actionable
            # governance, quiescence, and evidence failures above instead of
            # hiding them behind a missing Reporter terminal receipt.
            if kernel_owns_room_execution(self.mode) and (
                report is None or report.get("readyForTerminal") is not True
            ):
                return self._receipt(
                    conn,
                    root_id=root_id,
                    command_id=None,
                    receipt_kind="rejected",
                    status="rejected",
                    generation=int(root["generation"]),
                    details={
                        "reason": "reporter_terminal_missing",
                        "reportDispatchId": (
                            report["dispatch"]["dispatchId"]
                            if isinstance(report, Mapping)
                            else None
                        ),
                    },
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
            details={
                "purpose": "intake_phase",
                "phase": phase,
                "clarificationOccurred": bool(clarification_occurred),
                "source": _required(source, "intake phase source"),
                **dict(details),
            },
            now_ms=now_ms,
        )

    def intake_state(
        self,
        root_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        def read(active: sqlite3.Connection) -> dict[str, object]:
            rows = active.execute(
                """SELECT payload_json FROM room_kernel_receipts
                   WHERE root_id=? AND receipt_kind='accepted'
                   ORDER BY created_at_ms DESC,rowid DESC""",
                (_required(root_id, "root_id"),),
            ).fetchall()
            for row in rows:
                payload = json.loads(str(row["payload_json"]))
                details = (
                    payload.get("details")
                    if isinstance(payload, Mapping)
                    else None
                )
                if (
                    isinstance(details, Mapping)
                    and details.get("purpose") == "intake_phase"
                ):
                    return {"receipt": payload, **dict(details)}
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
            payload = json.loads(str(row["payload_json"]))
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

    def record_workspace_lifecycle(
        self,
        task_id: str,
        *,
        operation: str,
        workspace_result: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Project a receipted retain/abandon transition onto one Task."""

        if operation not in {"retain", "abandon"}:
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
            if operation == "abandon" and str(root["state"]) == "blocked":
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
            ):
                raise RoomKernelFenceError(
                    "workspace retry Dispatch does not match its parent fences"
                )
            target_participant_id = str(
                retry_dispatch.get("targetParticipantId") or ""
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
            result = dict(workspace_result or {})
            integrated = result.get("integrated") is True
            if (
                task.get("workspaceIntegrationState") == "applied"
                and integrated
            ):
                return task
            if str(row["state"]) != "completed":
                raise RoomKernelFenceError(
                    "workspace integration requires a completed child Task"
                )
            task.update(
                {
                    "workspaceIntegrationState": (
                        "applied"
                        if integrated or not workspace_result
                        else "pending"
                    ),
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
            if result:
                task["workspaceAttentionRequired"] = not integrated or str(
                    result.get("cleanupState") or ""
                ) not in {"cleaned", "missing"}
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
                    "operation": "room_integrate",
                    "taskId": task_id,
                    "integrationRef": integration_ref,
                    "integrated": integrated or not workspace_result,
                    "workspaceLifecycleState": task.get(
                        "workspaceLifecycleState"
                    ),
                    "workspaceCleanupState": task.get(
                        "workspaceCleanupState"
                    ),
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
            return json.loads(str(row["payload_json"]))

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
    def _latest_review_attempt_locked(
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> dict[str, object] | None:
        """Resolve the newest durable attempt for the authoritative review Task.

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
                }
            )
        if not candidates:
            return None
        candidate = max(
            candidates,
            key=lambda value: (
                max(
                    int(value["updatedAtMs"]),
                    (
                        int(value["dispatchRow"]["updated_at_ms"] or 0)
                        if value["dispatchRow"] is not None
                        else 0
                    ),
                    (
                        int(value["dispatchRow"]["created_at_ms"] or 0)
                        if value["dispatchRow"] is not None
                        else 0
                    ),
                ),
                str(value["taskId"]),
            ),
        )
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
                decoded_commit = json.loads(str(commit_row["payload_json"]))
                if not isinstance(decoded_commit, dict):
                    raise RoomKernelFenceError(
                        "review Dispatch Commit payload is corrupt"
                    )
                commit_payload = decoded_commit
                commit_id = str(commit_row["commit_id"])
                if str(dispatch_row["state"]) == "committed":
                    result_public = RoomKernelStore._commit_result_is_public(
                        conn,
                        commit_id,
                        payload=decoded_commit,
                    )
        return {
            "taskId": str(candidate["taskId"]),
            "taskState": str(candidate["taskState"]),
            "payload": dict(candidate["payload"]),
            "updatedAtMs": int(candidate["updatedAtMs"]),
            "dispatch": dispatch_payload,
            "commit": commit_payload,
            "commitId": commit_id,
            "resultPublic": result_public,
        }

    def latest_review_attempt(
        self,
        root_id: str,
    ) -> dict[str, object] | None:
        """Return the newest review/resume Dispatch and its exact Commit."""

        with self._connect() as conn:
            return self._latest_review_attempt_locked(
                conn,
                root_id=root_id,
            )

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
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            raise RoomKernelFenceError("Room Task Commit payload is corrupt")
        return payload

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
        rows = conn.execute(
            "SELECT payload_json FROM room_kernel_commits WHERE root_id = ?",
            (root_id,),
        ).fetchall()
        for row in rows:
            gate = json.loads(str(row["payload_json"])).get("qualityGateReceipt")
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
            rows = conn.execute(
                """SELECT payload_json
                   FROM room_kernel_commits
                   WHERE root_id = ?
                   ORDER BY created_at_ms, commit_id""",
                (root_id,),
            ).fetchall()
        collected: dict[str, list[str]] = {}
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
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
        payload = json.loads(str(row["payload_json"]))
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
            rows = conn.execute(
                """
                SELECT c.*, r.generation AS root_generation,
                       d.target_participant_id, d.target_session_id,
                       d.generation AS dispatch_generation,
                       d.hop_count AS parent_hop_count,
                       d.depth AS parent_depth
                FROM room_kernel_continuations c
                JOIN room_kernel_roots r ON r.root_id = c.root_id
                JOIN room_kernel_dispatches d ON d.dispatch_id = c.parent_dispatch_id
                WHERE r.room_id = ? AND r.state = 'waiting'
                  AND c.decision = 'wait' AND c.state = 'applied'
                ORDER BY c.created_at_ms DESC, c.continuation_id DESC
                """,
                (_required(room_id, "room_id"),),
            ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if (
                isinstance(payload, Mapping)
                and payload.get("waitingFor") == "user"
            ):
                candidate_root_id = str(row["root_id"])
                candidate_question_post_id = _stable_id(
                    "room-post",
                    str(row["commit_id"]),
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
    ) -> dict[str, object]:
        """Atomically consume a user wait and enqueue its one resume Dispatch."""

        validate_kernel_contract("dispatchEnvelope", dispatch_payload)
        with self._connect(immediate=True) as conn:
            continuation = conn.execute(
                "SELECT * FROM room_kernel_continuations "
                "WHERE continuation_id = ?",
                (_required(continuation_id, "continuation_id"),),
            ).fetchone()
            if continuation is None:
                raise RoomKernelFenceError("user wait continuation is missing")
            if str(continuation["state"]) != "applied":
                raise RoomKernelFenceError("user wait continuation was already resumed")
            continuation_payload = json.loads(
                str(continuation["payload_json"])
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
            expected_question_post_id = _stable_id(
                "room-post",
                str(continuation["commit_id"]),
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
            existing = conn.execute(
                "SELECT * FROM room_kernel_dispatches "
                "WHERE idempotency_key = ?",
                (str(dispatch_payload["idempotencyKey"]),),
            ).fetchone()
            if existing is None:
                resumed, _ = self._enqueue_dispatch(
                    conn,
                    dispatch_payload,
                    shadow_only=self.mode
                    not in {"cohort", "test", "kernel_only"},
                    now_ms=now_ms,
                )
            else:
                resumed = _dispatch_payload(existing)
            updated_payload = dict(continuation_payload)
            updated_payload.update(
                {
                    "answerPostId": _required(answer_post_id, "answer_post_id"),
                    "answerAnchorId": _required(
                        answer_anchor_id,
                        "answer_anchor_id",
                    ),
                    "resumeDispatchId": str(resumed["dispatchId"]),
                }
            )
            conn.execute(
                "UPDATE room_kernel_continuations SET state='blocked', "
                "payload_json=? WHERE continuation_id=?",
                (
                    _json(updated_payload),
                    continuation_id,
                ),
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
                    "answerPostId": answer_post_id,
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
                    "answerPostId": answer_post_id,
                    "answerAnchorId": answer_anchor_id,
                },
                now_ms=now_ms,
            )
            return {
                "receipt": receipt,
                "dispatch": dict(resumed),
                "continuationId": continuation_id,
            }

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
        _assert_criteria_within(
            set(criteria),
            set(criteria),
            scope="definition Root",
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
        if bool(updated_root_payload.get("independentReviewRequired")) != bool(
            independent_review_required
        ):
            raise RoomKernelFenceError(
                "room_define cannot infer or mutate independent review policy"
            )
        validate_kernel_contract("rootExecution", updated_root_payload)
        intake = self.intake_state(str(root["root_id"]), conn=conn)
        clarification_occurred = bool(intake["clarificationOccurred"])
        execution_authorized = not clarification_occurred
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
                details={
                    "executionDispatchId": str(
                        execute_dispatch["dispatchId"]
                    )
                },
                now_ms=now_ms,
            )
        else:
            self._record_intake_phase_locked(
                conn,
                root_id=str(root["root_id"]),
                phase="awaiting_start",
                clarification_occurred=True,
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
            details={
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
                **dict(details),
            },
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

    def start_defined_execution(
        self,
        *,
        root_id: str,
        client_action_id: str,
        user_post_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Consume the one typed post-clarification start action."""

        root_id = _required(root_id, "root_id")
        client_action_id = _required(client_action_id, "client_action_id")
        user_post_id = _required(user_post_id, "user_post_id")
        with self._connect(immediate=True) as conn:
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
                    dispatch_id = _required(
                        details.get("executionDispatchId"),
                        "execution dispatch id",
                    )
                    return {
                        "receipt": receipt,
                        "dispatch": self.dispatch(dispatch_id, conn=conn),
                        "intake": self.intake_state(root_id, conn=conn),
                        "created": False,
                    }
            intake = self.intake_state(root_id, conn=conn)
            if (
                intake.get("phase") != "awaiting_start"
                or intake.get("clarificationOccurred") is not True
                or str(root["state"]) != "waiting"
            ):
                raise RoomKernelFenceError(
                    "typed start is allowed only after a clarified definition"
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
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise RoomKernelFenceError("defined Task is missing")
            task_payload = json.loads(str(task_row["payload_json"]))
            task_payload["state"] = "active"
            validate_kernel_contract("roomTask", task_payload)
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
                else None
            )
            conn.execute(
                """UPDATE room_kernel_tasks
                   SET state='active',payload_json=?,updated_at_ms=?
                   WHERE task_id=?""",
                (_json(task_payload), int(now_ms), task_id),
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='running',updated_at_ms=? "
                "WHERE root_id=?",
                (int(now_ms), root_id),
            )
            self._record_intake_phase_locked(
                conn,
                root_id=root_id,
                phase="execution_ready",
                clarification_occurred=True,
                source="typed_start_action",
                generation=int(root["generation"]),
                details={
                    "clientActionId": client_action_id,
                    "userPostId": user_post_id,
                    "chronologyAfterPostId": chronology_after_post_id,
                },
                now_ms=now_ms,
            )
            dispatch, _ = self._enqueue_dispatch(
                conn,
                planned,
                shadow_only=self.mode not in {
                    "cohort",
                    "test",
                    "kernel_only",
                },
                now_ms=now_ms,
            )
            self._record_intake_phase_locked(
                conn,
                root_id=root_id,
                phase="executing",
                clarification_occurred=True,
                source="execute_dispatch_enqueued",
                generation=int(root["generation"]),
                details={
                    "clientActionId": client_action_id,
                    "userPostId": user_post_id,
                    "chronologyAfterPostId": chronology_after_post_id,
                    "executionDispatchId": str(dispatch["dispatchId"]),
                },
                now_ms=now_ms,
            )
            receipt = self._receipt(
                conn,
                root_id=root_id,
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=int(root["generation"]),
                details={
                    "purpose": "typed_start_action",
                    "clientActionId": client_action_id,
                    "userPostId": user_post_id,
                    "chronologyAfterPostId": chronology_after_post_id,
                    "executionDispatchId": str(dispatch["dispatchId"]),
                },
                now_ms=now_ms,
            )
            return {
                "receipt": receipt,
                "dispatch": dispatch,
                "intake": self.intake_state(root_id, conn=conn),
                "created": True,
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
                and (
                    not bool(had_tool_activity)
                    or normalized_reason == "room_commit_missing"
                )
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

    @staticmethod
    def _block_failed_dispatch(
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
        conn.execute(
            """UPDATE room_kernel_tasks
               SET state='blocked',updated_at_ms=? WHERE task_id=?""",
            (int(now_ms), dispatch["task_id"]),
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
                != ("running" if is_leaf else "committed")
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


def _dispatch_dependency_ids(payload: Mapping[str, object]) -> list[str]:
    raw = payload.get("dependsOnDispatchIds")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RoomKernelFenceError(
            "Dispatch dependsOnDispatchIds must be an array"
        )
    values = [str(value).strip() for value in raw]
    if any(not value for value in values) or len(values) != len(set(values)):
        raise RoomKernelFenceError(
            "Dispatch dependsOnDispatchIds contains an invalid identity"
        )
    return values


def _payload_depends_on(
    payload: Mapping[str, object],
    target_dispatch_id: str,
    *,
    dispatches_by_id: Mapping[str, Mapping[str, object]],
    visited: set[str] | None = None,
) -> bool:
    seen = set(visited or ())
    dispatch_id = str(payload.get("dispatchId") or "")
    if dispatch_id in seen:
        return False
    seen.add(dispatch_id)
    for dependency_id in _dispatch_dependency_ids(payload):
        if dependency_id == target_dispatch_id:
            return True
        dependency = dispatches_by_id.get(dependency_id)
        if dependency is not None and _payload_depends_on(
            dependency,
            target_dispatch_id,
            dispatches_by_id=dispatches_by_id,
            visited=seen,
        ):
            return True
    return False


def _dispatch_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = json.loads(str(row["payload_json"]))
    payload["state"] = str(row["state"])
    return payload


def _criteria(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {str(item).strip() for item in value if str(item or "").strip()}

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
