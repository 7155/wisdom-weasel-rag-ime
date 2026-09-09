export const TRACE_OPTIMIZATION_FOCUS = [
  ['tool', '工具调用'],
  ['skill', 'Skill'],
  ['prompt', '提示词'],
  ['workflow', '流程'],
  ['model', '模型'],
] as const;

export type TraceOptimizationFocus = typeof TRACE_OPTIMIZATION_FOCUS[number][0];
export interface TraceOptimizationIntent {
  mode: 'improve' | 'distill';
  scopeMode: 'all' | 'selected';
  focusAreas: TraceOptimizationFocus[];
  objective: string;
}

export function defaultTraceOptimizationIntent(objective = ''): TraceOptimizationIntent {
  return { mode: 'improve', scopeMode: 'all', focusAreas: TRACE_OPTIMIZATION_FOCUS.map(([key]) => key), objective };
}

/** A fresh value is captured before the first asynchronous start request. */
export function freezeTraceOptimizationIntent(intent: TraceOptimizationIntent): TraceOptimizationIntent {
  const focusAreas = TRACE_OPTIMIZATION_FOCUS.map(([key]) => key).filter((key) => intent.scopeMode === 'all' || intent.focusAreas.includes(key));
  if (!focusAreas.length) throw new Error('至少选择一个关注方向。');
  return { ...intent, focusAreas, objective: intent.objective.trim() };
}

export function TraceOptimizationSetup({ disabled, intent, onChange }: {
  disabled: boolean;
  intent: TraceOptimizationIntent;
  onChange: (intent: TraceOptimizationIntent) => void;
}) {
  return <section aria-label="本次任务设置" className="trace-agent-optimization-setup">
    <fieldset disabled={disabled}>
      <legend>你希望从这些记录中得到什么</legend>
      <div className="trace-agent-optimization-modes">
        <label><input checked={intent.mode === 'improve'} name="trace-optimization-mode" onChange={() => onChange({ ...intent, mode: 'improve' })} type="radio" value="improve" /><span><strong>分析并优化</strong><small>找到问题，生成候选，用相同任务检验效果。</small></span></label>
        <label><input checked={intent.mode === 'distill'} name="trace-optimization-mode" onChange={() => onChange({ ...intent, mode: 'distill' })} type="radio" value="distill" /><span><strong>从对话沉淀方法</strong><small>对照现有能力，提取可复用的 Skill、工具或经验。</small></span></label>
      </div>
    </fieldset>
    <fieldset aria-describedby="trace-focus-description" disabled={disabled}>
      <legend>关注哪些方面</legend>
      <div className="trace-agent-optimization-focus">
        <label><input checked={intent.scopeMode === 'all'} onChange={(event) => onChange({ ...intent, scopeMode: event.target.checked ? 'all' : 'selected', focusAreas: event.target.checked ? TRACE_OPTIMIZATION_FOCUS.map(([key]) => key) : [] })} type="checkbox" />全部</label>
        {TRACE_OPTIMIZATION_FOCUS.map(([key, label]) => <label key={key}><input checked={intent.focusAreas.includes(key)} onChange={(event) => onChange({ ...intent, scopeMode: 'selected', focusAreas: event.target.checked ? [...intent.focusAreas, key] : intent.focusAreas.filter((area) => area !== key) })} type="checkbox" />{label}</label>)}
      </div>
      <p id="trace-focus-description">{intent.focusAreas.length ? '按证据逐步读取；候选改动与评测受本次选择约束。' : '至少选择一个关注方向后才能开始。'}</p>
    </fieldset>
    <label className="trace-agent-optimization-objective">希望改善的结果（可选）<textarea disabled={disabled} maxLength={2000} onChange={(event) => onChange({ ...intent, objective: event.target.value })} placeholder={intent.mode === 'distill' ? '例如：把这几段对话中有效的排障步骤整理成可复用方法' : '例如：只检查这个 Skill 为什么反复重试'} rows={2} value={intent.objective} /></label>
    {disabled ? <p className="trace-agent-optimization-frozen">本轮范围已冻结。更改来源或方向时开始新一轮，已有报告保留原范围。</p> : null}
  </section>;
}
