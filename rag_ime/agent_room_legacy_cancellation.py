from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from .agent_room_cancellation_proofs import (
    _aggregate_session_abort_surfaces,
    _merge_root_surface,
    _root_resource_surface,
)
from .agent_room_turn_registry import RoomTurnRegistry


class LegacyCancellationHost(Protocol):
    rooms: Any
    room_events: Any
    delegation: Any
    room_intercom: Any
    wake_schedules: Any
    room_turns: RoomTurnRegistry

    def abort(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]: ...

    def _cancel_room_turn(
        self,
        session_id: str,
        room_turn_id: str,
    ) -> None: ...

    def _room_topic_for_turn(self, room_turn_id: str) -> str: ...


class RoomLegacyCancellationService:
    """Root cancellation compatibility for pre-Kernel Room turns."""

    def __init__(self, host: LegacyCancellationHost) -> None:
        self.host = host

    def abort_turn(
        self,
        room_id: str,
        *,
        room_turn_id: str,
    ) -> dict[str, object]:
        room = self.host.rooms.get(room_id)
        events = [
            event
            for event in self.host.rooms.list_events(room_id, after_sequence=0, limit=2000)
            if str(event.get("turnId") or "") == room_turn_id
        ]
        if not any(str(event.get("eventType") or "") == "user_message" for event in events):
            raise ValueError("Room turn does not belong to this Room")

        participants = {
            str(item.get("id") or ""): dict(item)
            for item in room.get("participants", [])
            if isinstance(item, Mapping) and str(item.get("id") or "")
        }
        targets: dict[str, dict[str, str]] = {}
        for event in events:
            if str(event.get("eventType") or "") != "route_decision":
                continue
            data = event.get("payload")
            data = data if isinstance(data, Mapping) else {}
            participant_id = str(
                event.get("participantId")
                or data.get("targetParticipantId")
                or ""
            )
            participant = participants.get(participant_id, {})
            session_id = str(
                event.get("sourceSessionId")
                or data.get("targetSessionId")
                or participant.get("sessionId")
                or ""
            )
            if not participant_id or not session_id:
                continue
            targets[participant_id] = {
                "participantId": participant_id,
                "sessionId": session_id,
                "dispatchId": str(data.get("dispatchId") or ""),
            }

        def _resolve_participant_id(session_id: str) -> str | None:
            participant = self.host.rooms.participant_for_session(
                session_id,
                active_only=False,
            )
            if participant is None:
                return None
            return str(participant.get("id") or "")

        # resolve runs inside the registry lock, keeping participant lookup
        # and mapping traversal one critical section as the inline loops were.
        for participant_id, session_id, dispatch_id in (
            self.host.room_turns.turn_targets(
                room_turn_id,
                resolve=_resolve_participant_id,
            )
        ):
            targets.setdefault(
                participant_id,
                {
                    "participantId": participant_id,
                    "sessionId": session_id,
                    "dispatchId": dispatch_id,
                },
            )

        terminal_participant_ids = {
            str(event.get("participantId") or "")
            for event in events
            if str(event.get("eventType") or "") in {"turn_completed", "turn_failed"}
            and str(event.get("participantId") or "")
        }
        active_targets = [
            target
            for target in targets.values()
            if target["participantId"] not in terminal_participant_ids
        ]
        if not active_targets:
            return {
                "schemaVersion": "rag-ime.agent-room-abort.v1",
                "ok": True,
                "roomId": room_id,
                "roomTurnId": room_turn_id,
                "status": "already_terminal",
                "cancellationReceiptId": "",
                "surfaces": {},
                "pendingTargets": [],
            }

        cancellation_receipt_id = f"room-cancel:{uuid.uuid4()}"
        self.host.room_turns.record_cancellation(
            room_turn_id,
            cancellation_receipt_id,
        )
        self.host.room_events.publish(
            room_id=room_id,
            event_type="participant_status",
            payload={
                "status": "cancellation_requested",
                "rootId": room_turn_id,
                "cancellationReceiptId": cancellation_receipt_id,
            },
            turn_id=room_turn_id,
            topic_id=self.host._room_topic_for_turn(room_turn_id),
        )

        primary_session_ids = {
            target["sessionId"] for target in active_targets if target["sessionId"]
        }
        chain_session_ids = set(primary_session_ids)
        delegation_receipts: list[dict[str, object]] = []
        delegation_pending: list[str] = []
        delegation_queue = deque(sorted(primary_session_ids))
        visited_delegation_parents: set[str] = set()
        while delegation_queue:
            parent_session_id = delegation_queue.popleft()
            if parent_session_id in visited_delegation_parents:
                continue
            visited_delegation_parents.add(parent_session_id)
            for batch in self.host.delegation.store.list_batches(
                parent_session_id=parent_session_id,
                limit=200,
            ):
                active_runs = [
                    run
                    for run in batch.get("runs", [])
                    if isinstance(run, Mapping)
                    and str(run.get("state") or "") in {"queued", "running"}
                ]
                if not active_runs:
                    continue
                for run in active_runs:
                    child_session_id = str(run.get("childSessionId") or "")
                    if child_session_id and child_session_id not in chain_session_ids:
                        chain_session_ids.add(child_session_id)
                        delegation_queue.append(child_session_id)
                try:
                    receipt = self.host.delegation.abort(
                        parent_session_id,
                        {"batchId": str(batch.get("id") or "")},
                    )
                except Exception as exc:
                    delegation_pending.append(
                        f"{batch.get('id') or 'delegation'}:{_public_error(exc)}"
                    )
                else:
                    delegation_receipts.append(dict(receipt))
                    returned_batch = receipt.get("batch")
                    if (
                        isinstance(returned_batch, Mapping)
                        and any(
                            isinstance(run, Mapping)
                            and str(run.get("state") or "") in {"queued", "running"}
                            for run in returned_batch.get("runs", [])
                        )
                    ):
                        delegation_pending.append(str(batch.get("id") or "delegation"))

        cancelled_wakes: list[str] = []
        wake_pending: list[str] = []
        for _pass in range(4):
            added_session = False
            for schedule in self.host.wake_schedules.list(limit=500):
                schedule_id = str(schedule.get("id") or "")
                if not schedule_id or str(schedule.get("status") or "") not in {
                    "scheduled",
                    "paused",
                    "running",
                }:
                    continue
                if (
                    str(schedule.get("targetSessionId") or "") not in chain_session_ids
                    and str(schedule.get("createdBySessionId") or "") not in chain_session_ids
                ):
                    continue
                if schedule_id in cancelled_wakes:
                    continue
                latest = schedule.get("latestRun")
                latest = latest if isinstance(latest, Mapping) else {}
                wake_session_id = str(latest.get("sessionId") or "")
                if wake_session_id and wake_session_id not in chain_session_ids:
                    chain_session_ids.add(wake_session_id)
                    primary_session_ids.add(wake_session_id)
                    delegation_queue.append(wake_session_id)
                    added_session = True
                try:
                    self.host.wake_schedules.cancel_for_root(
                        schedule_id,
                        reason=f"Cancelled with Room root {room_turn_id}",
                    )
                except Exception as exc:
                    wake_pending.append(f"{schedule_id}:{_public_error(exc)}")
                else:
                    cancelled_wakes.append(schedule_id)
            while delegation_queue:
                parent_session_id = delegation_queue.popleft()
                if parent_session_id in visited_delegation_parents:
                    continue
                visited_delegation_parents.add(parent_session_id)
                for batch in self.host.delegation.store.list_batches(
                    parent_session_id=parent_session_id,
                    limit=200,
                ):
                    active_runs = [
                        run
                        for run in batch.get("runs", [])
                        if isinstance(run, Mapping)
                        and str(run.get("state") or "") in {"queued", "running"}
                    ]
                    if not active_runs:
                        continue
                    for run in active_runs:
                        child_session_id = str(run.get("childSessionId") or "")
                        if child_session_id and child_session_id not in chain_session_ids:
                            chain_session_ids.add(child_session_id)
                            delegation_queue.append(child_session_id)
                    try:
                        delegation_receipts.append(
                            dict(
                                self.host.delegation.abort(
                                    parent_session_id,
                                    {"batchId": str(batch.get("id") or "")},
                                )
                            )
                        )
                    except Exception as exc:
                        delegation_pending.append(
                            f"{batch.get('id') or 'delegation'}:{_public_error(exc)}"
                        )
            if not added_session:
                break

        intercom_pending: list[str] = []
        try:
            cancelled_intercom = self.host.room_intercom.store.cancel_for_sessions(
                chain_session_ids,
                reason=f"Cancelled with Room root {room_turn_id}",
            )
        except Exception as exc:
            cancelled_intercom = []
            intercom_pending.append(_public_error(exc))

        session_abort_receipts: list[dict[str, object]] = []
        session_abort_errors: list[str] = []
        with ThreadPoolExecutor(
            max_workers=max(1, min(4, len(primary_session_ids)))
        ) as executor:
            pending = {
                executor.submit(self.host.abort, session_id): session_id
                for session_id in sorted(primary_session_ids)
            }
            for future in as_completed(pending):
                session_id = pending[future]
                try:
                    session_abort_receipts.append(dict(future.result()))
                except Exception as exc:
                    session_abort_errors.append(f"{session_id}:{_public_error(exc)}")

        surfaces = _aggregate_session_abort_surfaces(
            session_abort_receipts,
            expected_session_ids=primary_session_ids,
            errors=session_abort_errors,
        )
        surfaces["intercom"] = _root_resource_surface(
            "intercom",
            "unknown" if intercom_pending else "terminated",
            [str(item.get("id") or "") for item in cancelled_intercom],
            intercom_pending,
        )
        surfaces["delegation"] = _root_resource_surface(
            "delegation",
            "requested" if delegation_pending else "terminated",
            [
                str(receipt.get("batch", {}).get("id") or "")
                for receipt in delegation_receipts
                if isinstance(receipt.get("batch"), Mapping)
            ],
            delegation_pending,
        )
        surfaces["timer"] = _merge_root_surface(
            surfaces.get("timer"),
            _root_resource_surface(
                "timer",
                "unknown" if wake_pending else "terminated",
                cancelled_wakes,
                wake_pending,
            ),
        )
        surfaces["late_write"] = _root_resource_surface(
            "late_write",
            "terminated",
            [room_turn_id],
            [],
        )
        pending_targets = [
            surface
            for surface, proof in surfaces.items()
            if str(proof.get("state") or "") != "terminated"
        ]

        if not pending_targets:
            for target in active_targets:
                self.host.room_events.publish(
                    room_id=room_id,
                    event_type="turn_completed",
                    payload={
                        "status": "aborted",
                        "aborted": True,
                        "rootId": room_turn_id,
                        "dispatchId": target["dispatchId"],
                        "cancellationReceiptId": cancellation_receipt_id,
                        "pendingTargets": [],
                    },
                    turn_id=room_turn_id,
                    participant_id=target["participantId"],
                    source_session_id=target["sessionId"],
                    topic_id=self.host._room_topic_for_turn(room_turn_id),
                )
                self.host._cancel_room_turn(target["sessionId"], room_turn_id)
            self.host.room_turns.release_priority(
                primary_session_ids
            )

        final_event = self.host.room_events.publish(
            room_id=room_id,
            event_type="participant_status",
            payload={
                "status": (
                    "cancellation_pending"
                    if pending_targets
                    else "cancellation_applied"
                ),
                "rootId": room_turn_id,
                "cancellationReceiptId": cancellation_receipt_id,
                "pendingTargets": pending_targets,
                "surfaces": surfaces,
            },
            turn_id=room_turn_id,
            topic_id=self.host._room_topic_for_turn(room_turn_id),
        )
        return {
            "schemaVersion": "rag-ime.agent-room-abort.v1",
            "ok": not pending_targets,
            "roomId": room_id,
            "roomTurnId": room_turn_id,
            "status": "terminated" if not pending_targets else "cancellation_pending",
            "cancellationReceiptId": cancellation_receipt_id,
            "surfaces": surfaces,
            "pendingTargets": pending_targets,
            "sessionReceipts": session_abort_receipts,
            "event": final_event,
        }


def _public_error(error: BaseException) -> str:
    text = " ".join(str(error).split())
    return text[:240] or error.__class__.__name__
