CREATE TABLE room_v2_reflection_dead_letters (
    dead_letter_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES room_v2_incidents(incident_id),
    owner_ref TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    last_evidence_refs_json TEXT NOT NULL,
    next_action TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK(attempt_count>=1),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_materialization_receipts (
    materialization_receipt_id TEXT PRIMARY KEY,
    guard_candidate_id TEXT NOT NULL REFERENCES room_v2_guard_candidates(guard_candidate_id),
    guard_epoch INTEGER NOT NULL CHECK(guard_epoch>=1),
    artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('runtime_policy','regression_test','lint_ci','skill','runbook','alert','eval_fixture')),
    status TEXT NOT NULL CHECK(status IN ('pending','materialized','failed','rolled_back','retired')),
    artifact_hash TEXT NOT NULL,
    projection_ref TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_knowledge_eval_fixture_datasets (
    dataset_id TEXT PRIMARY KEY,
    dataset_version INTEGER NOT NULL CHECK(dataset_version>=1),
    signer_id TEXT NOT NULL,
    fixture_count INTEGER NOT NULL CHECK(fixture_count>=6),
    fixtures_json TEXT NOT NULL,
    thresholds_json TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    signer_signature TEXT NOT NULL CHECK(length(signer_signature)=64),
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL CHECK(expires_at_ms>created_at_ms),
    UNIQUE(dataset_id,dataset_version,content_hash)
);

CREATE TABLE room_v2_knowledge_search_use_eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES room_v2_knowledge_eval_fixture_datasets(dataset_id),
    dataset_content_hash TEXT NOT NULL,
    room_binding_id TEXT NOT NULL,
    trace_count INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    strata_metrics_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('passed','failed')),
    failure_reasons_json TEXT NOT NULL,
    report_only INTEGER NOT NULL CHECK(report_only=1),
    evaluator_id TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    evaluator_signature TEXT NOT NULL CHECK(length(evaluator_signature)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TRIGGER room_v2_reflection_dead_letter_no_update BEFORE UPDATE ON room_v2_reflection_dead_letters BEGIN SELECT RAISE(ABORT,'ReflectionDeadLetter is immutable'); END;
CREATE TRIGGER room_v2_reflection_dead_letter_no_delete BEFORE DELETE ON room_v2_reflection_dead_letters BEGIN SELECT RAISE(ABORT,'ReflectionDeadLetter is permanent'); END;
CREATE TRIGGER room_v2_guard_materialization_no_update BEFORE UPDATE ON room_v2_guard_materialization_receipts BEGIN SELECT RAISE(ABORT,'GuardMaterializationReceipt is immutable'); END;
CREATE TRIGGER room_v2_guard_materialization_no_delete BEFORE DELETE ON room_v2_guard_materialization_receipts BEGIN SELECT RAISE(ABORT,'GuardMaterializationReceipt is permanent'); END;
CREATE TRIGGER room_v2_knowledge_eval_dataset_no_update BEFORE UPDATE ON room_v2_knowledge_eval_fixture_datasets BEGIN SELECT RAISE(ABORT,'KnowledgeEvalDataset is immutable'); END;
CREATE TRIGGER room_v2_knowledge_eval_dataset_no_delete BEFORE DELETE ON room_v2_knowledge_eval_fixture_datasets BEGIN SELECT RAISE(ABORT,'KnowledgeEvalDataset is permanent'); END;
CREATE TRIGGER room_v2_knowledge_eval_run_no_update BEFORE UPDATE ON room_v2_knowledge_search_use_eval_runs BEGIN SELECT RAISE(ABORT,'KnowledgeEvalRun is immutable'); END;
CREATE TRIGGER room_v2_knowledge_eval_run_no_delete BEFORE DELETE ON room_v2_knowledge_search_use_eval_runs BEGIN SELECT RAISE(ABORT,'KnowledgeEvalRun is permanent'); END;
