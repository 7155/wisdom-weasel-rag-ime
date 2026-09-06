import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowLeft, LoaderCircle, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Button, Disclosure, Field, IconButton, Input, TextArea } from '@/components/primitives';
import { goldenErrorMessage, isGoldenRejection, useGoldenWorkflow } from './api';
import { CalibrationPanel } from './Calibration';
import { CaseReview } from './CaseReview';
import { GoldenExperiment } from './Experiment';
import { formatTime } from './Shared';
import { isActiveJob, jobLabel, jobStateLabel, type GoldenAction, type GoldenCommand, type GoldenJob, type GoldenSource, type GoldenSuite } from './types';
import './GoldenWorkflow.css';

const steps = ['起草题目', '审核标准', '校准评审', '冻结与实验'];

export function GoldenWorkflow({ onClose, startNew = false }: { onClose?: () => void; startNew?: boolean }) {
  const id = useId();
  const [selectedSuiteId, setSelectedSuiteId] = useState<string | null | undefined>(startNew ? null : undefined);
  const [step, setStep] = useState(0);
  const [newGeneration, setNewGeneration] = useState(0);
  const lastSuite = useRef('');
  const workflow = useGoldenWorkflow(selectedSuiteId ?? '');
  const data = workflow.query.data;
  const suite = selectedSuiteId === null ? null : data?.suite ?? data?.items.find((item) => item.suiteId === selectedSuiteId) ?? (selectedSuiteId === undefined ? data?.items[0] : undefined) ?? null;
  const suiteId = suite?.suiteId ?? '';
  const [dirty, setDirty] = useState({ suiteId: '', review: false, calibration: false });
  const reviewDirty = dirty.suiteId === suiteId && dirty.review;
  const calibrationDirty = dirty.suiteId === suiteId && dirty.calibration;
  const hasUnsaved = reviewDirty || calibrationDirty;
  const reportDirty = useCallback((part: 'review' | 'calibration', value: boolean) => {
    setDirty((current) => ({ ...(current.suiteId === suiteId ? current : { suiteId, review: false, calibration: false }), [part]: value }));
  }, [suiteId]);
  const reportReviewDirty = useCallback((value: boolean) => reportDirty('review', value), [reportDirty]);
  const reportCalibrationDirty = useCallback((value: boolean) => reportDirty('calibration', value), [reportDirty]);
  const activeJob = suite?.jobs.find(isActiveJob);
  const lastJob = suite ? [...suite.jobs].sort((left, right) => right.updatedAtMs - left.updatedAtMs)[0] : undefined;
  const visibleJob = activeJob ?? (lastJob && ['failed', 'interrupted', 'cancelled'].includes(lastJob.state) ? lastJob : undefined);
  const commandBusy = selectedSuiteId === undefined || Boolean(workflow.pending) || workflow.mutation.isPending || !workflow.query.isFetched || workflow.query.isPending || workflow.query.isError;
  const disabled = commandBusy || Boolean(activeJob);
  useEffect(() => {
    if (startNew) { setSelectedSuiteId(null); setStep(0); }
  }, [startNew]);
  useEffect(() => {
    if (selectedSuiteId === undefined && data) setSelectedSuiteId(data.suite?.suiteId ?? data.items[0]?.suiteId ?? null);
  }, [data, selectedSuiteId]);
  useEffect(() => {
    if (!suite || suite.suiteId === lastSuite.current) return;
    lastSuite.current = suite.suiteId;
    setStep(suite.snapshot ? 3 : suite.calibration ? 2 : suite.cases.length ? 1 : 0);
  }, [suite]);
  const createNew = () => {
    setSelectedSuiteId(null); setStep(0); lastSuite.current = ''; setNewGeneration((value) => value + 1);
  };
  const submit = async (action: GoldenAction, input: GoldenCommand['input'] = {}) => {
    if (hasUnsaved && ['freeze', 'calibrate', 'draft'].includes(action)) return false;
    return Boolean(await workflow.submit(action, input, suite));
  };
  const resumeJob = async (job: GoldenJob) => {
    if (await submit('resume', { jobId: job.jobId }) && job.kind === 'draft') setStep(1);
  };
  const verifyPending = async () => {
    const command = workflow.pending?.command;
    const receipt = await workflow.retryPending();
    if (!receipt || !command) return;
    if (command.action === 'create') setSelectedSuiteId(receipt.suite.suiteId);
    if (command.action === 'resume' && receipt.suite.jobs.find((job) => job.jobId === command.input.jobId)?.kind === 'draft') setStep(1);
  };
  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>, current: number) => {
    const last = suite ? steps.length - 1 : 0;
    const target = event.key === 'ArrowRight' ? (current + 1) % (last + 1) : event.key === 'ArrowLeft' ? (current + last) % (last + 1) : event.key === 'Home' ? 0 : event.key === 'End' ? last : null;
    if (target === null) return;
    event.preventDefault(); setStep(target); document.getElementById(`${id}-tab-${target}`)?.focus();
  };
  return <section className="golden-workflow" aria-label="Golden 评测集">
    <header className="golden-header">
      <div className="golden-header__titlebar">
        {onClose ? <IconButton icon={<ArrowLeft size={15} />} label="返回实验工作区" onClick={onClose} /> : null}
        <div className="golden-header__title"><h2>{suite?.title || '新建 Golden 评测集'}</h2>{suite ? <span className="golden-count">标准版本 {suite.revision}</span> : null}</div>
        {suite ? <div className="golden-header__actions"><IconButton icon={<RefreshCw size={14} />} label="重新读取评测集" disabled={workflow.query.isFetching} onClick={() => void workflow.query.refetch()} /><IconButton icon={<Plus size={15} />} label="新建评测集" disabled={Boolean(workflow.pending)} onClick={createNew} /></div> : null}
      </div>
      {suite || data?.items.length ? <div className="golden-header__context">
        {suite ? <Disclosure className="golden-task-description" summary="任务说明"><p className="golden-preserve-text">{suite.scenario}</p></Disclosure> : <p className="golden-note">从真实来源建立可人审、可校准、可复用的评测标准。</p>}
        {data?.items.length ? <label className="golden-suite-selector"><span className="golden-visually-hidden">选择评测集</span><select value={suite?.suiteId ?? ''} disabled={Boolean(workflow.pending)} onChange={(event) => { setSelectedSuiteId(event.target.value); lastSuite.current = ''; }}><option value="" disabled>选择已有评测集</option>{data.items.map((item) => <option key={item.suiteId} value={item.suiteId}>{item.title} · v{item.revision}</option>)}</select></label> : null}
      </div> : null}
    </header>
    <div className="golden-steps" role="tablist" aria-label="Golden 工作步骤">{steps.map((label, index) => <button key={label} type="button" id={`${id}-tab-${index}`} role="tab" aria-selected={step === index} aria-controls={`${id}-panel-${index}`} tabIndex={step === index ? 0 : -1} disabled={index > 0 && !suite} onKeyDown={(event) => onTabKey(event, index)} onClick={() => setStep(index)}><span aria-hidden="true">{index + 1}</span>{label}</button>)}</div>
    {hasUnsaved ? <div className="golden-recovery" role="status" aria-label="未保存的评测标准"><div><strong>草稿已保留，尚未纳入评测标准</strong><p>{[reviewDirty ? '审核标准有未保存修改' : '', calibrationDirty ? '校准评审有未保存修改' : ''].filter(Boolean).join('；')}。请先保存修改，再校准和冻结。</p></div><div>{reviewDirty ? <Button size="small" onClick={() => setStep(1)}>返回审核标准</Button> : null}{calibrationDirty ? <Button size="small" onClick={() => setStep(2)}>返回校准评审</Button> : null}</div></div> : null}
    {workflow.query.isPending ? <p className="golden-reading" role="status">正在读取评测集…</p> : null}
    {workflow.query.isError ? <div className="golden-recovery" role="alert"><div><strong>无法读取评测集</strong><p>{goldenErrorMessage(workflow.query.error)}</p></div><Button size="small" leadingIcon={<RefreshCw size={14} />} loading={workflow.query.isFetching} onClick={() => void workflow.query.refetch()}>重新读取</Button></div> : null}
    {workflow.pending?.outcome === 'unknown' ? <div className="golden-recovery" role="alert"><div><strong>本次操作的结果尚未确认</strong><p>核对回执会复用原请求；在确认结果前，不会提交另一项操作。</p></div><Button variant="primary" size="small" onClick={() => void verifyPending()}>核对本次操作</Button></div>
      : workflow.mutation.error && isGoldenRejection(workflow.mutation.error) ? <p className="golden-command-error" role="alert">{goldenErrorMessage(workflow.mutation.error, '这次操作未被接受，已重新读取当前版本。请核对后重试。')}</p> : null}
    {workflow.pending?.outcome === 'sending' ? <p className="golden-reading" role="status">正在提交本次操作…</p> : null}
    {visibleJob ? <JobStatus job={visibleJob} stale={workflow.query.isError} disabled={commandBusy} onCancel={() => void submit('cancel', { jobId: visibleJob.jobId })} onResume={() => void resumeJob(visibleJob)} /> : null}
    <div id={`${id}-panel-0`} className="golden-panel" role="tabpanel" aria-labelledby={`${id}-tab-0`} hidden={step !== 0}>
      {suite ? <SourceSummary suite={suite} disabled={disabled || hasUnsaved} onDraft={() => void submit('draft').then((accepted) => { if (accepted) setStep(1); })} /> : <SourceForm key={newGeneration} disabled={commandBusy} onCreate={async (input) => { const receipt = await workflow.submit('create', input); if (receipt) setSelectedSuiteId(receipt.suite.suiteId); }} />}
    </div>
    {suite ? <>
        <div id={`${id}-panel-1`} className="golden-panel" role="tabpanel" aria-labelledby={`${id}-tab-1`} hidden={step !== 1}><CaseReview key={suite.suiteId} suite={suite} disabled={disabled} onDirtyChange={reportReviewDirty} onReview={(input) => submit('review_case', input)} onNext={() => setStep(2)} onDraft={() => setStep(0)} /></div>
      <div id={`${id}-panel-2`} className="golden-panel" role="tabpanel" aria-labelledby={`${id}-tab-2`} hidden={step !== 2}><CalibrationPanel key={suite.suiteId} suite={suite} disabled={disabled} onDirtyChange={reportCalibrationDirty} reviewDirty={reviewDirty} onLabel={(input) => submit('label_sample', input)} onJudge={(input) => submit('judge_config', input)} onCalibrate={() => void submit('calibrate')} onNext={() => setStep(3)} onReview={() => setStep(1)} /></div>
      <div id={`${id}-panel-3`} className="golden-panel" role="tabpanel" aria-labelledby={`${id}-tab-3`} hidden={step !== 3}><GoldenExperiment key={suite.suiteId} suite={suite} disabled={disabled} unsaved={hasUnsaved} onFreeze={() => void submit('freeze')} onExperiment={(input) => submit('experiment', input)} onReview={() => setStep(1)} onCalibrate={() => setStep(2)} /></div>
    </> : null}
  </section>;
}

