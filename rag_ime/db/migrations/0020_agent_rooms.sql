CREATE TABLE IF NOT EXISTS agent_rooms (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    routing_policy TEXT NOT NULL CHECK (routing_policy IN ('manual_mentions', 'moderator')),
    moderator_participant_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    room_file TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    last_event_sequence INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_agent_rooms_recent
ON agent_rooms(status, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_room_participants (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL UNIQUE REFERENCES agent_sessions(id) ON DELETE RESTRICT,
    role_id TEXT NOT NULL,
    role_version TEXT NOT NULL,
    display_name TEXT NOT NULL,
    participant_status TEXT NOT NULL CHECK (participant_status IN ('active', 'muted', 'removed')),
    ordinal INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    last_spoke_at_ms INTEGER,
    UNIQUE(room_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_agent_room_participants_room
ON agent_room_participants(room_id, participant_status, ordinal);

CREATE TABLE IF NOT EXISTS agent_room_events (
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
        'turn_completed',
        'turn_failed',
        'snapshot_required'
    )),
    participant_id TEXT REFERENCES agent_room_participants(id) ON DELETE SET NULL,
    source_session_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(room_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_room_events_room_sequence
ON agent_room_events(room_id, sequence DESC);
