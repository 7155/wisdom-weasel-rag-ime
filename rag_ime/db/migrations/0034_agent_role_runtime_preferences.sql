CREATE TABLE IF NOT EXISTS agent_role_runtime_preferences (
    role_id TEXT NOT NULL,
    role_version TEXT NOT NULL,
    model_profile TEXT NOT NULL,
    thinking_level TEXT NOT NULL CHECK (thinking_level IN (
        'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'
    )),
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(role_id, role_version)
);

ALTER TABLE agent_sessions
ADD COLUMN thinking_level TEXT NOT NULL DEFAULT ''
CHECK (thinking_level IN ('', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'));
