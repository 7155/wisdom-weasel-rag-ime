CREATE TABLE IF NOT EXISTS agent_room_intercom_messages (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('send', 'ask', 'reply')),
    source_participant_id TEXT NOT NULL REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    target_participant_id TEXT NOT NULL REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    source_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE RESTRICT,
    target_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE RESTRICT,
    source_generation INTEGER NOT NULL CHECK (source_generation >= 0),
    target_generation INTEGER NOT NULL CHECK (target_generation >= 0),
    client_message_id TEXT NOT NULL,
    reply_to_message_id TEXT REFERENCES agent_room_intercom_messages(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'delivering', 'delivered', 'replied', 'failed', 'stale', 'cancelled'
    )),
    content TEXT NOT NULL,
    accepted_turn_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    delivered_at_ms INTEGER,
    replied_at_ms INTEGER,
    UNIQUE(room_id, source_participant_id, client_message_id),
    UNIQUE(reply_to_message_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_room_intercom_queue
ON agent_room_intercom_messages(status, created_at_ms, id);

CREATE INDEX IF NOT EXISTS idx_agent_room_intercom_room
ON agent_room_intercom_messages(room_id, created_at_ms DESC, id DESC);
