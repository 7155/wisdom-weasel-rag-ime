import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { TRACE_OPTIMIZATION_FOCUS } from './optimization-intent';

export type TraceCandidateAction = 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback';
export interface TraceReadingMetric {
  id: string;
  label: string;
  kind: string;
  baseline: number | null;
  candidate: number | null;
  baselineDisplay: string;
  candidateDisplay: string;
  baselineCount: string;
  candidateCount: string;
  baselineRatio: number | null;
  candidateRatio: number | null;
}
export interface TraceReadingComparison {
  id: string;
  candidateId: string;
  status: string;
  effect: string;
  effectLabel: string;
  comparable: boolean;
  decision: string;
  validationScopeLabel: string;
  explanation: string;
  reason: string;
  baselineTrialId: string;
  candidateTrialId: string;
  metrics: TraceReadingMetric[];
  cases: { id: string; baseline: number | null; candidate: number | null; regressed: boolean }[];
  regressions: string[];
  evidenceRefs: string[];
  controls: { baseline: Record<string, string>; candidate: Record<string, string> };
  cost: { baseline: number; candidate: number; currency: string } | null;
  costNote: string;
}
export interface TraceReadingCandidate {
  id: string;
  kind: string;
  kindLabel: string;
  target: string;
  parentVersion: string;
  candidateVersion: string;
  findingIds: string[];
  evidenceIds: string[];
  summary: string;
  expectedEffect: string;
  executionLabel: string;
  diffRef: string;
  diff: { before: string; after: string; unified: string } | null;
  comparison: TraceReadingComparison | null;
  applicationLabel: string;
  applicationReceipt: string;
  applicationStatus: string;
  availableActions: TraceCandidateAction[];
  canRun: boolean;
  execution: TraceReadingExecution | null;
}
export interface TraceReadingExecution {
  requestId: string;
  active: boolean;
  awaitingComparison: boolean;
  baselineState: string;
  candidateState: string;
  baselineSummary: string;
  candidateSummary: string;
  baselineJobId: string;
  candidateJobId: string;
}
export interface TraceOptimizationReadingModel {
  intentRecorded: boolean;
  mode: string;
  modeLabel: string;
  focusLabel: string;
  objective: string;
  sourceCount: number;
  recommendation: string;
  recommendationDetail: string;
  candidates: TraceReadingCandidate[];
  comparisons: TraceReadingComparison[];
  distillation: { outcome: string; label: string; title: string; reason: string; proposedChange: string; validationLabel: string; evidenceIds: string[]; candidateIds: string[]; existingCapabilityIds: string[] }[];
  reportRoute: string;
}

