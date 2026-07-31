ALTER TABLE agent_subagent_runs
ADD COLUMN plan_item_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN plan_item_title TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_agent_subagent_runs_plan_item_recent
ON agent_subagent_runs(plan_item_id, created_at_ms DESC)
WHERE plan_item_id <> '';
