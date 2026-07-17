from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations


_WORK_STATES = frozenset(
    {"queued", "active", "review", "blocked", "done", "failed", "cancelled"}
)
_AUTHORITATIVE_STATES = frozenset({"active", "review"})


class AgentRoomWorkItemNotFound(KeyError):
    pass


class AgentRoomWorkAssignmentChanged(RuntimeError):
    """Raised when dispatch races with a formal WorkItem reassignment."""


class AgentRoomWorkStore:
    """Durable WorkItem ownership and its formal assignment history."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def create(
        self,
        *,
        room_id: str,
        objective: str,
        expected_output: str,
        current_owner_participant_id: str,
        created_by_participant_id: str,
        client_message_id: str,
        accountable_participant_id: str = "",
        topic_id: str = "",
        root_turn_id: str = "",
        parent_work_id: str = "",
        acceptance_criteria: Sequence[object] = (),
        state: str = "active",
        depth: int = 1,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_room_id = _required_text(room_id, "room_id", maximum=320)
        normalized_objective = _required_text(objective, "objective", maximum=8_000)
        normalized_expected = _required_text(
            expected_output,
            "expected_output",
            maximum=8_000,
        )
        owner_id = _required_text(
            current_owner_participant_id,
            "current_owner_participant_id",
            maximum=320,
        )
        creator_id = _required_text(
            created_by_participant_id,
            "created_by_participant_id",
            maximum=320,
        )
        accountable_id = (
            _bounded_text(accountable_participant_id, maximum=320) or owner_id
        )
        normalized_client_message_id = _required_text(
            client_message_id,
            "client_message_id",
            maximum=320,
        )
        normalized_state = str(state or "").strip()
        if normalized_state not in _WORK_STATES:
            raise ValueError("unsupported agent room work item state")
        normalized_depth = int(depth)
        if not 1 <= normalized_depth <= 3:
            raise ValueError("agent room work item depth must be between 1 and 3")
        normalized_topic_id = _bounded_text(topic_id, maximum=320)
        normalized_root_turn_id = _bounded_text(root_turn_id, maximum=320)
        normalized_parent_id = _bounded_text(parent_work_id, maximum=320)
        try:
            normalized_acceptance_criteria = json.loads(
                json.dumps(
                    list(acceptance_criteria),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "acceptance_criteria must contain JSON-compatible values"
            ) from exc
        timestamp = _timestamp(created_at_ms)
        work_id = f"room-work:{uuid.uuid4()}"

        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM agent_room_work_items
                WHERE room_id = ? AND created_by_participant_id = ?
                  AND client_message_id = ?
                """,
                (
                    normalized_room_id,
                    creator_id,
                    normalized_client_message_id,
                ),
            ).fetchone()
            if existing is not None:
                payload = _work_item_payload(existing)
                if (
                    payload["objective"] != normalized_objective
                    or payload["expectedOutput"] != normalized_expected
                    or payload["currentOwnerParticipantId"] != owner_id
                    or payload["accountableParticipantId"] != accountable_id
                    or payload["topicId"] != normalized_topic_id
                    or payload["rootTurnId"] != normalized_root_turn_id
                    or payload["parentWorkId"] != normalized_parent_id
                    or payload["acceptanceCriteria"]
                    != normalized_acceptance_criteria
                    or payload["state"] != normalized_state
                    or payload["depth"] != normalized_depth
                ):
                    raise ValueError(
                        "client_message_id was already used for a different room work item"
                    )
                return payload

            participant_rows = conn.execute(
                """
                SELECT id, participant_status FROM agent_room_participants
                WHERE room_id = ? AND id IN (?, ?, ?)
                """,
                (normalized_room_id, owner_id, creator_id, accountable_id),
            ).fetchall()
            participants = {
                str(row["id"]): str(row["participant_status"]) for row in participant_rows
            }
            if (
                participants.get(owner_id) != "active"
                or participants.get(creator_id) != "active"
                or participants.get(accountable_id) != "active"
            ):
                raise ValueError(
                    "work item owner, creator, and accountable participant "
                    "must be active members of the room"
                )

            parent_id = normalized_parent_id
            if parent_id:
                parent = conn.execute(
                    """
                    SELECT room_id, root_work_id, depth
                    FROM agent_room_work_items WHERE id = ?
                    """,
                    (parent_id,),
                ).fetchone()
                if parent is None or str(parent["room_id"]) != normalized_room_id:
                    raise ValueError("parent work item does not belong to this room")
                if normalized_depth != int(parent["depth"]) + 1:
                    raise ValueError("child work item depth must follow its parent")
                root_work_id = str(parent["root_work_id"])
            else:
                root_work_id = work_id

            conn.execute(
                """
                INSERT INTO agent_room_work_items(
                    id, room_id, topic_id, root_turn_id, root_work_id,
                    parent_work_id, objective, expected_output,
                    acceptance_criteria_json, accountable_participant_id,
                    current_owner_participant_id, offered_to_participant_id,
                    created_by_participant_id, client_message_id, assignment_key,
                    state, depth, revision, result_summary, artifact_refs_json,
                    evidence_refs_json, blocker_json, accepted_turn_id,
                    created_at_ms, updated_at_ms, completed_at_ms
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?,
                    ?, ?, 0, '', '[]', '[]', '{}', '', ?, ?, NULL
                )
                """,
                (
                    work_id,
                    normalized_room_id,
                    normalized_topic_id,
                    normalized_root_turn_id,
                    root_work_id,
                    parent_id or None,
                    normalized_objective,
                    normalized_expected,
                    json.dumps(
                        normalized_acceptance_criteria,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    accountable_id,
                    owner_id,
                    creator_id,
                    normalized_client_message_id,
                    f"{normalized_room_id}:{work_id}:assignment:1",
                    normalized_state,
                    normalized_depth,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_assignment_event(
                conn,
                work_id=work_id,
                room_id=normalized_room_id,
                actor_participant_id=creator_id,
                previous_owner_participant_id="",
                current_owner_participant_id=owner_id,
                created_at_ms=timestamp,
                reason="initial_assignment",
            )
            row = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (work_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by the insert transaction
            raise RuntimeError("agent room work item did not persist")
        return _work_item_payload(row)

    def get(self, work_item_id: str, *, room_id: str = "") -> dict[str, object]:
        normalized_id = _required_text(work_item_id, "work_item_id", maximum=320)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
        if row is None:
            raise AgentRoomWorkItemNotFound(normalized_id)
        payload = _work_item_payload(row)
        expected_room_id = str(room_id or "").strip()
        if expected_room_id and payload["roomId"] != expected_room_id:
            raise ValueError("work item does not belong to this room")
        return payload

    def list(
        self,
        *,
        room_id: str,
        states: Sequence[str] = (),
        owner_participant_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        normalized_room_id = _required_text(room_id, "room_id", maximum=320)
        normalized_states = tuple(
            dict.fromkeys(str(value or "").strip() for value in states)
        )
        if any(value not in _WORK_STATES for value in normalized_states):
            raise ValueError("unsupported agent room work item state")
        normalized_owner_id = _bounded_text(owner_participant_id, maximum=320)
        bounded_limit = max(1, min(int(limit), 200))
        clauses = ["room_id = ?"]
        parameters: list[object] = [normalized_room_id]
        if normalized_states:
            placeholders = ", ".join("?" for _ in normalized_states)
            clauses.append(f"state IN ({placeholders})")
            parameters.extend(normalized_states)
        if normalized_owner_id:
            clauses.append("current_owner_participant_id = ?")
            parameters.append(normalized_owner_id)
        parameters.append(bounded_limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM agent_room_work_items
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at_ms DESC, id DESC
                LIMIT ?
                """,  # noqa: S608 - clauses contain only fixed internal columns
                parameters,
            ).fetchall()
        return [_work_item_payload(row) for row in rows]

    def authoritative_owner(
        self,
        work_item_id: str,
        *,
        room_id: str,
    ) -> tuple[dict[str, object], str]:
        normalized_id = _required_text(work_item_id, "work_item_id", maximum=320)
        with self._connect() as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            assignment = conn.execute(
                """
                SELECT payload_json FROM agent_room_work_events
                WHERE work_id = ? AND event_type = 'assigned'
                ORDER BY sequence DESC LIMIT 1
                """,
                (normalized_id,),
            ).fetchone()
        if row is None:
            raise AgentRoomWorkItemNotFound(normalized_id)
        item = _work_item_payload(row)
        if item["roomId"] != str(room_id or "").strip():
            raise ValueError("work item does not belong to this room")
        owner_id = ""
        if str(item["state"]) in _AUTHORITATIVE_STATES:
            if assignment is None:
                raise RuntimeError(
                    "active WorkItem owner has no formal assignment event"
                )
            assignment_payload = json.loads(str(assignment["payload_json"] or "{}"))
            owner_id = str(item["currentOwnerParticipantId"])
            if (
                str(assignment_payload.get("currentOwnerParticipantId") or "")
                != owner_id
            ):
                raise RuntimeError(
                    "WorkItem owner does not match its latest formal assignment event"
                )
        return item, owner_id

    def reassign(
        self,
        work_item_id: str,
        *,
        actor_participant_id: str,
        current_owner_participant_id: str,
        reason: str = "",
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_id = _required_text(work_item_id, "work_item_id", maximum=320)
        actor_id = _required_text(
            actor_participant_id,
            "actor_participant_id",
            maximum=320,
        )
        owner_id = _required_text(
            current_owner_participant_id,
            "current_owner_participant_id",
            maximum=320,
        )
        timestamp = _timestamp(updated_at_ms)
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise AgentRoomWorkItemNotFound(normalized_id)
            state = str(row["state"])
            if state not in _AUTHORITATIVE_STATES:
                raise ValueError("only active or review work items can be reassigned")
            room_id = str(row["room_id"])
            participants = conn.execute(
                """
                SELECT id, participant_status FROM agent_room_participants
                WHERE room_id = ? AND id IN (?, ?)
                """,
                (room_id, actor_id, owner_id),
            ).fetchall()
            participant_statuses = {
                str(value["id"]): str(value["participant_status"])
                for value in participants
            }
            if (
                participant_statuses.get(actor_id) != "active"
                or participant_statuses.get(owner_id) != "active"
            ):
                raise ValueError(
                    "reassignment actor and owner must be active room participants"
                )
            previous_owner_id = str(row["current_owner_participant_id"])
            if actor_id not in {
                previous_owner_id,
                str(row["accountable_participant_id"]),
            }:
                raise ValueError(
                    "only the current owner or accountable participant may reassign work"
                )
            if previous_owner_id == owner_id:
                return _work_item_payload(row)

            assignment_key = (
                f"{room_id}:{normalized_id}:assignment:{uuid.uuid4()}"
            )
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET current_owner_participant_id = ?,
                    offered_to_participant_id = NULL,
                    assignment_key = ?,
                    updated_at_ms = ?
                WHERE id = ?
                """,
                (
                    owner_id,
                    assignment_key,
                    timestamp,
                    normalized_id,
                ),
            )
            self._append_assignment_event(
                conn,
                work_id=normalized_id,
                room_id=room_id,
                actor_participant_id=actor_id,
                previous_owner_participant_id=previous_owner_id,
                current_owner_participant_id=owner_id,
                created_at_ms=timestamp,
                reason=_bounded_text(reason, maximum=500) or "reassignment",
            )
            updated = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
        if updated is None:  # pragma: no cover - guarded by the update transaction
            raise AgentRoomWorkItemNotFound(normalized_id)
        return _work_item_payload(updated)

    def claim_dispatch(
        self,
        work_item_id: str,
        *,
        room_id: str,
        owner_participant_id: str,
        assignment_key: str,
        previous_accepted_turn_id: str,
        room_turn_id: str,
        claimed_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Linearize routing against reassignment before invoking the runtime.

        The compare-and-set includes the formal assignment key and the previous
        accepted turn. Concurrent reassignment or dispatch therefore fails
        closed instead of sending work to a stale owner.
        """

        normalized_id = _required_text(work_item_id, "work_item_id", maximum=320)
        normalized_room_id = _required_text(room_id, "room_id", maximum=320)
        owner_id = _required_text(
            owner_participant_id,
            "owner_participant_id",
            maximum=320,
        )
        normalized_assignment_key = _required_text(
            assignment_key,
            "assignment_key",
            maximum=800,
        )
        previous_turn_id = _bounded_text(
            previous_accepted_turn_id,
            maximum=320,
        )
        normalized_turn_id = _required_text(
            room_turn_id,
            "room_turn_id",
            maximum=320,
        )
        timestamp = _timestamp(claimed_at_ms)
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise AgentRoomWorkItemNotFound(normalized_id)
            if str(row["room_id"]) != normalized_room_id:
                raise ValueError("work item does not belong to this room")
            if str(row["state"]) not in _AUTHORITATIVE_STATES:
                raise ValueError(
                    "only active or review work items can be dispatched"
                )
            assignment = conn.execute(
                """
                SELECT payload_json FROM agent_room_work_events
                WHERE work_id = ? AND event_type = 'assigned'
                ORDER BY sequence DESC LIMIT 1
                """,
                (normalized_id,),
            ).fetchone()
            if assignment is None:
                raise RuntimeError(
                    "active WorkItem owner has no formal assignment event"
                )
            assignment_payload = json.loads(
                str(assignment["payload_json"] or "{}")
            )
            if (
                str(row["current_owner_participant_id"]) != owner_id
                or str(row["assignment_key"]) != normalized_assignment_key
                or str(row["accepted_turn_id"] or "") != previous_turn_id
                or str(
                    assignment_payload.get("currentOwnerParticipantId") or ""
                )
                != owner_id
            ):
                raise AgentRoomWorkAssignmentChanged(
                    "WorkItem assignment changed before dispatch"
                )
            cursor = conn.execute(
                """
                UPDATE agent_room_work_items
                SET accepted_turn_id = ?, updated_at_ms = ?
                WHERE id = ? AND room_id = ?
                  AND current_owner_participant_id = ?
                  AND assignment_key = ?
                  AND accepted_turn_id = ?
                """,
                (
                    normalized_turn_id,
                    timestamp,
                    normalized_id,
                    normalized_room_id,
                    owner_id,
                    normalized_assignment_key,
                    previous_turn_id,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRoomWorkAssignmentChanged(
                    "WorkItem assignment changed before dispatch"
                )
            self._append_work_event(
                conn,
                work_id=normalized_id,
                room_id=normalized_room_id,
                event_type="accepted",
                actor_participant_id=owner_id,
                payload={
                    "assignmentKey": normalized_assignment_key,
                    "roomTurnId": normalized_turn_id,
                },
                created_at_ms=timestamp,
            )
            claimed = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
        if claimed is None:  # pragma: no cover - guarded by the transaction
            raise AgentRoomWorkItemNotFound(normalized_id)
        return _work_item_payload(claimed)

    def fail_dispatch(
        self,
        work_item_id: str,
        *,
        room_id: str,
        actor_participant_id: str,
        room_turn_id: str,
        previous_accepted_turn_id: str,
        reason: str,
        failed_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Record a runtime handoff failure without erasing newer claims."""

        normalized_id = _required_text(work_item_id, "work_item_id", maximum=320)
        normalized_room_id = _required_text(room_id, "room_id", maximum=320)
        actor_id = _required_text(
            actor_participant_id,
            "actor_participant_id",
            maximum=320,
        )
        normalized_turn_id = _required_text(
            room_turn_id,
            "room_turn_id",
            maximum=320,
        )
        previous_turn_id = _bounded_text(
            previous_accepted_turn_id,
            maximum=320,
        )
        timestamp = _timestamp(failed_at_ms)
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise AgentRoomWorkItemNotFound(normalized_id)
            if str(row["room_id"]) != normalized_room_id:
                raise ValueError("work item does not belong to this room")
            claim_is_current = (
                str(row["accepted_turn_id"] or "") == normalized_turn_id
            )
            if claim_is_current:
                conn.execute(
                    """
                    UPDATE agent_room_work_items
                    SET accepted_turn_id = ?, updated_at_ms = ?
                    WHERE id = ? AND accepted_turn_id = ?
                    """,
                    (
                        previous_turn_id,
                        timestamp,
                        normalized_id,
                        normalized_turn_id,
                    ),
                )
            self._append_work_event(
                conn,
                work_id=normalized_id,
                room_id=normalized_room_id,
                event_type="assignment_failed",
                actor_participant_id=actor_id,
                payload={
                    "roomTurnId": normalized_turn_id,
                    "claimCursorRestored": claim_is_current,
                    "reason": _bounded_text(reason, maximum=500)
                    or "runtime_dispatch_failed",
                },
                created_at_ms=timestamp,
            )
            updated = conn.execute(
                "SELECT * FROM agent_room_work_items WHERE id = ?",
                (normalized_id,),
            ).fetchone()
        if updated is None:  # pragma: no cover - guarded by the transaction
            raise AgentRoomWorkItemNotFound(normalized_id)
        return _work_item_payload(updated)

    def list_events(self, work_item_id: str) -> list[dict[str, object]]:
        item = self.get(work_item_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_room_work_events
                WHERE work_id = ? ORDER BY sequence ASC
                """,
                (str(item["id"]),),
            ).fetchall()
        return [_work_event_payload(row) for row in rows]

    @staticmethod
    def _append_assignment_event(
        conn: sqlite3.Connection,
        *,
        work_id: str,
        room_id: str,
        actor_participant_id: str,
        previous_owner_participant_id: str,
        current_owner_participant_id: str,
        created_at_ms: int,
        reason: str,
    ) -> None:
        payload = {
            "reason": reason,
            "previousOwnerParticipantId": previous_owner_participant_id,
            "currentOwnerParticipantId": current_owner_participant_id,
        }
        AgentRoomWorkStore._append_work_event(
            conn,
            work_id=work_id,
            room_id=room_id,
            event_type="assigned",
            actor_participant_id=actor_participant_id,
            payload=payload,
            created_at_ms=created_at_ms,
        )

    @staticmethod
    def _append_work_event(
        conn: sqlite3.Connection,
        *,
        work_id: str,
        room_id: str,
        event_type: str,
        actor_participant_id: str,
        payload: Mapping[str, object],
        created_at_ms: int,
    ) -> None:
        sequence_row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1
            FROM agent_room_work_events WHERE work_id = ?
            """,
            (work_id,),
        ).fetchone()
        sequence = int(sequence_row[0]) if sequence_row is not None else 1
        conn.execute(
            """
            INSERT INTO agent_room_work_events(
                event_id, work_id, room_id, sequence, event_type,
                actor_participant_id, payload_json, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"room-work-event:{uuid.uuid4()}",
                work_id,
                room_id,
                sequence,
                event_type,
                actor_participant_id,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                created_at_ms,
            ),
        )

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _work_item_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-room-work-item.v1",
        "id": str(row["id"]),
        "roomId": str(row["room_id"]),
        "topicId": str(row["topic_id"] or ""),
        "rootTurnId": str(row["root_turn_id"] or ""),
        "rootWorkId": str(row["root_work_id"]),
        "parentWorkId": str(row["parent_work_id"] or ""),
        "objective": str(row["objective"]),
        "expectedOutput": str(row["expected_output"]),
        "acceptanceCriteria": json.loads(
            str(row["acceptance_criteria_json"] or "[]")
        ),
        "accountableParticipantId": str(row["accountable_participant_id"]),
        "currentOwnerParticipantId": str(row["current_owner_participant_id"]),
        "offeredToParticipantId": str(row["offered_to_participant_id"] or ""),
        "createdByParticipantId": str(row["created_by_participant_id"]),
        "clientMessageId": str(row["client_message_id"]),
        "assignmentKey": str(row["assignment_key"]),
        "state": str(row["state"]),
        "depth": int(row["depth"]),
        "revision": int(row["revision"]),
        "resultSummary": str(row["result_summary"] or ""),
        "artifactRefs": json.loads(str(row["artifact_refs_json"] or "[]")),
        "evidenceRefs": json.loads(str(row["evidence_refs_json"] or "[]")),
        "blocker": json.loads(str(row["blocker_json"] or "{}")),
        "acceptedTurnId": str(row["accepted_turn_id"] or ""),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "completedAtMs": (
            int(row["completed_at_ms"]) if row["completed_at_ms"] is not None else None
        ),
    }


def _work_event_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-room-work-event.v1",
        "eventId": str(row["event_id"]),
        "workItemId": str(row["work_id"]),
        "roomId": str(row["room_id"]),
        "sequence": int(row["sequence"]),
        "eventType": str(row["event_type"]),
        "actorParticipantId": str(row["actor_participant_id"]),
        "payload": json.loads(str(row["payload_json"] or "{}")),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _required_text(value: object, field: str, *, maximum: int) -> str:
    text = _bounded_text(value, maximum=maximum)
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _bounded_text(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _timestamp(value: int | None) -> int:
    return int(value if value is not None else time.time() * 1000)
