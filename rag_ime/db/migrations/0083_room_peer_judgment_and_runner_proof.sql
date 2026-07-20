ALTER TABLE room_v2_verification_receipts ADD COLUMN receipt_schema_version TEXT NOT NULL DEFAULT 'wisdom-weasel.typed-verification-receipt.v1';
ALTER TABLE room_v2_verification_receipts ADD COLUMN worktree_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE room_v2_verification_receipts ADD COLUMN tool_version TEXT NOT NULL DEFAULT '';
ALTER TABLE room_v2_verification_receipts ADD COLUMN receipt_content_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE room_v2_verification_receipts ADD COLUMN issuer_id TEXT NOT NULL DEFAULT '';
ALTER TABLE room_v2_verification_receipts ADD COLUMN issuer_signature TEXT NOT NULL DEFAULT '';
ALTER TABLE room_v2_verification_receipts ADD COLUMN issuer_trust TEXT NOT NULL DEFAULT 'legacy_unsealed'
    CHECK (issuer_trust IN ('legacy_unsealed', 'runner_signed'));
ALTER TABLE room_v2_verification_receipts ADD COLUMN runner_receipt_type TEXT NOT NULL DEFAULT '';

CREATE TABLE room_v2_peer_judgment_rounds (
    round_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    root_id TEXT NOT NULL,
    catalog_revision_id TEXT NOT NULL REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id),
    target_commit TEXT NOT NULL,
    artifact_content_hash TEXT NOT NULL CHECK(length(artifact_content_hash) = 64),
    blind_input_hash TEXT NOT NULL CHECK(length(blind_input_hash) = 64),
    blind_input_json TEXT NOT NULL,
    author_participant_ids_json TEXT NOT NULL,
    minimum_reviewers INTEGER NOT NULL CHECK(minimum_reviewers >= 2),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_peer_judgments (
    judgment_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES room_v2_peer_judgment_rounds(round_id),
    reviewer_participant_id TEXT NOT NULL REFERENCES agent_room_participants(id),
    reviewer_session_id TEXT NOT NULL,
    reviewer_binding_id TEXT NOT NULL,
    reviewer_independence_key TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('pass', 'fail', 'abstain')),
    findings_json TEXT NOT NULL,
    requirement_coverage_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(round_id, reviewer_participant_id),
    UNIQUE(round_id, reviewer_independence_key)
);

CREATE TABLE room_v2_conflict_matrix_revisions (
    matrix_revision_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES room_v2_peer_judgment_rounds(round_id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_revision_id TEXT REFERENCES room_v2_conflict_matrix_revisions(matrix_revision_id),
    status TEXT NOT NULL CHECK(status IN ('open', 'resolved')),
    entries_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(round_id, revision)
);

CREATE TABLE room_v2_conflict_resolution_receipts (
    resolution_receipt_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES room_v2_peer_judgment_rounds(round_id),
    matrix_revision_id TEXT NOT NULL REFERENCES room_v2_conflict_matrix_revisions(matrix_revision_id),
    authority_kind TEXT NOT NULL CHECK(authority_kind IN ('independent_arbiter', 'user')),
    authority_ref TEXT NOT NULL,
    resolution_verdict TEXT NOT NULL CHECK(resolution_verdict IN ('pass', 'fail')),
    rationale TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_peer_judgment_final_receipts (
    final_receipt_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL UNIQUE REFERENCES room_v2_peer_judgment_rounds(round_id),
    status TEXT NOT NULL CHECK(status IN ('passed', 'failed', 'conflict')),
    judgment_ids_json TEXT NOT NULL,
    conflict_matrix_revision_id TEXT REFERENCES room_v2_conflict_matrix_revisions(matrix_revision_id),
    resolution_receipt_id TEXT REFERENCES room_v2_conflict_resolution_receipts(resolution_receipt_id),
    payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_delivery_gate_preview_receipts (
    preview_receipt_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    catalog_revision_id TEXT NOT NULL REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id),
    peer_round_id TEXT NOT NULL REFERENCES room_v2_peer_judgment_rounds(round_id),
    environment TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('observe_warn', 'room_v2_test_enforce_preview')),
    terminal_allowed INTEGER NOT NULL CHECK(terminal_allowed IN (0, 1)),
    reasons_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
    created_at_ms INTEGER NOT NULL
);

CREATE TRIGGER room_v2_peer_round_no_update BEFORE UPDATE ON room_v2_peer_judgment_rounds BEGIN SELECT RAISE(ABORT, 'PeerJudgmentRound is immutable'); END;
CREATE TRIGGER room_v2_peer_round_no_delete BEFORE DELETE ON room_v2_peer_judgment_rounds BEGIN SELECT RAISE(ABORT, 'PeerJudgmentRound is permanent'); END;
CREATE TRIGGER room_v2_peer_judgment_no_update BEFORE UPDATE ON room_v2_peer_judgments BEGIN SELECT RAISE(ABORT, 'PeerJudgment is immutable'); END;
CREATE TRIGGER room_v2_peer_judgment_no_delete BEFORE DELETE ON room_v2_peer_judgments BEGIN SELECT RAISE(ABORT, 'PeerJudgment is permanent'); END;
CREATE TRIGGER room_v2_conflict_matrix_no_update BEFORE UPDATE ON room_v2_conflict_matrix_revisions BEGIN SELECT RAISE(ABORT, 'ConflictMatrixRevision is immutable'); END;
CREATE TRIGGER room_v2_conflict_matrix_no_delete BEFORE DELETE ON room_v2_conflict_matrix_revisions BEGIN SELECT RAISE(ABORT, 'ConflictMatrixRevision is permanent'); END;
CREATE TRIGGER room_v2_conflict_resolution_no_update BEFORE UPDATE ON room_v2_conflict_resolution_receipts BEGIN SELECT RAISE(ABORT, 'ConflictResolutionReceipt is immutable'); END;
CREATE TRIGGER room_v2_conflict_resolution_no_delete BEFORE DELETE ON room_v2_conflict_resolution_receipts BEGIN SELECT RAISE(ABORT, 'ConflictResolutionReceipt is permanent'); END;
CREATE TRIGGER room_v2_peer_final_no_update BEFORE UPDATE ON room_v2_peer_judgment_final_receipts BEGIN SELECT RAISE(ABORT, 'PeerJudgmentFinalReceipt is immutable'); END;
CREATE TRIGGER room_v2_peer_final_no_delete BEFORE DELETE ON room_v2_peer_judgment_final_receipts BEGIN SELECT RAISE(ABORT, 'PeerJudgmentFinalReceipt is permanent'); END;
CREATE TRIGGER room_v2_gate_preview_no_update BEFORE UPDATE ON room_v2_delivery_gate_preview_receipts BEGIN SELECT RAISE(ABORT, 'DeliveryGatePreviewReceipt is immutable'); END;
CREATE TRIGGER room_v2_gate_preview_no_delete BEFORE DELETE ON room_v2_delivery_gate_preview_receipts BEGIN SELECT RAISE(ABORT, 'DeliveryGatePreviewReceipt is permanent'); END;
