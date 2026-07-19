CREATE TABLE IF NOT EXISTS room_v2_context_entries (
    entry_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    room_id TEXT NOT NULL CHECK (length(room_id) > 0),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    entry_kind TEXT NOT NULL CHECK (length(entry_kind) > 0),
    source_ref TEXT NOT NULL CHECK (length(source_ref) > 0),
    dedupe_key TEXT NOT NULL CHECK (length(dedupe_key) > 0),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    entry_hash TEXT NOT NULL CHECK (length(entry_hash) = 64),
    content_bytes BLOB NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(root_id, sequence),
    UNIQUE(root_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_context_entries_root
ON room_v2_context_entries(root_id, generation, sequence);

CREATE TABLE IF NOT EXISTS room_v2_posts (
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
        CHECK (publication_source_kind IN ('user', 'room_commit')),
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

CREATE INDEX IF NOT EXISTS idx_room_v2_posts_room
ON room_v2_posts(room_id, created_at_ms, post_id);

CREATE TABLE IF NOT EXISTS room_v2_provider_projection_journals (
    journal_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    room_id TEXT NOT NULL CHECK (length(room_id) > 0),
    binding_id TEXT NOT NULL CHECK (length(binding_id) > 0),
    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
    session_epoch INTEGER NOT NULL CHECK (session_epoch >= 1),
    context_epoch INTEGER NOT NULL CHECK (context_epoch >= 1),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    sealed_through_sequence INTEGER NOT NULL DEFAULT 0
        CHECK (sealed_through_sequence >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    identity_hash TEXT NOT NULL CHECK (length(identity_hash) = 64),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(binding_id, session_epoch, context_epoch)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_provider_projection_journals_session
ON room_v2_provider_projection_journals(session_id, session_epoch, context_epoch);

CREATE TABLE IF NOT EXISTS room_v2_provider_projection_items (
    journal_id TEXT NOT NULL
        REFERENCES room_v2_provider_projection_journals(journal_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    context_entry_id TEXT NOT NULL
        REFERENCES room_v2_context_entries(entry_id) ON DELETE RESTRICT,
    dedupe_key TEXT NOT NULL CHECK (length(dedupe_key) > 0),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    state TEXT NOT NULL CHECK (state IN ('pending', 'sealed')),
    appended_at_ms INTEGER NOT NULL,
    sealed_by_receipt_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(journal_id, sequence),
    UNIQUE(journal_id, context_entry_id),
    UNIQUE(journal_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_provider_projection_items_state
ON room_v2_provider_projection_items(journal_id, state, sequence);

CREATE TABLE IF NOT EXISTS room_v2_provider_projection_receipts (
    receipt_id TEXT PRIMARY KEY,
    journal_id TEXT NOT NULL
        REFERENCES room_v2_provider_projection_journals(journal_id) ON DELETE RESTRICT,
    provider_request_id TEXT NOT NULL CHECK (length(provider_request_id) > 0),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    sealed_through_sequence INTEGER NOT NULL CHECK (sealed_through_sequence >= 1),
    projection_hash TEXT NOT NULL CHECK (length(projection_hash) = 64),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(journal_id, provider_request_id)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_provider_projection_receipts_journal
ON room_v2_provider_projection_receipts(journal_id, sealed_through_sequence);
