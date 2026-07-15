CREATE TABLE IF NOT EXISTS agent_artifacts (
    id TEXT PRIMARY KEY,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    media_type TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    append_only INTEGER NOT NULL CHECK (append_only IN (0, 1)),
    byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL DEFAULT '',
    record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(owner_kind, owner_id, artifact_kind)
);

CREATE INDEX IF NOT EXISTS idx_agent_artifacts_owner
ON agent_artifacts(owner_kind, owner_id, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_artifact_snapshots (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_artifacts(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    storage_key TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
