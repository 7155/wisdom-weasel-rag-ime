import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { buildTraceDiagnosticReportHtml } from './html-export';
import { buildTraceOptimizationReadingModel, traceOptimizationNeedsPolling } from './optimization-report-model';
import { TraceDiagnosticReportDocument } from './report-document';

afterEach(cleanup);

describe('Trace optimization report', () => {
  it('polls completed reports with real active execution and allows cancellation without inventing progress', async () => {
    const report = optimizationFixture();
    report.optimization!.executions = [{ requestId: 'request:running', candidateId: 'candidate:retry', baselineJobId: 'job:before', candidateJobId: 'job:after', baselineState: 'completed', candidateState: 'running', baselineSummary: '原版 2 个用例已结束', candidateSummary: '候选正在处理第二个用例', comparisonId: '', createdAtMs: 210 }];
    expect(traceOptimizationNeedsPolling(report)).toBe(true);
    const onCancelCandidate = vi.fn();
    render(<TraceDiagnosticReportDocument report={report} onOpenDiagnosticSession={() => undefined} onOpenTarget={() => undefined} onCancelCandidate={onCancelCandidate} />);
    expect(screen.getByText('候选正在处理第二个用例')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: '取消本次验证' }));
    expect(onCancelCandidate).toHaveBeenCalledWith('candidate:retry');
    report.optimization!.executions[0].candidateState = 'completed';
    expect(traceOptimizationNeedsPolling(report)).toBe(true);
    report.optimization!.executions[0].comparisonId = 'comparison:retry';
    expect(traceOptimizationNeedsPolling(report)).toBe(false);
  });

  it('shows the same goal, linked change and paired denominators in the App and exported report', () => {
    const report = optimizationFixture();
    const comparison = report.optimization!.comparisons[0];
    comparison.reason = 'Frozen quality requirements passed without case regressions';
    comparison.validationScope = 'frozen_local_task_fixture';
    comparison.pairedMetrics[0] = { metricId: 'accuracy', kind: 'quality', baseline: 0, candidate: 1, delta: 1, baselineNumerator: 0, baselineDenominator: 2, candidateNumerator: 2, candidateDenominator: 2 };
    report.optimization!.executions = [{ requestId: 'request:finished', candidateId: 'candidate:retry', baselineJobId: 'job:before', candidateJobId: 'job:after', baselineState: 'completed', candidateState: 'completed', baselineSummary: 'completed', candidateSummary: ' Completed ', comparisonId: comparison.comparisonId, createdAtMs: 210 }];
    const { container } = renderDocument(report);
    const html = new DOMParser().parseFromString(buildTraceDiagnosticReportHtml(report), 'text/html');
    const appHeadings = [...container.querySelectorAll('.trace-reading h3')].map((heading) => heading.textContent);
    expect([...html.querySelectorAll('.trace-reading h3')].map((heading) => heading.textContent)).toEqual(appHeadings);
    for (const root of [container, html]) {
      const foreground = root.querySelector('.trace-reading');
      expect(foreground?.textContent).toContain('减少有效问题中的重复重试');
      expect(foreground?.textContent).toContain('建议采用候选');
      expect(foreground?.textContent).toContain('任务通过率');
      expect(foreground?.textContent).toContain('0 / 2');
      expect(foreground?.textContent).toContain('2 / 2');
      expect([...foreground!.querySelectorAll('.trace-reading__metric-side > strong')].map((value) => value.textContent)).toEqual(['0%', '100%']);
      expect(foreground?.querySelector('.trace-reading__validation > p')?.textContent).toContain('本次同条件验证支持采用候选');
      expect(foreground?.querySelector('.trace-reading__comparison-details')?.textContent).toContain(comparison.reason);
      expect(foreground?.textContent).toContain('仅验证冻结的本地任务用例，未证明未见任务或真实模型行为的改善。');
      expect(foreground?.querySelectorAll('.trace-reading__execution p')).toHaveLength(0);
      expect(foreground?.textContent).toContain('- retry any failure\n+ retry transient failures');
      expect(foreground?.querySelectorAll('.trace-reading__bar')).toHaveLength(2);
      expect(foreground?.textContent).not.toContain('八维');
    }
    expect(html.querySelector('.trace-reading button')).toBeNull();
    expect(html.querySelector('script')).toBeNull();
  });

  it('does not turn completed runs, unknown values or unbound comparisons into improvement claims', () => {
    const report = optimizationFixture();
    const comparison = report.optimization!.comparisons[0];
    comparison.comparable = false;
    comparison.pairedMetrics[0]!.candidate = null;
    comparison.pairedMetrics[0]!.candidateNumerator = null;
    comparison.pairedMetrics[0]!.candidateDenominator = null;
    const model = buildTraceOptimizationReadingModel(report);
    expect(model.recommendation).toBe('尚未验证');
    expect(model.candidates[0].comparison?.effect).toBe('unverified');
    expect(model.candidates[0].comparison?.metrics[0]).toMatchObject({ candidate: null, candidateRatio: null, candidateCount: '分子 / 分母未记录' });
    expect(model.candidates[0].comparison?.cost).toBeNull();
    renderDocument(report);
    expect(document.querySelectorAll('.trace-reading__bar')).toHaveLength(0);
    expect(screen.getByText('比较条件或执行证据不完整，以下记录不作为提升结论。')).toBeInTheDocument();
  });

  it('keeps unknown historical focus, unverified diffs and model-authored install claims out of authority', () => {
    const report = optimizationFixture();
    delete report.intent;
    report.optimization!.candidates[0].diffStatus = 'unverified';
    Object.assign(report.result!, { optimization: { applications: [{ status: 'applied', receiptRef: 'fake' }] }, distillation: { outcome: 'new_tool' } });
    const reading = buildTraceOptimizationReadingModel(report);
    expect(reading.focusLabel).toBe('未记录关注方向');
    expect(reading.candidates[0].diff).toBeNull();
    expect(reading.candidates[0].applicationLabel).toBe('尚未应用');
    expect(reading.distillation).toEqual([]);
  });

  it('waits for the owning service application receipt and preserves rejected validation', async () => {
    const report = optimizationFixture();
    report.optimization!.comparisons[0].effectStatus = 'regressed';
    report.optimization!.comparisons[0].decision = 'rejected';
    report.optimization!.comparisons[0].regressions = ['case:retry-exhausted'];
    report.optimization!.candidates[0].availableActions = ['keep_original'];
    const onCandidateAction = vi.fn();
    const view = renderDocument(report, onCandidateAction);
    expect(screen.getByText('建议保留原版')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '替换原版' })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: '保留原版' }));
    expect(onCandidateAction).toHaveBeenCalledWith('candidate:retry', 'keep_original');
    expect(screen.getByText('尚未应用')).toBeInTheDocument();
    report.optimization!.applications.push({ applicationId: 'application:keep', reportId: report.reportId, candidateId: 'candidate:retry', comparisonId: 'comparison:retry', action: 'keep_original', status: 'kept_original', receiptRef: 'receipt:keep', targetRef: 'skill:retry', versionRef: 'v1', createdAtMs: 300, contentSha256: 'c'.repeat(64) });
    view.rerender(<TraceDiagnosticReportDocument report={report} onOpenDiagnosticSession={() => undefined} onOpenTarget={() => undefined} onCandidateAction={onCandidateAction} />);
    expect(screen.getByText('已保留原版')).toBeInTheDocument();
    expect(screen.getByText('case:retry-exhausted')).toBeInTheDocument();
  });

  it('labels multi-conversation distillation outcomes with source evidence and candidate draft boundaries', () => {
    const report = optimizationFixture();
    report.intent!.mode = 'distill';
    report.distillation = { authority: 'analysis_proposal', inventorySha256: 'a'.repeat(64), sourceInspectionSha256: 'b'.repeat(64), items: ['update_existing', 'new_skill', 'new_tool', 'experience_only', 'no_change'].map((outcome, index) => ({ suggestionId: `suggestion:${index}`, outcome: outcome as 'new_skill', requestedOutcome: outcome as 'new_skill', title: `方法 ${index}`, reason: '已对照现有能力与两段来源对话', proposedChange: '', evidenceIds: ['evidence:retry'], sourceRefs: [], existingCapabilityIds: [], capabilityNeeds: [], validationStatus: outcome === 'experience_only' || outcome === 'no_change' ? 'not_applicable' as const : 'candidate_draft' as const, candidateIds: [] })) };
    renderDocument(report);
    const result = screen.getByRole('region', { name: '这些经历值得沉淀什么' });
    for (const label of ['改进已有能力', '新增 Skill 候选', '新增工具候选', '仅沉淀经验', '无需沉淀']) expect(within(result).getByText(label)).toBeInTheDocument();
    expect(within(result).getAllByRole('button', { name: '查看证据 evidence:retry' })).toHaveLength(5);
  });
});

