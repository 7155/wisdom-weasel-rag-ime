import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { TraceDiagnosticReportListV1 } from '@/contracts/generated/trace-diagnostic-report-list.v1';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { MockControlTransport } from '@/test/mock-transport';
import type {
  EvalLabEvidenceRun,
  EvalLabExperiment,
  EvalLabRun,
} from '../api';
import { LinkedOptimizationWorkbench, OptimizationWorkbench } from './OptimizationWorkbench';
import workbenchCss from './optimization-workbench.css?raw';
import { findLinkedTraceReportSummary } from './use-linked-trace-report';

afterEach(cleanup);

const experiment = {
  schemaVersion: 'rag-ime.agent-lab-experiment.v1',
  experimentId: 'experiment:checkout-repair',
  revisionSha256: 'a'.repeat(64),
  title: 'Checkout repair',
  vertical: 'cloudops',
  evaluationKind: 'trace_repair',
  status: 'kept',
  claimStatus: 'supporting',
  projectionState: 'current',
  businessProblem: '恢复 checkout 任务。',
  whyAgent: '需要核对真实执行证据。',
  dataset: {
    datasetId: 'checkout-validation',
    split: 'validation',
    caseCount: 1,
    unit: '冻结 Case',
    manifestSha256: 'b'.repeat(64),
    heldOutConsumed: false,
  },
  scoring: {
    primaryMetric: 'taskSuccessRate',
    evaluatorAuthority: 'host',
    goldHiddenFromAgent: true,
    hardGates: ['final state'],
  },
  factors: [{
    name: 'workflow',
    before: '没有终态检查',
    after: '增加终态检查',
    reason: '失败 Trace 指向工作流闭环。',
  }],
  frozenControls: [{ name: 'case_set', value: 'case-checkout-1', reason: '同 Case 比较。' }],
  baseline: {
    runId: 'run:checkout:baseline',
    metrics: { taskSuccessRate: 0 },
    evidenceRefs: ['receipt:baseline'],
  },
  candidate: {
    runId: 'run:checkout:candidate',
    metrics: { taskSuccessRate: 1 },
    evidenceRefs: ['receipt:candidate'],
  },
  comparison: {
    decision: 'keep',
    decisionReason: '同一 Case 复跑通过。',
    metricDeltas: [{ metric: 'taskSuccessRate', before: 0, after: 1, delta: 1 }],
    outputComparisons: [{
      caseId: 'case-checkout-1',
      before: '停在处理中。',
      after: '已写入终态并复核。',
    }],
  },
  star: { situation: '任务失败。', task: '定位并复跑。', action: '单因素修复。', result: '通过。' },
  claim: { resumeBullet: '', allowed: 'Validation 通过。', forbidden: '不代表生产通过。' },
  openGaps: [],
  importedAtMs: 1,
} as EvalLabExperiment;

const linkedRuns = [
  {
    runId: 'run:checkout:baseline',
    tasks: [{
      taskIndex: 1,
      taskSucceeded: false,
      terminalEvent: 'turn_completed',
      verifierPassed: 0,
      verifierTotal: 1,
      explanation: {
        caseId: 'case-checkout-1',
        businessRequest: { normalizedText: '完成 checkout 并写入终态。' },
        agentOutcome: { normalizedSummary: 'checkout 仍处于处理中。' },
        acceptance: {
          passed: 0,
          total: 1,
          items: [{
            id: 'final-state',
            label: '终态写入',
            status: 'fail',
            failureOwner: 'agent',
            explanation: '没有写入可复核终态。',
          }],
        },
      },
    }],
  },
  {
    runId: 'run:checkout:candidate',
    tasks: [{
      taskIndex: 1,
      taskSucceeded: true,
      terminalEvent: 'turn_completed',
      verifierPassed: 1,
      verifierTotal: 1,
      explanation: {
        caseId: 'case-checkout-1',
        businessRequest: { normalizedText: '完成 checkout 并写入终态。' },
        agentOutcome: { normalizedSummary: '已写入终态并复核。' },
        acceptance: { passed: 1, total: 1, items: [] },
      },
    }],
  },
] as unknown as readonly EvalLabRun[];

const evidenceRuns = [
  {
    runId: 'run:checkout:baseline',
    environment: { traceIds: ['trace:checkout:failure'] },
    tasks: [{ taskIndex: 1, taskLabel: 'Checkout Case', title: 'Checkout Case' }],
  },
  {
    runId: 'run:checkout:candidate',
    environment: { traceIds: ['trace:checkout:repair'] },
    tasks: [{ taskIndex: 1, taskLabel: 'Checkout Case', title: 'Checkout Case' }],
  },
] as unknown as readonly EvalLabEvidenceRun[];

