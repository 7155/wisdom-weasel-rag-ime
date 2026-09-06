import { ChevronDown } from 'lucide-react';
import type { EvalLabExperiment } from './api';
import './experiment-result-summary.css';

export type ExperimentResultMetricValue = {
  /** Comparable numeric value; populations and units are resolved by the owner. */
  value: number;
  display: string;
};

export type ExperimentResultDisplayMetric = {
  id: string;
  label: string;
  before?: ExperimentResultMetricValue | null;
  after?: ExperimentResultMetricValue | null;
  /** Omit when the two measurements do not support a directional comparison. */
  direction?: 'higher' | 'lower';
  /** Numeric scale owned by the metric projection, never inferred from copy. */
  format?: 'fraction' | 'usd';
  note?: string;
  /** Exact numeric fields and population/cost scope, shown in the disclosure. */
  source?: string;
};

type ResultExperiment = Pick<EvalLabExperiment, 'comparison'>;
type ResultMetric = Omit<ExperimentResultDisplayMetric, 'before' | 'after'> & {
  before?: ExperimentResultMetricValue;
  after?: ExperimentResultMetricValue;
  change: 'improved' | 'regressed' | 'unchanged' | 'unverified';
  scaleMax?: number;
  deltaLabel: string;
};

export type ExperimentResultSummaryProps = {
  experiment: ResultExperiment;
  displayMetrics?: readonly ExperimentResultDisplayMetric[];
  qualitySummary: string;
  reliabilitySummary: string;
  efficiencySummary: string;
  boundary?: string;
};

/** Presentation only: never derive a population or cost authority from prose. */
export function projectExperimentResultSummary(
  experiment: ResultExperiment,
  displayMetrics: readonly ExperimentResultDisplayMetric[] = [],
) {
  const decision = experiment.comparison.decision;
  const title = decision === 'observation' ? '本轮验证已完成' : decision === 'keep' ? '保留这个候选'
    : decision === 'reject' ? '本轮没有可采用的改善' : '这轮还需要更多证据';
  const description = decision === 'observation' ? '展示本轮验收；未提供配对基线，不声明改善。' : decision === 'keep' ? '对照原运行，查看候选在各项指标上的变化。'
    : decision === 'reject' ? '查看未通过的任务和实际改动，再决定下一轮修改什么。'
      : '先核对原运行、候选运行和各任务的结果。';
  const metrics: ResultMetric[] = [];
  for (const metric of displayMetrics) {
    const before = readableMetricValue(metric.before);
    const after = readableMetricValue(metric.after);
    if (!metric.id.trim() || !metric.label.trim() || metrics.some((item) => item.id === metric.id)) continue;
    const comparable = before !== undefined && after !== undefined && metric.direction !== undefined;
    const change = !comparable ? 'unverified'
      : before.value === after.value ? 'unchanged'
        : (metric.direction === 'higher' ? after.value > before.value : after.value < before.value) ? 'improved' : 'regressed';
    const scaleMax = comparable && before.value >= 0 && after.value >= 0
      ? metric.format === 'fraction' && before.value <= 1 && after.value <= 1 ? 1 : metric.format === 'usd' ? Math.max(before.value, after.value) : undefined
      : undefined;
    const delta = comparable ? after.value - before.value : undefined;
    const deltaLabel = delta === undefined ? '暂不可比'
      : delta === 0 ? '持平'
        : metric.format === 'fraction' ? `${delta > 0 ? '提高' : '降低'} ${Number((Math.abs(delta) * 100).toFixed(1))} 个百分点`
          : metric.format === 'usd' ? before!.value > 0 ? `${delta < 0 ? '减少' : '增加'} ${(Math.abs(delta / before!.value) * 100).toFixed(1)}%` : `增加 $${delta.toFixed(4)}`
            : change === 'improved' ? '改善' : '下降';
    metrics.push({ ...metric, before, after, change, scaleMax, deltaLabel });
    if (metrics.length === 3) break;
  }
  return { title, description, decision, metrics };
}

function readableMetricValue(value: ExperimentResultMetricValue | null | undefined): ExperimentResultMetricValue | undefined {
  return value && Number.isFinite(value.value) && value.display.trim()
    ? { value: value.value, display: value.display }
    : undefined;
}

export function ExperimentResultSummary({
  experiment, displayMetrics, qualitySummary, reliabilitySummary, efficiencySummary, boundary,
}: ExperimentResultSummaryProps) {
  const result = projectExperimentResultSummary(experiment, displayMetrics);
  return <section aria-label="当前实验结论" className="lab-result-summary" data-decision={result.decision}>
    <header className="lab-result-summary__heading">
      <div>
        <h3>{result.title}</h3>
        <p>{boundary || result.description}</p>
      </div>
    </header>
    {result.metrics.length ? <div className="lab-result-summary__metrics"><table>
      <caption className="lab-result-summary__accessible">原运行与候选的质量、可靠性和成本比较</caption>
      <thead><tr><th scope="col">检查项</th><th scope="col">原运行</th><th scope="col">候选</th></tr></thead>
      <tbody>{result.metrics.map((metric) => <tr className="lab-result-summary__metric" data-change={metric.change} key={metric.id}>
        <th scope="row"><span>{metric.label}</span><small className="lab-result-summary__delta">{metric.deltaLabel}</small></th>
        {(['before', 'after'] as const).map((side) => <td className={`lab-result-summary__${side}`} key={side}>
          <strong data-unavailable={!metric[side] || undefined}>{metric[side]?.display ?? '未提供'}</strong>
          {metric.scaleMax !== undefined ? <span aria-hidden="true" className="lab-result-summary__bar"><span style={{ width: `${metric.scaleMax > 0 ? metric[side]!.value / metric.scaleMax * 100 : 0}%` }} /></span> : null}
        </td>)}
      </tr>)}</tbody>
    </table></div> : <p className="lab-result-summary__fallback">{qualitySummary || '暂缺可比数据'}</p>}
    {result.metrics.some((metric) => metric.id === 'api_cost') ? <p className="lab-result-summary__cost-note">{result.metrics.find((metric) => metric.id === 'api_cost')?.note || '成本范围未提供，暂不判断节省。'}</p> : null}
    <details className="lab-result-summary__method">
      <summary><span>查看完整口径</span><ChevronDown aria-hidden="true" size={16} /></summary>
      <dl>
        <div><dt>图示口径</dt><dd>每项的两条线从零开始，使用同一尺度；不同单位的线长不作比较。质量比例以 100% 为满刻度，成本以本项较大值为满刻度。缺少可比条件时不画线、不计算变化。</dd></div>
        {result.metrics.filter((metric) => metric.note).map((metric) => <div key={`note-${metric.id}`}><dt>{metric.label} · 范围</dt><dd>{metric.note}</dd></div>)}
        {result.metrics.filter((metric) => metric.source).map((metric) => <div key={metric.id}><dt>{metric.label} · 字段与分母</dt><dd className="lab-result-summary__source">{metric.source}</dd></div>)}
        <div><dt>质量</dt><dd>{qualitySummary || '暂缺可比数据'}</dd></div>
        <div><dt>可靠性</dt><dd>{reliabilitySummary || '暂缺可比数据'}</dd></div>
        <div><dt>成本与用量 · 耗时仅供观察</dt><dd>{efficiencySummary || '暂缺可比数据'}</dd></div>
      </dl>
    </details>
  </section>;
}
