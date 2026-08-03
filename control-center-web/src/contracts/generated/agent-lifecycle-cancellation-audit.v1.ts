/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-lifecycle-cancellation-audit.v1.json
 */

export interface AgentLifecycleCancellationAuditV1 {
  schemaVersion: 'rag-ime.agent-lifecycle-cancellation-audit.v1';
  requestId: string;
  sessionId: string;
  scopeKind: 'goal';
  scopeId: string;
  sourceRevision: number;
  transitionRevision: number;
  action: 'cancel' | 'pause';
  reason: string;
  state: 'pending' | 'completed' | 'partial' | 'unknown';
  sourceTurnId: string;
  owners: {
    runtime: Owner;
    approval: Owner;
    job: Owner;
    delegation: Owner;
  };
  createdAtMs: number;
  updatedAtMs: number;
}
export interface Owner {
  status: 'pending' | 'succeeded' | 'excluded' | 'partial' | 'unknown';
  receipt: {
    [k: string]: unknown;
  };
}
