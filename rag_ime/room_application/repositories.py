from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from ..room_domain.model import DomainEvent, DomainPolicyError


class RoomDomainEventRepository:
    """Persist a transition and its recoverable effects in one transaction."""

    EFFECT_KINDS = ("project_room", "wake_room")

    @staticmethod
    def append(
        conn: sqlite3.Connection,
        event: DomainEvent,
        *,
        created_at_ms: int,
    ) -> bool:
        encoded = _json(asdict(event))
        existing = conn.execute(
            "SELECT payload_json FROM room_domain_events WHERE event_id=?",
            (event.event_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_json"]) != encoded:
                raise DomainPolicyError("domain event identity was rebound")
            return False
        room_sequence = int(
            conn.execute(
                """SELECT COALESCE(MAX(room_sequence), 0) + 1
                   FROM room_domain_events WHERE room_id=?""",
                (event.room_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """INSERT INTO room_domain_events(
               event_id,room_id,root_id,entity_id,event_kind,generation,
               room_sequence,payload_json,created_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                event.event_id,
                event.room_id,
                event.root_id,
                event.entity_id,
                event.kind,
                event.generation,
                room_sequence,
                encoded,
                int(created_at_ms),
            ),
        )
        for effect_kind in RoomDomainEventRepository.EFFECT_KINDS:
            outbox_id = f"{event.event_id}:{effect_kind}"
            payload = {
                "schemaVersion": "wisdom-weasel.room-application-effect.v1",
                "outboxId": outbox_id,
                "eventId": event.event_id,
                "effectKind": effect_kind,
                "roomId": event.room_id,
                "rootId": event.root_id,
                "generation": event.generation,
            }
            conn.execute(
                """INSERT INTO room_application_outbox(
                   outbox_id,event_id,room_id,root_id,effect_kind,state,
                   attempt,available_at_ms,lease_until_ms,last_error,
                   payload_json,created_at_ms,updated_at_ms)
                   VALUES (?,?,?,?,?,'pending',0,?,0,'',?,?,?)""",
                (
                    outbox_id,
                    event.event_id,
                    event.room_id,
                    event.root_id,
                    effect_kind,
                    int(created_at_ms),
                    _json(payload),
                    int(created_at_ms),
                    int(created_at_ms),
                ),
            )
        return True


class RoomInterventionRepository:
    """Authoritative execution-time corrections, independent of projections."""

    @staticmethod
    def pending(
        conn: sqlite3.Connection,
        *,
        root_id: str,
    ) -> list[dict[str, object]]:
        rows = conn.execute(
            """SELECT intervention_id,intervention_kind,state,
                      requirement_catalog_revision_id,
                      requires_plan_revision,affected_task_ids_json,
                      payload_json,created_at_ms
               FROM room_interventions
               WHERE root_id=? AND state='pending_reconciliation'
               ORDER BY created_at_ms,intervention_id""",
            (root_id,),
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            affected = json.loads(str(row["affected_task_ids_json"]))
            result.append(
                {
                    **(payload if isinstance(payload, dict) else {}),
                    "interventionId": str(row["intervention_id"]),
                    "kind": str(row["intervention_kind"]),
                    "state": str(row["state"]),
                    "requirementCatalogRevisionId": str(
                        row["requirement_catalog_revision_id"] or ""
                    ),
                    "requiresPlanRevision": bool(
                        row["requires_plan_revision"]
                    ),
                    "affectedTaskIds": [
                        str(value)
                        for value in affected
                        if str(value or "").strip()
                    ],
                    "createdAtMs": int(row["created_at_ms"]),
                }
            )
        return result


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
