/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-replay-case.v1.json
 */

export interface TraceReplayCaseV1 {
  schemaVersion: 'rag-ime.trace-replay-case.v1';
  replayCaseId: string;
  sourceScope: string;
  failureRef: string;
  sourceTraceId: string;
  baselineEvalRunId: string;
  baselineSandboxRunId: string;
  replayCohort: ReplayCohort;
  successCriterion: {
    metric: string;
    threshold: number;
    direction: 'at_least';
  };
  baselineMetricValue: number;
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
