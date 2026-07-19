/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-dispatch-envelope.v2.json
 */

export interface RoomDispatchEnvelopeV2 {
  schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2';
  dispatchId: string;
  rootId: string;
  taskId: string;
  parentDispatchId: string | null;
  generation: number;
  targetSessionId: string;
  targetParticipantId: string;
  triggerId: string;
  intentKind: 'execute' | 'review' | 'revise' | 'resume' | 'retry' | 'wake' | 'callback';
  idempotencyKey: string;
  attempt: number;
  capabilityEpoch: number;
  runtimeProfileRevision: string;
  state: 'pending' | 'leased' | 'running' | 'committed' | 'unknown' | 'failed' | 'cancelled';
}
