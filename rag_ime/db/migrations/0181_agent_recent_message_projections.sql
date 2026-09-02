CREATE TABLE agent_recent_message_projections (
    session_id TEXT PRIMARY KEY
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    transcript_ref TEXT NOT NULL,
    external_session_id TEXT NOT NULL,
    branch_anchor TEXT NOT NULL,
    transcript_device INTEGER NOT NULL,
    transcript_inode INTEGER NOT NULL,
    transcript_size INTEGER NOT NULL CHECK (transcript_size >= 0),
    transcript_mtime_ns INTEGER NOT NULL CHECK (transcript_mtime_ns >= 0),
    transcript_boundary_sha256 TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
);
