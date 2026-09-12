import { ArrowLeft, ArrowUpRight, CheckCircle2, CircleAlert, FileText, FolderOpen, History, LoaderCircle, MessageSquare, PanelLeftClose, PanelLeftOpen, Plus, RefreshCw, Upload } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useControlTransport } from '@/app/control-transport';
import { Button, IconButton } from '@/components/primitives';
import { GoldenWorkflow } from '../golden/GoldenWorkflow';
import { SceneTrialPanel } from '../trials/SceneTrialPanel';
import { ArtifactSurface, type ArtifactDraft } from './ArtifactSurface';
import { projectError, useLabArtifact, useLabProjects } from './api';
import { initialProjectMessage, pendingProjectMessages, ProjectGuide, retainProjectMessage, sendProjectGuideMessage, type PendingProjectMessage } from './ProjectGuide';
import { readArtifactDrafts, writeArtifactDrafts } from './drafts';
import { LabAppDelivery } from './LabAppDelivery';
import { LabKnowledge } from './LabKnowledge';
import { LabExperimentLifecycle } from './LabExperimentLifecycle';
import { defaultProjectView, readProjectViews, writeProjectViews, type ProjectPage, type ProjectView } from './views';
import { object, type ArtifactAction, type JsonValue, type LabBinding, type LabBindingExecution, type LabProject, type LabProjectLatestRecord, type LabProjectNextAction, type LabProjectSummary, type LabProjectWorkState, type ProjectReceipt } from './types';
import './lab-project-workbench.css';

type Intake = { sourceId?: string; title: string; kind?: string; text: string };
type ProjectHomeProjection = { workState: LabProjectWorkState; nextAction: LabProjectNextAction; latestRecord: LabProjectLatestRecord | null; rerunReadiness: { status: 'ready' | 'not_ready'; reason: string; missing: string[] } };

function projectHomeProjection(item: LabProjectSummary): ProjectHomeProjection {
  if (item.workState && item.nextAction && item.rerunReadiness) {
    return { workState: item.workState, nextAction: item.nextAction, rerunReadiness: item.rerunReadiness, latestRecord: item.latestRecord ?? null };
  }
  const historical = Boolean(item.historyOrigin);
  const missing = item.materialCount === 0 ? ['当前材料快照'] : ['执行绑定'];
  const workState: LabProjectWorkState = historical && item.materialCount === 0
    ? { status: 'history_only', label: '历史结果', reason: '这是迁移的历史记录，可以查看，但当前材料尚未确认可复跑。' }
    : item.materialCount === 0
      ? { status: 'draft', label: '待接入材料', reason: '项目还没有可用于验证的当前材料。' }
      : { status: 'needs_binding', label: '待连接执行', reason: '材料已保存，但执行绑定尚未从项目摘要中确认。' };
  const nextAction: LabProjectNextAction = historical
    ? { kind: 'prepare_rerun', label: '准备复跑', reason: '先绑定当前数据与执行环境。' }
    : item.materialCount === 0
      ? { kind: 'add_materials', label: '添加材料', reason: '上传、粘贴或连接执行器上的材料。' }
      : { kind: 'bind_execution', label: '连接执行', reason: '选择已登记的评测或运行适配器。' };
  const latestRecord = item.latestRecord ?? (historical ? { kind: 'history', status: 'historical', title: '历史实验快照', updatedAtMs: item.updatedAtMs, artifactId: item.historyOrigin?.snapshotArtifactId ?? '' } : item.artifactCount > 0 ? { kind: 'artifact', status: 'available', title: '已有成果', updatedAtMs: item.updatedAtMs, artifactId: '' } : null);
  return { workState, nextAction, latestRecord, rerunReadiness: { status: missing.length ? 'not_ready' : 'ready', reason: missing.join('；'), missing } };
}

function ProjectList({ items, onOpen }: { items: LabProjectSummary[]; onOpen: (projectId: string) => void }) {
  return <div className="lab-project-list__items">{items.map((item) => {
    const projection = projectHomeProjection(item);
    return <button key={item.projectId} onClick={() => onOpen(item.projectId)} className="lab-project-list__item" aria-label={`${item.title}，${projection.workState.label}`}>
      <span className="lab-project-list__icon"><FolderOpen size={20} /></span>
      <span className="lab-project-list__item-body"><strong>{item.title}</strong><small>{projection.workState.label} · {projection.latestRecord ? `${projection.latestRecord.title} · ` : ''}{item.artifactCount} 份成果 · {item.materialCount} 份材料</small><em>{projection.nextAction.label} · {projection.nextAction.reason}</em></span>
      <ArrowUpRight size={17} />
    </button>;
  })}</div>;
}

