CREATE TABLE IF NOT EXISTS agent_message_block_sidecars (
    block_ref TEXT PRIMARY KEY CHECK (length(block_ref) > 0),
    block_id TEXT NOT NULL CHECK (length(block_id) > 0),
    message_id TEXT NOT NULL CHECK (length(message_id) > 0),
    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
    turn_id TEXT NOT NULL DEFAULT '',
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    task_id TEXT NOT NULL DEFAULT '',
    invocation_id TEXT NOT NULL DEFAULT '',
    generation INTEGER NOT NULL CHECK (generation >= 0),
    block_type TEXT NOT NULL CHECK (length(block_type) > 0),
    visibility TEXT NOT NULL CHECK (visibility IN ('private_session','room_post','root_post')),
    lifecycle_status TEXT NOT NULL CHECK (lifecycle_status IN ('active','revoked','cancelled')),
    digest TEXT NOT NULL CHECK (length(digest) = 64),
    summary TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    raw_bytes INTEGER NOT NULL CHECK (raw_bytes >= 0),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, message_id, block_id, generation)
);

CREATE INDEX IF NOT EXISTS idx_agent_block_sidecars_message
ON agent_message_block_sidecars(session_id, message_id, generation, lifecycle_status);

CREATE INDEX IF NOT EXISTS idx_agent_block_sidecars_root
ON agent_message_block_sidecars(root_id, generation, lifecycle_status, created_at_ms);

CREATE TABLE IF NOT EXISTS agent_block_projection_receipts (
    receipt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
    message_id TEXT NOT NULL CHECK (length(message_id) > 0),
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    before_bytes INTEGER NOT NULL CHECK (before_bytes >= 0),
    after_bytes INTEGER NOT NULL CHECK (after_bytes >= 0),
    estimated_tokens_before INTEGER NOT NULL CHECK (estimated_tokens_before >= 0),
    estimated_tokens_after INTEGER NOT NULL CHECK (estimated_tokens_after >= 0),
    block_count INTEGER NOT NULL CHECK (block_count >= 0),
    projection_hash TEXT NOT NULL CHECK (length(projection_hash) = 64),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, message_id, generation)
);
