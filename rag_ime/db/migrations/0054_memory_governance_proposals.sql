CREATE TABLE IF NOT EXISTS memory_governance_proposals (
    proposal_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE RESTRICT,
    project TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL
        CHECK (operation IN ('remember_preview', 'correct_preview', 'forget_preview')),
    target_memory_id TEXT NOT NULL DEFAULT '',
    memory_kind TEXT NOT NULL DEFAULT '',
    proposed_text TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    evidence_ids_json TEXT NOT NULL,
    evidence_snapshot_json TEXT NOT NULL,
    target_snapshot_json TEXT NOT NULL DEFAULT '{}',
    target_state_sha256 TEXT NOT NULL DEFAULT '',
    action_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'preview'
        CHECK (status IN ('preview', 'applied', 'rolled_back', 'expired', 'failed')),
    applied_memory_id TEXT NOT NULL DEFAULT '',
    rollback_json TEXT NOT NULL DEFAULT '{}',
    receipt_json TEXT NOT NULL DEFAULT '{}',
    rollback_receipt_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    applied_at_ms INTEGER,
    rolled_back_at_ms INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_governance_live_idempotency
ON memory_governance_proposals(session_id, idempotency_key)
WHERE status = 'preview';

CREATE INDEX IF NOT EXISTS idx_memory_governance_session_recent
ON memory_governance_proposals(session_id, created_at_ms DESC, proposal_id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_governance_target_history
ON memory_governance_proposals(target_memory_id, created_at_ms DESC, proposal_id DESC)
WHERE target_memory_id <> '';

CREATE TABLE IF NOT EXISTS memory_atom_evidence_links (
    memory_atom_id TEXT NOT NULL REFERENCES memory_atoms(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
    proposal_id TEXT NOT NULL
        REFERENCES memory_governance_proposals(proposal_id) ON DELETE RESTRICT,
    relation TEXT NOT NULL CHECK (relation IN ('supports', 'corrects', 'retracts')),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    provenance_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(proposal_id, evidence_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_memory_atom_evidence_atom
ON memory_atom_evidence_links(memory_atom_id, relation, created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_memory_atom_evidence_evidence
ON memory_atom_evidence_links(evidence_id, memory_atom_id);
