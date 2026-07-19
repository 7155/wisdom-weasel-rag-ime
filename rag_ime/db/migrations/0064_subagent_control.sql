CREATE TABLE IF NOT EXISTS agent_subagent_controls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_subagent_runs(id) ON DELETE CASCADE,
    parent_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    client_action_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN (
        'steer', 'retry', 'resume', 'abort', 'reply'
    )),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL CHECK (state IN ('accepted', 'completed', 'failed')),
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    UNIQUE(run_id, client_action_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_subagent_controls_run_recent
ON agent_subagent_controls(run_id, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_subagent_inbox (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_subagent_runs(id) ON DELETE CASCADE,
    parent_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    child_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('need_decision', 'interview', 'progress')),
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('pending', 'replied', 'observed')),
    response_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER,
    UNIQUE(run_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_subagent_inbox_parent_status_recent
ON agent_subagent_inbox(parent_session_id, status, created_at_ms DESC);
