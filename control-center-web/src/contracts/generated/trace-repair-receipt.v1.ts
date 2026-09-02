/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-repair-receipt.v1.json
 */

export interface TraceRepairReceiptV1 {
  schemaVersion: 'rag-ime.trace-repair-receipt.v1';
  repairReceiptId: string;
  sourceScope: string;
  sourceTraceId: string;
  failureRef: string;
  changeReceiptId: string;
  testEvidenceId: string;
  testStatus: 'passed';
  sandboxStatus: 'passed' | 'not_required';
  sandboxedTestCount: number;
  repairTraceId: string;
  repairSessionId: string;
  createdAtMs: number;
}
