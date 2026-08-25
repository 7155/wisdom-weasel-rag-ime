CREATE TABLE IF NOT EXISTS agent_room_partner_dispatches (
    child_dispatch_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    root_id TEXT NOT NULL,
    parent_dispatch_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    source_participant_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    target_participant_id TEXT NOT NULL,
    target_session_id TEXT NOT NULL,
    target_session_turn_id TEXT NOT NULL DEFAULT '',
    work_item_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'prepared'
        CHECK (status IN (
            'prepared', 'dispatched', 'review', 'blocked',
            'failed', 'aborted', 'accepted', 'returned', 'cancelled'
        )),
    result_text TEXT NOT NULL DEFAULT '',
    completion_source TEXT NOT NULL DEFAULT '',
    post_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    wake_generation INTEGER NOT NULL DEFAULT 0,
    wake_schedule_id TEXT NOT NULL DEFAULT '',
    wake_state TEXT NOT NULL DEFAULT 'none'
        CHECK (wake_state IN ('none', 'pending', 'scheduled', 'delivered', 'failed', 'cancelled')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    UNIQUE(room_id, root_id, tool_call_id)
);

CREATE INDEX IF NOT EXISTS idx_room_partner_dispatches_work
ON agent_room_partner_dispatches(work_item_id, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_room_partner_dispatches_root
ON agent_room_partner_dispatches(room_id, root_id, status, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_room_partner_dispatches_wake
ON agent_room_partner_dispatches(wake_state, updated_at_ms);
