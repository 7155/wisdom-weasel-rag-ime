ALTER TABLE room_kernel_continuations
RENAME TO room_kernel_continuations_v143;

CREATE TABLE room_kernel_continuations (
    continuation_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL
        REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL
        REFERENCES room_kernel_tasks(task_id) ON DELETE CASCADE,
    parent_dispatch_id TEXT NOT NULL
        REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    child_dispatch_id TEXT
        REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE SET NULL,
    commit_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL
        CHECK(decision IN ('dispatch','wait','block','complete','post')),
    state TEXT NOT NULL
        CHECK(state IN ('applied','resumed','retry_required','blocked')),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

INSERT INTO room_kernel_continuations(
    continuation_id, root_id, task_id, parent_dispatch_id,
    child_dispatch_id, commit_id, decision, state,
    payload_json, created_at_ms
)
SELECT
    continuation.continuation_id,
    continuation.root_id,
    continuation.task_id,
    continuation.parent_dispatch_id,
    continuation.child_dispatch_id,
    continuation.commit_id,
    continuation.decision,
    CASE
        WHEN continuation.state IN ('applied', 'blocked')
         AND length(trim(coalesce(json_extract(
                 CASE WHEN json_valid(continuation.payload_json)
                      THEN continuation.payload_json ELSE '{}' END,
                 '$.resumeDispatchId'
             ), ''))) > 0
         AND EXISTS (
             SELECT 1
             FROM room_kernel_dispatches AS resumed
             WHERE resumed.dispatch_id = json_extract(
                       CASE WHEN json_valid(continuation.payload_json)
                            THEN continuation.payload_json ELSE '{}' END,
                       '$.resumeDispatchId'
                   )
               AND resumed.root_id = continuation.root_id
               AND resumed.task_id = continuation.task_id
               AND resumed.parent_dispatch_id = continuation.parent_dispatch_id
         )
         AND (
             continuation.child_dispatch_id IS NULL
             OR continuation.child_dispatch_id = json_extract(
                    CASE WHEN json_valid(continuation.payload_json)
                         THEN continuation.payload_json ELSE '{}' END,
                    '$.resumeDispatchId'
                )
         )
         AND (
             nullif(trim(coalesce(json_extract(
                 CASE WHEN json_valid(continuation.payload_json)
                      THEN continuation.payload_json ELSE '{}' END,
                 '$.answerAnchorId'
             ), '')), '') IS NULL
             OR EXISTS (
                 SELECT 1
                 FROM room_v2_requirement_anchors AS anchor
                 WHERE anchor.anchor_id = json_extract(
                           CASE WHEN json_valid(continuation.payload_json)
                                THEN continuation.payload_json ELSE '{}' END,
                           '$.answerAnchorId'
                       )
                   AND anchor.root_id = continuation.root_id
             )
         )
        THEN 'resumed'
        ELSE continuation.state
    END,
    continuation.payload_json,
    continuation.created_at_ms
FROM room_kernel_continuations_v143 AS continuation;

DROP TABLE room_kernel_continuations_v143;

CREATE INDEX idx_room_continuations_root
ON room_kernel_continuations(root_id, created_at_ms);
