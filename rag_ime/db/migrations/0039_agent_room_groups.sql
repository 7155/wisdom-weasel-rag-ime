ALTER TABLE agent_rooms
ADD COLUMN room_kind TEXT NOT NULL DEFAULT 'collaboration'
CHECK (room_kind IN ('collaboration', 'roleplay'));

ALTER TABLE agent_rooms
ADD COLUMN avatar TEXT NOT NULL DEFAULT 'members';

ALTER TABLE agent_rooms
ADD COLUMN description TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_rooms
ADD COLUMN scenario_prompt TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_rooms
ADD COLUMN routing_mode TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_rooms
ADD COLUMN routing_config_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_rooms
ADD COLUMN next_speaker_ordinal INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_rooms
ADD COLUMN active_topic_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_rooms
ADD COLUMN config_revision INTEGER NOT NULL DEFAULT 1;

ALTER TABLE agent_room_events
ADD COLUMN topic_id TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS agent_room_topics (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    topic_status TEXT NOT NULL DEFAULT 'active'
        CHECK (topic_status IN ('active', 'archived')),
    ordinal INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_room_topics_room
ON agent_room_topics(room_id, topic_status, ordinal, created_at_ms);

INSERT INTO agent_room_topics(
    id, room_id, title, summary, topic_status, ordinal, created_at_ms, updated_at_ms
)
SELECT
    'topic:' || lower(hex(randomblob(16))),
    id,
    '主话题',
    '',
    'active',
    0,
    created_at_ms,
    updated_at_ms
FROM agent_rooms
WHERE NOT EXISTS (
    SELECT 1 FROM agent_room_topics WHERE agent_room_topics.room_id = agent_rooms.id
);

UPDATE agent_rooms
SET active_topic_id = (
    SELECT id
    FROM agent_room_topics
    WHERE agent_room_topics.room_id = agent_rooms.id
    ORDER BY ordinal ASC, created_at_ms ASC
    LIMIT 1
)
WHERE active_topic_id = '';

CREATE TABLE IF NOT EXISTS agent_room_artifacts (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    artifact_status TEXT NOT NULL DEFAULT 'active'
        CHECK (artifact_status IN ('active', 'archived')),
    created_by_participant_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_room_artifacts_room
ON agent_room_artifacts(room_id, artifact_status, updated_at_ms DESC);

CREATE TABLE agent_room_events_v2 (
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

INSERT INTO agent_room_events_v2(
    event_id, room_id, sequence, turn_id, event_type, participant_id,
    source_session_id, topic_id, created_at_ms, payload_json
)
SELECT
    event_id, room_id, sequence, turn_id, event_type, participant_id,
    source_session_id, topic_id, created_at_ms, payload_json
FROM agent_room_events;

DROP TABLE agent_room_events;
ALTER TABLE agent_room_events_v2 RENAME TO agent_room_events;

CREATE INDEX idx_agent_room_events_room_sequence
ON agent_room_events(room_id, sequence DESC);
