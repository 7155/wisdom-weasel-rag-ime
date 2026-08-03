ALTER TABLE agent_subagent_batches
ADD COLUMN causal_generation INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_background_jobs
ADD COLUMN causal_room_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN causal_root_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN causal_generation INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_background_jobs
ADD COLUMN causal_task_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN causal_dispatch_id TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_agent_subagent_batches_room_quiescence
ON agent_subagent_batches(causal_root_id, causal_generation, causal_dispatch_id, state)
WHERE room_bound = 1 AND causal_root_id <> '';

CREATE INDEX idx_agent_background_jobs_room_quiescence
ON agent_background_jobs(causal_root_id, causal_generation, causal_dispatch_id, status)
WHERE room_bound = 1 AND causal_root_id <> '';
