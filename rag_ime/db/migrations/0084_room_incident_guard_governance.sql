CREATE TABLE room_v2_incidents (
    incident_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id),
    dispatch_id TEXT NOT NULL REFERENCES room_kernel_dispatches(dispatch_id),
    kernel_receipt_id TEXT NOT NULL REFERENCES room_kernel_receipts(receipt_id),
    taxonomy TEXT NOT NULL CHECK(taxonomy IN ('loop_detected','cancel_leak','stale_write','delivery_regression','tool_failure','context_corruption','security_boundary','user_correction','rollback','unknown')),
    failure_signature TEXT NOT NULL,
    dedupe_hash TEXT NOT NULL UNIQUE CHECK(length(dedupe_hash)=64),
    evidence_refs_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_incident_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES room_v2_incidents(incident_id),
    root_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    kernel_receipt_id TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    observed_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_lesson_candidates (
    lesson_candidate_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES room_v2_incidents(incident_id),
    facts_json TEXT NOT NULL,
    causes_json TEXT NOT NULL,
    applicability_boundary_json TEXT NOT NULL,
    counterexamples_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    candidate_hash TEXT NOT NULL UNIQUE CHECK(length(candidate_hash)=64),
    nominated_by TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_candidates (
    guard_candidate_id TEXT PRIMARY KEY,
    lesson_candidate_id TEXT NOT NULL REFERENCES room_v2_lesson_candidates(lesson_candidate_id),
    guard_version INTEGER NOT NULL CHECK(guard_version>=1),
    condition_json TEXT NOT NULL,
    action_json TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    risk TEXT NOT NULL CHECK(risk IN ('low','medium','high','critical')),
    thresholds_json TEXT NOT NULL,
    owner TEXT NOT NULL,
    sunset_at_ms INTEGER NOT NULL,
    candidate_hash TEXT NOT NULL UNIQUE CHECK(length(candidate_hash)=64),
    nominated_by TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    guard_candidate_id TEXT NOT NULL REFERENCES room_v2_guard_candidates(guard_candidate_id),
    candidate_hash TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('offline','shadow','canary')),
    dataset_hash TEXT NOT NULL CHECK(length(dataset_hash)=64),
    positive_fixture_count INTEGER NOT NULL CHECK(positive_fixture_count>0),
    negative_fixture_count INTEGER NOT NULL CHECK(negative_fixture_count>0),
    metrics_json TEXT NOT NULL,
    runner_receipt_id TEXT NOT NULL REFERENCES room_v2_verification_receipts(receipt_id),
    status TEXT NOT NULL CHECK(status IN ('passed','failed')),
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_approval_receipts (
    approval_receipt_id TEXT PRIMARY KEY,
    guard_candidate_id TEXT NOT NULL REFERENCES room_v2_guard_candidates(guard_candidate_id),
    candidate_hash TEXT NOT NULL,
    authority_ref TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('approve','reject')),
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    authority_signature TEXT NOT NULL CHECK(length(authority_signature)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_active_pointers (
    scope_key TEXT PRIMARY KEY,
    guard_epoch INTEGER NOT NULL CHECK(guard_epoch>=0),
    active_guard_candidate_id TEXT REFERENCES room_v2_guard_candidates(guard_candidate_id),
    active_candidate_hash TEXT NOT NULL DEFAULT '',
    activation_receipt_id TEXT,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_activation_receipts (
    activation_receipt_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    guard_candidate_id TEXT NOT NULL REFERENCES room_v2_guard_candidates(guard_candidate_id),
    candidate_hash TEXT NOT NULL,
    previous_guard_candidate_id TEXT,
    previous_activation_receipt_id TEXT,
    guard_epoch INTEGER NOT NULL,
    applies_to_roots_created_after_ms INTEGER NOT NULL,
    approval_receipt_id TEXT NOT NULL REFERENCES room_v2_guard_approval_receipts(approval_receipt_id),
    eval_run_ids_json TEXT NOT NULL,
    signed_config_hash TEXT NOT NULL CHECK(length(signed_config_hash)=64),
    config_signature TEXT NOT NULL CHECK(length(config_signature)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_execution_bindings (
    dispatch_id TEXT PRIMARY KEY REFERENCES room_kernel_dispatches(dispatch_id),
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id),
    scope_key TEXT NOT NULL,
    guard_candidate_id TEXT NOT NULL REFERENCES room_v2_guard_candidates(guard_candidate_id),
    guard_epoch INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','cancel_requested','terminal')),
    bound_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_rollback_receipts (
    rollback_receipt_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    from_guard_candidate_id TEXT NOT NULL,
    restored_guard_candidate_id TEXT,
    guard_epoch INTEGER NOT NULL,
    cancelled_dispatch_ids_json TEXT NOT NULL,
    authority_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    authority_signature TEXT NOT NULL CHECK(length(authority_signature)=64),
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TRIGGER room_v2_incident_no_update BEFORE UPDATE ON room_v2_incidents BEGIN SELECT RAISE(ABORT,'Incident is immutable'); END;
CREATE TRIGGER room_v2_incident_no_delete BEFORE DELETE ON room_v2_incidents BEGIN SELECT RAISE(ABORT,'Incident is permanent'); END;
CREATE TRIGGER room_v2_lesson_no_update BEFORE UPDATE ON room_v2_lesson_candidates BEGIN SELECT RAISE(ABORT,'LessonCandidate is immutable'); END;
CREATE TRIGGER room_v2_lesson_no_delete BEFORE DELETE ON room_v2_lesson_candidates BEGIN SELECT RAISE(ABORT,'LessonCandidate is permanent'); END;
CREATE TRIGGER room_v2_guard_candidate_no_update BEFORE UPDATE ON room_v2_guard_candidates BEGIN SELECT RAISE(ABORT,'GuardCandidate is immutable'); END;
CREATE TRIGGER room_v2_guard_candidate_no_delete BEFORE DELETE ON room_v2_guard_candidates BEGIN SELECT RAISE(ABORT,'GuardCandidate is permanent'); END;
CREATE TRIGGER room_v2_guard_eval_no_update BEFORE UPDATE ON room_v2_guard_eval_runs BEGIN SELECT RAISE(ABORT,'GuardEvalRun is immutable'); END;
CREATE TRIGGER room_v2_guard_approval_no_update BEFORE UPDATE ON room_v2_guard_approval_receipts BEGIN SELECT RAISE(ABORT,'GuardApprovalReceipt is immutable'); END;
CREATE TRIGGER room_v2_guard_activation_no_update BEFORE UPDATE ON room_v2_guard_activation_receipts BEGIN SELECT RAISE(ABORT,'GuardActivationReceipt is immutable'); END;
CREATE TRIGGER room_v2_guard_rollback_no_update BEFORE UPDATE ON room_v2_guard_rollback_receipts BEGIN SELECT RAISE(ABORT,'GuardRollbackReceipt is immutable'); END;
