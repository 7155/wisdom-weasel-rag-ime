from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from .agent_room_kernel import (
    RoomKernelFenceError,
    RoomKernelStore,
    kernel_owns_room_execution,
)


_LOG = logging.getLogger(__name__)

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
_SIDECAR_FOREGROUND_SURFACES = frozenset({"tool", "exec"})


def _matches_terminal_host_kill(
    receipt: object,
    intent: Mapping[str, object],
) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    termination = receipt.get("runtimeHostTermination")
    if not isinstance(termination, Mapping):
        return False
    try:
        exact_generation = int(receipt.get("generation", -1)) == int(
            intent["generation"]
        )
        exact_capability_epoch = int(
            receipt.get("capabilityEpoch", -1)
        ) == int(intent["capabilityEpoch"])
    except (TypeError, ValueError):
        return False
    return bool(
        receipt.get("schemaVersion")
        == "wisdom-weasel.room-runtime-receipt.v1"
        and receipt.get("receiptKind") == "cancel_applied"
        and receipt.get("status") == "applied"
        and receipt.get("cancelId") == intent.get("cancelId")
        and receipt.get("sessionId") == intent.get("sessionId")
        and receipt.get("rootId") == intent.get("rootId")
        and receipt.get("dispatchId") == intent.get("dispatchId")
        and receipt.get("turnId") == intent.get("turnId")
        and exact_generation
        and exact_capability_epoch
        and termination.get("schemaVersion")
        == "wisdom-weasel.runtime-host-kill-receipt.v1"
        and termination.get("requestKind") == "cancel_timeout"
        and termination.get("requestedBy")
        == f"session:{intent.get('sessionId')}"
        and termination.get("state") == "terminated"
        and termination.get("pendingTargets") == []
        and str(termination.get("killReceiptId") or "").strip()
        and str(termination.get("hostIdentity") or "").strip()
    )


def _exact_foreground_quiescence(
    receipt: Mapping[str, object],
    request: Mapping[str, object],
) -> bool:
    material = dict(receipt)
    revision = str(material.pop("receiptRevision", "") or "")
    if not revision or revision != hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest():
        return False
    if (
        receipt.get("schemaVersion")
        != "wisdom-weasel.room-workspace-writer-quiescence.v1"
        or any(receipt.get(key) != value for key, value in request.items())
    ):
        return False
    foreground = receipt.get("foregroundMutatingInvocations")
    if not isinstance(foreground, Mapping):
        return False
    active_count = foreground.get("activeCount")
    return bool(
        foreground.get("known") is True
        and isinstance(active_count, int)
        and not isinstance(active_count, bool)
        and active_count == 0
        and foreground.get("pendingInvocationReceiptIds") == []
        and foreground.get("hostTerminatedInvocationReceiptIds") == []
        and foreground.get("invalidExecutionReceiptIds") == []
    )


