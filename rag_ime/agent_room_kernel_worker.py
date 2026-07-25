from __future__ import annotations

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
        prepare_dispatch: Callable[[Mapping[str, object], int], Mapping[str, object]] | None = None,
        prepare_memory_context: Callable[
            [Mapping[str, object], int], Mapping[str, object]
        ]
        | None = None,
        accept_runtime_context: Callable[[Mapping[str, object]], object] | None = None,
        revoke_session: Callable[[str, int], object] | None = None,
        invalidate_room_approvals: Callable[
            [str, str, str, int], Mapping[str, object]
        ]
        | None = None,
        learning_observer: Callable[[Mapping[str, object]], object] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.message_builder = message_builder or _default_dispatch_message
        self.prepare_dispatch = prepare_dispatch
        self.prepare_memory_context = prepare_memory_context
        self.accept_runtime_context = accept_runtime_context
        self.revoke_session = revoke_session
        self.invalidate_room_approvals = invalidate_room_approvals
        self.learning_observer = learning_observer
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def run_once(self, *, lease_ttl_ms: int = 30_000) -> dict[str, object] | None:
        if self.store.mode not in {"cohort", "test", "kernel_only"}:
            return None
        now_ms = self.clock_ms()
        pending = self.store.pending_dispatch(now_ms=now_ms)
        if pending is None:
            return None
        prepared: Mapping[str, object] = {}
        if self.prepare_dispatch is not None:
            prepared = self.prepare_dispatch(pending, now_ms)
            if not prepared.get("sessionId") or not prepared.get("manifestHash"):
                raise RoomKernelFenceError("managed Dispatch preparation returned no capability fence")
        if self.prepare_memory_context is not None:
            # Generic RAG is an enhancement. Its application service preserves
            # the last valid projection and may return an empty fail-open
            # receipt when no memory source is currently available.
            self.prepare_memory_context(pending, now_ms)
        lease = self.store.lease_next(
            now_ms=now_ms,
            ttl_ms=lease_ttl_ms,
            dispatch_id=str(pending["dispatchId"]),
            prepared_session_id=str(prepared.get("sessionId") or ""),
            prepared_manifest_hash=str(prepared.get("manifestHash") or ""),
        )
        if lease is None:
            return None
        dispatch = self.store.outbox(str(lease["dispatchId"]))["payload"]
        if not isinstance(dispatch, Mapping):
            raise RoomKernelFenceError("outbox payload is not a Dispatch envelope")
        self.store.record_runtime_dispatch_intent(str(dispatch["dispatchId"]), now_ms=self.clock_ms())
        try:
            runtime_receipt = self.runtime.dispatch_room(
                dispatch,
                message=self.message_builder(dispatch),
                lease_token=str(lease["leaseToken"]),
            )
        except BaseException as exc:
            if self.revoke_session is not None:
                self.revoke_session(str(dispatch["targetSessionId"]), self.clock_ms())
            self._observe_failure(dispatch, "runtime_failed", exc)
            raise
        accepted = self.store.accept_runtime_receipt(
            lease_token=str(lease["leaseToken"]),
            runtime_receipt=runtime_receipt,
            now_ms=self.clock_ms(),
        )
        try:
            if self.accept_runtime_context is not None:
                self.accept_runtime_context(runtime_receipt)
        except BaseException as exc:
            # Pi has accepted the turn, so the result is no longer an unknown
            # delivery. A failed governed projection is instead an explicit
            # fail-closed Root cancellation with durable runtime fan-out.
            self._observe_failure(
                dispatch,
                "runtime_context_failed",
                exc,
            )
            self.cancel_root(str(dispatch["rootId"]))
            raise
        return accepted

    def _observe_failure(
        self,
        dispatch: Mapping[str, object],
        event_kind: str,
        error: BaseException,
    ) -> None:
        if self.learning_observer is None:
            return
        try:
            self.learning_observer(
                {
                    "eventKind": event_kind,
                    "rootId": str(dispatch["rootId"]),
                    "dispatchId": str(dispatch["dispatchId"]),
                    "reason": f"{type(error).__name__}: {error}"[:500],
                    "createdAtMs": self.clock_ms(),
                }
            )
        except Exception:
            # Kernel state and cancellation evidence remain authoritative.
            pass

    def cancel_root(self, root_id: str) -> dict[str, object]:
        kernel_receipt = self.store.cancel_root(root_id, now_ms=self.clock_ms())
        runtime_receipts = self.drain_cancel_outbox()
        return {"kernelReceipt": kernel_receipt, "runtimeReceipts": runtime_receipts}

    def apply_control_command(self, command: Mapping[str, object]) -> dict[str, object]:
        receipt = self.store.apply_control_command(command)
        runtime_receipts = self.drain_cancel_outbox()
        return {
            "kernelReceipt": receipt,
            "runtimeReceipts": runtime_receipts,
            "runtimeCancelFailures": {},
        }

    def drain_cancel_outbox(self, *, limit: int = 100) -> list[dict[str, object]]:
        receipts: list[dict[str, object]] = []
        for _ in range(max(0, min(int(limit), 1000))):
            intent = self.store.lease_cancel(now_ms=self.clock_ms())
            if intent is None:
                break
            try:
                if self.revoke_session is not None:
                    self.revoke_session(str(intent["sessionId"]), self.clock_ms())
                approval_cancellation: Mapping[str, object] | None = None
                if self.invalidate_room_approvals is not None:
                    approval_cancellation = self.invalidate_room_approvals(
                        str(intent["sessionId"]),
                        str(intent["rootId"]),
                        str(intent["dispatchId"]),
                        self.clock_ms(),
                    )
                runtime_receipt = dict(
                    self.runtime.cancel_room(
                        session_id=str(intent["sessionId"]),
                        root_id=str(intent["rootId"]),
                        generation=int(intent["generation"]),
                    )
                )
                if approval_cancellation is not None:
                    runtime_receipt["approvalCancellation"] = dict(
                        approval_cancellation
                    )
                self.store.complete_cancel(str(intent["cancelId"]), runtime_receipt, now_ms=self.clock_ms())
                receipts.append(dict(runtime_receipt))
            except Exception as exc:
                self.store.fail_cancel(str(intent["cancelId"]), f"{type(exc).__name__}: {exc}", now_ms=self.clock_ms())
        return receipts

    def reconcile(self) -> list[dict[str, object]]:
        now_ms = self.clock_ms()
        receipts = self.store.cancel_expired_roots(now_ms=now_ms)
        receipts.extend(self.store.reconcile_expired_leases(now_ms=now_ms))
        # Durable cancel delivery owns capability revocation too; doing it here
        # would double-fire the same session when the outbox is drained below.
        self.drain_cancel_outbox()
        return receipts


