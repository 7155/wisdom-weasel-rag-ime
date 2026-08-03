ALTER TABLE agent_subagent_batches
ADD COLUMN causal_room_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_batches
ADD COLUMN causal_root_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_batches
ADD COLUMN causal_task_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_batches
ADD COLUMN causal_dispatch_id TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_agent_subagent_batches_room_task_recent
ON agent_subagent_batches(
    causal_room_id,
    causal_root_id,
    causal_task_id,
    created_at_ms DESC
)
WHERE room_bound = 1 AND causal_task_id <> '';
