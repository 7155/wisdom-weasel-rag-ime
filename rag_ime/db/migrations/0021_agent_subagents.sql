CREATE TABLE IF NOT EXISTS agent_subagent_batches (
    id TEXT PRIMARY KEY,
    parent_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    parent_run_id TEXT NOT NULL DEFAULT '',
    context_mode TEXT NOT NULL CHECK (context_mode IN ('fresh', 'fork')),
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'running', 'completed', 'failed', 'aborted', 'timed_out'
    )),
    depth INTEGER NOT NULL CHECK (depth BETWEEN 1 AND 2),
    max_depth INTEGER NOT NULL CHECK (max_depth BETWEEN 1 AND 2),
    abort_requested INTEGER NOT NULL DEFAULT 0 CHECK (abort_requested IN (0, 1)),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_agent_subagent_batches_parent_recent
ON agent_subagent_batches(parent_session_id, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_subagent_runs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES agent_subagent_batches(id) ON DELETE CASCADE,
    child_session_id TEXT NOT NULL UNIQUE REFERENCES agent_sessions(id) ON DELETE RESTRICT,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 1),
    task_text TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'running', 'completed', 'failed', 'aborted', 'timed_out'
    )),
    max_turns INTEGER NOT NULL CHECK (max_turns BETWEEN 1 AND 32),
    max_tool_calls INTEGER NOT NULL CHECK (max_tool_calls BETWEEN 0 AND 64),
    max_total_tokens INTEGER NOT NULL CHECK (max_total_tokens BETWEEN 256 AND 262144),
    max_duration_ms INTEGER NOT NULL CHECK (max_duration_ms BETWEEN 1000 AND 900000),
    max_output_chars INTEGER NOT NULL CHECK (max_output_chars BETWEEN 256 AND 100000),
    turn_count INTEGER NOT NULL DEFAULT 0,
    tool_count INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    started_at_ms INTEGER,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    UNIQUE(batch_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_agent_subagent_runs_state_recent
ON agent_subagent_runs(state, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_subagent_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_subagent_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'queued', 'started', 'progress', 'budget_exceeded',
        'completed', 'failed', 'aborted', 'timed_out'
    )),
    created_at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(run_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_subagent_events_run_sequence
ON agent_subagent_events(run_id, sequence DESC);
