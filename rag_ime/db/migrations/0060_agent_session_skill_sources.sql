ALTER TABLE agent_sessions
ADD COLUMN pi_skills_enabled INTEGER NOT NULL DEFAULT 0
CHECK (pi_skills_enabled IN (0, 1));

ALTER TABLE agent_sessions
ADD COLUMN codex_skills_enabled INTEGER NOT NULL DEFAULT 0
CHECK (codex_skills_enabled IN (0, 1));
