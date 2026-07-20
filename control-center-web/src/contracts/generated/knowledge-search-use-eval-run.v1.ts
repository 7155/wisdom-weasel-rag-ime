/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/knowledge-search-use-eval-run.v1.json
 */

export interface KnowledgeSearchUseEvalRunV1 {
  schemaVersion: 'wisdom-weasel.knowledge-search-use-eval-run.v1';
  evalRunId: string;
  datasetId: string;
  datasetContentHash: string;
  roomBindingId: string;
  traceCount: number;
  metrics: {
    [k: string]: unknown;
  };
  strataMetrics: {
    [k: string]: unknown;
  };
  status: 'passed' | 'failed';
  failureReasons: unknown[];
  reportOnly: true;
  evaluatorId: string;
  contentHash: string;
  evaluatorSignature: string;
  createdAtMs: number;
}
