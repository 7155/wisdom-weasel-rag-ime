export const ROOM_RUNTIME_PROTOCOL_VERSION = "2" as const;

export const ROOM_RUNTIME_METHODS = ["room.dispatch", "room.cancel"] as const;

export type RoomRuntimeMethod = (typeof ROOM_RUNTIME_METHODS)[number];

export type RoomDispatchParams = {
  sessionId: string;
  rootId: string;
  dispatchId: string;
  generation: number;
  idempotencyKey: string;
  leaseToken: string;
  message: string;
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
  | { method: "room.dispatch"; params: RoomDispatchParams }
  | { method: "room.cancel"; params: RoomCancelParams };

export type RoomRuntimeReceipt = RoomDispatchReceipt | RoomCancelReceipt;
