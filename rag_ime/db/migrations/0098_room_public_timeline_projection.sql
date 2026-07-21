CREATE TABLE agent_room_events_v3 (
    event_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    turn_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL CHECK (event_type IN (
        'user_message',
        'route_decision',
        'participant_status',
        'participant_delta',
        'participant_activity',
        'participant_message',
        'room_post',
        'room_config_changed',
        'topic_changed',
        'artifact_changed',
        'turn_completed',
        'turn_failed',
        'snapshot_required'
    )),
    participant_id TEXT REFERENCES agent_room_participants(id) ON DELETE SET NULL,
    source_session_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(room_id, sequence)
);

INSERT INTO agent_room_events_v3(
    event_id, room_id, sequence, turn_id, event_type, participant_id,
    source_session_id, topic_id, created_at_ms, payload_json
)
SELECT
    event_id, room_id, sequence, turn_id, event_type, participant_id,
    source_session_id, topic_id, created_at_ms, payload_json
FROM agent_room_events;

DROP TABLE agent_room_events;
ALTER TABLE agent_room_events_v3 RENAME TO agent_room_events;

CREATE INDEX idx_agent_room_events_room_sequence
ON agent_room_events(room_id, sequence DESC);

CREATE TABLE agent_room_public_projection_receipts (
    projection_key TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX idx_agent_room_public_projection_receipts_room
ON agent_room_public_projection_receipts(room_id, created_at_ms DESC);
