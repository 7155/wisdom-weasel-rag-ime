from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from .agent_room_kernel_contracts import (
    KERNEL_COMMAND_SCHEMA_VERSION,
    KERNEL_RECEIPT_SCHEMA_VERSION,
    validate_kernel_contract,
)
from .agent_room_quality_gate import (
    RoomQualityGateError,
    validate_quality_gate_receipt,
)
from .db import apply_database_migrations


KernelMode = Literal["off", "shadow", "cohort", "test", "kernel_only"]
_ACTIVE_DISPATCH_STATES = ("pending", "leased", "running", "retry_wait", "timer_wait")
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
                    root_id, room_id, generation, state, owner,
                    requirement_anchor_ref, budget_remaining, budget_reserved, max_hops,
                    max_depth, acceptance_criteria_json, covered_criteria_json,
                    terminal_receipt_id, payload_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, '[]', NULL, ?, ?, ?)
                """,
                (
                    root_id,
                    str(payload["roomId"]),
                    int(payload["generation"]),
                    str(payload["state"]),
                    str(payload["owner"]),
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
                task_id, root_id, parent_task_id, state, payload_json, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload["taskId"]),
                str(payload["rootId"]),
                parent_task_id,
                str(payload["state"]),
                encoded,
                int(now_ms),
            ),
        )
        return dict(payload), True

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
                if (
                    existing_root is None
                    or existing_task is None
                    or json.loads(str(existing_root["payload_json"])) != dict(root_payload)
                    or json.loads(str(existing_task["payload_json"])) != dict(task_payload)
                    or int(existing_root["budget_remaining"]) != budget
                    or int(existing_root["budget_reserved"]) != 0
                    or int(existing_root["max_hops"]) != max_hops
                    or int(existing_root["max_depth"]) != max_depth
                    or json.loads(str(existing_root["acceptance_criteria_json"]))
                    != sorted(set(acceptance_criteria))
                ):
                    raise RoomKernelFenceError("Root/Task creation identity conflicts with durable state")
                return {"root": self.root(root_id), "task": self.task(task_id)}
            conn.execute(
                """
                INSERT INTO room_kernel_roots(
                    root_id, room_id, generation, state, owner,
                    requirement_anchor_ref, budget_remaining, budget_reserved, max_hops,
                    max_depth, acceptance_criteria_json, covered_criteria_json,
                    terminal_receipt_id, payload_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, '[]', NULL, ?, ?, ?)
                """,
                (
                    root_id, str(root_payload["roomId"]), int(root_payload["generation"]),
                    str(root_payload["state"]), str(root_payload["owner"]),
                    str(root_payload["requirementAnchorRef"]), budget, max_hops, max_depth,
                    _json(sorted(set(acceptance_criteria))), _json(root_payload),
                    int(now_ms), int(now_ms),
                ),
            )
            conn.execute(
                """
                INSERT INTO room_kernel_tasks(
                    task_id, root_id, parent_task_id, state, payload_json, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, root_id, task_payload.get("parentTaskId"),
                    str(task_payload["state"]), _json(task_payload), int(now_ms),
                ),
            )
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
        session_ids = [identity[3] for identity in identities]
        if len(session_ids) != len(set(session_ids)):
            raise RoomKernelFenceError("dispatch batch targets one Session more than once")

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
        active_target = conn.execute(
            f"""SELECT dispatch_id FROM room_kernel_dispatches
                WHERE target_session_id = ?
                  AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})
                ORDER BY created_at_ms, dispatch_id
                LIMIT 1""",
            (str(payload["targetSessionId"]), *_ACTIVE_DISPATCH_STATES),
        ).fetchone()
        if active_target is not None:
            raise RoomKernelFenceError(
                "target Session already has an active Dispatch: "
                f"{active_target['dispatch_id']}"
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
            conn, root_id=str(root["root_id"]), dispatch_id=str(payload["dispatchId"]),
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
        return json.loads(str(row["payload_json"])) if row is not None else None

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
            lease_id = _stable_id("room-lease", str(row["dispatch_id"]), str(now_ms))
            token = _stable_id("room-lease-token", lease_id, str(row["generation"]))
            expires = int(now_ms) + max(1, int(ttl_ms))
            conn.execute(
                """INSERT INTO room_kernel_leases(
                   lease_id, root_id, dispatch_id, generation, lease_token,
                   state, expires_at_ms, updated_at_ms
                   ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                (lease_id, row["root_id"], row["dispatch_id"], row["generation"], token, expires, int(now_ms)),
            )
            conn.execute("UPDATE room_kernel_dispatches SET state = 'leased', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), row["dispatch_id"]))
            conn.execute("UPDATE room_kernel_outbox SET state = 'leased', updated_at_ms = ? WHERE outbox_id = ?", (int(now_ms), row["outbox_id"]))
            return {"leaseId": lease_id, "leaseToken": token, "dispatchId": str(row["dispatch_id"]), "generation": int(row["generation"]), "expiresAtMs": expires}

    def _first_ready_outbox(
        self,
        conn: sqlite3.Connection,
        *,
        now_ms: int,
        dispatch_id: str = "",
    ) -> sqlite3.Row | None:
        rows = conn.execute(
            """SELECT o.*, d.state AS dispatch_state, d.target_session_id
               FROM room_kernel_outbox o
               JOIN room_kernel_dispatches d USING(dispatch_id)
               WHERE o.state = 'pending' AND o.shadow_only = 0
                 AND o.available_at_ms <= ? AND d.state = 'pending'
                 AND (? = '' OR o.dispatch_id = ?)
               ORDER BY o.available_at_ms, o.outbox_id""",
            (int(now_ms), dispatch_id, dispatch_id),
        ).fetchall()
        for row in rows:
            if self._dispatch_dependencies_ready(
                conn,
                str(row["dispatch_id"]),
            ):
                return row
        return None

    def _dispatch_dependencies_ready(
        self,
        conn: sqlite3.Connection,
        dispatch_id: str,
    ) -> bool:
        continuation = conn.execute(
            """SELECT commit_id,payload_json
               FROM room_kernel_continuations
               WHERE child_dispatch_id = ?
                 AND decision IN ('dispatch','wait')""",
            (dispatch_id,),
        ).fetchone()
        if continuation is None:
            return True
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
                    *(
                        str(value).strip()
                        for value in raw_dependencies
                    ),
                    *([waiting_for_dispatch] if waiting_for_dispatch else []),
                ]
            )
        )
        if not dependency_ids:
            return True
        if any(not value for value in dependency_ids):
            raise RoomKernelFenceError(
                "Dispatch continuation has an invalid dependency"
            )
        placeholders = ",".join("?" for _ in dependency_ids)
        rows = conn.execute(
            f"""SELECT dispatch_id, state
                FROM room_kernel_dispatches
                WHERE dispatch_id IN ({placeholders})""",
            dependency_ids,
        ).fetchall()
        states = {
            str(row["dispatch_id"]): str(row["state"])
            for row in rows
        }
        if set(states) != set(dependency_ids):
            raise RoomKernelFenceError(
                "Dispatch continuation dependency is missing"
            )
        if any(states[value] != "committed" for value in dependency_ids):
            return False
        return all(
            self._dispatch_result_is_public(conn, dependency_id)
            for dependency_id in dependency_ids
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
            raise RoomKernelFenceError(
                "committed Dispatch has no canonical RoomCommit"
            )
        return RoomKernelStore._commit_result_is_public(
            conn,
            str(commit["commit_id"]),
            payload=json.loads(str(commit["payload_json"])),
        )

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
            return True
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

    def fail_cancel(self, cancel_id: str, reason: str, *, now_ms: int) -> None:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT attempt_count,session_id FROM room_kernel_cancel_outbox WHERE cancel_id=?",
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
            dispatch = self._dispatch_row(conn, str(lease["dispatch_id"]))
            generation = int(lease["generation"])
            if generation != int(root["generation"]) or generation != int(dispatch["generation"]):
                raise RoomKernelFenceError("runtime receipt generation is stale")
            if (
                runtime_receipt.get("schemaVersion")
                != "wisdom-weasel.room-runtime-receipt.v1"
                or runtime_receipt.get("receiptKind") != "dispatch_accepted"
                or runtime_receipt.get("status") != "accepted"
                or runtime_receipt.get("rootId") != lease["root_id"]
                or runtime_receipt.get("dispatchId") != lease["dispatch_id"]
                or int(runtime_receipt.get("generation", -1)) != generation
            ):
                raise RoomKernelFenceError("runtime receipt does not match the leased Dispatch")
            conn.execute(
                """UPDATE room_kernel_runtime_effects SET state='accepted',runtime_receipt_json=?,updated_at_ms=?
                   WHERE dispatch_id=?""",
                (_json(runtime_receipt), int(now_ms), lease["dispatch_id"]),
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

    def record_runtime_dispatch_intent(self, dispatch_id: str, *, now_ms: int) -> None:
        """Persist the cancellable target before crossing the Pi process boundary."""
        with self._connect(immediate=True) as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            conn.execute(
                """INSERT INTO room_kernel_runtime_effects(dispatch_id,root_id,session_id,dispatch_generation,state,updated_at_ms)
                   VALUES (?,?,?,?,'intent',?)
                   ON CONFLICT(dispatch_id) DO UPDATE SET updated_at_ms=excluded.updated_at_ms""",
                (dispatch_id, dispatch["root_id"], dispatch["target_session_id"], dispatch["generation"], int(now_ms)),
            )
            conn.execute(
                """INSERT INTO room_kernel_abort_scopes(
                   dispatch_id,root_id,session_id,generation,state,surfaces_json,updated_at_ms)
                   VALUES (?,?,?,?,'registered',?,?)
                   ON CONFLICT(dispatch_id) DO UPDATE SET
                     state=room_kernel_abort_scopes.state,
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
                """SELECT d.dispatch_id, d.root_id, d.generation, d.state, r.room_id
                   FROM room_kernel_dispatches d
                   JOIN room_kernel_roots r ON r.root_id = d.root_id
                   WHERE d.target_session_id = ?
                     AND d.state IN ('pending','leased','running','retry_wait','timer_wait')
                   ORDER BY d.updated_at_ms DESC, d.dispatch_id DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "roomId": str(row["room_id"]),
                "rootId": str(row["root_id"]),
                "dispatchId": str(row["dispatch_id"]),
                "generation": int(row["generation"]),
                "state": str(row["state"]),
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
                or child_task.get("assigneeParticipantId")
                != child_dispatch.get("targetParticipantId")
            ):
                raise RoomKernelFenceError(
                    "Room collaboration child does not match parent fences"
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
        child_task_payload: Mapping[str, object] | None = None
        child_payload: Mapping[str, object] | None = None
        if action == "dispatch":
            if not isinstance(continuation, Mapping) or continuation.get("decision") != "dispatch":
                raise RoomKernelFenceError("dispatch Commit requires a deterministic continuation")
            child_task = continuation.get("childTask")
            child = continuation.get("childDispatch")
            if not isinstance(child_task, Mapping) or not isinstance(child, Mapping):
                raise RoomKernelFenceError(
                    "dispatch continuation requires childTask and childDispatch"
                )
            validate_kernel_contract("roomTask", child_task)
            validate_kernel_contract("dispatchEnvelope", child)
            child_task_payload = child_task
            child_payload = child
        elif action == "post":
            decision = str(continuation.get("decision") if isinstance(continuation, Mapping) else "wait")
            if decision not in {"dispatch", "wait", "block", "complete"}:
                raise RoomKernelFenceError("post continuation decision is invalid")
            if decision == "dispatch":
                child_task = continuation.get("childTask") if isinstance(continuation, Mapping) else None
                child = continuation.get("childDispatch") if isinstance(continuation, Mapping) else None
                if not isinstance(child_task, Mapping) or not isinstance(child, Mapping):
                    raise RoomKernelFenceError(
                        "post dispatch continuation requires childTask and childDispatch"
                    )
                validate_kernel_contract("roomTask", child_task)
                validate_kernel_contract("dispatchEnvelope", child)
                child_task_payload = child_task
                child_payload = child
        elif isinstance(continuation, Mapping) and continuation.get("decision") != action:
            raise RoomKernelFenceError("RoomCommit continuation contradicts its action")
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
            if child_payload is not None and (
                child_task_payload is None
                or child_task_payload.get("rootId") != root["root_id"]
                or child_task_payload.get("parentTaskId") != dispatch["task_id"]
                or child_payload.get("rootId") != root["root_id"]
                or child_payload.get("taskId") != child_task_payload.get("taskId")
                or child_payload.get("parentDispatchId") != dispatch["dispatch_id"]
                or int(child_payload.get("generation", -1)) != generation
                or child_task_payload.get("assigneeParticipantId")
                != child_payload.get("targetParticipantId")
            ):
                raise RoomKernelFenceError("continuation child does not match parent fences")
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
                "dispatch": "completed",
            }[decision]
            conn.execute(
                "UPDATE room_kernel_tasks SET state=?,updated_at_ms=? WHERE task_id=?",
                (next_state, int(now_ms), dispatch["task_id"]),
            )
            root_state = {"wait": "waiting", "post": "waiting", "block": "blocked"}.get(decision, "running")
            conn.execute(
                "UPDATE room_kernel_roots SET state=?,updated_at_ms=? WHERE root_id=?",
                (root_state, int(now_ms), root["root_id"]),
            )
            child_dispatch = None
            if child_payload is not None:
                assert child_task_payload is not None
                self._insert_task(conn, child_task_payload, now_ms=now_ms)
                child_dispatch, _ = self._enqueue_dispatch(
                    conn,
                    child_payload,
                    shadow_only=self.mode not in {"cohort", "test", "kernel_only"},
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
               WHERE root_id=? AND decision='wait' AND state='applied'
                 AND child_dispatch_id IS NULL
               ORDER BY created_at_ms,continuation_id""",
            (root_id,),
        ).fetchall()
        resumed: list[str] = []
        blocked: list[dict[str, str]] = []
        for continuation in rows:
            payload = json.loads(str(continuation["payload_json"]))
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
            task_row = conn.execute(
                """SELECT state FROM room_kernel_tasks
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
            capability_epoch = (
                parent_epoch if active_same_wave else parent_epoch + 1
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
            conn.execute(
                """UPDATE room_kernel_continuations
                   SET child_dispatch_id=?
                   WHERE continuation_id=? AND child_dispatch_id IS NULL""",
                (child["dispatchId"], continuation_id),
            )
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
        """Apply typed cancellation controls through the single Kernel command path."""

        validate_kernel_contract("kernelCommand", command)
        kind = str(command["commandKind"])
        if kind not in {"cancel_target", "cancel_root", "panic"}:
            raise ValueError("control command must be cancel_target, cancel_root, or panic")
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
                if kind == "cancel_root" and (
                    command.get("targetKind") != "root" or command.get("targetId") != root_id
                ):
                    raise RoomKernelFenceError("cancel_root target does not match Root")
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
            return self._cancel_target(conn, root_id=root_id, target_kind=str(command["targetKind"]), target_id=_required(command.get("targetId"), "targetId"), command_id=str(command["commandId"]), now_ms=int(command["createdAtMs"]))

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
            active = int(conn.execute(f"SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id = ? AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})", (root_id, *_ACTIVE_DISPATCH_STATES)).fetchone()[0])
            unknown = int(conn.execute("SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id = ? AND state IN ('unknown','dead_letter')", (root_id,)).fetchone()[0])
            open_outbox = int(conn.execute("SELECT COUNT(*) FROM room_kernel_outbox WHERE root_id = ? AND state IN ('pending','leased','running','retry_wait','timer_wait')", (root_id,)).fetchone()[0])
            active_leases = int(conn.execute("SELECT COUNT(*) FROM room_kernel_leases WHERE root_id = ? AND state = 'active'", (root_id,)).fetchone()[0])
            open_tasks = int(conn.execute(f"SELECT COUNT(*) FROM room_kernel_tasks WHERE root_id = ? AND state NOT IN ({','.join('?' for _ in _TERMINAL_TASK_STATES)})", (root_id, *_TERMINAL_TASK_STATES)).fetchone()[0])
            expected = set(json.loads(str(root["acceptance_criteria_json"])))
            covered = set(json.loads(str(root["covered_criteria_json"])))
            missing = sorted(expected - covered)
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
                conn, root_id=root_id, command_id=None, receipt_kind="terminal",
                status="applied", generation=int(root["generation"]),
                details={
                    "quiescent": True,
                    "acceptanceSatisfied": True,
                    "acceptanceEvidenceRefCounts": {
                        criterion_id: len(refs)
                        for criterion_id, refs in sorted(proven.items())
                    },
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

    def root(self, root_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = self._root_row(conn, root_id)
            payload = json.loads(str(row["payload_json"]))
            payload.update({
                "generation": int(row["generation"]),
                "state": str(row["state"]),
                "budgetRemaining": int(row["budget_remaining"]),
                "budgetReserved": int(row["budget_reserved"]),
                "acceptanceCriteria": json.loads(str(row["acceptance_criteria_json"])),
                "coveredCriteria": json.loads(str(row["covered_criteria_json"])),
                "terminalReceiptId": row["terminal_receipt_id"],
            })
            return payload

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

    def task(self, task_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM room_kernel_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            payload = json.loads(str(row["payload_json"]))
            payload["state"] = str(row["state"])
            return payload

    def dispatch(self, dispatch_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, object]:
        if conn is not None:
            return _dispatch_payload(self._dispatch_row(conn, dispatch_id))
        with self._connect() as owned:
            return _dispatch_payload(self._dispatch_row(owned, dispatch_id))

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
                    if (
                        evidence_ref
                        and evidence_ref not in target
                        and len(target) < 64
                    ):
                        target.append(evidence_ref)
        projected: dict[str, list[str]] = {}
        remaining = 32
        for ref_index in range(4):
            for criterion_id in criterion_order:
                refs = collected.get(criterion_id, ())
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
        child_task = (
            payload.get("childTask")
            if isinstance(payload, Mapping)
            else None
        )
        return {
            "continuationId": str(row["continuation_id"]),
            "rootId": str(row["root_id"]),
            "taskId": str(row["task_id"]),
            "parentDispatchId": str(row["parent_dispatch_id"]),
            "childTaskId": (
                child_task.get("taskId")
                if isinstance(child_task, Mapping)
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

    def record_runtime_failure(
        self,
        dispatch_id: str,
        *,
        generation: int,
        source_event_id: str,
        now_ms: int,
        resource_usage: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Close one failed Pi turn without pretending it settled or was cancelled."""

        event_id = _required(source_event_id, "source_event_id")
        with self._connect(immediate=True) as conn:
            dispatch = self._dispatch_row(conn, dispatch_id)
            root = self._root_row(conn, str(dispatch["root_id"]))
            if (
                generation != int(dispatch["generation"])
                or generation != int(root["generation"])
            ):
                raise RoomKernelFenceError(
                    "runtime failure generation is stale"
                )
            existing = conn.execute(
                """SELECT reason_code,payload_json
                   FROM room_kernel_dead_letters
                   WHERE dispatch_id=?""",
                (dispatch_id,),
            ).fetchone()
            if existing is not None:
                payload = json.loads(str(existing["payload_json"]))
                if (
                    str(existing["reason_code"]) == "runtime_turn_failed"
                    and payload.get("sourceEventId") == event_id
                    and isinstance(payload.get("kernelReceipt"), Mapping)
                ):
                    return dict(payload["kernelReceipt"])
                raise RoomKernelFenceError(
                    "Dispatch already has another dead-letter outcome"
                )
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
                        "reasonCode": "runtime_turn_failed",
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
                    "reasonCode": "runtime_turn_failed",
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
                    "reasonCode": "runtime_turn_failed",
                    "sourceEventId": event_id,
                },
            )
            dead_letter_id = _stable_id(
                "room-dead-letter",
                dispatch_id,
                "runtime_turn_failed",
            )
            conn.execute(
                """INSERT INTO room_kernel_dead_letters(
                   dead_letter_id,root_id,dispatch_id,reason_code,
                   payload_json,created_at_ms)
                   VALUES (?,?,?,'runtime_turn_failed',?,?)""",
                (
                    dead_letter_id,
                    root["root_id"],
                    dispatch_id,
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

    def record_uncommitted_settle(
        self,
        dispatch_id: str,
        *,
        generation: int,
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
            if generation != int(dispatch["generation"]) or generation != int(root["generation"]):
                raise RoomKernelFenceError("uncommitted settle generation is stale")
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
            row = conn.execute("SELECT * FROM room_kernel_leases WHERE dispatch_id = ?", (dispatch_id,)).fetchone()
            if row is None:
                raise KeyError(dispatch_id)
            return {"leaseId": str(row["lease_id"]), "rootId": str(row["root_id"]), "dispatchId": dispatch_id, "generation": int(row["generation"]), "leaseToken": str(row["lease_token"]), "state": str(row["state"]), "expiresAtMs": int(row["expires_at_ms"])}

    def receipt(self, receipt_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM room_kernel_receipts WHERE receipt_id = ?", (receipt_id,)).fetchone()
            if row is None:
                raise KeyError(receipt_id)
            return json.loads(str(row["payload_json"]))

    def counts(self, root_id: str) -> dict[str, int]:
        with self._connect() as conn:
            names = {"commands": "room_kernel_commands", "dispatches": "room_kernel_dispatches", "commits": "room_kernel_commits", "outbox": "room_kernel_outbox", "leases": "room_kernel_leases", "receipts": "room_kernel_receipts", "deadLetters": "room_kernel_dead_letters"}
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
        conn: sqlite3.Connection, *, root_id: str, dispatch_id: str, now_ms: int
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
            ("concurrency", 1, "concurrency_limit", None, "concurrency_reserved"),
            ("input token", DISPATCH_INPUT_TOKEN_RESERVATION, "input_token_limit", "input_token_used", "input_token_reserved"),
            ("output token", DISPATCH_OUTPUT_TOKEN_RESERVATION, "output_token_limit", "output_token_used", "output_token_reserved"),
            ("tool call", DISPATCH_TOOL_CALL_RESERVATION, "tool_call_limit", "tool_call_used", "tool_call_reserved"),
            ("tool cost", DISPATCH_TOOL_COST_RESERVATION, "tool_cost_limit", "tool_cost_used", "tool_cost_reserved"),
        )
        for label, requested, limit_key, used_key, reserved_key in checks:
            used = int(limits[used_key]) if used_key else 0
            if used + int(limits[reserved_key]) + requested > int(limits[limit_key]):
                raise RoomKernelFenceError(f"Root {label} limit exhausted")
        conn.execute(
            """INSERT INTO room_kernel_dispatch_resource_reservations(
               dispatch_id,root_id,input_tokens,output_tokens,tool_calls,tool_cost,
               state,created_at_ms,updated_at_ms)
               VALUES (?,?,?,?,?,?,'reserved',?,?)""",
            (
                dispatch_id, root_id, DISPATCH_INPUT_TOKEN_RESERVATION,
                DISPATCH_OUTPUT_TOKEN_RESERVATION, DISPATCH_TOOL_CALL_RESERVATION,
                DISPATCH_TOOL_COST_RESERVATION, int(now_ms), int(now_ms),
            ),
        )
        conn.execute(
            """UPDATE room_kernel_root_limits SET
               dispatch_reserved=dispatch_reserved+1,
               concurrency_reserved=concurrency_reserved+1,
               input_token_reserved=input_token_reserved+?,
               output_token_reserved=output_token_reserved+?,
               tool_call_reserved=tool_call_reserved+?,
               tool_cost_reserved=tool_cost_reserved+?,updated_at_ms=?
               WHERE root_id=?""",
            (
                DISPATCH_INPUT_TOKEN_RESERVATION, DISPATCH_OUTPUT_TOKEN_RESERVATION,
                DISPATCH_TOOL_CALL_RESERVATION, DISPATCH_TOOL_COST_RESERVATION,
                int(now_ms), root_id,
            ),
        )

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
               concurrency_reserved=MAX(0,concurrency_reserved-1),
               dispatch_used=dispatch_used+?,input_token_used=input_token_used+?,
               output_token_used=output_token_used+?,tool_call_used=tool_call_used+?,
               tool_cost_used=tool_cost_used+?,retry_used=retry_used+?,repair_used=repair_used+?,
               updated_at_ms=? WHERE root_id=?""",
            (
                reservation["input_tokens"], reservation["output_tokens"],
                reservation["tool_calls"], reservation["tool_cost"],
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


def _dispatch_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = json.loads(str(row["payload_json"]))
    payload["state"] = str(row["state"])
    return payload


def _criteria(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {str(item).strip() for item in value if str(item or "").strip()}


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