function attentionPage(kind: LabProjectNextAction['kind']): ProjectPage {
  if (kind === 'add_materials' || kind === 'fix_materials') return 'materials';
  if (kind === 'review_latest') return 'artifact';
  return 'lifecycle';
}

function ProjectAttention({ items, onOpen }: { items: LabProjectSummary[]; onOpen: (projectId: string, page?: ProjectPage) => void }) {
  const attention = items.filter((item) => ['blocked', 'draft', 'needs_binding', 'history_only'].includes(projectHomeProjection(item).workState.status)).slice(0, 3);
  if (!attention.length) return <p className="lab-project-muted">当前没有需要处理的项目。可以从最近项目继续核对，或新建一项工作。</p>;
  return <div className="lab-project-attention">{attention.map((item) => {
    const projection = projectHomeProjection(item);
    return <button key={item.projectId} onClick={() => onOpen(item.projectId, attentionPage(projection.nextAction.kind))} className="lab-project-attention__item"><span><strong>{item.title}</strong><small>{projection.workState.reason}</small></span><b>{projection.nextAction.label}<ArrowUpRight size={15} /></b></button>;
  })}</div>;
}

function BindingExecutionStatus({ execution }: { execution?: LabBindingExecution }) {
  if (!execution) return <small className="lab-binding-execution lab-binding-execution--unknown">读取运行状态中…</small>;
  const Icon = execution.status === 'running' || execution.status === 'queued' ? LoaderCircle
    : execution.status === 'completed' ? CheckCircle2 : execution.status === 'failed' || execution.status === 'interrupted' ? CircleAlert : null;
  return <small className={`lab-binding-execution lab-binding-execution--${execution.status}`}>
    {Icon ? <Icon size={13} aria-hidden="true" className={execution.status === 'running' ? 'lab-binding-execution__spin' : undefined} /> : null}
    <strong>{execution.label}</strong><span>{execution.reason}</span>
  </small>;
}

function ProjectBindingList({ bindings, onOpen }: { bindings: LabBinding[]; onOpen: (binding: LabBinding) => void }) {
  return <section className="lab-project-bindings" aria-label="真实模型运行与优化">
    <header className="lab-project-bindings__header"><div><small>执行回执</small><h2>模型运行与下一轮优化</h2><p>这里的状态来自 Golden/Pi 或场景执行器的真实回执。进入后才能开始模型调用、查看逐题结果和提交下一轮候选。</p></div><span>{bindings.length} 个绑定</span></header>
    {bindings.map((item) => <button className="lab-project-binding" key={item.bindingId} onClick={() => onOpen(item)}>
      <span><strong>{item.adapterId === 'golden.context_qa' ? '资料问答评测' : item.adapterId === 'golden.knowledge_qa' ? '知识库回答评测' : item.adapterId === 'scene.trial' ? '场景验证' : item.adapterId}</strong><small>{item.execution?.status === 'completed' ? `真实模型运行已完成${item.execution.latestJob?.decision ? ` · ${item.execution.latestJob.decision}` : ''}` : item.summary || '进入执行器'}</small><BindingExecutionStatus execution={item.execution} /></span><ArrowUpRight size={18} />
    </button>)}
  </section>;
}

