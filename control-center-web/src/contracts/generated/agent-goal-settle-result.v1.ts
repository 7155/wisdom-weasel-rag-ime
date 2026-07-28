/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-goal-settle-result.v1.json
 */

export interface AgentGoalSettleResultV1 {
  schemaVersion: 'rag-ime.agent-goal-settle-result.v1';
  sessionId: string;
  goalId: string;
  goalRevision: number;
  settleScopeId: string;
  settleAttempt: number;
  freshToolEvidenceCount: number;
  freshToolEvidenceSha256: string;
  continuationEpoch: number;
  continuationCount: number;
  continuationLimit: number;
  continuationRemaining: number;
  state:
    | 'inactive'
    | 'continue'
    | 'paused'
    | 'completed'
    | 'cancelled'
    | 'blocked'
    | 'stalled'
    | 'budget_exhausted';
  reason: string;
  followUpKey: string;
  message: string;
}
