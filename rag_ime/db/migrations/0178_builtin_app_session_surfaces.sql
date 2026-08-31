-- Expand the Session surface discriminator without rebuilding its parent
-- table, so every existing row, child foreign key and unrelated index keeps
-- the same identity.  The v177 compatibility column is removed in the same
-- append-only migration after its values are copied.
DROP INDEX idx_agent_sessions_surface_recent;

ALTER TABLE agent_sessions
RENAME COLUMN surface_kind TO surface_kind_v177;

ALTER TABLE agent_sessions
ADD COLUMN surface_kind TEXT NOT NULL DEFAULT 'agent'
CHECK (surface_kind IN ('agent', 'extension_app', 'builtin_app'));

UPDATE agent_sessions
SET surface_kind = surface_kind_v177;

ALTER TABLE agent_sessions
DROP COLUMN surface_kind_v177;

CREATE INDEX idx_agent_sessions_surface_recent
ON agent_sessions(
    surface_kind,
    owner_app_id,
    surface_key,
    status,
    updated_at_ms DESC,
    id DESC
);