class RoomRuntime(Protocol):
    def dispatch_room(
        self,
        payload: Mapping[str, object],
        *,
        message: str,
        images: list[Mapping[str, str]] | None = None,
        lease_token: str,
        record_intent: Callable[[], None],
    ) -> dict[str, object]: ...

    def cancel_room(
        self,
        *,
        cancel_id: str,
        session_id: str,
        root_id: str,
        dispatch_id: str,
        generation: int,
        turn_id: str,
        capability_epoch: int,
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
        foreground_invocation_quiescence: Callable[
            [Mapping[str, object]], Mapping[str, object]
        ]
        | None = None,
        image_provider: Callable[
            [Mapping[str, object]], list[dict[str, str]]
        ] | None = None,
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
        self.foreground_invocation_quiescence = (
            foreground_invocation_quiescence
        )
        self.image_provider = image_provider
        self.learning_observer = learning_observer
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._dispatch_claim_lock = threading.Lock()

    def run_once(
        self,
        *,
        lease_ttl_ms: int = 30_000,
        on_claim: Callable[[], object] | None = None,
    ) -> dict[str, object] | None:
        claimed = self._claim_next_dispatch(lease_ttl_ms=lease_ttl_ms)
        if claimed is None:
            return None
        lease, dispatch = claimed
        if on_claim is not None:
            on_claim()
        runtime_intent_recorded = False

        def record_runtime_intent() -> None:
            nonlocal runtime_intent_recorded
            self.store.record_runtime_dispatch_intent(
                str(dispatch["dispatchId"]),
                now_ms=self.clock_ms(),
            )
            runtime_intent_recorded = True

        try:
            message = self.message_builder(dispatch)
            images = (
                self.image_provider(dispatch)
                if self.image_provider is not None
                else []
            )
            if images:
                runtime_receipt = self.runtime.dispatch_room(
                    dispatch,
                    message=message,
                    images=images,
                    lease_token=str(lease["leaseToken"]),
                    record_intent=record_runtime_intent,
                )
            else:
                runtime_receipt = self.runtime.dispatch_room(
                    dispatch,
                    message=message,
                    lease_token=str(lease["leaseToken"]),
                    record_intent=record_runtime_intent,
                )
        except Exception as exc:
            _LOG.exception(
                "Room Runtime dispatch failed before acknowledgement "
                "(dispatch_id=%s, session_id=%s, runtime_intent=%s)",
                dispatch.get("dispatchId"),
                dispatch.get("targetSessionId"),
                runtime_intent_recorded,
            )
            if not runtime_intent_recorded:
                failure = self.store.record_runtime_preflight_failure(
                    lease_token=str(lease["leaseToken"]),
                    now_ms=self.clock_ms(),
                )
                if (
                    failure.get("receiptKind") == "runtime_failed"
                    and failure.get("status") == "applied"
                    and self.revoke_session is not None
                ):
                    self.revoke_session(
                        str(dispatch["targetSessionId"]),
                        self.clock_ms(),
                    )
                return failure
            if self.revoke_session is not None:
                self.revoke_session(
                    str(dispatch["targetSessionId"]),
                    self.clock_ms(),
                )
            self._observe_failure(dispatch, "runtime_failed", exc)
            raise
        except BaseException as exc:
            if self.revoke_session is not None:
                self.revoke_session(
                    str(dispatch["targetSessionId"]),
                    self.clock_ms(),
                )
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

    def _claim_next_dispatch(
        self,
        *,
        lease_ttl_ms: int,
    ) -> tuple[dict[str, object], Mapping[str, object]] | None:
        if self.store.mode not in {"cohort", "test", "kernel_only"}:
            return None
        with self._dispatch_claim_lock:
            now_ms = self.clock_ms()
            pending = self.store.pending_dispatch(now_ms=now_ms)
            if pending is None:
                return None
            prepared: Mapping[str, object] = {}
            is_runtime_retry = pending.get("state") == "retry_wait"
            if self.prepare_dispatch is not None and not is_runtime_retry:
                prepared = self.prepare_dispatch(pending, now_ms)
                if not prepared.get("sessionId") or not prepared.get(
                    "manifestHash"
                ):
                    raise RoomKernelFenceError(
                        "managed Dispatch preparation returned no capability fence"
                    )
            if self.prepare_memory_context is not None and not is_runtime_retry:
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
                raise RoomKernelFenceError(
                    "outbox payload is not a Dispatch envelope"
                )
            return dict(lease), dispatch

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
                if (
                    not str(intent.get("turnId") or "").strip()
                    or int(intent.get("capabilityEpoch", -1)) < 0
                ):
                    raise RoomKernelFenceError(
                        "cancel intent has no active runtime receipt lineage"
                    )
                previous = intent.get("previousRuntimeReceipt")
                if _matches_terminal_host_kill(previous, intent):
                    runtime_receipt = dict(previous)
                else:
                    runtime_receipt = dict(
                        self.runtime.cancel_room(
                            cancel_id=str(intent["cancelId"]),
                            session_id=str(intent["sessionId"]),
                            root_id=str(intent["rootId"]),
                            dispatch_id=str(intent["dispatchId"]),
                            generation=int(intent["generation"]),
                            turn_id=str(intent["turnId"]),
                            capability_epoch=int(intent["capabilityEpoch"]),
                        )
                    )
                runtime_receipt = self._fence_host_kill_with_foreground_proof(
                    intent,
                    runtime_receipt,
                )
                if approval_cancellation is not None:
                    runtime_receipt["approvalCancellation"] = dict(
                        approval_cancellation
                    )
                self.store.complete_cancel(str(intent["cancelId"]), runtime_receipt, now_ms=self.clock_ms())
                receipts.append(dict(runtime_receipt))
            except Exception as exc:
                receipts.extend(
                    self.store.fail_cancel(
                        str(intent["cancelId"]),
                        f"{type(exc).__name__}: {exc}",
                        now_ms=self.clock_ms(),
                    )
                )
        return receipts

    def _fence_host_kill_with_foreground_proof(
        self,
        intent: Mapping[str, object],
        runtime_receipt: Mapping[str, object],
    ) -> dict[str, object]:
        receipt = dict(runtime_receipt)
        if not _matches_terminal_host_kill(receipt, intent):
            return receipt
        dispatch = self.store.dispatch(str(intent["dispatchId"]))
        request = {
            "rootId": str(intent["rootId"]),
            "taskId": str(dispatch["taskId"]),
            "dispatchId": str(intent["dispatchId"]),
            "ownerSessionId": str(intent["sessionId"]),
        }
        quiescence: Mapping[str, object] = {}
        if self.foreground_invocation_quiescence is not None:
            try:
                candidate = self.foreground_invocation_quiescence(request)
                if isinstance(candidate, Mapping):
                    quiescence = candidate
            except Exception as exc:
                quiescence = {
                    "schemaVersion": (
                        "wisdom-weasel.room-workspace-writer-quiescence.v1"
                    ),
                    **request,
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
        receipt["foregroundInvocationQuiescence"] = dict(quiescence)
        surfaces = {
            surface: dict(value) if isinstance(value, Mapping) else {}
            for surface, value in dict(
                receipt.get("cancellationSurfaces") or {}
            ).items()
        }
        terminal = _exact_foreground_quiescence(quiescence, request)
        foreground = (
            quiescence.get("foregroundMutatingInvocations")
            if isinstance(quiescence, Mapping)
            else None
        )
        pending_ids = []
        if isinstance(foreground, Mapping):
            for key in (
                "pendingInvocationReceiptIds",
                "hostTerminatedInvocationReceiptIds",
                "invalidExecutionReceiptIds",
            ):
                values = foreground.get(key)
                if isinstance(values, list):
                    pending_ids.extend(
                        str(value) for value in values if str(value).strip()
                    )
        if not pending_ids:
            pending_ids = [str(intent["sessionId"])]
        quiescence_revision = str(quiescence.get("receiptRevision") or "")
        host_termination = dict(receipt["runtimeHostTermination"])
        for surface in _SIDECAR_FOREGROUND_SURFACES:
            proof = surfaces.get(surface, {})
            proof.update(
                {
                    "schemaVersion": (
                        "wisdom-weasel.runtime-surface-termination-receipt.v1"
                    ),
                    "surface": surface,
                    "state": "terminated" if terminal else "unknown",
                    "targetIds": [] if terminal else list(dict.fromkeys(pending_ids)),
                    "terminationProof": {
                        "kind": "foreground_invocation_registry",
                        "killReceiptId": str(
                            host_termination.get("killReceiptId") or ""
                        ),
                        "writerQuiescenceReceiptRevision": quiescence_revision,
                    },
                }
            )
            surfaces[surface] = proof
        receipt["cancellationSurfaces"] = surfaces
        receipt["pendingTargets"] = [
            surface
            for surface in _RUNTIME_CANCEL_SURFACES
            if str(surfaces.get(surface, {}).get("state") or "")
            in {"requested", "acknowledged", "unknown"}
        ]
        return receipt

    def reconcile(self) -> list[dict[str, object]]:
        now_ms = self.clock_ms()
        receipts = self.store.reconcile_exhausted_cancels(now_ms=now_ms)
        receipts.extend(self.store.cancel_expired_roots(now_ms=now_ms))
        receipts.extend(self.store.reconcile_expired_leases(now_ms=now_ms))
        # Durable cancel delivery owns capability revocation too; doing it here
        # would double-fire the same session when the outbox is drained below.
        receipts.extend(self.drain_cancel_outbox())
        return receipts

    def recover_terminated_runtime_host(
        self,
        startup_targets: list[Mapping[str, object]],
        orphan_reconcile_receipts: list[Mapping[str, object]],
    ) -> dict[str, object]:
        """Fail and replace turns owned by the pre-restart Runtime lifecycle.

        The startup target list is captured before stopping/constructing the
        Pi Runtime and before this worker can run.  That lifecycle seam is the
        authority; an orphan-kill receipt only enriches the audit result.
        Empty in-memory Session sets are never used as evidence, and old
        Dispatch identities are never replayed.
        """

        targets = [dict(item) for item in startup_targets]
        empty = {
            "killReceiptId": "",
            "failedDispatchIds": [],
            "retriedDispatchIds": [],
            "blockedRootIds": [],
        }
        if not targets:
            return empty
        captured_at_ms = max(
            int(item.get("capturedAtMs") or 0) for item in targets
        )
        terminal_receipts = [
            dict(receipt)
            for receipt in orphan_reconcile_receipts
            if (
                receipt.get("schemaVersion")
                == "wisdom-weasel.runtime-host-kill-receipt.v1"
                and receipt.get("requestKind") == "orphan_reconcile"
                and receipt.get("state") == "terminated"
                and receipt.get("pendingTargets") == []
                and str(receipt.get("killReceiptId") or "").strip()
                and int(receipt.get("requestedAtMs") or 0)
                >= captured_at_ms
                and int(receipt.get("terminatedAtMs") or 0)
                >= int(receipt.get("requestedAtMs") or 0)
            )
        ]
        terminal = (
            max(
                terminal_receipts,
                key=lambda item: (
                    int(item.get("terminatedAtMs") or 0),
                    str(item.get("killReceiptId") or ""),
                ),
            )
            if terminal_receipts
            else None
        )
        kill_receipt_id = (
            str(terminal["killReceiptId"])
            if terminal is not None
            else ""
        )
        recovery_now_ms = self.clock_ms()
        failed_by_root: dict[str, list[dict[str, object]]] = {}
        for target in targets:
            dispatch_id = str(target.get("dispatchId") or "")
            root_id = str(target.get("rootId") or "")
            session_id = str(target.get("sessionId") or "")
            turn_id = str(target.get("runtimeTurnId") or "")
            source_event_id = (
                "runtime-lifecycle-recovery:"
                f"{dispatch_id}:{int(target.get('generation') or 0)}:"
                f"{int(target.get('capabilityEpoch') or 0)}:"
                f"{turn_id}:{int(target.get('dispatchAttempt') or 0)}"
            )
            try:
                was_running = (
                    self.store.dispatch(dispatch_id).get("state") == "running"
                )
                receipt = self.store.record_runtime_failure(
                    dispatch_id,
                    generation=int(target.get("generation") or 0),
                    source_event_id=source_event_id,
                    runtime_turn_id=turn_id,
                    dispatch_attempt=int(
                        target.get("dispatchAttempt") or 0
                    ),
                    now_ms=recovery_now_ms,
                    retryable=False,
                    had_tool_activity=True,
                    reason_code="runtime_host_restarted",
                )
            except RoomKernelFenceError as exc:
                _LOG.info(
                    "Room Host restart recovery skipped stale target "
                    "(dispatch_id=%s, session_id=%s, reason=%s)",
                    dispatch_id,
                    session_id,
                    exc,
                )
                continue
            if (
                receipt.get("receiptKind") != "runtime_failed"
                or receipt.get("status") not in {"applied", "noop"}
                or self.store.dispatch(dispatch_id).get("state") != "failed"
            ):
                continue
            recovered_target = dict(target)
            recovered_target["recoveryAtMs"] = int(
                receipt.get("createdAtMs") or recovery_now_ms
            )
            failed_by_root.setdefault(root_id, []).append(recovered_target)
            if not was_running:
                continue
            if self.invalidate_room_approvals is not None:
                try:
                    self.invalidate_room_approvals(
                        session_id,
                        root_id,
                        dispatch_id,
                        recovery_now_ms,
                    )
                except Exception:
                    _LOG.exception(
                        "Room Host restart approval cleanup failed "
                        "(dispatch_id=%s, session_id=%s)",
                        dispatch_id,
                        session_id,
                    )
            if self.revoke_session is not None:
                try:
                    self.revoke_session(session_id, recovery_now_ms)
                except Exception:
                    _LOG.exception(
                        "Room Host restart capability revocation failed "
                        "(dispatch_id=%s, session_id=%s)",
                        dispatch_id,
                        session_id,
                    )

        retried_dispatch_ids: list[str] = []
        blocked_root_ids: list[str] = []
        for root_id in sorted(failed_by_root):
            root = self.store.root(root_id)
            failed_dispatch_ids = sorted(
                str(item["dispatchId"])
                for item in failed_by_root[root_id]
            )
            lifecycle_lineage = [
                (
                    f"{item['dispatchId']}:{int(item.get('generation') or 0)}:"
                    f"{int(item.get('capabilityEpoch') or 0)}:"
                    f"{item['runtimeTurnId']}:"
                    f"{int(item.get('dispatchAttempt') or 0)}"
                )
                for item in failed_by_root[root_id]
            ]
            lifecycle_source_id = (
                "runtime-lifecycle:sha256:"
                + hashlib.sha256(
                    (root_id + "\n" + "\n".join(sorted(lifecycle_lineage))).encode(
                        "utf-8"
                    )
                ).hexdigest()
            )
            command_id = f"runtime-host-restart-retry:{lifecycle_source_id}"
            command = {
                "schemaVersion": "wisdom-weasel.room-kernel-command.v1",
                "commandId": command_id,
                "rootId": root_id,
                "roomId": str(root["roomId"]),
                "commandKind": "retry_root",
                "targetKind": "root",
                "targetId": root_id,
                "sourceKind": "runtime_host_reconcile",
                "sourceId": lifecycle_source_id,
                "idempotencyKey": command_id,
                "generation": int(root["generation"]),
                "payload": {
                    "reasonCode": "runtime_host_restarted",
                    "failedDispatchIds": failed_dispatch_ids,
                    "lifecycleSourceId": lifecycle_source_id,
                },
                "createdAtMs": max(
                    int(item.get("recoveryAtMs") or recovery_now_ms)
                    for item in failed_by_root[root_id]
                ),
            }
            try:
                retried = self.apply_control_command(command)[
                    "kernelReceipt"
                ]
            except RoomKernelFenceError as exc:
                blocked_root_ids.append(root_id)
                _LOG.warning(
                    "Room Host restart retry remained blocked "
                    "(root_id=%s, reason=%s)",
                    root_id,
                    exc,
                )
                continue
            details = retried.get("details")
            if isinstance(details, Mapping):
                retried_dispatch_ids.extend(
                    str(value)
                    for value in details.get("retriedDispatchIds") or []
                )
        return {
            "killReceiptId": kill_receipt_id,
            "failedDispatchIds": sorted(
                {
                    str(item["dispatchId"])
                    for items in failed_by_root.values()
                    for item in items
                }
            ),
            "retriedDispatchIds": sorted(set(retried_dispatch_ids)),
            "blockedRootIds": sorted(set(blocked_root_ids)),
        }


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

    def create_task(
        self,
        task: Mapping[str, object],
        *,
        now_ms: int,
    ) -> dict[str, object]:
        return self.store.create_task(task, now_ms=now_ms)

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


def _default_dispatch_message(dispatch: Mapping[str, object]) -> str:
    # Dispatch identity, requirements and Room facts are already carried by
    # the fenced provider-only projection. The Session receives only a stable
    # private trigger, never the transport envelope or its internal IDs.
    recovery = (
        "这是恢复轮次：沿用上一轮已经完成的内容，只补齐缺少的结果或正式回复；"
        "不要从头重做。"
        if int(dispatch.get("attempt") or 0) > 0
        else ""
    )
    return (
        recovery
        + "继续当前 Room 工作卡片；本轮要做什么、由谁负责，以 Room Context 为准。"
        "需要核对自己的部分、验收条件或伙伴状态时，先调用 room_state。"
        "AC-1 表示 room_state 验收清单中的第一项，AC-2 表示第二项，以此类推。"
        "结束本轮只调用 room_commit：evidence.acceptance 只能填写 room_state "
        "返回的 AC-1、AC-2 等验收短名；每项只放直接支持它的最小 refs 集合。"
        "refs 必须原样复制最新 room_state 或成功工具结果返回的完整 evidenceRef，"
        "不得改写、拼接或猜测；不要填写内部 criterionId，也不要自行宣布已通过"
        "或最终裁决，服务端会根据实际结果判断。summary、evidence 和接手指令放在"
        "结构化私有字段；publicSummary 用自然语言写给用户，不暴露这些内部字段或"
        "私下推理。"
    )


_MAX_ROOM_DISPATCH_DELIVERY_THREADS = 32


def _runtime_dispatch_concurrency_limit(worker: RoomKernelWorker) -> int:
    status_provider = getattr(
        getattr(worker, "runtime", None),
        "runtime_status",
        None,
    )
    if not callable(status_provider):
        return 1
    try:
        status = status_provider()
    except Exception:
        return 1
    capabilities = status.get("capabilities") if isinstance(status, Mapping) else None
    raw_limit = (
        capabilities.get("maxSessions")
        if isinstance(capabilities, Mapping)
        else None
    )
    if isinstance(raw_limit, bool):
        return 1
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return 1
    return max(1, min(_MAX_ROOM_DISPATCH_DELIVERY_THREADS, limit))


class RoomKernelWorkerLoop:
    """Stoppable cohort worker with bounded concurrent Runtime delivery."""

    def __init__(
        self,
        worker: RoomKernelWorker,
        *,
        on_change: Callable[[], object] | None = None,
        poll_seconds: float = 0.25,
        max_concurrent_dispatches: int | None = None,
    ) -> None:
        self.worker = worker
        self.on_change = on_change or (lambda: None)
        self.poll_seconds = max(0.01, float(poll_seconds))
        concurrency = (
            _runtime_dispatch_concurrency_limit(worker)
            if max_concurrent_dispatches is None
            else int(max_concurrent_dispatches)
        )
        self.max_concurrent_dispatches = max(
            1,
            min(_MAX_ROOM_DISPATCH_DELIVERY_THREADS, concurrency),
        )
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._delivery_lock = threading.Lock()
        self._delivery_threads: set[threading.Thread] = set()
        self._delivery_sequence = 0
        self._delivery_probe_active = False
        self._delivery_changed = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if not kernel_owns_room_execution(self.worker.store.mode) or self.running:
            return False
        with self._delivery_lock:
            if self._delivery_threads:
                return False
            self._delivery_probe_active = False
            self._delivery_changed = False
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
        deadline = time.monotonic() + max(1.0, self.poll_seconds * 4)
        with self._delivery_lock:
            deliveries = tuple(self._delivery_threads)
        for delivery in deliveries:
            if delivery is threading.current_thread():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            delivery.join(timeout=remaining)

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                # Preserve the old lease-expiry semantics: while a Runtime ACK
                # is outstanding, its in-memory owner is still active and the
                # reconciliation pass must not expire that exact lease.
                changed = (
                    False
                    if self._delivery_in_flight()
                    else bool(self.worker.reconcile())
                )
                changed = self._take_delivery_changed() or changed
                if changed:
                    self.on_change()
                self._start_delivery_probe()
            except Exception:
                # A leased but unacknowledged effect is intentionally left for
                # expiry reconciliation; it must never be replayed blindly.
                # Projection callbacks are part of the same recoverable
                # iteration: one stale read model must not kill the worker.
                _LOG.exception("Room Kernel worker iteration failed")
            self._wake.wait(self.poll_seconds)
            self._wake.clear()

    def _delivery_in_flight(self) -> bool:
        with self._delivery_lock:
            return bool(self._delivery_threads)

    def _take_delivery_changed(self) -> bool:
        with self._delivery_lock:
            changed = self._delivery_changed
            self._delivery_changed = False
            return changed

    def _start_delivery_probe(self) -> None:
        with self._delivery_lock:
            if (
                self._stop.is_set()
                or self._delivery_probe_active
                or len(self._delivery_threads)
                >= self.max_concurrent_dispatches
            ):
                return
            self._delivery_sequence += 1
            delivery = threading.Thread(
                target=self._deliver_once,
                name=(
                    "rag-ime-room-kernel-delivery-"
                    f"{self._delivery_sequence}"
                ),
                daemon=True,
            )
            self._delivery_probe_active = True
            self._delivery_threads.add(delivery)
        try:
            delivery.start()
        except BaseException:
            with self._delivery_lock:
                self._delivery_threads.discard(delivery)
                self._delivery_probe_active = False
            raise

    def _deliver_once(self) -> None:
        claimed = False
        receipt: dict[str, object] | None = None

        def on_claim() -> None:
            nonlocal claimed
            if claimed:
                return
            claimed = True
            with self._delivery_lock:
                self._delivery_probe_active = False
            # A durable lease now owns one slot. Probe the next ready Dispatch
            # without waiting for this Host/session-open acknowledgement.
            self._wake.set()

        try:
            if not self._stop.is_set():
                receipt = self.worker.run_once(on_claim=on_claim)
            if receipt is not None:
                with self._delivery_lock:
                    self._delivery_changed = True
        except Exception:
            _LOG.exception("Room Kernel worker delivery failed")
        finally:
            current = threading.current_thread()
            with self._delivery_lock:
                self._delivery_threads.discard(current)
                if not claimed:
                    self._delivery_probe_active = False
            if claimed or receipt is not None:
                self._wake.set()
