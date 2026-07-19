CREATE TABLE IF NOT EXISTS room_v2_shadow_observations (
    id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    task_id TEXT NOT NULL DEFAULT '',
    dispatch_id TEXT NOT NULL DEFAULT '',
    trigger_id TEXT NOT NULL CHECK (length(trigger_id) > 0),
    record_kind TEXT NOT NULL CHECK (length(record_kind) > 0),
    entity_id TEXT NOT NULL CHECK (length(entity_id) > 0),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    payload_json TEXT NOT NULL,
    first_observed_at_ms INTEGER NOT NULL,
    last_observed_at_ms INTEGER NOT NULL,
    UNIQUE(root_id, trigger_id, record_kind, entity_id),
    UNIQUE(root_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_shadow_observations_root
ON room_v2_shadow_observations(root_id, sequence);

CREATE TABLE IF NOT EXISTS room_v2_shadow_legacy_refs (
    source_kind TEXT NOT NULL CHECK (length(source_kind) > 0),
    source_id TEXT NOT NULL CHECK (length(source_id) > 0),
    observation_id TEXT NOT NULL
        REFERENCES room_v2_shadow_observations(id) ON DELETE CASCADE,
    observed_at_ms INTEGER NOT NULL,
    PRIMARY KEY(source_kind, source_id)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_shadow_legacy_refs_observation
ON room_v2_shadow_legacy_refs(observation_id, source_kind, source_id);

CREATE TABLE IF NOT EXISTS room_v2_shadow_quarantine (
    id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL CHECK (length(source_kind) > 0),
    source_id TEXT NOT NULL CHECK (length(source_id) > 0),
    root_id TEXT NOT NULL DEFAULT '',
    reason_code TEXT NOT NULL CHECK (length(reason_code) > 0),
    raw_payload_hash TEXT NOT NULL CHECK (length(raw_payload_hash) = 64),
    raw_payload_json TEXT NOT NULL,
    first_observed_at_ms INTEGER NOT NULL,
    last_observed_at_ms INTEGER NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
    UNIQUE(source_kind, source_id, reason_code, raw_payload_hash)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_shadow_quarantine_reason
ON room_v2_shadow_quarantine(reason_code, first_observed_at_ms, id);
