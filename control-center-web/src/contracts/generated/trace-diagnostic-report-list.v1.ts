/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-diagnostic-report-list.v1.json
 */

export interface TraceDiagnosticReportListV1 {
  schemaVersion: 'rag-ime.trace-diagnostic-report-list.v1';
  total: number;
  truncated: boolean;
  /**
   * @maxItems 100
   */
  items: Item[];
}
export interface Item {
  reportId: string;
  revision: number;
  status: 'generating' | 'completed' | 'failed';
  title: string;
  diagnosticSessionId: string;
  /**
   * @minItems 1
   * @maxItems 12
   */
  targetKeys:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
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
  repairState?: 'not_recorded' | 'authorized' | 'verified' | 'failed';
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
