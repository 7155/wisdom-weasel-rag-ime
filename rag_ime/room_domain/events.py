from __future__ import annotations

import hashlib
import json
from typing import Mapping

from .model import DomainEvent, DomainPolicyError


def past_tense_event(
    *,
    kind: str,
    room_id: str,
    root_id: str,
    entity_id: str,
    generation: int,
    idempotency_key: str,
    payload: Mapping[str, object] | None = None,
) -> DomainEvent:
    values = {
        "kind": _required(kind, "kind"),
        "roomId": _required(room_id, "room_id"),
        "rootId": _required(root_id, "root_id"),
        "entityId": _required(entity_id, "entity_id"),
        "generation": _non_negative(generation, "generation"),
        "idempotencyKey": _required(idempotency_key, "idempotency_key"),
        "payload": dict(payload or {}),
    }
    digest = hashlib.sha256(
        json.dumps(
            values,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return DomainEvent(
        event_id=f"room-domain:{digest}",
        kind=values["kind"],
        room_id=values["roomId"],
        root_id=values["rootId"],
        entity_id=values["entityId"],
        generation=values["generation"],
        payload=values["payload"],
    )


def _required(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomainPolicyError(f"{field} is required")
    return text


def _non_negative(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DomainPolicyError(f"{field} must be a non-negative integer")
    return value
