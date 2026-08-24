import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  CircleAlert,
  CircleDashed,
  ExternalLink,
  FileText,
  FolderTree,
  GitBranch,
  LoaderCircle,
  Network,
  PencilLine,
  PanelsTopLeft,
  Plus,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import '../styles/paw-os-workbench-migrated-v1.css';

/**
 * THESIS: Workbench is a live project dependency field, never a summary-card dashboard.
 * OWN-WORLD: Cold-white canvas, coral project identity, compact white task plates, dotted topology, blue flow, and restrained semantic inks.
 * STORY: Read the real project, inspect task ownership and dependencies, then open the authoritative task or WorkDocument.
 * FIRST VIEWPORT: Project outline left, dependency field center, selected truth right; overview and documents retain the same hierarchy.
 * FORM: Archive-led Operate extension, pawos-workbench-v1.
 */

export const PAW_WORKBENCH_MIGRATED_ROUTES = {
  overview: '/overview',
  planning: '/planning',
  documents: '/work-documents',
} as const;

export type PawWorkbenchPageId = keyof typeof PAW_WORKBENCH_MIGRATED_ROUTES;
export type PawWorkbenchRecord = Record<string, unknown>;
export type PawWorkbenchResourceKey = 'overview' | 'planning' | 'documents' | 'documentDetail';
export type PawWorkbenchDocumentScope = 'active' | 'history';

export interface PawWorkbenchResourceState {
  loading?: boolean;
  error?: string;
}

export interface PawWorkbenchMigratedProps {
  pageId: PawWorkbenchPageId;
  overview: PawWorkbenchRecord;
  planning: PawWorkbenchRecord;
  documents: readonly PawWorkbenchRecord[];
  documentTotal?: number;
  selectedDocument: PawWorkbenchRecord | null;
  resourceStates?: Partial<Record<PawWorkbenchResourceKey, PawWorkbenchResourceState>>;
  onOpenTask: (task: PawWorkbenchRecord) => void;
  onEditTask?: (task: PawWorkbenchRecord) => void;
  onCreateGoal?: () => void;
  onEditGoal?: (goal: PawWorkbenchRecord) => void;
  onOpenDocument: (document: PawWorkbenchRecord) => void | Promise<void>;
  onOpenDocumentWindow?: (document: PawWorkbenchRecord) => void;
  onCloseDocument: () => void;
  documentLifecycle?: ReactNode;
  documentScope?: PawWorkbenchDocumentScope;
  documentHistoryQuery?: string;
  documentHistorySupported?: boolean;
  onDocumentScopeChange?: (scope: PawWorkbenchDocumentScope) => void;
  onDocumentHistoryQueryChange?: (query: string) => void;
  planningTools?: ReactNode;
  primaryAction?: { label: string; onClick: () => void };
  onNavigate?: (pageId: PawWorkbenchPageId) => void;
  onRefresh?: (resource: PawWorkbenchResourceKey) => void;
}

type TaskLane = 'done' | 'active' | 'review' | 'blocked' | 'todo';

interface TaskGraphNode {
  id: string;
  lane: TaskLane;
  task: PawWorkbenchRecord;
  x: number;
  y: number;
}

interface TaskGraphEdge {
  id: string;
  path: string;
  active: boolean;
}

const GRAPH_LANES: readonly TaskLane[] = ['done', 'active', 'review', 'blocked', 'todo'];
const GRAPH_NODE_WIDTH = 188;
const GRAPH_NODE_HEIGHT = 82;
const GRAPH_COLUMN_GAP = 42;
const GRAPH_ROW_GAP = 28;
const GRAPH_PADDING_X = 28;
const GRAPH_PADDING_Y = 62;