/** Only persisted host projections supply change, comparison and application state. */
export function buildTraceOptimizationReadingModel(report: TraceDiagnosticReportV1): TraceOptimizationReadingModel {
  const raw = record(report);
  const intent = record(raw.intent);
  const optimization = record(raw.optimization);
  const comparisons = records(optimization.comparisons)
    .filter((item) => text(item.reportId) === report.reportId)
    .sort((a, b) => (numeric(a.createdAtMs) ?? 0) - (numeric(b.createdAtMs) ?? 0))
    .map(readComparison);
  const applications = records(optimization.applications).sort((a, b) => (numeric(a.createdAtMs) ?? 0) - (numeric(b.createdAtMs) ?? 0));
  const pendingApplications = records(optimization.pendingApplications).sort((a, b) => (numeric(a.createdAtMs) ?? 0) - (numeric(b.createdAtMs) ?? 0));
  const executions = records(optimization.executions).sort((a, b) => (numeric(a.createdAtMs) ?? 0) - (numeric(b.createdAtMs) ?? 0));
  const candidates = records(optimization.candidates).filter((item) => text(item.reportId) === report.reportId).map((item): TraceReadingCandidate => {
    const id = text(item.candidateId);
    const kind = text(item.targetKind);
    const comparison = comparisons.filter((entry) => entry.candidateId === id).at(-1) ?? null;
    const candidateApplications = applications.filter((entry) => text(entry.candidateId) === id && text(entry.reportId) === report.reportId);
    const latestApplication = candidateApplications.at(-1) ?? {};
    const previousApplied = candidateApplications.filter((entry) => ['applied', 'rolled_back', 'kept_original'].includes(text(entry.status))).at(-1);
    const pendingApplication = pendingApplications.filter((entry) => text(entry.candidateId) === id).at(-1);
    const application = pendingApplication ?? (latestApplication.status === 'failed' && previousApplied ? previousApplied : latestApplication);
    const applicationReceipt = text(application.receiptRef);
    const applicationStatus = text(application.status);
    const actualDiff = record(item.actualDiff);
    const diff = { before: text(actualDiff.before), after: text(actualDiff.after), unified: text(actualDiff.unifiedDiff) };
    return {
      id, kind, kindLabel: focusLabel(kind), target: text(item.targetRef, '未记录应用目标'),
      parentVersion: text(item.parentVersionRef, '未记录原版本'), candidateVersion: text(item.candidateVersionRef, '未记录候选版本'),
      findingIds: strings(item.findingIds), evidenceIds: strings(item.evidenceIds),
      summary: text(item.summary, '候选尚无说明'), expectedEffect: text(item.expectedEffect, '尚未声明预期改善'),
      executionLabel: executionLabel(comparison?.status || text(item.executionStatus)), diffRef: text(item.actualDiffRef),
      diff: item.diffStatus === 'verified' && (diff.before || diff.after || diff.unified) ? diff : null, comparison,
      applicationLabel: `${applicationLabel(applicationStatus, applicationReceipt)}${latestApplication.status === 'failed' && previousApplied ? ' · 最近操作失败，之前的状态仍有效' : ''}`, applicationReceipt, applicationStatus,
      availableActions: pendingApplication ? [] : strings(item.availableActions).filter((action): action is TraceCandidateAction => ['install', 'replace', 'apply', 'keep_original', 'rollback'].includes(action)),
      canRun: strings(item.availableActions).includes('run_candidate'),
      execution: readExecution(executions.filter((entry) => text(entry.candidateId) === id).at(-1)),
    };
  });
  const distillationItems = records(record(raw.distillation).items);
  const distillation = distillationItems.map((item) => ({
    outcome: text(item.outcome), label: distillationLabel(text(item.outcome)), reason: text(item.reason, '尚未记录选择理由'),
    title: text(item.title), proposedChange: text(item.proposedChange), validationLabel: item.validationStatus === 'candidate_draft' ? '候选草稿 · 尚未独立验证' : '无需安装可执行能力',
    evidenceIds: strings(item.evidenceIds), candidateIds: strings(item.candidateIds), existingCapabilityIds: strings(item.existingCapabilityIds),
  }));
  const validated = candidates.filter((item) => item.comparison?.comparable && item.comparison.status === 'completed');
  const improved = validated.filter((item) => item.comparison?.effect === 'improved' && item.comparison.decision === 'kept');
  const regressed = validated.filter((item) => item.comparison?.effect === 'regressed');
  let recommendation = '尚未验证';
  let recommendationDetail = '尚无可比的原版与候选运行结果，当前发现和建议不能证明效果提升。';
  if (candidates.length > 1 && validated.length) {
    recommendation = '逐项选择版本';
    recommendationDetail = `${candidates.length} 个候选分别展示改动、验证与应用状态；不同候选不合成为一个总分。`;
  } else if (improved.length) {
    recommendation = '建议采用候选';
    recommendationDetail = '已记录的可比验证支持改善。是否生效，以各候选的应用回执为准。';
  } else if (regressed.length || (validated.length && validated.every((item) => item.comparison?.effect === 'neutral'))) {
    recommendation = '建议保留原版';
    recommendationDetail = regressed.length ? '候选出现退化，先保留原版并查看受影响案例。' : '可比验证尚未显示改善，可保留原版。';
  } else if (intent.mode === 'distill' && distillation.length && distillation.every((item) => ['experience_only', 'no_change'].includes(item.outcome))) {
    recommendation = '本轮无需安装';
    recommendationDetail = distillation.every((item) => item.outcome === 'no_change')
      ? '本轮仅保留诊断报告及来源，不创建能力或经验条目。'
      : '本轮结果保留经验及来源，不把经验记录视为已安装能力。';
  }
  return {
    intentRecorded: Object.keys(intent).length > 0,
    mode: text(intent.mode), modeLabel: intent.mode === 'distill' ? '从对话沉淀方法' : intent.mode === 'improve' ? '分析并优化' : '历史诊断',
    focusLabel: !Object.keys(intent).length ? '未记录关注方向' : intent.scopeMode === 'all' ? `全部 · ${strings(intent.focusAreas).map(focusLabel).join('、')}` : strings(intent.focusAreas).map(focusLabel).join('、') || '未记录关注方向',
    objective: text(intent.objective, '未单独记录优化目标；以下保留来源任务与诊断结论。'), sourceCount: report.targets.length,
    recommendation, recommendationDetail, candidates, comparisons, distillation,
    reportRoute: `/trace-agent?reportId=${encodeURIComponent(report.reportId)}`,
  };
}

