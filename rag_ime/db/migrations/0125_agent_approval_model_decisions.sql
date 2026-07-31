CREATE TABLE IF NOT EXISTS agent_approval_model_decisions (
    receipt_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'deny')),
    status TEXT NOT NULL CHECK (status IN ('decided', 'failed_closed')),
    model_provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_profile TEXT NOT NULL,
    thinking_level TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    scope_sha256 TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    rationale_summary TEXT NOT NULL,
    failure_code TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    decided_at_ms INTEGER NOT NULL,
    FOREIGN KEY (approval_id) REFERENCES agent_approvals(approval_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_approval_model_decisions_session
ON agent_approval_model_decisions(session_id, decided_at_ms DESC, receipt_id DESC);

CREATE TRIGGER IF NOT EXISTS agent_approval_model_decisions_immutable_update
BEFORE UPDATE ON agent_approval_model_decisions
BEGIN
    SELECT RAISE(ABORT, 'approval model decision receipts are immutable');
END;

