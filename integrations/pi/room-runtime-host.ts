export const ROOM_RUNTIME_PROTOCOL_VERSION = "2" as const;

export const ROOM_RUNTIME_METHODS = [
  "session.control_state",
  "session.await_settled",
  "room.dispatch",
  "room.cancel",
] as const;

export type RoomRuntimeMethod = (typeof ROOM_RUNTIME_METHODS)[number];

export type SessionControlStateParams = {
  sessionId: string;
};

export type SessionControlStateReceipt = {
  schemaVersion: "rag-ime.pi-session-control-state.v1";
  sessionId: string;
  isIdle: boolean;
  isCompacting: boolean;
  activeTurn?: Record<string, unknown>;
  roomCapability?: Record<string, unknown>;
  activeRoom?: Record<string, unknown>;
  sequence: number;
};

export type SessionAwaitSettledParams = {
  sessionId: string;
  turnId: string;
  allowSuspended?: boolean;
  timeoutMs?: number;
};

export type AgentSettledReceiptV2 = {
  schemaVersion: "pi.agent-settled.v2";
  receiptId: string;
  sessionId: string;
  runId: string;
  scopeId: string;
  generation: number;
  disposition: "completed" | "failed" | "aborted" | "suspended";
  stopReason:
    | "natural"
    | "error"
    | "cancelled"
    | "continuation_scheduled"
    | "settlement_rejected"
    | "operations_pending";
  finalMessage?: Record<string, unknown>;
  transcript: {
    messageCount: number;
    entryCount: number;
    leafId?: string;
    contentHash: string;
  };
  continuations: {
    pendingIds: string[];
    leasedIds: string[];
    terminalIds: string[];
    counts: Record<string, number>;
  };
  operations: {
    pending: number;
    pendingByKind: Record<string, number>;
    registeredByKind: Record<string, number>;
  };
  settledAtMs: number;
  aborted: boolean;
  pendingOperations: number;
  operationCounts: Record<string, number>;
};

export type SessionAwaitSettledReceipt = {
  schemaVersion: "rag-ime.pi-turn-settlement.v1";
  sessionId: string;
  turnId: string;
  clientMessageId?: string;
  receipt: AgentSettledReceiptV2;
};

export type RoomDispatchParams = {
  sessionId: string;
  rootId: string;
  dispatchId: string;
  generation: number;
  capabilityEpoch: number;
  dispatchAttempt: number;
  idempotencyKey: string;
  leaseToken: string;
  message: string;
  images?: Array<{
    type: "image";
    data: string;
    mimeType: "image/png" | "image/jpeg" | "image/gif" | "image/webp";
  }>;
};

export type RoomCancelParams = {
  cancelId: string;
  sessionId: string;
  rootId: string;
  dispatchId: string;
  generation: number;
  turnId: string;
  capabilityEpoch: number;
};

export type RoomCancellationSurface =
  | "provider"
  | "tool"
  | "exec"
  | "retry"
  | "compaction"
  | "branch_summary"
  | "timer"
  | "continuation"
  | "session";

export type RuntimeSurfaceTerminationReceipt = {
  schemaVersion: "wisdom-weasel.runtime-surface-termination-receipt.v1";
  surface: RoomCancellationSurface;
  state: "terminated" | "requested" | "unknown";
  targetIds: string[];
};

export type RoomDispatchReceipt = {
  schemaVersion: "wisdom-weasel.room-runtime-receipt.v1";
  receiptKind: "dispatch_accepted";
  status: "accepted";
  sessionId: string;
  rootId: string;
  dispatchId: string;
  generation: number;
  turnId: string;
  capabilityEpoch: number;
  duplicate?: boolean;
};

export type RoomCancelReceipt = {
  schemaVersion: "wisdom-weasel.room-runtime-receipt.v1";
  receiptKind: "cancel_applied";
  status: "applied";
  cancelId: string;
  sessionId: string;
  rootId: string;
  dispatchId: string;
  generation: number;
  turnId: string;
  capabilityEpoch: number;
  cancelledContinuationIds: string[];
  activeRunAborted: boolean;
  pendingTargets: RoomCancellationSurface[];
  cancellationSurfaces: Record<
    RoomCancellationSurface,
    RuntimeSurfaceTerminationReceipt
  >;
};

export type RoomRuntimeRequest =
  | { method: "session.control_state"; params: SessionControlStateParams }
  | { method: "session.await_settled"; params: SessionAwaitSettledParams }
  | { method: "room.dispatch"; params: RoomDispatchParams }
  | { method: "room.cancel"; params: RoomCancelParams };

export type RoomRuntimeReceipt =
  | SessionControlStateReceipt
  | SessionAwaitSettledReceipt
  | RoomDispatchReceipt
  | RoomCancelReceipt;
