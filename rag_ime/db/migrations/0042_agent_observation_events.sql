CREATE TABLE IF NOT EXISTS agent_observation_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    room_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    phase TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER,
    duration_ms REAL,
    privacy_class TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    attributes_json TEXT NOT NULL DEFAULT '{}',
    refs_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_agent_observation_created
ON agent_observation_events(created_at_ms DESC, sequence DESC);

CREATE INDEX IF NOT EXISTS idx_agent_observation_trace
ON agent_observation_events(trace_id, sequence);

CREATE INDEX IF NOT EXISTS idx_agent_observation_session
ON agent_observation_events(session_id, sequence);

CREATE INDEX IF NOT EXISTS idx_agent_observation_room
ON agent_observation_events(room_id, sequence);

CREATE INDEX IF NOT EXISTS idx_agent_observation_category
ON agent_observation_events(category, status, sequence);
