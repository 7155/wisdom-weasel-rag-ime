/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/eval-run.v1.json
 */

export interface EvalRunV1 {
  schemaVersion: 'rag-ime.eval-run.v1';
  evalRunId: string;
  /**
   * @minItems 1
   * @maxItems 2048
   */
  traceIds: [string, ...string[]];
  mode: 'ground_truth' | 'ai_judge';
  metricAuthority: 'ground_truth' | 'ai_judge_estimate';
  truth: {
    status: 'none' | 'human' | 'frozen';
    datasetId: string;
    labelRevision: string;
  };
  evaluator: {
    provider: string;
    model: string;
    thinking: string;
    displayName: string;
  };
  requestedEvaluator?: {
    provider: string;
    model: string;
    thinking: string;
    displayName: string;
  };
  suiteBinding?: {
    suiteId: string;
    suiteRevision: string;
  };
  metrics: {
    [k: string]: number;
  };
  status: 'queued' | 'running' | 'completed' | 'failed';
  promptVersion?: string;
  rubricVersion?: string;
  inputTraceFingerprint?: string;
  startedAtMs?: number;
  completedAtMs?: number;
  elapsedMs?: number;
  latencyMs?: number;
  usage?: {
    input?: number;
    output?: number;
    cacheRead?: number;
    cacheWrite?: number;
    totalTokens?: number;
  };
  cost?: {
    input?: number;
    output?: number;
    cacheRead?: number;
    cacheWrite?: number;
    total?: number;
  };
  fallbackUsed?: boolean;
  failureCode?:
    | 'ai_judge_runtime_unavailable'
    | 'ai_judge_request_failed'
    | 'ai_judge_invalid_response'
    | 'ai_judge_timeout';
  sourceTraceId?: string;
  repairTraceId?: string;
  sourceScope?: string;
  failureRef?: string;
  repairReceiptId?: string;
  changeReceiptId?: string;
  testEvidenceId?: string;
  testStatus?: 'passed';
  createdAtMs: number;
  updatedAtMs: number;
}
