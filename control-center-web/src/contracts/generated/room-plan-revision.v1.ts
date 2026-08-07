/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-plan-revision.v1.json
 */

export interface RoomPlanRevisionV1 {
  schemaVersion: 'wisdom-weasel.room-plan-revision.v1';
  planRevisionId: string;
  rootId: string;
  revision: number;
  state: 'proposed' | 'active' | 'superseded' | 'cancelled';
  requirementCatalogRevisionId: string;
  /**
   * @minItems 1
   * @maxItems 12
   */
  tasks:
    | [Task]
    | [Task, Task]
    | [Task, Task, Task]
    | [Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task, Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task, Task, Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task, Task, Task, Task, Task, Task, Task]
    | [Task, Task, Task, Task, Task, Task, Task, Task, Task, Task, Task, Task];
  createdAtMs: number;
  activatedAtMs: number | null;
  workDocumentRef: null | {
    documentId: string;
    contentSha256: string;
    documentRevision: number;
  };
}
export interface Task {
  taskId: string;
  kind: 'feature' | 'integration' | 'review';
  title: string;
  userOutcome: string;
  ownerParticipantId: string;
  participantRef: string;
  dependencyTaskIds: string[];
  dependencyTitles: string[];
  wave: number;
  writeBoundary: string;
  workspacePolicy: 'read_only' | 'shared_single_writer' | 'isolated_writable';
  acceptanceCriterionIds: string[];
  scopeTaskIds: string[];
  authorParticipantIds: string[];
}
