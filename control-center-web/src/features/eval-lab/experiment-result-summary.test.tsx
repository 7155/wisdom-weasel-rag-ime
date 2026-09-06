import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ExperimentResultSummary, projectExperimentResultSummary, type ExperimentResultDisplayMetric } from './ExperimentResultSummary';

const kept = { comparison: { decision: 'keep', decisionReason: '候选通过本轮条件。', metricDeltas: [] } };
const metrics: ExperimentResultDisplayMetric[] = [
  { id: 'task_success', label: '任务通过', before: { value: .75, display: '3/4' }, after: { value: 1, display: '4/4' }, direction: 'higher', format: 'fraction' },
  { id: 'citation_coverage', label: '引用事实覆盖', before: { value: 7 / 9, display: '7/9' }, after: { value: 1, display: '9/9' }, direction: 'higher', format: 'fraction' },
  { id: 'api_cost', label: 'API 估算', before: { value: 2.170603, display: '$2.1706' }, after: { value: .1029376, display: '$0.1029' }, direction: 'lower', format: 'usd', note: 'Runtime 对账 · 完整四条 lane + 冻结 Judge · 非 Provider 账单' },
];

describe('Experiment result summary projection', () => {
  it('uses a full proportion scale and a shared zero cost scale only for owner-comparable values', () => {
    const values = projectExperimentResultSummary(kept, [
      { ...metrics[0], after: { value: .8, display: '80%' } },
      metrics[2],
      { ...metrics[2], id: 'unknown-cost', direction: undefined },
    ]).metrics;
    expect(values[0]).toMatchObject({ scaleMax: 1, deltaLabel: '提高 5 个百分点' });
    expect(values[1]).toMatchObject({ scaleMax: 2.170603, deltaLabel: '减少 95.3%' });
    expect(values[2].scaleMax).toBeUndefined();
    expect(values[2].deltaLabel).toBe('暂不可比');
    const zero = projectExperimentResultSummary(kept, [{ ...metrics[2], before: { value: 0, display: '$0' } }]).metrics[0];
    expect(zero.deltaLabel).toBe('增加 $0.1029');
  });

  it('preserves owner-projected populations, units, and scope without deriving them from prose', () => {
    const result = projectExperimentResultSummary(kept, metrics);
    expect(result.metrics.map(({ before, after }) => [before?.display, after?.display])).toEqual([
      ['3/4', '4/4'], ['7/9', '9/9'], ['$2.1706', '$0.1029'],
    ]);
    expect(result.metrics[2].note).toBe(metrics[2].note);
    expect(result.metrics.map(({ change }) => change)).toEqual(['improved', 'improved', 'improved']);
  });

  it('does not turn lower estimated cost into an experiment adoption decision', () => {
    const result = projectExperimentResultSummary({ comparison: { ...kept.comparison, decision: 'reject' } }, [metrics[2]]);
    expect(result.metrics[0].change).toBe('improved');
    expect(result.title).toBe('本轮没有可采用的改善');
    expect(result.decision).toBe('reject');
  });

  it('keeps missing and non-finite evidence unavailable, while preserving an observed zero', () => {
    const result = projectExperimentResultSummary(kept, [
      { id: 'partial', label: '任务通过', before: { value: Number.NaN, display: '0/4' }, after: { value: 0, display: '0/4' }, direction: 'higher' },
      { id: 'unknown', label: '引用事实覆盖', before: { value: Infinity, display: '0%' }, after: null },
    ]);
    expect(result.metrics).toHaveLength(2);
    expect(result.metrics[0].before).toBeUndefined();
    expect(result.metrics[0].after).toEqual({ value: 0, display: '0/4' });
    expect(result.metrics[0].change).toBe('unverified');
    expect(result.metrics[1].change).toBe('unverified');
    expect(projectExperimentResultSummary(kept).metrics).toEqual([]);
  });

  it('does not infer improvement when the owner has not asserted comparable direction', () => {
    const result = projectExperimentResultSummary(kept, [{ ...metrics[2], direction: undefined, note: '暂缺可比数据' }]);
    expect(result.metrics[0].change).toBe('unverified');
    expect(result.metrics[0].note).toBe('暂缺可比数据');
  });

  it('keeps missing metrics visible and exposes raw field provenance in the disclosure', () => {
    const html = renderToStaticMarkup(<ExperimentResultSummary experiment={kept} qualitySummary="" reliabilitySummary="" efficiencySummary=""
      displayMetrics={[{ id: 'task', label: '完整任务通过', source: 'taskSuccessCount / taskCount', note: '分子或有效分母未提供，暂不比较。' }]} />);
    const view = document.createElement('div');
    view.innerHTML = html;
    expect(view.querySelectorAll('strong[data-unavailable]')).toHaveLength(2);
    expect(view.querySelector('details')?.textContent).toContain('taskSuccessCount / taskCount');
    expect(view.querySelector('.lab-result-summary__metric')?.getAttribute('data-change')).toBe('unverified');
  });

  it('renders the accessible conclusion and one disclosure with every complete audit string', () => {
    const html = renderToStaticMarkup(<ExperimentResultSummary
      displayMetrics={metrics}
      efficiencySummary="API 估算 $2.1706 → $0.1029；此处保留完整成本口径。"
      experiment={kept}
      qualitySummary="任务通过 3/4 → 4/4；可回答题答案正确 1/2 → 2/2。"
      reliabilitySummary="引用门禁 未通过 → 通过。"
    />);
    const view = document.createElement('div');
    view.innerHTML = html;
    expect(view.querySelector('h3')?.textContent).toBe('保留这个候选');
    expect(view.querySelector('section')?.getAttribute('aria-label')).toBe('当前实验结论');
    expect(view.querySelectorAll('details')).toHaveLength(1);
    expect(view.querySelector('summary')?.textContent).toBe('查看完整口径');
    expect(view.querySelector('details')?.textContent).toContain('可回答题答案正确 1/2 → 2/2。');
    expect(view.querySelector('details')?.textContent).toContain('此处保留完整成本口径。');
    expect(view.querySelector('details')?.textContent).toContain('引用门禁 未通过 → 通过。');
    expect(view.querySelectorAll('button')).toHaveLength(0);
  });
});
