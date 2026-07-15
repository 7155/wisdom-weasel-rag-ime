/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-runtime-binding.v1.json
 */

export interface AgentRuntimeBindingV1 {
  schemaVersion: 'rag-ime.agent-runtime-binding.v1';
  sessionId?: string;
  driverId: string;
  runtimeKind: string;
  externalSessionId?: string;
  transcriptRef?: string;
  branchAnchor?: string;
  generation: number;
  state: 'prepared' | 'active' | 'stale';
  metadata?: {
    [k: string]: unknown;
  };
  createdAtMs: number;
  updatedAtMs: number;
  [k: string]: unknown;
}
