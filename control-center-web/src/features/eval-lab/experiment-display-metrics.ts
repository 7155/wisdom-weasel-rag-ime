import type { ExperimentResultDisplayMetric, ExperimentResultMetricValue } from './ExperimentResultSummary';
import { pawSelfbootDisplayMetrics } from './paw-selfboot-metrics';

type Metrics = Readonly<Record<string, number>>;
/** The public ledger and API projection share these numeric owners. */
export type ExperimentMetricSource = {
  vertical: string;
  evaluationKind?: string;
  dataset: { caseCount?: number; split?: string };
  baseline: { metrics: Metrics };
  candidate: { metrics: Metrics };
  frozenControls?: readonly { name: string; value: string }[];
};

function finite(metrics: Metrics, key: string): number | undefined {
  const value = metrics[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function fraction(numerator: number | undefined, denominator: number | undefined): ExperimentResultMetricValue | undefined {
  if (numerator === undefined || denominator === undefined || !Number.isInteger(denominator) || denominator <= 0
    || numerator < 0 || numerator > denominator || Math.abs(numerator - Math.round(numerator)) > 1e-6) return undefined;
  return { value: numerator / denominator, display: `${Math.round(numerator)}/${denominator}` };
}

/** Never infer task counts, population, or cost authority from narrative text. */
export function buildExperimentDisplayMetrics(experiment: ExperimentMetricSource): ExperimentResultDisplayMetric[] {
  if (experiment.vertical === 'paw-selfboot') return pawSelfbootDisplayMetrics(experiment);
  const before = experiment.baseline.metrics;
  const after = experiment.candidate.metrics;
  const splitLabels: Record<string, string> = {
    validation: '验证集', development: '开发集', shadow_validation: '隔离验证集',
    holdout: '保留集', heldout: '保留集', test: '测试集',
  };
  const split = experiment.dataset.split;
  const scope = `本轮${split ? splitLabels[split] || split : '数据划分未提供'}，仅描述这批记录。`;
  const paired = (id: string, label: string, project: (metrics: Metrics) => ExperimentResultMetricValue | undefined, fields: string): ExperimentResultDisplayMetric => {
    const first = project(before);
    const second = project(after);
    return {
      id, label, before: first, after: second, format: 'fraction',
      direction: first && second && first.display.split('/')[1] === second.display.split('/')[1] ? 'higher' : undefined,
      note: !first || !second ? '分子或有效分母未提供，暂不比较。' : scope,
      source: fields,
    };
  };
  const counted = (id: string, label: string, numerator: string, denominator: string) => paired(id, label,
    (metrics) => fraction(finite(metrics, numerator), finite(metrics, denominator)), `${numerator} / ${denominator}`);
  const rated = (id: string, label: string, rate: string) => paired(id, label,
    (metrics) => {
      const value = finite(metrics, rate);
      const count = experiment.dataset.caseCount;
      if (value === undefined || value < 0 || value > 1 || count === undefined || !Number.isInteger(count) || count <= 0) return undefined;
      const exact = fraction(value * count, count);
      if (!exact) return { value, display: `${(value * 100).toFixed(1)}%` };
      return exact;
    }, `${rate} × dataset.caseCount / dataset.caseCount；dataset.caseCount=${experiment.dataset.caseCount ?? '未提供'}；无法还原整数分子时保留原始比例。`);

  if (experiment.evaluationKind === 'rag_retrieval' || (finite(before, 'recallAt10') !== undefined && finite(before, 'mrr') !== undefined)) {
    return [['recallAt10', 'Recall@10'], ['mrr', 'MRR'], ['ndcgAt10', 'nDCG@10']].map(([id, label]) => {
      const point = (metrics: Metrics) => {
        const value = finite(metrics, id);
        return value === undefined || value < 0 || value > 1 ? undefined : { value, display: value.toFixed(4) };
      };
      return { id, label, before: point(before), after: point(after), direction: 'higher' as const, format: 'fraction' as const,
        note: scope, source: `${id}；dataset.caseCount=${experiment.dataset.caseCount ?? '未提供'}；聚合评分，不能反推命中题数。` };
    });
  }

  let result: ExperimentResultDisplayMetric[];
  switch (experiment.vertical) {
    case 'enterprise-customer-support':
      result = [counted('task_success', '完整任务通过', 'taskSuccessCount', 'taskCount'), counted('verifier_pass', '业务验收检查', 'verifierPassCount', 'verifierCount')];
      break;
    case 'enterprise-knowledge-retrieval':
      result = [paired('task_success', '完整任务通过', (metrics) => {
        const denominator = finite(metrics, 'agentCaseCount') ?? experiment.dataset.caseCount;
        const rate = finite(metrics, 'agentSuccessRate');
        return fraction(rate === undefined || denominator === undefined ? undefined : rate * denominator, denominator);
      }, `agentSuccessRate × (agentCaseCount ?? dataset.caseCount)；dataset.caseCount=${experiment.dataset.caseCount ?? '未提供'}`),
      paired('citation_coverage', '引用事实覆盖', (metrics) => {
        const denominator = finite(metrics, 'citationFactCount') ?? finite(metrics, 'verifiedRequiredFactCount');
        const count = finite(metrics, 'exactCitationFactsCovered');
        const rate = finite(metrics, 'exactCitationFactCoverage') ?? finite(metrics, 'citationFactCoverage');
        return fraction(count ?? (rate === undefined || denominator === undefined ? undefined : rate * denominator), denominator);
      }, 'exactCitationFactsCovered / citationFactCount；旧记录：citationFactCoverage × verifiedRequiredFactCount / verifiedRequiredFactCount')];
      break;
    case 'cloudops-incident-diagnosis':
      result = [rated('joint_root_cause', '联合根因判定', 'jra'), paired('tool_success', '工具调用成功', (metrics) => {
        const total = finite(metrics, 'toolCalls');
        const failed = finite(metrics, 'failedToolCalls');
        return fraction(total === undefined || failed === undefined ? undefined : total - failed, total);
      }, '(toolCalls − failedToolCalls) / toolCalls')];
      break;
    case 'memory-maintenance':
      result = [counted('curation_pass', '记忆整理通过', 'curationPassed', 'curationCases'), counted('durable_recall', '持久记忆召回', 'durableRecallPassed', 'durableRecallTotal')];
      break;
    default:
      return [];
  }
  const cost = (metrics: Metrics) => {
    const value = finite(metrics, 'apiCostUsd') ?? finite(metrics, 'estimatedApiCostUsd');
    return value === undefined || value < 0 ? undefined : { value, display: `$${value.toFixed(4)}` };
  };
  const costScope = experiment.frozenControls?.find((control) => control.name === 'cost_scope')?.value;
  const costAuthority = experiment.frozenControls?.find((control) => control.name === 'cost_authority')?.value;
  result.push({ id: 'api_cost', label: 'API 估算成本', before: cost(before), after: cost(after), format: 'usd',
    direction: costScope ? 'lower' : undefined,
    note: costScope ? '同一记录口径的运行估算，非 Provider 账单。'
      : costAuthority ? '计价依据已记录，非 Provider 账单。' : '成本统计范围未提供，暂不判断增减；非 Provider 账单。',
    source: `apiCostUsd（兼容 estimatedApiCostUsd）；成本范围：${costScope || '未提供'}；计价依据：${costAuthority || '见范围说明'}` });
  return result;
}
