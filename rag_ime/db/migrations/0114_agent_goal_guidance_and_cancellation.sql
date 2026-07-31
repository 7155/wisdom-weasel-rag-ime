CREATE TABLE agent_thread_goal_events_v114 (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    objective TEXT NOT NULL,
    success_criteria TEXT NOT NULL DEFAULT '',
    evidence_expectations_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK (
        status IN ('active', 'paused', 'completed', 'cancelled', 'cleared')
    ),
    token_budget INTEGER,
    time_budget_ms INTEGER,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    completion_audit_id TEXT,
    cancellation_audit_id TEXT,
    actor TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    CHECK (token_budget IS NULL OR token_budget > 0),
    CHECK (time_budget_ms IS NULL OR time_budget_ms > 0),
    CHECK (tokens_used >= 0),
    CHECK (elapsed_ms >= 0),
    UNIQUE(session_id, sequence)
);

INSERT INTO agent_thread_goal_events_v114(
    event_id, session_id, goal_id, sequence, objective, status,
    token_budget, time_budget_ms, tokens_used, elapsed_ms,
    completion_audit_id, actor, created_at_ms
)
SELECT
    event_id, session_id, goal_id, sequence, objective, status,
    token_budget, time_budget_ms, tokens_used, elapsed_ms,
    completion_audit_id, actor, created_at_ms
FROM agent_thread_goal_events;

CREATE TABLE agent_goal_usage_receipts_v114 (
    receipt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    turn_id TEXT NOT NULL DEFAULT '',
    source_event_id TEXT NOT NULL DEFAULT '',
    token_delta INTEGER NOT NULL,
    elapsed_delta_ms INTEGER NOT NULL,
    goal_event_id TEXT NOT NULL REFERENCES agent_thread_goal_events_v114(event_id),
    created_at_ms INTEGER NOT NULL,
    CHECK (token_delta >= 0),
    CHECK (elapsed_delta_ms >= 0),
    UNIQUE(session_id, idempotency_key)
);

INSERT INTO agent_goal_usage_receipts_v114(
    receipt_id, session_id, goal_id, idempotency_key, turn_id,
    source_event_id, token_delta, elapsed_delta_ms, goal_event_id,
    created_at_ms
)
SELECT
    receipt_id, session_id, goal_id, idempotency_key, turn_id,
    source_event_id, token_delta, elapsed_delta_ms, goal_event_id,
    created_at_ms
FROM agent_goal_usage_receipts;

DROP TABLE agent_goal_usage_receipts;
DROP TABLE agent_thread_goal_events;
ALTER TABLE agent_thread_goal_events_v114 RENAME TO agent_thread_goal_events;
ALTER TABLE agent_goal_usage_receipts_v114 RENAME TO agent_goal_usage_receipts;

CREATE INDEX idx_agent_thread_goal_events_session_sequence
ON agent_thread_goal_events(session_id, sequence DESC);

CREATE INDEX idx_agent_thread_goal_events_goal_sequence
ON agent_thread_goal_events(goal_id, sequence DESC);

CREATE INDEX idx_agent_goal_usage_receipts_session_created
ON agent_goal_usage_receipts(session_id, created_at_ms DESC);

CREATE TABLE agent_goal_cancellation_audits (
    audit_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    cancelled_by TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX idx_agent_goal_cancellation_audits_session_created
ON agent_goal_cancellation_audits(session_id, created_at_ms DESC);
