CREATE TABLE IF NOT EXISTS daily_activity_timelines (
    timeline_id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT '',
    timeline_date TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'rejected', 'superseded')),
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    source_event_hash TEXT NOT NULL,
    segments_json TEXT NOT NULL DEFAULT '[]',
    summary_text TEXT NOT NULL DEFAULT '',
    event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    segment_count INTEGER NOT NULL DEFAULT 0 CHECK (segment_count >= 0),
    approved_book_id TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at_ms INTEGER,
    rejection_reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(project, timeline_date, source_event_hash)
);

CREATE INDEX IF NOT EXISTS idx_daily_activity_timelines_project_date
ON daily_activity_timelines(project, timeline_date DESC, status, updated_at_ms DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_activity_timelines_one_draft
ON daily_activity_timelines(project, timeline_date)
WHERE status = 'draft';

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_activity_timelines_one_approved
ON daily_activity_timelines(project, timeline_date)
WHERE status = 'approved';
