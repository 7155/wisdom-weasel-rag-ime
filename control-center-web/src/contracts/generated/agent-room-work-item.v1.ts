/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-room-work-item.v1.json
 */

export interface AgentRoomWorkItemV1 {
  schemaVersion: 'rag-ime.agent-room-work-item.v1';
  id: string;
  roomId: string;
  topicId: string;
  rootTurnId: string;
  rootWorkId: string;
  parentWorkId: string;
  objective: string;
  expectedOutput: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  acceptanceCriteria:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  accountableParticipantId: string;
  currentOwnerParticipantId: string;
  offeredToParticipantId: string;
  createdByParticipantId: string;
  clientMessageId: string;
  assignmentKey: string;
  state: 'queued' | 'active' | 'review' | 'blocked' | 'done' | 'failed' | 'cancelled';
  depth: number;
  revision: number;
  resultSummary: string;
  /**
   * @maxItems 16
   */
  artifactRefs:
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
   * @maxItems 24
   */
  evidenceRefs: string[];
  proposedOperabilityVerdict: '' | 'passed' | 'failed' | 'unverified';
  proposedRequirementVerdict: '' | 'satisfied' | 'not_satisfied' | 'unverified';
  review: {
    operabilityVerdict: '' | 'passed' | 'failed' | 'unverified';
    requirementVerdict: '' | 'satisfied' | 'not_satisfied' | 'unverified';
    /**
     * @maxItems 24
     */
    evidenceRefs: string[];
    reason: string;
    reviewerParticipantId: string;
    reviewedAtMs: number | null;
  };
  blocker: {
    [k: string]: unknown;
  };
  acceptedTurnId: string;
  createdAtMs: number;
  updatedAtMs: number;
  completedAtMs: number | null;
}
