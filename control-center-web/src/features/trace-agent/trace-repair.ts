import type { EvalRunV1 } from '@/contracts/generated/eval-run.v1';
import type { TraceRepairReceiptV1 } from '@/contracts/generated/trace-repair-receipt.v1';
import { parseContract } from '@/contracts/validators';

/** The public identity of the failure a repair is allowed to address. */
export type TraceRepairIdentity = {
  sourceScope: string;
  sourceTraceId: string;
  failureRef: string;
};

export type TraceRepairCanonicalEvidence = {
  schemaVersion: 'rag-ime.trace-repair-canonical-evidence.v1';
  evidenceKind: 'change' | 'test';
  repairSessionId: string;
  repairTraceId: string;
  eventCount: number;
  completedCount: number;
  toolCount: number;
  toolNames: string[];
  signalIds: string[];
  changeCount?: number;
  testCount?: number;
  passedCount?: number;
  failedCount?: number;
  status?: 'passed' | 'failed' | 'blocked';
};

export type TraceRepairEvidenceWrite = {
  schemaVersion: 'rag-ime.trace-repair-evidence-write.v1';
  ok: true;
  evidence: {
    schemaVersion: 'rag-ime.trace-repair-evidence.v1';
    evidenceId: string;
    evidenceKind: 'change' | 'test';
    sourceScope: string;
    sourceTraceId: string;
    testStatus: '' | 'passed' | 'failed' | 'blocked';
    evidence: TraceRepairCanonicalEvidence;
    createdAtMs: number;
  };
};

export type TraceRepairReceiptCreate = {
  schemaVersion: 'rag-ime.trace-repair-receipt-create.v1';
  ok: true;
  receipt: TraceRepairReceiptV1;
};

export type TraceRepairReceiptGet = {
  schemaVersion: 'rag-ime.trace-repair-receipt-get.v1';
  ok: true;
  receipt: TraceRepairReceiptV1;
};

export type TraceRepairRecheck = {
  schemaVersion: 'rag-ime.trace-repair-recheck.v1';
  ok: true;
  receipt: TraceRepairReceiptV1;
  evalRun: EvalRunV1;
  idempotent?: boolean;
};

export class TraceRepairValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TraceRepairValidationError';
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function assertIdentity(value: TraceRepairReceiptV1, expected: TraceRepairIdentity): void {
  for (const key of ['sourceScope', 'sourceTraceId', 'failureRef'] as const) {
    if (value[key] !== expected[key]) {
      throw new TraceRepairValidationError(`权威回执 ${key} 与原始失败范围不一致。`);
    }
  }
}

export function parseTraceRepairEvidenceWrite(
  value: unknown,
  kind: 'change' | 'test',
  expected: { repairSessionId: string; repairTraceId: string },
): TraceRepairEvidenceWrite['evidence'] {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-repair-evidence-write.v1' || payload.ok !== true) {
    throw new TraceRepairValidationError(`服务端未确认 ${kind} evidence 写入。`);
  }
  const evidence = record(payload.evidence);
  if (evidence.evidenceKind !== kind || !text(evidence.evidenceId)) {
    throw new TraceRepairValidationError(`服务端返回的 ${kind} evidence 无有效服务端 ID。`);
  }
  if (evidence.sourceScope !== 'trace-repair' || evidence.sourceTraceId !== expected.repairTraceId) {
    throw new TraceRepairValidationError(`服务端返回的 ${kind} evidence 绑定不一致。`);
  }
  if (kind === 'change' && evidence.testStatus !== '') {
    throw new TraceRepairValidationError('change evidence 不应携带测试通过状态。');
  }
  if (kind === 'test' && !['passed', 'failed', 'blocked'].includes(text(evidence.testStatus))) {
    throw new TraceRepairValidationError('test evidence 未返回结构化测试状态。');
  }
  const canonical = record(evidence.evidence);
  if (
    canonical.schemaVersion !== 'rag-ime.trace-repair-canonical-evidence.v1'
    || canonical.evidenceKind !== kind
    || canonical.repairSessionId !== expected.repairSessionId
    || canonical.repairTraceId !== expected.repairTraceId
  ) {
    throw new TraceRepairValidationError(`${kind} evidence 没有绑定本次修复 Session/Trace。`);
  }
  return evidence as TraceRepairEvidenceWrite['evidence'];
}

