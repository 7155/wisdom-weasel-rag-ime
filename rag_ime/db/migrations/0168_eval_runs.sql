CREATE TABLE eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    mode TEXT NOT NULL CHECK (mode IN ('ground_truth', 'ai_judge')),
    metric_authority TEXT NOT NULL CHECK (
        metric_authority IN ('ground_truth', 'ai_judge_estimate')
    ),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE eval_run_trace_refs (
    eval_run_id TEXT NOT NULL REFERENCES eval_runs(eval_run_id) ON DELETE CASCADE,
    trace_id TEXT NOT NULL,
    PRIMARY KEY (eval_run_id, trace_id)
);

CREATE INDEX idx_eval_runs_created
    ON eval_runs(created_at_ms, eval_run_id);

CREATE INDEX idx_eval_run_trace_refs_trace
    ON eval_run_trace_refs(trace_id, eval_run_id);
