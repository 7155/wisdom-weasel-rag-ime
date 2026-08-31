import { describe, expect, it } from 'vitest';
import type { SandboxRunV1 } from '@/contracts/generated/sandbox-run.v1';
import type { ObservabilityEvalListV1 } from '@/contracts/generated/observability-eval-list.v1';
import { projectVerticalAppEval } from './vertical-app-eval-projection';

type EvalSummary = ObservabilityEvalListV1['items'][number];

describe('projectVerticalAppEval', () => {
  it('keeps a completed multi-Eval candidate waiting when verification and promotion receipts are absent', () => {
    const projection = projectVerticalAppEval(
      sandboxRun(),
      [
        evalSummary('eval:ground-truth', {
          metrics: { evidenceRecall: 0.92 },
        }),
        evalSummary('eval:judge', {
          metricAuthority: 'ai_judge_estimate',
          mode: 'ai_judge',
          metrics: { qualityEstimate: 0.81 },
          truthStatus: 'none',
        }),
      ],
    );

    expect(projection.candidate.state).toBe('passed');
    expect(projection.sandbox.state).toBe('passed');
    expect(projection.evals).toMatchObject({
      state: 'passed',
      expectedCount: 2,
      receivedCount: 2,
      suiteAligned: true,
      missingEvalRunIds: [],
    });
    expect(projection.evals.items.map((item) => item.metrics)).toEqual([
      [['evidenceRecall', 0.92]],
      [['qualityEstimate', 0.81]],
    ]);
    expect(projection.evals.suiteAlignmentReason).toBe('suite 一致；完整 cohort comparability 仍等待 verification receipt。');
    expect(projection.decision).toEqual({
      state: 'waiting',
      label: '等待 verification / promotion 回执',
      detail: '多个 Eval 已完成，但还不能 Keep 或改写当前 App 配置。',
    });
    expect(projection.failureBranch).toBe(false);
  });

  it('names missing Eval receipts instead of inventing scores or completion', () => {
    const projection = projectVerticalAppEval(sandboxRun(), [evalSummary('eval:ground-truth')]);

    expect(projection.evals).toMatchObject({
      state: 'waiting',
      expectedCount: 2,
      receivedCount: 1,
      missingEvalRunIds: ['eval:judge'],
    });
    expect(projection.decision.state).toBe('waiting');
    expect(projection.failureBranch).toBe(false);
  });

  it('opens the Trace repair recheck branch only for an observed failure', () => {
    const failedRun = sandboxRun({ status: 'failed' });
    const projection = projectVerticalAppEval(failedRun, []);

    expect(projection.sandbox.state).toBe('failed');
    expect(projection.decision).toEqual({
      state: 'waiting',
      label: '等待 verification / promotion 回执',
      detail: '候选出现失败；Keep / Reject 仍须等待评价或晋升回执。',
    });
    expect(projection.failureBranch).toBe(true);
    expect(projection.traceIds).toEqual(['trace:vertical-app:1']);
  });

  it('does not call mismatched suites comparable', () => {
    const projection = projectVerticalAppEval(
      sandboxRun(),
      [
        evalSummary('eval:ground-truth', {
          suiteBinding: { suiteId: 'sgg', suiteRevision: 'fixture-v3' },
        }),
        evalSummary('eval:judge'),
      ],
    );

    expect(projection.evals.suiteAligned).toBe(false);
    expect(projection.evals.suiteAlignmentReason).toBe('Eval suite 与冻结 cohort 不一致，不能直接比较。');
    expect(projection.evals.state).toBe('waiting');
    expect(projection.decision.state).toBe('waiting');
  });

  it('keeps an unversioned candidate at the frozen-config receipt boundary', () => {
    const run = sandboxRun();
    delete run.replayCohort;

    const projection = projectVerticalAppEval(run, []);

    expect(projection.candidate).toEqual({
      state: 'waiting',
      label: '等待候选配置冻结回执',
      configFingerprint: '',
      cohortLabel: '',
    });
    expect(projection.decision.state).toBe('waiting');
  });
});

function sandboxRun(overrides: Partial<SandboxRunV1> = {}): SandboxRunV1 {
  return {
    schemaVersion: 'rag-ime.sandbox-run.v1',
    sandboxRunId: 'sandbox:vertical-app:1',
    appId: 'extension:vertical-app',
    status: 'completed',
    policy: {
      workspaceBindingId: 'workspace:vertical-app',
      workspaceFingerprint: `sha256:${'0'.repeat(64)}`,
      mutationMode: 'staged',
      network: 'blocked',
      productionWriteBlocked: true,
    },
    replayCohort: {
      suiteId: 'sgg',
      suiteRevision: 'fixture-v2',
      caseId: 'case:checkout',
      inputFingerprint: `sha256:${'1'.repeat(64)}`,
      environmentFingerprint: `sha256:${'2'.repeat(64)}`,
      configFingerprint: `sha256:${'3'.repeat(64)}`,
      modelProfileFingerprint: `sha256:${'4'.repeat(64)}`,
      toolProfileFingerprint: `sha256:${'5'.repeat(64)}`,
      skillProfileFingerprint: `sha256:${'6'.repeat(64)}`,
    },
    traceIds: ['trace:vertical-app:1'],
    evalRunIds: ['eval:ground-truth', 'eval:judge'],
    createdAtMs: 1,
    updatedAtMs: 2,
    ...overrides,
  };
}

function evalSummary(
  evalRunId: string,
  overrides: Partial<EvalSummary> = {},
): EvalSummary {
  return {
    evalRunId,
    mode: 'ground_truth',
    metricAuthority: 'ground_truth',
    truthStatus: 'frozen',
    datasetId: 'sgg:fixture-v2',
    labelRevision: 'labels:1',
    evaluatorDisplayName: '确定性 Eval',
    suiteBinding: { suiteId: 'sgg', suiteRevision: 'fixture-v2' },
    metrics: {},
    status: 'completed',
    createdAtMs: 1,
    updatedAtMs: 2,
    ...overrides,
  };
}
