/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-approval.v1.json
 */

export interface AgentApprovalV1 {
  schemaVersion: 'rag-ime.agent-approval.v1';
  approvalId: string;
  sessionId: string;
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
  decidedAtMs?: number | null;
  receipt?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
