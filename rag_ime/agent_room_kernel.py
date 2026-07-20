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
from .db import apply_database_migrations


KernelMode = Literal["off", "shadow", "cohort", "test"]
_ACTIVE_DISPATCH_STATES = ("pending", "leased", "running", "retry_wait", "timer_wait")
_TERMINAL_TASK_STATES = ("completed", "failed", "cancelled")


class RoomKernelFenceError(RuntimeError):
    pass


class RoomKernelStore:
    """Non-cutover Room state machine.

    The production default is shadow-only. Legacy Intercom, WorkItem, mention,
    and wake paths may normalize into this store, but they cannot lease work or
    become a second execution authority.
    """

    def __init__(self, db_path: str | Path, *, mode: KernelMode = "shadow", enforce_test_delivery_gate: bool = False) -> None:
        if mode not in {"off", "shadow", "cohort", "test"}:
            raise ValueError("Room Kernel mode must be off, shadow, cohort, or test")
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
        return self.root(root_id)

    def create_task(self, payload: Mapping[str, object], *, now_ms: int) -> dict[str, object]:
        validate_kernel_contract("roomTask", payload)
        with self._connect(immediate=True) as conn:
            self._root_row(conn, str(payload["rootId"]))
            conn.execute(
                """
                INSERT INTO room_kernel_tasks(
                    task_id, root_id, parent_task_id, state, payload_json, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(payload["taskId"]),
                    str(payload["rootId"]),
                    payload.get("parentTaskId"),
                    str(payload["state"]),
                    _json(payload),
                    int(now_ms),
                ),
            )
        return self.task(str(payload["taskId"]))

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
                    shadow_only=self.mode not in {"cohort", "test"},
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
        source_kind: Literal["intercom", "work_item", "mention", "wake"],
        source_id: str,
        now_ms: int,
    ) -> tuple[dict[str, object] | None, bool]:
        """Fail closed for ordinary sessions and normalize bound legacy paths."""

        if room_binding_ref is None:
            return None, False
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
                shadow_only=self.mode not in {"cohort", "test"},
                now_ms=now_ms,
            )

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
        if self.mode not in {"cohort", "test"}:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """SELECT o.payload_json FROM room_kernel_outbox o
                   JOIN room_kernel_dispatches d USING(dispatch_id)
                   WHERE o.state = 'pending' AND o.shadow_only = 0
                     AND o.available_at_ms <= ? AND d.state = 'pending'
                   ORDER BY o.available_at_ms, o.outbox_id LIMIT 1""",
                (int(now_ms),),
            ).fetchone()
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
        if self.mode not in {"cohort", "test"}:
            return None
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """SELECT o.*, d.state AS dispatch_state, d.target_session_id
                   FROM room_kernel_outbox o JOIN room_kernel_dispatches d USING(dispatch_id)
                   WHERE o.state = 'pending' AND o.shadow_only = 0
                     AND o.available_at_ms <= ? AND d.state = 'pending'
                     AND (? = '' OR o.dispatch_id = ?)
                   ORDER BY o.available_at_ms, o.outbox_id LIMIT 1""",
                (int(now_ms), dispatch_id, dispatch_id),
            ).fetchone()
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
                conn.execute("UPDATE room_kernel_outbox SET state = 'dead_letter', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), dispatch_id))
                dead_id = f"dead-letter:{dispatch_id}"
                conn.execute(
                    """INSERT OR IGNORE INTO room_kernel_dead_letters(
                       dead_letter_id, root_id, dispatch_id, reason_code, payload_json, created_at_ms
                       ) VALUES (?, ?, ?, 'lease_expired_result_unknown', ?, ?)""",
                    (dead_id, lease["root_id"], dispatch_id, _json({"leaseId": lease["lease_id"]}), int(now_ms)),
                )
                receipts.append(self._receipt(conn, root_id=str(lease["root_id"]), command_id=None, receipt_kind="dispatch_unknown", status="unknown", generation=int(lease["generation"]), details={"dispatchId": dispatch_id, "deadLetterId": dead_id}, now_ms=now_ms))
        return receipts

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
                "UPDATE room_kernel_dispatches SET state = 'running', updated_at_ms = ? WHERE dispatch_id = ? AND state = 'leased'",
                (int(now_ms), lease["dispatch_id"]),
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state = 'running', updated_at_ms = ? WHERE dispatch_id = ? AND state = 'leased'",
                (int(now_ms), lease["dispatch_id"]),
            )
            return self._receipt(
                conn,
                root_id=str(lease["root_id"]),
                command_id=None,
                receipt_kind="runtime_accepted",
                status="applied",
                generation=generation,
                details={
                    "dispatchId": str(lease["dispatch_id"]),
                    "leaseId": str(lease["lease_id"]),
                    "runtimeReceipt": dict(runtime_receipt),
                },
                now_ms=now_ms,
            )

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

    def apply_commit(
        self,
        payload: Mapping[str, object],
        *,
        generation: int,
        now_ms: int,
        post_proposal: Mapping[str, object] | None = None,
        invocation_receipt_id: str = "",
    ) -> dict[str, object]:
        validate_kernel_contract("roomCommit", payload)
        if post_proposal is not None:
            validate_kernel_contract("roomPost", post_proposal)
        if (payload.get("action") == "post") != (post_proposal is not None):
            raise RoomKernelFenceError("RoomCommit post action and RoomPost proposal must agree")
        with self._connect(immediate=True) as conn:
            dispatch = self._dispatch_row(conn, str(payload["dispatchId"]))
            root = self._root_row(conn, str(dispatch["root_id"]))
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
            conn.execute("UPDATE room_kernel_dispatches SET state = 'committed', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), payload["dispatchId"]))
            conn.execute("UPDATE room_kernel_outbox SET state = 'committed', updated_at_ms = ? WHERE dispatch_id = ?", (int(now_ms), payload["dispatchId"]))
            conn.execute("UPDATE room_kernel_leases SET state = 'completed', updated_at_ms = ? WHERE dispatch_id = ? AND state = 'active'", (int(now_ms), payload["dispatchId"]))
            remaining = max(0, int(root["budget_remaining"]) - int(dispatch["budget_cost"]))
            reserved = max(0, int(root["budget_reserved"]) - int(dispatch["budget_cost"]))
            covered = set(json.loads(str(root["covered_criteria_json"])))
            covered.update(str(item) for item in payload["requirementCoverage"])
            conn.execute("UPDATE room_kernel_roots SET budget_remaining = ?, budget_reserved = ?, covered_criteria_json = ?, updated_at_ms = ? WHERE root_id = ?", (remaining, reserved, _json(sorted(covered)), int(now_ms), root["root_id"]))
            if str(payload["action"]) == "complete":
                conn.execute("UPDATE room_kernel_tasks SET state = 'completed', updated_at_ms = ? WHERE task_id = ?", (int(now_ms), dispatch["task_id"]))
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
            receipt = self._receipt(conn, root_id=str(root["root_id"]), command_id=None, receipt_kind="accepted", status="applied", generation=generation, details={"commitId": payload["commitId"]}, now_ms=now_ms)
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
        return self._receipt(conn, root_id=root_id, command_id=command_id, receipt_kind="target_cancelled", status="applied" if count else "noop", generation=int(root["generation"]), details={"targetKind": target_kind, "targetId": target_id, "cancelledDispatches": count}, now_ms=now_ms)

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
        generation = int(root["generation"]) + 1
        unknown = int(conn.execute("SELECT COUNT(*) FROM room_kernel_dispatches WHERE root_id = ? AND state = 'unknown'", (root_id,)).fetchone()[0])
        ids = [str(row[0]) for row in conn.execute(f"SELECT dispatch_id FROM room_kernel_dispatches WHERE root_id = ? AND state IN ({','.join('?' for _ in _ACTIVE_DISPATCH_STATES)})", (root_id, *_ACTIVE_DISPATCH_STATES))]
        cancelled = self._cancel_dispatch_ids(conn, ids, now_ms=now_ms)
        state = "cancelled_with_unknowns" if unknown else "cancelled"
        conn.execute("UPDATE room_kernel_roots SET generation = ?, state = ?, updated_at_ms = ? WHERE root_id = ?", (generation, state, int(now_ms), root_id))
        return self._receipt(conn, root_id=root_id, command_id=command_id, receipt_kind=receipt_kind, status="applied", generation=generation, details={"cancelledDispatches": cancelled, "unknownDispatches": unknown}, now_ms=now_ms)

    def _cancel_dispatch_ids(self, conn: sqlite3.Connection, ids: list[str], *, now_ms: int) -> int:
        released_by_root: dict[str, int] = {}
        for dispatch_id in ids:
            row = self._dispatch_row(conn, dispatch_id)
            if str(row["state"]) in _ACTIVE_DISPATCH_STATES:
                root_id = str(row["root_id"])
                released_by_root[root_id] = released_by_root.get(root_id, 0) + int(row["budget_cost"])
            conn.execute("UPDATE room_kernel_dispatches SET state = 'cancelled', updated_at_ms = ? WHERE dispatch_id = ? AND state IN ('pending','leased','running','retry_wait','timer_wait')", (int(now_ms), dispatch_id))
            conn.execute("UPDATE room_kernel_outbox SET state = 'cancelled', updated_at_ms = ? WHERE dispatch_id = ? AND state NOT IN ('committed','dead_letter')", (int(now_ms), dispatch_id))
            conn.execute("UPDATE room_kernel_leases SET state = 'cancelled', updated_at_ms = ? WHERE dispatch_id = ? AND state = 'active'", (int(now_ms), dispatch_id))
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
            payload.update({"generation": int(row["generation"]), "state": str(row["state"]), "budgetRemaining": int(row["budget_remaining"]), "budgetReserved": int(row["budget_reserved"]), "terminalReceiptId": row["terminal_receipt_id"]})
            return payload

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

    def commit(self, commit_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM room_kernel_commits WHERE commit_id = ?", (commit_id,)).fetchone()
            if row is None:
                raise KeyError(commit_id)
            return json.loads(str(row["payload_json"]))

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
