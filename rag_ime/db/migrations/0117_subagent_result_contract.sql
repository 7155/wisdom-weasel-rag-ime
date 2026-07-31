ALTER TABLE agent_subagent_batches
ADD COLUMN result_delivery_mode TEXT NOT NULL DEFAULT 'inline'
CHECK (result_delivery_mode IN ('inline', 'next_turn'));

ALTER TABLE agent_subagent_runs
ADD COLUMN expected_output TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_runs
ADD COLUMN acceptance_criteria_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE agent_subagent_runs
ADD COLUMN output_schema_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_subagent_runs
ADD COLUMN result_context_scheduled_at_ms INTEGER;

UPDATE agent_subagent_runs
SET updated_at_ms = updated_at_ms + 1;
