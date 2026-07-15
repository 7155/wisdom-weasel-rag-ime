CREATE TABLE IF NOT EXISTS agent_configuration_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    revision INTEGER NOT NULL,
    configuration_json TEXT NOT NULL,
    applied_revision INTEGER NOT NULL,
    sync_state TEXT NOT NULL CHECK (sync_state IN ('synchronized', 'pending', 'failed')),
    sync_error TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_control_events (
    sequence INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_control_events_created
ON agent_control_events(created_at_ms DESC);
