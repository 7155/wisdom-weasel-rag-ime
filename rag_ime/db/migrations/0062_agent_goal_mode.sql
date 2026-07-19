ALTER TABLE agent_plan_events
ADD COLUMN position INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_plan_events
ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1));

CREATE TABLE IF NOT EXISTS agent_plan_state_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'review', 'approved', 'executing', 'completed', 'cancelled')
    ),
    actor TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_plan_state_events_session_sequence
ON agent_plan_state_events(session_id, sequence DESC);

CREATE TABLE IF NOT EXISTS agent_thread_goal_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'completed', 'cleared')),
    token_budget INTEGER,
    time_budget_ms INTEGER,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    completion_audit_id TEXT,
    actor TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    CHECK (token_budget IS NULL OR token_budget > 0),
    CHECK (time_budget_ms IS NULL OR time_budget_ms > 0),
    CHECK (tokens_used >= 0),
    CHECK (elapsed_ms >= 0),
    UNIQUE(session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_thread_goal_events_session_sequence
ON agent_thread_goal_events(session_id, sequence DESC);

CREATE INDEX IF NOT EXISTS idx_agent_thread_goal_events_goal_sequence
ON agent_thread_goal_events(goal_id, sequence DESC);

CREATE TABLE IF NOT EXISTS agent_goal_completion_audits (
    audit_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    completed_by TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_goal_completion_audits_session_created
ON agent_goal_completion_audits(session_id, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_goal_usage_receipts (
    receipt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    turn_id TEXT NOT NULL DEFAULT '',
    source_event_id TEXT NOT NULL DEFAULT '',
    token_delta INTEGER NOT NULL,
    elapsed_delta_ms INTEGER NOT NULL,
    goal_event_id TEXT NOT NULL REFERENCES agent_thread_goal_events(event_id),
    created_at_ms INTEGER NOT NULL,
    CHECK (token_delta >= 0),
    CHECK (elapsed_delta_ms >= 0),
    UNIQUE(session_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_goal_usage_receipts_session_created
ON agent_goal_usage_receipts(session_id, created_at_ms DESC);
