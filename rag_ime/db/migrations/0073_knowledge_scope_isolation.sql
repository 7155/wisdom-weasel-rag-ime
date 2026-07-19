ALTER TABLE agent_memory_sources ADD COLUMN knowledge_domain TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE agent_memory_sources ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE agent_memory_sources ADD COLUMN scope_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_memory_sources ADD COLUMN visibility TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE agent_memory_sources ADD COLUMN authorization_revision TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_memory_sources ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_memory_sources ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy'
    CHECK (scope_mode IN ('legacy', 'authoritative', 'quarantined'));

ALTER TABLE agent_memory_evidence ADD COLUMN owner_kind TEXT NOT NULL DEFAULT 'user';
ALTER TABLE agent_memory_evidence ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE agent_memory_evidence ADD COLUMN knowledge_domain TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE agent_memory_evidence ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE agent_memory_evidence ADD COLUMN scope_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_memory_evidence ADD COLUMN visibility TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE agent_memory_evidence ADD COLUMN authorization_revision TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_memory_evidence ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_memory_evidence ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy'
    CHECK (scope_mode IN ('legacy', 'authoritative', 'quarantined'));

ALTER TABLE memory_items ADD COLUMN knowledge_domain TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_items ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_items ADD COLUMN scope_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_items ADD COLUMN visibility TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_items ADD COLUMN authorization_revision TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_items ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_items ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy'
    CHECK (scope_mode IN ('legacy', 'authoritative', 'quarantined'));

ALTER TABLE memory_atoms ADD COLUMN knowledge_domain TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_atoms ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_atoms ADD COLUMN scope_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_atoms ADD COLUMN visibility TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_atoms ADD COLUMN authorization_revision TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_atoms ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_atoms ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy'
    CHECK (scope_mode IN ('legacy', 'authoritative', 'quarantined'));

ALTER TABLE memory_books ADD COLUMN knowledge_domain TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_books ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_books ADD COLUMN scope_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_books ADD COLUMN visibility TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_books ADD COLUMN authorization_revision TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_books ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_books ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy'
    CHECK (scope_mode IN ('legacy', 'authoritative', 'quarantined'));

ALTER TABLE memory_retrieval_docs ADD COLUMN knowledge_domain TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_retrieval_docs ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_retrieval_docs ADD COLUMN scope_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_retrieval_docs ADD COLUMN visibility TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE memory_retrieval_docs ADD COLUMN authorization_revision TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_retrieval_docs ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_retrieval_docs ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy'
    CHECK (scope_mode IN ('legacy', 'authoritative', 'quarantined'));

DROP INDEX IF EXISTS idx_memory_atoms_one_current_claim;
CREATE UNIQUE INDEX idx_memory_atoms_one_current_claim
ON memory_atoms(
    knowledge_domain, owner_kind, owner_id, scope_kind, scope_id,
    claim_key, COALESCE(scope_project, ''), COALESCE(scope_app, ''), kind
)
WHERE claim_key <> '' AND claim_state = 'current'
  AND status IN ('active', 'approved');

CREATE INDEX idx_memory_retrieval_docs_scope_status
ON memory_retrieval_docs(
    scope_mode, knowledge_domain, scope_kind, scope_id,
    owner_kind, owner_id, status, updated_at_ms DESC
);

CREATE TABLE knowledge_scope_quarantine (
    quarantine_id TEXT PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    observed_scope_json TEXT NOT NULL DEFAULT '{}',
    first_observed_at_ms INTEGER NOT NULL,
    last_observed_at_ms INTEGER NOT NULL,
    observation_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source_table, source_id, reason_code)
);

CREATE INDEX idx_knowledge_scope_quarantine_reason
ON knowledge_scope_quarantine(reason_code, last_observed_at_ms DESC);

CREATE TABLE knowledge_shadow_diffs (
    diff_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    query_hash TEXT NOT NULL,
    primary_refs_json TEXT NOT NULL,
    shadow_refs_json TEXT NOT NULL,
    added_refs_json TEXT NOT NULL,
    removed_refs_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(root_id, session_id, query_hash, primary_refs_json, shadow_refs_json)
);