class KernelCommandBus:
    """The product-facing authority for Room Kernel state transitions.

    The store remains a persistence/state-machine boundary. Routes and product
    services use this bus so dispatch delivery and cancellation propagation
    cannot accidentally take a second path.
    """

    def __init__(
        self,
        store: RoomKernelStore,
        worker: RoomKernelWorker,
        *,
        runtime_effects_enabled: bool = True,
    ) -> None:
        self.store = store
        self.worker = worker
        self.runtime_effects_enabled = bool(runtime_effects_enabled)

    def create_root_task(
        self,
        root: Mapping[str, object],
        task: Mapping[str, object],
        *,
        budget: int,
        max_hops: int,
        max_depth: int,
        acceptance_criteria: tuple[str, ...],
        now_ms: int,
    ) -> dict[str, object]:
        return self.store.create_root_with_task(
            root,
            task,
            budget=budget,
            max_hops=max_hops,
            max_depth=max_depth,
            acceptance_criteria=acceptance_criteria,
            now_ms=now_ms,
        )

    def dispatch(self, payload: Mapping[str, object], *, now_ms: int) -> tuple[dict[str, object], bool]:
        return self.store.enqueue_dispatch(payload, now_ms=now_ms)

    def dispatch_many(
        self,
        payloads: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
        *,
        now_ms: int,
    ) -> list[tuple[dict[str, object], bool]]:
        return self.store.enqueue_dispatches(payloads, now_ms=now_ms)

    def control(self, command: Mapping[str, object]) -> dict[str, object]:
        if not self.runtime_effects_enabled:
            return {
                "kernelReceipt": self.store.apply_control_command(command),
                "runtimeReceipts": [],
                "runtimeCancelFailures": {},
            }
        return self.worker.apply_control_command(command)

    def cancel_root(self, root_id: str) -> dict[str, object]:
        if not self.runtime_effects_enabled:
            return {
                "kernelReceipt": self.store.cancel_root(
                    root_id,
                    now_ms=self.worker.clock_ms(),
                ),
                "runtimeReceipts": [],
            }
        return self.worker.cancel_root(root_id)

    def commit(
        self,
        payload: Mapping[str, object],
        *,
        generation: int,
        now_ms: int,
        post_proposal: Mapping[str, object] | None = None,
        invocation_receipt_id: str = "",
        resource_usage: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.store.apply_commit(
            payload,
            generation=generation,
            now_ms=now_ms,
            post_proposal=post_proposal,
            invocation_receipt_id=invocation_receipt_id,
            resource_usage=resource_usage,
        )

    def finalize(
        self,
        root_id: str,
        *,
        now_ms: int,
        delivery_gate_preview: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.store.finalize_root(
            root_id,
            now_ms=now_ms,
            delivery_gate_preview=delivery_gate_preview,
        )


def _default_dispatch_message(_dispatch: Mapping[str, object]) -> str:
    # Dispatch identity, requirements and Room facts are already carried by
    # the fenced provider-only projection. The Session receives only a stable
    # private trigger, never the transport envelope or its internal IDs.
    return (
        "执行当前受管 Room 任务；任务事实与责任以本轮 Room Context 为准。"
        "需要确认当前责任、验收或成员时先调用 room_state。"
        "AC 是 Acceptance Criterion（验收条件）的短别名；AC-1 就是 room_state "
        "当前验收清单的第一项。收工只调用 room_commit：evidence.acceptance "
        "只能填写 room_state 的 acceptanceAliases 返回的 AC-1、AC-2 等当前任务"
        "验收别名；每个 AC 只提交直接支撑它的最小 refs 集合。refs 必须逐字复制"
        "最新 room_state 或成功工具结果返回的完整 evidenceRef，不得重写、拼接或"
        "猜测；不要填写数据库 criterionId，也不要自报 "
        "已通过或最终裁决，真实状态由 Kernel 判定。"
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
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.worker.store.mode not in {"cohort", "kernel_only"} or self.running:
            return False
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="rag-ime-room-kernel-worker",
            daemon=True,
        )
        self._thread.start()
        return True

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.poll_seconds * 4))
        self._thread = None

    def wake(self) -> None:
        self._wake.set()

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
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
