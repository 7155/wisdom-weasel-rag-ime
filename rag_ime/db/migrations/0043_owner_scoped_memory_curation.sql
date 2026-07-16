ALTER TABLE agent_memory_sources
ADD COLUMN owner_kind TEXT NOT NULL DEFAULT 'user'
    CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room'));

ALTER TABLE agent_memory_sources
ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE agent_memory_sources
ADD COLUMN role_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_memory_sources
ADD COLUMN role_version TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_memory_sources
ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'user_final'
    CHECK (source_kind IN (
        'user_final',
        'tool_receipt',
        'session_compaction',
        'session_digest',
        'explicit_memory'
    ));

ALTER TABLE agent_memory_sources
ADD COLUMN trust_class TEXT NOT NULL DEFAULT 'user_claim'
    CHECK (trust_class IN (
        'user_claim',
        'applied_receipt',
        'session_summary',
        'assistant_claim',
        'explicit_command'
    ));

ALTER TABLE agent_memory_sources
ADD COLUMN disposition TEXT NOT NULL DEFAULT 'pending'
    CHECK (disposition IN (
        'pending',
        'remember',
        'not_for_memory',
        'needs_review',
        'consolidated',
        'expired'
    ));

ALTER TABLE agent_memory_sources
ADD COLUMN disposition_reason TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_memory_sources
ADD COLUMN disposition_updated_at_ms INTEGER;

ALTER TABLE agent_memory_sources
ADD COLUMN processed_at_ms INTEGER;

ALTER TABLE agent_memory_sources
ADD COLUMN curation_run_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_memory_sources
ADD COLUMN coverage_start_entry_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_memory_sources
ADD COLUMN coverage_end_entry_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_memory_sources
ADD COLUMN expires_at_ms INTEGER;

ALTER TABLE agent_memory_sources
ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'
    CHECK (json_valid(metadata_json));

UPDATE agent_memory_sources
SET role_id = COALESCE(
        (SELECT role_id FROM agent_sessions WHERE id = agent_memory_sources.session_id),
        ''
    ),
    role_version = COALESCE(
        (SELECT role_version FROM agent_sessions WHERE id = agent_memory_sources.session_id),
        ''
    ),
    owner_kind = CASE source_role WHEN 'tool_receipt' THEN 'shared' ELSE 'user' END,
    owner_id = CASE source_role
        WHEN 'tool_receipt' THEN COALESCE(
            NULLIF(
                (SELECT project FROM input_events WHERE id = agent_memory_sources.input_event_id),
                ''
            ),
            'default'
        )
        ELSE 'default'
    END,
    source_kind = CASE source_role
        WHEN 'tool_receipt' THEN 'tool_receipt'
        ELSE 'user_final'
    END,
    trust_class = CASE source_role
        WHEN 'tool_receipt' THEN 'applied_receipt'
        ELSE 'user_claim'
    END;