export function PawWorkbenchMigrated({
  pageId,
  overview,
  planning,
  documents,
  documentTotal,
  selectedDocument,
  resourceStates = {},
  onOpenTask,
  onEditTask,
  onCreateGoal,
  onEditGoal,
  onOpenDocument,
  onOpenDocumentWindow,
  onCloseDocument,
  documentLifecycle,
  documentScope = 'active',
  documentHistoryQuery = '',
  documentHistorySupported = false,
  onDocumentScopeChange,
  onDocumentHistoryQueryChange,
  planningTools,
  primaryAction,
  onNavigate,
  onRefresh,
}: PawWorkbenchMigratedProps) {
  const project = record(overview.project);
  const plan = record(planning.plan);
  const tasks = rows(planning, ['tasks', 'items']);
  const goals = rows(planning, ['goals']);
  const projectPath = text(project.path)
    || text(overview.projectPath)
    || text(plan.workspaceRoot)
    || documents.map((document) => text(document.workspaceRoot)).find(Boolean)
    || '';
  const projectName = text(project.name)
    || text(overview.projectName)
    || text(plan.project)
    || text(planning.project)
    || pathName(projectPath)
    || '未选择项目';
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [openedOverviewDocument, setOpenedOverviewDocument] = useState<PawWorkbenchRecord | null>(null);

  useEffect(() => {
    if (pageId !== 'overview') setOpenedOverviewDocument(null);
  }, [pageId]);

  useEffect(() => {
    if (tasks.some((task, index) => taskId(task, index) === selectedTaskId)) return;
    const firstActiveIndex = tasks.findIndex((task) => taskLane(task) === 'active');
    const nextIndex = firstActiveIndex >= 0 ? firstActiveIndex : 0;
    setSelectedTaskId(tasks[nextIndex] ? taskId(tasks[nextIndex], nextIndex) : '');
  }, [selectedTaskId, tasks]);

  const selectedTask = tasks.find((task, index) => taskId(task, index) === selectedTaskId) ?? null;
  const selectTask = (task: PawWorkbenchRecord, index: number) => {
    setSelectedTaskId(taskId(task, index));
  };
  const openTask = (task: PawWorkbenchRecord, index: number) => {
    setSelectedTaskId(taskId(task, index));
    onOpenTask(task);
  };
  const openDocument = async (document: PawWorkbenchRecord): Promise<void> => {
    if (pageId === 'overview') setOpenedOverviewDocument(document);
    await onOpenDocument(document);
  };
  const closeDocument = () => {
    setOpenedOverviewDocument(null);
    onCloseDocument();
  };
  const activePageId: PawWorkbenchPageId = pageId === 'overview' && openedOverviewDocument ? 'documents' : pageId;
  const activeDocument = openedOverviewDocument
    ? (selectedDocument && sameDocument(selectedDocument, openedOverviewDocument) ? selectedDocument : openedOverviewDocument)
    : selectedDocument;

  return (
    <section className="paw-workbench-migrated" data-page-id={activePageId}>
      <span aria-hidden data-paw-workbench-direction="pawos-workbench-v1" hidden />
      <WorkbenchChrome
        pageId={activePageId}
        primaryAction={primaryAction}
        projectName={projectName}
        projectPath={projectPath}
      />
      {activePageId === 'overview' ? (
        <ProjectOverview
          documents={documents}
          documentTotal={documentTotal}
          documentsState={resourceStates.documents}
          goals={goals}
          onOpenDocument={openDocument}
          onOpenTask={openTask}
          onNavigate={onNavigate}
          onRefresh={onRefresh}
          overview={overview}
          overviewState={resourceStates.overview}
          planning={planning}
          planningState={resourceStates.planning}
          project={project}
          projectName={projectName}
          projectPath={projectPath}
          tasks={tasks}
        />
      ) : null}
      {activePageId === 'planning' ? (
        <div className="paw-wb-planning">
          {planningTools}
          <TaskOrchestration
            goals={goals}
            onCreateGoal={onCreateGoal}
            onEditGoal={onEditGoal}
            onEditTask={onEditTask}
            onOpenTask={onOpenTask}
            onRefresh={onRefresh}
            onSelectTask={selectTask}
            projectName={projectName}
            resourceState={resourceStates.planning}
            selectedTask={selectedTask}
            selectedTaskId={selectedTaskId}
            tasks={tasks}
          />
        </div>
      ) : null}
      {activePageId === 'documents' ? (
        <WorkDocumentWorkspace
          documents={documents}
          documentTotal={documentTotal}
          documentHistoryQuery={documentHistoryQuery}
          documentHistorySupported={documentHistorySupported}
          documentLifecycle={documentLifecycle}
          documentScope={documentScope}
          detailState={resourceStates.documentDetail}
          listState={resourceStates.documents}
          onCloseDocument={closeDocument}
          onOpenDocument={openDocument}
          onOpenDocumentWindow={onOpenDocumentWindow}
          onDocumentHistoryQueryChange={onDocumentHistoryQueryChange}
          onDocumentScopeChange={onDocumentScopeChange}
          onRefresh={onRefresh}
          projectName={projectName}
          selectedDocument={activeDocument}
        />
      ) : null}
    </section>
  );
}

function WorkbenchChrome({
  pageId,
  projectName,
  projectPath,
  primaryAction,
}: {
  pageId: PawWorkbenchPageId;
  projectName: string;
  projectPath: string;
  primaryAction?: PawWorkbenchMigratedProps['primaryAction'];
}) {
  const pageLabel = { overview: '项目概览', planning: '任务', documents: '工作文档' }[pageId];
  return (
    <header className="paw-wb-chrome">
      <div className="paw-wb-chrome__identity">
        <span>
          <strong title={projectName}>{projectName}</strong>
          <small title={projectPath || pageLabel}>{projectPath || pageLabel}</small>
        </span>
      </div>
      <div className="paw-wb-chrome__location" aria-label="当前位置">
        <h1>{pageLabel}</h1>
      </div>
      {primaryAction ? (
        <button aria-label={primaryAction.label} className="paw-wb-primary" onClick={primaryAction.onClick} type="button">
          <Plus aria-hidden size={15} />
          <span>{primaryAction.label}</span>
        </button>
      ) : <span className="paw-wb-chrome__spacer" />}
    </header>
  );
}

