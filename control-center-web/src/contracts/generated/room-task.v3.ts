/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-task.v3.json
 */

export interface RoomTaskV3 {
  schemaVersion: 'wisdom-weasel.room-task.v3';
  taskId: string;
  rootId: string;
  parentTaskId: string | null;
  taskKind: 'work' | 'invitation' | 'review';
  currentOwnerParticipantId: string;
  ownershipRevision: number;
  ownershipReceiptId: string | null;
  objective: string;
  expectedOutput: string;
  requirementItemIds: string[];
  acceptanceCriterionIds: string[];
  contextEvidenceRefs: string[];
  invitationId: string | null;
  reviewOfTaskIds: string[];
  reviewAuthorParticipantIds: string[];
  reviewState: 'not_required' | 'required' | 'in_review' | 'accepted' | 'changes_requested';
  revision: number;
  state:
    'pending' | 'active' | 'review' | 'waiting' | 'blocked' | 'completed' | 'failed' | 'cancelled';
}
