ALTER TABLE agent_message_media RENAME TO agent_message_media_v118;
ALTER TABLE agent_media RENAME TO agent_media_v118;

CREATE TABLE agent_media (
    media_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE CASCADE,
    room_id TEXT REFERENCES agent_rooms(id) ON DELETE CASCADE,
    owner_type TEXT NOT NULL DEFAULT 'session' CHECK (owner_type IN ('session', 'room')),
    owner_id TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    storage_name TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL CHECK (mime_type IN (
        'image/png', 'image/jpeg', 'image/gif', 'image/webp',
        'audio/mpeg', 'audio/mp4', 'audio/wav',
        'application/pdf', 'text/plain', 'text/markdown', 'text/html',
        'text/x-diff', 'text/x-patch'
    )),
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    duration_ms INTEGER,
    thumbnail_media_id TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('user_attachment', 'tool_result', 'managed_asset')),
    origin_tool TEXT NOT NULL DEFAULT '',
    origin_receipt_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    CHECK (
        (owner_type = 'session' AND session_id IS NOT NULL AND room_id IS NULL)
        OR (owner_type = 'room' AND room_id IS NOT NULL AND session_id IS NULL)
    )
);

INSERT INTO agent_media(
    media_id, session_id, room_id, owner_type, owner_id,
    file_name, storage_name, mime_type, byte_size, sha256,
    width, height, duration_ms, thumbnail_media_id, origin,
    origin_tool, origin_receipt_id, created_at_ms
)
SELECT
    media_id, session_id, NULL, 'session', session_id,
    file_name, storage_name, mime_type, byte_size, sha256,
    width, height, duration_ms, thumbnail_media_id, origin,
    origin_tool, origin_receipt_id, created_at_ms
FROM agent_media_v118;

CREATE TABLE agent_message_media (
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    pi_entry_id TEXT NOT NULL,
    turn_id TEXT NOT NULL DEFAULT '',
    media_id TEXT NOT NULL REFERENCES agent_media(media_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, pi_entry_id, media_id)
);

INSERT INTO agent_message_media(
    session_id, pi_entry_id, turn_id, media_id, ordinal, created_at_ms
)
SELECT session_id, pi_entry_id, turn_id, media_id, ordinal, created_at_ms
FROM agent_message_media_v118;

DROP TABLE agent_message_media_v118;
DROP TABLE agent_media_v118;

CREATE INDEX idx_agent_media_owner_recent
ON agent_media(owner_type, owner_id, created_at_ms DESC);

CREATE INDEX idx_agent_media_owner_sha
ON agent_media(owner_type, owner_id, sha256);

CREATE INDEX idx_agent_media_session_recent
ON agent_media(session_id, created_at_ms DESC);

CREATE INDEX idx_agent_message_media_entry
ON agent_message_media(session_id, pi_entry_id, ordinal);
