CREATE TABLE room_v2_rollout_policies (
    policy_id TEXT PRIMARY KEY,
    previous_policy_id TEXT REFERENCES room_v2_rollout_policies(policy_id),
    stage TEXT NOT NULL CHECK(stage IN ('off','shadow','named_canary','production_cohort','kernel_only')),
    cohort_id TEXT NOT NULL,
    readiness_hash TEXT NOT NULL CHECK(length(readiness_hash)=64),
    readiness_json TEXT NOT NULL,
    canary_metrics_json TEXT NOT NULL,
    rollback_target TEXT NOT NULL,
    admin_ref TEXT NOT NULL,
    approval_signature TEXT NOT NULL CHECK(length(approval_signature)=64),
    created_at_ms INTEGER NOT NULL,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    UNIQUE(stage,cohort_id,readiness_hash)
);
CREATE UNIQUE INDEX idx_room_v2_rollout_active ON room_v2_rollout_policies(active) WHERE active=1;

CREATE TABLE room_v2_rollout_receipts (
    receipt_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES room_v2_rollout_policies(policy_id),
    action TEXT NOT NULL CHECK(action IN ('promote','rollback')),
    from_stage TEXT NOT NULL,
    to_stage TEXT NOT NULL,
    affected_root_ids_json TEXT NOT NULL,
    ledger_hash TEXT NOT NULL CHECK(length(ledger_hash)=64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_root_execution_owners (
    root_id TEXT PRIMARY KEY,
    execution_owner TEXT NOT NULL CHECK(execution_owner IN ('legacy','kernel')),
    policy_id TEXT NOT NULL REFERENCES room_v2_rollout_policies(policy_id),
    cohort_id TEXT NOT NULL,
    assigned_at_ms INTEGER NOT NULL,
    cancelled_at_ms INTEGER NOT NULL DEFAULT 0
);
