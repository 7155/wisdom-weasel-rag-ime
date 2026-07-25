/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-task.v2.json
 */

export interface RoomTaskV2 {
  schemaVersion: 'wisdom-weasel.room-task.v2';
  taskId: string;
  rootId: string;
  parentTaskId: string | null;
  ownerParticipantId: string;
  assigneeParticipantId: string | null;
  objective: string;
  expectedOutput: string;
  requirementItemIds: string[];
  acceptanceCriterionIds: string[];
  contextEvidenceRefs?: string[];
  revision: number;
  state:
    'pending' | 'active' | 'review' | 'waiting' | 'blocked' | 'completed' | 'failed' | 'cancelled';
}
