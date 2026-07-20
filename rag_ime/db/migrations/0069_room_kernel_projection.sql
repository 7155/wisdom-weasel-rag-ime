CREATE TABLE IF NOT EXISTS room_kernel_events (
    room_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    entity_kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at_ms INTEGER NOT NULL,
    PRIMARY KEY(room_id, sequence)
);

CREATE TABLE IF NOT EXISTS room_kernel_projection_hashes (
    room_id TEXT NOT NULL,
    projection_kind TEXT NOT NULL,
    projection_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY(room_id, projection_kind, projection_id)
);

CREATE TABLE IF NOT EXISTS room_kernel_posts (
    post_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    idempotency_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(room_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_room_kernel_events_replay
ON room_kernel_events(room_id, sequence);

CREATE INDEX IF NOT EXISTS idx_room_kernel_posts_root
ON room_kernel_posts(room_id, root_id, created_at_ms);