const traceReport = {
  schemaVersion: 'rag-ime.trace-diagnostic-report.v1',
  reportId: `trace-report:${'c'.repeat(32)}`,
  revision: 1,
  status: 'completed',
  title: 'Checkout failure diagnosis',
  diagnosticSessionId: 'agent:trace:checkout',
  targets: [{
    targetKey: 'run:run:checkout:baseline',
    kind: 'run',
    id: 'run:checkout:baseline',
    title: 'Baseline run',
    traceIds: ['trace:checkout:failure'],
    sourceAvailable: true,
  }],
  traceIds: ['trace:checkout:failure'],
  inspectionSha256: 'd'.repeat(64),
  inspection: {
    scorecard: { dimensions: [] },
    evidence: [{
      evidenceId: 'evidence:workflow:1',
      targetKey: 'run:run:checkout:baseline',
      traceId: 'trace:checkout:failure',
      sourceKind: 'trace',
      sourceRef: 'trace:checkout:failure#event-4',
      status: 'failed',
      summary: '执行结束但没有写入终态。',
      createdAtMs: 2,
    }],
    timeline: [],
  },
  result: {
    presentation: {
      failureAttribution: {
        primaryLayer: 'workflow',
        summary: '主要失败在工作流闭环。',
        layers: [{
          layer: 'workflow',
          verdict: 'primary',
          evidenceIds: ['evidence:workflow:1'],
          explanation: '终态步骤没有执行。',
        }],
      },
    },
    findings: [],
    hardGates: [],
    judgeScores: [],
    summary: '工作流缺少终态步骤。',
  },
  failureReason: '',
  createdAtMs: 2,
  updatedAtMs: 3,
} as unknown as TraceDiagnosticReportV1;

