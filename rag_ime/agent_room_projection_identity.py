from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def room_projection_hash(
    *,
    room_id: str,
    event_type: str,
    payload: Mapping[str, object],
    turn_id: str,
    participant_id: str | None,
    source_session_id: str,
    topic_id: str,
) -> str:
    """Hash the immutable identity of one durable public Room projection."""

    material = {
        "roomId": room_id,
        "eventType": event_type,
        "turnId": str(turn_id or ""),
        "participantId": participant_id,
        "sourceSessionId": str(source_session_id or ""),
        "topicId": str(topic_id or ""),
        "payload": dict(payload),
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
