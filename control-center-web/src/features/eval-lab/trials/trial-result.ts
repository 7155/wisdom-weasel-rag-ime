import { object } from './api';

const metricNames: Record<string, string> = {
  AnswerCoverage: '答案覆盖率', CA: '故障组件命中（CA）', FA: '故障类型命中（FA）', JRA: '联合根因命中（JRA）', Top3JRA: '前三项联合命中',
  passRate: '任务通过率', casePassRate: '任务通过率', factCoverage: '事实覆盖率', citationFactCoverage: '引用事实覆盖率',
  highLevelAnswerCorrectnessRate: '回答正确率', curationPassRate: '记忆维护通过率', durableRecallRate: '持久记忆召回率', abstentionPassRate: '拒答通过率',
  highLevelFactCoverage: '回答事实覆盖率', answerableCitationSupportRate: '可回答案例引用支持率', infoNotFoundAbstentionRecall: '无答案案例拒答召回率',
  answerJudgeCorrectnessRate: '回答评分正确率', answerSuccessRate: '回答成功率', citationSuccessRate: '引用成功率',
  agentSuccessRate: 'Agent 成功率', toolSuccessRate: '工具成功率', abstentionAccuracy: '拒答准确率',
  sourceCount: '来源数', modelDecisionCount: '模型决策数', currentAtomCount: '当前记忆条数',
  governedCurrentAtomCount: '受治理的记忆条数', legalLineageCurrentAtomCount: '来源链完整的记忆条数',
  caseCount: '案例数', durableCaseCount: '持久记忆案例数', ok: '执行检查', passed: '验收检查', projectionFresh: '投影已更新',
  curationCases: '记忆维护案例数', curationPassed: '记忆维护通过数', durableRecallPassed: '持久记忆召回通过数', durableRecallTotal: '持久记忆召回案例数',
  rollbackPassed: '回滚检查', rollbackRestoredBaseline: '回滚恢复基线', replayAttempted: '已执行重放',
  replayPassed: '重放检查', replayReusedModelRequests: '重放复用模型请求',
};
const groupNames: Record<string, string> = {
  curation: '记忆维护', retrieval: '记忆检索', recovery: '恢复检查',
  baseline: '基线', skill: '技能方案', tuned: '调优方案', agentic: 'Agent 检索',
};
const fractionMetrics = new Set([
  'AnswerCoverage', 'CA', 'FA', 'JRA', 'Top3JRA', 'passRate', 'casePassRate', 'factCoverage', 'citationFactCoverage',
  'highLevelAnswerCorrectnessRate', 'curationPassRate', 'durableRecallRate', 'abstentionPassRate', 'highLevelFactCoverage',
  'answerableCitationSupportRate', 'infoNotFoundAbstentionRecall', 'answerJudgeCorrectnessRate', 'answerSuccessRate',
  'citationSuccessRate', 'agentSuccessRate', 'toolSuccessRate', 'abstentionAccuracy',
]);

export function trialMetrics(result: Record<string, unknown>): Array<{ key: string; label: string; value: string }> {
  const values: Array<{ key: string; label: string; value: string }> = [];
  const append = (name: string, value: unknown, group = '') => {
    const display = typeof value === 'number' && Number.isFinite(value) && value >= 0
      ? fractionMetrics.has(name) && value <= 1
        ? `${Number((value * 100).toFixed(2))}%` : Number(value.toFixed(4)).toLocaleString()
      : typeof value === 'boolean' ? /passed|^ok$/iu.test(name) ? value ? '通过' : '未通过' : value ? '是' : '否'
        : value === null ? '暂不可核对' : undefined;
    if (display !== undefined) values.push({ key: `${group}:${name}`, label: `${group ? `${groupNames[group] ?? group} · ` : ''}${metricNames[name] ?? name}`, value: display });
  };
  for (const [name, value] of Object.entries(object(result.metrics))) {
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      for (const [metric, amount] of Object.entries(value)) append(metric, amount, name);
    } else append(name, value);
  }
  return values;
}

export function trialCost(result: Record<string, unknown>): string | null {
  const cost = object(result.cost);
  const raw = cost.totalCostUsd ?? cost.estimatedCostUsd;
  const amount = typeof raw === 'number' || typeof raw === 'string' && /^\d+(?:\.\d+)?(?:e[+-]?\d+)?$/iu.test(raw.trim()) ? Number(raw) : NaN;
  return cost.available === true && (cost.currency === undefined || cost.currency === 'USD') && Number.isFinite(amount) && amount >= 0 ? `$${amount.toFixed(4)}` : null;
}

export function trialQuality(result: Record<string, unknown>): string {
  const verdict = result.qualityVerdict ?? object(result.signals).qualityVerdict;
  return verdict === 'pass' ? '验收通过' : verdict === 'keep' ? '验收结论：保留候选'
    : verdict === 'reject' ? '未达到验收标准' : '尚无可核对的质量结论';
}
