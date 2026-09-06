import type { ExperimentResultDisplayMetric } from './ExperimentResultSummary';
import type { ExperimentMetricSource } from './experiment-display-metrics';

type PawDisplayMetric = ExperimentResultDisplayMetric & { format: 'fraction' | 'usd' };

const COUNTS = [
  ['taskSuccessCount', 'taskCount', '完整任务通过'],
  ['verifierPassCount', 'verifierCount', '实现与业务验收'],
  ['recallPassed', 'recallTotal', '关键信息召回'],
  ['exclusionPassed', 'exclusionTotal', '应排除信息拦截'],
  ['observationPassed', 'observationCount', '受控观察通过'],
  ['startupPassed', 'startupCount', '隔离启动通过'],
  ['uiPassed', 'uiCount', '真实界面验收'],
  ['deliveryPassed', 'deliveryCount', '实际交付检查'],
] as const;

export const PAW_METRIC_LABELS: Readonly<Record<string, string>> = {
  providerCalls: '模型调用', totalTokens: '完整 turn tokens',
  modelAttemptMessages: '模型响应记录（含中断）', observedTokens: '已观察 tokens', knownEstimatedApiCostUsd: '已知估算费用',
  continuationEntered: '已进入重启后的接续阶段', restartPreserved: '重启后产物保留',
  optimizationProviderCalls: '实验与优化总调用', optimizationTokens: '实验与优化总 tokens',
  optimizationEstimatedCostUsd: '实验与优化总估算费用', diagnosisEstimatedCostUsd: '诊断估算费用',
  observationPassed: '通过的受控观察', observationCount: '受控观察总数', scenarioCount: '故障种类',
  recallPassed: '正例召回数', recallTotal: '正例总数', exclusionPassed: '负例排除数', exclusionTotal: '负例总数',
  staleExposureCount: '过期或错误信息暴露数', exposureCaseCount: '上下文检查数', memoryContextEstimatedTokens: '记忆上下文估算 tokens',
  startupPassed: '隔离启动通过数', startupCount: '隔离启动总数', uiPassed: '界面验收通过数', uiCount: '界面验收总数',
  uniqueBusinessCases: '唯一业务用例', parityPassed: '导出前后一致',
  deliveryPassed: '实际交付通过数', deliveryCount: '实际交付检查数',
  cancelP95Ms: '取消收口 p95', cancelSamples: '取消计时样本', restoreP95Ms: '恢复读回 p95', restoreSamples: '恢复计时样本',
  duplicateSideEffects: '重复副作用', assignedCaseOverlap: '分配重叠', correctHandoffFacts: '正确交接项',
  omittedCorrectHandoffFacts: '交接遗漏', duplicateFindingRows: '重复发现行', forbiddenApprovals: '禁止批准事件', negativeCaseCount: '禁止批准负例',
};

function known(metrics: Readonly<Record<string, number>>, key: string): number | undefined {
  const value = metrics[key];
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}

export function pawSelfbootDisplayMetrics(experiment: ExperimentMetricSource): PawDisplayMetric[] {
  const comparable = experiment.frozenControls?.some((c) => c.name === 'comparison_scope' && c.value === 'paired');
  const result: PawDisplayMetric[] = [];
  for (const [numerator, denominator, label] of COUNTS) {
    const value = (side: 'baseline' | 'candidate') => {
      const n = known(experiment[side].metrics, numerator); const d = known(experiment[side].metrics, denominator);
      return n !== undefined && d !== undefined && Number.isInteger(n) && Number.isInteger(d) && d > 0 && n <= d
        ? { value: n / d, display: `${n}/${d}` } : undefined;
    };
    const before = value('baseline'); const after = value('candidate');
    if (!before && !after) continue;
    result.push({ id: numerator, label, before, after, format: 'fraction',
      direction: comparable && before && after && before.display.split('/')[1] === after.display.split('/')[1] ? 'higher' : undefined,
      source: `${numerator} / ${denominator}`,
      note: comparable ? '只描述本轮固定任务；检查数与独立任务数分开。' : '单轮观察或环境阻塞；没有配对收益结论。' });
  }
  const cost = (side: 'baseline' | 'candidate') => {
    const value = known(experiment[side].metrics, 'estimatedApiCostUsd');
    return value === undefined ? undefined : { value, display: `$${value.toFixed(6)}` };
  };
  if (cost('baseline') || cost('candidate')) result.push({ id: 'api_cost', label: 'API 估算成本', before: cost('baseline'), after: cost('candidate'), format: 'usd',
    direction: comparable && cost('baseline') && cost('candidate') ? 'lower' : undefined,
    note: 'Pi 完整 turn 目录价估算，非 Provider 账单；优化投入另列。', source: 'estimatedApiCostUsd' });
  return result;
}

export function pawSelfbootQuality(experiment: ExperimentMetricSource): string {
  return pawSelfbootDisplayMetrics(experiment).filter((m) => m.format === 'fraction').map((m) =>
    `${m.label} ${m.before?.display ?? '未提供基线'} → ${m.after?.display ?? '未测'}`).join(' · ') || '质量验收尚未提供';
}

export function pawSelfbootReliability(experiment: ExperimentMetricSource): string {
  const candidate = experiment.candidate.metrics;
  const keys = ['duplicateSideEffects', 'omittedCorrectHandoffFacts', 'duplicateFindingRows', 'staleExposureCount', 'forbiddenApprovals'];
  const values = keys.filter((key) => known(candidate, key) !== undefined).map((key) => `${PAW_METRIC_LABELS[key]} ${candidate[key]}`);
  const recovery = pawSelfbootRecoveryStatus(candidate);
  if (recovery) values.push(recovery);
  return values.join(' · ')
    || '按本轮检查范围验收；恢复和副作用证据见报告';
}

export function pawSelfbootRecoveryStatus(metrics: Readonly<Record<string, number>>): string | undefined {
  if (metrics.continuationEntered === 0) return '尚未进入重启后的接续阶段';
  if (metrics.continuationEntered === 1) return metrics.restartPreserved === 1
    ? '已进入重启后的接续阶段；产物保留已观察'
    : '已进入重启后的接续阶段；产物保留未记录';
  return undefined;
}

export function pawSelfbootEfficiency(experiment: ExperimentMetricSource): string {
  const fields = [
    ['providerCalls', '模型调用', (n: number) => String(n)],
    ['totalTokens', 'tokens', (n: number) => n.toLocaleString('en-US')],
    ['estimatedApiCostUsd', '估算费用', (n: number) => `$${n.toFixed(6)}`],
    ['latencyMs', '耗时', (n: number) => `${(n / 1000).toFixed(2)} 秒`],
    ['modelAttemptMessages', '模型响应记录（含中断）', (n: number) => String(n)],
    ['observedTokens', '已观察 tokens', (n: number) => n.toLocaleString('en-US')],
    ['knownEstimatedApiCostUsd', '已知估算费用', (n: number) => `$${n.toFixed(6)}`],
  ] as const;
  return fields.flatMap(([key, label, format]) => {
    const before = known(experiment.baseline.metrics, key); const after = known(experiment.candidate.metrics, key);
    if (before === undefined && after === undefined) return [];
    return [`${label} ${before === undefined ? '' : `${format(before)} → `}${after === undefined ? '未测' : format(after)}`];
  }).join(' · ') || '代价尚未测量';
}
