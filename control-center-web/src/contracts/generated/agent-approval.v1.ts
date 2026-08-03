/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-approval.v1.json
 */

export interface AgentApprovalV1 {
  schemaVersion: 'rag-ime.agent-approval.v1';
  approvalId: string;
  sessionId: string;
  toolCallId?: string;
  toolId: string;
  operation: string;
  payloadSha256: string;
  preview: {
    [k: string]: unknown;
  };
  riskLevel: 'R1' | 'R2' | 'R3';
  state:
    | 'pending'
    | 'approved'
    | 'external_pending'
    | 'rejected'
    | 'expired'
    | 'stale'
    | 'applied'
    | 'failed';
  requestedAtMs: number;
  expiresAtMs: number;
  decidedBy: string;
  decidedAtMs?: number | null;
  receipt?: {
    [k: string]: unknown;
  } | null;
  causalMetadata: {
    todoId: string;
    todoRevision: number;
    goalId: string;
    goalRevision: number;
    turnId: string;
    roomBound: boolean;
  };
  [k: string]: unknown;
}
