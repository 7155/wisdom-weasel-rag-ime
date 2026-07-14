ALTER TABLE agent_approvals RENAME TO agent_approvals_before_external_supervisor;

DROP INDEX IF EXISTS idx_agent_approvals_session_state;

CREATE TABLE agent_approvals (
    approval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    preview_json TEXT NOT NULL DEFAULT '{}',
    risk_level TEXT NOT NULL CHECK (risk_level IN ('R1', 'R2', 'R3')),
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'external_pending', 'rejected', 'expired', 'stale', 'applied', 'failed')),
    requested_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    decided_at_ms INTEGER,
    decided_by TEXT NOT NULL DEFAULT '',
    receipt_json TEXT
);

INSERT INTO agent_approvals(
    approval_id,
    session_id,
    tool_name,
    operation,
    payload_sha256,
    preview_json,
    risk_level,
    state,
    requested_at_ms,
    expires_at_ms,
    decided_at_ms,
    decided_by,
    receipt_json
)
SELECT
    approval_id,
    session_id,
    tool_name,
    operation,
    payload_sha256,
    preview_json,
    risk_level,
    state,
    requested_at_ms,
    expires_at_ms,
    decided_at_ms,
    decided_by,
    receipt_json
FROM agent_approvals_before_external_supervisor;

DROP TABLE agent_approvals_before_external_supervisor;

CREATE INDEX idx_agent_approvals_session_state
ON agent_approvals(session_id, state, requested_at_ms DESC);
