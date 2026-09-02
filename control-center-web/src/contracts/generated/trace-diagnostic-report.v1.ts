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
  repairLifecycle?: RepairLifecycle;
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
export interface RepairLifecycle {
  authorization: RepairAuthorization;
  verification: RepairVerification;
}
export interface RepairAuthorization {
  state: 'authorized' | 'declined' | 'blocked' | 'expired';
  authorizationKind: 'repair_handoff';
  writeAuthority:
    'per_action_required' | 'model_arbitrated_full_trust' | 'auto_approved_full_trust';
  authorizationId: string;
  findingId: string;
  sourceScope: string;
  sourceTraceId: string;
  failureRef: string;
  repairSessionId: string;
  authorizedAtMs: number;
}
export interface RepairVerification {
  state: 'pending' | 'verified' | 'failed';
  repairReceiptId: string;
  repairTraceId: string;
  evalRunId: string;
  testStatus: '' | 'passed' | 'failed' | 'blocked';
  sandboxStatus: '' | 'passed' | 'not_required' | 'blocked';
  sandboxedTestCount: number;
  verifiedAtMs: number;
  comparison: Comparison;
}
export interface Comparison {
  status: 'pending' | 'incomparable' | 'failed' | 'unknown';
  reason: string;
  sourceStatus: string;
  repairStatus: string;
  sourceFingerprint: string;
  repairFingerprint: string;
  beforeMetrics: {
    [k: string]: number;
  };
  afterMetrics: {
    [k: string]: number;
  };
  deltas: {
    [k: string]: number;
  };
}
