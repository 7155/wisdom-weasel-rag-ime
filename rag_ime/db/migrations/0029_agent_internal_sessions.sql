ALTER TABLE agent_sessions
ADD COLUMN session_kind TEXT NOT NULL DEFAULT 'conversation'
CHECK (session_kind IN ('conversation', 'subagent_runtime'));

UPDATE agent_sessions
SET session_kind = 'subagent_runtime'
WHERE id IN (SELECT child_session_id FROM agent_subagent_runs);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_kind_status_recent
ON agent_sessions(session_kind, status, updated_at_ms DESC);
