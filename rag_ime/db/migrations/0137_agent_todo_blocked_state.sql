ALTER TABLE agent_todo_events RENAME TO agent_todo_events_before_blocked_state;

CREATE TABLE agent_todo_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    operation TEXT NOT NULL CHECK (
        operation IN (
            'init',
            'start',
            'done',
            'drop',
            'block',
            'unblock',
            'append',
            'rm',
            'migrate'
        )
    ),
    phases_json TEXT NOT NULL CHECK (json_valid(phases_json)),
    actor TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, revision)
);

INSERT INTO agent_todo_events(
    event_id,
    session_id,
    revision,
    operation,
    phases_json,
    actor,
    created_at_ms
)
SELECT
    event_id,
    session_id,
    revision,
    operation,
    phases_json,
    actor,
    created_at_ms
FROM agent_todo_events_before_blocked_state;

DROP TABLE agent_todo_events_before_blocked_state;

CREATE INDEX idx_agent_todo_events_session_revision
ON agent_todo_events(session_id, revision DESC);
