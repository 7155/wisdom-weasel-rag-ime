/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-diagnostic-report.v1.json
 */

export interface TraceDiagnosticReportV1 {
  schemaVersion: 'rag-ime.trace-diagnostic-report.v1';
  reportId: string;
  revision: number;
  status: 'generating' | 'completed' | 'failed';
  title: string;
  diagnosticSessionId: string;
  /**
   * @minItems 1
   * @maxItems 12
   */
  targets:
    | [Target]
    | [Target, Target]
    | [Target, Target, Target]
    | [Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target, Target, Target, Target]
    | [
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
      ];
  /**
   * @maxItems 32
   */
  traceIds: string[];
  inspectionSha256: string;
  inspection: {
    [k: string]: unknown;
  };
  result: {
    [k: string]: unknown;
  } | null;
  failureReason: string;
  createdAtMs: number;
  updatedAtMs: number;
}
export interface Target {
  targetKey: string;
  kind: 'session' | 'room' | 'run';
  id: string;
  title: string;
  /**
   * @maxItems 32
   */
  traceIds: string[];
  sourceAvailable: boolean;
}
