/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/observability-evidence-eval-request.v1.json
 */

export interface ObservabilityEvidenceEvalRequestV1 {
  schemaVersion: 'rag-ime.observability-evidence-eval-request.v1';
  traceId: string;
  /**
   * @maxItems 2048
   */
  requiredEvidenceIds: string[];
  datasetId: string;
  labelRevision: string;
  truthKind: 'human';
}
