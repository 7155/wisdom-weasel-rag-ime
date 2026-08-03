-- Make the legacy capture queue independent from Agent Session lifetime.
-- The queue remains a compatibility/audit projection; canonical Memory
-- Evidence is owned by agent_memory_evidence below.
ALTER TABLE memory_source_disposition_events
RENAME TO memory_source_disposition_events_before_canonical_evidence;

ALTER TABLE memory_capture_hints
RENAME TO memory_capture_hints_before_canonical_evidence;

ALTER TABLE agent_memory_sources
RENAME TO agent_memory_sources_before_canonical_evidence;

CREATE TABLE agent_memory_sources (
    source_id TEXT PRIMARY KEY,
    -- Historical provenance, deliberately not a foreign key. Deleting a
    -- Session must never erase or rewrite an immutable source identifier.
    session_id TEXT NOT NULL DEFAULT '',
    pi_entry_id TEXT NOT NULL,
    input_event_id INTEGER NOT NULL
        REFERENCES input_events(id) ON DELETE RESTRICT,
    source_role TEXT NOT NULL CHECK (source_role IN ('user', 'tool_receipt')),
    source_revision INTEGER NOT NULL DEFAULT 1,
    canonical_text_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'archived', 'tombstoned')),
    turn_id TEXT NOT NULL DEFAULT '',
    approval_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    superseded_at_ms INTEGER,
    owner_kind TEXT NOT NULL DEFAULT 'user'
        CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room')),
    owner_id TEXT NOT NULL DEFAULT 'default',
    role_id TEXT NOT NULL DEFAULT '',
    role_version TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'user_final'
        CHECK (source_kind IN (
            'user_final',
            'tool_receipt',
            'session_compaction',
            'session_digest',
            'explicit_memory'
        )),
    trust_class TEXT NOT NULL DEFAULT 'user_claim'
        CHECK (trust_class IN (
            'user_claim',
            'applied_receipt',
            'session_summary',
            'assistant_claim',
            'explicit_command'
        )),
    disposition TEXT NOT NULL DEFAULT 'pending'
        CHECK (disposition IN (
            'pending',
            'remember',
            'not_for_memory',
            'needs_review',
            'consolidated',
            'expired'
        )),
    disposition_reason TEXT NOT NULL DEFAULT '',
    disposition_updated_at_ms INTEGER,
    processed_at_ms INTEGER,
    curation_run_id TEXT NOT NULL DEFAULT '',
    coverage_start_entry_id TEXT NOT NULL DEFAULT '',
    coverage_end_entry_id TEXT NOT NULL DEFAULT '',
    expires_at_ms INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    knowledge_domain TEXT NOT NULL DEFAULT 'legacy',
    scope_kind TEXT NOT NULL DEFAULT 'legacy',
    scope_id TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'legacy',
    authorization_revision TEXT NOT NULL DEFAULT '',
    binding_id TEXT NOT NULL DEFAULT '',
    scope_mode TEXT NOT NULL DEFAULT 'legacy'
        CHECK (scope_mode IN ('legacy', 'authoritative', 'quarantined')),
    UNIQUE(session_id, pi_entry_id, source_role, source_revision)
);

INSERT INTO agent_memory_sources(
    source_id, session_id, pi_entry_id, input_event_id, source_role,
    source_revision, canonical_text_sha256, status, turn_id, approval_id,
    created_at_ms, superseded_at_ms, owner_kind, owner_id, role_id,
    role_version, source_kind, trust_class, disposition, disposition_reason,
    disposition_updated_at_ms, processed_at_ms, curation_run_id,
    coverage_start_entry_id, coverage_end_entry_id, expires_at_ms,
    metadata_json, knowledge_domain, scope_kind, scope_id, visibility,
    authorization_revision, binding_id, scope_mode
)
SELECT
    source_id, session_id, pi_entry_id, input_event_id, source_role,
    source_revision, canonical_text_sha256, status, turn_id, approval_id,
    created_at_ms, superseded_at_ms, owner_kind, owner_id, role_id,
    role_version, source_kind, trust_class, disposition, disposition_reason,
    disposition_updated_at_ms, processed_at_ms, curation_run_id,
    coverage_start_entry_id, coverage_end_entry_id, expires_at_ms,
    metadata_json, knowledge_domain, scope_kind, scope_id, visibility,
    authorization_revision, binding_id, scope_mode
