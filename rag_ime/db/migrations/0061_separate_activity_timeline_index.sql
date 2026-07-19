-- Daily activity is an independent retrieval product, not a Topic Book.
UPDATE memory_books
SET status = 'archived',
    archived_at_ms = COALESCE(archived_at_ms, updated_at_ms),
    archive_reason = CASE
        WHEN archive_reason = '' THEN 'migrated_to_timeline_index'
        ELSE archive_reason
    END
WHERE book_type = 'daily';

UPDATE daily_activity_timelines
SET approved_book_id = ''
WHERE approved_book_id != '';

-- Rebuild the derived retrieval catalog after migration. Otherwise the old
-- Daily Book rows remain searchable until some unrelated memory write happens.
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
    '0061_separate_activity_timeline_index',
    'rebuild',
    61,
    '{"schemaVersion":"rag-ime.memory-projection.v1","project":"","reason":"separate_activity_timeline_index"}',
    'pending',
    0,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000
WHERE EXISTS (
    SELECT 1 FROM sqlite_master
    WHERE type = 'table' AND name = 'memory_projection_outbox'
);
