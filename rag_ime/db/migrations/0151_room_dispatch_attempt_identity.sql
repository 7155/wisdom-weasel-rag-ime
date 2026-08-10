CREATE TABLE room_kernel_dispatch_attempts (
    attempt_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL
        REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL
        REFERENCES room_kernel_tasks(task_id) ON DELETE CASCADE,
    dispatch_id TEXT NOT NULL
        REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    dispatch_attempt INTEGER NOT NULL CHECK(dispatch_attempt >= 0),
    generation INTEGER NOT NULL CHECK(generation >= 0),
    capability_epoch INTEGER NOT NULL CHECK(capability_epoch >= 0),
    target_session_id TEXT NOT NULL,
    target_participant_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'pending','retry_wait','leased','runtime_accepted','cancel_requested',
        'completed','failed','cancelled','unknown'
    )),
    lease_id TEXT NOT NULL DEFAULT '',
    lease_token TEXT NOT NULL DEFAULT '',
    runtime_turn_id TEXT NOT NULL DEFAULT '',
    runtime_receipt_json TEXT NOT NULL DEFAULT '{}',
    terminal_receipt_json TEXT NOT NULL DEFAULT '{}',
    dispatch_payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(dispatch_id, dispatch_attempt)
);

CREATE INDEX idx_room_kernel_dispatch_attempt_root_state
ON room_kernel_dispatch_attempts(root_id, state, updated_at_ms);

CREATE INDEX idx_room_kernel_dispatch_attempt_session
ON room_kernel_dispatch_attempts(target_session_id, state, updated_at_ms);

INSERT INTO room_kernel_dispatch_attempts(
    attempt_id,root_id,task_id,dispatch_id,dispatch_attempt,generation,
    capability_epoch,target_session_id,target_participant_id,state,
    lease_id,lease_token,runtime_turn_id,runtime_receipt_json,
    terminal_receipt_json,
    dispatch_payload_json,created_at_ms,updated_at_ms
)
SELECT
    'room-dispatch-attempt:' || dispatch.dispatch_id || ':' ||
        CAST(COALESCE(json_extract(dispatch.payload_json,'$.attempt'),0) AS TEXT),
    dispatch.root_id,
    dispatch.task_id,
    dispatch.dispatch_id,
    CAST(COALESCE(json_extract(dispatch.payload_json,'$.attempt'),0) AS INTEGER),
    dispatch.generation,
    CAST(COALESCE(json_extract(dispatch.payload_json,'$.capabilityEpoch'),0) AS INTEGER),
    dispatch.target_session_id,
    dispatch.target_participant_id,
    CASE dispatch.state
        WHEN 'leased' THEN 'leased'
        WHEN 'running' THEN CASE
            WHEN effect.state IN ('accepted','completed')
                THEN 'runtime_accepted'
            ELSE 'unknown'
        END
        WHEN 'committed' THEN 'completed'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        WHEN 'unknown' THEN 'unknown'
        WHEN 'retry_wait' THEN 'retry_wait'
        ELSE 'pending'
    END,
    COALESCE(lease.lease_id,''),
    COALESCE(lease.lease_token,''),
    COALESCE(
        (
            SELECT json_extract(
                receipt.payload_json,
                '$.details.runtimeReceipt.turnId'
            )
            FROM room_kernel_receipts AS receipt
            WHERE receipt.root_id=dispatch.root_id
              AND receipt.receipt_kind='runtime_accepted'
              AND json_extract(
                    receipt.payload_json,
                    '$.details.dispatchId'
                  )=dispatch.dispatch_id
            ORDER BY receipt.created_at_ms DESC,receipt.rowid DESC
            LIMIT 1
        ),
        json_extract(effect.runtime_receipt_json,'$.turnId'),
        ''
    ),
    COALESCE(
        (
            SELECT json_extract(
                receipt.payload_json,
                '$.details.runtimeReceipt'
            )
            FROM room_kernel_receipts AS receipt
            WHERE receipt.root_id=dispatch.root_id
              AND receipt.receipt_kind='runtime_accepted'
              AND json_extract(
                    receipt.payload_json,
                    '$.details.dispatchId'
                  )=dispatch.dispatch_id
            ORDER BY receipt.created_at_ms DESC,receipt.rowid DESC
            LIMIT 1
        ),
        CASE
            WHEN effect.state IN ('accepted','completed')
                THEN effect.runtime_receipt_json
            ELSE '{}'
        END,
        '{}'
    ),
    CASE
        WHEN effect.state IN ('failed','cancelled','unknown')
            THEN COALESCE(effect.runtime_receipt_json,'{}')
        ELSE '{}'
    END,
    dispatch.payload_json,
    dispatch.created_at_ms,
    dispatch.updated_at_ms
FROM room_kernel_dispatches AS dispatch
LEFT JOIN room_kernel_leases AS lease
    ON lease.dispatch_id=dispatch.dispatch_id
LEFT JOIN room_kernel_runtime_effects AS effect
    ON effect.dispatch_id=dispatch.dispatch_id;
