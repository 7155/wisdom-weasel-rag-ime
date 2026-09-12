import { ArrowLeft, ArrowRight, BookOpen } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/primitives';
import type { EvalLabExperiment } from './api';

type StoryDeckProps = { experiments: readonly EvalLabExperiment[]; selectedId: string; onSelect: (id: string) => void };

/** A source-grounded result record for one Lab experiment. */
export function StoryDeck({ experiments, selectedId, onSelect }: StoryDeckProps) {
  const experiment = experiments.find((item) => item.experimentId === selectedId) ?? experiments[0];
  const [page, setPage] = useState(0);
  if (!experiment) return null;
  const factors = experiment.factors ?? [];
  const metricRows = Object.keys({ ...experiment.baseline.metrics, ...experiment.candidate.metrics }).map((key) => ({
    key,
    baseline: experiment.baseline.metrics[key],
    candidate: experiment.candidate.metrics[key],
    delta: typeof experiment.baseline.metrics[key] === 'number' && typeof experiment.candidate.metrics[key] === 'number'
      ? (experiment.candidate.metrics[key] as number) - (experiment.baseline.metrics[key] as number)
      : undefined,
  }));
  const changeGroups = ['prompt', 'tool', 'workflow', 'model', 'rag', 'memory', 'skill', 'execution_policy'];
  const factorGroups = changeGroups.map((group) => ({
    group,
    items: factors.filter((factor) => factor.name === group || factor.name.startsWith(`${group}_`)),
  }));
  const pages = [
    { title: '这次实验要解决什么', label: '问题', content: <p>{experiment.businessProblem}</p> },
    { title: '原始证据与冻结条件', label: '证据', content: <><p>{experiment.dataset.datasetId} · {experiment.dataset.caseCount} 个 Case · {experiment.dataset.split}</p><p>Baseline：{experiment.baseline.runId}<br />Candidate：{experiment.candidate.runId}</p><ul>{experiment.scoring.hardGates.map((gate) => <li key={gate}>{gate}</li>)}</ul></> },
    { title: '实际改动记录', label: '改动', content: <div className="eval-lab__change-groups">{factorGroups.map(({ group, items }) => <section aria-label={`${group} 改动`} className="eval-lab__change-group" key={group}><h4>{group}</h4>{items.length ? <ul>{items.map((factor) => <li key={`${group}-${factor.name}`}><strong>{factor.before} → {factor.after}</strong><br /><small>{factor.reason}</small></li>)}</ul> : <span>本轮未改动</span>}</section>)}</div> },
    { title: '实际指标与判定', label: '效果', content: <><div className="eval-lab__story-table-wrap"><table><thead><tr><th>指标</th><th>Baseline</th><th>Candidate</th><th>Δ</th></tr></thead><tbody>{metricRows.map((row) => <tr key={row.key}><th title={row.key}>{metricLabel(row.key)}<small className="eval-lab__metric-key">{row.key}</small></th><td>{formatMetricForKey(row.key, row.baseline)}</td><td>{formatMetricForKey(row.key, row.candidate)}</td><td className={metricDeltaClass(row.key, row.delta)}>{formatMetricForKey(row.key, row.delta, true)}</td></tr>)}</tbody></table></div><p><strong className={`eval-lab__decision eval-lab__decision--${experiment.comparison.decision}`}>{experiment.comparison.decision}</strong> {experiment.comparison.decisionReason}</p><p className="eval-lab__story-evidence">证据：{[...experiment.baseline.evidenceRefs, ...experiment.candidate.evidenceRefs].filter((ref, index, refs) => refs.indexOf(ref) === index).join(' · ') || '原始回执未提供路径'}</p></> },
    { title: '结论边界', label: '边界', content: <><p><strong>可以说：</strong>{experiment.claim.allowed}</p><p><strong>不能说：</strong>{experiment.claim.forbidden}</p></> },
  ];
  return <section aria-label="实验结果记录" className="eval-lab__story">
    <header className="eval-lab__story-header"><div><p className="eval-lab__eyebrow"><BookOpen aria-hidden="true" size={15} /> 实验结果记录</p><h2>一次实验的完整结果</h2><p>以下内容由 Lab 运行记录生成，保留原始数据、改动、指标和判定。</p></div><select aria-label="选择实验记录" value={experiment.experimentId} onChange={(event) => { onSelect(event.target.value); setPage(0); }}>{experiments.map((item) => <option key={item.experimentId} value={item.experimentId}>{item.title}</option>)}</select></header>
    <nav aria-label="实验记录" className="eval-lab__story-experiments">{experiments.map((item) => <button aria-current={item.experimentId === experiment.experimentId ? 'true' : undefined} className={item.experimentId === experiment.experimentId ? 'is-selected' : undefined} key={item.experimentId} onClick={() => { onSelect(item.experimentId); setPage(0); }} type="button"><strong>{item.title}</strong><span>{item.status} · {item.comparison.decision}</span></button>)}</nav>
    <div aria-label={`第 ${page + 1} 页，共 ${pages.length} 页`} className="eval-lab__story-progress"><span style={{ width: `${((page + 1) / pages.length) * 100}%` }} /></div>
    <article aria-live="polite" className="eval-lab__story-card" onKeyDown={(event) => { if (event.key === 'ArrowRight' && page < pages.length - 1) setPage((current) => current + 1); if (event.key === 'ArrowLeft' && page > 0) setPage((current) => current - 1); }} tabIndex={0}><div className="eval-lab__story-card-meta"><span>{experiment.experimentId}</span><strong>{experiment.status} · {experiment.comparison.decision}</strong></div><span>{page + 1} / {pages.length} · {pages[page]!.label}</span><h3>{pages[page]!.title}</h3>{pages[page]!.content}</article>
    <nav aria-label="实验结果区段" className="eval-lab__story-nav"><Button disabled={page === 0} leadingIcon={<ArrowLeft size={15} />} onClick={() => setPage((current) => current - 1)} variant="secondary">上一页</Button><div>{pages.map((item, index) => <button aria-label={`第 ${index + 1} 页：${item.label}`} aria-pressed={page === index} key={item.label} onClick={() => setPage(index)} type="button">{index + 1}</button>)}</div><Button disabled={page === pages.length - 1} onClick={() => setPage((current) => current + 1)} trailingIcon={<ArrowRight size={15} />} variant="primary">下一页</Button></nav>
  </section>;
}