export function parseTraceRepairReceiptCreate(value: unknown, expected: TraceRepairIdentity, evidence: { changeReceiptId: string; testEvidenceId: string; repairTraceId: string; repairSessionId: string }): TraceRepairReceiptV1 {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-repair-receipt-create.v1' || payload.ok !== true) {
    throw new TraceRepairValidationError('服务端未确认权威修复回执创建。');
  }
  let receipt: TraceRepairReceiptV1;
  try {
    receipt = parseContract('trace-repair-receipt.v1', payload.receipt);
  } catch {
    throw new TraceRepairValidationError('服务端返回的权威修复回执无效。');
  }
  assertIdentity(receipt, expected);
  if (!receipt.repairReceiptId || receipt.changeReceiptId !== evidence.changeReceiptId || receipt.testEvidenceId !== evidence.testEvidenceId || receipt.repairTraceId !== evidence.repairTraceId || receipt.repairSessionId !== evidence.repairSessionId) {
    throw new TraceRepairValidationError('权威修复回执未绑定本次服务端 evidence。');
  }
  if (receipt.testStatus !== 'passed') throw new TraceRepairValidationError('权威修复回执测试未通过。');
  return receipt;
}

export function parseTraceRepairReceiptGet(value: unknown, expected: TraceRepairIdentity, receiptId: string): TraceRepairReceiptV1 {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-repair-receipt-get.v1' || payload.ok !== true) {
    throw new TraceRepairValidationError('服务端未确认读取权威修复回执。');
  }
  let receipt: TraceRepairReceiptV1;
  try {
    receipt = parseContract('trace-repair-receipt.v1', payload.receipt);
  } catch {
    throw new TraceRepairValidationError('读取到的权威修复回执无效。');
  }
  assertIdentity(receipt, expected);
  if (receipt.repairReceiptId !== receiptId) throw new TraceRepairValidationError('读取到的权威回执 ID 不一致。');
  return receipt;
}

export function parseTraceRepairRecheck(value: unknown, expected: TraceRepairIdentity, receipt: TraceRepairReceiptV1): TraceRepairRecheck {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-repair-recheck.v1' || payload.ok !== true) {
    throw new TraceRepairValidationError('服务端未确认 Trace 修复复检。');
  }
  const returnedReceipt = parseTraceRepairReceiptGet({ schemaVersion: 'rag-ime.trace-repair-receipt-get.v1', ok: true, receipt: payload.receipt }, expected, receipt.repairReceiptId);
  if (JSON.stringify(returnedReceipt) !== JSON.stringify(receipt)) throw new TraceRepairValidationError('复检返回的权威回执发生漂移。');
  let evalRun: EvalRunV1;
  try {
    evalRun = parseContract('eval-run.v1', payload.evalRun);
  } catch {
    throw new TraceRepairValidationError('复检未返回有效 EvalRun。');
  }
  if (evalRun.status !== 'completed' || evalRun.mode !== 'ai_judge' || evalRun.metricAuthority !== 'ai_judge_estimate') {
    throw new TraceRepairValidationError('复检 EvalRun 未完成或权威类型不正确。');
  }
  const provenance: Array<[keyof TraceRepairReceiptV1, keyof EvalRunV1]> = [
    ['sourceTraceId', 'sourceTraceId'],
    ['repairTraceId', 'repairTraceId'],
    ['sourceScope', 'sourceScope'],
    ['failureRef', 'failureRef'],
    ['repairReceiptId', 'repairReceiptId'],
    ['changeReceiptId', 'changeReceiptId'],
    ['testEvidenceId', 'testEvidenceId'],
    ['testStatus', 'testStatus'],
  ];
  for (const [receiptKey, evalKey] of provenance) {
    if (evalRun[evalKey] !== receipt[receiptKey]) throw new TraceRepairValidationError('EvalRun provenance 与权威修复回执不一致。');
  }
  return { schemaVersion: 'rag-ime.trace-repair-recheck.v1', ok: true, receipt: returnedReceipt, evalRun, ...(typeof payload.idempotent === 'boolean' ? { idempotent: payload.idempotent } : {}) };
}
