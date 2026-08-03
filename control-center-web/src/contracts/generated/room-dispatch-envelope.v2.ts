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
  hopCount: number;
  depth: number;
  budgetCost: number;
  targetSessionId: string;
  targetParticipantId: string;
  triggerId: string;
  intentKind:
    'align' | 'execute' | 'review' | 'revise' | 'resume' | 'retry' | 'wake' | 'callback' | 'close';
  idempotencyKey: string;
  attempt: number;
  capabilityEpoch: number;
  runtimeProfileRevision: string;
  alignmentOrdinal?: number;
  /**
   * @maxItems 16
   */
  dependsOnDispatchIds?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
  /**
   * @maxItems 8
   */
  attachmentIds?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  state:
    | 'pending'
    | 'leased'
    | 'running'
    | 'retry_wait'
    | 'timer_wait'
    | 'committed'
    | 'unknown'
    | 'dead_letter'
    | 'failed'
    | 'cancelled';
}