function ProjectOverview({
  documents,
  documentTotal,
  documentsState,
  goals,
  onOpenDocument,
  onOpenTask,
  onNavigate,
  onRefresh,
  overview,
  overviewState,
  planning,
  planningState,
  project,
  projectName,
  projectPath,
  tasks,
}: {
  documents: readonly PawWorkbenchRecord[];
  documentTotal?: number;
  documentsState?: PawWorkbenchResourceState;
  goals: PawWorkbenchRecord[];
  onOpenDocument: PawWorkbenchMigratedProps['onOpenDocument'];
  onOpenTask: (task: PawWorkbenchRecord, index: number) => void;
  onNavigate?: PawWorkbenchMigratedProps['onNavigate'];
  onRefresh?: PawWorkbenchMigratedProps['onRefresh'];
  overview: PawWorkbenchRecord;
  overviewState?: PawWorkbenchResourceState;
  planning: PawWorkbenchRecord;
  planningState?: PawWorkbenchResourceState;
  project: PawWorkbenchRecord;
  projectName: string;
  projectPath: string;
  tasks: PawWorkbenchRecord[];
}) {
  const metrics = overviewMetrics(overview, planning, documents, documentsState);
  const resolvedDocumentTotal = Math.max(documents.length, documentTotal ?? 0);
  const [visibleTaskCount, setVisibleTaskCount] = useState(8);
  const [visibleDocumentCount, setVisibleDocumentCount] = useState(6);
  const displayedTasks = tasks.slice(0, Math.min(tasks.length, visibleTaskCount));
  const displayedDocuments = documents.slice(0, Math.min(documents.length, visibleDocumentCount));
  const remainingTasks = Math.max(0, tasks.length - displayedTasks.length);
  const remainingLoadedDocuments = Math.max(0, documents.length - displayedDocuments.length);
  const remainingUnloadedDocuments = Math.max(0, resolvedDocumentTotal - documents.length);
  return (
    <div className="paw-wb-overview">
      <ResourceNotice label="项目概览" onRefresh={onRefresh ? () => onRefresh('overview') : undefined} state={overviewState} />
      <section className="paw-wb-project-lead">
        <div className="paw-wb-project-lead__mark"><FolderTree aria-hidden size={27} /></div>
        <div className="paw-wb-project-lead__copy">
          <h2 title={projectName}>{projectName}</h2>
          {projectPath ? <p className="paw-wb-mono" title={projectPath}>{projectPath}</p> : <p>当前项目尚未提供工作区路径。</p>}
        </div>
        <dl className="paw-wb-project-facts">
          {text(project.branch) || text(overview.branch) ? <Fact label="分支" value={text(project.branch) || text(overview.branch)} /> : null}
          {text(project.status) || text(overview.status) ? <Fact label="状态" value={stateLabel(text(project.status) || text(overview.status))} /> : null}
          {text(project.revision) || text(overview.revision) ? <Fact label="Revision" value={text(project.revision) || text(overview.revision)} mono /> : null}
        </dl>
      </section>

      {metrics.length ? <dl className="paw-wb-metrics" aria-label="项目真实指标">{metrics.map((metric) => <Fact key={metric.label} label={metric.label} value={metric.value} />)}</dl> : null}

      <div className="paw-wb-overview__columns">
        <section className="paw-wb-focus">
          <header>
            <div><GitBranch aria-hidden size={17} /><h2>当前工作</h2></div>
            <div className="paw-wb-focus__scope">
              <span>{tasks.length > 8 ? `当前 ${displayedTasks.length} / 共 ${tasks.length}` : `${tasks.length} 项`}</span>
            </div>
          </header>
          <ResourceNotice label="任务" onRefresh={onRefresh ? () => onRefresh('planning') : undefined} state={planningState} />
          {tasks.length ? (
            <ol className="paw-wb-focus__list" data-scrollable={displayedTasks.length > 8 || undefined}>
              {displayedTasks.map((task, index) => (
                <li key={taskId(task, index)}>
                  <button onClick={() => onOpenTask(task, index)} title={`${taskTitle(task)} · ${taskMeta(task)}`} type="button">
                    <StatusMark lane={taskLane(task)} />
                    <span><strong>{taskTitle(task)}</strong><small>{taskMeta(task)}</small></span>
                    <em>{taskStateLabel(task)}</em>
                  </button>
                </li>
              ))}
            </ol>
          ) : resourceSettled(planningState) ? <EmptyState icon={<CircleDashed size={22} />} title="暂无真实任务" copy="任务会在规划数据可用后出现在这里。" /> : null}
          {remainingTasks ? <button className="paw-wb-focus__more" aria-label={`显示更多任务：${remainingTasks} 项`} onClick={() => setVisibleTaskCount((value) => value + 8)} type="button">显示更多 {Math.min(8, remainingTasks)} 项</button> : null}
        </section>

        <section className="paw-wb-focus">
          <header>
            <div><FileText aria-hidden size={17} /><h2>工作文档</h2></div>
            <div className="paw-wb-focus__scope">
              <span>{resolvedDocumentTotal > 6 ? `当前 ${displayedDocuments.length} / 已加载 ${documents.length}${remainingUnloadedDocuments ? ` · 共 ${resolvedDocumentTotal}` : ''}` : `${resolvedDocumentTotal} 份`}</span>
            </div>
          </header>
          <ResourceNotice label="工作文档" onRefresh={onRefresh ? () => onRefresh('documents') : undefined} state={documentsState} />
          {documents.length ? (
            <ol className="paw-wb-document-rows" data-scrollable={displayedDocuments.length > 6 || undefined}>
              {displayedDocuments.map((document, index) => (
                <li key={documentId(document, index)}>
                  <button onClick={() => void onOpenDocument(document)} title={`${documentTitle(document)} · ${authorityLabel(text(document.authorityKind))}`} type="button">
                    <FileText aria-hidden size={16} />
                    <span><strong>{documentTitle(document)}</strong><small>{authorityLabel(text(document.authorityKind))} · {updatedLabel(number(document.updatedAtMs))}</small></span>
                    <StatusMark lane={documentLane(document)} />
                  </button>
                </li>
              ))}
            </ol>
          ) : resourceSettled(documentsState) ? <EmptyState icon={<FileText size={22} />} title="暂无工作文档" copy="这里只显示 Runtime 已登记的 WorkDocument。" /> : null}
          {remainingLoadedDocuments ? <button className="paw-wb-focus__more" aria-label={`显示更多工作文档：${remainingLoadedDocuments} 项`} onClick={() => setVisibleDocumentCount((value) => value + 6)} type="button">显示已加载的更多 {Math.min(6, remainingLoadedDocuments)} 项</button> : null}
          {!remainingLoadedDocuments && remainingUnloadedDocuments ? (
            onNavigate ? <button className="paw-wb-focus__more" aria-label={`在工作文档中查看其余 ${remainingUnloadedDocuments} 项`} onClick={() => onNavigate('documents')} type="button">在工作文档中查看其余 {remainingUnloadedDocuments} 项<ArrowRight aria-hidden size={13} /></button> : <p className="paw-wb-focus__boundary">已加载全部 {documents.length} 项；其余 {remainingUnloadedDocuments} 项尚未加载。</p>
          ) : null}
        </section>
      </div>

      {goals.length ? (
        <section className="paw-wb-goals">
          <header><Network aria-hidden size={17} /><h2>目标层级</h2></header>
          <ol>{goals.map((goal, index) => <li key={text(goal.id) || `goal-${index}`}><StatusMark lane={taskLane(goal)} /><span><strong title={text(goal.title) || '未命名目标'}>{text(goal.title) || '未命名目标'}</strong>{text(goal.detail) ? <small title={text(goal.detail)}>{text(goal.detail)}</small> : null}</span><em>{stateLabel(text(goal.status))}</em></li>)}</ol>
        </section>
      ) : null}
    </div>
  );
}

