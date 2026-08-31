/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/observation-event.v1.json
 */

export interface ObservationEventV1 {
  schemaVersion: 'rag-ime.observation-event.v1';
  eventType: 'observation' | 'snapshot_required';
  eventId: string;
  sequence: number;
  resumeToken: string;
  traceId: string;
  spanId: string;
  parentSpanId: string;
  sessionId: string;
  roomId: string;
  turnId: string;
  runId: string;
  category:
    | 'context'
    | 'retrieval'
    | 'memory'
    | 'tool'
    | 'agent'
    | 'room'
    | 'intercom'
    | 'approval'
    | 'runtime'
    | 'system';
  phase: string;
  name: string;
  status:
    'queued' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled' | 'expired' | 'info';
  summary: string;
  createdAtMs: number;
  startedAtMs: number;
  endedAtMs: number | null;
  durationMs: number | null;
  privacyClass: 'metadata' | 'redacted' | 'owner_local';
  metrics: {
    [k: string]: unknown;
  };
  attributes: {
    [k: string]: unknown;
  };
  refs: {
    kind: string;
    id: string;
    label: string;
  }[];
}
