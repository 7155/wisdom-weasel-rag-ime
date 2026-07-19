-- Owner curation now emits stable thematic Topic Books. Retire the old
-- catch-all owner book only when another active thematic book already exists,
-- so Atom-only installations never lose their sole book-level projection.
UPDATE memory_books
SET status = 'archived',
    archived_at_ms = COALESCE(archived_at_ms, updated_at_ms),
    archive_reason = CASE
        WHEN archive_reason = '' THEN 'migrated_to_thematic_topic_books'
        ELSE archive_reason
    END
WHERE book_type = 'topic'
  AND status IN ('active', 'approved')
  AND book_id LIKE 'book:owner:%'
  AND book_id NOT LIKE 'book:owner:%:topic:%'
  AND EXISTS (
      SELECT 1
      FROM memory_books AS thematic
      WHERE thematic.book_id != memory_books.book_id
        AND thematic.book_type = 'topic'
        AND thematic.status IN ('active', 'approved')
        AND thematic.owner_kind = memory_books.owner_kind
        AND thematic.owner_id = memory_books.owner_id
        AND thematic.project = memory_books.project
  );

INSERT OR IGNORE INTO memory_projection_outbox(
    projection_kind,
    aggregate_type,
    aggregate_id,
    operation,
    revision,
    payload_json,
    state,
    attempts,
    available_at_ms,
    created_at_ms,
    updated_at_ms
)
SELECT
    'retrieval_docs',
    'schema_migration',
    '0062_retire_owner_umbrella_topic_books',
    'rebuild',
    62,
    '{"schemaVersion":"rag-ime.memory-projection.v1","project":"","reason":"retire_owner_umbrella_topic_books"}',
    'pending',
    0,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000
WHERE changes() > 0
  AND EXISTS (
    SELECT 1 FROM sqlite_master
    WHERE type = 'table' AND name = 'memory_projection_outbox'
);
