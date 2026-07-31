ALTER TABLE agent_session_tool_policies
ADD COLUMN disclosure_preferences_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_session_tool_policies
ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT 1 CHECK (policy_revision >= 1);
