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
  taskKind: 'work' | 'invitation' | 'review' | 'report';
  workItemId?: string;
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
  reviewState:
    | 'not_required'
    | 'required'
    | 'in_review'
    | 'accepted'
    | 'accepted_with_notes'
    | 'changes_requested'
    | 'disputed'
    | 'escalated'
    | 'stale';
  resultSummary?: string;
  resultKind?: 'complete' | 'dispatch' | 'wait' | 'post' | 'block';
  resultAtMs?: number;
  verificationCount?: number;
  /**
   * @maxItems 64
   */
  verifications?: PublicVerification[];
  /**
   * @maxItems 128
   */
  artifactRefs?: string[];
  /**
   * @maxItems 32
   */
  residualRisks?: string[];
  reviewTargetRevision?: string;
  reviewEvidenceNotBeforeMs?: number;
  reviewRound?: number;
  /**
   * @maxItems 64
   */
  reviewFindings?: ReviewFinding[];
  workspacePolicy?: 'read_only' | 'shared_single_writer' | 'isolated_writable';
  workspaceRoot?: string;
  workspaceBaseRoot?: string;
  workspaceBaseCommit?: string;
  workspaceSnapshotSha256?: string;
  workspaceBindingId?: string;
  workspaceRepositoryId?: string;
  workspaceLifecycleState?:
    | 'reserved'
    | 'materialized'
    | 'work_started'
    | 'delivered'
    | 'integration_started'
    | 'integrated'
    | 'conflict'
    | 'failed'
    | 'blocked'
    | 'cancelled'
    | 'orphaned'
    | 'incomplete'
    | 'retained'
    | 'retry_bound'
    | 'abandoned'
    | 'cleanup_failed'
    | 'cleaned';
  workspaceCleanupState?:
    'not_authorized' | 'authorized' | 'retained' | 'cleaned' | 'missing' | 'failed';
  workspaceAttentionRequired?: boolean;
  workspaceDeliveryRevision?: string;
  workspaceDeliveryHead?: string;
  workspaceDeliverySnapshotSha256?: string;
  workspaceDelivery?: WorkspaceDelivery;
  workspaceIntegrationPatchSha256?: string;
  workspaceIntegratedRevision?: string;
  workspaceIntegratedSnapshotSha256?: string;
  workspaceTerminalReason?: string;
  workspaceIntegrationState?: 'not_required' | 'pending' | 'applied';
  workspaceIntegrationRef?: string | null;
  workspaceRestorePolicy?: {
    mode: 'assistant' | 'coordinator';
    toolProfileVersion: string;
    executionMode: 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';
    workspaceScopeGranted: boolean;
    workspaceScopeSha256: string;
    workspaceScopeGrantedAtMs: number;
    toolAllowlistMode: 'profile' | 'explicit';
    /**
     * @maxItems 128
     */
    allowedTools: string[];
    projectContextEnabled: boolean;
    piSkillsEnabled: boolean;
    codexSkillsEnabled: boolean;
  };
  revision: number;
  state:
    'pending' | 'active' | 'review' | 'waiting' | 'blocked' | 'completed' | 'failed' | 'cancelled';
}
export interface PublicVerification {
  label: string;
  result: 'pass' | 'fail' | 'not_verified' | 'recorded';
  source: 'quality_gate';
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
  response: null | {
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
  };
}
export interface WorkspaceDelivery {
  schemaVersion: 'wisdom-weasel.room-workspace-delivery.v1';
  ownerParticipantId: string;
  ownerSessionId: string;
  workItemId: string;
  taskId: string;
  deliveryRevision: string;
  baseCommit: string;
  workspaceSnapshotSha256: string;
  patchSha256: string;
  deliveredAtMs: number;
  resultSummary: string;
  manifestSha256: string;
  /**
   * @maxItems 512
   */
  files: WorkspaceDeliveryFile[];
  totals: WorkspaceDeliveryTotals;
  /**
   * @maxItems 128
   */
  artifactRefs: string[];
  verificationCount: number;
  /**
   * @maxItems 64
   */
  verifications: PublicVerification[];
  /**
   * @maxItems 128
   */
  verificationRefs: string[];
  /**
   * @maxItems 32
   */
  residualRisks: string[];
}
export interface WorkspaceDeliveryFile {
  path: string;
  additions: number | null;
  deletions: number | null;
  binary: boolean;
  generated: boolean;
  redacted: boolean;
}
export interface WorkspaceDeliveryTotals {
  fileCount: number;
  additions: number;
  deletions: number;
  binaryFiles: number;
  generatedFiles: number;
  redactedFiles: number;
}
