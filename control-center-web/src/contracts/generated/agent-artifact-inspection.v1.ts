/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-artifact-inspection.v1.json
 */

export interface AgentArtifactInspectionV1 {
  schemaVersion: 'rag-ime.agent-artifact-inspection.v1';
  artifact: {
    [k: string]: unknown;
  };
  /**
   * @maxItems 500
   */
  records: {
    [k: string]: unknown;
  }[];
  totalRecords: number;
  returnedRecords: number;
  truncated: boolean;
  limits: {
    requestedRecords: number;
    maxRecords: 500;
    maxOutputBytes: 262144;
  };
}