function renderDocument(report: TraceDiagnosticReportV1, onCandidateAction = vi.fn()) { return render(<TraceDiagnosticReportDocument report={report} onOpenDiagnosticSession={() => undefined} onOpenTarget={() => undefined} onCandidateAction={onCandidateAction} />); }

function optimizationFixture(): TraceDiagnosticReportV1 {
  const reportId = `trace-report:${'f'.repeat(32)}`;
  const intent = { mode: 'improve', scopeMode: 'selected', focusAreas: ['skill'], objective: '减少有效问题中的重复重试' } as const;
  return {
    schemaVersion: 'rag-ime.trace-diagnostic-report.v1', reportId, revision: 1, status: 'completed', title: '重试策略优化', diagnosticSessionId: 'session:diagnostic', targets: [{ targetKey: 'session:source', kind: 'session', id: 'source', title: '排障对话', traceIds: ['trace:source'], sourceAvailable: true }], traceIds: ['trace:source'], inspectionSha256: 'a'.repeat(64), failureReason: '', createdAtMs: 100, updatedAtMs: 200,
    intent: { ...intent, focusAreas: ['skill'] },
    inspection: { evidence: [{ evidenceId: 'evidence:retry', sourceRef: 'trace:source:span:retry', sourceKind: 'trace_span', targetKey: 'session:source', summary: '已知输入错误重复重试', status: 'failed', traceId: 'trace:source' }] },
    result: { summary: '在固定任务上限制无效重试。', findings: [{ findingId: 'finding:retry', observation: '已知输入错误仍重复调用工具', hypothesis: 'Skill 没有区分可重试与不可重试错误', conclusion: '先区分错误类别再决定重试', candidateRepair: '缩小重试触发条件', verification: '在原案例与独立回归案例中检查结果', evidenceIds: ['evidence:retry'], dimensionId: 'tool_runtime', severity: 'high', confidence: 'medium' }] },
    optimization: {
      schemaVersion: 'rag-ime.trace-optimization.v1', applications: [],
      candidates: [{ candidateId: 'candidate:retry', reportId, optimizationProjectId: 'project:retry', targetKind: 'skill', targetRef: 'skill:retry', parentVersionRef: 'v1', candidateVersionRef: 'v2', findingIds: ['finding:retry'], evidenceIds: ['evidence:retry'], historicalPatternRefs: [], summary: '仅对暂时性故障重试', expectedEffect: '任务质量保持达标，减少重复调用', actualDiffRef: 'artifact:retry-diff', actualDiff: { before: 'retry any failure', after: 'retry transient failures', unifiedDiff: '- retry any failure\n+ retry transient failures' }, diffStatus: 'verified', availableActions: ['replace', 'keep_original'], supportedActions: ['run_candidate', 'replace', 'keep_original'], executionStatus: 'not_started', createdAtMs: 110, contentSha256: 'b'.repeat(64), comparisonContractSha256: 'c'.repeat(64), intent: { ...intent, focusAreas: ['skill'] }, comparisonContract: { caseSetRef: 'cases:retry', caseIds: ['case:1', 'case:2'], controls: { model: 'model:v1' }, declaredChanges: [{ kind: 'skill', targetRef: 'skill:retry', beforeVersionRef: 'v1', afterVersionRef: 'v2' }], qualityGates: [{ metricId: '任务成功率', minimum: 0.8 }], costMetric: 'totalCost' } }],
      comparisons: [{ comparisonId: 'comparison:retry', reportId, candidateId: 'candidate:retry', optimizationProjectId: 'project:retry', baselineTrialId: 'trial:before', candidateTrialId: 'trial:after', executionStatus: 'completed', effectStatus: 'improved', validationScope: 'registered_task_execution', decision: 'kept', comparable: true, reason: '同一组固定任务、模型与工具，唯一改变是重试 Skill。', pairedMetrics: [{ metricId: '任务成功率', kind: 'quality', baseline: 0.8, candidate: 1, delta: 0.2, baselineNumerator: 8, baselineDenominator: 10, candidateNumerator: 10, candidateDenominator: 10 }], cases: [{ caseId: 'case:1', baseline: 0, candidate: 1, regressed: false }, { caseId: 'case:2', baseline: 1, candidate: 1, regressed: false }], regressions: [], usage: { baselineCost: 1, candidateCost: 0.8, currency: 'USD', complete: true }, evidenceRefs: ['trial:before', 'trial:after'], actualLoadedVersions: { baseline: { skill: 'v1' }, candidate: { skill: 'v2' } }, createdAtMs: 200, contentSha256: 'd'.repeat(64) }],
    },
  };
}
