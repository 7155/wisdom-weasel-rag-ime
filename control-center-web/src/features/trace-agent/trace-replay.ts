import type { TraceReplayCaseV1 } from '@/contracts/generated/trace-replay-case.v1';
import type { TraceVerificationReceiptV1 } from '@/contracts/generated/trace-verification-receipt.v1';
import { parseContract } from '@/contracts/validators';

export class TraceReplayValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TraceReplayValidationError';
  }
}

type ReplayCaseIdentity = {
  sourceScope: string;
  failureRef: string;
  sourceTraceId: string;
  baselineEvalRunId: string;
  baselineSandboxRunId: string;
  successMetric: string;
  successThreshold: number;
  rollbackTarget: string;
};

type VerificationIdentity = {
  replayCase: TraceReplayCaseV1;
  repairReceiptId: string;
  repairTraceId: string;
  repairEvalRunId: string;
  repairSandboxRunId: string;
  regressionEvalRunIds: string[];
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function parseReplayCase(value: unknown): TraceReplayCaseV1 {
  try {
    return parseContract('trace-replay-case.v1', value);
  } catch {
    throw new TraceReplayValidationError('服务端返回的 Replay Case 无效。');
  }
}

function parseVerificationReceipt(value: unknown): TraceVerificationReceiptV1 {
  try {
    return parseContract('trace-verification-receipt.v1', value);
  } catch {
    throw new TraceReplayValidationError('服务端返回的 Verification Receipt 无效。');
  }
}

function assertReplayCaseIdentity(
  replayCase: TraceReplayCaseV1,
  expected: ReplayCaseIdentity,
): void {
  if (
    replayCase.sourceScope !== expected.sourceScope
    || replayCase.failureRef !== expected.failureRef
    || replayCase.sourceTraceId !== expected.sourceTraceId
    || replayCase.baselineEvalRunId !== expected.baselineEvalRunId
    || replayCase.baselineSandboxRunId !== expected.baselineSandboxRunId
    || replayCase.successCriterion.metric !== expected.successMetric
    || replayCase.successCriterion.threshold !== expected.successThreshold
    || replayCase.rollbackTarget !== expected.rollbackTarget
  ) {
    throw new TraceReplayValidationError('Replay Case 与本次冻结的原始失败身份不一致。');
  }
}

export function parseTraceReplayCaseCreate(
  value: unknown,
  expected: ReplayCaseIdentity,
): TraceReplayCaseV1 {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-replay-case-create.v1' || payload.ok !== true) {
    throw new TraceReplayValidationError('服务端未确认 Replay Case 创建。');
  }
  const replayCase = parseReplayCase(payload.replayCase);
  if (!replayCase.replayCaseId) {
    throw new TraceReplayValidationError('Replay Case 缺少服务端 ID。');
  }
  assertReplayCaseIdentity(replayCase, expected);
  return replayCase;
}

export function parseTraceReplayCaseGet(
  value: unknown,
  expected: TraceReplayCaseV1,
): TraceReplayCaseV1 {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-replay-case-get.v1' || payload.ok !== true) {
    throw new TraceReplayValidationError('服务端未确认读取 Replay Case。');
  }
  const replayCase = parseReplayCase(payload.replayCase);
  if (
    replayCase.replayCaseId !== expected.replayCaseId
    || JSON.stringify(replayCase) !== JSON.stringify(expected)
  ) {
    throw new TraceReplayValidationError('重新读取的 Replay Case 已漂移，候选修复未启动。');
  }
  return replayCase;
}

function assertVerificationIdentity(
  receipt: TraceVerificationReceiptV1,
  expected: VerificationIdentity,
): void {
  const replayCase = expected.replayCase;
  if (
    receipt.replayCaseId !== replayCase.replayCaseId
    || receipt.repairReceiptId !== expected.repairReceiptId
    || receipt.sourceTraceId !== replayCase.sourceTraceId
    || receipt.repairTraceId !== expected.repairTraceId
    || receipt.baselineEvalRunId !== replayCase.baselineEvalRunId
    || receipt.repairEvalRunId !== expected.repairEvalRunId
    || receipt.baselineSandboxRunId !== replayCase.baselineSandboxRunId
    || receipt.repairSandboxRunId !== expected.repairSandboxRunId
    || receipt.rollbackTarget !== replayCase.rollbackTarget
    || JSON.stringify(receipt.replayCohort) !== JSON.stringify(replayCase.replayCohort)
    || JSON.stringify(receipt.successCriterion) !== JSON.stringify(replayCase.successCriterion)
    || JSON.stringify(receipt.regressionEvalRunIds) !== JSON.stringify(expected.regressionEvalRunIds)
  ) {
    throw new TraceReplayValidationError('Verification Receipt 未绑定本次 Replay Case 与候选修复。');
  }
}

export function parseTraceVerificationCreate(
  value: unknown,
  expected: VerificationIdentity,
): TraceVerificationReceiptV1 {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-verification-receipt-create.v1' || payload.ok !== true) {
    throw new TraceReplayValidationError('服务端未确认同 Case 验证。');
  }
  const receipt = parseVerificationReceipt(payload.verificationReceipt);
  if (!receipt.verificationReceiptId) {
    throw new TraceReplayValidationError('Verification Receipt 缺少服务端 ID。');
  }
  assertVerificationIdentity(receipt, expected);
  return receipt;
}

export function parseTraceVerificationGet(
  value: unknown,
  expected: TraceVerificationReceiptV1,
): TraceVerificationReceiptV1 {
  const payload = record(value);
  if (payload.schemaVersion !== 'rag-ime.trace-verification-receipt-get.v1' || payload.ok !== true) {
    throw new TraceReplayValidationError('服务端未确认读取 Verification Receipt。');
  }
  const receipt = parseVerificationReceipt(payload.verificationReceipt);
  if (
    receipt.verificationReceiptId !== expected.verificationReceiptId
    || JSON.stringify(receipt) !== JSON.stringify(expected)
  ) {
    throw new TraceReplayValidationError('重新读取的 Verification Receipt 已漂移，不能绑定决策。');
  }
  return receipt;
}