export function LabProjectWorkbench({ initialProjectId = '', onOpenHistory, onProjectSelect }: { initialProjectId?: string; onOpenHistory?: () => void; onProjectSelect?: (id: string) => void }) {
  const transport = useControlTransport(); const [projectId, setProjectId] = useState(initialProjectId);
  const currentProjectId = useRef(projectId); currentProjectId.current = projectId;
  const workflow = useLabProjects(projectId); const project = workflow.project.data?.project;
  const [views, setViews] = useState<Record<string, ProjectView>>(() => readProjectViews(workflow.connection)); const viewsRef = useRef(views);
  const projectDefaultView = { ...defaultProjectView, guideOpen:project?.workspace.layout !== 'focus' };
  const view = views[projectId] ?? projectDefaultView; const { page, guideOpen } = view;
  const [drafts, setDrafts] = useState<Record<string, ArtifactDraft>>(() => readArtifactDrafts(workflow.connection));
  const draftsRef = useRef(drafts);
  const [notice, setNotice] = useState(''); const [sending, setSending] = useState(false);
  const [historyImportOpen, setHistoryImportOpen] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [pendingMessages, setPendingMessages] = useState<PendingProjectMessage[]>([]);
  const [draftRequest, setDraftRequest] = useState<{ id: number; text: string }>();
  const [stagedAction, setStagedAction] = useState<{ text: string; title: string }>();
  const binding = project?.bindings.find((item) => item.bindingId === view.bindingId); const [intakeOpen, setIntakeOpen] = useState(false);
  const restored = useRef(''); const selectionKey = `paw.lab.project-selection.v1:${workflow.connection}`;
  const updateView = (patch: Partial<ProjectView>) => {
    const next = { ...viewsRef.current, [projectId]: { ...(viewsRef.current[projectId] ?? projectDefaultView), ...patch } };
    viewsRef.current = next; setViews(next);
    if (!writeProjectViews(workflow.connection, next)) setNotice('当前浏览器未能保存查看位置，已保存的项目和运行不受影响。');
  };
  const setPage = (next: ProjectPage) => updateView({ page:next });
  const setGuideOpen = (next: boolean | ((current: boolean) => boolean)) => updateView({ guideOpen:typeof next === 'function' ? next(viewsRef.current[projectId]?.guideOpen ?? projectDefaultView.guideOpen) : next });
  const setBinding = (next?: LabBinding) => updateView({ bindingId:next?.bindingId });
  const updateDraft = (key: string, draft?: ArtifactDraft) => {
    const next = { ...draftsRef.current }; if (draft) next[key] = draft; else delete next[key];
    draftsRef.current = next; setDrafts(next);
    if (!writeArtifactDrafts(workflow.connection, next)) setNotice('浏览器暂时无法保存草稿；本窗口仍保留输入，请先保存成果再关闭。');
  };
  useEffect(() => {
    if (restored.current === workflow.connection) return;
    restored.current = workflow.connection;
    const savedDrafts = readArtifactDrafts(workflow.connection); draftsRef.current = savedDrafts; setDrafts(savedDrafts);
    const savedViews = readProjectViews(workflow.connection); viewsRef.current = savedViews; setViews(savedViews);
    if (initialProjectId) return;
    try { setProjectId(localStorage.getItem(selectionKey) ?? ''); } catch { /* Start at the project list. */ }
  }, [workflow.connection, initialProjectId, selectionKey]);
  useEffect(() => { if (initialProjectId) setProjectId(initialProjectId); }, [initialProjectId]);
  useEffect(() => { setPendingMessages(project ? pendingProjectMessages(transport, project) : []); }, [transport, project?.projectId, project?.guideSessionId]);
  const openProject = (id: string, targetPage?: ProjectPage) => {
    if (targetPage) {
      const next = { ...viewsRef.current, [id]: { ...(viewsRef.current[id] ?? defaultProjectView), page: targetPage } };
      viewsRef.current = next; setViews(next);
      if (!writeProjectViews(workflow.connection, next)) setNotice('当前浏览器未能保存查看位置，已保存的项目和运行不受影响。');
    }
    setProjectId(id); setNotice(''); setStagedAction(undefined);
    try { if (id) localStorage.setItem(selectionKey, id); else localStorage.removeItem(selectionKey); } catch { /* The current view remains usable. */ }
    onProjectSelect?.(id);
  };
  const selectedId = project ? view.artifactId ?? project.workspace.primaryArtifactId : '';
  const selected = project?.artifacts.find((item) => item.artifactId === selectedId);
  const artifact = useLabArtifact(projectId, selected?.artifactId ?? '', selected?.revision);
  const draftKey = `${workflow.connection}:${projectId}:${selectedId}`;
  const busy = Boolean(workflow.pending) || workflow.mutation.isPending;
  const activeError = workflow.mutation.error ?? workflow.project.error ?? workflow.catalog.error;
  const refresh = () => { void workflow.catalog.refetch(); if (projectId) void workflow.project.refetch(); };
  const start = async (current: LabProject) => {
    setSending(true); setNotice('');
    try { await sendProjectGuideMessage(transport, current, initialProjectMessage, `lab-project-start:${current.projectId}`); }
    catch (error) { setNotice(projectError(error, '消息未完成，已保留在项目对话中。')); }
    finally { setSending(false); if (currentProjectId.current === current.projectId) setPendingMessages(pendingProjectMessages(transport, current)); }
  };
  const created = async (receipt?: ProjectReceipt) => {
    if (!receipt) return;
    setNewProjectOpen(false);
    try { sessionStorage.removeItem(`paw.lab.new-project.v1:${workflow.connection}`); } catch { /* The created project is already durable. */ }
    openProject(receipt.project.projectId);
    if (receipt.project.guideSessionId) await start(receipt.project);
  };
  const ensureGuide = async () => {
    if (!project) return;
    const receipt = await workflow.submit('ensure_guide', {}, project);
    if (receipt) await start(receipt.project);
  };
  const sendOptimizationDirection = async (direction: string) => {
    if (!project || sending) return;
    setSending(true); setGuideOpen(true); setNotice('');
    try { await sendProjectGuideMessage(transport, project, `开始下一轮 Agent Lab 实验。优化方向：${direction}。先读取当前项目成果、评测集、原始运行记录和上一轮指标，只改变这一层并保留其他冻结条件。若项目存在执行绑定，先用 execution_read 核对当前 suite/job；Prompt 或 Model 优化必须进入真实 Golden/Pi 实验，等待 completed 回执后再发布指标、原始聊天/Tool 回执和 Keep/Reject 判定。没有新的 completed 执行回执时，只记录 blocked/待执行状态，不得编造指标或把 Agent 建议当作运行结果。Tool、MCP/Workflow、检索等方向必须使用对应的已接入执行器；若当前项目没有该执行器，明确说明缺口，不要假称优化已完成。`, `lab-optimization-direction:${crypto.randomUUID()}`); }
    catch (error) { setNotice(projectError(error)); }
    finally { setSending(false); if (currentProjectId.current === project.projectId) setPendingMessages(pendingProjectMessages(transport, project)); }
  };
  const beginOptimization = async (direction: string) => {
    // Prompt and model optimization use the project-owned Golden runner. Open
    // that exact binding before sending the causal note so the next action is
    // a real experiment, rather than an Agent-only recommendation.
    if (direction === 'Prompt 优化' || direction === 'Model 优化') {
      const target = project?.bindings.find((item) => item.ownerRef.kind === 'golden_suite');
      if (target) updateView({ page: 'runs', bindingId: target.bindingId });
    }
    await sendOptimizationDirection(direction);
  };
  const act = async (action: ArtifactAction, values: Record<string, JsonValue>, staged = false) => {
    if (!project || !selected) return;
    const text = `${action.prompt}\n\n当前成果：${selected.title}\n成果引用：${selected.artifactId} · v${selected.revision}\n用户输入：${JSON.stringify(values)}`;
    setGuideOpen(true);
    if (staged) { setStagedAction({ text, title: selected.title }); return; }
    setSending(true); setNotice('');
    try { await sendProjectGuideMessage(transport, project, text, `lab-artifact-action:${crypto.randomUUID()}`); }
    catch (error) { setNotice(projectError(error)); }
    finally { setSending(false); if (currentProjectId.current === project.projectId) setPendingMessages(pendingProjectMessages(transport, project)); }
  };
  const recoverMessage = async (message: PendingProjectMessage) => {
    if (!project || sending) return;
    setSending(true); setNotice(''); setGuideOpen(true);
    const clientId = message.outcome === 'unknown' ? message.clientMessageId : `lab-project-retry:${crypto.randomUUID()}`;
    if (message.outcome === 'rejected') retainProjectMessage(transport, project, message, true);
    try { await sendProjectGuideMessage(transport, project, message.message, clientId); }
    catch (reason) { setNotice(projectError(reason)); }
    finally { setSending(false); if (currentProjectId.current === project.projectId) setPendingMessages(pendingProjectMessages(transport, project)); }
  };
  const projectItems = workflow.catalog.data?.items ?? [];
  const hasProjects = projectItems.length > 0;
  return <main className="eval-lab lab-project-workbench" aria-label="Agent Lab 项目工作台">
    <header className="lab-project-header">
      <div className="lab-project-heading">{projectId ? <IconButton icon={<ArrowLeft size={17} />} label="返回 Lab 项目" onClick={() => openProject('')} /> : <span className="lab-project-logo" aria-hidden="true">L</span>}
        <div><small>Agent Lab</small><h1>{project?.title ?? (projectId ? '正在读取项目' : '从你的项目开始')}</h1></div></div>
      <div className="lab-project-header__actions"><IconButton icon={<RefreshCw size={16} />} label="重新读取 Lab 项目" onClick={refresh} disabled={workflow.catalog.isFetching || workflow.project.isFetching} />
        {project ? <><Button size="small" onClick={() => setIntakeOpen(true)}><Upload size={14} />添加材料</Button><IconButton icon={guideOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />} label={guideOpen ? '收起项目 Agent' : '展开项目 Agent'} onClick={() => setGuideOpen((value) => !value)} /></> : null}
        {!projectId ? <><Button size="small" onClick={() => setNewProjectOpen(true)}><Plus size={14} />新建项目</Button><Button size="small" onClick={() => setHistoryImportOpen(true)}><History size={14} />导入已有实验</Button></> : null}
        {onOpenHistory ? <Button size="small" onClick={onOpenHistory}><History size={14} />已有实验</Button> : null}</div>
    </header>
    {workflow.pending?.outcome === 'unknown' ? <div className="lab-project-notice" role="status"><p>上次操作的回执尚未确认，原请求和输入已保留。</p><Button disabled={workflow.mutation.isPending} onClick={() => void workflow.reconcile().then((receipt) => { if (receipt && workflow.pending?.command.action === 'create') void created(receipt); else if (receipt && workflow.pending?.command.action === 'import_history') { setHistoryImportOpen(false); openProject(receipt.project.projectId); } })}>核对原操作</Button></div> : null}
    {activeError ? <p className="lab-project-error" role="alert">{projectError(activeError)}</p> : null}
    {notice && !pendingMessages.length ? <p className="lab-project-notice" role="status">{notice}</p> : null}
    {pendingMessages.map((message) => <div className="lab-project-notice" role="status" key={message.clientMessageId}><p>{message.error || '项目消息的接纳结果尚未确认，原输入已保留。'}</p><Button disabled={sending} onClick={() => void recoverMessage(message)}>{message.outcome === 'unknown' ? '核对原消息' : '重新发送项目消息'}</Button></div>)}
    {!projectId ? hasProjects ? <div className="lab-project-home lab-project-home--returning">
      <section className="lab-project-returning" aria-labelledby="lab-project-continue-title"><header><div><small>继续你的工作</small><h2 id="lab-project-continue-title">需要处理</h2><p>从真实状态、最近成果和下一步开始，不必重新描述项目。</p></div><Button size="small" variant="primary" onClick={() => setNewProjectOpen(true)}><Plus size={14} />新建项目</Button></header><ProjectAttention items={projectItems} onOpen={openProject} /></section>
      <section className="lab-project-list" aria-label="最近的优化项目"><header><div><small>项目与运行记录</small><h2>最近项目</h2></div><span>{projectItems.length} 个</span></header><ProjectList items={projectItems} onOpen={openProject} /></section>
    </div> : <div className="lab-project-home">
      <section className="lab-project-start"><h2>描述你想完成的工作。</h2><p>带上业务资料或已有项目。Agent 会根据实际情况组织成果，带你改进、验证和交付。</p>
        <NewProject key={workflow.connection} connection={workflow.connection} busy={busy || sending} onCreate={async (input) => created(await workflow.submit('create', input))} /></section>
      <section className="lab-project-list" aria-label="最近的优化项目"><header><h2>最近项目</h2><span>{workflow.catalog.data?.items.length ?? '—'}</span></header>
        {workflow.catalog.isPending ? <p role="status">正在读取项目…</p> : !workflow.catalog.data?.items.length && !workflow.catalog.isError ? <p className="lab-project-muted">新项目和它的成果会保存在这里。</p> : null}
      </section>
    </div> : !project ? <div className="lab-project-loading" role="status">{workflow.project.isError ? '项目未能读取，已保存的工作仍保留。' : '正在恢复项目与成果…'}</div>
      : <div className="lab-project-body" data-guide-open={guideOpen}>
        {guideOpen ? <ProjectGuide key={project.projectId} project={project} draftRequest={draftRequest} onNewProject={() => openProject('')} onProjectActivity={refresh} onEnsure={() => void ensureGuide()} /> : null}
        <div className="lab-project-results">
          <nav className="lab-project-tabs" aria-label="项目成果">
            <div className="lab-project-tabs__artifacts">{project.workspace.artifactOrder.map((id) => project.artifacts.find((item) => item.artifactId === id)).filter((item) => item !== undefined).map((item) => <button key={item.artifactId} title={item.title} aria-current={page === 'artifact' && selectedId === item.artifactId ? 'page' : undefined} onClick={() => updateView({ artifactId:item.artifactId, page:'artifact', bindingId:undefined })}><FileText size={14} /><span>{item.title}</span></button>)}</div>
            <div className="lab-project-tabs__resources"><button aria-current={page === 'materials' ? 'page' : undefined} onClick={() => setPage('materials')}>材料 {project.materialCount}</button>
            <button aria-current={page === 'knowledge' ? 'page' : undefined} onClick={() => setPage('knowledge')}>知识库实验</button>
            <button aria-current={page === 'lifecycle' ? 'page' : undefined} onClick={() => setPage('lifecycle')}>实验闭环</button>
            {project.bindings.length ? <button aria-current={page === 'runs' ? 'page' : undefined} onClick={() => setPage('runs')}>运行</button> : null}
            <button aria-current={page === 'apps' ? 'page' : undefined} onClick={() => setPage('apps')}>应用交付</button>
            <button aria-current={page === 'brief' ? 'page' : undefined} onClick={() => setPage('brief')}>项目说明</button>
            </div>
          </nav>
          {stagedAction ? <div className="lab-project-notice" role="status"><span>“{stagedAction.title}”提供了一项交互输入。</span><Button size="small" onClick={() => { setDraftRequest({ id: Date.now(), text: stagedAction.text }); setStagedAction(undefined); setGuideOpen(true); }}>带入对话</Button><Button size="small" onClick={() => setStagedAction(undefined)}>关闭</Button></div> : null}
          <div className="lab-project-stage">
            {page === 'materials' ? <Materials project={project} onAdd={() => setIntakeOpen(true)} />
              : page === 'knowledge' ? <LabKnowledge key={project.projectId} project={project} busy={busy} onCommand={(input) => workflow.submit('knowledge', input, project)} onBind={(input) => workflow.submit('bind_execution', input, project)} onOpenBinding={(binding) => updateView({ page: 'runs', bindingId: binding.bindingId })} />
              : page === 'lifecycle' ? <LabExperimentLifecycle project={project} onOpenArtifact={(artifactId) => updateView({ page: 'artifact', artifactId, bindingId: undefined })} onOpenRuns={() => updateView({ page: 'runs', bindingId: undefined })} onDirection={(direction) => void beginOptimization(direction)} />
              : page === 'apps' ? <LabAppDelivery projectId={project.projectId} preparing={busy} onPrepare={async (directory, appId) => Boolean(await workflow.submit('prepare_app', { directory, ...(appId ? { appId } : {}) }, project))} />
              : page === 'brief' ? <section className="lab-project-brief"><small>用户描述 · v{project.briefVersion}</small><h2>{project.title}</h2><p>{project.description}</p><p className="lab-project-muted">需要调整方向时，可以直接告诉项目 Agent。</p></section>
                : page === 'runs' ? binding?.ownerRef.kind === 'golden_suite' ? <GoldenWorkflow key={binding.bindingId} initialSuiteId={binding.ownerRef.id} onClose={() => setBinding(undefined)} />
                  : binding?.ownerRef.kind === 'scene_trial' ? <section className="lab-project-bindings"><h2>继续场景验证</h2><p>历史对照保存在项目成果中。这里使用执行器当前登记的资料与规则，新运行单独记录；不会覆盖历史成绩。</p><SceneTrialPanel sceneId={binding.ownerRef.id} /></section>
                  : <ProjectBindingList bindings={project.bindings} onOpen={setBinding} />
                  : selected ? artifact.isPending ? <p className="lab-project-loading" role="status">正在读取成果…</p> : artifact.isError ? <div className="lab-project-error" role="alert"><p>{projectError(artifact.error)}</p><Button onClick={() => void artifact.refetch()}>重新读取成果</Button></div>
                    : artifact.data ? <ArtifactSurface artifact={artifact.data} draft={drafts[draftKey]} busy={busy || sending}
                      onDraft={(draft) => updateDraft(draftKey, draft)}
                      onSave={async (content, revision) => Boolean(await workflow.submit('publish_artifact', { artifactId: artifact.data!.artifactId, expectedArtifactRevision: revision, content }, project))}
                      onAction={(action, values, staged) => void act(action, values, staged)} /> : null
                    : <section className="lab-project-empty"><span><MessageSquare size={24} /></span><h2>让成果跟随项目生长。</h2><p>和 Agent 继续工作，它会把适合当前项目的文档、表格、交互页面或其他成果放在这里。</p>{!guideOpen ? <Button onClick={() => setGuideOpen(true)}>打开项目对话</Button> : null}</section>}
          </div>
        </div>
      </div>}
    <Dialog.Root open={intakeOpen && Boolean(project)} onOpenChange={setIntakeOpen}><Dialog.Overlay className="lab-project-modal-backdrop" /><Dialog.Content className="lab-project-modal" aria-describedby={undefined}><header><Dialog.Title asChild><h2>添加项目材料</h2></Dialog.Title><Dialog.Close asChild><Button size="small">关闭</Button></Dialog.Close></header>{project ? <MaterialIntake busy={busy} onAdd={async (input) => { const receipt = await workflow.submit('import_materials', input, project); if (receipt) { setIntakeOpen(false); setPage('materials'); } }} /> : null}</Dialog.Content></Dialog.Root>
    <Dialog.Root open={newProjectOpen && !projectId} onOpenChange={setNewProjectOpen}><Dialog.Overlay className="lab-project-modal-backdrop" /><Dialog.Content className="lab-project-modal" aria-describedby="lab-new-project-description"><header><Dialog.Title asChild><h2>新建项目</h2></Dialog.Title><Dialog.Close asChild><Button size="small">关闭</Button></Dialog.Close></header><p id="lab-new-project-description">先保存项目和材料，再由 Agent 在同一个项目里继续组织计划、实验与交付。创建不会伪造评测结果。</p><NewProject key={`dialog:${workflow.connection}`} connection={workflow.connection} busy={busy || sending} onCreate={async (input) => created(await workflow.submit('create', input))} /></Dialog.Content></Dialog.Root>
    <Dialog.Root open={historyImportOpen} onOpenChange={setHistoryImportOpen}><Dialog.Overlay className="lab-project-modal-backdrop" /><Dialog.Content className="lab-project-modal" aria-describedby="lab-history-import-description"><header><Dialog.Title asChild><h2>导入已有实验</h2></Dialog.Title><Dialog.Close asChild><Button size="small">关闭</Button></Dialog.Close></header><p id="lab-history-import-description">把已有基线、候选、失败记录和原始指标保留为项目成果。导入不会运行模型或重新评分。</p>
      {workflow.catalog.data?.historyUnavailable ? <p role="alert">已有实验来源暂时不可读取，请重新读取后再试。</p> : null}
      {workflow.catalog.data?.historyCollections?.map((source) => { const imported = workflow.catalog.data?.items.find((item) => item.historyOrigin?.sceneId === source.sceneId); return <section key={source.sceneId} className="lab-project-bindings" aria-label={source.title}><h3>{source.title}</h3><p>{source.experimentCount} 条实验记录 · {source.datasetIds.length} 个数据集版本</p><Button disabled={busy} onClick={() => { if (imported) { setHistoryImportOpen(false); openProject(imported.projectId); } else void workflow.submit('import_history', { sceneId: source.sceneId, sourceHash: source.sourceHash }).then((receipt) => { if (receipt) { setHistoryImportOpen(false); openProject(receipt.project.projectId); } }); }}>{imported ? '打开已导入项目' : '导入为项目'}</Button></section>; })}
      {!workflow.catalog.isPending && !workflow.catalog.data?.historyUnavailable && !workflow.catalog.data?.historyCollections?.length ? <p>当前执行器没有可导入的已有实验。</p> : null}
    </Dialog.Content></Dialog.Root>
  </main>;
}

