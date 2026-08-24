ALTER TABLE agent_room_work_events RENAME TO agent_room_work_events_legacy_0159;

DROP INDEX IF EXISTS idx_agent_room_work_events_room;

CREATE TABLE agent_room_work_events (
    event_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES agent_room_work_items(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'assigned',
        'accepted',
        'submitted',
        'returned',
        'completed',
        'blocked',
        'escalated',
        'assignment_failed',
        'cancelled',
        'reassigned',
        'resumed',
        'failed',
        'abandoned'
    )),
    actor_participant_id TEXT NOT NULL
        REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    UNIQUE(work_id, sequence)
);

INSERT INTO agent_room_work_events(
    event_id,
    work_id,
    room_id,
    sequence,
    event_type,
    actor_participant_id,
    payload_json,
    created_at_ms
)
SELECT
    event_id,
    work_id,
    room_id,
    sequence,
    event_type,
    actor_participant_id,
    payload_json,
    created_at_ms
FROM agent_room_work_events_legacy_0159;

DROP TABLE agent_room_work_events_legacy_0159;

CREATE INDEX idx_agent_room_work_events_room
ON agent_room_work_events(room_id, created_at_ms DESC, event_id DESC);