function TaskOrchestration({
  goals,
  onCreateGoal,
  onEditGoal,
  onEditTask,
  onOpenTask,
  onRefresh,
  onSelectTask,
  projectName,
  resourceState,
  selectedTask,
  selectedTaskId,
  tasks,
}: {
  goals: PawWorkbenchRecord[];
  onCreateGoal?: PawWorkbenchMigratedProps['onCreateGoal'];
  onEditGoal?: PawWorkbenchMigratedProps['onEditGoal'];
  onEditTask?: PawWorkbenchMigratedProps['onEditTask'];
  onOpenTask: PawWorkbenchMigratedProps['onOpenTask'];
  onRefresh?: PawWorkbenchMigratedProps['onRefresh'];
  onSelectTask: (task: PawWorkbenchRecord, index: number) => void;
  projectName: string;
  resourceState?: PawWorkbenchResourceState;
  selectedTask: PawWorkbenchRecord | null;
  selectedTaskId: string;
  tasks: PawWorkbenchRecord[];
}) {
  const graph = useMemo(() => buildTaskGraph(tasks), [tasks]);
  return (
    <div className="paw-wb-orchestration">
      <aside className="paw-wb-outline">
        <header>
          <FolderTree aria-hidden size={16} />
          <strong>目标与任务</strong>
          {onCreateGoal ? <button aria-label="添加目标" onClick={onCreateGoal} type="button"><Plus aria-hidden size={14} /></button> : null}
        </header>
        <div className="paw-wb-outline__project"><StatusMark lane="active" /><strong title={projectName}>{projectName}</strong><small>{tasks.length} 项</small></div>
        {goals.length ? <ol className="paw-wb-outline__goals">{goals.map((goal, index) => {
          const title = text(goal.title) || '未命名目标';
          return <li key={text(goal.id) || `goal-${index}`}>
            {onEditGoal ? (
              <button aria-label={`编辑目标：${title}`} onClick={() => onEditGoal(goal)} type="button">
                <StatusMark lane={taskLane(goal)} /><span>{title}</span><PencilLine aria-hidden size={13} />
              </button>
            ) : <><StatusMark lane={taskLane(goal)} /><span>{title}</span></>}
          </li>;
        })}</ol> : null}
        <ol className="paw-wb-outline__tasks">{tasks.map((task, index) => <li key={taskId(task, index)}><button aria-label={`在任务列表中选择：${taskTitle(task)}`} aria-current={taskId(task, index) === selectedTaskId || undefined} onClick={() => onSelectTask(task, index)} title={`${taskTitle(task)} · ${taskMeta(task)}`} type="button"><StatusMark lane={taskLane(task)} /><span>{taskTitle(task)}</span><small>{taskProgressLabel(task)}</small></button></li>)}</ol>
      </aside>

      <main className="paw-wb-graph" aria-label="真实任务依赖图">
        <header>
          <div><GitBranch aria-hidden size={16} /><strong>依赖图</strong><span>{tasks.length} 节点 · {graph.edges.length} 条真实依赖</span></div>
          <p>连线只来自任务记录中的依赖字段。</p>
        </header>
        <ResourceNotice label="任务编排" onRefresh={onRefresh ? () => onRefresh('planning') : undefined} state={resourceState} />
        {tasks.length ? (
          <div className="paw-wb-graph__viewport">
            <div className="paw-wb-graph__field" style={{ height: graph.height, width: graph.width }}>
              <svg aria-hidden className="paw-wb-graph__edges" height={graph.height} viewBox={`0 0 ${graph.width} ${graph.height}`} width={graph.width}>
                {graph.edges.map((edge) => <path className="paw-wb-graph__edge" d={edge.path} data-active={edge.active || undefined} key={edge.id} />)}
                {graph.edges.filter((edge) => edge.active).map((edge) => (
                  <circle className="paw-wb-flow-packet" data-flow-packet key={`packet-${edge.id}`} r="4">
                    <animateMotion begin="300ms" dur="900ms" fill="remove" path={edge.path} repeatCount="1" />
                  </circle>
                ))}
              </svg>
              {graph.nodes.map((node, index) => (
                <button
                  aria-label={`在依赖图中选择：${taskTitle(node.task)}`}
                  aria-pressed={node.id === selectedTaskId}
                  className="paw-wb-task-node"
                  data-gate={taskIsGate(node.task) || undefined}
                  data-lane={node.lane}
                  key={node.id}
                  onClick={() => onSelectTask(node.task, tasks.indexOf(node.task))}
                  style={{ '--paw-wb-node-x': `${node.x}px`, '--paw-wb-node-y': `${node.y}px` } as CSSProperties}
                  title={`${taskTitle(node.task)} · ${taskMeta(node.task)} · ${taskStateLabel(node.task)}`}
                  type="button"
                >
                  <span className="paw-wb-task-node__title"><StatusMark lane={node.lane} /><strong>{taskTitle(node.task)}</strong></span>
                  <span className="paw-wb-task-node__meta"><small>{taskMeta(node.task)}</small><em>{taskStateLabel(node.task)}</em></span>
                  {taskProgress(node.task) !== null ? <span className="paw-wb-task-progress" aria-label={`进度 ${taskProgressLabel(node.task)}`}><i style={{ width: `${Math.round((taskProgress(node.task) ?? 0) * 100)}%` }} /></span> : null}
                </button>
              ))}
            </div>
          </div>
        ) : resourceSettled(resourceState) ? <EmptyState icon={<GitBranch size={24} />} title="没有可编排的真实任务" copy="Workbench 不会为了填满画布创建演示节点。" /> : null}
      </main>

      <TaskDetail onEditTask={onEditTask} onOpenTask={onOpenTask} onSelectTask={onSelectTask} task={selectedTask} tasks={tasks} />
    </div>
  );
}

