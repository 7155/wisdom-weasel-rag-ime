import { ArrowRight, FolderOpen, MessageSquare, Play } from 'lucide-react';
import { useCallback, useId, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Button } from '@/components/primitives';
import { useControlTransport } from '@/app/control-transport';
import type { EvalLabExperiment } from './api';
import { compileExperimentDispatch, defaultExperimentSetup, type ExperimentSetup, type OptimizationTarget } from './execution-contract';
import { SceneTrialPanel } from './trials/SceneTrialPanel';
import { SceneTrialResult, type TrialResultIdentity } from './trials/SceneTrialResult';
import './experiment-workspace.css';

type ExperimentStep = 'setup' | 'run' | 'results' | 'apply';
const STEPS = [
  ['setup', '设置实验'],
  ['run', '运行'],
  ['results', '检查结果'],
  ['apply', '应用版本'],
] as const satisfies ReadonlyArray<readonly [ExperimentStep, string]>;

type ExperimentWorkspaceProps = {
  experiment: EvalLabExperiment;
  title: string;
  scene: string;
  datasetSummary: string;
  decision: string;
  busy: boolean;
  error?: string;
  dispatchPending?: boolean;
  recovery?: ReactNode;
  selector: ReactNode;
  baseline: ReactNode;
  results: ReactNode;
  application: ReactNode;
  room: ReactNode;
  trialSceneId?: string;
  roomCount: number;
  onStart: (setup: ExperimentSetup) => Promise<void>;
  onDiscuss: () => void;
  onCreateEvaluation?: () => void;
};

/**
 * Operate surface: a white experiment notebook, with one action per stage.
 * The experiment stays central; its native Room supplies conversation and
 * authoritative running, stop, and recovery state. Historical scores never
 * imply that a new execution is running or that a candidate was applied.
 */
