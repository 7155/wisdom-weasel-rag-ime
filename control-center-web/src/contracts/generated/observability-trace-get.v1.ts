/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/observability-trace-get.v1.json
 */

export interface ObservabilityTraceGetV1 {
  schemaVersion: 'rag-ime.observability-trace-get.v1';
  traceId: string;
  trace: {
    schemaVersion: 'rag-ime.trace-envelope.v1';
    traceId: string;
    sourceKind: string;
    status: 'building' | 'completed' | 'failed' | 'cancelled';
    binding: {
      sessionId?: string;
      turnId?: string;
      roomId?: string;
      runId?: string;
      sourceLoopId?: string;
      workItemId?: string;
      caseId?: string;
    };
    parentTraceId?: string | null;
    /**
     * @maxItems 64
     */
    links?: TraceLink[];
    input: {
      fingerprint: string;
      contentPolicy: 'hash_only' | 'redacted' | 'owner_local';
      normalization: string;
    };
    /**
     * @maxItems 256
     */
    spans: Span[];
    /**
     * @maxItems 2048
     */
    evidence: Evidence[];
    /**
     * @maxItems 256
     */
    artifacts: Artifact[];
    createdAtMs: number;
    updatedAtMs: number;
  };
  truncated: boolean;
  projectionSource: 'observation_journal' | 'source_adapter' | 'trace_store';
  observationWindow: {
    firstSequence: number;
    lastSequence: number;
    resumeToken: string;
    nextBeforeSequence: number | null;
  };
}
export interface TraceLink {
  traceId: string;
  relation: 'retry' | 'related';
  targetKind: 'trace';
}
export interface Span {
  spanId: string;
  name: string;
  parentSpanId: string | null;
  status: 'queued' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled' | 'info';
  startedAtMs: number;
  endedAtMs: number | null;
  durationMs: number | null;
  recorded: boolean;
  unavailableReason: string;
  metrics: {
    [k: string]: unknown;
  };
  attributes: {
    [k: string]: unknown;
  };
}
export interface Evidence {
  evidenceId: string;
  sourceKind: string;
  sourceRef: string;
  sourceLane: string;
  evidenceStage: string;
  disposition: 'included' | 'omitted' | 'filtered' | 'redacted';
  scores: {
    [k: string]: number;
  };
  rankBefore: number | null;
  rankAfter: number | null;
  omissionReason: string;
}
export interface Artifact {
  artifactId: string;
  kind: string;
  mediaType: string;
  sha256: string;
  byteSize: number;
  recordCount: number;
}