FROM agent_memory_sources_before_canonical_evidence;

CREATE TABLE memory_source_disposition_events (
    event_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL
        REFERENCES agent_memory_sources(source_id) ON DELETE RESTRICT,
    previous_disposition TEXT NOT NULL,
    new_disposition TEXT NOT NULL CHECK (new_disposition IN (
        'pending',
        'remember',
        'not_for_memory',
        'needs_review',
        'consolidated',
        'expired'
    )),
    reason_code TEXT NOT NULL,
    actor_kind TEXT NOT NULL
        CHECK (actor_kind IN ('rule', 'model', 'user', 'system', 'rollback')),
    run_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
);

INSERT INTO memory_source_disposition_events(
    event_id, source_id, previous_disposition, new_disposition, reason_code,
    actor_kind, run_id, created_at_ms, metadata_json
)
SELECT
    event_id, source_id, previous_disposition, new_disposition, reason_code,
    actor_kind, run_id, created_at_ms, metadata_json
FROM memory_source_disposition_events_before_canonical_evidence;

CREATE TABLE memory_capture_hints (
    hint_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL
        REFERENCES agent_memory_sources(source_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL
        CHECK (kind IN ('preference', 'fact', 'decision', 'correction', 'pitfall')),
    normalized_claim TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('user', 'project')),
    reason TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_ids_json)),
    captured_by_session_id TEXT NOT NULL DEFAULT '',
    captured_by_role_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'consumed', 'superseded')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    basis TEXT NOT NULL DEFAULT 'explicit_user_statement'
        CHECK (basis IN (
            'explicit_user_request',
            'explicit_user_statement',
            'user_correction',
            'repeated_user_signal',
            'verified_outcome'
        )),
    future_use TEXT NOT NULL DEFAULT '',
    supersedes TEXT NOT NULL DEFAULT '',
    UNIQUE(source_id, kind, normalized_claim)
);

INSERT INTO memory_capture_hints(
    hint_id, source_id, kind, normalized_claim, scope, reason,
    evidence_ids_json, captured_by_session_id, captured_by_role_id, status,
    created_at_ms, updated_at_ms, basis, future_use, supersedes
)
SELECT
    hint_id, source_id, kind, normalized_claim, scope, reason,
    evidence_ids_json, captured_by_session_id, captured_by_role_id, status,
    created_at_ms, updated_at_ms, basis, future_use, supersedes
FROM memory_capture_hints_before_canonical_evidence;

DROP TABLE memory_source_disposition_events_before_canonical_evidence;
DROP TABLE memory_capture_hints_before_canonical_evidence;
DROP TABLE agent_memory_sources_before_canonical_evidence;

CREATE INDEX idx_agent_memory_sources_session_recent
ON agent_memory_sources(session_id, status, created_at_ms DESC);

CREATE INDEX idx_agent_memory_sources_input_event
ON agent_memory_sources(input_event_id);

CREATE INDEX idx_agent_memory_sources_owner_pending
ON agent_memory_sources(
    owner_kind, owner_id, disposition, status, created_at_ms, source_id
);

CREATE INDEX idx_agent_memory_sources_role_recent
ON agent_memory_sources(role_id, source_kind, status, created_at_ms DESC);

CREATE INDEX idx_memory_source_disposition_source_recent
ON memory_source_disposition_events(source_id, created_at_ms DESC, event_id DESC);

CREATE INDEX idx_memory_source_disposition_run
ON memory_source_disposition_events(run_id, created_at_ms, event_id);

CREATE INDEX idx_memory_capture_hints_source_status
ON memory_capture_hints(source_id, status, updated_at_ms DESC);