function SourceForm({ disabled, onCreate }: { disabled: boolean; onCreate: (input: GoldenCommand['input']) => Promise<void> }) {
  const id = useId();
  const [title, setTitle] = useState('');
  const [scenario, setScenario] = useState('');
  const [targetCount, setTargetCount] = useState('30');
  const [sources, setSources] = useState<GoldenSource[]>(() => [emptySource()]);
  const valid = Boolean(title.trim() && scenario.trim()) && Number.isSafeInteger(Number(targetCount)) && Number(targetCount) >= 2
    && sources.length > 0 && sources.every((source) => source.title.trim() && source.uri.trim() && source.text.trim());
  const changeSource = (sourceId: string, patch: Partial<GoldenSource>) => setSources((current) => current.map((source) => source.sourceId === sourceId ? { ...source, ...patch } : source));
  return <section className="golden-section" aria-labelledby={`${id}-heading`}>
    <header className="golden-section__heading"><div><h3 id={`${id}-heading`}>起草题目</h3><p>粘贴文档、历史任务或失败记录。保留来源引用，Agent 将据此起草问题、标准、证据和校准样例。</p></div></header>
    <form className="golden-source-form" onSubmit={(event) => { event.preventDefault(); if (valid && !disabled) void onCreate({ title: title.trim(), scenario: scenario.trim(), targetCount: Number(targetCount), sources }); }}>
      <fieldset disabled={disabled}>
        <div className="golden-source-form__identity"><Field htmlFor={`${id}-title`} label="评测集名称" required><Input id={`${id}-title`} value={title} onChange={(event) => setTitle(event.target.value)} /></Field><Field htmlFor={`${id}-count`} label="计划题数"><Input id={`${id}-count`} type="number" min={2} step={1} value={targetCount} onChange={(event) => setTargetCount(event.target.value)} /></Field></div>
        <Field htmlFor={`${id}-scenario`} label="要评测的任务" required><TextArea id={`${id}-scenario`} rows={2} value={scenario} placeholder="写明 Agent 应完成什么任务，以及答案的使用场景" onChange={(event) => setScenario(event.target.value)} /></Field>
        <div className="golden-source-editors">{sources.map((source, index) => <section className="golden-source-editor" key={source.sourceId}>
          <header><h4>来源 {index + 1}</h4>{sources.length > 1 ? <IconButton icon={<Trash2 size={15} />} label={`移除来源 ${index + 1}`} onClick={() => setSources((current) => current.filter((item) => item.sourceId !== source.sourceId))} /> : null}</header>
          <div className="golden-field-row"><Field htmlFor={`${id}-source-title-${index}`} label={`来源 ${index + 1} 标题`} required><Input id={`${id}-source-title-${index}`} value={source.title} onChange={(event) => changeSource(source.sourceId, { title: event.target.value })} /></Field><Field htmlFor={`${id}-source-kind-${index}`} label={`来源 ${index + 1} 类型`}><select id={`${id}-source-kind-${index}`} value={source.kind} onChange={(event) => changeSource(source.sourceId, { kind: event.target.value as GoldenSource['kind'] })}><option value="document">文档</option><option value="history">历史任务</option><option value="failure">失败记录</option></select></Field></div>
          <Field htmlFor={`${id}-source-uri-${index}`} label={`来源 ${index + 1} 引用`} required><Input id={`${id}-source-uri-${index}`} value={source.uri} placeholder="文档链接、文件路径或原任务引用" onChange={(event) => changeSource(source.sourceId, { uri: event.target.value })} /></Field>
          <Field htmlFor={`${id}-source-text-${index}`} label={`来源 ${index + 1} 原文`} required><TextArea id={`${id}-source-text-${index}`} rows={8} value={source.text} placeholder="粘贴这份来源的真实内容" onChange={(event) => changeSource(source.sourceId, { text: event.target.value })} /></Field>
        </section>)}</div>
        <Button variant="quiet" size="small" leadingIcon={<Plus size={14} />} onClick={() => setSources((current) => [...current, emptySource()])}>添加来源</Button>
      </fieldset>
      <footer className="golden-section__footer"><p className="golden-note">保存后即可让 Agent 起草。草稿不会自动获得人类通过标签。</p><Button type="submit" variant="primary" disabled={disabled || !valid}>保存来源，建立评测集</Button></footer>
    </form>
  </section>;
}

