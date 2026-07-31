ALTER TABLE room_kernel_roots RENAME COLUMN owner TO facilitator_participant_id;
ALTER TABLE room_kernel_roots ADD COLUMN reporter_participant_id TEXT;
ALTER TABLE room_kernel_roots ADD COLUMN reporter_selection_receipt_id TEXT REFERENCES room_kernel_receipts(receipt_id);

ALTER TABLE room_kernel_tasks ADD COLUMN current_owner_participant_id TEXT NOT NULL DEFAULT '';
ALTER TABLE room_kernel_tasks ADD COLUMN ownership_revision INTEGER NOT NULL DEFAULT 0 CHECK(ownership_revision >= 0);
ALTER TABLE room_kernel_tasks ADD COLUMN ownership_receipt_id TEXT REFERENCES room_kernel_receipts(receipt_id);
ALTER TABLE room_kernel_tasks ADD COLUMN task_kind TEXT NOT NULL DEFAULT 'work' CHECK(task_kind IN ('work','invitation','review'));
ALTER TABLE room_kernel_tasks ADD COLUMN invitation_id TEXT;
ALTER TABLE room_kernel_tasks ADD COLUMN review_state TEXT NOT NULL DEFAULT 'not_required' CHECK(review_state IN ('not_required','required','in_review','accepted','changes_requested'));

UPDATE room_kernel_tasks
SET current_owner_participant_id = COALESCE(
    NULLIF(json_extract(payload_json, '$.currentOwnerParticipantId'), ''),
    NULLIF(json_extract(payload_json, '$.assigneeParticipantId'), ''),
    NULLIF(json_extract(payload_json, '$.ownerParticipantId'), ''),
    ''
);

UPDATE room_kernel_tasks
SET payload_json = json_remove(
    json_set(
        payload_json,
        '$.schemaVersion', 'wisdom-weasel.room-task.v3',
        '$.taskKind', 'work',
        '$.currentOwnerParticipantId', current_owner_participant_id,
        '$.ownershipRevision', ownership_revision,
        '$.ownershipReceiptId', NULL,
        '$.invitationId', NULL,
        '$.reviewState', 'not_required',
        '$.reviewOfTaskIds', json('[]'),
        '$.reviewAuthorParticipantIds', json('[]'),
        '$.contextEvidenceRefs',
        COALESCE(json_extract(payload_json, '$.contextEvidenceRefs'), json('[]'))
    ),
    '$.ownerParticipantId',
    '$.assigneeParticipantId'
);

CREATE TABLE room_kernel_task_owner_transitions (
    receipt_id TEXT PRIMARY KEY REFERENCES room_kernel_receipts(receipt_id),
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES room_kernel_tasks(task_id) ON DELETE CASCADE,
    ownership_revision INTEGER NOT NULL CHECK(ownership_revision >= 1),
    from_participant_id TEXT NOT NULL,
    to_participant_id TEXT NOT NULL,
    source_dispatch_id TEXT NOT NULL REFERENCES room_kernel_dispatches(dispatch_id),
    source_commit_id TEXT NOT NULL REFERENCES room_kernel_commits(commit_id),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(task_id, ownership_revision)
);

CREATE TABLE room_kernel_peer_invitations (
    invitation_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    parent_task_id TEXT NOT NULL REFERENCES room_kernel_tasks(task_id) ON DELETE CASCADE,
    parent_dispatch_id TEXT NOT NULL REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    opened_by_participant_id TEXT NOT NULL,
    offered_to_participant_id TEXT,
    winner_participant_id TEXT,
    intent_kind TEXT NOT NULL CHECK(intent_kind IN ('execute','review','revise')),
    objective TEXT NOT NULL,
    expected_output TEXT NOT NULL,
    acceptance_criterion_ids_json TEXT NOT NULL,
    context_evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL CHECK(state IN ('open','offered','accepted','returned','counterproposed','review_ready','cancelled','expired')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    response_receipt_id TEXT REFERENCES room_kernel_receipts(receipt_id),
    offer_task_id TEXT REFERENCES room_kernel_tasks(task_id),
    offer_dispatch_id TEXT REFERENCES room_kernel_dispatches(dispatch_id),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_kernel_peer_invitation_responses (
    response_id TEXT PRIMARY KEY,
    invitation_id TEXT NOT NULL REFERENCES room_kernel_peer_invitations(invitation_id) ON DELETE CASCADE,
    participant_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('accept','return','counterproposal','review_ready')),
    proposal_json TEXT NOT NULL DEFAULT '{}',
    receipt_id TEXT NOT NULL UNIQUE REFERENCES room_kernel_receipts(receipt_id),
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX room_kernel_task_owner_root_idx
ON room_kernel_task_owner_transitions(root_id, task_id, ownership_revision);
CREATE INDEX room_kernel_peer_invitation_root_idx
ON room_kernel_peer_invitations(root_id, state, updated_at_ms);
CREATE INDEX room_kernel_peer_invitation_offer_idx
ON room_kernel_peer_invitations(offered_to_participant_id, state, updated_at_ms);

CREATE TRIGGER room_kernel_task_owner_transition_no_update
BEFORE UPDATE ON room_kernel_task_owner_transitions
BEGIN SELECT RAISE(ABORT, 'Room Task ownership receipts are immutable'); END;
CREATE TRIGGER room_kernel_task_owner_transition_no_delete
BEFORE DELETE ON room_kernel_task_owner_transitions
BEGIN SELECT RAISE(ABORT, 'Room Task ownership receipts are immutable'); END;
CREATE TRIGGER room_kernel_peer_invitation_response_no_update
BEFORE UPDATE ON room_kernel_peer_invitation_responses
BEGIN SELECT RAISE(ABORT, 'Room invitation responses are immutable'); END;
CREATE TRIGGER room_kernel_peer_invitation_response_no_delete
BEFORE DELETE ON room_kernel_peer_invitation_responses
BEGIN SELECT RAISE(ABORT, 'Room invitation responses are immutable'); END;
