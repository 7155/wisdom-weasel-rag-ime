/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/memory-governance-preview.v1.json
 */

export interface MemoryGovernancePreviewV1 {
  schemaVersion: 'rag-ime.memory-governance-preview.v1';
  previewId: string;
  proposalId: string;
  operation: 'remember_preview' | 'correct_preview' | 'forget_preview';
  applyOperation: 'remember_apply' | 'correct_apply' | 'forget_apply';
  sessionId: string;
  project: string;
  targetId: string;
  memoryKind: '' | 'fact' | 'preference' | 'decision' | 'commitment' | 'project_state';
  proposedText: string;
  reason: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  evidenceIds:
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
  summary: string;
  status: 'ready' | 'applied' | 'rolled_back' | 'expired' | 'failed';
  reviewRequired: true;
  applyOperationAvailable: boolean;
  mutationApplied: false;
  writes: {
    proposalStored: true;
    memoryAtoms: false;
    memoryBooks: false;
    retrievalVectors: false;
  };
  audit: {
    payloadSha256: string;
    recordKind: 'memory_governance_proposal';
    sessionId: string;
    idempotencyKey: string;
  };
  createdAtMs: number;
  expiresAtMs: number;
}
