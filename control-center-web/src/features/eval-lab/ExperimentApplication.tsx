import { Button, Disclosure } from '@/components/primitives';
import type { EvalLabExperiment } from './api';
import {
  isSceneRecipeRejection,
  sceneRecipeIdForExperiment,
  sceneRecipeRejectionMessage,
  useSceneRecipeActions,
  useSceneRecipeState,
  type SceneRecipe,
} from './scene-recipes';
import './ExperimentApplication.css';

export function ExperimentApplication({ experiment }: { experiment: Pick<EvalLabExperiment, 'experimentId'> }) {
  const sceneId = sceneRecipeIdForExperiment(experiment.experimentId);
  return sceneId ? <SceneRecipeApplication sceneId={sceneId} experimentId={experiment.experimentId} /> : (
    <section aria-label="应用候选版本" className="lab-workspace__application">
      <h3>场景版本</h3>
      <p>这个实验尚未接入场景版本管理。实验结论与原始证据可继续查看。</p>
    </section>
  );
}

function SceneRecipeApplication({ sceneId, experimentId }: { sceneId: string; experimentId: string }) {
  const query = useSceneRecipeState(sceneId, experimentId);
  const actions = useSceneRecipeActions(sceneId, experimentId);
  const state = query.data;
  const candidate = state?.candidate.version;
  const comparisonBase = state?.previousVersion ?? state?.activeVersion;
  const changes = candidate && comparisonBase ? recipeChanges(comparisonBase.recipe, candidate.recipe) : [];
  const uncertain = actions.pending?.outcome === 'unknown' ? actions.pending.command : undefined;
  const busy = actions.mutation.isPending || actions.pending?.outcome === 'sending';
  const fresh = Boolean(state) && !query.isError && !query.isFetching;

  return (
    <section aria-label="应用候选版本" className="lab-workspace__application scene-recipe">
      <h3>场景版本</h3>
      <p>用于之后的本场景验证实验。开始实验时会固定当时生效的版本。</p>
      {!state && query.isPending ? <p role="status">正在读取场景版本…</p> : null}
      {query.isError ? <div className="scene-recipe__recovery"><p role="alert">场景服务暂不可用，当前生效版本尚未确认。</p><Button loading={query.isFetching} onClick={() => void query.refetch()} size="small" variant="quiet">刷新状态</Button></div> : null}
      {state ? <>
        <div aria-label="当前生效版本" className="scene-recipe__current">
          <span>{query.isError ? '上次读取的版本' : '当前生效'}</span>
          <strong>{state.activeVersion.recipe.model}</strong>
          <span>{promptLabel(state.activeVersion.recipe.promptProfile)}</span>
        </div>
        {state.lastEvent ? <p className="scene-recipe__receipt">{state.lastEvent.operation === 'apply' ? '已应用候选' : '已返回上版'} · 场景版本 {state.revision}</p> : <p className="scene-recipe__receipt">正在使用内置版本，尚无应用记录。</p>}
        {candidate ? <>
          <h4>候选改动</h4>
          {changes.length ? <table className="scene-recipe__diff"><thead><tr><th>设置</th><th>{state.previousVersion ? '上版' : '当前'}</th><th>候选</th></tr></thead><tbody>{changes.map((change) => <tr key={change.label}><th scope="row">{change.label}</th><td>{change.before}</td><td>{change.after}</td></tr>)}</tbody></table> : <p>候选与当前版本的配置相同。</p>}
        </> : null}
        {!state.candidate.available ? <p>{state.candidate.reasonCode === 'already_active' ? '当前正在使用这个候选版本。' : state.candidate.reason || '当前候选暂不能应用。'}</p> : null}
      </> : null}
      {uncertain ? <p className="scene-recipe__operation-error" role="alert">操作结果尚未确认。重试会复用同一请求，先核对这次操作的回执。</p>
        : actions.mutation.error && isSceneRecipeRejection(actions.mutation.error) ? <p className="scene-recipe__operation-error" role="alert">{sceneRecipeRejectionMessage(actions.mutation.error)}</p> : null}
      <div className="scene-recipe__actions">
        {uncertain ? <Button loading={busy} onClick={() => actions.submit(uncertain.operation, uncertain.expectedRevision)} variant="primary">{uncertain.operation === 'apply' ? '重试应用' : '重试返回上版'}</Button> : <>
          {state?.candidate.available ? <Button disabled={!fresh} loading={busy} onClick={() => actions.submit('apply', state.revision)} variant="primary">应用到场景</Button> : null}
          {state?.rollbackAvailable ? <Button disabled={!fresh || busy} onClick={() => actions.submit('rollback', state.revision)} variant="secondary">返回上版</Button> : null}
        </>}
      </div>
      {state ? <Disclosure className="scene-recipe__details" summary="版本与运行来源">
        <dl><div><dt>当前版本</dt><dd>{state.activeVersion.versionId}</dd></div>
          {candidate?.sourceCandidateRunId ? <div><dt>候选运行</dt><dd>{candidate.sourceCandidateRunId}</dd></div> : null}
          {state.lastEvent ? <div><dt>最近操作回执</dt><dd>{state.lastEvent.eventId}</dd></div> : null}
        </dl>
        <p>证据范围仍为已观察候选的验证集，不代表独立留出集上的提升。</p>
      </Disclosure> : null}
    </section>
  );
}

function promptLabel(profile: string): string {
  return profile === 'incumbent' ? '内置证据规则' : profile === 'coverage-balanced-evidence-gate-v4' ? 'Prompt-v4 · 证据覆盖' : profile;
}

function recipeChanges(before: SceneRecipe, after: SceneRecipe) {
  const fields: Array<[keyof SceneRecipe, string]> = [
    ['provider', '服务'], ['model', '模型'], ['thinkingLevel', '推理强度'], ['promptProfile', '回答规则'],
    ['promptContractVersion', '规则版本'], ['agenticSupplementalLimit', '补充检索上限'], ['answerOnly', '答案验证'],
    ['developmentOnly', '开发验证'], ['split', '数据范围'], ['candidateAware', '已观察候选'], ['unbiasedPromotionClaimAllowed', '独立推广结论'],
  ];
  const display = (key: keyof SceneRecipe, value: SceneRecipe[keyof SceneRecipe]) => key === 'promptProfile' ? promptLabel(String(value)) : typeof value === 'boolean' ? value ? '启用' : '关闭' : String(value);
  return fields.filter(([key]) => before[key] !== after[key]).map(([key, label]) => ({ label, before: display(key, before[key]), after: display(key, after[key]) }));
}
