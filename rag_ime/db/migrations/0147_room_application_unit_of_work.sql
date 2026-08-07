CREATE TABLE IF NOT EXISTS room_domain_events (
    event_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    room_sequence INTEGER NOT NULL CHECK (room_sequence > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(room_id, room_sequence)
);

CREATE INDEX IF NOT EXISTS idx_room_domain_events_room_created
ON room_domain_events(room_id, room_sequence);

CREATE TABLE IF NOT EXISTS room_application_outbox (
    outbox_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES room_domain_events(event_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    effect_kind TEXT NOT NULL CHECK (
        effect_kind IN ('project_room', 'wake_room')
    ),
    state TEXT NOT NULL DEFAULT 'pending' CHECK (
        state IN ('pending', 'leased', 'applied', 'retry_wait', 'dead_letter')
    ),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    available_at_ms INTEGER NOT NULL,
    lease_until_ms INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(event_id, effect_kind)
);

CREATE INDEX IF NOT EXISTS idx_room_application_outbox_ready
ON room_application_outbox(state, available_at_ms, room_id, created_at_ms);
