CREATE TABLE IF NOT EXISTS agent_plan_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed')),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_plan_events_session_item_sequence
ON agent_plan_events(session_id, item_id, sequence DESC);

CREATE INDEX IF NOT EXISTS idx_agent_plan_events_session_sequence
ON agent_plan_events(session_id, sequence DESC);
