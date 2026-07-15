CREATE TABLE IF NOT EXISTS agent_media (
    media_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL DEFAULT '',
    storage_name TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL CHECK (mime_type IN (
        'image/png', 'image/jpeg', 'image/gif', 'image/webp',
        'audio/mpeg', 'audio/mp4', 'audio/wav',
        'application/pdf', 'text/plain'
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
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_media_session_recent
ON agent_media(session_id, created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_agent_media_session_sha
ON agent_media(session_id, sha256);

CREATE TABLE IF NOT EXISTS agent_message_media (
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    pi_entry_id TEXT NOT NULL,
    turn_id TEXT NOT NULL DEFAULT '',
    media_id TEXT NOT NULL REFERENCES agent_media(media_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, pi_entry_id, media_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_message_media_entry
ON agent_message_media(session_id, pi_entry_id, ordinal);
