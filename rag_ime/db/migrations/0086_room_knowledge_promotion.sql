CREATE TABLE room_v2_knowledge_epochs (
    scope_key TEXT PRIMARY KEY,
    knowledge_epoch INTEGER NOT NULL CHECK(knowledge_epoch>=0),
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_promotion_candidates (
    promotion_candidate_id TEXT PRIMARY KEY,
    evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('private_session','room_post','external_import')),
    evidence_ref TEXT NOT NULL,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    claim_key TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    knowledge_domain TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('project','room','participant','private')),
    promotion_policy TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    conflict_status TEXT NOT NULL CHECK(conflict_status IN ('clear','open')),
    conflict_claim_refs_json TEXT NOT NULL,
    secret_scan_json TEXT NOT NULL,
    risk TEXT NOT NULL CHECK(risk IN ('low','medium','high')),
    nominated_by TEXT NOT NULL,
    candidate_hash TEXT NOT NULL UNIQUE CHECK(length(candidate_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_promotion_approval_receipts (
    approval_receipt_id TEXT PRIMARY KEY,
    promotion_candidate_id TEXT NOT NULL REFERENCES room_v2_promotion_candidates(promotion_candidate_id),
    candidate_hash TEXT NOT NULL,
    authority_ref TEXT NOT NULL,
    conflict_resolution TEXT NOT NULL CHECK(conflict_resolution IN ('none','replace','coexist','reject')),
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    authority_signature TEXT NOT NULL CHECK(length(authority_signature)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_knowledge_claim_versions (
    claim_version_id TEXT PRIMARY KEY,
    claim_identity TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>=1),
    supersedes_version_id TEXT REFERENCES room_v2_knowledge_claim_versions(claim_version_id),
    promotion_candidate_id TEXT NOT NULL REFERENCES room_v2_promotion_candidates(promotion_candidate_id),
    promotion_receipt_id TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_hash TEXT NOT NULL CHECK(length(claim_hash)=64),
    knowledge_domain TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    visibility TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    contradiction_refs_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(claim_identity,version)
);

CREATE TABLE room_v2_promotion_receipts (
    promotion_receipt_id TEXT PRIMARY KEY,
    promotion_candidate_id TEXT NOT NULL REFERENCES room_v2_promotion_candidates(promotion_candidate_id),
    approval_receipt_id TEXT REFERENCES room_v2_promotion_approval_receipts(approval_receipt_id),
    low_risk_rule_id TEXT,
    claim_version_id TEXT NOT NULL UNIQUE REFERENCES room_v2_knowledge_claim_versions(claim_version_id),
    scope_key TEXT NOT NULL,
    knowledge_epoch INTEGER NOT NULL,
    candidate_hash TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_knowledge_claim_pointers (
    claim_identity TEXT PRIMARY KEY,
    current_claim_version_id TEXT REFERENCES room_v2_knowledge_claim_versions(claim_version_id),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('current','revoked','archived','unbound','deleted')),
    scope_key TEXT NOT NULL,
    knowledge_epoch INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_knowledge_index_outbox (
    outbox_id TEXT PRIMARY KEY,
    claim_version_id TEXT NOT NULL REFERENCES room_v2_knowledge_claim_versions(claim_version_id),
    operation TEXT NOT NULL CHECK(operation IN ('index','invalidate','archive','unbind','delete','quarantine_purge')),
    state TEXT NOT NULL CHECK(state IN ('pending','leased','retry_wait','applied','dead_letter')),
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK(max_attempts BETWEEN 1 AND 8),
    available_at_ms INTEGER NOT NULL DEFAULT 0,
    lease_until_ms INTEGER NOT NULL DEFAULT 0,
    projection_receipts_json TEXT NOT NULL DEFAULT '[]',
    last_error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    UNIQUE(claim_version_id,operation,payload_hash)
);

CREATE TABLE room_v2_knowledge_search_projections (
    claim_version_id TEXT PRIMARY KEY REFERENCES room_v2_knowledge_claim_versions(claim_version_id),
    claim_text TEXT NOT NULL,
    claim_hash TEXT NOT NULL,
    knowledge_domain TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    visibility TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    contradiction_refs_json TEXT NOT NULL,
    indexed_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_knowledge_retrieval_receipts (
    retrieval_receipt_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    authorization_revision TEXT NOT NULL,
    query_hash TEXT NOT NULL CHECK(length(query_hash)=64),
    scope_epochs_json TEXT NOT NULL,
    result_refs_json TEXT NOT NULL,
    result_hashes_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_external_import_intakes (
    import_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    scan_status TEXT NOT NULL CHECK(scan_status IN ('allowed','quarantined')),
    finding_codes_json TEXT NOT NULL,
    data_only INTEGER NOT NULL CHECK(data_only=1),
    raw_bytes_stored INTEGER NOT NULL CHECK(raw_bytes_stored=0),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_knowledge_lifecycle_receipts (
    lifecycle_receipt_id TEXT PRIMARY KEY,
    claim_identity TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('revoke','archive','unbind','delete','owner_change')),
    from_claim_version_id TEXT,
    to_claim_version_id TEXT,
    scope_key TEXT NOT NULL,
    knowledge_epoch INTEGER NOT NULL,
    authority_ref TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_knowledge_cache_tombstones (
    tombstone_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    knowledge_epoch INTEGER NOT NULL,
    journal_id TEXT,
    session_id TEXT,
    reason TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    consumed_at_ms INTEGER NOT NULL DEFAULT 0,
    UNIQUE(scope_key,knowledge_epoch,journal_id,session_id)
);

CREATE INDEX idx_room_v2_knowledge_outbox_ready
ON room_v2_knowledge_index_outbox(state,available_at_ms,created_at_ms);

CREATE TRIGGER room_v2_promotion_candidate_no_update BEFORE UPDATE ON room_v2_promotion_candidates BEGIN SELECT RAISE(ABORT,'PromotionCandidate is immutable'); END;
CREATE TRIGGER room_v2_promotion_candidate_no_delete BEFORE DELETE ON room_v2_promotion_candidates BEGIN SELECT RAISE(ABORT,'PromotionCandidate is permanent'); END;
CREATE TRIGGER room_v2_promotion_receipt_no_update BEFORE UPDATE ON room_v2_promotion_receipts BEGIN SELECT RAISE(ABORT,'PromotionReceipt is immutable'); END;
CREATE TRIGGER room_v2_promotion_receipt_no_delete BEFORE DELETE ON room_v2_promotion_receipts BEGIN SELECT RAISE(ABORT,'PromotionReceipt is permanent'); END;
CREATE TRIGGER room_v2_promotion_approval_no_update BEFORE UPDATE ON room_v2_promotion_approval_receipts BEGIN SELECT RAISE(ABORT,'PromotionApprovalReceipt is immutable'); END;
CREATE TRIGGER room_v2_promotion_approval_no_delete BEFORE DELETE ON room_v2_promotion_approval_receipts BEGIN SELECT RAISE(ABORT,'PromotionApprovalReceipt is permanent'); END;
CREATE TRIGGER room_v2_claim_version_no_update BEFORE UPDATE ON room_v2_knowledge_claim_versions BEGIN SELECT RAISE(ABORT,'KnowledgeClaimVersion is immutable'); END;
CREATE TRIGGER room_v2_claim_version_no_delete BEFORE DELETE ON room_v2_knowledge_claim_versions BEGIN SELECT RAISE(ABORT,'KnowledgeClaimVersion is permanent'); END;
CREATE TRIGGER room_v2_retrieval_receipt_no_update BEFORE UPDATE ON room_v2_knowledge_retrieval_receipts BEGIN SELECT RAISE(ABORT,'KnowledgeRetrievalReceipt is immutable'); END;
CREATE TRIGGER room_v2_retrieval_receipt_no_delete BEFORE DELETE ON room_v2_knowledge_retrieval_receipts BEGIN SELECT RAISE(ABORT,'KnowledgeRetrievalReceipt is permanent'); END;
CREATE TRIGGER room_v2_lifecycle_receipt_no_update BEFORE UPDATE ON room_v2_knowledge_lifecycle_receipts BEGIN SELECT RAISE(ABORT,'KnowledgeLifecycleReceipt is immutable'); END;
CREATE TRIGGER room_v2_lifecycle_receipt_no_delete BEFORE DELETE ON room_v2_knowledge_lifecycle_receipts BEGIN SELECT RAISE(ABORT,'KnowledgeLifecycleReceipt is permanent'); END;
