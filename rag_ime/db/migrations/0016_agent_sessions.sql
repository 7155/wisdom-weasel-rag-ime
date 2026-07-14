CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    pi_session_id TEXT NOT NULL DEFAULT '',
    session_file TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    session_mode TEXT NOT NULL CHECK (session_mode IN ('assistant', 'coordinator')),
    role_id TEXT NOT NULL,
    role_version TEXT NOT NULL,
    model_profile TEXT NOT NULL,
    tool_profile_version TEXT NOT NULL,
    workspace_roots_json TEXT NOT NULL DEFAULT '[]',
    shell_policy_version TEXT NOT NULL DEFAULT 'assistant-no-shell-v1',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    last_opened_at_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('idle', 'active', 'busy', 'faulted', 'archived')),
    archived_at_ms INTEGER,
    message_count INTEGER NOT NULL DEFAULT 0,
    last_message_preview TEXT NOT NULL DEFAULT '',
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_recent
ON agent_sessions(status, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_approvals (
    approval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    preview_json TEXT NOT NULL DEFAULT '{}',
    risk_level TEXT NOT NULL CHECK (risk_level IN ('R1', 'R2', 'R3')),
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'rejected', 'expired', 'stale', 'applied', 'failed')),
    requested_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    decided_at_ms INTEGER,
    decided_by TEXT NOT NULL DEFAULT '',
    receipt_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_approvals_session_state
ON agent_approvals(session_id, state, requested_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_runtime_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL DEFAULT '',
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    redacted_summary TEXT NOT NULL DEFAULT '',
    UNIQUE(session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_events_session_sequence
ON agent_runtime_events(session_id, sequence DESC);
