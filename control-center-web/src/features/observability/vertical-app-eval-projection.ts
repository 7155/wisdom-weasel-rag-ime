import type { SandboxRunV1 } from '@/contracts/generated/sandbox-run.v1';
import type { ObservabilityEvalListV1 } from '@/contracts/generated/observability-eval-list.v1';

type EvalSummary = ObservabilityEvalListV1['items'][number];
export type VerticalAppEvalState = 'waiting' | 'active' | 'passed' | 'failed';

export interface VerticalAppEvalItemProjection {
  evalRunId: string;
  status: EvalSummary['status'];
  authority: EvalSummary['metricAuthority'];
  truthStatus: EvalSummary['truthStatus'];
  suiteLabel: string;
  evaluatorDisplayName: string;
  metrics: Array<[string, number]>;
}

export interface VerticalAppEvalProjection {
  appId: string;
  sandboxRunId: string;
  traceIds: string[];
  candidate: {
    state: VerticalAppEvalState;
    label: string;
    configFingerprint: string;
    cohortLabel: string;
  };
  sandbox: {
    state: VerticalAppEvalState;
    label: string;
  };
  evals: {
    state: VerticalAppEvalState;
    expectedCount: number;
    receivedCount: number;
    missingEvalRunIds: string[];
    suiteAligned: boolean;
    suiteAlignmentReason: string;
    items: VerticalAppEvalItemProjection[];
  };
  decision: {
    state: 'waiting';
    label: string;
    detail: string;
  };
  failureBranch: boolean;
}

export function projectVerticalAppEval(
  run: SandboxRunV1,
  evalItems: EvalSummary[],
): VerticalAppEvalProjection {
  const cohort = run.replayCohort;
  const expectedEvalRunIds = [...new Set(run.evalRunIds)];
  const evalById = new Map(evalItems.map((item) => [item.evalRunId, item]));
  const matchedItems = expectedEvalRunIds
    .map((evalRunId) => evalById.get(evalRunId))
    .filter((item): item is EvalSummary => Boolean(item));
  const missingEvalRunIds = expectedEvalRunIds.filter((evalRunId) => !evalById.has(evalRunId));
  const suiteAlignment = evalSuiteAlignment(cohort, matchedItems);
  const sandboxState = sandboxProjectionState(run.status);
  const hasObservedFailure = sandboxState === 'failed'
    || matchedItems.some((item) => item.status === 'failed');
  const hasActiveEval = matchedItems.some((item) => item.status === 'queued' || item.status === 'running');
  const allExpectedEvalsCompleted = expectedEvalRunIds.length > 0
    && missingEvalRunIds.length === 0
    && matchedItems.every((item) => item.status === 'completed');
  const evalState: VerticalAppEvalState = hasObservedFailure
    ? 'failed'
    : sandboxState === 'active' || hasActiveEval
      ? 'active'
      : allExpectedEvalsCompleted && suiteAlignment.aligned
        ? 'passed'
        : 'waiting';

  return {
    appId: run.appId,
    sandboxRunId: run.sandboxRunId,
    traceIds: [...run.traceIds],
    candidate: cohort ? {
      state: 'passed',
      label: '候选配置已冻结',
      configFingerprint: cohort.configFingerprint,
      cohortLabel: `${cohort.suiteId} · ${cohort.suiteRevision} · ${cohort.caseId}`,
    } : {
      state: 'waiting',
      label: '等待候选配置冻结回执',
      configFingerprint: '',
      cohortLabel: '',
    },
    sandbox: {
      state: sandboxState,
      label: sandboxLabel(run.status),
    },
    evals: {
      state: evalState,
      expectedCount: expectedEvalRunIds.length,
      receivedCount: matchedItems.length,
      missingEvalRunIds,
      suiteAligned: suiteAlignment.aligned,
      suiteAlignmentReason: suiteAlignment.reason,
      items: matchedItems.map((item) => ({
        evalRunId: item.evalRunId,
        status: item.status,
        authority: item.metricAuthority,
        truthStatus: item.truthStatus,
        suiteLabel: item.suiteBinding
          ? `${item.suiteBinding.suiteId} · ${item.suiteBinding.suiteRevision}`
          : '',
        evaluatorDisplayName: item.evaluatorDisplayName,
        metrics: item.status === 'completed' ? Object.entries(item.metrics) : [],
      })),
    },
    decision: {
      state: 'waiting',
      label: '等待 verification / promotion 回执',
      detail: hasObservedFailure
        ? '候选出现失败；Keep / Reject 仍须等待评价或晋升回执。'
        : allExpectedEvalsCompleted && suiteAlignment.aligned
        ? '多个 Eval 已完成，但还不能 Keep 或改写当前 App 配置。'
        : '候选仍在试验链路中；收到可比 Eval 与晋升回执前不会 Keep。',
    },
    failureBranch: hasObservedFailure,
  };
}

function sandboxProjectionState(status: SandboxRunV1['status']): VerticalAppEvalState {
  if (status === 'completed') return 'passed';
  if (status === 'failed' || status === 'cancelled') return 'failed';
  return 'active';
}

function sandboxLabel(status: SandboxRunV1['status']): string {
  return ({
    queued: 'Host 受管沙盒排队中',
    running: 'Host 受管沙盒测试中',
    completed: 'Host 受管沙盒测试已完成',
    failed: 'Host 受管沙盒测试失败',
    cancelled: 'Host 受管沙盒测试已取消',
  })[status];
}

function evalSuiteAlignment(
  cohort: SandboxRunV1['replayCohort'],
  items: EvalSummary[],
): { aligned: boolean; reason: string } {
  if (!cohort) return { aligned: false, reason: '缺少冻结 cohort，无法核对 suite；完整可比性等待 verification receipt。' };
  if (!items.length) return { aligned: false, reason: '等待 Eval 回执后核对 suite；完整可比性仍由 verification receipt 证明。' };
  if (items.some((item) => !item.suiteBinding)) {
    return { aligned: false, reason: 'Eval 缺少 suite 绑定；完整可比性等待 verification receipt。' };
  }
  if (items.some((item) => (
    item.suiteBinding?.suiteId !== cohort.suiteId
    || item.suiteBinding.suiteRevision !== cohort.suiteRevision
  ))) {
    return { aligned: false, reason: 'Eval suite 与冻结 cohort 不一致，不能直接比较。' };
  }
  return { aligned: true, reason: 'suite 一致；完整 cohort comparability 仍等待 verification receipt。' };
}
