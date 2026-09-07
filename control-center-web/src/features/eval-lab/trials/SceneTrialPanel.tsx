import { CirclePause, FileText, LoaderCircle, Play, RefreshCw, Square, TriangleAlert } from 'lucide-react';
import { useEffect } from 'react';
import { Button } from '@/components/primitives';
import { activeTrial, useSceneTrials } from './api';
import { TrialOutcome, trialStateLabels as labels, type TrialResultIdentity } from './SceneTrialResult';
import './scene-trial.css';

/** Execution belongs to the trial service; the panel only projects receipts. */
export function SceneTrialPanel({ sceneId, onResultChange, onInspectResult, onCreateEvaluation }: { sceneId: string; onResultChange?: (identity: TrialResultIdentity) => void; onInspectResult?: (identity: TrialResultIdentity) => void; onCreateEvaluation?: () => void }) {
  const trials = useSceneTrials(sceneId);
  const { selectedJobId: selected, resultRequestId, model, prompt } = trials.view;
  const setSelected = (selectedJobId: string) => trials.updateView({ selectedJobId, resultRequestId: '' });
  const active = trials.jobs.find(activeTrial);
  const current = selected ? trials.jobs.find((job) => job.jobId === selected)
    : resultRequestId ? trials.jobs.find((job) => job.clientRequestId === resultRequestId) : active ?? trials.jobs[0];
  const running = Boolean(active);
  const pending = trials.pending;
  const busy = trials.mutation.isPending || pending?.outcome === 'sending';
  const pendingRequestId = resultRequestId || (!selected ? pending?.command.clientRequestId : undefined);
  const currentJobId = current?.jobId;
  useEffect(() => {
    if (pendingRequestId) onResultChange?.({ clientRequestId: pendingRequestId });
    else if (currentJobId) onResultChange?.({ jobId: currentJobId });
  }, [currentJobId, pendingRequestId, onResultChange]);
  const StatusIcon = !current ? CirclePause : activeTrial(current) ? LoaderCircle : current.state === 'completed' ? FileText : current.state === 'cancelled' ? CirclePause : TriangleAlert;

  return <section aria-label="场景验证执行" className="scene-trial">
    <header className="scene-trial__heading">
      <div><h3>验证一组配置</h3><p>使用本机登记的数据与验收规则。运行开始后，可以离开此页。</p></div>
      <Button aria-label="刷新执行状态" leadingIcon={<RefreshCw size={14} />} loading={trials.query.isFetching} onClick={() => void trials.query.refetch()} size="small" variant="quiet">刷新</Button>
    </header>
    {trials.query.isPending ? <p role="status">正在读取执行记录…</p> : null}
    {trials.query.isError ? <p className="scene-trial__error" role="alert">暂时无法读取执行状态。已有实验不会因断开连接而重新启动，请刷新核对。</p> : null}
    {!trials.query.isPending && !trials.query.isError && !trials.registered ? <div className="scene-trial__unavailable"><strong>这个场景尚未连接执行环境。</strong><p>重新运行需要连接该场景的数据、工具和评分器。已有实验记录仍可查看。</p>{onCreateEvaluation ? <Button onClick={onCreateEvaluation}>从真实资料新建评测</Button> : null}</div> : null}
    {active && current?.jobId !== active.jobId ? <div className="scene-trial__active">
      <p>{trials.query.isError ? `另一次验证的上次状态：${labels[active.state]}；当前进展尚未确认。` : `另一次验证${labels[active.state]}。`}</p>
      <Button onClick={() => setSelected(active.jobId)} size="small" variant="secondary">查看当前执行</Button>
    </div> : null}
    {current ? <>
      <div className="scene-trial__execution">
        <div className="scene-trial__state" aria-live="polite">
          <StatusIcon aria-hidden="true" className={activeTrial(current) && !trials.query.isError ? 'scene-trial__working' : undefined} size={19} />
          <div><strong>{labels[current.state]}</strong>
            {trials.query.isError ? <p>上次读取的状态，当前进展尚未确认。</p>
              : current.state === 'cancelling' ? <p>正在结束当前执行并保存回执。</p>
                : current.progress && activeTrial(current) ? <p>{current.progress}</p>
                  : current.state === 'interrupted' ? <p>原执行记录已保留。核对原记录后再决定是否新建实验。</p>
                    : current.state === 'failed' ? <p>这次执行没有产出完整结果，原执行记录已保留。</p> : null}
          </div>
        </div>
        {activeTrial(current) && current.state !== 'cancelling' ? <Button leadingIcon={<Square size={12} />} loading={trials.stop.isPending} onClick={() => trials.stop.mutate(current.jobId)} size="small" variant="secondary">停止实验</Button> : null}
      </div>
      {trials.stop.isError && trials.stop.variables === current.jobId && activeTrial(current) ? <p className="scene-trial__error" role="alert">停止结果尚未确认，请刷新状态；仍在运行时可再次停止。</p> : null}
      <TrialOutcome job={current} />
      {!activeTrial(current) && onInspectResult ? <Button onClick={() => onInspectResult({ jobId: current.jobId })} variant="primary">查看本次验证结果</Button> : null}
      <details className="scene-trial__details"><summary>执行记录{current.sessions.length ? ` · ${new Set(current.sessions.map((item) => item.sessionId)).size} 个对话` : ''}</summary>
        <dl><div><dt>实验编号</dt><dd>{current.jobId}</dd></div>
          {current.sessions.map((binding) => <div key={`${binding.sessionId}:${binding.turnId}`}><dt>{binding.turnId ? '执行轮次' : '对话已创建'}</dt><dd>{binding.sessionId}{binding.turnId ? ` · ${binding.turnId}` : ''}</dd></div>)}
        </dl>
      </details>
    </> : null}
    {pending?.outcome === 'unknown' ? <div className="scene-trial__recovery" role="alert"><p>启动结果尚未确认。核对会使用原请求，不会创建第二次实验。</p><Button loading={busy} onClick={() => trials.retryStart()} variant="primary">核对本次启动</Button></div>
      : trials.startError && !pending ? <p className="scene-trial__error" role="alert">这组设置未能启动。请检查模型与场景执行环境后重试。</p> : null}
    {trials.registered && !running && !pending ? <form className="scene-trial__form" onSubmit={(event) => {
      event.preventDefault();
      const clientRequestId = trials.start({ ...(model.trim() ? { model: model.trim() } : {}), ...(prompt.trim() && sceneId !== 'memory' ? { candidatePromptText: prompt } : {}) });
      if (clientRequestId) onResultChange?.({ clientRequestId });
    }}>
      <details><summary>模型与{sceneId === 'memory' ? '运行配置' : '提示词'}</summary>
        {sceneId === 'memory' ? <p>使用合成案例验证记忆整理与恢复流程。</p> : null}
        <label>执行模型<input autoComplete="off" onChange={(event) => trials.updateView({ model: event.target.value })} placeholder="留空使用场景默认模型" value={model} /></label>
        {sceneId !== 'memory' ? <label>候选补充提示词<textarea onChange={(event) => trials.updateView({ prompt: event.target.value })} placeholder="可选。填写这一轮需要验证的通用规则。" rows={3} value={prompt} /></label> : null}
      </details>
      <Button disabled={trials.query.isError || busy} leadingIcon={<Play size={14} />} loading={busy} type="submit" variant="primary">运行验证</Button>
    </form> : busy ? <p role="status">正在提交实验，等待启动回执…</p> : null}
    {trials.jobs.length > 1 || trials.jobs.length > 0 && !current ? <details className="scene-trial__history"><summary>此前的执行 · {trials.jobs.length} 次</summary><ol>{trials.jobs.map((job) => <li key={job.jobId}><button aria-current={current?.jobId === job.jobId ? 'true' : undefined} onClick={() => setSelected(job.jobId)} type="button"><span>{new Date(job.createdAtMs).toLocaleString()}</span><span>{labels[job.state]}</span></button></li>)}</ol></details> : null}
  </section>;
}
