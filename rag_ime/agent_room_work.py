from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


WORK_STATES = frozenset(
    {"queued", "active", "review", "blocked", "done", "failed", "cancelled"}
)
OPEN_WORK_STATES = frozenset({"queued", "active", "review", "blocked"})
MAX_ASSIGNMENTS_PER_ROOT = 6
MAX_ASSIGNMENT_DEPTH = 3
MAX_REVISIONS = 2


class AgentRoomWorkStore:
    """Durable Room responsibility ledger with append-only transition evidence."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def assign(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
        *,
        root_turn_id: str = "",
        topic_id: str = "",
        created_at_ms: int | None = None,
    ) -> tuple[dict[str, object], bool]:
        timestamp = _timestamp(created_at_ms)
        target_id = _required_text(
            payload.get("targetParticipantId"),
            "targetParticipantId",
            maximum=240,
        )
        client_message_id = _required_text(
            payload.get("clientMessageId"),
            "clientMessageId",
            maximum=200,
        )
        objective = _required_text(payload.get("objective"), "objective", maximum=4_000)
        expected_output = _required_text(
            payload.get("expectedOutput"),
            "expectedOutput",
            maximum=2_000,
        )
        criteria = _text_list(
            payload.get("acceptanceCriteria"),
            "acceptanceCriteria",
            maximum_items=8,
            maximum_length=500,
            required=True,
        )
        parent_work_id = _optional_text(
            payload.get("parentWorkId"),
            maximum=240,
        )
        assignment_key = hashlib.sha256(
            f"{parent_work_id}\0{target_id}\0{' '.join(objective.lower().split())}".encode()
        ).hexdigest()

        with self._connect(immediate=True) as conn:
            source = _participant_for_session(conn, source_session_id)
            room_id = str(source["room_id"])
            existing = conn.execute(
                """
                SELECT * FROM agent_room_work_items
                WHERE room_id = ? AND created_by_participant_id = ?
                  AND client_message_id = ?
                """,
                (room_id, str(source["id"]), client_message_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["offered_to_participant_id"] or "") != target_id
                    or str(existing["objective"]) != objective
                    or str(existing["expected_output"]) != expected_output
                    or json.loads(str(existing["acceptance_criteria_json"])) != criteria
                    or str(existing["parent_work_id"] or "") != parent_work_id
                ):
                    raise ValueError(
                        "clientMessageId was already used for a different Room assignment"
                    )
                return work_item_payload(existing), False

            target = _participant(conn, room_id, target_id)
            if str(target["id"]) == str(source["id"]):
                raise ValueError("Room work cannot be assigned to the current owner")

            accountable_id = str(source["id"])
            root_work_id = ""
            depth = 1
            parent: sqlite3.Row | None = None
            if parent_work_id:
                parent = conn.execute(
                    """
                    SELECT * FROM agent_room_work_items
                    WHERE id = ? AND room_id = ?
                    """,
                    (parent_work_id, room_id),
                ).fetchone()
                if parent is None:
                    raise ValueError("parentWorkId does not identify work in this Room")
                if str(parent["current_owner_participant_id"]) != str(source["id"]):
                    raise ValueError("only the current owner may split a WorkItem")
                if str(parent["state"]) not in {"active", "blocked"}:
                    raise ValueError("only active or blocked work may be split")
                root_work_id = str(parent["root_work_id"])
                accountable_id = str(parent["accountable_participant_id"])
                depth = int(parent["depth"]) + 1
                if depth > MAX_ASSIGNMENT_DEPTH:
                    raise ValueError("Room assignment depth limit is 3")
                self._reject_ancestor_bounce(
                    conn,
                    parent,
                    target_participant_id=target_id,
                )

            open_children = conn.execute(
                """
                SELECT COUNT(*) FROM agent_room_work_items
                WHERE created_by_participant_id = ?
                  AND state IN ('queued', 'active', 'review', 'blocked')
                """,
                (str(source["id"]),),
            ).fetchone()
            parallel_limit = (
                2 if str(source["collaboration_role"]) == "coordinator" else 1
            )
            if int(open_children[0] if open_children else 0) >= parallel_limit:
                raise ValueError(
                    f"Room assignment parallel limit is {parallel_limit} for this role"
                )

            duplicate = conn.execute(
                """
                SELECT * FROM agent_room_work_items
                WHERE room_id = ? AND created_by_participant_id = ?
                  AND assignment_key = ? AND state = 'queued'
                ORDER BY created_at_ms ASC LIMIT 1
                """,
                (room_id, str(source["id"]), assignment_key),
            ).fetchone()
            if duplicate is not None:
                return work_item_payload(duplicate), False

            work_id = f"room-work:{uuid.uuid4()}"
            root_work_id = root_work_id or work_id
            assignment_count = conn.execute(
                "SELECT COUNT(*) FROM agent_room_work_items WHERE root_work_id = ?",
                (root_work_id,),
            ).fetchone()
            if int(assignment_count[0] if assignment_count else 0) >= MAX_ASSIGNMENTS_PER_ROOT:
                raise ValueError("Room root assignment limit is 6")

            conn.execute(
                """
                INSERT INTO agent_room_work_items(
                    id, room_id, topic_id, root_turn_id, root_work_id, parent_work_id,
                    objective, expected_output, acceptance_criteria_json,
                    accountable_participant_id, current_owner_participant_id,
                    offered_to_participant_id, created_by_participant_id,
                    client_message_id, assignment_key, state, depth, revision,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'queued', ?, 0, ?, ?)
                """,
                (
                    work_id,
                    room_id,
                    str(topic_id or ""),
                    str(root_turn_id or ""),
                    root_work_id,
                    parent_work_id or None,
                    objective,
                    expected_output,
                    json.dumps(criteria, ensure_ascii=False, separators=(",", ":")),
                    accountable_id,
                    str(source["id"]),
                    target_id,
                    str(source["id"]),
                    client_message_id,
                    assignment_key,
                    depth,
                    timestamp,
                    timestamp,
                ),
            )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="assigned",
                actor_participant_id=str(source["id"]),
                created_at_ms=timestamp,
            )
        return work_item_payload(row), True

    def accept_assignment(
        self,
        work_id: str,
        *,
        target_participant_id: str,
        accepted_turn_id: str,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        with self._connect(immediate=True) as conn:
            row = self._row(conn, work_id)
            if str(row["state"]) == "active":
                return work_item_payload(row)
            if str(row["state"]) != "queued":
                raise ValueError("Room assignment is no longer queued")
            if str(row["offered_to_participant_id"] or "") != target_participant_id:
                raise ValueError("only the offered participant may accept this assignment")
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'active', current_owner_participant_id = ?,
                    offered_to_participant_id = NULL, accepted_turn_id = ?,
                    updated_at_ms = ?
                WHERE id = ?
                """,
                (
                    target_participant_id,
                    str(accepted_turn_id or "")[:240],
                    timestamp,
                    work_id,
                ),
            )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="accepted",
                actor_participant_id=target_participant_id,
                created_at_ms=timestamp,
            )
        return work_item_payload(row)

    def fail_assignment(
        self,
        work_id: str,
        *,
        actor_participant_id: str,
        reason: str,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        with self._connect(immediate=True) as conn:
            row = self._row(conn, work_id)
            if str(row["state"]) != "queued":
                return work_item_payload(row)
            blocker = {"reason": _bounded(reason, 500), "phase": "assignment"}
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'failed', blocker_json = ?, updated_at_ms = ?,
                    completed_at_ms = ?
                WHERE id = ?
                """,
                (
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
                event_type="assignment_failed",
                actor_participant_id=actor_participant_id,
                created_at_ms=timestamp,
            )
        return work_item_payload(row)

    def submit(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
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
                "room_submit requires at least one artifactRefs or evidenceRefs entry"
            )
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._owned_row(conn, work_id, actor)
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
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'review', result_summary = ?, artifact_refs_json = ?,
                    evidence_refs_json = ?, blocker_json = '{}', updated_at_ms = ?
                WHERE id = ?
                """,
                (
                    summary,
                    json.dumps(artifact_refs, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(evidence_refs, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    work_id,
                ),
            )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="submitted",
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
            )
        return work_item_payload(row)

    def accept(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        return self._review_transition(
            session_id,
            payload,
            accept=True,
            updated_at_ms=updated_at_ms,
        )

    def return_for_revision(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        return self._review_transition(
            session_id,
            payload,
            accept=False,
            updated_at_ms=updated_at_ms,
        )

    def block(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        work_id = _required_text(payload.get("workId"), "workId", maximum=240)
        blocker = {
            "reason": _required_text(payload.get("reason"), "reason", maximum=2_000),
            "nextStep": _required_text(
                payload.get("nextStep"),
                "nextStep",
                maximum=2_000,
            ),
            "wakeCondition": _wake_condition(payload.get("wakeCondition")),
        }
        deadline = payload.get("deadlineAtMs")
        if deadline is not None:
            if not isinstance(deadline, int) or isinstance(deadline, bool) or deadline < 1:
                raise ValueError("deadlineAtMs must be a positive integer")
            blocker["deadlineAtMs"] = deadline
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._owned_row(conn, work_id, actor)
            if str(row["state"]) != "active":
                raise ValueError("only active work may be blocked")
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'blocked', blocker_json = ?, updated_at_ms = ?
                WHERE id = ?
                """,
                (
                    json.dumps(blocker, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    work_id,
                ),
            )
            row = self._row(conn, work_id)
            self._append_event(
                conn,
                row,
                event_type="blocked",
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
            )
        return work_item_payload(row)

    def escalate(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        work_id = _required_text(payload.get("workId"), "workId", maximum=240)
        reason = _required_text(payload.get("reason"), "reason", maximum=2_000)
        next_step = _required_text(payload.get("nextStep"), "nextStep", maximum=2_000)
        with self._connect(immediate=True) as conn:
            actor = _participant_for_session(conn, session_id)
            row = self._owned_row(conn, work_id, actor)
            if str(row["state"]) not in {"active", "blocked"}:
                raise ValueError("only active or blocked work may be escalated")
            blocker = {
                "reason": reason,
                "nextStep": next_step,
                "escalated": True,
            }
            conn.execute(
                """
                UPDATE agent_room_work_items
                SET state = 'failed', blocker_json = ?, updated_at_ms = ?,
                    completed_at_ms = ?
                WHERE id = ?
                """,
                (
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
                event_type="escalated",
                actor_participant_id=str(actor["id"]),
                created_at_ms=timestamp,
            )
        return work_item_payload(row)

    def list_for_session(
        self,
        session_id: str,
        *,
        status: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        normalized_status = str(status or "").strip()
        if normalized_status and normalized_status not in WORK_STATES:
            raise ValueError("unsupported Room work state")
        bounded = max(1, min(int(limit), 200))
        with self._connect() as conn:
            participant = _participant_for_session(conn, session_id, active_only=False)
            params: list[object] = [str(participant["room_id"])]
            clause = ""
            if normalized_status:
                clause = "AND state = ?"
                params.append(normalized_status)
            params.append(bounded)
            rows = conn.execute(
                f"""
                SELECT * FROM agent_room_work_items
                WHERE room_id = ? {clause}
                ORDER BY
                    CASE state
                        WHEN 'blocked' THEN 0
                        WHEN 'review' THEN 1
                        WHEN 'active' THEN 2
                        WHEN 'queued' THEN 3
                        ELSE 4
                    END,
                    updated_at_ms DESC
                LIMIT ?
                """,  # noqa: S608 - clause is selected from a fixed string
                tuple(params),
            ).fetchall()
        return [work_item_payload(row) for row in rows]

    def list_for_room(
        self,
        room_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        bounded = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_room_work_items
                WHERE room_id = ?
                ORDER BY
                    CASE state
                        WHEN 'blocked' THEN 0
                        WHEN 'review' THEN 1
                        WHEN 'active' THEN 2
                        WHEN 'queued' THEN 3
                        ELSE 4
                    END,
                    updated_at_ms DESC
                LIMIT ?
                """,
                (room_id, bounded),
            ).fetchall()
        return [work_item_payload(row) for row in rows]

    def get(self, work_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = self._row(conn, work_id)
        return work_item_payload(row)

    def reviewer_participant_id(self, work_id: str) -> str:
        with self._connect() as conn:
            row = self._row(conn, work_id)
            if row["parent_work_id"]:
                parent = self._row(conn, str(row["parent_work_id"]))
                return str(parent["current_owner_participant_id"])
        return str(row["accountable_participant_id"])

    def reconcile_intercom_outcomes(self) -> int:
        """Repair the rare crash window between durable delivery and Room projection."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.work_item_id, m.status, m.target_participant_id,
                       m.source_participant_id, m.accepted_turn_id, m.error
                FROM agent_room_intercom_messages m
                JOIN agent_room_work_items w ON w.id = m.work_item_id
                WHERE m.work_action = 'assignment'
                  AND w.state = 'queued'
                  AND m.status IN ('delivered', 'failed', 'stale', 'cancelled')
                ORDER BY m.updated_at_ms ASC
                """
            ).fetchall()
        repaired = 0
        for row in rows:
            work_id = str(row["work_item_id"])
            if str(row["status"]) == "delivered":
                self.accept_assignment(
                    work_id,
                    target_participant_id=str(row["target_participant_id"]),
                    accepted_turn_id=str(row["accepted_turn_id"] or ""),
                )
            else:
                self.fail_assignment(
                    work_id,
                    actor_participant_id=str(row["source_participant_id"]),
                    reason=str(row["error"] or row["status"]),
                )
            repaired += 1
        return repaired

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
                    raise ValueError("room_return requires a concrete reason")
                revision = int(row["revision"]) + 1
                if revision > MAX_REVISIONS:
                    raise ValueError(
                        "Room revision limit is 2; use room_escalate instead"
                    )
                conn.execute(
                    """
                    UPDATE agent_room_work_items
                    SET state = 'active', revision = ?, blocker_json = ?,
                        updated_at_ms = ?
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
        return work_item_payload(row)

    def _require_reviewer(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        participant_id: str,
    ) -> None:
        expected = str(row["accountable_participant_id"])
        if row["parent_work_id"]:
            parent = self._row(conn, str(row["parent_work_id"]))
            expected = str(parent["current_owner_participant_id"])
        if participant_id != expected:
            raise ValueError("only the accountable parent owner may review this work")

    def _owned_row(
        self,
        conn: sqlite3.Connection,
        work_id: str,
        actor: sqlite3.Row,
    ) -> sqlite3.Row:
        row = self._row(conn, work_id)
        if str(row["room_id"]) != str(actor["room_id"]):
            raise ValueError("WorkItem does not belong to the current Room")
        if str(row["current_owner_participant_id"]) != str(actor["id"]):
            raise ValueError("only the current owner may change this WorkItem")
        return row

    def _reject_ancestor_bounce(
        self,
        conn: sqlite3.Connection,
        parent: sqlite3.Row,
        *,
        target_participant_id: str,
    ) -> None:
        current: sqlite3.Row | None = parent
        while current is not None:
            ancestor_participants = {
                str(current["current_owner_participant_id"]),
                str(current["created_by_participant_id"]),
                str(current["accountable_participant_id"]),
            }
            if target_participant_id in ancestor_participants:
                raise ValueError(
                    "cannot assign work back to an ancestor owner; submit or escalate it"
                )
            parent_id = str(current["parent_work_id"] or "")
            current = self._row(conn, parent_id) if parent_id else None

    def _append_event(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        event_type: str,
        actor_participant_id: str,
        created_at_ms: int,
    ) -> None:
        sequence_row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_room_work_events WHERE work_id = ?",
            (str(row["id"]),),
        ).fetchone()
        sequence = int(sequence_row[0] if sequence_row else 1)
        snapshot = work_item_payload(row)
        conn.execute(
            """
            INSERT INTO agent_room_work_events(
                event_id, work_id, room_id, sequence, event_type,
                actor_participant_id, payload_json, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"room-work-event:{uuid.uuid4()}",
                str(row["id"]),
                str(row["room_id"]),
                sequence,
                event_type,
                actor_participant_id,
                json.dumps(
                    {"work": snapshot},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                created_at_ms,
            ),
        )

    @staticmethod
    def _row(conn: sqlite3.Connection, work_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_room_work_items WHERE id = ?",
            (str(work_id or "").strip(),),
        ).fetchone()
        if row is None:
            raise KeyError(work_id)
        return row

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


def work_item_payload(row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-room-work-item.v1",
        "id": str(row["id"]),
        "roomId": str(row["room_id"]),
        "topicId": str(row["topic_id"] or ""),
        "rootTurnId": str(row["root_turn_id"] or ""),
        "rootWorkId": str(row["root_work_id"]),
        "parentWorkId": str(row["parent_work_id"] or ""),
        "objective": str(row["objective"]),
        "expectedOutput": str(row["expected_output"]),
        "acceptanceCriteria": [
            str(value)
            for value in json.loads(str(row["acceptance_criteria_json"] or "[]"))
        ],
        "accountableParticipantId": str(row["accountable_participant_id"]),
        "currentOwnerParticipantId": str(row["current_owner_participant_id"]),
        "offeredToParticipantId": str(row["offered_to_participant_id"] or ""),
        "createdByParticipantId": str(row["created_by_participant_id"]),
        "clientMessageId": str(row["client_message_id"]),
        "state": str(row["state"]),
        "depth": int(row["depth"]),
        "revision": int(row["revision"]),
        "resultSummary": str(row["result_summary"] or ""),
        "artifactRefs": [
            str(value)
            for value in json.loads(str(row["artifact_refs_json"] or "[]"))
        ],
        "evidenceRefs": [
            str(value)
            for value in json.loads(str(row["evidence_refs_json"] or "[]"))
        ],
        "blocker": dict(json.loads(str(row["blocker_json"] or "{}"))),
        "acceptedTurnId": str(row["accepted_turn_id"] or ""),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "completedAtMs": (
            int(row["completed_at_ms"])
            if row["completed_at_ms"] is not None
            else None
        ),
    }
    validate_contract(payload, "agent-room-work-item.v1.json")
    return payload


def _participant_for_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    active_only: bool = True,
) -> sqlite3.Row:
    clause = (
        "AND p.participant_status = 'active' AND r.status = 'active'"
        if active_only
        else ""
    )
    row = conn.execute(
        f"""
        SELECT p.*, r.status AS room_status
        FROM agent_room_participants p
        JOIN agent_rooms r ON r.id = p.room_id
        WHERE p.session_id = ? {clause}
        """,  # noqa: S608 - clause is a fixed internal string
        (str(session_id or "").strip(),),
    ).fetchone()
    if row is None:
        raise ValueError("session is not an active Room participant")
    return row


def _participant(
    conn: sqlite3.Connection,
    room_id: str,
    participant_id: str,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT * FROM agent_room_participants
        WHERE id = ? AND room_id = ? AND participant_status = 'active'
        """,
        (participant_id, room_id),
    ).fetchone()
    if row is None:
        raise ValueError("target is not an active participant in the same Room")
    return row


def _text_list(
    value: object,
    name: str,
    *,
    maximum_items: int,
    maximum_length: int,
    required: bool = False,
) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an array")
    items = [
        _required_text(item, name, maximum=maximum_length)
        for item in value
    ]
    if required and not items:
        raise ValueError(f"{name} must not be empty")
    if len(items) > maximum_items:
        raise ValueError(f"{name} accepts at most {maximum_items} items")
    return items


def _required_text(value: object, name: str, *, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return text


def _optional_text(value: object, *, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise ValueError(f"value exceeds {maximum} characters")
    return text


def _bounded(value: object, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _wake_condition(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("wakeCondition must be an object")
    allowed = {"kind", "sourceId", "description"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(
            f"unsupported wakeCondition fields: {', '.join(sorted(str(key) for key in unknown))}"
        )
    kind = str(value.get("kind") or "").strip()
    if kind and kind not in {"manual", "message", "artifact", "time", "external"}:
        raise ValueError("unsupported wakeCondition kind")
    result: dict[str, str] = {}
    if kind:
        result["kind"] = kind
    for key, maximum in (("sourceId", 240), ("description", 500)):
        text = str(value.get(key) or "").strip()
        if len(text) > maximum:
            raise ValueError(f"wakeCondition {key} exceeds {maximum} characters")
        if text:
            result[key] = text
    return result


def _timestamp(value: int | None = None) -> int:
    return int(value if value is not None else time.time() * 1000)