function TaskDetail({
  onEditTask,
  onOpenTask,
  onSelectTask,
  task,
  tasks,
}: {
  onEditTask?: PawWorkbenchMigratedProps['onEditTask'];
  onOpenTask: PawWorkbenchMigratedProps['onOpenTask'];
  onSelectTask: (task: PawWorkbenchRecord, index: number) => void;
  task: PawWorkbenchRecord | null;
  tasks: PawWorkbenchRecord[];
}) {
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const selectedTaskKey = task ? taskId(task, tasks.indexOf(task)) : '';
  useEffect(() => setDetailsExpanded(false), [selectedTaskKey]);
  if (!task) return <aside className="paw-wb-detail"><EmptyState icon={<CircleDashed size={23} />} title="未选择任务" copy="选择一个真实任务以查看它的状态与依赖。" /></aside>;
  const dependencies = taskDependencyIds(task);
  const progress = taskProgress(task);
  const detail = text(task.detail) || text(task.description);
  return (
    <aside className="paw-wb-detail" data-expanded={detailsExpanded || undefined}>
      <header><StatusMark lane={taskLane(task)} /><div><h2 title={taskTitle(task)}>{taskTitle(task)}</h2><p className="paw-wb-mono" title={selectedTaskKey || '无任务 ID'}>{selectedTaskKey || '无任务 ID'}</p></div></header>
      <div className="paw-wb-detail__actions">
        {onEditTask ? <button onClick={() => onEditTask(task)} type="button"><PencilLine aria-hidden size={14} />编辑任务</button> : null}
        <button
          aria-expanded={detailsExpanded}
          className="paw-wb-detail__compact-toggle"
          onClick={() => setDetailsExpanded((expanded) => !expanded)}
          type="button"
        >
          <ChevronDown aria-hidden size={14} />
          {detailsExpanded ? '收起任务详情' : '展开任务详情'}
        </button>
        <button onClick={() => onOpenTask(task)} type="button"><PanelsTopLeft aria-hidden size={14} />打开任务窗口</button>
      </div>
      <div className="paw-wb-detail__body">
        {detail ? <p className="paw-wb-detail__description">{detail}</p> : null}
        {progress !== null ? <section><h3>进度 · 真实比例</h3><strong>{taskProgressLabel(task)}</strong><span className="paw-wb-task-progress"><i style={{ width: `${Math.round(progress * 100)}%` }} /></span></section> : null}
        <dl>
          {text(task.owner) ? <Fact label="Owner" value={text(task.owner)} /> : null}
          {text(task.project) ? <Fact label="项目" value={text(task.project)} /> : null}
          {text(task.source) ? <Fact label="来源" value={text(task.source)} /> : null}
          <Fact label="状态" value={taskStateLabel(task)} />
        </dl>
        <section>
          <h3>依赖</h3>
          {dependencies.length ? <ol className="paw-wb-dependencies">{dependencies.map((id) => {
            const dependencyIndex = tasks.findIndex((candidate, index) => taskId(candidate, index) === id);
            const dependency = dependencyIndex >= 0 ? tasks[dependencyIndex] : null;
            return <li key={id}>{dependency ? (
              <button aria-label={`查看依赖任务：${taskTitle(dependency)}`} onClick={() => onSelectTask(dependency, dependencyIndex)} title={`${taskTitle(dependency)} · ${id}`} type="button">
                <ArrowRight aria-hidden size={13} />
                <span><strong>{taskTitle(dependency)}</strong><small className="paw-wb-mono">{id}</small></span>
              </button>
            ) : <span className="paw-wb-dependencies__unresolved" title={id}><ArrowRight aria-hidden size={13} /><span className="paw-wb-mono">{id}</span></span>}</li>;
          })}</ol> : <p className="paw-wb-detail__quiet">该任务记录没有声明依赖。</p>}
        </section>
      </div>
    </aside>
  );
}

