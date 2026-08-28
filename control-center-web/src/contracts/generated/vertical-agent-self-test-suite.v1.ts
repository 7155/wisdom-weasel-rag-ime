/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/vertical-agent-self-test-suite.v1.json
 */

export interface VerticalAgentSelfTestSuiteV1 {
  schemaVersion: 'rag-ime.vertical-agent-self-test-suite.v1';
  status: 'completed' | 'failed';
  totalCount: number;
  passedCount: number;
  failedCount: number;
  results: Result[];
  failures: Failure[];
}
export interface Result {
  appId: string;
  fixtureId: string;
  traceId: string;
  evalRunId: string;
  sandboxRunId: string;
  metrics: {
    [k: string]: number;
  };
  providerCalls: 0;
  productionWriteBlocked: true;
  status: 'passed';
}
export interface Failure {
  appId: string;
  status: 'failed';
  errorCode: string;
  errorFingerprint: string;
}
