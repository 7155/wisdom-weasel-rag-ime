import { useEffect, useId, useRef, useState } from 'react';
import { Button, Disclosure } from '@/components/primitives';
import { EvidenceView, formatRate, formatTime, ModelFields } from './Shared';
import { isExperimentResult, isRunnableGoldenModel, jobStateLabel, object, verdictLabel, type CaseRun, type ExperimentResult, type ExperimentUsage, type GoldenCommand, type GoldenSource, type GoldenSuite, type PhaseReport } from './types';

export function GoldenExperiment({ suite, disabled, onFreeze, onExperiment, onReview, onCalibrate, unsaved = false }: {
  suite: GoldenSuite; disabled: boolean; onFreeze: () => void;
  onExperiment: (input: GoldenCommand['input']) => Promise<boolean>;
  onReview?: () => void; onCalibrate?: () => void;
  unsaved?: boolean;
}) {
  const id = useId();
  const answerDefaults = { ...suite.judgeConfig, prompt: '' };
  const [baseline, setBaseline] = useState(answerDefaults);
  const [candidate, setCandidate] = useState(answerDefaults);
  const previousDefaults = useRef(answerDefaults);
  const modelDefaults = JSON.stringify(answerDefaults);
  useEffect(() => {
    const previous = JSON.stringify(previousDefaults.current);
    const next = JSON.parse(modelDefaults);
    setBaseline((value) => JSON.stringify(value) === previous ? next : value);
    setCandidate((value) => JSON.stringify(value) === previous ? next : value);
    previousDefaults.current = next;
  }, [modelDefaults]);
  const [optimizePrompt, setOptimizePrompt] = useState(true);
  const [maxCandidates, setMaxCandidates] = useState(1);
  const [selectedJobId, setSelectedJobId] = useState('');
  const snapshot = suite.snapshot;
  const approved = suite.cases.filter((item) => item.review.status === 'approved');
  const developmentCount = approved.filter((item) => item.split === 'development').length;
  const holdoutCount = approved.filter((item) => item.split === 'holdout').length;
  const calibrationReady = suite.calibration?.ready && suite.calibration.suiteRevision === suite.revision;
  const currentSnapshot = snapshot?.sourceRevision === suite.revision;
  const experiments = suite.jobs.filter((job) => job.kind === 'experiment').sort((left, right) => right.createdAtMs - left.createdAtMs);
  const selectedJob = experiments.find((job) => job.jobId === selectedJobId) ?? experiments[0];
  const modelsRunnable = isRunnableGoldenModel(baseline) && isRunnableGoldenModel(candidate);
  const start = async () => {
    if (!snapshot || !modelsRunnable) return;
    if (await onExperiment({ snapshotId: snapshot.snapshotId, baseline, candidate, optimizePrompt, maxCandidates })) setSelectedJobId('');
  };
  const settings = <div className="golden-section">
    <header className="golden-section__heading"><div><h3 id={`${id}-freeze-title`}>冻结标准，再比较 Agent</h3><p>基线与候选使用同一份不可变题集。先在开发题调整 Prompt，固定候选后再评留出题。</p></div></header>
    <div className="golden-freeze">
      <div><h4>{currentSnapshot ? `已冻结快照 v${snapshot.version}` : '当前标准待冻结'}</h4><p className="golden-note">标准版本 {suite.revision} · 已通过 {developmentCount} 道开发题、{holdoutCount} 道留出题 · {calibrationReady ? '校准通过' : '需要当前版本的有效校准'}</p></div>
      <Button variant={snapshot ? 'secondary' : 'primary'} disabled={disabled || unsaved || currentSnapshot || !calibrationReady || !developmentCount || !holdoutCount} onClick={onFreeze}>{currentSnapshot ? (unsaved ? '已保存标准已冻结' : '当前标准已冻结') : '冻结当前标准'}</Button>
    </div>
    {snapshot ? <>
      <div className="golden-snapshot" aria-label="冻结快照">
        <dl><div><dt>实验使用</dt><dd>快照 v{snapshot.version}</dd></div><div><dt>标准版本</dt><dd>{snapshot.sourceRevision}</dd></div><div><dt>题目</dt><dd>{snapshot.developmentCount} 开发 · {snapshot.holdoutCount} 留出</dd></div><div><dt>冻结时间</dt><dd>{formatTime(snapshot.createdAtMs)}</dd></div></dl>
        {!currentSnapshot ? <p className="golden-note">当前标准已修改，旧快照仍保持不变。下方实验继续使用 v{snapshot.version}；如需新标准，请先校准并重新冻结。</p> : null}
        {unsaved ? <p className="golden-note">未保存的标准与评审修改不包含在此快照中。下方实验仍只使用已冻结的 v{snapshot.version}。</p> : null}
        <p className="golden-note">冻结评审：{snapshot.judgeConfig.provider} / {snapshot.judgeConfig.model} · {snapshot.judgeConfig.thinkingLevel || '默认推理'}。候选优化不会改动它。</p>
        {typeof snapshot.judgeProtocolVersion === 'string' ? <p className="golden-note">评审协议：{snapshot.judgeProtocolVersion}</p> : null}
      </div>
      <form className="golden-experiment-form" onSubmit={(event) => { event.preventDefault(); if (!disabled) void start(); }}>
        <div className="golden-model-comparison"><ModelFields label="基线" value={baseline} onChange={setBaseline} disabled={disabled} /><ModelFields label="候选" value={candidate} onChange={setCandidate} disabled={disabled} /></div>
        <div className="golden-experiment-options"><label className="golden-check"><input type="checkbox" checked={optimizePrompt} disabled={disabled} onChange={(event) => setOptimizePrompt(event.target.checked)} />基于开发题自动优化 Prompt</label>
          {optimizePrompt ? <label htmlFor={`${id}-budget`}>最多尝试<select id={`${id}-budget`} value={maxCandidates} disabled={disabled} onChange={(event) => setMaxCandidates(Number(event.target.value))}>{[1, 2, 3].map((number) => <option key={number} value={number}>{number} 个候选</option>)}</select></label> : null}
        </div>
        <div className="golden-section__footer"><p className="golden-note">本流程比较有来源的问答与 Prompt。新题集的分数不会与历史不同题目的分数混用。</p><Button type="submit" variant="primary" disabled={disabled || !modelsRunnable}>开始冻结集实验</Button></div>
      </form>
    </> : <div className="golden-empty"><h4>还没有冻结快照</h4><p>完成逐题人审和评审校准后，即可冻结同一套标准用于自动实验。</p>{!developmentCount || !holdoutCount ? onReview ? <Button size="small" onClick={onReview}>去审核题目</Button> : null : !calibrationReady && onCalibrate ? <Button size="small" onClick={onCalibrate}>去校准评审</Button> : null}</div>}
  </div>;
  const results = selectedJob ? <section className="golden-experiment-results" aria-label="实验结果">
      <header className="golden-section__heading"><div><h3>实验结果</h3><p>{formatTime(selectedJob.createdAtMs)} · {jobStateLabel[selectedJob.state]}</p></div>
        {experiments.length > 1 ? <label>查看实验<select value={selectedJob.jobId} onChange={(event) => setSelectedJobId(event.target.value)}>{experiments.map((job) => <option key={job.jobId} value={job.jobId}>{formatTime(job.createdAtMs)} · {jobStateLabel[job.state]}</option>)}</select></label> : null}
      </header>
      {selectedJob.state === 'completed' && isExperimentResult(selectedJob.result) ? <ExperimentReport result={selectedJob.result} sources={suite.sources} />
        : selectedJob.state === 'completed' ? <p role="alert" className="golden-field-error">实验结果回执不完整，尚无法比较基线与候选。请重新读取状态。</p>
          : selectedJob.state === 'running' || selectedJob.state === 'queued' ? <p className="golden-note">{selectedJob.progress || '结果将在真实执行结束后显示。'}</p>
            : <div><p className="golden-field-error">{selectedJob.error || '本次实验未完成，尚无完整比较结论。'}</p>{object(selectedJob.result).usage ? <UsageSummary usage={object(object(selectedJob.result).usage)} /> : null}</div>}
    </section> : null;
  return <section className="golden-section golden-experiment" aria-label="冻结与实验">
    {selectedJob?.state === 'completed' ? <>{results}<Disclosure className="golden-next-experiment" summary="设置下一轮实验">{settings}</Disclosure></> : <>{settings}{results}</>}
  </section>;
}

