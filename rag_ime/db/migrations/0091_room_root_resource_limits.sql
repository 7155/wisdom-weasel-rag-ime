CREATE TABLE room_kernel_root_limits (
    root_id TEXT PRIMARY KEY REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    deadline_at_ms INTEGER NOT NULL,
    input_token_limit INTEGER NOT NULL,
    input_token_used INTEGER NOT NULL DEFAULT 0,
    input_token_reserved INTEGER NOT NULL DEFAULT 0,
    output_token_limit INTEGER NOT NULL,
    output_token_used INTEGER NOT NULL DEFAULT 0,
    output_token_reserved INTEGER NOT NULL DEFAULT 0,
    dispatch_limit INTEGER NOT NULL,
    dispatch_used INTEGER NOT NULL DEFAULT 0,
    dispatch_reserved INTEGER NOT NULL DEFAULT 0,
    concurrency_limit INTEGER NOT NULL,
    concurrency_reserved INTEGER NOT NULL DEFAULT 0,
    tool_call_limit INTEGER NOT NULL,
    tool_call_used INTEGER NOT NULL DEFAULT 0,
    tool_call_reserved INTEGER NOT NULL DEFAULT 0,
    tool_cost_limit INTEGER NOT NULL,
    tool_cost_used INTEGER NOT NULL DEFAULT 0,
    tool_cost_reserved INTEGER NOT NULL DEFAULT 0,
    retry_limit INTEGER NOT NULL,
    retry_used INTEGER NOT NULL DEFAULT 0,
    repair_limit INTEGER NOT NULL,
    repair_used INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_kernel_dispatch_resource_reservations (
    dispatch_id TEXT PRIMARY KEY REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    tool_cost INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reserved','consumed','released')),
    actual_usage_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

INSERT INTO room_kernel_root_limits(
    root_id,deadline_at_ms,input_token_limit,output_token_limit,
    dispatch_limit,concurrency_limit,tool_call_limit,tool_cost_limit,
    retry_limit,repair_limit,updated_at_ms)
SELECT root_id,created_at_ms + 14400000,2000000,500000,64,4,500,100000,8,4,updated_at_ms
FROM room_kernel_roots;
