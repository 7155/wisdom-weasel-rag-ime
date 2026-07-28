CREATE TABLE IF NOT EXISTS agent_goal_continuation_budgets (
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    epoch INTEGER NOT NULL DEFAULT 1,
    issued_count INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(session_id, goal_id),
    CHECK (epoch >= 1),
    CHECK (issued_count >= 0)
);

CREATE TABLE IF NOT EXISTS agent_goal_continuation_receipts (
    receipt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    issued_index INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    CHECK (epoch >= 1),
    CHECK (issued_index >= 1),
    UNIQUE(session_id, request_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_goal_continuation_receipts_goal
ON agent_goal_continuation_receipts(session_id, goal_id, epoch, issued_index);
