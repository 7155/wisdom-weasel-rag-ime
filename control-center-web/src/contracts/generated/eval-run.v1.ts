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
  suiteBinding?: {
    suiteId: string;
    suiteRevision: string;
  };
  metrics: {
    [k: string]: number;
  };
  status: 'queued' | 'running' | 'completed' | 'failed';
  createdAtMs: number;
  updatedAtMs: number;
}