function WorkDocumentWorkspace({
  documents,
  documentTotal,
  documentHistoryQuery,
  documentHistorySupported,
  documentLifecycle,
  documentScope,
  detailState,
  listState,
  onCloseDocument,
  onOpenDocument,
  onOpenDocumentWindow,
  onDocumentHistoryQueryChange,
  onDocumentScopeChange,
  onRefresh,
  projectName,
  selectedDocument,
}: {
  documents: readonly PawWorkbenchRecord[];
  documentTotal?: number;
  documentHistoryQuery: string;
  documentHistorySupported: boolean;
  documentLifecycle?: ReactNode;
  documentScope: PawWorkbenchDocumentScope;
  detailState?: PawWorkbenchResourceState;
  listState?: PawWorkbenchResourceState;
  onCloseDocument: () => void;
  onOpenDocument: PawWorkbenchMigratedProps['onOpenDocument'];
  onOpenDocumentWindow?: PawWorkbenchMigratedProps['onOpenDocumentWindow'];
  onDocumentHistoryQueryChange?: PawWorkbenchMigratedProps['onDocumentHistoryQueryChange'];
  onDocumentScopeChange?: PawWorkbenchMigratedProps['onDocumentScopeChange'];
  onRefresh?: PawWorkbenchMigratedProps['onRefresh'];
  projectName: string;
  selectedDocument: PawWorkbenchRecord | null;
}) {
  const resolvedDocumentTotal = Math.max(documents.length, documentTotal ?? 0);
  return (
    <div className="paw-wb-documents" data-reader-open={selectedDocument ? 'true' : undefined}>
      <aside className="paw-wb-document-index">
        <header><FileText aria-hidden size={16} /><strong>工作文档</strong><span title={`已载入 ${documents.length} / 共 ${resolvedDocumentTotal}`}>{resolvedDocumentTotal}</span></header>
        {onDocumentScopeChange ? (
          <div className="paw-wb-document-index__scope" role="group" aria-label="工作文档范围">
            <button aria-pressed={documentScope === 'active'} onClick={() => onDocumentScopeChange('active')} type="button">当前</button>
            <button aria-pressed={documentScope === 'history'} disabled={!documentHistorySupported} onClick={() => onDocumentScopeChange('history')} type="button">历史</button>
          </div>
        ) : null}
        {documentScope === 'history' && onDocumentHistoryQueryChange ? (
          <label className="paw-wb-document-index__search">
            <span>筛选历史</span>
            <input onChange={(event) => onDocumentHistoryQueryChange(event.target.value)} placeholder="标题、Authority 或路径" type="search" value={documentHistoryQuery} />
          </label>
        ) : null}
        <ResourceNotice label="工作文档" onRefresh={onRefresh ? () => onRefresh('documents') : undefined} state={listState} />
        {documents.length ? <ol>{documents.map((document, index) => <li key={documentId(document, index)}><button aria-current={sameDocument(document, selectedDocument) || undefined} onClick={() => void onOpenDocument(document)} title={`${documentTitle(document)} · ${text(document.activePath) || text(document.path) || text(document.authorityId)}`} type="button"><FileText aria-hidden size={15} /><span><strong>{documentTitle(document)}</strong><small>{authorityLabel(text(document.authorityKind))} · r{number(document.documentRevision)}</small></span><StatusMark lane={documentLane(document)} /></button></li>)}</ol> : resourceSettled(listState) ? <EmptyState icon={<FileText size={22} />} title={documentScope === 'history' ? '没有匹配的历史文档' : '暂无工作文档'} copy={documentScope === 'history' ? '调整筛选条件，或返回当前文档。' : '这里只投影 Runtime 已登记的文档。'} /> : null}
      </aside>

      <main className="paw-wb-document-reader">
        {selectedDocument ? (
          <>
            <header>
              <button aria-label="返回文档列表" onClick={onCloseDocument} type="button"><ChevronLeft aria-hidden size={17} /></button>
              <div><h2 title={documentTitle(selectedDocument)}>{documentTitle(selectedDocument)}</h2><p title={`${projectName} · ${authorityLabel(text(selectedDocument.authorityKind))}`}>{projectName} · {authorityLabel(text(selectedDocument.authorityKind))}</p></div>
              <div className="paw-wb-document-reader__actions">
                {onOpenDocumentWindow ? <button aria-label="在独立窗口打开文档" onClick={() => onOpenDocumentWindow(selectedDocument)} type="button"><PanelsTopLeft aria-hidden size={15} />独立窗口</button> : null}
                <StateBadge lane={documentLane(selectedDocument)} label={stateLabel(text(selectedDocument.state) || 'active')} />
              </div>
            </header>
            <ResourceNotice label="文档详情" onRefresh={onRefresh ? () => onRefresh('documentDetail') : undefined} state={detailState} />
            <section className="paw-wb-document-reader__authority">
              <ShieldCheck aria-hidden size={21} />
              <div><h2>权威绑定</h2><p>文档承载已接受语义；运行状态仍由对应 Runtime 对象负责。</p></div>
            </section>
            <dl className="paw-wb-document-facts">
              <Fact label="Authority" value={text(selectedDocument.authorityId) || '—'} mono />
              <Fact label="Authority kind" value={authorityLabel(text(selectedDocument.authorityKind))} />
              <Fact label="Authority revision" value={String(number(selectedDocument.authorityRevision))} />
              <Fact label="Document revision" value={String(number(selectedDocument.documentRevision))} />
              <Fact label="状态" value={stateLabel(text(selectedDocument.state) || 'active')} />
              <Fact label="更新时间" value={updatedLabel(number(selectedDocument.updatedAtMs))} />
              <Fact label="当前路径" value={text(selectedDocument.activePath) || text(selectedDocument.path) || '—'} mono wide />
              {text(selectedDocument.contentSha256) ? <Fact label="内容校验" titleValue={text(selectedDocument.contentSha256)} value={shortHash(text(selectedDocument.contentSha256))} mono wide /> : null}
            </dl>
            {text(selectedDocument.error) ? <div className="paw-wb-document-error"><CircleAlert aria-hidden size={16} /><span>{text(selectedDocument.error)}</span></div> : null}
            {resourceSettled(detailState) ? documentLifecycle : null}
          </>
        ) : <EmptyState icon={<ExternalLink size={25} />} title="选择一份工作文档" copy="详情只显示文档合同已有的权威、revision、路径与状态。" />}
      </main>

      <aside className="paw-wb-document-truth">
        <header><Network aria-hidden size={16} /><strong>事实边界</strong></header>
        <ul>
          <li><CheckCircle2 aria-hidden size={15} /><span>语义由 WorkDocument 保存</span></li>
          <li><CheckCircle2 aria-hidden size={15} /><span>机械状态来自 Runtime</span></li>
          <li><CheckCircle2 aria-hidden size={15} /><span>路径与 revision 原样投影</span></li>
        </ul>
        {selectedDocument ? <dl><Fact label="Document ID" value={text(selectedDocument.documentId) || text(selectedDocument.id) || '—'} mono /><Fact label="Authority key" value={text(selectedDocument.authorityKey) || '—'} mono /></dl> : null}
      </aside>
    </div>
  );
}

