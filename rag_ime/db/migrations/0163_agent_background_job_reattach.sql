ALTER TABLE agent_background_jobs
ADD COLUMN raw_output_path TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN exit_status_path TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN temporary_path TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN raw_output_cursor INTEGER NOT NULL DEFAULT 0
CHECK (raw_output_cursor >= 0);
