ALTER TABLE agent_todo_events
RENAME TO agent_todo_events_before_checkpoint_metadata;

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
            'checkpoint',
            'append',
            'rm',
            'migrate'
        )
    ),
    phases_json TEXT NOT NULL CHECK (json_valid(phases_json)),
    actor TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    room_lineage_json TEXT NOT NULL DEFAULT 'null'
        CHECK (
            json_valid(room_lineage_json)
            AND json_type(room_lineage_json) IN ('null', 'object')
        ),
    UNIQUE(session_id, revision)
);

INSERT INTO agent_todo_events(
    event_id,
    session_id,
    revision,
    operation,
    phases_json,
    actor,
    created_at_ms,
    room_lineage_json
)
SELECT
    event_id,
    session_id,
    revision,
    operation,
    phases_json,
    actor,
    created_at_ms,
    room_lineage_json
FROM agent_todo_events_before_checkpoint_metadata;

DROP TABLE agent_todo_events_before_checkpoint_metadata;

CREATE INDEX idx_agent_todo_events_session_revision
ON agent_todo_events(session_id, revision DESC);