function ResourceNotice({ label, onRefresh, state }: { label: string; onRefresh?: () => void; state?: PawWorkbenchResourceState }) {
  if (!state?.loading && !state?.error) return null;
  return (
    <div className="paw-wb-resource-notice" data-error={state.error || undefined} role={state.error ? 'alert' : 'status'}>
      {state.loading ? <LoaderCircle aria-hidden className="paw-wb-spin" size={15} /> : <CircleAlert aria-hidden size={15} />}
      <span>{state.error || `正在读取${label}`}</span>
      {state.error && onRefresh ? <button onClick={onRefresh} type="button"><RefreshCw aria-hidden size={13} />重试</button> : null}
    </div>
  );
}

function EmptyState({ icon, title, copy }: { icon: ReactNode; title: string; copy: string }) {
  return <div className="paw-wb-empty">{icon}<strong>{title}</strong><p>{copy}</p></div>;
}

function resourceSettled(state?: PawWorkbenchResourceState): boolean {
  return !state?.loading && !state?.error;
}

function StatusMark({ lane }: { lane: TaskLane }) {
  return <i aria-hidden className="paw-wb-status-mark" data-lane={lane} />;
}

function StateBadge({ label, lane }: { label: string; lane: TaskLane }) {
  return <span className="paw-wb-state-badge" data-lane={lane}><StatusMark lane={lane} />{label}</span>;
}

function Fact({ label, mono = false, titleValue, value, wide = false }: { label: string; mono?: boolean; titleValue?: string; value: string; wide?: boolean }) {
  return <div data-wide={wide || undefined}><dt>{label}</dt><dd className={mono ? 'paw-wb-mono' : undefined} title={titleValue ?? value}>{value}</dd></div>;
}

function buildTaskGraph(tasks: PawWorkbenchRecord[]): { nodes: TaskGraphNode[]; edges: TaskGraphEdge[]; height: number; width: number } {
  const byLane = new Map<TaskLane, PawWorkbenchRecord[]>();
  for (const lane of GRAPH_LANES) byLane.set(lane, []);
  for (const task of tasks) byLane.get(taskLane(task))?.push(task);
  const nodes: TaskGraphNode[] = [];
  for (const task of tasks) {
    const lane = taskLane(task);
    const laneIndex = GRAPH_LANES.indexOf(lane);
    const rowIndex = byLane.get(lane)?.indexOf(task) ?? 0;
    nodes.push({
      id: taskId(task, tasks.indexOf(task)),
      lane,
      task,
      x: GRAPH_PADDING_X + laneIndex * (GRAPH_NODE_WIDTH + GRAPH_COLUMN_GAP),
      y: GRAPH_PADDING_Y + rowIndex * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP),
    });
  }
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const edges: TaskGraphEdge[] = [];
  for (const target of nodes) {
    for (const dependencyId of taskDependencyIds(target.task)) {
      const source = nodesById.get(dependencyId);
      if (!source) continue;
      const startX = source.x + GRAPH_NODE_WIDTH;
      const startY = source.y + GRAPH_NODE_HEIGHT / 2;
      const endX = target.x;
      const endY = target.y + GRAPH_NODE_HEIGHT / 2;
      const bend = Math.max(24, Math.abs(endX - startX) * .46);
      edges.push({
        id: `${source.id}:${target.id}`,
        path: `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`,
        active: target.lane === 'active',
      });
    }
  }
  const maxRows = Math.max(1, ...GRAPH_LANES.map((lane) => byLane.get(lane)?.length ?? 0));
  return {
    nodes,
    edges,
    height: GRAPH_PADDING_Y * 2 + maxRows * GRAPH_NODE_HEIGHT + Math.max(0, maxRows - 1) * GRAPH_ROW_GAP,
    width: GRAPH_PADDING_X * 2 + GRAPH_LANES.length * GRAPH_NODE_WIDTH + (GRAPH_LANES.length - 1) * GRAPH_COLUMN_GAP,
  };
}

function overviewMetrics(
  overview: PawWorkbenchRecord,
  planning: PawWorkbenchRecord,
  documents: readonly PawWorkbenchRecord[],
  documentsState?: PawWorkbenchResourceState,
): { label: string; value: string }[] {
  const metrics = record(overview.metrics);
  const summary = record(planning.summary);
  const candidates: [string, unknown][] = [
    ['活跃 Session', metrics.activeSessions ?? overview.activeSessions],
    ['开放任务', metrics.openTasks ?? summary.openTaskCount],
    ['已完成任务', summary.completedTaskCount],
    ['整体进度', percentage(summary.progress)],
    ['工作文档', documentsState?.loading || documentsState?.error ? undefined : documents.length],
  ];
  return candidates.flatMap(([label, value]) => value === undefined || value === null || value === '' ? [] : [{ label, value: scalar(value) }]);
}

