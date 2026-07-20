from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations


class RuntimeHostKillGate:
    """Durable process-tree kill authority for the managed Pi Runtime Host.

    Cooperative RPC cancellation remains the first path. This gate is the
    bounded escalation path and refuses to signal a recycled PID/process group.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        signal_tree: Callable[[int], None] | None = None,
        identity_probe: Callable[[int], tuple[int, str] | None] | None = None,
        confirm_attempts: int = 4,
        confirm_interval_seconds: float = 0.01,
    ) -> None:
        self.db_path = Path(db_path)
        self._signal_tree = signal_tree or _signal_process_group
        self._identity_probe = identity_probe or _process_identity
        self._confirm_attempts = max(1, int(confirm_attempts))
        self._confirm_interval_seconds = max(0.0, float(confirm_interval_seconds))

    def initialize(self) -> int:
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def register_process(
        self,
        *,
        host_identity: str,
        owner_instance_id: str,
        pid: int,
        process_group_id: int,
        job_identity: str,
        process_birth_token: str,
        executable_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        if min(int(pid), int(process_group_id)) <= 0:
            raise ValueError("runtime host process identity requires positive pid and process group")
        required = (host_identity, owner_instance_id, job_identity, process_birth_token, executable_ref)
        if any(not str(value).strip() for value in required):
            raise ValueError("runtime host process identity is incomplete")
        with self._connect(immediate=True) as conn:
            active = conn.execute(
                "SELECT host_identity FROM room_v2_runtime_host_processes WHERE state='running'"
            ).fetchall()
            if active:
                raise RuntimeError("an unreconciled Runtime Host process is still registered")
            conn.execute(
                """INSERT INTO room_v2_runtime_host_processes(
                   host_identity,owner_instance_id,pid,process_group_id,job_identity,
                   process_birth_token,executable_ref,state,registered_at_ms,updated_at_ms)
                   VALUES (?,?,?,?,?,?,?,'running',?,?)""",
                (
                    host_identity,
                    owner_instance_id,
                    int(pid),
                    int(process_group_id),
                    job_identity,
                    process_birth_token,
                    executable_ref,
                    int(now_ms),
                    int(now_ms),
                ),
            )
        return self.process(host_identity)

    def mark_terminated(self, host_identity: str, *, now_ms: int) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_v2_runtime_host_processes SET state='terminated',updated_at_ms=? WHERE host_identity=?",
                (int(now_ms), host_identity),
            )
            conn.execute(
                """UPDATE room_v2_runtime_host_kill_receipts
                   SET state='terminated',pending_targets_json='[]',terminated_at_ms=?,updated_at_ms=?
                   WHERE host_identity=? AND state IN ('requested','acknowledged')""",
                (int(now_ms), int(now_ms), host_identity),
            )

    def request_kill(
        self,
        host_identity: str,
        *,
        request_kind: str,
        requested_by: str,
        reason: str,
        now_ms: int,
    ) -> dict[str, object]:
        if request_kind not in {"cancel_timeout", "admin_panic", "orphan_reconcile"}:
            raise ValueError("unsupported Runtime Host kill request kind")
        if request_kind == "admin_panic" and not requested_by.startswith("admin:"):
            raise PermissionError("Runtime Host panic requires an administrator identity")
        receipt_id = f"runtime-kill:{uuid.uuid4()}"
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_runtime_host_processes WHERE host_identity=?",
                (host_identity,),
            ).fetchone()
            if row is None:
                raise KeyError(host_identity)
            pending = [self._target(row)] if row["state"] == "running" else []
            initial = "requested" if pending else "terminated"
            conn.execute(
                """INSERT INTO room_v2_runtime_host_kill_receipts(
                   kill_receipt_id,host_identity,request_kind,requested_by,reason,state,
                   pending_targets_json,requested_at_ms,terminated_at_ms,updated_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    receipt_id,
                    host_identity,
                    request_kind,
                    requested_by,
                    str(reason)[:500],
                    initial,
                    _json(pending),
                    int(now_ms),
                    int(now_ms) if not pending else 0,
                    int(now_ms),
                ),
            )
        if not pending:
            return self.receipt(receipt_id)
        self._deliver(receipt_id, now_ms=now_ms)
        self.confirm_termination(receipt_id, now_ms=now_ms)
        return self.receipt(receipt_id)

    def confirm_termination(self, receipt_id: str, *, now_ms: int) -> dict[str, object]:
        receipt = self.receipt(receipt_id)
        if receipt["state"] != "acknowledged":
            return receipt
        process = self.process(str(receipt["hostIdentity"]))
        pid = int(process["pid"])
        expected_birth = ""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT process_birth_token FROM room_v2_runtime_host_processes WHERE host_identity=?",
                (receipt["hostIdentity"],),
            ).fetchone()
            expected_birth = str(row[0]) if row else ""
        for _ in range(self._confirm_attempts):
            observed = self._identity_probe(pid)
            if observed is None or observed[1] != expected_birth:
                self.mark_terminated(str(receipt["hostIdentity"]), now_ms=now_ms)
                return self.receipt(receipt_id)
            if self._confirm_interval_seconds:
                time.sleep(self._confirm_interval_seconds)
        return self.receipt(receipt_id)

    def reconcile_orphans(
        self, *, owner_instance_id: str, now_ms: int, include_owner: bool = False
    ) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT host_identity FROM room_v2_runtime_host_processes
                   WHERE state='running' AND (?=1 OR owner_instance_id!=?)
                   ORDER BY registered_at_ms""",
                (int(include_owner), owner_instance_id),
            ).fetchall()
        return [
            self.request_kill(
                str(row[0]),
                request_kind="orphan_reconcile",
                requested_by=f"runtime:{owner_instance_id}",
                reason="runtime host owner restarted",
                now_ms=now_ms,
            )
            for row in rows
        ]

    def receipt(self, receipt_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_runtime_host_kill_receipts WHERE kill_receipt_id=?",
                (receipt_id,),
            ).fetchone()
        if row is None:
            raise KeyError(receipt_id)
        return {
            "schemaVersion": "wisdom-weasel.runtime-host-kill-receipt.v1",
            "killReceiptId": str(row["kill_receipt_id"]),
            "hostIdentity": str(row["host_identity"]),
            "requestKind": str(row["request_kind"]),
            "requestedBy": str(row["requested_by"]),
            "state": str(row["state"]),
            "pendingTargets": json.loads(str(row["pending_targets_json"])),
            "errorCode": str(row["error_code"]),
            "requestedAtMs": int(row["requested_at_ms"]),
            "acknowledgedAtMs": int(row["acknowledged_at_ms"]),
            "terminatedAtMs": int(row["terminated_at_ms"]),
        }

    def process(self, host_identity: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_runtime_host_processes WHERE host_identity=?",
                (host_identity,),
            ).fetchone()
        if row is None:
            raise KeyError(host_identity)
        return self._target(row) | {"state": str(row["state"])}

    def _deliver(self, receipt_id: str, *, now_ms: int) -> None:
        with self._connect(immediate=True) as conn:
            receipt = conn.execute(
                "SELECT * FROM room_v2_runtime_host_kill_receipts WHERE kill_receipt_id=? AND state='requested'",
                (receipt_id,),
            ).fetchone()
            if receipt is None:
                return
            process = conn.execute(
                "SELECT * FROM room_v2_runtime_host_processes WHERE host_identity=?",
                (receipt["host_identity"],),
            ).fetchone()
            assert process is not None
            observed = self._identity_probe(int(process["pid"]))
            expected = (int(process["process_group_id"]), str(process["process_birth_token"]))
            if observed is None:
                conn.execute(
                    "UPDATE room_v2_runtime_host_processes SET state='terminated',updated_at_ms=? WHERE host_identity=?",
                    (int(now_ms), process["host_identity"]),
                )
                conn.execute(
                    """UPDATE room_v2_runtime_host_kill_receipts SET state='terminated',pending_targets_json='[]',
                       terminated_at_ms=?,updated_at_ms=? WHERE kill_receipt_id=?""",
                    (int(now_ms), int(now_ms), receipt_id),
                )
                return
            if observed != expected:
                conn.execute(
                    "UPDATE room_v2_runtime_host_processes SET state='unknown',updated_at_ms=? WHERE host_identity=?",
                    (int(now_ms), process["host_identity"]),
                )
                conn.execute(
                    """UPDATE room_v2_runtime_host_kill_receipts SET state='unknown',error_code='process_identity_mismatch',
                       updated_at_ms=? WHERE kill_receipt_id=?""",
                    (int(now_ms), receipt_id),
                )
                return
            try:
                self._signal_tree(int(process["process_group_id"]))
            except (OSError, ProcessLookupError):
                conn.execute(
                    """UPDATE room_v2_runtime_host_kill_receipts SET state='unknown',error_code='kill_signal_failed',
                       updated_at_ms=? WHERE kill_receipt_id=?""",
                    (int(now_ms), receipt_id),
                )
                return
            conn.execute(
                """UPDATE room_v2_runtime_host_kill_receipts SET state='acknowledged',acknowledged_at_ms=?,
                   updated_at_ms=? WHERE kill_receipt_id=?""",
                (int(now_ms), int(now_ms), receipt_id),
            )

    @staticmethod
    def _target(row: sqlite3.Row) -> dict[str, object]:
        return {
            "hostIdentity": str(row["host_identity"]),
            "pid": int(row["pid"]),
            "processGroupId": int(row["process_group_id"]),
            "jobIdentity": str(row["job_identity"]),
        }

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def process_birth_token(pid: int) -> str:
    identity = _process_identity(pid)
    if identity is None:
        raise RuntimeError("Runtime Host exited before process identity registration")
    return identity[1]


def _process_identity(pid: int) -> tuple[int, str] | None:
    try:
        process_group_id = os.getpgid(int(pid))
    except (OSError, ProcessLookupError):
        return None
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(int(pid))],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    token = " ".join(result.stdout.split())
    return (int(process_group_id), token) if result.returncode == 0 and token else None


def _signal_process_group(process_group_id: int) -> None:
    if os.name == "posix":
        os.killpg(int(process_group_id), signal.SIGKILL)
        return
    raise OSError("process-tree kill is unavailable on this platform")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
