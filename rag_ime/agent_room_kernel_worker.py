from __future__ import annotations

import json
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
        if self.store.mode != "test":
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

    def reconcile(self) -> list[dict[str, object]]:
        return self.store.reconcile_expired_leases(now_ms=self.clock_ms())


def _default_dispatch_message(dispatch: Mapping[str, object]) -> str:
    return "[ROOM_DISPATCH_V2]\n" + json.dumps(
        dict(dispatch), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