function taskId(task: PawWorkbenchRecord, index: number): string {
  return text(task.id) || text(task.taskId) || `task-${index}`;
}

function taskTitle(task: PawWorkbenchRecord): string {
  return text(task.title) || text(task.objective) || '未命名任务';
}

function taskMeta(task: PawWorkbenchRecord): string {
  return [text(task.owner), text(task.project), text(task.source)].filter(Boolean).join(' · ') || '当前项目';
}

function taskLane(task: PawWorkbenchRecord): TaskLane {
  const value = (text(task.state) || text(task.status)).toLowerCase();
  if (['done', 'complete', 'completed', 'accepted', 'success'].includes(value)) return 'done';
  if (['review', 'verifying', 'verification', 'approval_pending', 'waiting_approval'].includes(value)) return 'review';
  if (['blocked', 'failed', 'error', 'cancelled'].includes(value)) return 'blocked';
  if (['todo', 'pending', 'queued', 'ready', 'idle', 'waiting'].includes(value)) return 'todo';
  return 'active';
}

function taskStateLabel(task: PawWorkbenchRecord): string {
  const raw = text(task.state) || text(task.status);
  if (raw) return stateLabel(raw);
  return { done: '已完成', active: '进行中', review: '待验收', blocked: '受阻', todo: '待办' }[taskLane(task)];
}

function taskDependencyIds(task: PawWorkbenchRecord): string[] {
  const values = [task.dependencies, task.dependsOn, task.dependencyIds, task.blockedBy];
  const ids = values.flatMap((value) => dependencyIds(value));
  return [...new Set(ids.filter(Boolean))];
}

function dependencyIds(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap((item) => dependencyIds(item));
  const item = record(value);
  const id = text(item.id) || text(item.taskId) || text(item.workItemId);
  return id ? [id] : [];
}

function taskProgress(task: PawWorkbenchRecord): number | null {
  const raw = task.progress ?? task.progressRatio ?? task.completion;
  if (typeof raw === 'number' && Number.isFinite(raw)) return clamp(raw > 1 ? raw / 100 : raw);
  const completed = number(task.completedCount) || number(task.completed);
  const total = number(task.totalCount) || number(task.total);
  if (total > 0) return clamp(completed / total);
  return null;
}

function taskProgressLabel(task: PawWorkbenchRecord): string {
  const progress = taskProgress(task);
  if (progress === null) return '';
  const completed = number(task.completedCount) || number(task.completed);
  const total = number(task.totalCount) || number(task.total);
  return total > 0 ? `${completed} / ${total}` : `${Math.round(progress * 100)}%`;
}

function taskIsGate(task: PawWorkbenchRecord): boolean {
  const kind = `${text(task.kind)} ${text(task.type)} ${text(task.status)}`.toLowerCase();
  return /approval|gate|审批/.test(kind);
}

function documentId(document: PawWorkbenchRecord, index: number): string {
  return text(document.documentId) || text(document.id) || `document-${index}`;
}

function documentTitle(document: PawWorkbenchRecord): string {
  return text(document.title) || '未命名文档';
}

function documentLane(document: PawWorkbenchRecord): TaskLane {
  const state = text(document.state);
  if (state === 'archived') return 'done';
  if (state === 'error') return 'blocked';
  if (state.endsWith('_pending')) return 'review';
  return 'active';
}

function sameDocument(document: PawWorkbenchRecord, selected: PawWorkbenchRecord | null): boolean {
  if (!selected) return false;
  return (text(document.documentId) || text(document.id)) === (text(selected.documentId) || text(selected.id));
}

function authorityLabel(value: string): string {
  return ({ session_todo: 'Session Todo', session_goal: 'Session Goal', room_work_item: 'Room WorkItem' } as Record<string, string>)[value] ?? (value || 'WorkDocument');
}

function stateLabel(value: string): string {
  return ({
    active: '进行中', in_progress: '进行中', running: '运行中', review: '待验收', verifying: '验证中',
    done: '已完成', complete: '已完成', completed: '已完成', accepted: '已接受', pending: '待办', queued: '排队中',
    ready: '已就绪', idle: '空闲', blocked: '受阻', failed: '失败', error: '错误', cancelled: '已取消',
    archive_pending: '等待归档', archived: '已归档', reopen_pending: '等待重开',
  } as Record<string, string>)[value] ?? value;
}

function updatedLabel(timestamp: number): string {
  if (!timestamp) return '未提供时间';
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(timestamp));
}

function shortHash(value: string): string {
  return value.length > 16 ? `${value.slice(0, 12)}…${value.slice(-4)}` : value;
}

function pathName(value: string): string {
  return value.split(/[\\/]/).filter(Boolean).at(-1) ?? '';
}

function percentage(value: unknown): string | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
  return `${Math.round((value > 1 ? value / 100 : value) * 100)}%`;
}

function scalar(value: unknown): string {
  return typeof value === 'number' ? new Intl.NumberFormat('zh-CN').format(value) : String(value);
}

function rows(envelope: PawWorkbenchRecord, keys: string[]): PawWorkbenchRecord[] {
  for (const key of keys) if (Array.isArray(envelope[key])) return (envelope[key] as unknown[]).map(record);
  return [];
}

function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function number(value: unknown): number { return typeof value === 'number' && Number.isFinite(value) ? value : 0; }
function record(value: unknown): PawWorkbenchRecord { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as PawWorkbenchRecord : {}; }
function clamp(value: number): number { return Math.max(0, Math.min(1, value)); }