const ACTIVE_EXECUTION_STATES = ['queued', 'preparing', 'running', 'cancelling'];
export function traceOptimizationNeedsPolling(report: TraceDiagnosticReportV1): boolean {
  if (report.status === 'generating') return true;
  return records(record(record(report).optimization).executions).some((entry) => {
    const execution = readExecution(entry);
    return execution?.active || execution?.awaitingComparison;
  });
}

function readExecution(item: Record<string, unknown> | undefined): TraceReadingExecution | null {
  if (!item) return null;
  const baseline = text(item.baselineState);
  const candidate = text(item.candidateState);
  const active = ACTIVE_EXECUTION_STATES.includes(baseline) || ACTIVE_EXECUTION_STATES.includes(candidate);
  return {
    requestId: text(item.requestId), active,
    awaitingComparison: !active && !text(item.comparisonId) && ['completed', 'failed', 'cancelled', 'interrupted'].includes(baseline) && ['completed', 'failed', 'cancelled', 'interrupted'].includes(candidate),
    baselineState: executionStateLabel(baseline), candidateState: executionStateLabel(candidate),
    baselineSummary: executionSummary(item.baselineSummary, baseline), candidateSummary: executionSummary(item.candidateSummary, candidate),
    baselineJobId: text(item.baselineJobId), candidateJobId: text(item.candidateJobId),
  };
}

function readComparison(item: Record<string, unknown>): TraceReadingComparison {
  const baselineTrialId = text(item.baselineTrialId);
  const candidateTrialId = text(item.candidateTrialId);
  const status = text(item.executionStatus);
  const comparable = item.comparable === true && status === 'completed' && Boolean(baselineTrialId && candidateTrialId);
  const declaredEffect = text(item.effectStatus, 'not_run');
  const effect = comparable ? declaredEffect : status === 'not_started' ? 'not_run' : 'unverified';
  const usage = record(item.usage);
  const baselineCost = numeric(usage.baselineCost);
  const candidateCost = numeric(usage.candidateCost);
  const costComplete = usage.complete === true && baselineCost !== null && candidateCost !== null;
  const qualityPassed = comparable && item.decision === 'kept' && !strings(item.regressions).length;
  const versions = record(item.actualLoadedVersions);
  return {
    id: text(item.comparisonId), candidateId: text(item.candidateId), status, effect, effectLabel: effectLabel(effect), comparable, decision: text(item.decision),
    validationScopeLabel: item.validationScope === 'frozen_local_task_fixture' ? '仅验证冻结的本地任务用例，未证明未见任务或真实模型行为的改善。' : item.validationScope === 'registered_task_execution' ? '已登记执行器的实际任务验证' : '验证覆盖范围未记录',
    explanation: comparisonExplanation(effect, text(item.decision), comparable),
    reason: text(item.reason, comparable ? '比较条件已记录。' : '缺少完整的同条件前后验证。'), baselineTrialId, candidateTrialId,
    metrics: records(item.pairedMetrics).filter((metric) => metric.kind !== 'cost').map((metric) => {
      const baselineNumerator = numeric(metric.baselineNumerator);
      const baselineDenominator = numeric(metric.baselineDenominator);
      const candidateNumerator = numeric(metric.candidateNumerator);
      const candidateDenominator = numeric(metric.candidateDenominator);
      const id = text(metric.metricId, '未命名指标');
      const baseline = numeric(metric.baseline);
      const candidate = numeric(metric.candidate);
      return {
        id, label: id === 'accuracy' ? '任务通过率' : id, kind: text(metric.kind), baseline, candidate,
        baselineDisplay: metricValue(id, baseline), candidateDisplay: metricValue(id, candidate),
        baselineCount: countText(baselineNumerator, baselineDenominator), candidateCount: countText(candidateNumerator, candidateDenominator),
        baselineRatio: comparable ? ratio(baselineNumerator, baselineDenominator) : null, candidateRatio: comparable ? ratio(candidateNumerator, candidateDenominator) : null,
      };
    }),
    cases: records(item.cases).map((entry) => ({ id: text(entry.caseId), baseline: numeric(entry.baseline), candidate: numeric(entry.candidate), regressed: entry.regressed === true })),
    regressions: strings(item.regressions), evidenceRefs: strings(item.evidenceRefs),
    controls: { baseline: stringRecord(versions.baseline), candidate: stringRecord(versions.candidate) },
    cost: qualityPassed && costComplete ? { baseline: baselineCost!, candidate: candidateCost!, currency: text(usage.currency) } : null,
    costNote: !costComplete ? '实际用量不完整，成本保持未知。' : !qualityPassed ? '质量通过且无退化后再比较成本；当前成本不作为采用依据。' : '仅比较这两次已记录运行的成本；按价格表计算的值属于估算。',
  };
}

