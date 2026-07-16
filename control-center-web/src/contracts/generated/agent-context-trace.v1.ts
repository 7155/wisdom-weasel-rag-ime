/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-context-trace.v1.json
 */

export interface AgentContextTraceV1 {
  schemaVersion: 'rag-ime.agent-context-trace.v1';
  traceId: string;
  sessionId: string;
  turnId: string;
  sourceKind: string;
  status: 'building' | 'accepted' | 'failed';
  finalFingerprint: string;
  /**
   * @maxItems 64
   */
  nodes: Node[];
  /**
   * @maxItems 128
   */
  edges: Edge[];
  createdAtMs: number;
  updatedAtMs: number;
}
export interface Node {
  nodeId: string;
  ordinal: number;
  stage: string;
  label: string;
  sourceKind: string;
  disposition: 'included' | 'omitted' | 'redacted' | 'failed';
  summary: string;
  charCount: number;
  tokenEstimate: number;
  durationMs: number;
  fingerprint: string;
  reason: string;
  metadata: {
    [k: string]: unknown;
  };
  createdAtMs: number;
}
export interface Edge {
  source: string;
  target: string;
}
