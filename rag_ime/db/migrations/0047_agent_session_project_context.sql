ALTER TABLE agent_sessions
ADD COLUMN project_context_enabled INTEGER NOT NULL DEFAULT 1
CHECK (project_context_enabled IN (0, 1));
