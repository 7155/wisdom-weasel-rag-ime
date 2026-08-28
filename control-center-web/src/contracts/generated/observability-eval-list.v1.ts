/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/observability-eval-list.v1.json
 */

export interface ObservabilityEvalListV1 {
  schemaVersion: 'rag-ime.observability-eval-list.v1';
  traceId: string;
  total: number;
  truncated: boolean;
  /**
   * @maxItems 500
   */
  items: EvalSummary[];
}
export interface EvalSummary {
  evalRunId: string;
  mode: 'ground_truth' | 'ai_judge';
  metricAuthority: 'ground_truth' | 'ai_judge_estimate';
  truthStatus: 'none' | 'human' | 'frozen';
  datasetId: string;
  labelRevision: string;
  evaluatorDisplayName: string;
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
