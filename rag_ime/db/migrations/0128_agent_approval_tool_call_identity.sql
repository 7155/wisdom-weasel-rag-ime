ALTER TABLE agent_approvals
ADD COLUMN tool_call_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_agent_approvals_tool_call
ON agent_approvals(session_id, tool_call_id, requested_at_ms ASC)
WHERE tool_call_id <> '';
