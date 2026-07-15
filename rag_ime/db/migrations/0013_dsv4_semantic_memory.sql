ALTER TABLE memory_tags ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_tags ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy_auto';
ALTER TABLE memory_tags ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE memory_tags ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS memory_semantic_groups (
    group_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0.5,
    quality_score REAL NOT NULL DEFAULT 0.5,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memory_semantic_groups_status_quality
ON memory_semantic_groups(status, quality_score DESC, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS memory_semantic_group_members (
    group_id TEXT NOT NULL,
    member_type TEXT NOT NULL,
    member_id TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.8,
    source TEXT NOT NULL DEFAULT 'dsv4',
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(group_id, member_type, member_id),
    FOREIGN KEY(group_id) REFERENCES memory_semantic_groups(group_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_semantic_group_members_target
ON memory_semantic_group_members(member_type, member_id);

-- Raw input is an immutable source ledger. It must not be a retrieval document
-- or an automatically promoted phrase before the offline organizer reviews it.
UPDATE memory_items
SET status = 'hidden'
WHERE kind = 'raw_event';

UPDATE memory_items
SET status = 'hidden'
WHERE kind = 'phrase'
  AND metadata_json LIKE '%"raw_memory_id"%';

DELETE FROM memory_items_fts
WHERE rowid IN (
    SELECT id
    FROM memory_items
    WHERE status NOT IN ('active', 'approved')
       OR privacy_class = 'sensitive'
);

DELETE FROM memory_item_vectors
WHERE memory_item_id IN (
    SELECT id
    FROM memory_items
    WHERE status NOT IN ('active', 'approved')
       OR privacy_class = 'sensitive'
);

DELETE FROM memory_fts
WHERE rowid IN (
    SELECT id
    FROM input_events
    WHERE tags_json NOT LIKE '%"compiled-memory"%'
      AND tags_json NOT LIKE '%"compiled-phrase"%'
      AND tags_json NOT LIKE '%"curated"%'
      AND tags_json NOT LIKE '%"phrase-memory"%'
      AND tags_json NOT LIKE '%"stable-memory"%'
);

DELETE FROM memory_vectors
WHERE event_id IN (
    SELECT id
    FROM input_events
    WHERE tags_json NOT LIKE '%"compiled-memory"%'
      AND tags_json NOT LIKE '%"compiled-phrase"%'
      AND tags_json NOT LIKE '%"curated"%'
      AND tags_json NOT LIKE '%"phrase-memory"%'
      AND tags_json NOT LIKE '%"stable-memory"%'
);

-- Preserve human-edited and previously compiled tags, but hide legacy token/
-- n-gram tags from user views and semantic retrieval governance.
UPDATE memory_tags
SET source = 'user'
WHERE id IN (SELECT tag_id FROM memory_tag_profiles);

UPDATE memory_tags
SET source = 'dsv4'
WHERE id IN (
    SELECT CAST(tag_id AS INTEGER)
    FROM memory_atom_tags
    WHERE source = 'memory_book_compile'
)
  AND source != 'user';

UPDATE memory_tags
SET status = 'hidden'
WHERE source = 'legacy_auto';

-- Semantic relations are emitted with evidence by DSV4. Legacy co-occurrence
-- edges are intentionally dropped instead of being treated as knowledge.
DELETE FROM memory_tag_edges
WHERE edge_type = 'cooccur';
