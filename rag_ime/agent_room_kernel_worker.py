from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore


class RoomRuntime(Protocol):
    def dispatch_room(
        self,
        payload: Mapping[str, object],
        *,
        message: str,
        lease_token: str,
    ) -> dict[str, object]: ...

    def cancel_room(
        self,
        *,
        session_id: str,
        root_id: str,
        generation: int,
    ) -> dict[str, object]: ...


class RoomKernelWorker:
    """Single-authority outbox delivery adapter for typed Pi Room RPC."""

    def __init__(
        self,
        store: RoomKernelStore,
        runtime: RoomRuntime,
        *,
        message_builder: Callable[[Mapping[str, object]], str] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.message_builder = message_builder or _default_dispatch_message
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def run_once(self, *, lease_ttl_ms: int = 30_000) -> dict[str, object] | None:
        if self.store.mode not in {"cohort", "test"}:
            return None
        now_ms = self.clock_ms()
        lease = self.store.lease_next(now_ms=now_ms, ttl_ms=lease_ttl_ms)
        if lease is None:
            return None
        dispatch = self.store.outbox(str(lease["dispatchId"]))["payload"]
        if not isinstance(dispatch, Mapping):
            raise RoomKernelFenceError("outbox payload is not a Dispatch envelope")
        runtime_receipt = self.runtime.dispatch_room(
            dispatch,
            message=self.message_builder(dispatch),
            lease_token=str(lease["leaseToken"]),
        )
        return self.store.accept_runtime_receipt(
            lease_token=str(lease["leaseToken"]),
            runtime_receipt=runtime_receipt,
            now_ms=self.clock_ms(),
        )

    def cancel_root(self, root_id: str) -> dict[str, object]:
        targets = self.store.active_runtime_targets(root_id)
        kernel_receipt = self.store.cancel_root(root_id, now_ms=self.clock_ms())
        runtime_receipts: list[dict[str, object]] = []
        for target in targets:
            runtime_receipts.append(
                self.runtime.cancel_room(
                    session_id=str(target["sessionId"]),
                    root_id=root_id,
                    generation=int(kernel_receipt["generation"]),
                )
            )
        return {"kernelReceipt": kernel_receipt, "runtimeReceipts": runtime_receipts}

    def apply_control_command(self, command: Mapping[str, object]) -> dict[str, object]:
        kind = str(command.get("commandKind") or "")
        room_id = str(command.get("roomId") or "")
        root_id = str(command.get("rootId") or "")
        if kind == "panic":
            targets = self.store.room_active_runtime_targets(room_id)
        else:
            targets = self.store.active_runtime_targets(
                root_id,
                target_kind=(
                    str(command.get("targetKind") or "root")
                    if kind == "cancel_target"
                    else "root"
                ),
                target_id=str(command.get("targetId") or ""),
            )
            for target in targets:
                target["rootId"] = root_id
        receipt = self.store.apply_control_command(command)
        failures: dict[str, list[str]] = {}
        for target in targets:
            target_root_id = str(target["rootId"])
            try:
                generation = int(self.store.root(target_root_id)["generation"])
                self.runtime.cancel_room(
                    session_id=str(target["sessionId"]),
                    root_id=target_root_id,
                    generation=generation,
                )
            except Exception as exc:
                failures.setdefault(target_root_id, []).append(str(target["dispatchId"]))
                reason = f"{type(exc).__name__}: {exc}"[:500]
                self.store.mark_runtime_cancel_unknown(
                    root_id=target_root_id,
                    dispatch_ids=[str(target["dispatchId"])],
                    reason=reason,
                    now_ms=self.clock_ms(),
                )
        return {"kernelReceipt": receipt, "runtimeCancelFailures": failures}

    def reconcile(self) -> list[dict[str, object]]:
        return self.store.reconcile_expired_leases(now_ms=self.clock_ms())


def _default_dispatch_message(dispatch: Mapping[str, object]) -> str:
    return "[ROOM_DISPATCH_V2]\n" + json.dumps(
        dict(dispatch), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


class RoomKernelWorkerLoop:
    """Stoppable cohort worker; shadow/off modes never start a thread."""

    def __init__(
        self,
        worker: RoomKernelWorker,
        *,
        on_change: Callable[[], object] | None = None,
        poll_seconds: float = 0.25,
    ) -> None:
        self.worker = worker
        self.on_change = on_change or (lambda: None)
        self.poll_seconds = max(0.01, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.worker.store.mode != "cohort" or self.running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="rag-ime-room-kernel-worker",
            daemon=True,
        )
        self._thread.start()
        return True

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.poll_seconds * 4))
        self._thread = None

    def wake(self) -> None:
        self._stop.wait(0)

    def _run(self) -> None:
        while not self._stop.is_set():
            changed = False
            try:
                changed = bool(self.worker.reconcile())
                changed = self.worker.run_once() is not None or changed
            except Exception:
                # A leased but unacknowledged effect is intentionally left for
                # expiry reconciliation; it must never be replayed blindly.
                pass
            if changed:
                self.on_change()
            self._stop.wait(self.poll_seconds)
