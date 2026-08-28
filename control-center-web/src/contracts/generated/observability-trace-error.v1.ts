/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/observability-trace-error.v1.json
 */

export interface ObservabilityTraceErrorV1 {
  schemaVersion: 'rag-ime.observability-trace-error.v1';
  ok: false;
  errorCode: 'trace_not_found' | 'invalid_trace_id' | 'trace_invalid';
  error: string;
  traceId: string;
}
