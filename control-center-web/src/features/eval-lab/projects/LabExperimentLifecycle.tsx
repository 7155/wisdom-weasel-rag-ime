import { ArrowRight, CheckCircle2, CircleDot, FileText, MessageSquare, Play, RotateCcw, Target } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { Button } from '@/components/primitives';
import type { ArtifactSummary, LabProject } from './types';

type Props = {
  project: LabProject;
  onOpenArtifact: (artifactId: string) => void;
  onOpenRuns: () => void;
  onDirection: (direction: string) => void;
};
const directions = [
  ['prompt', 'Prompt 优化'], ['tool', 'Tool 优化'], ['workflow', 'MCP / Workflow 优化'],
  ['retrieval', '检索优化'], ['model', 'Model 优化'],
] as const;

const artifactFor = (artifacts: ArtifactSummary[], ...names: string[]) => artifacts.find((item) => names.some((name) => item.title.includes(name)));
const titleOf = (artifact?: ArtifactSummary) => artifact?.title ?? '尚未生成';

/**
 * The project-owned lifecycle surface. It renders the causal chain recorded by
 * Agent Lab; it does not calculate or invent metrics in the client.
 */
export function LabExperimentLifecycle({ project, onOpenArtifact, onOpenRuns, onDirection }: Props) {
  const [round, setRound] = useState(0);
  const artifacts = project.artifacts;
  const modelBinding = project.bindings.find((item) => item.ownerRef.kind === 'golden_suite');
  const records = useMemo(() => ({
    materials: artifactFor(artifacts, '冻结材料', '材料目录'),
    overview: artifactFor(artifacts, '实验总览', '评测数据'),
    metrics: artifactFor(artifacts, '指标对照', '指标'),
    changes: artifactFor(artifacts, '改动与结论', '逐步实验卡', '变更'),
    snapshot: artifactFor(artifacts, '原始评测记录', '原始运行', '聊天记录'),
    best: artifactFor(artifacts, '最优方案', '最终方案', '总结'),
    failure: artifactFor(artifacts, '失败', '诊断', '问题'),
  }), [artifacts]);
  const execution = modelBinding?.execution;
  const completed = execution?.status === 'completed' && execution.latestJob?.kind === 'experiment';
  const decision = execution?.latestJob?.decision;
  const step = (number: number, title: string, description: string, artifact?: ArtifactSummary, action?: ReactNode, statusLabel?: string) => (
    <section className="lab-lifecycle-stage" key={title}>
      <div className="lab-lifecycle-stage__index">{number}</div>
      <div className="lab-lifecycle-stage__body">
        <div className="lab-lifecycle-stage__heading"><div><h3>{title}</h3><p>{description}</p></div>{artifact ? <span className="lab-lifecycle-stage__record"><FileText size={13} />{titleOf(artifact)}</span> : statusLabel ? <span className="lab-lifecycle-stage__record"><CheckCircle2 size={13} />{statusLabel}</span> : <span className="lab-lifecycle-stage__missing">尚未记录</span>}</div>
        <div className="lab-lifecycle-stage__actions">
          {artifact ? <Button size="small" variant="secondary" onClick={() => onOpenArtifact(artifact.artifactId)}>打开真实记录<ArrowRight size={14} /></Button> : null}
          {action}
        </div>
      </div>
    </section>
  );
  return <section className="lab-lifecycle" aria-label="实验闭环">
    <header className="lab-lifecycle__header"><div><small>项目实验闭环 · 真实记录</small><h2>材料 → 评测 → 运行 → 多轮指标 → 最优方案</h2><p>每个结论都必须能回到评测集、原始运行和对应变更；客户端只展示已保存回执。</p></div><Button size="small" onClick={onOpenRuns}><Play size={14} />查看原始运行记录</Button></header>
    <div className="lab-lifecycle-chain" aria-label="实验因果链"><span>失败证据</span><ArrowRight size={14} /><span>修改假设</span><ArrowRight size={14} /><span>实际运行</span><ArrowRight size={14} /><span>指标判定</span><ArrowRight size={14} /><span>保留 / 淘汰</span></div>
    <div className="lab-lifecycle-stages">
      {step(1, '接入材料与知识库', `${project.materialCount} 份材料已接入；来源、版本和解析问题保存在材料快照中。`, records.materials, <Button size="small" variant="secondary" onClick={() => onOpenArtifact(records.materials?.artifactId ?? '')} disabled={!records.materials}>查看材料关联</Button>, records.materials ? undefined : project.materialCount ? `${project.materialCount} 份材料已冻结` : undefined)}
      {step(2, '选择或生成评测数据', '先选择“我提供评测集”或“Agent 起草评测集”，审核题目和标准后才允许产生指标。', records.overview, <div className="lab-lifecycle-source"><span>当前记录：{records.overview ? '已绑定评测回执' : completed ? '已随本轮真实运行核对' : '等待评测集'}</span></div>, !records.overview && completed ? '评测回执已进入本轮运行' : undefined)}
      {step(3, '运行基线并保留原始记录', '聊天、Tool/MCP 调用、模型配置、题集版本和终态回执必须来自同一次运行。', records.snapshot, <div className="lab-lifecycle-run-action"><Button size="small" variant="secondary" onClick={onOpenRuns}><MessageSquare size={14} />{execution?.status === 'running' || execution?.status === 'queued' ? '查看模型运行' : completed ? '查看本轮回执' : '开始真实模型运行'}</Button><span>{execution?.label ?? '尚未读取运行状态'}</span></div>, !records.snapshot && completed ? `真实运行回执 · ${execution?.label ?? '已完成'}` : undefined)}
      {step(4, `第 ${round + 1} 轮优化与指标`, '每轮只改一个主要方向；上一轮结果作为对照，指标和失败 Case 不覆盖历史。', records.metrics, <div className="lab-lifecycle-rounds"><div className="lab-lifecycle-rounds__toolbar"><Button size="small" variant="secondary" onClick={() => setRound((value) => Math.max(0, value - 1))} disabled={round === 0}><RotateCcw size={13} />上一轮</Button><span>Round {round + 1} · 与上一轮直接对照</span><Button size="small" variant="secondary" onClick={() => setRound((value) => value + 1)}>下一轮</Button></div><div className="lab-lifecycle-directions">{directions.map(([id, label]) => <Button key={id} size="small" variant="secondary" onClick={() => onDirection(label)} data-direction={id}>{label}</Button>)}</div></div>, !records.metrics && completed ? `已完成 · ${decision || '判定已记录'}` : undefined)}
      {step(5, '最优方案与完整变更链', '最终方案必须逐项说明 Prompt、Tool、MCP/Workflow、Model、检索和 Skill 从基线到当前版本的实际变化。', records.best ?? records.changes, <div className="lab-lifecycle-best"><Target size={15} />{records.best ? '已保存最优方案快照' : completed && decision === 'no_improvement' ? '本轮无提升 · 保留基线并可继续' : '尚未生成最优方案快照'}{records.best ? <Button size="small" variant="secondary" onClick={() => onOpenArtifact(records.best!.artifactId)}>打开总结</Button> : null}</div>, !records.best && !records.changes && completed ? (decision === 'no_improvement' ? '本轮无提升 · 保留基线' : '本轮判定已记录') : undefined)}
    </div>
    <section className="lab-lifecycle-causality" aria-label="失败证据与修改依据"><header><div><small>为什么做这次修改</small><h3>失败证据 → 修改方向</h3></div>{records.failure ? <Button size="small" variant="secondary" onClick={() => onOpenArtifact(records.failure!.artifactId)}>查看失败记录</Button> : null}</header><p>{records.failure?.summary ?? '当前项目还没有绑定失败证据；先完成一次基线运行，才会出现可追溯的修改依据。'}</p><div className="lab-lifecycle-causality__links"><span><CircleDot size={13} />本轮变更：{titleOf(records.changes)}</span><span><CircleDot size={13} />指标记录：{titleOf(records.metrics)}</span><span><CircleDot size={13} />原始运行：{titleOf(records.snapshot)}</span></div></section>
    <footer><CheckCircle2 size={15} />当前项目：{project.artifactCount} 份成果 · {project.bindings.length} 个执行绑定 · Round {round + 1}{completed ? ` · ${decision || '已完成'}` : ''}</footer>
  </section>;
}
