ALTER TABLE agent_message_block_sidecars
RENAME TO agent_message_block_sidecars_before_lifecycle_v94;

CREATE TABLE agent_message_block_sidecars (
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
    lifecycle_status TEXT NOT NULL CHECK (lifecycle_status IN ('active','completed','revoked','cancelled')),
    digest TEXT NOT NULL CHECK (length(digest) = 64),
    summary TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    raw_bytes INTEGER NOT NULL CHECK (raw_bytes >= 0),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, message_id, block_id, generation)
);

INSERT INTO agent_message_block_sidecars(
    block_ref, block_id, message_id, session_id, turn_id, root_id, task_id,
    invocation_id, generation, block_type, visibility, lifecycle_status,
    digest, summary, raw_json, raw_bytes, created_at_ms, updated_at_ms
)
SELECT
    block_ref, block_id, message_id, session_id, turn_id, root_id, task_id,
    invocation_id, generation, block_type, visibility, lifecycle_status,
    digest, summary, raw_json, raw_bytes, created_at_ms, updated_at_ms
FROM agent_message_block_sidecars_before_lifecycle_v94;

DROP TABLE agent_message_block_sidecars_before_lifecycle_v94;

CREATE INDEX idx_agent_block_sidecars_message
ON agent_message_block_sidecars(session_id, message_id, generation, lifecycle_status);

CREATE INDEX idx_agent_block_sidecars_root
ON agent_message_block_sidecars(root_id, generation, lifecycle_status, created_at_ms);

CREATE TABLE agent_block_message_envelopes (
    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
    message_id TEXT NOT NULL CHECK (length(message_id) > 0),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    message_hash TEXT NOT NULL CHECK (length(message_hash) = 64),
    message_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(session_id, message_id, generation)
);

CREATE INDEX idx_agent_block_message_envelopes_session
ON agent_block_message_envelopes(session_id, created_at_ms, message_id);
