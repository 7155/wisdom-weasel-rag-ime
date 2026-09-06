import { Button } from '@/components/primitives';
import { activeTrial, object, useSceneTrials, type TrialJob } from './api';
import { trialCost, trialMetrics, trialQuality } from './trial-result';
import './scene-trial.css';

export type TrialResultIdentity = { jobId: string } | { clientRequestId: string };
export const trialStateLabels: Record<TrialJob['state'], string> = {
  queued: '等待执行', running: '正在运行', cancelling: '正在停止',
  completed: '已完成', failed: '执行失败', cancelled: '已停止', interrupted: '执行中断',
};

export function TrialOutcome({ job }: { job: TrialJob }) {
  const result = object(job.result), cost = trialCost(result), signals = object(result.signals);
  if (job.state !== 'completed') return !activeTrial(job) && cost ? <div className="scene-trial__result"><dl><div><dt>本次执行已记录的估算 API 成本</dt><dd>{cost}</dd></div></dl></div> : null;
  return <div className="scene-trial__result">
    <dl><div><dt>质量结论</dt><dd>{trialQuality(result)}</dd></div>
      {typeof result.caseCount === 'number' && Number.isSafeInteger(result.caseCount) && result.caseCount >= 0 ? <div><dt>验证案例</dt><dd>{result.caseCount} 个</dd></div> : null}
      {trialMetrics(result).map((metric) => <div key={metric.key}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}
      <div><dt>估算 API 成本</dt><dd>{cost ?? '暂不可核对'}</dd></div>
    </dl>
    {signals.syntheticFixture === true ? <p>本次使用合成案例，仅验证记忆流程。</p> : null}
    {signals.candidateAware === true ? <p>本次使用已参与调优的验证案例，不能代表独立评测结果。</p> : null}
    <p>{job.result ? '本次结果来自所选验证案例。与基线使用相同条件复验后，才能判断配置是否更好。' : '执行已结束，但尚无可核对的评测报告。'}</p>
  </div>;
}

/** Select an exact receipt, never substitute a previous experiment or trial. */
export function SceneTrialResult({ sceneId, identity, onRun }: { sceneId: string; identity: TrialResultIdentity; onRun: () => void }) {
  const trials = useSceneTrials(sceneId);
  const job = trials.jobs.find((item) => 'jobId' in identity ? item.jobId === identity.jobId : item.clientRequestId === identity.clientRequestId);
  const pending = 'clientRequestId' in identity && trials.pending?.command.clientRequestId === identity.clientRequestId ? trials.pending : null;
  const rejected = 'clientRequestId' in identity && trials.startFailure?.clientRequestId === identity.clientRequestId;
  const spec = object(job?.publicSpec), prompt = object(spec.candidatePrompt);
  const readText = (value: unknown) => typeof value === 'string' && value.trim() ? value : '未提供';
  return <section className="scene-trial scene-trial--record" aria-label="所选验证记录">
    <header className="scene-trial__heading"><div><h3>本次验证结果</h3><p>这是一条独立的场景验证记录。</p></div><Button size="small" variant="secondary" loading={trials.query.isFetching} onClick={() => void trials.query.refetch()}>刷新本次结果</Button></header>
    {trials.query.isError ? <p className="scene-trial__error" role="alert">读取暂时失败；仍显示这条验证的最后回执，当前进展尚未确认。</p> : null}
    {job ? <>
      <div className="scene-trial__record-identity"><strong>{trialStateLabels[job.state]}</strong><dl>
        <div><dt>验证编号</dt><dd>{job.jobId}</dd></div><div><dt>场景</dt><dd>{job.sceneId}</dd></div>
        <div><dt>启动配置模型</dt><dd>{readText(spec.model)}</dd></div><div><dt>建立时间</dt><dd>{new Date(job.createdAtMs).toLocaleString()}</dd></div>
        <div><dt>补充提示词</dt><dd>{prompt.enabled === true ? '已启用，内容身份见执行设置' : prompt.enabled === false ? '未启用' : '未提供'}</dd></div>
      </dl></div>
      {activeTrial(job) ? <p role="status">{job.progress || '尚未结束，请返回运行页查看进展或停止。'}</p> : job.state !== 'completed' ? <p className="scene-trial__error">{job.error || '这次验证未完成，原记录和已产生的回执均保留。'}</p> : null}
      <TrialOutcome job={job} />
      <div className="scene-trial__next"><strong>尚未关联同条件基线</strong><p>这条记录没有与已保存实验建立配对关系；不能把上一次实验的基线、Case 或费用当作本次验证的对照。</p><p>下一步：核对下面的实际配置与执行对话。要判断改善，需固定相同数据和评审，取得基线与候选的完整对照；问答与 Prompt 可通过“评测集”完成冻结集实验。</p></div>
      <details className="scene-trial__details"><summary>实际执行设置与对话</summary><dl>
        <div><dt>启动请求</dt><dd>{job.clientRequestId}</dd></div>
        {job.sessions.map((binding) => <div key={`${binding.sessionId}:${binding.turnId}`}><dt>{binding.turnId ? '执行轮次' : '对话已创建'}</dt><dd>{binding.sessionId}{binding.turnId ? ` · ${binding.turnId}` : ''}</dd></div>)}
      </dl><p>以下是这次启动保存的公开配置。补充提示词可能仅提供内容身份，不使用当前编辑框的草稿补全。</p><pre>{JSON.stringify(job.publicSpec, null, 2)}</pre></details>
    </> : <div className="scene-trial__next" role="status"><strong>{rejected ? '本次启动未被接受' : pending?.outcome === 'sending' ? '正在等待这次验证的启动回执' : pending ? '这次验证的启动结果尚未确认' : trials.query.isPending ? '正在读取这次验证的记录…' : '尚未找到匹配的验证记录'}</strong><p>请求或记录：{'jobId' in identity ? identity.jobId : identity.clientRequestId}</p><p>{rejected ? '没有本次执行结果。请返回运行页检查模型与场景设置；原草稿和此前的执行记录均保留。' : '刷新会核对原记录；也可返回运行页处理这次启动，不会用旧实验替代。'}</p></div>}
    <Button variant="secondary" onClick={onRun}>返回运行与历史</Button>
  </section>;
}
