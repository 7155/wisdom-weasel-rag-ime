import type { EvalLabExperiment } from './api';

export function CandidatePatchEvidence({ experiment }: { experiment: EvalLabExperiment }) {
  const patch = experiment.optimizationEvidence?.patch;
  const available = patch?.status === 'available' && patch.unifiedDiff.trim() && patch.beforeRef && patch.afterRef;
  const factors = (experiment.factors ?? []).filter((factor) => factor.before !== factor.after);
  const factorLabel = (name: string) => ({ model: '模型', prompt: 'Prompt', tool: '工具', skill: '技能', workflow: '工作流', context: '上下文', memory_rag: '记忆与检索', guardrail: '规则约束', execution_policy: '执行策略', pricing: '价格口径', human_loop: '人工审核', baseline: '基线' } as Record<string, string>)[name] ?? name;
  return <section aria-label="候选实际差异" className="lab-candidate-patch">
    <header><h4>本轮改了什么</h4></header>
    {factors.length ? <>
      <table className="lab-candidate-patch__changes"><caption className="lab-result-summary__accessible">实验记录中的变量变化</caption><thead><tr><th scope="col">变量</th><th scope="col">原方案</th><th scope="col">候选方案</th></tr></thead><tbody>{factors.map((factor, index) => <tr key={`${factor.name}:${index}`}><th scope="row">{factorLabel(factor.name)}</th><td>{factor.before}</td><td>{factor.after}</td></tr>)}</tbody></table>
      {factors.length > 1 ? <p>本次对照包含 {factors.map((factor) => factorLabel(factor.name)).join('、')} 的组合变化，不能把全部收益归因于其中一个因素。</p> : null}
    </> : <p>实验记录未列出变量变化；请核对下方实际差异。</p>}
    <details className="lab-candidate-patch__diff"><summary>查看实际改动</summary><p>{patch?.reason || '尚未取得实际改动文件。方案记录不能代替实际差异。'}</p>
    {available ? <>
      <pre><code>{patch.unifiedDiff}</code></pre>
      <details><summary>改动来源</summary><dl><div><dt>原配置</dt><dd><code>{patch.beforeRef}</code></dd></div><div><dt>候选配置</dt><dd><code>{patch.afterRef}</code></dd></div><div><dt>文件</dt><dd><code>{patch.artifactPath}</code></dd></div></dl></details>
    </> : <p className="lab-candidate-patch__missing">真实 Diff 未记录</p>}
    </details>
  </section>;
}
