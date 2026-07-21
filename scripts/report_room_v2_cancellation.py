#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


RUNTIME_SURFACES = {
    "provider",
    "tool",
    "exec",
    "retry",
    "compaction",
    "branch_summary",
    "timer",
    "continuation",
    "session",
}


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise RuntimeError("cancellation receipt must be a JSON object")
    return parsed


def _row(row: sqlite3.Row | None, label: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"missing {label}")
    return dict(row)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _select_root(conn: sqlite3.Connection, root_id: str) -> dict[str, Any]:
    if root_id:
        row = conn.execute(
            "SELECT * FROM room_kernel_roots WHERE root_id=?",
            (root_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM room_kernel_roots
               WHERE terminal_receipt_id IS NOT NULL
               ORDER BY updated_at_ms DESC LIMIT 1"""
        ).fetchone()
    return _row(row, "terminal Room Root")


def build_report(db_path: Path, root_id: str = "") -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        root = _select_root(conn, root_id)
        dispatch_rows = conn.execute(
            """SELECT dispatch_id,target_session_id,generation,state,updated_at_ms
               FROM room_kernel_dispatches WHERE root_id=? ORDER BY created_at_ms""",
            (root["root_id"],),
        ).fetchall()
        if not dispatch_rows:
            raise RuntimeError("Room Root has no dispatches")

        dispatches: list[dict[str, Any]] = []
        all_surfaces: list[dict[str, Any]] = []
        lifecycle_receipts: list[dict[str, Any]] = []
        checks: dict[str, bool] = {
            "rootCancelled": root["state"] == "cancelled",
            "terminalReceiptPresent": bool(root["terminal_receipt_id"]),
            "dispatchesCancelled": True,
            "cancelOutboxApplied": True,
            "abortScopesCancelled": True,
            "allRuntimeSurfacesPresent": True,
            "allRuntimeSurfacesTerminated": True,
            "typedSessionAbortReceipt": True,
            "lifecycleDrainedAndIdle": True,
            "noPendingLifecycleOperations": True,
        }

        for dispatch_row in dispatch_rows:
            dispatch = dict(dispatch_row)
            scope = _row(
                conn.execute(
                    "SELECT state,cancel_receipt_json FROM room_kernel_abort_scopes WHERE dispatch_id=?",
                    (dispatch["dispatch_id"],),
                ).fetchone(),
                f"abort scope for {dispatch['dispatch_id']}",
            )
            cancel = _row(
                conn.execute(
                    """SELECT cancel_id,state,attempt_count,last_error,runtime_receipt_json
                       FROM room_kernel_cancel_outbox
                       WHERE root_id=? AND dispatch_id=? ORDER BY created_at_ms DESC LIMIT 1""",
                    (root["root_id"], dispatch["dispatch_id"]),
                ).fetchone(),
                f"cancel outbox row for {dispatch['dispatch_id']}",
            )
            surfaces = [
                dict(row)
                for row in conn.execute(
                    """SELECT surface,state,target_ref,detail_json,updated_at_ms
                       FROM room_v2_runtime_cancel_surface_receipts
                       WHERE cancel_id=? ORDER BY surface""",
                    (cancel["cancel_id"],),
                ).fetchall()
            ]
            runtime_receipt = _json_object(cancel.pop("runtime_receipt_json"))
            session_receipt = runtime_receipt.get("sessionAbortReceipt")
            lifecycle = session_receipt.get("lifecycle") if isinstance(session_receipt, dict) else None

            checks["dispatchesCancelled"] &= dispatch["state"] == "cancelled"
            checks["cancelOutboxApplied"] &= cancel["state"] == "applied"
            checks["abortScopesCancelled"] &= scope["state"] == "cancelled"
            checks["allRuntimeSurfacesPresent"] &= {row["surface"] for row in surfaces} == RUNTIME_SURFACES
            checks["allRuntimeSurfacesTerminated"] &= bool(surfaces) and all(
                row["state"] == "terminated" for row in surfaces
            )
            checks["typedSessionAbortReceipt"] &= (
                isinstance(session_receipt, dict)
                and session_receipt.get("schemaVersion") == "rag-ime.pi-session-abort-receipt.v1"
                and isinstance(lifecycle, dict)
                and lifecycle.get("schemaVersion") == "pi.agent-abort-receipt.v1"
            )
            checks["lifecycleDrainedAndIdle"] &= (
                isinstance(lifecycle, dict)
                and lifecycle.get("drained") is True
                and lifecycle.get("idle") is True
            )
            checks["noPendingLifecycleOperations"] &= (
                isinstance(lifecycle, dict) and lifecycle.get("pendingOperations") == []
            )
            if isinstance(lifecycle, dict):
                lifecycle_receipts.append(lifecycle)
            all_surfaces.extend(surfaces)
            dispatches.append(
                {
                    **dispatch,
                    "abortScopeState": scope["state"],
                    "cancel": cancel,
                    "runtimeReceipt": runtime_receipt,
                    "surfaces": surfaces,
                }
            )

        terminal_receipt = _row(
            conn.execute(
                "SELECT * FROM room_kernel_receipts WHERE receipt_id=?",
                (root["terminal_receipt_id"],),
            ).fetchone(),
            "Room Root terminal receipt",
        )

    report = {
        "schemaVersion": "rag-ime.room-v2-cancellation-evidence.v1",
        "observedAtMs": int(time.time() * 1000),
        "sourceDb": str(db_path.resolve()),
        "passed": all(checks.values()),
        "checks": checks,
        "root": root,
        "terminalReceipt": terminal_receipt,
        "dispatches": dispatches,
        "surfaceCount": len(all_surfaces),
        "lifecycleReceiptCount": len(lifecycle_receipts),
    }
    if not report["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"Room cancellation evidence failed: {', '.join(failed)}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and persist typed Room V2 cancellation evidence from a live canary database"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--root-id", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.db.resolve(), args.root_id)
    _atomic_write(args.output.resolve(), report)
    print(json.dumps({"passed": True, "rootId": report["root"]["root_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
