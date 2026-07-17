ALTER TABLE agent_command_receipts RENAME TO agent_command_receipts_v45;

CREATE TABLE agent_command_receipts (
    command_scope TEXT NOT NULL
        CHECK (command_scope IN ('session_prompt', 'session_rewrite', 'room_message')),
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

INSERT INTO agent_command_receipts(
    command_scope, scope_id, client_message_id, payload_sha256,
    claim_token, state, response_json, error, created_at_ms, updated_at_ms
)
SELECT
    command_scope, scope_id, client_message_id, payload_sha256,
    claim_token, state, response_json, error, created_at_ms, updated_at_ms
FROM agent_command_receipts_v45;

DROP TABLE agent_command_receipts_v45;

CREATE INDEX idx_agent_command_receipts_updated
ON agent_command_receipts(updated_at_ms DESC);
