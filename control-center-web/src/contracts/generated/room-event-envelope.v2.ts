/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-event-envelope.v2.json
 */

export interface RoomEventEnvelopeV2 {
  schemaVersion: 'wisdom-weasel.room-event-envelope.v2';
  entityKind: 'root' | 'task' | 'dispatch' | 'commit' | 'post' | 'binding';
  entityId: string;
  eventKind: string;
  sequence: number;
  occurredAtMs: number;
  payload: {
    [k: string]: unknown;
  };
}
