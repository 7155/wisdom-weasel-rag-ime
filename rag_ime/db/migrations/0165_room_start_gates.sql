-- Durable Room-only start confirmation.  This is a routing fence, not an
-- approval record and does not alter ordinary Session lifecycle or policy.
CREATE TABLE IF NOT EXISTS agent_room_start_gates (
    room_id TEXT PRIMARY KEY REFERENCES agent_rooms(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed')),
    objective_text TEXT NOT NULL DEFAULT '',
    objective_sha256 TEXT NOT NULL DEFAULT '',
    target_participant_ids_json TEXT NOT NULL DEFAULT '[]',
    work_item_id TEXT NOT NULL DEFAULT '',
    root_id TEXT NOT NULL DEFAULT '',
    confirmation_text TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    confirmed_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_agent_room_start_gates_status
ON agent_room_start_gates(status, updated_at_ms DESC);
