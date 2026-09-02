ALTER TABLE agent_sessions
ADD COLUMN evaluation_snapshot INTEGER NOT NULL DEFAULT 0
CHECK (evaluation_snapshot IN (0, 1));
