UPDATE memory_cleanup_diffs
SET status = 'rejected'
WHERE status IN ('pending', 'approved')
  AND run_id IN (
      SELECT run_id
      FROM memory_cleanup_runs
      WHERE status = 'draft'
        AND run_id LIKE 'memory_book_%'
  );

UPDATE memory_cleanup_runs
SET status = 'superseded'
WHERE status = 'draft'
  AND run_id LIKE 'memory_book_%';

UPDATE memory_compile_state
SET last_drafted_event_id = 0,
    last_draft_ms = 0,
    last_draft_bundle_hash = '',
    last_draft_run_id = '';
