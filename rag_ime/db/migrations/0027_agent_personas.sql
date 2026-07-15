CREATE TABLE IF NOT EXISTS agent_personas (
    role_id TEXT NOT NULL,
    version TEXT NOT NULL,
    display_name TEXT NOT NULL,
    tagline TEXT NOT NULL,
    summary TEXT NOT NULL,
    traits_json TEXT NOT NULL,
    timeline_model TEXT NOT NULL CHECK (timeline_model IN ('luna', 'terra', 'sol')),
    selectable_modes_json TEXT NOT NULL,
    persona_prompt TEXT NOT NULL,
    visual_profile_json TEXT NOT NULL,
    model_policy TEXT NOT NULL,
    memory_policy TEXT NOT NULL,
    tool_profile_version TEXT NOT NULL,
    safety_policy_version TEXT NOT NULL,
    safety_policy_prompt TEXT NOT NULL,
    tool_policy_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    archived_at_ms INTEGER,
    PRIMARY KEY(role_id, version)
);

CREATE INDEX IF NOT EXISTS idx_agent_personas_status_recent
ON agent_personas(status, updated_at_ms DESC);
