/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-peer-invitation.v1.json
 */

export interface RoomPeerInvitationV1 {
  schemaVersion: 'wisdom-weasel.room-peer-invitation.v1';
  invitationId: string;
  rootId: string;
  parentTaskId: string;
  parentDispatchId: string;
  openedByParticipantId: string;
  offeredToParticipantId: string | null;
  winnerParticipantId: string | null;
  intent: 'execute' | 'review' | 'revise';
  objective: string;
  expectedOutput: string;
  /**
   * @minItems 1
   */
  acceptanceCriterionIds: [string, ...string[]];
  contextEvidenceRefs: string[];
  state:
    | 'open'
    | 'offered'
    | 'accepted'
    | 'returned'
    | 'counterproposed'
    | 'review_ready'
    | 'cancelled'
    | 'expired';
  revision: number;
  responseReceiptId: string | null;
  availableActions: ('accept' | 'return' | 'counterproposal' | 'review_ready')[];
  createdAtMs: number;
  updatedAtMs: number;
}
