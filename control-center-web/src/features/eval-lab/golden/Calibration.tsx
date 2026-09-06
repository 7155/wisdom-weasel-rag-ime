import { useEffect, useId, useState } from 'react';
import { Button, Disclosure, Field, TextArea } from '@/components/primitives';
import { EvidenceView, formatRate, ModelFields } from './Shared';
import { categoryLabel, isRunnableGoldenModel, verdictLabel, type GoldenCommand, type GoldenSuite, type Verdict } from './types';
import { SavedProgress } from './WorkflowGuide';

type SampleDraft = { answer: string; humanVerdict: Verdict | null; humanNote: string };
const sampleChanged = (draft: SampleDraft | undefined, saved: SampleDraft) => Boolean(draft && (draft.answer !== saved.answer || draft.humanVerdict !== saved.humanVerdict || draft.humanNote !== saved.humanNote));

export function CalibrationPanel({ suite, disabled, onLabel, onJudge, onCalibrate, onNext, onReview, onDirtyChange, reviewDirty = false }: {
  suite: GoldenSuite; disabled: boolean;
  onLabel: (input: GoldenCommand['input']) => Promise<boolean>;
  onJudge: (input: GoldenCommand['input']) => Promise<boolean>;
  onCalibrate: () => void; onNext: () => void; onReview?: () => void;
  onDirtyChange?: (dirty: boolean) => void; reviewDirty?: boolean;
}) {
  const id = useId();
  const development = suite.cases.filter((item) => item.split === 'development' && item.review.status === 'approved');
  const samples = development.flatMap((item) => item.samples.map((sample) => ({ item, sample, key: `${item.caseId}:${sample.sampleId}` })));
  const [selectedKey, setSelectedKey] = useState('');
  const selected = samples.find((entry) => entry.key === selectedKey) ?? samples.find((entry) => entry.sample.humanVerdict === null) ?? samples[0];
  const [drafts, setDrafts] = useState<Record<string, SampleDraft>>({});
  const sample = selected ? drafts[selected.key] ?? selected.sample : null;
  const unsavedSamples = new Set(samples.filter((entry) => sampleChanged(drafts[entry.key], entry.sample)).map((entry) => entry.key));
  const selectedDirty = selected ? unsavedSamples.has(selected.key) : false;
  const hasUnsavedSamples = unsavedSamples.size > 0;
  const [judge, setJudge] = useState(suite.judgeConfig);
  const serverJudge = JSON.stringify(suite.judgeConfig);
  useEffect(() => { setJudge(JSON.parse(serverJudge)); }, [serverJudge]);
  const judgeChanged = JSON.stringify(judge) !== serverJudge;
  const judgeRunnable = isRunnableGoldenModel(judge);
  const labelled = samples.filter((entry) => entry.sample.humanVerdict !== null);
  const categories = new Set(labelled.map((entry) => entry.sample.category));
  const humanPass = labelled.some((entry) => entry.sample.humanVerdict === 'pass');
  const humanFail = labelled.some((entry) => entry.sample.humanVerdict === 'fail');
  const missing = [
    ...(['correct', 'incorrect', 'boundary'] as const).filter((category) => !categories.has(category)).map((category) => `${categoryLabel[category]}的人类标签`),
    ...(!humanPass ? ['至少一个人类通过标签'] : []), ...(!humanFail ? ['至少一个人类不通过标签'] : []),
  ];
  const calibration = suite.calibration;
  const savedCalibrationReady = calibration?.ready && calibration.suiteRevision === suite.revision;
  const ownChanges = hasUnsavedSamples || judgeChanged;
  useEffect(() => { onDirtyChange?.(ownChanges); }, [ownChanges, onDirtyChange]);
  const pendingChanges = ownChanges || reviewDirty;
  const ready = savedCalibrationReady && !pendingChanges;
  const changeSample = (next: SampleDraft) => { if (selected) setDrafts((current) => ({ ...current, [selected.key]: next })); };
  const saveLabel = async (advance = false) => {
    if (!selected || !selectedDirty || !sample?.humanVerdict) return;
    if (await onLabel({ caseId: selected.item.caseId, sampleId: selected.sample.sampleId, answer: sample.answer, humanVerdict: sample.humanVerdict, humanNote: sample.humanNote })) {
      setDrafts((current) => {
        if (sampleChanged(current[selected.key], sample)) return current;
        const next = { ...current }; delete next[selected.key]; return next;
      });
      if (advance) {
        const next = samples.find((entry) => entry.key !== selected.key && entry.sample.humanVerdict === null);
        if (next) setSelectedKey(next.key);
      }
    }
  };

  return <section className="golden-section" aria-labelledby={`${id}-calibration-title`}>
    <header className="golden-section__heading"><div><h3 id={`${id}-calibration-title`}>让评审与人的标准对齐</h3><p>只标注已通过开发题的样例。Agent 构造的样例类别是意图，不代表你的判断。</p></div><span className="golden-count">{labelled.length} / {samples.length} 个样例标签已保存{hasUnsavedSamples ? ` · ${unsavedSamples.size} 个待保存` : ''}</span></header>
    {samples.length ? <SavedProgress label="答案标注已保存" value={labelled.length} total={samples.length} /> : null}
    {!samples.length ? <div className="golden-empty"><h4>还没有可校准的样例</h4><p>先审核通过开发题；每题的正确、错误和边界样例会在这里等待人类标注。</p>{onReview ? <Button size="small" onClick={onReview}>去审核开发题</Button> : null}</div> : <div className="golden-notebook">
      <aside className="golden-case-list" aria-label="校准样例列表"><ol>{samples.map((entry) => {
        const dirty = unsavedSamples.has(entry.key);
        const visibleSample = dirty ? drafts[entry.key] : entry.sample;
        return <li key={entry.key}><button type="button" aria-current={entry.key === selected?.key ? 'true' : undefined} onClick={() => setSelectedKey(entry.key)}>
          <span><strong>{entry.item.question}</strong><small>{categoryLabel[entry.sample.category]} · {visibleSample.humanVerdict ? `人类：${verdictLabel[visibleSample.humanVerdict]}` : '待人类标注'}{dirty ? ' · 未保存修改' : ''}</small></span>
        </button></li>;
      })}</ol></aside>
      {selected && sample ? <form className="golden-sample-editor" onSubmit={(event) => { event.preventDefault(); if (!disabled) void saveLabel(); }}>
        <h4>{selected.item.question}</h4>
        <p className="golden-note">Agent 构造意图：{categoryLabel[selected.sample.category]}</p>
        <Disclosure className="golden-disclosure golden-review-reference" defaultOpen summary="查看本题标准和引用"><h5>必须回答的事实</h5>{selected.item.requiredFacts.length ? <ul>{selected.item.requiredFacts.map((fact, index) => <li key={index}>{fact}</li>)}</ul> : <p className="golden-note">本题未列出必要事实。</p>}<h5>通过标准</h5><ul>{selected.item.rubric.map((rule, index) => <li key={index}>{rule}</li>)}</ul><EvidenceView evidence={selected.item.evidence} sources={suite.sources} /></Disclosure>
        <fieldset disabled={disabled}>
          <Field htmlFor={`${id}-answer`} label="待标注答案"><TextArea id={`${id}-answer`} rows={6} value={sample.answer} onChange={(event) => changeSample({ ...sample, answer: event.target.value })} /></Field>
          <fieldset className="golden-human-label"><legend>你的判断</legend>{(['pass', 'fail', 'uncertain'] as const).map((verdict) => <label key={verdict}><input type="radio" name={`${id}-verdict`} value={verdict} checked={sample.humanVerdict === verdict} onChange={() => changeSample({ ...sample, humanVerdict: verdict })} />{verdictLabel[verdict]}</label>)}</fieldset>
          <Field htmlFor={`${id}-note`} label="标注说明"><TextArea id={`${id}-note`} rows={2} value={sample.humanNote} onChange={(event) => changeSample({ ...sample, humanNote: event.target.value })} /></Field>
        </fieldset>
        {selectedDirty ? <p className="golden-note" role="status">本样例的修改尚未保存，请先保存人类标签。</p> : null}
        <div className="golden-editor-actions"><Button type="submit" disabled={disabled || !selectedDirty || !sample.humanVerdict || !sample.answer.trim()}>保存人类标签</Button>{samples.some((entry) => entry.key !== selected.key && entry.sample.humanVerdict === null) ? <Button variant="primary" disabled={disabled || !selectedDirty || !sample.humanVerdict || !sample.answer.trim()} onClick={() => void saveLabel(true)}>保存并看下一条</Button> : null}</div>
      </form> : null}
    </div>}
    <div className="golden-calibration-config">
      <ModelFields label="评审" value={judge} onChange={setJudge} disabled={disabled} />
      {judgeChanged ? <div className="golden-inline-action"><p className="golden-note">保存新设置后，需重新校准。</p><Button disabled={disabled || !judgeRunnable} onClick={() => void onJudge({ judgeConfig: judge })}>保存评审设置</Button></div> : null}
      <div className="golden-section__footer golden-action-bar"><div>{hasUnsavedSamples ? <p className="golden-note" role="status">{unsavedSamples.size} 个样例有未保存修改，请逐一保存人类标签后再校准。</p> : missing.length ? <p className="golden-note">还需：{missing.join('、')}。</p> : <p className="golden-note">标签已满足要求。点击后会调用评审模型，检查是否误放行或无法判定。</p>}</div><Button variant="primary" disabled={disabled || !judgeRunnable || pendingChanges || missing.length > 0} onClick={onCalibrate}>{calibration ? '重新校准评审' : '开始校准评审'}</Button></div>
    </div>
    {calibration ? <section className="golden-calibration-result" aria-label="校准结果">
      <header><h4>{pendingChanges ? '当前修改尚未校准' : ready ? '校准通过，可以冻结' : '校准尚未通过'}</h4><span className="golden-count">标准版本 {calibration.suiteRevision}</span></header>
      {pendingChanges ? <p className="golden-note">下方仅为已保存标准与标签的校准结果。请先保存修改并重新校准。</p> : null}
      <p>一致率 {formatRate(calibration.metrics.agreement)}，基于 {calibration.metrics.comparable} 个可比较标签；误通过 {calibration.metrics.falsePasses} 个，误拒绝 {calibration.metrics.falseFails} 个，无法判定 {calibration.metrics.uncertain} 个。</p>
      {calibration.suiteRevision !== suite.revision ? <p className="golden-field-error">标准或标签已修改，请重新校准。</p> : null}
      {calibration.reasons.length ? <ul>{calibration.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul> : null}
      <p className="golden-note">小样本的一致率只说明这些已标注样例；不代表所有任务上的评审质量。人类“无法判定”标签不计入通过与否的一致率。</p>
      <div className="golden-judgments">{calibration.judgments.map((judgment) => {
        const item = suite.cases.find((item) => item.caseId === judgment.caseId);
        const sample = item?.samples.find((sample) => sample.sampleId === judgment.sampleId);
        return <details key={`${judgment.caseId}:${judgment.sampleId}`}><summary><span>{item?.question ?? '题目不可用'}</span><span>人类：{sample?.humanVerdict ? verdictLabel[sample.humanVerdict] : '未标注'} · 评审：{verdictLabel[judgment.verdict]}</span></summary><p>{judgment.reason}</p><EvidenceView evidence={judgment.evidence} sources={suite.sources} /></details>;
      })}</div>
      {savedCalibrationReady ? <div className="golden-section__footer golden-action-bar"><p className="golden-ready">评审已与这些标签对齐，可以进入模型对比。</p><Button variant="primary" disabled={disabled || pendingChanges} onClick={onNext}>继续冻结与实验</Button></div> : null}
    </section> : null}
  </section>;
}
