/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-kernel-command.v1.json
 */

export interface RoomKernelCommandV1 {
  schemaVersion: 'wisdom-weasel.room-kernel-command.v1';
  commandId: string;
  rootId: string | null;
  roomId: string;
  commandKind:
    | 'dispatch'
    | 'commit'
    | 'settle'
    | 'cancel_target'
    | 'cancel_root'
    | 'retry_root'
    | 'panic'
    | 'reconcile';
  targetKind: 'root' | 'task' | 'dispatch' | null;
  targetId: string | null;
  sourceKind: string;
  sourceId: string;
  idempotencyKey: string;
  generation: number;
  payload: {
    [k: string]: unknown;
  };
  createdAtMs: number;
}
