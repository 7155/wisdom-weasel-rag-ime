-- Lifecycle metadata only. Canonical content remains in memory_atoms,
-- agent_memory_evidence and input_events; no parallel Memory truth store.
CREATE TABLE memory_portable_identity (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    namespace TEXT NOT NULL UNIQUE
);
INSERT INTO memory_portable_identity(singleton, namespace)
VALUES (1, 'paw:' || lower(hex(randomblob(16))));

CREATE TABLE memory_portable_imports (
    namespace TEXT NOT NULL,
    object_kind TEXT NOT NULL CHECK (object_kind IN ('source', 'evidence', 'atom')),
    external_id TEXT NOT NULL,
    project TEXT NOT NULL,
    local_id TEXT NOT NULL,
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    imported_at_ms INTEGER NOT NULL,
    PRIMARY KEY (namespace, object_kind, external_id, project)
);
CREATE INDEX idx_memory_portable_imports_local
ON memory_portable_imports(object_kind, local_id);

-- 0054 already owns memory_atom_evidence_links with a governance-specific
-- schema. Lifecycle portability needs a separate relation because it must
-- work before/without a governance proposal.
CREATE TABLE memory_lifecycle_atom_evidence_links (
    atom_id TEXT NOT NULL REFERENCES memory_atoms(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
    relation TEXT NOT NULL DEFAULT 'source' CHECK (relation IN ('source', 'context')),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (atom_id, evidence_id, relation)
);
CREATE INDEX idx_memory_lifecycle_atom_evidence_links_evidence
ON memory_lifecycle_atom_evidence_links(evidence_id, atom_id);

CREATE TABLE memory_portable_revocations (
    namespace TEXT NOT NULL,
    object_kind TEXT NOT NULL CHECK (object_kind IN ('source', 'evidence', 'atom')),
    external_id TEXT NOT NULL,
    revoked_at_ms INTEGER NOT NULL,
    PRIMARY KEY (namespace, object_kind, external_id)
);

CREATE TABLE memory_capture_exclusions (
    project TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('session', 'source')),
    target_id TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (project, target_kind, target_id)
);

-- The job state/result lives in the EXISTING maintenance receipt table.
-- This supplementary row owns frozen inputs and fencing, not a second queue.
CREATE TABLE memory_refresh_checkpoints (
    job_id TEXT PRIMARY KEY REFERENCES memory_maintenance_jobs(job_id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (operation IN ('daily_report', 'retrieval_projection')),
    batch_id TEXT NOT NULL UNIQUE,
    schedule_key TEXT UNIQUE,
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    source_cursor_json TEXT NOT NULL CHECK (json_valid(source_cursor_json)),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    next_attempt_at_ms INTEGER NOT NULL,
    lease_token TEXT NOT NULL DEFAULT '',
    lease_expires_at_ms INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT NOT NULL DEFAULT '',
    last_success_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX idx_memory_refresh_checkpoints_due
ON memory_refresh_checkpoints(next_attempt_at_ms, lease_expires_at_ms);