export function ExperimentWorkspace(props: ExperimentWorkspaceProps) {
  const transport = useControlTransport();
  const [step, setStep] = useState<ExperimentStep>('results');
  const [setup, setSetup] = useState(() => defaultExperimentSetup(props.experiment));
  const [errors, setErrors] = useState<string[]>([]);
  const [picking, setPicking] = useState(false);
  const [trialResult, setTrialResult] = useState<TrialResultIdentity | null>(null);
  const [resultView, setResultView] = useState<'comparison' | 'trial'>('comparison');
  const showingTrial = resultView === 'trial' && trialResult && props.trialSceneId;
  const selectTrial = useCallback((identity: TrialResultIdentity) => { setTrialResult(identity); setResultView('trial'); }, []);
  const id = useId();
  const historical = props.experiment.projectionState === 'history';

  function update<K extends keyof ExperimentSetup>(key: K, value: ExperimentSetup[K]) {
    setSetup((current) => ({ ...current, [key]: value }));
    setErrors([]);
  }

  function updateTarget(target: OptimizationTarget) {
    setSetup((current) => ({
      ...current,
      target,
      layer: target === 'model' ? 'configuration' : current.layer,
      allowedChanges: current.allowedChanges === defaultAllowedChanges(current.target)
        ? defaultAllowedChanges(target)
        : current.allowedChanges,
    }));
    setErrors([]);
  }

  function moveStep(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === 'ArrowRight' ? (index + 1) % STEPS.length
      : event.key === 'ArrowLeft' ? (index + STEPS.length - 1) % STEPS.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? STEPS.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    setStep(STEPS[next]![0]);
    document.getElementById(`${id}-${STEPS[next]![0]}-tab`)?.focus();
  }

  async function pickWorkspace() {
    if (!transport.pickFiles) {
      setErrors(['当前连接不能选择候选目录，请从桌面 App 打开 Lab 后重试。']);
      return;
    }
    setPicking(true);
    try {
      const picked = await transport.pickFiles({ purpose: 'workspace-root', selection: 'directory', multiple: false, maxFiles: 1 });
      if (picked[0]?.path) update('workspaceRoot', picked[0].path);
    } catch {
      setErrors(['候选目录未能读取，请重新选择。']);
    } finally {
      setPicking(false);
    }
  }

  async function start() {
    if (props.dispatchPending || props.busy) return;
    const compiled = compileExperimentDispatch(props.experiment, setup);
    if (!compiled.ok) {
      setErrors(compiled.errors);
      return;
    }
    setErrors([]);
    setStep('run');
    await props.onStart(setup);
  }

  return (
    <section aria-label="实验工作区" className="lab-workspace">
      <header className="lab-workspace__heading">
        <div>
          <h2 className="lab-workspace__accessible-title">{props.title}</h2>
          {props.selector}
          <p>{step === 'results' && showingTrial ? '所选场景验证独立于已保存实验；配置与结果见本次回执。' : props.datasetSummary}</p>
        </div>
        <div className="lab-workspace__heading-actions">
          <span className="lab-workspace__decision">{step === 'results' && showingTrial ? '单次验证' : historical ? '历史实验' : props.decision}</span>
          <Button leadingIcon={<MessageSquare size={15} />} loading={props.busy} onClick={() => { setStep('run'); props.onDiscuss(); }} variant="secondary">与 Agent 讨论</Button>
        </div>
      </header>

      <nav aria-label="实验流程" className="lab-workspace__steps" role="tablist">
        {STEPS.map(([value, label], index) => <button
          aria-controls={`${id}-${value}-panel`}
          aria-selected={step === value}
          id={`${id}-${value}-tab`}
          key={value}
          onClick={() => setStep(value)}
          onKeyDown={(event) => moveStep(event, index)}
          role="tab"
          tabIndex={step === value ? 0 : -1}
          type="button"
        ><span aria-hidden="true">{index + 1}</span>{label}</button>)}
      </nav>

      <div aria-labelledby={`${id}-${step}-tab`} className="lab-workspace__panel" id={`${id}-${step}-panel`} role="tabpanel">
        {props.error ? <p className="lab-workspace__error" role="alert">{props.error}</p> : null}
        {props.recovery}
        {step === 'setup' ? <>
          <header className="lab-workspace__section-heading"><h3>定义下一轮实验</h3><p>固定任务与基线，再设定 Agent 可以修改的范围和结束条件。</p></header>
          {historical ? <p className="lab-workspace__notice">这是只读历史实验。请选择当前实验后继续运行。</p> : null}
          <div className="lab-workspace__setup-layout">
            <form className="lab-workspace__form" onSubmit={(event) => { event.preventDefault(); void start(); }}>
              <label>优化目标<textarea disabled={historical || props.busy} onChange={(event) => update('goal', event.target.value)} rows={2} value={setup.goal} /></label>
              <fieldset disabled={historical || props.busy}>
                <legend>修改层级</legend>
                <div className="lab-workspace__layer-options">
                  <label><input checked={setup.layer === 'configuration'} name={`${id}-layer`} onChange={() => update('layer', 'configuration')} type="radio" value="configuration" /><span><strong>配置层</strong><small>模型、提示词、检索参数与技能配置</small></span></label>
                  <label><input checked={setup.layer === 'implementation'} disabled={setup.target === 'model'} name={`${id}-layer`} onChange={() => update('layer', 'implementation')} type="radio" value="implementation" /><span><strong>实现层</strong><small>工具、检索或工作流的实现代码</small></span></label>
                </div>
              </fieldset>
              <label htmlFor={`${id}-target`}>优化对象<select aria-label="优化对象" disabled={historical || props.busy} id={`${id}-target`} onChange={(event) => updateTarget(event.target.value as OptimizationTarget)} value={setup.target}>
                <option value="model">Model / 模型与成本</option>
                <option value="prompt">Prompt / 回答规则</option>
                <option value="retrieval">RAG / 检索</option>
                <option value="tool">Tool / 工具调用</option>
                <option value="skill">Skill / 技能加载</option>
                <option value="workflow">Workflow / 工作流</option>
              </select><span className="lab-workspace__field-note">每轮只针对一个对象，其他控制保持冻结，便于解释成功率和成本变化。</span></label>
              <label>允许修改的范围<textarea disabled={historical || props.busy} onChange={(event) => update('allowedChanges', event.target.value)} rows={2} value={setup.allowedChanges} /></label>
              <div className="lab-workspace__budget">
                <label>最多候选数<input disabled={historical || props.busy} min={1} onChange={(event) => update('maxCandidates', event.target.valueAsNumber)} required step={1} type="number" value={Number.isFinite(setup.maxCandidates) ? setup.maxCandidates : ''} /></label>
                <label>预算上限（美元）<input disabled={historical || props.busy} min={0.01} onChange={(event) => update('budgetUsd', event.target.valueAsNumber)} required step={0.01} type="number" value={Number.isFinite(setup.budgetUsd) ? setup.budgetUsd : ''} /></label>
              </div>
              <p className="lab-workspace__field-note">Agent 根据可读取的用量回执检查预算；当前没有系统强制扣费上限。</p>
              <label>停止条件<textarea disabled={historical || props.busy} onChange={(event) => update('stopCondition', event.target.value)} rows={2} value={setup.stopCondition} /></label>
              <div className="lab-workspace__workspace-choice">
                {transport.pickFiles ? <>
                  <span>候选工作区</span>
                  <Button disabled={historical || props.busy} leadingIcon={<FolderOpen size={15} />} loading={picking} onClick={() => void pickWorkspace()} variant="secondary">{setup.workspaceRoot ? '更换候选目录' : '选择候选目录'}</Button>
                  <p>{setup.workspaceRoot || '选择用于测试新方案的目录。运行会在其中创建隔离候选。'}</p>
                </> : <>
                  <label htmlFor={`${id}-workspace-root`}>候选目录路径</label>
                  <input autoCapitalize="none" autoComplete="off" disabled={historical || props.busy} id={`${id}-workspace-root`} onChange={(event) => update('workspaceRoot', event.target.value)} placeholder="/path/to/lab-candidates" spellCheck={false} type="text" value={setup.workspaceRoot} />
                  <p>填写所连接机器上的绝对路径。运行会在其中创建隔离候选。</p>
                </>}
              </div>
              <p className="lab-workspace__field-note">执行权限：全自动。伙伴和子 Agent 继承同一权限；本次任务的修改范围仍由上方设置限定。</p>
              {errors.length ? <ul className="lab-workspace__error" role="alert">{errors.map((error) => <li key={error}>{error}</li>)}</ul> : null}
              <div className="lab-workspace__form-actions"><Button disabled={historical || props.dispatchPending} leadingIcon={<Play size={15} />} loading={props.busy} type="submit" variant="primary">开始实验</Button><span>交给本实验的真实 Agent Room 执行</span></div>
            </form>
            <aside aria-label="固定任务与基线" className="lab-workspace__baseline">
              <h4>本轮保持不变</h4>
              <dl>
                <div><dt>任务</dt><dd>{props.experiment.businessProblem}</dd></div>
                <div><dt>数据</dt><dd>{props.experiment.vertical === 'paw-selfboot' ? props.datasetSummary : <>{props.experiment.dataset.datasetId} · {props.experiment.dataset.caseCount} 个 Case</>}</dd></div>
                <div><dt>验收</dt><dd>{props.experiment.scoring.hardGates.join('；') || '沿用当前实验的评分标准'}</dd></div>
              </dl>
              {props.baseline}
            </aside>
          </div>
        </> : null}
        {step === 'run' ? <>
          {props.trialSceneId ? <SceneTrialPanel sceneId={props.trialSceneId} onCreateEvaluation={props.onCreateEvaluation} onResultChange={selectTrial} onInspectResult={(identity) => { selectTrial(identity); setStep('results'); }} /> : null}
          <header className="lab-workspace__section-heading"><h3>与 Agent 一起优化</h3><p>在实验 Room 中诊断原因、提出修改，并核对下一轮结果。</p></header>
          {props.busy && !props.roomCount ? <p className="lab-workspace__notice" role="status">正在创建本轮实验对话并发送已设定的任务…</p> : null}
          {props.roomCount ? props.room : !props.busy ? <div className="lab-workspace__empty"><h4>尚未建立本轮优化 Room</h4><p>设置修改范围与预算后，可让 Agent 协作诊断并提出候选方案。</p><Button onClick={() => setStep('setup')} trailingIcon={<ArrowRight size={15} />} variant="primary">设置下一轮</Button></div> : null}
          <button className="lab-workspace__text-action" onClick={() => { setResultView('comparison'); setStep('results'); }} type="button">查看已保存的实验结果 <ArrowRight aria-hidden="true" size={14} /></button>
        </> : null}
        {step === 'results' ? <>
          {trialResult && props.trialSceneId ? <div className="lab-workspace__result-choice"><Button variant="secondary" size="small" onClick={() => setResultView(showingTrial ? 'comparison' : 'trial')}>{showingTrial ? '查看已保存实验对比' : '返回所选验证记录'}</Button><span>{showingTrial ? '已有对比仍使用原实验的基线与候选。' : '当前查看已保存实验；验证记录保留独立身份。'}</span></div> : null}
          {showingTrial && trialResult && props.trialSceneId ? <SceneTrialResult sceneId={props.trialSceneId} identity={trialResult} onRun={() => setStep('run')} /> : props.results}
        </> : null}
        {step === 'apply' ? <>{trialResult ? <p className="lab-workspace__notice">这里应用的是已保存实验的登记版本。所选验证记录尚未绑定可应用版本。</p> : null}{props.application}</> : null}
      </div>
    </section>
  );
}

function defaultAllowedChanges(target: OptimizationTarget): string {
  return {
    model: '只替换业务执行模型；固定推理强度、Judge、Prompt、Tool、Skill 和工作流。',
    prompt: '通用 Prompt 与证据规则；每个候选只改变一个因素。',
    retrieval: '一个 RAG 检索参数族；冻结模型、Prompt 和其余检索控制。',
    tool: 'Tool 选择、参数约束或调用顺序；保持业务权限范围不变。',
    skill: 'Skill 选择、版本或加载配置；冻结 Prompt、模型和权限。',
    workflow: '一个工作流依赖、重试或恢复边界；保持任务和权限不变。',
  }[target];
}
