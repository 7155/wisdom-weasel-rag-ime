CREATE TABLE IF NOT EXISTS agent_room_work_items (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL DEFAULT '',
    root_turn_id TEXT NOT NULL DEFAULT '',
    root_work_id TEXT NOT NULL,
    parent_work_id TEXT REFERENCES agent_room_work_items(id) ON DELETE RESTRICT,
    objective TEXT NOT NULL,
    expected_output TEXT NOT NULL,
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
    accountable_participant_id TEXT NOT NULL
        REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    current_owner_participant_id TEXT NOT NULL
        REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    offered_to_participant_id TEXT
        REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    created_by_participant_id TEXT NOT NULL
        REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    client_message_id TEXT NOT NULL,
    assignment_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'active', 'review', 'blocked', 'done', 'failed', 'cancelled'
    )),
    depth INTEGER NOT NULL CHECK (depth BETWEEN 1 AND 3),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision BETWEEN 0 AND 2),
    result_summary TEXT NOT NULL DEFAULT '',
    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    blocker_json TEXT NOT NULL DEFAULT '{}',
    accepted_turn_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    UNIQUE(room_id, created_by_participant_id, client_message_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_room_work_items_room
ON agent_room_work_items(room_id, state, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_agent_room_work_items_root
ON agent_room_work_items(root_work_id, created_at_ms ASC);

CREATE INDEX IF NOT EXISTS idx_agent_room_work_items_owner
ON agent_room_work_items(current_owner_participant_id, state, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_room_work_events (
    event_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES agent_room_work_items(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'assigned',
        'accepted',
        'submitted',
        'returned',
        'completed',
        'blocked',
        'escalated',
        'assignment_failed',
        'cancelled'
    )),
    actor_participant_id TEXT NOT NULL
        REFERENCES agent_room_participants(id) ON DELETE RESTRICT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    UNIQUE(work_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_room_work_events_room
ON agent_room_work_events(room_id, created_at_ms DESC, event_id DESC);

ALTER TABLE agent_room_intercom_messages
ADD COLUMN work_item_id TEXT REFERENCES agent_room_work_items(id) ON DELETE SET NULL;

ALTER TABLE agent_room_intercom_messages
ADD COLUMN work_action TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_agent_room_intercom_work
ON agent_room_intercom_messages(work_item_id, created_at_ms ASC);

CREATE TABLE IF NOT EXISTS agent_room_delivery_cursors (
    room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    participant_id TEXT NOT NULL
        REFERENCES agent_room_participants(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL DEFAULT '',
    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(room_id, participant_id, topic_id)
);
