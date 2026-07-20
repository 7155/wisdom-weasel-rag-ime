CREATE TABLE IF NOT EXISTS room_v2_requirement_anchors (
    anchor_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    root_sequence INTEGER NOT NULL CHECK (root_sequence >= 1),
    original_bytes BLOB NOT NULL,
    original_sha256 TEXT NOT NULL CHECK (length(original_sha256) = 64),
    created_by TEXT NOT NULL CHECK (length(created_by) > 0),
    authenticity TEXT NOT NULL
        CHECK (authenticity IN ('original_user_bytes', 'legacy_quarantined')),
    provenance_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(root_id, root_sequence)
);

CREATE TRIGGER room_v2_requirement_anchors_no_update
BEFORE UPDATE ON room_v2_requirement_anchors BEGIN
    SELECT RAISE(ABORT, 'RequirementAnchor is immutable');
END;

CREATE TRIGGER room_v2_requirement_anchors_no_delete
BEFORE DELETE ON room_v2_requirement_anchors BEGIN
    SELECT RAISE(ABORT, 'RequirementAnchor is permanent');
END;

CREATE TABLE IF NOT EXISTS room_v2_requirement_catalog_revisions (
    catalog_revision_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    supersedes_revision_id TEXT,
    anchor_refs_json TEXT NOT NULL,
    change_reason TEXT NOT NULL CHECK (length(change_reason) > 0),
    provenance_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    created_by TEXT NOT NULL CHECK (length(created_by) > 0),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(root_id, revision),
    FOREIGN KEY(supersedes_revision_id)
        REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS room_v2_requirement_items (
    catalog_revision_id TEXT NOT NULL
        REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id) ON DELETE RESTRICT,
    item_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'explicit_user_requirement', 'system_hard_constraint',
        'agent_inferred_requirement', 'implementation_suggestion'
    )),
    statement TEXT NOT NULL CHECK (length(statement) > 0),
    origin TEXT NOT NULL CHECK (length(origin) > 0),
    state TEXT NOT NULL CHECK (state IN (
        'active', 'needs_confirmation', 'withdrawn', 'superseded'
    )),
    source_spans_json TEXT NOT NULL,
    supersedes_json TEXT NOT NULL,
    ambiguity TEXT NOT NULL DEFAULT '',
    confirmation TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(catalog_revision_id, item_id)
);

