/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-verification-receipt.v1.json
 */

export interface TraceVerificationReceiptV1 {
  schemaVersion: 'rag-ime.trace-verification-receipt.v1';
  verificationReceiptId: string;
  replayCaseId: string;
  repairReceiptId: string;
  sourceTraceId: string;
  repairTraceId: string;
  baselineEvalRunId: string;
  repairEvalRunId: string;
  baselineSandboxRunId: string;
  repairSandboxRunId: string;
  /**
   * @minItems 1
   * @maxItems 256
   */
  regressionEvalRunIds: [string, ...string[]];
  replayCohort: ReplayCohort;
  successCriterion: {
    metric: string;
    threshold: number;
    direction: 'at_least';
  };
  repairPassed: boolean;
  regression: {
    count: number;
    passed: boolean;
    failedEvalRunIds: string[];
  };
  comparison: {
    status: 'available';
    metric: string;
    before: number;
    after: number;
    absoluteDelta: number;
    relativeDelta: number | null;
  };
  efficiency: {
    latencyMs: NullableDelta;
    totalTokens: NullableDelta;
  };
  decision: 'kept' | 'rejected';
  rollbackTarget: string;
  createdAtMs: number;
}
export interface ReplayCohort {
  suiteId: string;
  suiteRevision: string;
  caseId: string;
  inputFingerprint: string;
  environmentFingerprint: string;
  configFingerprint: string;
  modelProfileFingerprint: string;
  toolProfileFingerprint: string;
  skillProfileFingerprint: string;
}
export interface NullableDelta {
  before: number | null;
  after: number | null;
  delta: number | null;
}
