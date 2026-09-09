CREATE TABLE IF NOT EXISTS trace_optimization_versions (
    version_ref TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_optimization_execution_plans (
    plan_ref TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_optimization_application_receipts (
    receipt_ref TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_optimization_run_pairs (
    request_id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    baseline_job_id TEXT NOT NULL,
    candidate_job_id TEXT NOT NULL,
    comparison_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL
);