CREATE TRIGGER trg_memory_source_event_agent_insert
AFTER INSERT ON agent_memory_sources
BEGIN
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    VALUES ('agent_memory_source', NEW.source_id, NEW.input_event_id);
END;

CREATE TRIGGER trg_memory_source_event_agent_update
AFTER UPDATE OF input_event_id ON agent_memory_sources
BEGIN
    DELETE FROM memory_source_event_links
    WHERE source_type = 'agent_memory_source' AND source_id = NEW.source_id;
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    VALUES ('agent_memory_source', NEW.source_id, NEW.input_event_id);
END;

CREATE TRIGGER trg_memory_source_event_agent_delete
BEFORE DELETE ON agent_memory_sources
BEGIN
    DELETE FROM memory_source_event_links
    WHERE source_type = 'agent_memory_source' AND source_id = OLD.source_id;
END;

CREATE TRIGGER trg_memory_source_generation_agent_insert
AFTER INSERT ON agent_memory_sources
BEGIN
    INSERT OR IGNORE INTO memory_source_generations(
        source_type, source_id, generation, updated_at_ms
    ) VALUES (
        'agent_memory_source', NEW.source_id, 1,
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    );
END;

CREATE TRIGGER trg_memory_source_generation_agent_update
AFTER UPDATE OF status, source_revision, input_event_id, source_role, session_id,
                owner_kind, owner_id, role_id, role_version, source_kind,
                trust_class, disposition, disposition_reason, processed_at_ms
