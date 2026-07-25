ALTER TABLE room_v2_posts RENAME TO room_v2_posts_before_immediate_publication;

CREATE TABLE room_v2_posts (
    post_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL CHECK (length(room_id) > 0),
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    task_id TEXT NOT NULL DEFAULT '',
    dispatch_id TEXT NOT NULL DEFAULT '',
    author_actor_ref TEXT NOT NULL CHECK (length(author_actor_ref) > 0),
    post_kind TEXT NOT NULL CHECK (length(post_kind) > 0),
    visibility TEXT NOT NULL CHECK (visibility IN ('room', 'root')),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) > 0),
    publication_source_kind TEXT NOT NULL
        CHECK (publication_source_kind IN ('user', 'room_post', 'room_commit')),
    publication_source_ref TEXT NOT NULL CHECK (length(publication_source_ref) > 0),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    post_hash TEXT NOT NULL CHECK (length(post_hash) = 64),
    content_bytes BLOB NOT NULL,
    payload_json TEXT NOT NULL,
    context_entry_id TEXT NOT NULL UNIQUE
        REFERENCES room_v2_context_entries(entry_id) ON DELETE RESTRICT,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(root_id, idempotency_key)
);

INSERT INTO room_v2_posts(
    post_id, room_id, root_id, generation, task_id, dispatch_id,
    author_actor_ref, post_kind, visibility, idempotency_key,
    publication_source_kind, publication_source_ref, content_hash,
    post_hash, content_bytes, payload_json, context_entry_id, created_at_ms
)
SELECT
    post_id, room_id, root_id, generation, task_id, dispatch_id,
    author_actor_ref, post_kind, visibility, idempotency_key,
    publication_source_kind, publication_source_ref, content_hash,
    post_hash, content_bytes, payload_json, context_entry_id, created_at_ms
FROM room_v2_posts_before_immediate_publication;

DROP TABLE room_v2_posts_before_immediate_publication;

CREATE INDEX idx_room_v2_posts_room
ON room_v2_posts(room_id, created_at_ms, post_id);
