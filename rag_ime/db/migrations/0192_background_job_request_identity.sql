ALTER TABLE agent_background_jobs
ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN idempotency_digest TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX idx_agent_background_jobs_session_idempotency
ON agent_background_jobs(session_id, idempotency_key)
WHERE idempotency_key <> '';