ON agent_memory_sources
BEGIN
    INSERT INTO memory_source_generations(
        source_type, source_id, generation, updated_at_ms
    ) VALUES (
        'agent_memory_source', NEW.source_id, 2,
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER trg_memory_source_generation_agent_delete
BEFORE DELETE ON agent_memory_sources
BEGIN
    INSERT INTO memory_source_generations(
        source_type, source_id, generation, updated_at_ms
    ) VALUES (
        'agent_memory_source', OLD.source_id, 2,
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER trg_memory_graph_dirty_agent_source
AFTER UPDATE OF status, source_revision, input_event_id, source_role, session_id,
                owner_kind, owner_id, role_id, role_version, source_kind,
                trust_class, disposition, disposition_reason, processed_at_ms
ON agent_memory_sources
BEGIN
    INSERT INTO memory_graph_source_dirty(
        source_type, source_id, dirty_revision, reason, updated_at_ms
    ) VALUES (
        'agent_memory_source', NEW.source_id, 1, 'agent_source_updated',
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER trg_memory_graph_dirty_agent_source_delete
AFTER DELETE ON agent_memory_sources
BEGIN
    INSERT INTO memory_graph_source_dirty(
        source_type, source_id, dirty_revision, reason, updated_at_ms
    ) VALUES (
        'agent_memory_source', OLD.source_id, 1, 'agent_source_deleted',
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

-- Canonical Evidence state. Existing Agent evidence belongs to role-book
-- context, not personal Memory. It stays queryable through its domain-specific
-- consumers but can never satisfy the personal Evidence predicate.
ALTER TABLE agent_memory_evidence
ADD COLUMN evidence_domain TEXT NOT NULL DEFAULT 'role_book'
    CHECK (evidence_domain IN ('personal_memory', 'role_book', 'audit_context'));

ALTER TABLE agent_memory_evidence
ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'legacy_agent_event'
    CHECK (origin_kind IN (
        'capture_v2_input',
        'capture_v2_voice',
        'explicit_user_memory',
        'applied_personal_receipt',
        'legacy_untyped_input',
        'legacy_tool_receipt',
        'legacy_agent_event'
    ));

ALTER TABLE agent_memory_evidence
ADD COLUMN admission_state TEXT NOT NULL DEFAULT 'admitted'
    CHECK (admission_state IN (
        'candidate', 'admitted', 'needs_review', 'rejected', 'forgotten'
    ));

ALTER TABLE agent_memory_evidence
ADD COLUMN admission_reason TEXT NOT NULL DEFAULT 'legacy_role_book_only';

ALTER TABLE agent_memory_evidence
ADD COLUMN trust_class TEXT NOT NULL DEFAULT 'assistant_claim';

ALTER TABLE agent_memory_evidence
ADD COLUMN boundary_kind TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_memory_evidence
ADD COLUMN admission_revision INTEGER NOT NULL DEFAULT 1
    CHECK (admission_revision >= 1);

ALTER TABLE agent_memory_evidence
ADD COLUMN admission_updated_at_ms INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_memory_evidence
ADD COLUMN forgotten_at_ms INTEGER;

CREATE TABLE memory_evidence_input_event_links (
    evidence_id TEXT NOT NULL
        REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
    input_event_id INTEGER NOT NULL
        REFERENCES input_events(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    relation TEXT NOT NULL DEFAULT 'source'
        CHECK (relation IN ('source', 'context')),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(evidence_id, input_event_id, relation)
);

CREATE INDEX idx_memory_evidence_input_event
ON memory_evidence_input_event_links(input_event_id, relation, evidence_id);

CREATE TABLE memory_evidence_admission_events (
    event_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL
        REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL CHECK (new_state IN (
        'candidate', 'admitted', 'needs_review', 'rejected', 'forgotten'
    )),
    reason_code TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK (actor_kind IN (
        'rule', 'luna', 'user', 'system', 'migration', 'rollback'
    )),
    run_id TEXT NOT NULL DEFAULT '',
    source_disposition_event_id TEXT NOT NULL DEFAULT '',
    source_previous_disposition TEXT NOT NULL DEFAULT '',
    source_new_disposition TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
);

CREATE INDEX idx_memory_evidence_admission_recent
ON memory_evidence_admission_events(evidence_id, created_at_ms DESC, event_id DESC);

CREATE INDEX idx_memory_evidence_admission_run
ON memory_evidence_admission_events(run_id, created_at_ms, event_id);

ALTER TABLE input_capture_receipts
ADD COLUMN evidence_id TEXT NOT NULL DEFAULT '';

ALTER TABLE input_capture_receipts
ADD COLUMN evidence_state TEXT NOT NULL DEFAULT 'not_evaluated'
    CHECK (evidence_state IN (
        'not_evaluated', 'candidate', 'admitted', 'needs_review', 'rejected', 'forgotten'
    ));

ALTER TABLE input_capture_receipts
ADD COLUMN evidence_reason TEXT NOT NULL DEFAULT '';

-- Preserve every existing compatibility source in the canonical owner. None
-- is auto-admitted: v1 tags and prior Atom references are not legal proof.
INSERT OR IGNORE INTO agent_memory_evidence(
    evidence_id, project, role_id, session_id, source_kind, source_id,
    idempotency_key, content_text, content_sha256, provenance_json,
    metadata_json, privacy_class, status, occurred_at_ms, recorded_at_ms,
    owner_kind, owner_id, knowledge_domain, scope_kind, scope_id, visibility,
    authorization_revision, binding_id, scope_mode, evidence_domain,
    origin_kind, admission_state, admission_reason, trust_class,
    boundary_kind, admission_revision, admission_updated_at_ms
)
SELECT
    'evidence:source:' || source.source_id,
    event.project,
    source.role_id,
    source.session_id,
    CASE WHEN source.source_kind = 'tool_receipt'
         THEN 'tool_receipt' ELSE 'user_message' END,
    source.source_id,
    'canonical-source:' || source.source_id,
    event.committed_text,
    source.canonical_text_sha256,
    json_object(
        'sourceType', 'agent_memory_source',
        'sourceId', source.source_id,
        'inputEventId', source.input_event_id,
        'sessionId', source.session_id
    ),
    source.metadata_json,
    'local',
    CASE WHEN source.status = 'tombstoned' THEN 'tombstoned' ELSE 'active' END,
    source.created_at_ms,
    source.created_at_ms,
    source.owner_kind,
    source.owner_id,
    source.knowledge_domain,
    source.scope_kind,
    source.scope_id,
    source.visibility,
    source.authorization_revision,
    source.binding_id,
    source.scope_mode,
    CASE WHEN source.disposition IN ('pending', 'remember', 'needs_review', 'consolidated')
         THEN 'personal_memory' ELSE 'audit_context' END,
    CASE
        WHEN source.source_kind = 'explicit_memory' THEN 'explicit_user_memory'
        WHEN source.source_kind = 'tool_receipt' THEN 'legacy_tool_receipt'
        ELSE 'legacy_untyped_input'
    END,
    CASE
        WHEN source.status = 'tombstoned' THEN 'forgotten'
        WHEN source.disposition IN ('pending', 'remember', 'needs_review', 'consolidated')
            THEN 'needs_review'
        ELSE 'rejected'
    END,
    CASE
        WHEN source.status = 'tombstoned' THEN 'legacy_source_tombstoned'
        WHEN source.disposition IN ('pending', 'remember', 'needs_review', 'consolidated')
            THEN 'legacy_source_requires_revalidation'
        ELSE COALESCE(NULLIF(source.disposition_reason, ''), 'legacy_source_not_for_memory')
    END,
    source.trust_class,
    '',
    1,
    COALESCE(source.disposition_updated_at_ms, source.created_at_ms)
FROM agent_memory_sources AS source
JOIN input_events AS event ON event.id = source.input_event_id;

INSERT OR IGNORE INTO memory_evidence_input_event_links(
    evidence_id, input_event_id, ordinal, relation, content_sha256, created_at_ms
)
SELECT
    'evidence:source:' || source.source_id,
    source.input_event_id,
    0,
    'source',
    source.canonical_text_sha256,
    source.created_at_ms
FROM agent_memory_sources AS source
WHERE EXISTS (
    SELECT 1 FROM agent_memory_evidence AS evidence
    WHERE evidence.evidence_id = 'evidence:source:' || source.source_id
);

INSERT OR IGNORE INTO memory_evidence_admission_events(
    event_id, evidence_id, previous_state, new_state, reason_code, actor_kind,
    source_disposition_event_id, source_previous_disposition,
    source_new_disposition, created_at_ms, metadata_json
)
SELECT
    'evidence-admission:migration-0130:' || source.source_id,
    'evidence:source:' || source.source_id,
    '',
    evidence.admission_state,
    evidence.admission_reason,
    'migration',
    '',
    '',
    source.disposition,
    COALESCE(source.disposition_updated_at_ms, source.created_at_ms),
    json_object('migrationVersion', 130)
FROM agent_memory_sources AS source
JOIN agent_memory_evidence AS evidence
  ON evidence.evidence_id = 'evidence:source:' || source.source_id;

INSERT OR IGNORE INTO memory_evidence_admission_events(
    event_id, evidence_id, previous_state, new_state, reason_code, actor_kind,
    run_id, source_disposition_event_id, source_previous_disposition,
    source_new_disposition, created_at_ms, metadata_json
)
SELECT
    'evidence-admission:source-event:' || disposition.event_id,
    'evidence:source:' || disposition.source_id,
    '',
    CASE
        WHEN disposition.new_disposition IN ('pending', 'remember', 'needs_review', 'consolidated')
            THEN 'needs_review'
        ELSE 'rejected'
    END,
    disposition.reason_code,
    'migration',
    disposition.run_id,
    disposition.event_id,
    disposition.previous_disposition,
    disposition.new_disposition,
    disposition.created_at_ms,
    disposition.metadata_json
FROM memory_source_disposition_events AS disposition
WHERE EXISTS (
    SELECT 1 FROM agent_memory_evidence AS evidence
    WHERE evidence.evidence_id = 'evidence:source:' || disposition.source_id
);

CREATE INDEX idx_agent_memory_evidence_personal_admission
ON agent_memory_evidence(
    evidence_domain, admission_state, status, occurred_at_ms DESC, evidence_id DESC
);

CREATE INDEX idx_agent_memory_evidence_origin_admission
ON agent_memory_evidence(origin_kind, admission_state, occurred_at_ms DESC);