function ExperimentReport({ result, sources }: { result: ExperimentResult; sources: GoldenSource[] }) {
  const conclusion = {
    improved: '候选在本次冻结题集上有改善',
    no_improvement: '本次未观察到候选改善',
    inconclusive: '证据不足，暂不能判断改善',
  }[result.comparison.decision];
  return <div className="golden-report">
    <div className="golden-report__conclusion"><h4>{conclusion}</h4><p>开发题通过率变化 {difference(result.comparison.developmentDelta)}；留出题变化 {difference(result.comparison.holdoutDelta)}。</p>{result.comparison.improvementBasis === 'answer_cost_estimate' ? <p>成本改善依据模型目录估算，实际费用尚未完整提供。</p> : null}{result.comparison.reasons.length ? <ul>{result.comparison.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul> : null}<p className="golden-note">本次使用同一冻结快照，Golden 标准没有改变。结论只覆盖这份题集。</p></div>
    <PhaseResults title="开发题" phase={result.development} />
    <PhaseResults title="留出题" phase={result.holdout} />
    <UsageSummary usage={result.usage} title="实验总开销" />
    {result.usageByScope ? <ScopeUsage scopes={result.usageByScope} /> : null}
    <CaseComparisons title="开发题" phase={result.development} sources={sources} />
    <CaseComparisons title="留出题" phase={result.holdout} sources={sources} />
    <Disclosure className="golden-disclosure" summary="本次实际模型与候选规则"><dl className="golden-definition"><div><dt>基线</dt><dd>{result.baseline.provider} / {result.baseline.model} · {result.baseline.thinkingLevel || '默认推理'}</dd></div><div><dt>最终候选</dt><dd>{result.candidate.provider} / {result.candidate.model} · {result.candidate.thinkingLevel || '默认推理'}</dd></div><div><dt>候选 Prompt</dt><dd className="golden-preserve-text">{result.candidate.prompt || '未提供独立 Prompt'}</dd></div><div><dt>固定评审</dt><dd>{result.judgeConfig.provider} / {result.judgeConfig.model}</dd></div><div><dt>快照</dt><dd>{result.snapshotId}</dd></div></dl></Disclosure>
    <Disclosure className="golden-disclosure" summary={`运行来源（${result.receipts.length} 次调用）`}><ol className="golden-call-receipts">{result.receipts.map((receipt, index) => <li key={`${receipt.requestId}:${index}`}><strong>{receipt.stage}</strong><span>Session {receipt.sessionId || '未提供'}</span><span>回合 {receipt.turnId || '未提供'}</span></li>)}</ol></Disclosure>
  </div>;
}

function PhaseResults({ title, phase }: { title: string; phase: PhaseReport }) {
  return <section className="golden-phase" aria-label={`${title}比较`}>
    <h4>{title}</h4>
    <div className="golden-table-scroll"><table className="golden-table"><caption className="golden-visually-hidden">{title}基线与候选汇总</caption><thead><tr><th scope="col">版本</th><th scope="col">通过率</th><th scope="col">通过 / 总数</th><th scope="col">不通过</th><th scope="col">无法判定</th><th scope="col">运行错误</th></tr></thead><tbody>{([['基线', phase.baselineMetrics], ['候选', phase.candidateMetrics]] as const).map(([label, metrics]) => <tr key={label}><th scope="row">{label}</th><td>{formatRate(metrics.passRate)}</td><td>{metrics.passed} / {metrics.total}</td><td>{metrics.failed}</td><td>{metrics.uncertain}</td><td>{metrics.runtimeErrors}</td></tr>)}</tbody></table></div>
    {phase.businessCost ? <BusinessCost cost={phase.businessCost} /> : <p className="golden-note">本阶段尚未提供可比较的业务答案费用。</p>}
  </section>;
}
function CaseComparisons({ title, phase, sources }: { title: string; phase: PhaseReport; sources: GoldenSource[] }) {
  return <section className="golden-phase" aria-label={`${title}逐题差异`}>
    <h4>{title} · 逐题差异</h4>
    <div className="golden-result-cases">{phase.cases.map((item) => <details key={item.caseId}><summary><strong>{item.question}</strong><span>基线 {runVerdict(item.baseline)} · 候选 {runVerdict(item.candidate)}</span></summary><div className="golden-answer-comparison"><AnswerResult label="基线答案" run={item.baseline} sources={sources} /><AnswerResult label="候选答案" run={item.candidate} sources={sources} /></div></details>)}</div>
  </section>;
}
function runVerdict(run: CaseRun) { return run.status === 'runtime_error' ? '运行错误' : verdictLabel[run.judgment.verdict]; }
function AnswerResult({ label, run, sources }: { label: string; run: CaseRun; sources: GoldenSource[] }) {
  return <section><h5>{label} · {runVerdict(run)}</h5><p className="golden-preserve-text">{run.answer || '没有返回答案'}</p><h6>评审依据</h6><p>{run.judgment.reason || '未提供判断理由'}</p><EvidenceView evidence={run.judgment.evidence} sources={sources} /></section>;
}
function UsageSummary({ usage, title = '实际用量' }: { usage: Partial<ExperimentUsage> | Record<string, unknown>; title?: string }) {
  const metric = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN') : '未提供';
  const cost = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(4)}` : '未提供';
  return <section className="golden-usage" aria-label={title}><h4>{title}</h4><dl><div><dt>模型调用</dt><dd>{metric(usage.calls)}</dd></div><div><dt>输入 / 输出 Token</dt><dd>{metric(usage.inputTokens)} / {metric(usage.outputTokens)}</dd></div><div><dt>实际总成本</dt><dd>{usage.costComplete === true ? cost(usage.costUsd) : '未提供完整成本'}</dd></div>{usage.estimateComplete === true ? <div><dt>模型目录估算</dt><dd>{cost(usage.estimatedCostUsd)}</dd></div> : null}</dl>{usage.costComplete !== true && typeof usage.knownCostUsd === 'number' ? <p className="golden-note">已提供价格的 {metric(usage.pricedCalls)} 次调用合计 {cost(usage.knownCostUsd)}，其余调用成本未知。</p> : null}{title === '实验总开销' ? <p className="golden-note">包含全部试跑、评审与优化调用，不等于单次业务答案成本。</p> : null}</section>;
}
function BusinessCost({ cost }: { cost: NonNullable<PhaseReport['businessCost']> }) {
  if (!['actual', 'model_catalog_estimate'].includes(cost.basis)) return <p className="golden-note">业务答案费用未提供，不能据此判断节省。</p>;
  return <div className="golden-business-cost"><p>业务答案{cost.basis === 'actual' ? '实际费用' : '估算费用'}：基线 {money(cost.baselineUsd)}，候选 {money(cost.candidateUsd)}；变化 {money(cost.deltaUsd)}。</p><p className="golden-note">仅统计本阶段最终选中答案的调用。每个通过答案：基线 {money(cost.baselineCostPerSuccessUsd)}，候选 {money(cost.candidateCostPerSuccessUsd)}。{cost.basis === 'model_catalog_estimate' ? '估算来自模型目录价格。' : ''}</p></div>;
}
function ScopeUsage({ scopes }: { scopes: NonNullable<ExperimentResult['usageByScope']> }) {
  const labels = { baselineAnswers: '基线答案', candidateAnswers: '候选答案（含全部试跑）', judging: '评审开销', optimization: 'Prompt 优化开销', drafting: '起草开销', calibration: '校准开销' };
  return <Disclosure className="golden-disclosure" summary="按用途查看调用开销"><div className="golden-table-scroll"><table className="golden-table"><thead><tr><th scope="col">用途</th><th scope="col">调用</th><th scope="col">实际费用</th><th scope="col">目录估算</th></tr></thead><tbody>{(Object.keys(labels) as (keyof typeof labels)[]).filter((key) => scopes[key]).map((key) => { const usage = scopes[key]!; return <tr key={key}><th scope="row">{labels[key]}</th><td>{typeof usage.calls === 'number' ? usage.calls : '未提供'}</td><td>{usage.costComplete ? money(usage.costUsd) : '未提供完整成本'}</td><td>{usage.estimateComplete ? money(usage.estimatedCostUsd) : '未提供'}</td></tr>; })}</tbody></table></div></Disclosure>;
}
function money(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${value < 0 ? '−' : ''}$${Math.abs(value).toFixed(4)}` : '未提供'; }
function difference(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '无法比较';
  return `${value > 0 ? '+' : ''}${(value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 个百分点`;
}
