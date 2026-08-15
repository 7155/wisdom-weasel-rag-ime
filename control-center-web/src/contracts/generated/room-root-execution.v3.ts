/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-root-execution.v3.json
 */

export interface RoomRootExecutionV3 {
  schemaVersion: 'wisdom-weasel.room-root-execution.v3';
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
  facilitatorParticipantId: string;
  reporterParticipantId: string | null;
  reporterSelectionReceiptId: string | null;
  requirementAnchorRef: string;
  createdByActorRef: string;
  terminalReceiptId: string | null;
  activeProfileRef: string | null;
  budgetPolicyRef: string;
  independentReviewRequired: boolean;
  createdAtMs?: number;
}
