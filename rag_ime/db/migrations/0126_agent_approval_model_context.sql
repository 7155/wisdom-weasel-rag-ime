DROP TRIGGER IF EXISTS agent_approval_model_decisions_immutable_update;

ALTER TABLE agent_approval_model_decisions
ADD COLUMN context_kind TEXT NOT NULL DEFAULT 'session'
CHECK (context_kind IN ('session', 'room'));

ALTER TABLE agent_approval_model_decisions
ADD COLUMN context_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_approval_model_decisions
ADD COLUMN history_entry_count INTEGER NOT NULL DEFAULT 0
CHECK (history_entry_count >= 0);

UPDATE agent_approval_model_decisions
SET context_id = session_id
WHERE context_id = '';

CREATE INDEX IF NOT EXISTS idx_agent_approval_model_decisions_context
ON agent_approval_model_decisions(
    context_kind,
    context_id,
    decided_at_ms ASC,
    receipt_id ASC
);

CREATE TRIGGER IF NOT EXISTS agent_approval_model_decisions_immutable_update
BEFORE UPDATE ON agent_approval_model_decisions
BEGIN
    SELECT RAISE(ABORT, 'approval model decision receipts are immutable');
END;
