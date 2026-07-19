/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-root-execution.v2.json
 */

export interface RoomRootExecutionV2 {
  schemaVersion: 'wisdom-weasel.room-root-execution.v2';
  rootId: string;
  roomId: string;
  generation: number;
  state:
    | 'pending'
    | 'running'
    | 'waiting'
    | 'blocked'
    | 'cancelling'
    | 'cancelled'
    | 'cancelled_with_unknowns'
    | 'completed'
    | 'failed';
  owner: string;
  requirementAnchorRef: string;
  createdByActorRef: string;
  terminalReceiptId: string | null;
  activeProfileRef: string | null;
  budgetPolicyRef: string;
  createdAtMs: number;
}