function formatMetric(value: unknown, signed = false): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') {
    const formatted = Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
    return signed && value > 0 ? `+${formatted}` : formatted;
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function metricLabel(key: string): string {
  return ({
    recall: '召回率', ndcg10: 'nDCG@10', mrr: 'MRR', toolCalls: '工具调用数', failedToolCalls: '工具失败数',
    taskSuccessRate: '任务成功率', verifierPassRate: 'Verifier 通过率', latencyMs: '延迟（毫秒）',
    apiCostUsd: 'API 成本估算（美元）', vectorCoverage: '向量覆盖率', citationFactCoverage: '引用事实覆盖率',
  } as Record<string, string>)[key] ?? key;
}

function formatMetricForKey(key: string, value: unknown, signed = false): string {
  if (typeof value === 'number' && ['recall', 'ndcg10', 'taskSuccessRate', 'verifierPassRate', 'vectorCoverage', 'citationFactCoverage'].includes(key)) {
    const percentage = `${(value * 100).toFixed(2).replace(/0+$/, '').replace(/\.$/, '')}%`;
    return `${signed && value > 0 ? '+' : ''}${percentage} (${formatMetric(value, signed)})`;
  }
  return formatMetric(value, signed);
}

function metricDeltaClass(key: string, delta: unknown): string {
  if (typeof delta !== 'number' || delta === 0) return '';
  const lowerIsBetter = /(?:cost|latency|elapsed|tokens?|toolcalls|failed|error|failure)/iu.test(key);
  return (lowerIsBetter ? delta < 0 : delta > 0) ? 'is-positive' : 'is-negative';
}
