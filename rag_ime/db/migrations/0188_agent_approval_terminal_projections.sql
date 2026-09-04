-- Keep one durable, content-free terminal projection authority per approval
-- surface. Runtime events are intentionally retained in a bounded ledger and
-- therefore cannot be the exactly-once owner after a long Session restart.

CREATE TABLE IF NOT EXISTS agent_approval_terminal_projections (
    session_id TEXT NOT NULL
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    approval_id TEXT NOT NULL
        REFERENCES agent_approvals(approval_id) ON DELETE CASCADE,
    projection_kind TEXT NOT NULL
        CHECK (projection_kind IN ('approval_resolved', 'tool_finished')),
    tool_call_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    room_id TEXT NOT NULL DEFAULT '',
    room_root_id TEXT NOT NULL DEFAULT '',
    room_dispatch_id TEXT NOT NULL DEFAULT '',
    room_generation INTEGER NOT NULL DEFAULT 0
        CHECK (room_generation >= 0),
    event_id TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
    projected_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, approval_id, projection_kind),
    UNIQUE (session_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_approval_terminal_projection_tool
ON agent_approval_terminal_projections(
    session_id,
    projection_kind,
    tool_call_id,
    turn_id,
    projected_at_ms
);

CREATE INDEX IF NOT EXISTS idx_agent_approval_terminal_projection_room
ON agent_approval_terminal_projections(
    room_id,
    room_root_id,
    room_dispatch_id,
    room_generation
)
WHERE room_id <> '';
