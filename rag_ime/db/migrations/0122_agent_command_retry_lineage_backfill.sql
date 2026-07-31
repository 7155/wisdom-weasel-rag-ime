UPDATE agent_command_receipts
SET semantic_payload_sha256 = payload_sha256
WHERE semantic_payload_sha256 = '';