CREATE TABLE IF NOT EXISTS room_v2_acceptance_criteria (
    catalog_revision_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    acceptance_criterion_full_name_zh TEXT NOT NULL CHECK (
        length(acceptance_criterion_full_name_zh) > 0
    ),
    criterion_kind TEXT NOT NULL CHECK (criterion_kind IN ('requirement', 'user_journey')),
    expected_receipt_types_json TEXT NOT NULL,
    statement TEXT NOT NULL CHECK (length(statement) > 0),
    PRIMARY KEY(catalog_revision_id, criterion_id),
    FOREIGN KEY(catalog_revision_id, item_id)
        REFERENCES room_v2_requirement_items(catalog_revision_id, item_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS room_v2_verification_receipts (
    receipt_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    catalog_revision_id TEXT NOT NULL
        REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id) ON DELETE RESTRICT,
    receipt_type TEXT NOT NULL CHECK (receipt_type IN ('test', 'build', 'install', 'evidence')),
    source_commit TEXT NOT NULL CHECK (length(source_commit) > 0),
    environment TEXT NOT NULL CHECK (length(environment) > 0),
    command_or_action TEXT NOT NULL CHECK (length(command_or_action) > 0),
    exit_status INTEGER NOT NULL,
    output_hash TEXT NOT NULL CHECK (length(output_hash) = 64),
    artifact_hash TEXT NOT NULL CHECK (length(artifact_hash) = 64),
    verifier TEXT NOT NULL CHECK (length(verifier) > 0),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS room_v2_criterion_proofs (
    proof_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    catalog_revision_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL
        REFERENCES room_v2_verification_receipts(receipt_id) ON DELETE RESTRICT,
    linked_by TEXT NOT NULL CHECK (length(linked_by) > 0),
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY(catalog_revision_id, criterion_id)
        REFERENCES room_v2_acceptance_criteria(catalog_revision_id, criterion_id) ON DELETE RESTRICT,
    UNIQUE(catalog_revision_id, criterion_id, receipt_id)
);

CREATE TABLE IF NOT EXISTS room_v2_requirement_conflicts (
    conflict_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    catalog_revision_id TEXT NOT NULL
        REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id) ON DELETE RESTRICT,
    left_item_id TEXT NOT NULL,
    right_item_id TEXT NOT NULL,
    conflict_kind TEXT NOT NULL CHECK (conflict_kind IN ('contradiction', 'unknown', 'ambiguity')),
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    resolution TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    UNIQUE(catalog_revision_id, left_item_id, right_item_id, conflict_kind)
);

CREATE TABLE IF NOT EXISTS room_v2_delivery_obstacles (
    obstacle_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    catalog_revision_id TEXT NOT NULL
        REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id) ON DELETE RESTRICT,
    obstacle_kind TEXT NOT NULL CHECK (obstacle_kind IN ('blocker', 'unknown')),
    statement TEXT NOT NULL CHECK (length(statement) > 0),
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    created_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS room_v2_delivery_gate_receipts (
    gate_receipt_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    catalog_revision_id TEXT NOT NULL
        REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id) ON DELETE RESTRICT,
    target_commit TEXT NOT NULL CHECK (length(target_commit) > 0),
    mode TEXT NOT NULL CHECK (mode = 'observe_warn'),
    gate_status TEXT NOT NULL CHECK (gate_status IN ('observed_pass', 'warn_blocked')),
    enforcement_applied INTEGER NOT NULL CHECK (enforcement_applied = 0),
    blind_review_status TEXT NOT NULL CHECK (
        blind_review_status IN ('pending', 'passed', 'failed', 'unavailable')
    ),
    reasons_json TEXT NOT NULL,
    proof_matrix_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TRIGGER room_v2_requirement_catalog_no_update
BEFORE UPDATE ON room_v2_requirement_catalog_revisions BEGIN
    SELECT RAISE(ABORT, 'RequirementCatalogRevision is immutable');
END;
CREATE TRIGGER room_v2_requirement_catalog_no_delete
BEFORE DELETE ON room_v2_requirement_catalog_revisions BEGIN
    SELECT RAISE(ABORT, 'RequirementCatalogRevision is permanent');
END;
CREATE TRIGGER room_v2_requirement_items_no_update
BEFORE UPDATE ON room_v2_requirement_items BEGIN
    SELECT RAISE(ABORT, 'RequirementItem snapshot is immutable');
END;
CREATE TRIGGER room_v2_requirement_items_no_delete
BEFORE DELETE ON room_v2_requirement_items BEGIN
    SELECT RAISE(ABORT, 'RequirementItem snapshot is permanent');
END;
CREATE TRIGGER room_v2_acceptance_criteria_no_update
BEFORE UPDATE ON room_v2_acceptance_criteria BEGIN
    SELECT RAISE(ABORT, 'AcceptanceCriterion snapshot is immutable');
END;
CREATE TRIGGER room_v2_acceptance_criteria_no_delete
BEFORE DELETE ON room_v2_acceptance_criteria BEGIN
    SELECT RAISE(ABORT, 'AcceptanceCriterion snapshot is permanent');
END;
CREATE TRIGGER room_v2_verification_receipts_no_update
BEFORE UPDATE ON room_v2_verification_receipts BEGIN
    SELECT RAISE(ABORT, 'VerificationReceipt is immutable');
END;
CREATE TRIGGER room_v2_verification_receipts_no_delete
BEFORE DELETE ON room_v2_verification_receipts BEGIN
    SELECT RAISE(ABORT, 'VerificationReceipt is permanent');
END;
