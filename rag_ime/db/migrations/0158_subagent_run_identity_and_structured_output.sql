ALTER TABLE agent_subagent_runs
ADD COLUMN logical_node_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN attempt_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number >= 1);

ALTER TABLE agent_subagent_runs
ADD COLUMN predecessor_attempt_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN owner_run_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN parent_run_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN depth INTEGER NOT NULL DEFAULT 1 CHECK (depth BETWEEN 1 AND 2);

ALTER TABLE agent_subagent_runs
ADD COLUMN launch_digest_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_subagent_runs
ADD COLUMN structured_output_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_subagent_runs
ADD COLUMN structured_output_tool_call_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN structured_output_error TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN structured_output_validated_at_ms INTEGER;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_subagent_runs_node_attempt
ON agent_subagent_runs(logical_node_id, attempt_number)
WHERE logical_node_id <> '';

CREATE INDEX IF NOT EXISTS idx_agent_subagent_runs_parent_run
ON agent_subagent_runs(parent_run_id, created_at_ms);
