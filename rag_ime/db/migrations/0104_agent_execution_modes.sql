ALTER TABLE agent_sessions
ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'per_action'
CHECK (execution_mode IN ('read_only', 'per_action', 'workspace_managed', 'full_trust'));

ALTER TABLE agent_sessions
ADD COLUMN workspace_scope_sha256 TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_sessions
ADD COLUMN workspace_scope_granted_at_ms INTEGER NOT NULL DEFAULT 0;

UPDATE agent_sessions
SET execution_mode = 'read_only'
WHERE tool_profile_version = 'subagent-readonly-v1';

UPDATE agent_sessions
SET execution_mode = 'full_trust',
    tool_profile_version = 'control-center-v1',
    workspace_scope_sha256 = '',
    workspace_scope_granted_at_ms = 0
WHERE tool_profile_version = 'control-center-auto-approve-v1';
