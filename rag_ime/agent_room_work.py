from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence

from .agent_room_work_base import *  # noqa: F403 - compatibility re-export
from . import agent_room_work_base as _base


_timestamp = _base._timestamp
_required_text = _base._required_text
_optional_text = _base._optional_text
_text_list = _base._text_list
_bounded = _base._bounded
_wake_condition = _base._wake_condition
_participant_for_session = _base._participant_for_session
work_item_payload = _base.work_item_payload
_BaseAgentRoomWorkStore = _base.AgentRoomWorkStore


class AgentRoomWorkAttemptChanged(RuntimeError):
    """A late Partner result targeted an obsolete WorkItem attempt."""


class AgentRoomWorkStore(_BaseAgentRoomWorkStore):
    """Authoritative WorkItem lifecycle layered on the durable Room ledger."""

    def submit_attempt(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        attempt_id: str,
        expected_revision: int,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Submit one Partner result only while its exact attempt still owns the item."""

        timestamp = _timestamp(updated_at_ms)
        work_id = _required_text(payload.get("workId"), "workId", maximum=240)
        summary = _required_text(
            payload.get("resultSummary"),
            "resultSummary",
            maximum=4_000,
        )
        artifact_refs = _text_list(
            payload.get("artifactRefs"),
            "artifactRefs",
            maximum_items=16,
            maximum_length=1_000,
        )
        evidence_refs = _text_list(
            payload.get("evidenceRefs"),
            "evidenceRefs",
            maximum_items=24,
            maximum_length=1_000,
        )
        if not artifact_refs and not evidence_refs:
            raise ValueError(
                "work submission requires at least one artifactRefs or evidenceRefs entry"
            )
        normalized_attempt_id = _required_text(
            attempt_id,
            "attempt_id",
            maximum=320,
        )
        normalized_revision = int(expected_revision)
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._owned_row(conn, work_id, actor)
            self._require_attempt(
                row,
                attempt_id=normalized_attempt_id,
                expected_revision=normalized_revision,
            )
            if str(row["state"]) not in {"active", "blocked"}:
                raise ValueError("only active or blocked work may be submitted")
            open_children = conn.execute(
                """
                SELECT COUNT(*) FROM agent_room_work_items
                WHERE parent_work_id = ?
                  AND state IN ('queued', 'active', 'review', 'blocked')
                """,
                (work_id,),
            ).fetchone()
            if int(open_children[0] if open_children else 0) > 0:
                raise ValueError(
                    "Room work cannot be submitted while child WorkItems are open"
                )
            cursor = conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'review', result_summary = ?, artifact_refs_json = ?,
                    evidence_refs_json = ?, blocker_json = '{}', updated_at_ms = ?
                WHERE id = ? AND revision = ? AND accepted_turn_id = ?
                  AND state IN ('active', 'blocked')
                """,
                (
                    summary,
                    json.dumps(artifact_refs, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(evidence_refs, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    work_id,
                    normalized_revision,
                    normalized_attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRoomWorkAttemptChanged(
                    "WorkItem attempt changed before Partner result submission"
                )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="submitted",
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
                payload={
                    "attemptId": normalized_attempt_id,
                    "revision": normalized_revision,
                },
            )
        return work_item_payload(row)


    def block_attempt(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        attempt_id: str,
        expected_revision: int,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Record a bounded Partner failure without accepting a late attempt."""

        timestamp = _timestamp(updated_at_ms)
        work_id = _required_text(payload.get("workId"), "workId", maximum=240)
        blocker = {
            "reason": _required_text(payload.get("reason"), "reason", maximum=2_000),
            "nextStep": _required_text(
                payload.get("nextStep") or "resume, reassign, fail, or abandon",
                "nextStep",
                maximum=2_000,
            ),
            "wakeCondition": _wake_condition(payload.get("wakeCondition")),
            "attemptId": _required_text(attempt_id, "attempt_id", maximum=320),
            "revision": int(expected_revision),
        }
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._owned_row(conn, work_id, actor)
            self._require_attempt(
                row,
                attempt_id=str(blocker["attemptId"]),
                expected_revision=int(blocker["revision"]),
            )
            if str(row["state"]) != "active":
                raise ValueError("only active work may be blocked by an attempt")
            cursor = conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'blocked', blocker_json = ?, updated_at_ms = ?
                WHERE id = ? AND revision = ? AND accepted_turn_id = ?
                  AND state = 'active'
                """,
                (
                    json.dumps(blocker, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    work_id,
                    int(blocker["revision"]),
                    str(blocker["attemptId"]),
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRoomWorkAttemptChanged(
                    "WorkItem attempt changed before Partner failure settlement"
                )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="blocked",
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
                payload={
                    "attemptId": str(blocker["attemptId"]),
                    "revision": int(blocker["revision"]),
                },
            )
        return work_item_payload(row)


    def resume(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Resume the same blocked WorkItem; the next dispatch claims a new attempt."""

        timestamp = _timestamp(updated_at_ms)
        work_id = _required_text(payload.get("workId"), "workId", maximum=240)
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._row(conn, work_id)
            self._require_owner_or_accountable(row, str(actor["id"]))
            if str(row["state"]) != "blocked":
                raise ValueError("only blocked work may be resumed")
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'active', blocker_json = '{}', accepted_turn_id = '',
                    updated_at_ms = ?
                WHERE id = ?
                """,
                (timestamp, work_id),
            )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="resumed",
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
            )
        return work_item_payload(row)


    def fail(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Explicitly terminate one open WorkItem as failed."""

        return self._terminate_open_work(
            session_id,
            payload,
            state="failed",
            event_type="failed",
            updated_at_ms=updated_at_ms,
        )


    def abandon(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Explicitly abandon optional work without marking the whole Room failed."""

        return self._terminate_open_work(
            session_id,
            payload,
            state="cancelled",
            event_type="abandoned",
            updated_at_ms=updated_at_ms,
        )


    def require_dependencies_done(
        self,
        room_id: str,
        work_ids: Sequence[object],
    ) -> list[dict[str, object]]:
        """Return exact dependency evidence only when every item is accepted."""

        normalized_room_id = _required_text(room_id, "room_id", maximum=320)
        normalized_ids = _text_list(
            work_ids,
            "dependsOnWorkItemIds",
            maximum_items=16,
            maximum_length=320,
        )
        if not normalized_ids:
            return []
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("dependsOnWorkItemIds must be unique")
        with self._connect() as conn:
            rows = [self._row(conn, work_id) for work_id in normalized_ids]
        values = [work_item_payload(row) for row in rows]
        if any(str(item["roomId"]) != normalized_room_id for item in values):
            raise ValueError("Room dependency belongs to a different Room")
        incomplete = [
            str(item["id"])
            for item in values
            if str(item["state"]) != "done"
        ]
        if incomplete:
            raise ValueError(
                "Room dependencies are not accepted: " + ", ".join(incomplete)
            )
        return values


    def open_for_root(
        self,
        *,
        room_id: str,
        root_turn_id: str,
    ) -> list[dict[str, object]]:
        """List unresolved WorkItems currently attached to one public Root."""

        normalized_room_id = _required_text(room_id, "room_id", maximum=320)
        normalized_root_id = _required_text(
            root_turn_id,
            "root_turn_id",
            maximum=320,
        )
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_room_work_items
                WHERE room_id = ? AND root_turn_id = ?
                  AND state IN ('queued', 'active', 'review', 'blocked')
                ORDER BY updated_at_ms ASC, id ASC
                """,
                (normalized_room_id, normalized_root_id),
            ).fetchall()
        return [work_item_payload(row) for row in rows]


    def reassign(
        self,
        work_id: str,
        *,
        actor_participant_id: str,
        current_owner_participant_id: str,
        reason: str = "",
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        actor_id = _required_text(actor_participant_id, "actor_participant_id", maximum=320)
        owner_id = _required_text(
            current_owner_participant_id,
            "current_owner_participant_id",
            maximum=320,
        )
        timestamp = _timestamp(updated_at_ms)
        with self._connect(immediate=True) as conn:
            row = self._row(conn, work_id)
            if str(row["state"]) not in {"active", "review", "blocked"}:
                raise ValueError("only active, review, or blocked work items can be reassigned")
            room_id = str(row["room_id"])
            participant_rows = conn.execute(
                """
                SELECT id, participant_status FROM agent_room_participants
                WHERE room_id = ? AND id IN (?, ?)
                """,
                (room_id, actor_id, owner_id),
            ).fetchall()
            statuses = {str(value["id"]): str(value["participant_status"]) for value in participant_rows}
            if statuses.get(actor_id) != "active" or statuses.get(owner_id) != "active":
                raise ValueError("reassignment actor and owner must be active room participants")
            previous_owner_id = str(row["current_owner_participant_id"])
            if actor_id not in {previous_owner_id, str(row["accountable_participant_id"])}:
                raise ValueError("only the current owner or accountable participant may reassign work")
            if previous_owner_id == owner_id:
                return work_item_payload(row)
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET current_owner_participant_id = ?, offered_to_participant_id = NULL,
                    assignment_key = ?, accepted_turn_id = '', updated_at_ms = ?
                WHERE id = ?
                """,
                (
                    owner_id,
                    f"{room_id}:{work_id}:assignment:{uuid.uuid4()}",
                    timestamp,
                    work_id,
                ),
            )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="assigned",
                actor_participant_id=actor_id,
                created_at_ms=timestamp,
                payload={
                    "reason": _bounded(reason, 500) or "reassignment",
                    "previousOwnerParticipantId": previous_owner_id,
                    "currentOwnerParticipantId": owner_id,
                },
            )
        return work_item_payload(row)


    def claim_dispatch(
        self,
        work_id: str,
        *,
        room_id: str,
        owner_participant_id: str,
        assignment_key: str,
        previous_accepted_turn_id: str,
        room_turn_id: str,
        root_turn_id: str = "",
        claimed_at_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = _timestamp(claimed_at_ms)
        public_root_id = _optional_text(root_turn_id, maximum=320) or str(room_turn_id)
        with self._connect(immediate=True) as conn:
            row = self._row(conn, work_id)
            if str(row["room_id"]) != str(room_id):
                raise ValueError("work item does not belong to this room")
            if str(row["state"]) not in AUTHORITATIVE_WORK_STATES:
                raise ValueError("only active or review work items can be dispatched")
            if (
                str(row["current_owner_participant_id"]) != str(owner_participant_id)
                or str(row["assignment_key"]) != str(assignment_key)
                or str(row["accepted_turn_id"] or "") != str(previous_accepted_turn_id or "")
            ):
                raise AgentRoomWorkAssignmentChanged("WorkItem assignment changed before dispatch")
            cursor = conn.execute(
                """
                UPDATE agent_room_work_items
                SET accepted_turn_id = ?, root_turn_id = ?, updated_at_ms = ?
                WHERE id = ? AND room_id = ? AND current_owner_participant_id = ?
                  AND assignment_key = ? AND accepted_turn_id = ?
                """,
                (
                    str(room_turn_id),
                    public_root_id,
                    timestamp,
                    work_id,
                    room_id,
                    owner_participant_id,
                    assignment_key,
                    str(previous_accepted_turn_id or ""),
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRoomWorkAssignmentChanged("WorkItem assignment changed before dispatch")
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="accepted",
                actor_participant_id=str(owner_participant_id),
                created_at_ms=timestamp,
            )
        return work_item_payload(row)


    def _review_transition(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        accept: bool,
        updated_at_ms: int | None,
    ) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        work_id = _required_text(payload.get("workId"), "workId", maximum=240)
        feedback = _optional_text(payload.get("reason"), maximum=2_000)
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._row(conn, work_id)
            self._require_reviewer(conn, row, str(actor["id"]))
            if str(row["state"]) != "review":
                raise ValueError("Room work must be in review")
            if accept:
                conn.execute(
                    """
                    UPDATE agent_room_work_items
                    SET state = 'done', blocker_json = '{}', updated_at_ms = ?,
                        completed_at_ms = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, work_id),
                )
                event_type = "completed"
            else:
                if not feedback:
                    raise ValueError("revision return requires a concrete reason")
                revision = int(row["revision"]) + 1
                if revision > MAX_REVISIONS:
                    raise ValueError(
                        "Room revision limit is 2; escalate to the accountable participant"
                    )
                conn.execute(
                    """
                    UPDATE agent_room_work_items
                    SET state = 'active', revision = ?, blocker_json = ?,
                        accepted_turn_id = '', updated_at_ms = ?
                    WHERE id = ?
                    """,
                    (
                        revision,
                        json.dumps(
                            {"reviewFeedback": feedback},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        timestamp,
                        work_id,
                    ),
                )
                event_type = "returned"
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type=event_type,
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
            )
        result = work_item_payload(row)
        self._notify_terminal(result)
        return result


    def _terminate_open_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        state: str,
        event_type: str,
        updated_at_ms: int | None,
    ) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        work_id = _required_text(payload.get("workId"), "workId", maximum=240)
        reason = _required_text(payload.get("reason"), "reason", maximum=2_000)
        next_step = _optional_text(payload.get("nextStep"), maximum=2_000)
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._row(conn, work_id)
            self._require_owner_or_accountable(row, str(actor["id"]))
            if str(row["state"]) not in OPEN_WORK_STATES:
                raise ValueError("only open work may be terminated")
            blocker = {
                "reason": reason,
                "nextStep": next_step,
                "terminalDecision": event_type,
            }
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = ?, blocker_json = ?, accepted_turn_id = '',
                    updated_at_ms = ?, completed_at_ms = ?
                WHERE id = ?
                """,
                (
                    state,
                    json.dumps(blocker, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    timestamp,
                    work_id,
                ),
            )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type=event_type,
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
            )
        result = work_item_payload(row)
        self._notify_terminal(result)
        return result


    def _require_attempt(
        row: sqlite3.Row,
        *,
        attempt_id: str,
        expected_revision: int,
    ) -> None:
        if (
            int(row["revision"]) != int(expected_revision)
            or str(row["accepted_turn_id"] or "") != str(attempt_id)
        ):
            raise AgentRoomWorkAttemptChanged(
                "WorkItem revision or attempt changed before settlement"
            )


    def _require_owner_or_accountable(
        row: sqlite3.Row,
        participant_id: str,
    ) -> None:
        if participant_id not in {
            str(row["current_owner_participant_id"]),
            str(row["accountable_participant_id"]),
        }:
            raise ValueError(
                "only the current owner or accountable participant may change this WorkItem"
            )

