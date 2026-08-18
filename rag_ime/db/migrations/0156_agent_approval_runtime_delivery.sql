ALTER TABLE agent_approvals
ADD COLUMN runtime_notified_at_ms INTEGER;

ALTER TABLE agent_approvals
ADD COLUMN runtime_resolution_state TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_agent_approvals_runtime_delivery
ON agent_approvals(session_id, state, runtime_notified_at_ms)
WHERE state IN (
    'external_pending', 'rejected', 'expired', 'stale', 'applied', 'failed'
);
