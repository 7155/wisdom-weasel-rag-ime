CREATE TABLE IF NOT EXISTS collaboration_profile_candidates (
    candidate_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    files_json TEXT NOT NULL,
    signer_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    pipeline_stage TEXT NOT NULL CHECK (
        pipeline_stage IN ('inspected', 'validated', 'compiled', 'dry_run', 'staged')
    ),
    compile_receipt_id TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_collaboration_profile_candidate_hash
ON collaboration_profile_candidates(content_hash);

CREATE TABLE IF NOT EXISTS collaboration_profile_versions (
    content_hash TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    files_json TEXT NOT NULL,
    signer_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    compile_receipt_id TEXT NOT NULL,
    revoked_at_ms INTEGER,
    revoke_reason TEXT NOT NULL DEFAULT '',
    staged_at_ms INTEGER NOT NULL,
    UNIQUE(profile_id, profile_version)
);

CREATE TABLE IF NOT EXISTS collaboration_profile_compile_receipts (
    receipt_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    binding_revision TEXT NOT NULL,
    baseline_capabilities_json TEXT NOT NULL,
    requested_capabilities_json TEXT NOT NULL,
    effective_capabilities_json TEXT NOT NULL,
    rejected_capabilities_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS collaboration_profile_active_pointers (
    profile_id TEXT PRIMARY KEY,
    active_content_hash TEXT,
    previous_content_hash TEXT,
    pointer_revision INTEGER NOT NULL CHECK (pointer_revision >= 1),
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(active_content_hash) REFERENCES collaboration_profile_versions(content_hash),
    FOREIGN KEY(previous_content_hash) REFERENCES collaboration_profile_versions(content_hash)
);

CREATE TABLE IF NOT EXISTS collaboration_profile_activation_receipts (
    receipt_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('activate', 'rollback', 'revoke')),
    from_content_hash TEXT,
    to_content_hash TEXT,
    pointer_revision INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_collaboration_profile_versions_profile
ON collaboration_profile_versions(profile_id, staged_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_collaboration_profile_activation_recent
ON collaboration_profile_activation_receipts(profile_id, created_at_ms DESC);
