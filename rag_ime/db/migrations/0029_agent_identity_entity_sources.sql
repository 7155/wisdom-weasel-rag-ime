UPDATE agent_sessions
SET agent_id = id
WHERE agent_id = '';

CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent
ON agent_sessions(agent_id, status, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS memory_source_generations (
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(source_type, source_id)
);

CREATE TABLE IF NOT EXISTS memory_entity_sources (
    entity_id TEXT NOT NULL REFERENCES memory_entities(entity_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL DEFAULT 1 CHECK (source_revision >= 1),
    evidence_text TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(entity_id, source_type, source_id, source_revision)
);

CREATE INDEX IF NOT EXISTS idx_memory_entity_sources_source
ON memory_entity_sources(source_type, source_id, entity_id);

INSERT OR IGNORE INTO memory_source_generations(
    source_type, source_id, generation, updated_at_ms
)
SELECT source_type, source_id, MAX(source_revision), MAX(created_at_ms)
FROM (
    SELECT source_type, source_id, source_revision, created_at_ms
    FROM memory_relation_sources
    UNION ALL
    SELECT source_type, source_id, source_revision, created_at_ms
    FROM memory_entity_sources
)
GROUP BY source_type, source_id;

CREATE TABLE IF NOT EXISTS memory_graph_source_dirty (
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    dirty_revision INTEGER NOT NULL DEFAULT 1 CHECK (dirty_revision >= 1),
    reason TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_graph_source_dirty_updated
ON memory_graph_source_dirty(updated_at_ms, source_type, source_id);

CREATE TABLE IF NOT EXISTS memory_source_event_links (
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    PRIMARY KEY(source_type, source_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_source_event_links_event
ON memory_source_event_links(event_id, source_type, source_id);

INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
SELECT 'agent_memory_source', source_id, input_event_id
FROM agent_memory_sources;

INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
SELECT 'atom', a.id, CAST(source_event.value AS INTEGER)
FROM memory_atoms AS a
JOIN json_each(
    CASE WHEN json_valid(a.source_event_ids_json) THEN a.source_event_ids_json ELSE '[]' END
) AS source_event
WHERE CAST(source_event.value AS INTEGER) > 0;

INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
SELECT 'book', b.book_id, CAST(source_event.value AS INTEGER)
FROM memory_books AS b
JOIN json_each(
    CASE WHEN json_valid(b.source_event_ids_json) THEN b.source_event_ids_json ELSE '[]' END
) AS source_event
WHERE CAST(source_event.value AS INTEGER) > 0;

INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
SELECT 'item', memory_id, source_event_id FROM memory_items WHERE source_event_id IS NOT NULL;

INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
SELECT 'phrase', memory_id, source_event_id FROM memory_items WHERE source_event_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_agent_insert
AFTER INSERT ON agent_memory_sources
BEGIN
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    VALUES ('agent_memory_source', NEW.source_id, NEW.input_event_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_agent_update
AFTER UPDATE OF input_event_id ON agent_memory_sources
BEGIN
    DELETE FROM memory_source_event_links
    WHERE source_type = 'agent_memory_source' AND source_id = NEW.source_id;
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    VALUES ('agent_memory_source', NEW.source_id, NEW.input_event_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_agent_delete
BEFORE DELETE ON agent_memory_sources
BEGIN
    DELETE FROM memory_source_event_links
    WHERE source_type = 'agent_memory_source' AND source_id = OLD.source_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_atom_insert
AFTER INSERT ON memory_atoms
BEGIN
    INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
    SELECT 'atom', NEW.id, CAST(value AS INTEGER)
    FROM json_each(
        CASE WHEN json_valid(NEW.source_event_ids_json) THEN NEW.source_event_ids_json ELSE '[]' END
    )
    WHERE CAST(value AS INTEGER) > 0;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_atom_update
AFTER UPDATE OF source_event_ids_json ON memory_atoms
BEGIN
    DELETE FROM memory_source_event_links WHERE source_type = 'atom' AND source_id = NEW.id;
    INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
    SELECT 'atom', NEW.id, CAST(value AS INTEGER)
    FROM json_each(
        CASE WHEN json_valid(NEW.source_event_ids_json) THEN NEW.source_event_ids_json ELSE '[]' END
    )
    WHERE CAST(value AS INTEGER) > 0;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_atom_delete
BEFORE DELETE ON memory_atoms
BEGIN
    DELETE FROM memory_source_event_links WHERE source_type = 'atom' AND source_id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_book_insert
AFTER INSERT ON memory_books
BEGIN
    INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
    SELECT 'book', NEW.book_id, CAST(value AS INTEGER)
    FROM json_each(
        CASE WHEN json_valid(NEW.source_event_ids_json) THEN NEW.source_event_ids_json ELSE '[]' END
    )
    WHERE CAST(value AS INTEGER) > 0;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_book_update
AFTER UPDATE OF source_event_ids_json ON memory_books
BEGIN
    DELETE FROM memory_source_event_links WHERE source_type = 'book' AND source_id = NEW.book_id;
    INSERT OR IGNORE INTO memory_source_event_links(source_type, source_id, event_id)
    SELECT 'book', NEW.book_id, CAST(value AS INTEGER)
    FROM json_each(
        CASE WHEN json_valid(NEW.source_event_ids_json) THEN NEW.source_event_ids_json ELSE '[]' END
    )
    WHERE CAST(value AS INTEGER) > 0;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_book_delete
BEFORE DELETE ON memory_books
BEGIN
    DELETE FROM memory_source_event_links WHERE source_type = 'book' AND source_id = OLD.book_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_item_insert
AFTER INSERT ON memory_items WHEN NEW.source_event_id IS NOT NULL
BEGIN
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    VALUES ('item', NEW.memory_id, NEW.source_event_id);
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    VALUES ('phrase', NEW.memory_id, NEW.source_event_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_item_update
AFTER UPDATE OF source_event_id ON memory_items
BEGIN
    DELETE FROM memory_source_event_links
    WHERE source_type IN ('item', 'phrase') AND source_id = NEW.memory_id;
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    SELECT 'item', NEW.memory_id, NEW.source_event_id WHERE NEW.source_event_id IS NOT NULL;
    INSERT OR REPLACE INTO memory_source_event_links(source_type, source_id, event_id)
    SELECT 'phrase', NEW.memory_id, NEW.source_event_id WHERE NEW.source_event_id IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_event_item_delete
BEFORE DELETE ON memory_items
BEGIN
    DELETE FROM memory_source_event_links
    WHERE source_type IN ('item', 'phrase') AND source_id = OLD.memory_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_event_insert
AFTER INSERT ON input_events
BEGIN
    INSERT OR IGNORE INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('input_event', CAST(NEW.id AS TEXT), 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_event_update
AFTER UPDATE OF committed_text, recent_context, preedit, schema_id, app, project,
                provider_name, tags_json, context_group_id, context_group_level, source
ON input_events
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('input_event', CAST(NEW.id AS TEXT), 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    SELECT links.source_type, links.source_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000
    FROM memory_source_event_links AS links
    WHERE links.event_id = NEW.id
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_event_state
AFTER UPDATE OF deleted ON memory_state
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('input_event', CAST(NEW.event_id AS TEXT), 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    SELECT links.source_type, links.source_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000
    FROM memory_source_event_links AS links
    WHERE links.event_id = NEW.event_id
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_event_delete
BEFORE DELETE ON input_events
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('input_event', CAST(OLD.id AS TEXT), 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    SELECT links.source_type, links.source_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000
    FROM memory_source_event_links AS links
    WHERE links.event_id = OLD.id
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_agent_insert
AFTER INSERT ON agent_memory_sources
BEGIN
    INSERT OR IGNORE INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('agent_memory_source', NEW.source_id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_agent_update
AFTER UPDATE OF status, source_revision, input_event_id, source_role, session_id
ON agent_memory_sources
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('agent_memory_source', NEW.source_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_agent_delete
BEFORE DELETE ON agent_memory_sources
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('agent_memory_source', OLD.source_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_atom_insert
AFTER INSERT ON memory_atoms
BEGIN
    INSERT OR IGNORE INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('atom', NEW.id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_atom_update
AFTER UPDATE OF kind, text, canonical_text, source_event_ids_json, scope_app,
                scope_project, privacy_level, status
ON memory_atoms
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('atom', NEW.id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_atom_delete
BEFORE DELETE ON memory_atoms
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('atom', OLD.id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_item_insert
AFTER INSERT ON memory_items
BEGIN
    INSERT OR IGNORE INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('item', NEW.memory_id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
    INSERT OR IGNORE INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('phrase', NEW.memory_id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_item_update
AFTER UPDATE OF kind, text, normalized_text, summary, source_event_id, project,
                app, scope, status, privacy_class
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

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_item_delete
BEFORE DELETE ON memory_items
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('item', OLD.memory_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('phrase', OLD.memory_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_book_insert
AFTER INSERT ON memory_books
BEGIN
    INSERT OR IGNORE INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('book', NEW.book_id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_book_update
AFTER UPDATE OF book_type, book_key, title, summary, normalized_text, project, app,
                tags_json, surface_hints_json, query_expansions_json,
                source_event_ids_json, memory_atom_ids_json, status
ON memory_books
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('book', NEW.book_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_source_generation_book_delete
BEFORE DELETE ON memory_books
BEGIN
    INSERT INTO memory_source_generations(source_type, source_id, generation, updated_at_ms)
    VALUES ('book', OLD.book_id, 2, CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        generation = memory_source_generations.generation + 1,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_event_text
AFTER UPDATE OF committed_text, recent_context, preedit, schema_id, app, project,
                provider_name, tags_json, context_group_id, context_group_level, source
ON input_events
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('input_event', CAST(NEW.id AS TEXT), 1, 'input_event_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_event_state
AFTER UPDATE OF deleted ON memory_state
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('input_event', CAST(NEW.event_id AS TEXT), 1, 'memory_state_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_event_delete
AFTER DELETE ON input_events
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('input_event', CAST(OLD.id AS TEXT), 1, 'input_event_deleted', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_agent_source
AFTER UPDATE OF status, source_revision, input_event_id, source_role, session_id
ON agent_memory_sources
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('agent_memory_source', NEW.source_id, 1, 'agent_source_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_agent_source_delete
AFTER DELETE ON agent_memory_sources
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('agent_memory_source', OLD.source_id, 1, 'agent_source_deleted', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_atom
AFTER UPDATE OF kind, text, canonical_text, source_event_ids_json, scope_app,
                scope_project, privacy_level, status
ON memory_atoms
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('atom', NEW.id, 1, 'atom_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_item
AFTER UPDATE OF kind, text, normalized_text, summary, source_event_id, project,
                app, scope, status, privacy_class
ON memory_items
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('item', NEW.memory_id, 1, 'item_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('phrase', NEW.memory_id, 1, 'item_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_atom_delete
AFTER DELETE ON memory_atoms
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('atom', OLD.id, 1, 'atom_deleted', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_item_delete
AFTER DELETE ON memory_items
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('item', OLD.memory_id, 1, 'item_deleted', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('phrase', OLD.memory_id, 1, 'item_deleted', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_book
AFTER UPDATE OF book_type, book_key, title, summary, normalized_text, project, app,
                tags_json, surface_hints_json, query_expansions_json,
                source_event_ids_json, memory_atom_ids_json, status
ON memory_books
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('book', NEW.book_id, 1, 'book_updated', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_graph_dirty_book_delete
AFTER DELETE ON memory_books
BEGIN
    INSERT INTO memory_graph_source_dirty(source_type, source_id, dirty_revision, reason, updated_at_ms)
    VALUES ('book', OLD.book_id, 1, 'book_deleted', CAST(strftime('%s', 'now') AS INTEGER) * 1000)
    ON CONFLICT(source_type, source_id) DO UPDATE SET
        dirty_revision = memory_graph_source_dirty.dirty_revision + 1,
        reason = excluded.reason,
        updated_at_ms = excluded.updated_at_ms;
END;