CREATE INDEX IF NOT EXISTS idx_agent_memory_sources_owner_pending
ON agent_memory_sources(
    owner_kind,
    owner_id,
    disposition,
    status,
    created_at_ms,
    source_id
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_sources_role_recent
ON agent_memory_sources(role_id, source_kind, status, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS memory_source_disposition_events (
    event_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES agent_memory_sources(source_id) ON DELETE CASCADE,
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
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('rule', 'model', 'user', 'system', 'rollback')),
    run_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
);

CREATE INDEX IF NOT EXISTS idx_memory_source_disposition_source_recent
ON memory_source_disposition_events(source_id, created_at_ms DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_source_disposition_run
ON memory_source_disposition_events(run_id, created_at_ms, event_id);

CREATE TABLE IF NOT EXISTS memory_curation_cursors (
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room')),
    owner_id TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    lane TEXT NOT NULL CHECK (lane IN ('daily', 'manual', 'dream')),
    last_source_created_at_ms INTEGER NOT NULL DEFAULT 0,
    last_source_id TEXT NOT NULL DEFAULT '',
    last_run_ms INTEGER NOT NULL DEFAULT 0,
    last_run_id TEXT NOT NULL DEFAULT '',
    next_due_at_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'idle'
        CHECK (status IN ('idle', 'running', 'waiting_review', 'backoff')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(owner_kind, owner_id, project, lane)
);

CREATE INDEX IF NOT EXISTS idx_memory_curation_cursors_due
ON memory_curation_cursors(lane, status, next_due_at_ms, updated_at_ms);

ALTER TABLE memory_cleanup_runs
ADD COLUMN owner_kind TEXT NOT NULL DEFAULT 'user'
    CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room'));

ALTER TABLE memory_cleanup_runs
ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE memory_cleanup_runs
ADD COLUMN run_kind TEXT NOT NULL DEFAULT 'legacy'
    CHECK (run_kind IN ('legacy', 'daily_curation', 'manual_curation', 'dream_insight'));

CREATE INDEX IF NOT EXISTS idx_memory_cleanup_runs_owner_recent
ON memory_cleanup_runs(owner_kind, owner_id, run_kind, created_at_ms DESC);

ALTER TABLE memory_items
ADD COLUMN owner_kind TEXT NOT NULL DEFAULT 'user'
    CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room'));

ALTER TABLE memory_items
ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE memory_atoms
ADD COLUMN owner_kind TEXT NOT NULL DEFAULT 'user'
    CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room'));

ALTER TABLE memory_atoms
ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE memory_books
ADD COLUMN owner_kind TEXT NOT NULL DEFAULT 'user'
    CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room'));

ALTER TABLE memory_books
ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE memory_retrieval_docs
ADD COLUMN owner_kind TEXT NOT NULL DEFAULT 'user'
    CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room'));

ALTER TABLE memory_retrieval_docs
ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_memory_items_owner_status
ON memory_items(owner_kind, owner_id, project, status, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_memory_atoms_owner_status
ON memory_atoms(owner_kind, owner_id, scope_project, status, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_memory_books_owner_status
ON memory_books(owner_kind, owner_id, project, status, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_memory_retrieval_docs_owner_status
ON memory_retrieval_docs(owner_kind, owner_id, project, status, updated_at_ms DESC);

DROP TRIGGER IF EXISTS trg_memory_source_generation_agent_update;

CREATE TRIGGER trg_memory_source_generation_agent_update
AFTER UPDATE OF status, source_revision, input_event_id, source_role, session_id,
                owner_kind, owner_id, role_id, role_version, source_kind,
                trust_class, disposition, disposition_reason, processed_at_ms
ON agent_memory_sources
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('agent_memory_source', NEW.source_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

DROP TRIGGER IF EXISTS trg_memory_graph_dirty_agent_source;

CREATE TRIGGER trg_memory_graph_dirty_agent_source
AFTER UPDATE OF status, source_revision, input_event_id, source_role, session_id,
                owner_kind, owner_id, role_id, role_version, source_kind,
                trust_class, disposition, disposition_reason, processed_at_ms
ON agent_memory_sources
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('agent_memory_source', NEW.source_id, 1, 'agent_source_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

DROP TRIGGER IF EXISTS trg_memory_source_generation_atom_update;

CREATE TRIGGER trg_memory_source_generation_atom_update
AFTER UPDATE OF kind, text, canonical_text, source_event_ids_json, scope_app,
                scope_project, privacy_level, status, owner_kind, owner_id
ON memory_atoms
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('atom', NEW.id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

DROP TRIGGER IF EXISTS trg_memory_source_generation_item_update;

CREATE TRIGGER trg_memory_source_generation_item_update
AFTER UPDATE OF kind, text, normalized_text, summary, source_event_id, project,
                app, scope, status, privacy_class, owner_kind, owner_id
ON memory_items
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('item', NEW.memory_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('phrase', NEW.memory_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

DROP TRIGGER IF EXISTS trg_memory_source_generation_book_update;

CREATE TRIGGER trg_memory_source_generation_book_update
AFTER UPDATE OF book_type, book_key, title, summary, normalized_text, project, app,
                tags_json, surface_hints_json, query_expansions_json,
                source_event_ids_json, memory_atom_ids_json, status, owner_kind, owner_id
ON memory_books
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('book', NEW.book_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

DROP TRIGGER IF EXISTS trg_memory_graph_dirty_atom;

CREATE TRIGGER trg_memory_graph_dirty_atom
AFTER UPDATE OF kind, text, canonical_text, source_event_ids_json, scope_app,
                scope_project, privacy_level, status, owner_kind, owner_id
ON memory_atoms
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('atom', NEW.id, 1, 'atom_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

DROP TRIGGER IF EXISTS trg_memory_graph_dirty_item;

CREATE TRIGGER trg_memory_graph_dirty_item
AFTER UPDATE OF kind, text, normalized_text, summary, source_event_id, project,
                app, scope, status, privacy_class, owner_kind, owner_id
ON memory_items
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('item', NEW.memory_id, 1, 'item_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

DROP TRIGGER IF EXISTS trg_memory_graph_dirty_book;

CREATE TRIGGER trg_memory_graph_dirty_book
AFTER UPDATE OF book_type, book_key, title, summary, normalized_text, project, app,
                tags_json, surface_hints_json, query_expansions_json,
                source_event_ids_json, memory_atom_ids_json, status, owner_kind, owner_id
ON memory_books
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('book', NEW.book_id, 1, 'book_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;
