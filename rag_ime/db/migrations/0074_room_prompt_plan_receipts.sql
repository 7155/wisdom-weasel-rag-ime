CREATE TABLE IF NOT EXISTS room_v2_prompt_compile_receipts (
    receipt_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL CHECK (length(binding_id) > 0),
    room_id TEXT NOT NULL CHECK (length(room_id) > 0),
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
    journal_id TEXT NOT NULL
        REFERENCES room_v2_provider_projection_journals(journal_id) ON DELETE RESTRICT,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    session_epoch INTEGER NOT NULL CHECK (session_epoch >= 1),
    context_epoch INTEGER NOT NULL CHECK (context_epoch >= 1),
    capability_revision TEXT NOT NULL CHECK (length(capability_revision) > 0),
    capability_epoch INTEGER NOT NULL CHECK (capability_epoch >= 0),
    skill_policy_revision TEXT NOT NULL CHECK (length(skill_policy_revision) > 0),
    context_policy_revision TEXT NOT NULL CHECK (length(context_policy_revision) > 0),
    plan_hash TEXT NOT NULL CHECK (length(plan_hash) = 64),
    stable_prefix_hash TEXT NOT NULL CHECK (length(stable_prefix_hash) = 64),
    projection_hash TEXT NOT NULL CHECK (length(projection_hash) = 64),
    through_sequence INTEGER NOT NULL CHECK (through_sequence >= 0),
    layers_json TEXT NOT NULL,
    sealed_projection_refs_json TEXT NOT NULL,
    dynamic_tail_refs_json TEXT NOT NULL,
    omitted_layers_json TEXT NOT NULL,
    producer_audit_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(binding_id, session_epoch, context_epoch, generation, plan_hash)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_prompt_receipts_binding
ON room_v2_prompt_compile_receipts(
    binding_id, session_epoch, context_epoch, generation, created_at_ms DESC
);

CREATE TABLE IF NOT EXISTS room_v2_prompt_compare_diffs (
    diff_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL CHECK (length(binding_id) > 0),
    legacy_prompt_hash TEXT NOT NULL CHECK (length(legacy_prompt_hash) = 64),
    prompt_plan_hash TEXT NOT NULL CHECK (length(prompt_plan_hash) = 64),
    added_layer_refs_json TEXT NOT NULL,
    removed_legacy_refs_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(binding_id, legacy_prompt_hash, prompt_plan_hash)
);