export function traceCandidateActionLabel(action: TraceCandidateAction): string { return ({ install: '安装候选', replace: '替换原版', apply: '应用候选', keep_original: '保留原版', rollback: '回退版本' })[action]; }
function applicationLabel(status: string, receipt: string): string {
  if (status === 'kept_original') return '已保留原版';
  if (status === 'failed') return '应用失败';
  if (status === 'interrupted') return '操作结果待确认';
  if (status === 'applying') return '应用结果待核对';
  if (status === 'applied') return receipt ? '已应用 · 有实际回执' : '应用状态待核验 · 缺少回执';
  if (status === 'rolled_back') return receipt ? '已回退 · 有实际回执' : '回退状态待核验 · 缺少回执';
  return '尚未应用';
}
function executionLabel(status: string): string { return ({ not_started: '候选待执行', running: '候选执行中', completed: '候选执行完成', failed: '候选执行失败', cancelled: '已取消', interrupted: '已中断' } as Record<string, string>)[status] ?? '未记录执行状态'; }
function executionStateLabel(status: string): string { return ({ queued: '排队中', preparing: '准备中', running: '执行中', cancelling: '正在取消', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '执行中断', unavailable: '状态不可用' } as Record<string, string>)[status] ?? '状态未记录'; }
function executionSummary(value: unknown, state: string): string {
  const summary = text(value).trim();
  const normalized = summary.toLowerCase();
  return normalized === state.toLowerCase() || summary === executionStateLabel(state) || [...ACTIVE_EXECUTION_STATES, 'completed', 'failed', 'cancelled', 'interrupted', 'unavailable', 'not_started'].includes(normalized) ? '' : summary;
}
function comparisonExplanation(effect: string, decision: string, comparable: boolean): string {
  if (!comparable) return '尚未完成可比的原版与候选验证，当前结果不能证明改善。';
  if (effect === 'regressed') return '候选在本次验证中出现退化，建议保留原版；成本下降不能抵消质量退化。';
  if (effect === 'improved' && decision === 'kept') return '本次同条件验证支持采用候选：已记录的质量或执行成本有所改善。是否生效，以实际应用回执为准。';
  if (decision === 'rejected') return '候选未达到本次采用条件，建议保留原版，并查看质量要求与逐案例结果。';
  if (effect === 'neutral') return '本次可比验证未显示改善，暂不建议替换原版。';
  if (effect === 'improved') return '本次可比验证记录有改善，是否采用仍需结合验证决定与应用回执。';
  return '验证依据仍不完整，需要补充验证后再决定是否采用。';
}
function metricValue(id: string, value: number | null): string {
  if (value === null) return '未记录';
  return ['accuracy', '任务通过率', '任务成功率'].includes(id) && value >= 0 && value <= 1 ? `${Number((value * 100).toFixed(2))}%` : String(value);
}
function effectLabel(effect: string): string { return ({ improved: '有改善', neutral: '未见改善', regressed: '出现退化', not_run: '待重测', unverified: '尚未验证' } as Record<string, string>)[effect] ?? '尚未验证'; }
function distillationLabel(outcome: string): string { return ({ update_existing: '改进已有能力', new_skill: '新增 Skill 候选', new_tool: '新增工具候选', experience_only: '仅沉淀经验', no_change: '无需沉淀' } as Record<string, string>)[outcome] ?? '沉淀结论未记录'; }
function focusLabel(key: string): string { return TRACE_OPTIMIZATION_FOCUS.find(([id]) => id === (key === 'template' ? 'prompt' : key))?.[1] ?? key; }
function countText(n: number | null, d: number | null): string { return n !== null && d !== null ? `${n} / ${d}` : '分子 / 分母未记录'; }
function ratio(n: number | null, d: number | null): number | null { return n !== null && d !== null && d > 0 && n >= 0 && n <= d ? n / d : null; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function records(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.map(record) : []; }
function text(value: unknown, fallback = ''): string { return typeof value === 'string' && value.trim() ? value : fallback; }
function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []; }
function numeric(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
function stringRecord(value: unknown): Record<string, string> { return Object.fromEntries(Object.entries(record(value)).filter((pair): pair is [string, string] => typeof pair[1] === 'string')); }
