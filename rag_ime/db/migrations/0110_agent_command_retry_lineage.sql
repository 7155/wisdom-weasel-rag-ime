ALTER TABLE agent_command_receipts
ADD COLUMN semantic_payload_sha256 TEXT NOT NULL DEFAULT ''
    CHECK (
        semantic_payload_sha256 = ''
        OR length(semantic_payload_sha256) = 64
    );

ALTER TABLE agent_command_receipts
ADD COLUMN retry_of_client_message_id TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX idx_agent_command_receipts_one_successor
ON agent_command_receipts(
    command_scope,
    scope_id,
    retry_of_client_message_id
)
WHERE retry_of_client_message_id <> '';
