export const ROOM_RUNTIME_PROTOCOL_VERSION = "2" as const;

export const ROOM_RUNTIME_METHODS = [
  "session.control_state",
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

export type RoomDispatchParams = {
  sessionId: string;
  rootId: string;
  dispatchId: string;
  generation: number;
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
  sessionId: string;
  rootId: string;
  generation: number;
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
  duplicate?: boolean;
};

export type RoomCancelReceipt = {
  schemaVersion: "wisdom-weasel.room-runtime-receipt.v1";
  receiptKind: "cancel_applied";
  status: "applied";
  sessionId: string;
  rootId: string;
  generation: number;
  cancelledContinuationIds: string[];
  activeRunAborted: boolean;
};

export type RoomRuntimeRequest =
  | { method: "session.control_state"; params: SessionControlStateParams }
  | { method: "room.dispatch"; params: RoomDispatchParams }
  | { method: "room.cancel"; params: RoomCancelParams };

export type RoomRuntimeReceipt =
  | SessionControlStateReceipt
  | RoomDispatchReceipt
  | RoomCancelReceipt;
