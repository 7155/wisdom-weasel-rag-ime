CREATE TABLE IF NOT EXISTS agent_memory_sources (
    source_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    pi_entry_id TEXT NOT NULL,
    input_event_id INTEGER NOT NULL REFERENCES input_events(id) ON DELETE CASCADE,
    source_role TEXT NOT NULL CHECK (source_role IN ('user', 'tool_receipt')),
    source_revision INTEGER NOT NULL DEFAULT 1,
    canonical_text_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'archived', 'tombstoned')),
    turn_id TEXT NOT NULL DEFAULT '',
    approval_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    superseded_at_ms INTEGER,
    UNIQUE(session_id, pi_entry_id, source_role, source_revision)
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_sources_session_recent
ON agent_memory_sources(session_id, status, created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_agent_memory_sources_input_event
ON agent_memory_sources(input_event_id);
