CREATE TABLE IF NOT EXISTS agent_command_receipts (
    command_scope TEXT NOT NULL
        CHECK (command_scope IN ('session_prompt', 'room_message')),
    scope_id TEXT NOT NULL,
    client_message_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    claim_token TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'accepted', 'failed')),
    response_json TEXT,
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (command_scope, scope_id, client_message_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_command_receipts_updated
ON agent_command_receipts(updated_at_ms DESC);