function NewProject({ connection, busy, onCreate }: { connection: string; busy: boolean; onCreate: (input: Record<string, JsonValue>) => Promise<void> }) {
  const key = `paw.lab.new-project.v1:${connection}`;
  const [saved] = useState(() => { try { return object(JSON.parse(sessionStorage.getItem(key) ?? '{}')); } catch { return {}; } });
  const [description, setDescription] = useState(typeof saved.description === 'string' ? saved.description : '');
  const [path, setPath] = useState(typeof saved.path === 'string' ? saved.path : '');
  const [materials, setMaterials] = useState<Intake[]>(() => Array.isArray(saved.materials) ? saved.materials.filter((item): item is Intake => typeof object(item).title === 'string' && typeof object(item).text === 'string') : []);
  const [error, setError] = useState(''); const [reading, setReading] = useState(false);
  useEffect(() => {
    try { sessionStorage.setItem(key, JSON.stringify({ description, path, materials })); }
    catch { setError('浏览器暂时无法保存草稿，请保持当前页面并完成创建。'); }
  }, [key, description, path, materials]);
  const chooseFiles = async (list: FileList | null) => {
    if (!list?.length || reading || busy) return;
    setReading(true); setError('');
    try { setMaterials(await loadFiles(list)); setPath(''); }
    catch (reason) { setError(projectError(reason)); }
    finally { setReading(false); }
  };
  const submit = async (event: FormEvent) => { event.preventDefault(); if (!description.trim() || busy || reading) return; await onCreate({ description: description.trim(), ...(materials.length ? { materials } : path.trim() ? { path: path.trim() } : {}) }); };
  return <form className="lab-project-compose" onSubmit={(event) => void submit(event)}><textarea aria-label="描述你的项目" placeholder="例如：我有一个处理售后问题的 Agent，希望它依据规则完成操作。也可以从一个新的业务想法开始。" rows={5} value={description} onChange={(event) => setDescription(event.target.value)} disabled={busy} />
    <div className="lab-project-compose__materials"><label className="lab-project-file-picker"><Upload size={15} />{reading ? '正在读取文件…' : '添加文件'}<input type="file" multiple disabled={busy || reading} onChange={(event) => { void chooseFiles(event.target.files); event.target.value = ''; }} /></label>
      {materials.length ? <><span>{materials.length} 份文件已选，创建时上传</span><Button type="button" size="small" disabled={busy || reading} onClick={() => setMaterials([])}>移除已选文件</Button></> : <input aria-label="连接执行器上的材料路径" value={path} placeholder="或填写已连接执行器上的绝对路径" disabled={busy || reading} onChange={(event) => setPath(event.target.value)} />}</div>
    {error ? <p role="alert" className="lab-project-error">{error}</p> : null}<footer><span>项目内容由 Agent 按实际任务组织。</span><Button type="submit" variant="primary" disabled={busy || reading || !description.trim()}>{busy ? '正在建立项目…' : reading ? '正在读取材料…' : '创建并开始'}<ArrowUpRight size={16} /></Button></footer>
  </form>;
}
function MaterialIntake({ busy, onAdd }: { busy: boolean; onAdd: (input: Record<string, JsonValue>) => Promise<void> }) {
  const [path, setPath] = useState(''); const [title, setTitle] = useState(''); const [text, setText] = useState(''); const [error, setError] = useState('');
  return <div className="lab-project-intake"><label className="lab-project-file-picker"><Upload size={16} />上传文本或源码文件<input type="file" multiple disabled={busy} onChange={(event) => void loadFiles(event.target.files).then((materials) => onAdd({ materials })).catch((reason) => setError(projectError(reason)))} /></label>
    <label>已连接执行器上的路径<input value={path} placeholder="绝对路径" onChange={(event) => setPath(event.target.value)} disabled={busy} /></label><Button disabled={busy || !path.trim()} onClick={() => void onAdd({ path: path.trim() })}>读取路径</Button>
    <hr /><label>粘贴材料标题<input value={title} onChange={(event) => setTitle(event.target.value)} disabled={busy} /></label><label>材料正文<textarea rows={7} value={text} onChange={(event) => setText(event.target.value)} disabled={busy} /></label>
    <Button disabled={busy || !title.trim() || !text.trim()} onClick={() => void onAdd({ materials: [{ title: title.trim(), text }] })}>保存文本材料</Button>{error ? <p role="alert" className="lab-project-error">{error}</p> : null}</div>;
}
function Materials({ project, onAdd }: { project: LabProject; onAdd: () => void }) {
  const [selectedId, setSelectedId] = useState(''); const selected = project.materialSet.materials.find((item) => item.sourceId === selectedId) ?? project.materialSet.materials[0];
  return <section className="lab-project-materials"><header><div><small>材料快照 · v{project.materialSet.version}</small><h2>项目实际材料</h2></div><Button onClick={onAdd}><Plus size={14} />添加材料</Button></header>
    {project.intake.issues.length ? <details className="lab-project-notice"><summary>最近接入有 {project.intake.skippedCount} 项未读取</summary><ul>{project.intake.issues.map((issue, index) => <li key={index}><strong>{issue.title}</strong>：{issue.message}</li>)}</ul></details> : null}
    {!selected ? <p>尚未读取材料。可以上传文件、粘贴正文或连接执行器路径。</p> : <div className="lab-project-materials__body"><nav aria-label="材料文件">{project.materialSet.materials.map((item) => <button key={item.sourceId} aria-current={selected.sourceId === item.sourceId ? 'page' : undefined} onClick={() => setSelectedId(item.sourceId)}><FileText size={15} />{item.title}<small>{item.kind}</small></button>)}</nav><article><header><h3>{selected.title}</h3><small>{selected.byteSize.toLocaleString()} bytes · 已保存快照</small></header><pre>{selected.text}</pre></article></div>}
  </section>;
}
async function loadFiles(list: FileList | null): Promise<Intake[]> {
  const files = [...(list ?? [])]; if (!files.length || files.length > 100 || files.reduce((total, file) => total + file.size, 0) > 2_000_000) throw new Error('请选择 1–100 份文件，合计不超过 2 MB。');
  return Promise.all(files.map(async (file) => {
    if (file.size > 500_000) throw new Error(`${file.name} 超过 500 KB，请拆分后添加。`);
    let text: string; try { text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); } catch { throw new Error(`${file.name} 尚不能作为 UTF-8 文本读取。`); }
    if (!text.trim() || text.includes('\0')) throw new Error(`${file.name} 没有可用的文本内容。`);
    return { title: file.name, text, kind: file.name === 'SKILL.md' ? 'skill' : /\.(?:py|[cm]?js|jsx|ts|tsx|go|rs|java|swift)$/iu.test(file.name) ? 'code' : 'document' };
  }));
}
