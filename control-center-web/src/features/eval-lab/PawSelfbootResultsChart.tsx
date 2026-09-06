import { useState } from 'react';
import type { EvalLabExperiment } from './api';
import { pawSelfbootDisplayMetrics, pawSelfbootRecoveryStatus } from './paw-selfboot-metrics';
import './paw-selfboot-results-chart.css';

type Point = { value: number; display: string };
type Row = { id: string; label: string; before?: Point | null; after?: Point | null; proportion?: boolean };
type View = 'quality' | 'usage' | 'recovery';

export function PawSelfbootResultsChart({ experiment }: { experiment: EvalLabExperiment }) {
  const [view, setView] = useState<View>('quality');
  const numeric = (id: string, label: string, format: (n: number) => string): Row => {
    const point = (side: 'baseline' | 'candidate') => {
      const n = experiment[side].metrics[id];
      return typeof n === 'number' && Number.isFinite(n) && n >= 0 ? { value: n, display: format(n) } : undefined;
    };
    return { id, label, before: point('baseline'), after: point('candidate') };
  };
  const count = (n: number) => n.toLocaleString('en-US');
  const money = (n: number) => `$${n.toFixed(6)}`;
  const time = (n: number) => `${n.toFixed(3)} ms`;
  const groups: Record<View, Row[]> = {
    quality: pawSelfbootDisplayMetrics(experiment).filter((m) => m.format === 'fraction').map((m) => ({ ...m, proportion: true })),
    usage: [numeric('providerCalls', '模型调用', count), numeric('totalTokens', '完整 turn tokens', count),
      numeric('estimatedApiCostUsd', '任务估算费用', money), numeric('optimizationEstimatedCostUsd', '实验与优化总投入', money),
      numeric('modelAttemptMessages', '模型响应记录（含中断）', count), numeric('observedTokens', '已观察 tokens', count),
      numeric('knownEstimatedApiCostUsd', '已知估算费用', money)],
    recovery: [numeric('cancelP95Ms', '取消收口 p95', time), numeric('restoreP95Ms', '恢复读回 p95', time)],
  };
  const titles: Record<View, string> = { quality: '验收结果', usage: '用量与费用', recovery: '取消与恢复' };
  const recoveryStates = (['baseline', 'candidate'] as const).flatMap((side) => {
    const status = pawSelfbootRecoveryStatus(experiment[side].metrics);
    return status ? [{ side, label: side === 'baseline' ? '原方案' : '本轮方案', status }] : [];
  });
  const views = (Object.keys(groups) as View[]).filter((key) => groups[key].some((r) => r.before || r.after)
    || key === 'recovery' && recoveryStates.length > 0);
  const selected = views.includes(view) ? view : views[0];
  if (!selected) return null;
  const rows = groups[selected].filter((r) => r.before || r.after);
  const paired = experiment.frozenControls.some((c) => c.name === 'comparison_scope' && c.value === 'paired');
  const partialCost = experiment.frozenControls.some((c) => c.name === 'cost_completeness' && c.value === 'partial_after_budget_stop');
  return <figure aria-label="实验结果可视化" className="paw-results-chart">
    <figcaption><strong>本轮结果</strong><div aria-label="选择结果视图" className="paw-results-chart__views">
      {views.map((key) => <button aria-pressed={selected === key} key={key} onClick={() => setView(key)} type="button">{titles[key]}</button>)}
    </div></figcaption>
    <div className="paw-results-chart__legend"><span>原方案</span><span>本轮方案</span><small>{paired ? '本轮配对记录' : '观察记录 · 不计算收益'}</small></div>
    <div className="paw-results-chart__plots">
      {rows.map((row) => {
        const maximum = row.proportion ? 1 : Math.max(row.before?.value ?? 0, row.after?.value ?? 0, Number.EPSILON);
        return <div className="paw-results-chart__metric" key={row.id}>
          <div className="paw-results-chart__metric-title"><strong>{row.label}</strong><small>{row.proportion ? '固定分母 · 满刻度 100%' : '本项独立尺度 · 从零开始'}</small></div>
          {(['before', 'after'] as const).map((side) => {
            const point = row[side]; const label = side === 'before' ? '原方案' : '本轮方案';
            return <div className={`paw-results-chart__row paw-results-chart__row--${side}`} key={side}>
              <span>{label}</span>
              {point ? <div aria-label={`${row.label}，${label} ${point.display}`} className="paw-results-chart__track" role="img">
                <i style={{ width: `${point.value / maximum * 100}%` }} />
              </div> : <div aria-label={`${label}未提供数据`} className="paw-results-chart__missing" />}
              <b>{point?.display ?? '未提供'}</b>
            </div>;
          })}
        </div>;
      })}
    </div>
    {(selected === 'quality' || selected === 'recovery') && recoveryStates.length > 0 ? <div className="paw-results-chart__recovery" aria-label="接续阶段观察">
      {recoveryStates.map(({ side, label, status }) => <p key={side}><strong>{label}</strong><span>{status}</span></p>)}
      <small>进入接续阶段和保留产物不等于完成接续任务；完整任务通过数以验收结果为准。</small>
    </div> : null}
    <p>{selected === 'quality' ? '完整任务、实现检查和重复观察分别计数；未执行的接续检查不补成零分。'
      : selected === 'usage' ? '目录价估算，非 Provider 账单。总投入包含基线、诊断与复验，不能与单次任务费用相加。'
        : rows.length > 0 ? `取消样本 ${experiment.candidate.metrics.cancelSamples ?? '未记录'}；恢复样本 ${experiment.candidate.metrics.restoreSamples ?? '未记录'}。这是进程内 owner 重建的受控测量。`
          : '这里只记录实际进入的阶段，不计算接续成功率。'}</p>
    {partialCost ? <p className="paw-results-chart__cost-note">预算中断；只展示已记录的用量和费用，未记录的在途成本未知，不能作为总额或节省。</p> : null}
  </figure>;
}