describe('OptimizationWorkbench', () => {
  it('never links a Trace report by title or candidate identity', () => {
    const candidateOnly: TraceDiagnosticReportListV1['items'][number] = {
      reportId: traceReport.reportId,
      revision: 1,
      status: 'completed' as const,
      title: experiment.title,
      diagnosticSessionId: traceReport.diagnosticSessionId,
      targetKeys: ['run:run:checkout:candidate'],
      targets: [{
        targetKey: 'run:run:checkout:candidate',
        kind: 'run' as const,
        id: experiment.candidate.runId,
        title: experiment.title,
        traceIds: ['trace:checkout:repair'],
        sourceAvailable: true,
      }],
      traceIds: ['trace:checkout:repair'],
      failureReason: '',
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    expect(findLinkedTraceReportSummary(
      [candidateOnly],
      experiment.baseline.runId,
      ['trace:checkout:failure'],
    )).toBeUndefined();
  });

  it('stacks the diagnostic flow in reading order on narrow screens', () => {
    const narrowRule = workbenchCss.match(/@media\s*\(max-width:\s*760px\)\s*\{([\s\S]*)\}\s*$/u)?.[1] ?? '';
    expect(narrowRule).toContain('.optimization-workbench__primary-flow');
    expect(narrowRule).toContain('.optimization-workbench__closure');
    expect(narrowRule).toMatch(/grid-template-columns:\s*1fr/);
  });

  it('connects an exact failed Case to receipt-backed attribution, exact Trace drill-down, same-Case comparison, and the persisted verdict', async () => {
    const onOpenTraceReport = vi.fn();
    render(
      <OptimizationWorkbench
        evidenceRuns={evidenceRuns}
        experiment={experiment}
        linkedRuns={linkedRuns}
        onOpenTraceReport={onOpenTraceReport}
        traceReport={traceReport}
      />,
    );

    const workbench = screen.getByRole('region', { name: 'Optimization Workbench' });
    expect(workbench).toHaveTextContent('run:checkout:baseline');
    expect(workbench).toHaveTextContent('case-checkout-1');
    expect(workbench).toHaveTextContent('trace:checkout:failure');
    expect(workbench).toHaveTextContent('完成 checkout 并写入终态。');
    expect(workbench).toHaveTextContent('checkout 仍处于处理中。');
    expect(workbench).toHaveTextContent('终态写入');

    const attribution = within(workbench).getByRole('group', { name: '根因归因' });
    expect(attribution).toHaveTextContent('工作流');
    expect(attribution).toHaveTextContent('主要');
    expect(attribution).toHaveTextContent('E1');
    await userEvent.setup().click(within(attribution).getByRole('button', { name: '打开 Trace 诊断报告' }));
    expect(onOpenTraceReport).toHaveBeenCalledOnce();
    expect(onOpenTraceReport).toHaveBeenCalledWith(traceReport.reportId);

    const candidate = within(workbench).getByRole('group', { name: '候选变化' });
    expect(candidate).toHaveTextContent('变化摘要');
    expect(candidate).toHaveTextContent('没有终态检查');
    expect(candidate).toHaveTextContent('增加终态检查');
    expect(candidate).toHaveTextContent('真实 Diff 未记录');

    const comparison = within(workbench).getByRole('group', { name: 'Before / After' });
    expect(comparison).toHaveTextContent('停在处理中。');
    expect(comparison).toHaveTextContent('已写入终态并复核。');
    expect(comparison).not.toHaveTextContent('不可比较');
    expect(within(workbench).getByRole('group', { name: 'Keep / Reject' })).toHaveTextContent('Keep');
  });

  it('fails closed for history and does not use a candidate-only Trace report or infer a verdict', () => {
    const mismatchedReport = {
      ...traceReport,
      targets: [{
        ...traceReport.targets[0],
        id: 'run:checkout:candidate',
        traceIds: ['trace:checkout:repair'],
      }],
      traceIds: ['trace:checkout:repair'],
    } as TraceDiagnosticReportV1;
    render(
      <OptimizationWorkbench
        evidenceRuns={[]}
        experiment={{
          ...experiment,
          projectionState: 'history',
          comparison: { ...experiment.comparison, decision: 'diagnostic', outputComparisons: [] },
        }}
        linkedRuns={[]}
        traceReport={mismatchedReport}
      />,
    );

    const workbench = screen.getByRole('region', { name: 'Optimization Workbench' });
    expect(workbench).toHaveTextContent('历史只读');
    expect(workbench).toHaveTextContent('尚未找到精确失败 Case');
    expect(within(workbench).getByRole('group', { name: '根因归因' })).toHaveTextContent('未绑定 Trace 诊断回执');
    expect(within(workbench).getByRole('group', { name: 'Before / After' })).toHaveTextContent('不可比较');
    expect(within(workbench).getByRole('group', { name: 'Keep / Reject' })).toHaveTextContent('待定');
    expect(workbench).not.toHaveTextContent('主要失败在工作流闭环');
    expect(screen.queryByRole('button', { name: '打开 Trace 诊断报告' })).not.toBeInTheDocument();
  });

  it('loads a persisted Trace report only through an exact baseline run or trace identity', async () => {
    const summary = {
      reportId: traceReport.reportId,
      revision: traceReport.revision,
      status: traceReport.status,
      title: traceReport.title,
      diagnosticSessionId: traceReport.diagnosticSessionId,
      targetKeys: traceReport.targets.map((target) => target.targetKey),
      targets: traceReport.targets,
      traceIds: traceReport.traceIds,
      failureReason: '',
      createdAtMs: traceReport.createdAtMs,
      updatedAtMs: traceReport.updatedAtMs,
    };
    const transport = new MockControlTransport({
      routes: {
        'observability.traceDiagnosticReports.list': {
          schemaVersion: 'rag-ime.trace-diagnostic-report-list.v1',
          total: 1,
          truncated: false,
          nextCursor: null,
          items: [summary],
        },
        'observability.traceDiagnosticReport.get': traceReport,
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <LinkedOptimizationWorkbench
            evidenceRuns={evidenceRuns}
            experiment={experiment}
            linkedRuns={linkedRuns}
          />
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('主要失败在工作流闭环。')).toBeInTheDocument();
    expect(transport.requests.map(({ request }) => request.pathId)).toEqual(expect.arrayContaining([
      'observability.traceDiagnosticReports.list',
      'observability.traceDiagnosticReport.get',
    ]));
  });

  it('keeps a report-only failed Case visible while marking its expected and actual text unavailable', () => {
    const reportOnlyEvidence = [{
      ...evidenceRuns[0],
      tasks: [{
        taskIndex: 7,
        taskLabel: 'case-report-only-7',
        title: 'Report-only failure',
        taskSucceeded: false,
        terminalEvent: 'failed',
        failedVerifierNames: ['terminal contract'],
      }],
    }] as unknown as readonly EvalLabEvidenceRun[];

    render(
      <OptimizationWorkbench
        evidenceRuns={reportOnlyEvidence}
        experiment={experiment}
        linkedRuns={[]}
      />,
    );

    const failure = screen.getByRole('group', { name: '失败切片' });
    expect(failure).toHaveTextContent('run:checkout:baseline');
    expect(failure).toHaveTextContent('case-report-only-7');
    expect(failure).toHaveTextContent('任务要求未记录');
    expect(failure).toHaveTextContent('实际输出未记录');
    expect(failure).toHaveTextContent('terminal contract');
  });
});
