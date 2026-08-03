/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-commit.v4.json
 */

export interface RoomCommitV4 {
  schemaVersion: 'wisdom-weasel.room-commit.v4';
  commitId: string;
  dispatchId: string;
  action: 'post' | 'dispatch' | 'wait' | 'complete' | 'block';
  contentHash: string;
  postProposal: {
    [k: string]: unknown;
  } | null;
  postInvocationReceiptId?: string;
  continuation?: null | {
    [k: string]: unknown;
  };
  qualityGateReceipt: QualityGateReceipt;
  evidenceRefs: string[];
  requirementCoverage: string[];
  /**
   * @maxItems 64
   */
  reviewFindings?: ReviewFinding[];
  /**
   * @maxItems 64
   */
  reviewFindingResponses?: ReviewFindingResponse[];
  reviewEvidenceBinding?: ReviewEvidenceBinding;
  createdAtMs: number;
}
export interface QualityGateReceipt {
  schemaVersion: 'wisdom-weasel.room-quality-gate-receipt.v1';
  receiptId: string;
  rootId: string;
  taskId: string;
  dispatchId: string;
  generation: number;
  originalRequestChecked: boolean;
  verdict: 'ready_to_deliver' | 'not_ready';
  /**
   * @maxItems 64
   */
  items: {
    criterionId: string;
    status: 'pass' | 'fail' | 'not_verified';
    /**
     * @maxItems 64
     */
    evidenceRefs: string[];
  }[];
  /**
   * @maxItems 32
   */
  residualRisks: string[];
  createdAtMs: number;
}
export interface ReviewFinding {
  findingId: string;
  fingerprint: string;
  gateEffect: 'blocking' | 'advisory';
  impact: 'critical' | 'high' | 'normal';
  category:
    | 'correctness'
    | 'security'
    | 'privacy'
    | 'data_loss'
    | 'authorization'
    | 'permission'
    | 'destructive_behavior'
    | 'core_runtime_unavailable'
    | 'regression'
    | 'review_target_identity'
    | 'spec_mismatch'
    | 'ux'
    | 'performance'
    | 'maintainability'
    | 'test'
    | 'documentation';
  scope: {
    [k: string]: unknown;
  };
  observation: string;
  expected: string;
  userImpact: string;
  /**
   * @minItems 1
   * @maxItems 64
   */
  evidenceRefs: [string, ...string[]];
  /**
   * @minItems 1
   * @maxItems 16
   */
  reproduction:
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
  state: 'open' | 'resolved' | 'dismissed' | 'accepted_risk' | 'contested' | 'escalated';
  dispositionRationale?: string | null;
  ownerParticipantId?: string | null;
  firstSeenRevision: string;
  lastCheckedRevision: string;
  failedRechecks: number;
  response: null | ReviewFindingResponse;
}
export interface ReviewFindingResponse {
  findingId: string;
  action: 'fixed' | 'contest';
  rationale: string;
  /**
   * @minItems 1
   * @maxItems 64
   */
  evidenceRefs: [string, ...string[]];
  participantId: string;
  createdAtMs: number;
}
export interface ReviewEvidenceBinding {
  schemaVersion: 'wisdom-weasel.review-evidence-binding.v1';
  bindingId: string;
  reviewTargetRevision: string;
  taskId: string;
  dispatchId: string;
  /**
   * @maxItems 64
   */
  evidenceRefs: string[];
  notBeforeMs: number;
}