function SourceSummary({ suite, disabled, onDraft }: { suite: GoldenSuite; disabled: boolean; onDraft: () => void }) {
  return <section className="golden-section"><header className="golden-section__heading"><div><h3>起草题目</h3><p>{suite.sources.length} 份真实来源 · 计划 {suite.targetCount} 题 · {suite.cases.length ? `已有 ${suite.cases.length} 题` : '尚未起草'}</p></div></header>
    <div className="golden-sources">{suite.sources.map((source) => <Disclosure className="golden-source-summary" key={source.sourceId} summary={<span><strong>{source.title}</strong><small>{({ document: '文档', history: '历史任务', failure: '失败记录' })[source.kind]} · {source.uri}</small></span>}><p className="golden-preserve-text">{source.text}</p></Disclosure>)}</div>
    <footer className="golden-section__footer"><p className="golden-note">{suite.cases.length ? '保留已审核题目，更新待审草案；更新后需要重新校准。' : '起草使用已配置的 Agent 模型，所有题目先进入待审核状态。'}</p><Button variant="primary" disabled={disabled} onClick={onDraft}>{suite.cases.length ? '重新起草题目' : '让 Agent 起草题目'}</Button></footer>
  </section>;
}
function JobStatus({ job, stale, disabled, onCancel, onResume }: { job: GoldenJob; stale: boolean; disabled: boolean; onCancel: () => void; onResume: () => void }) {
  const active = isActiveJob(job);
  const canReprocess = job.kind === 'draft' && job.state === 'failed' && job.canReprocess === true;
  return <section className="golden-job" aria-label="当前任务状态"><div><p role="status">{active && !stale ? <LoaderCircle aria-hidden="true" size={15} className="golden-job__spinner" /> : null}<strong>{jobLabel[job.kind]} · {jobStateLabel[job.state]}</strong><span>{formatTime(job.updatedAtMs)}</span></p><p>{stale ? '上次读取的状态，当前进展尚未确认。' : job.error || job.progress || (active ? '等待真实执行回执。' : '任务已经停止。')}</p>{canReprocess ? <p>复用原结果重新处理，不会重新调用模型。</p> : null}</div><div>{active ? <Button size="small" disabled={disabled} onClick={onCancel}>停止任务</Button> : job.state === 'interrupted' ? <Button size="small" disabled={disabled} onClick={onResume}>恢复任务</Button> : canReprocess ? <Button size="small" disabled={disabled} onClick={onResume}>重新处理结果</Button> : null}</div></section>;
}
function emptySource(): GoldenSource { return { sourceId: `source:${crypto.randomUUID()}`, title: '', kind: 'document', uri: '', text: '' }; }
