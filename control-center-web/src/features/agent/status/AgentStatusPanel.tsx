import {
  Bot,
  BookOpenText,
  Check,
  ChevronRight,
  CircleDashed,
  FileText,
  FolderKanban,
  ExternalLink,
  ListChecks,
  LoaderCircle,
  Paperclip,
  PanelRightClose,
  Search,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { forwardRef, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  IconButton,
} from '@/components/primitives';
import type { AgentActivityProjection, AgentProjectionState, AgentTurnStatus } from '@/contracts/agent-reducer';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import { useAgentLiveStore } from '../state/live-store';
import { publicToolResultView } from '../timeline/public-tool-result';

export const AgentStatusPanel = forwardRef<HTMLElement, {
  sessionId: string;
  open: boolean;
  modal?: boolean;
  onClose: () => void;
}>(function AgentStatusPanel({
  sessionId,
  open,
  modal = false,
  onClose,
}, ref) {
  const transport = useControlTransport();
  const projection = useAgentLiveStore((state) => state.projections[sessionId]);
  const view = useMemo(() => projectStatusPanel(projection), [projection]);
  const subagents = useQuery({
    queryKey: ['agent', 'status-panel', 'subagents', sessionId],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.subagents.list',
      query: { sessionId, limit: 50 },
      signal,
    }),
    enabled: open && Boolean(sessionId),
    refetchInterval: open
      ? (query) => hasActiveSubagentRuns(subagentRuns(query.state.data)) ? 1_000 : 5_000
      : false,
    retry: false,
  });
  const runs = useMemo(() => subagentRuns(subagents.data), [subagents.data]);

  return (
    <aside
      ref={ref}
      className="agent-status-panel"
      data-open={open}
      aria-hidden={!open}
      aria-label="当前对话状态"
      aria-modal={modal || undefined}
      inert={open ? undefined : true}
      role={modal ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header>
        <span><strong>状态</strong><small>{view.turn ? turnStatusLabel(view.turn.status) : '等待新回合'}</small></span>
        <IconButton icon={<PanelRightClose size={17} />} label="收起状态面板" onClick={onClose} tooltip />
      </header>
      <div className="agent-status-panel__body">
        <StatusSection icon={ListChecks} title="当前回合" count={view.tasks.length}>
          {view.turn ? (
            <div className="agent-status-turn" data-state={view.turn.status}>
              <TurnStateIcon status={view.turn.status} />
              <span><strong>{turnStatusLabel(view.turn.status)}</strong><small>{turnProgressLabel(view)}</small></span>
            </div>
          ) : <EmptyLine>还没有可展示的回合状态</EmptyLine>}
          {view.tasks.length ? (
            <ol className="agent-status-tasks">
              {view.tasks.map((task) => (
                <li key={task.id} data-state={task.status}>
                  <TaskStateIcon status={task.status} />
                  <span>{task.label}</span>
                </li>
              ))}
            </ol>
          ) : null}
        </StatusSection>

        <StatusSection icon={Wrench} title="关键步骤" count={view.tools.length}>
          {view.tools.length ? (
            <div className="agent-status-tools">
              {view.tools.map((tool) => <ToolStep key={tool.id} activity={tool} />)}
            </div>
          ) : <EmptyLine>本轮还没有工具步骤</EmptyLine>}
        </StatusSection>

        <StatusSection icon={Paperclip} title="附件与文件" count={view.files.length + view.attachmentCount}>
          {view.files.length || view.attachmentCount ? (
            <div className="agent-status-files">
              {view.attachmentCount ? <StatusRow icon={Paperclip} title={`${view.attachmentCount} 个受管附件`} detail="随会话消息保存" /> : null}
              {view.files.map((file) => <StatusRow key={file.id} icon={FileText} title={file.name} detail={file.kind} />)}
            </div>
          ) : <EmptyLine>当前会话没有附件或文件</EmptyLine>}
        </StatusSection>

        <StatusSection icon={FolderKanban} title="产物" count={view.artifacts.length + runs.filter((run) => run.artifact).length}>
          {view.artifacts.length || runs.some((run) => run.artifact) ? (
            <div className="agent-status-files">
              {view.artifacts.map((artifact) => <StatusRow key={artifact.id} icon={FolderKanban} title={artifact.name} detail={artifact.kind} />)}
              {runs.filter((run) => run.artifact).map((run) => <StatusRow key={`artifact:${run.id}`} icon={FolderKanban} title={`${templateLabel(run.templateId)}协作产物`} detail={stateLabel(run.state)} />)}
            </div>
          ) : <EmptyLine>本轮还没有可交付产物</EmptyLine>}
        </StatusSection>

        <StatusSection icon={Bot} title="子智能体" count={runs.length}>
          {subagents.isPending ? <EmptyLine animated>正在读取协作状态</EmptyLine> : null}
          {subagents.error ? <EmptyLine tone="danger">子智能体状态暂时不可用</EmptyLine> : null}
          {!subagents.isPending && !subagents.error && runs.length === 0 ? <EmptyLine>当前会话没有委派任务</EmptyLine> : null}
          {runs.length ? (
            <div className="agent-status-subagents">
              {runs.map((run) => <SubagentRow key={run.id} run={run} sessionId={sessionId} />)}
            </div>
          ) : null}
        </StatusSection>
      </div>
    </aside>
  );
});

function StatusSection({
  icon: Icon,
  title,
  count,
  children,
}: {
  icon: LucideIcon;
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="agent-status-section">
      <header><Icon size={15} /><strong>{title}</strong>{count > 0 ? <span>{count}</span> : null}</header>
      {children}
    </section>
  );
}

function ToolStep({ activity }: { activity: AgentActivityProjection }) {
  const view = publicToolResultView(activity);
  const knowledge = view.toolLabel === '文档知识库';
  const stateIcon = activity.status === 'running'
    ? <LoaderCircle size={14} />
    : activity.status === 'waiting'
      ? <CircleDashed size={14} />
      : activity.status === 'failed'
        ? <TriangleAlert size={14} />
        : knowledge
          ? <Search size={14} />
          : <Wrench size={14} />;
  return (
    <details className="agent-status-tool" data-state={activity.status}>
      <summary>
        <span className="agent-status-tool__icon">{stateIcon}</span>
        <span><strong>{knowledge ? '知识库' : view.toolLabel}</strong><small>{view.summary}</small></span>
        <i>{view.sources.length ? `来源 ${view.sources.length} · ` : ''}{activityStatusLabel(activity.status)}</i>
        <ChevronRight size={14} />
      </summary>
      <div>
        {view.fields.slice(0, 5).map((field) => <p key={field.id}><span>{field.label}</span><strong>{field.value}</strong></p>)}
        {view.sources.length ? (
          <section className="agent-status-tool__sources">
            <strong><BookOpenText size={13} />信息来源</strong>
            <ul aria-label={`${view.toolLabel}公开来源`}>
              {view.sources.map((source) => <li key={source}>{source}</li>)}
            </ul>
          </section>
        ) : null}
        {view.destination ? (
          <a className="agent-tool-destination" href={view.destination.href}>
            {view.destination.label}<ExternalLink size={13} aria-hidden="true" />
          </a>
        ) : null}
      </div>
    </details>
  );
}

function SubagentRow({ run, sessionId }: { run: AgentSubagentRunV1; sessionId: string }) {
  const active = run.state === 'queued' || run.state === 'running';
  const elapsed = useRunElapsed(run);
  return (
    <div className="agent-status-subagent" data-state={run.state}>
      <span className="agent-status-subagent__state"><SubagentStateIcon state={run.state} /></span>
      <span><strong>{templateLabel(run.templateId)}</strong><small>{publicText(run.task, '协作任务')}</small></span>
      <i><span>{stateLabel(run.state)}</span>{elapsed ? <time>{elapsed}</time> : null}</i>
      <SubagentResultDialog run={run} sessionId={sessionId} triggerLabel={active ? '查看进度' : '查看结果'} />
    </div>
  );
}

function SubagentResultDialog({ run, sessionId, triggerLabel }: { run: AgentSubagentRunV1; sessionId: string; triggerLabel: string }) {
  const transport = useControlTransport();
  const [open, setOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState('');
  const detail = useQuery({
    queryKey: ['agent', 'status-panel', 'subagent', sessionId, run.id],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.subagent.get',
      params: { runId: run.id },
      query: { sessionId },
      signal,
    }),
    enabled: open,
    refetchInterval: (query) => {
      const latest = findSubagentRun(query.state.data, run.id) ?? run;
      return isActiveSubagentRun(latest) ? 1_000 : false;
    },
    retry: false,
  });
  const current = findSubagentRun(detail.data, run.id) ?? run;
  const summary = publicResultSummary(current.result);
  const active = current.state === 'queued' || current.state === 'running';
  const artifactId = current.artifact?.artifactId ?? '';
  const artifact = useQuery({
    queryKey: ['agent', 'status-panel', 'artifact', sessionId, artifactId],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.artifact.get',
      params: { artifactId },
      query: { sessionId, limit: 60 },
      signal,
    }),
    enabled: open && Boolean(artifactId),
    refetchInterval: open && active ? 1_500 : false,
    retry: false,
  });
  const records = publicArtifactRecords(artifact.data);

  async function stopRun(): Promise<void> {
    if (!active || stopping) return;
    setStopping(true);
    setStopError('');
    try {
      await transport.request({ pathId: 'agent.subagent.abort', params: { runId: current.id }, body: { sessionId } });
      await detail.refetch();
    } catch {
      setStopError('任务暂时无法停止，请稍后重试。');
    } finally {
      setStopping(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="small" variant="quiet">{triggerLabel}</Button></DialogTrigger>
      <DialogContent className="agent-subagent-result-dialog">
        <DialogHeader>
          <DialogTitle>{templateLabel(current.templateId)} · {stateLabel(current.state)}</DialogTitle>
          <DialogDescription>{publicText(current.task, '协作任务')}</DialogDescription>
        </DialogHeader>
        <div className="agent-subagent-result">
          {detail.isPending ? <EmptyLine animated>正在读取最新结果</EmptyLine> : null}
          {detail.error ? <EmptyLine tone="danger">最新结果暂时无法读取</EmptyLine> : null}
          {!detail.isPending ? <p>{summary || terminalResultFallback(current.state)}</p> : null}
          <dl>
            <div><dt>回合</dt><dd>{current.usage.turnCount}</dd></div>
            <div><dt>工具</dt><dd>{current.usage.toolCount}</dd></div>
            <div><dt>Token</dt><dd>{current.usage.totalTokens}</dd></div>
            <div><dt>产物</dt><dd>{current.artifact ? '已记录' : '无'}</dd></div>
          </dl>
          {artifactId ? (
            <details className="agent-subagent-artifact">
              <summary><BookOpenText size={14} /><span>运行记录</span><small>{records.length ? `${records.length} 条` : '读取中'}</small><ChevronRight size={14} /></summary>
              {artifact.isPending ? <EmptyLine animated>正在读取审计记录</EmptyLine> : null}
              {artifact.error ? <EmptyLine tone="danger">运行记录暂时不可用</EmptyLine> : null}
              {records.length ? <ol>{records.map((record) => <li key={record.id}><time>{record.time}</time><span><strong>{record.label}</strong><small>{record.detail}</small></span></li>)}</ol> : null}
            </details>
          ) : null}
          {stopError ? <p className="agent-subagent-result__error" role="alert">{stopError}</p> : null}
          {active ? <div className="agent-subagent-result__actions"><Button loading={stopping} onClick={() => void stopRun()} variant="danger">停止任务</Button></div> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function StatusRow({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return <div className="agent-status-row"><Icon size={14} /><span><strong>{title}</strong><small>{detail}</small></span></div>;
}

function EmptyLine({ children, animated = false, tone = 'neutral' }: { children: ReactNode; animated?: boolean; tone?: 'neutral' | 'danger' }) {
  return <p className="agent-status-empty" data-animated={animated || undefined} data-tone={tone}>{animated ? <LoaderCircle size={13} /> : null}{children}</p>;
}

function TurnStateIcon({ status }: { status: AgentTurnStatus }) {
  if (status === 'queued' || status === 'running') return <LoaderCircle size={15} />;
  if (status === 'waiting') return <CircleDashed size={15} />;
  if (status === 'failed') return <TriangleAlert size={15} />;
  return <Check size={15} />;
}

function TaskStateIcon({ status }: { status: string }) {
  if (status === 'running') return <LoaderCircle size={13} />;
  if (status === 'completed') return <Check size={13} />;
  if (status === 'failed') return <TriangleAlert size={13} />;
  return <CircleDashed size={13} />;
}

function SubagentStateIcon({ state }: { state: AgentSubagentRunV1['state'] }) {
  if (state === 'running') return <LoaderCircle size={15} />;
  if (state === 'queued') return <CircleDashed size={15} />;
  if (state === 'completed') return <Check size={15} />;
  return <TriangleAlert size={15} />;
}

function useRunElapsed(run: AgentSubagentRunV1): string {
  const active = run.state === 'queued' || run.state === 'running';
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active]);
  if (!active) return '';
  const startedAt = run.startedAtMs ?? run.createdAtMs;
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1_000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}分${String(seconds % 60).padStart(2, '0')}秒` : `${seconds}秒`;
}

function publicArtifactRecords(value: unknown): Array<{ id: string; label: string; detail: string; time: string }> {
  const items = Array.isArray(record(value).records) ? record(value).records as unknown[] : [];
  return items.slice(-60).map((item, index) => {
    const entry = record(item);
    const payload = record(entry.payload);
    const eventType = text(entry.eventType);
    const createdAtMs = Number(entry.createdAtMs);
    return {
      id: text(entry.recordId) || `${eventType}:${index}`,
      label: artifactEventLabel(eventType),
      detail: publicText(payload.summary ?? payload.message ?? payload.reason ?? payload.state, '状态已记录'),
      time: Number.isFinite(createdAtMs) && createdAtMs > 0
        ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(createdAtMs)
        : '--:--:--',
    };
  });
}

function artifactEventLabel(value: string): string {
  return ({
    queued: '已进入队列',
    started: '开始执行',
    checkpoint: '保存检查点',
    supervision_soft: '接近运行预算',
    supervision_hard: '触发停止保护',
    supervision_forced: '已强制停止',
    completed: '执行完成',
    failed: '执行失败',
    aborted: '用户已停止',
    timed_out: '执行超时',
    runtime_retired: '临时运行环境已清理',
  } as Record<string, string>)[value] ?? '运行状态更新';
}

interface StatusPanelProjection {
  turn?: AgentProjectionState['turnsById'][string];
  tasks: Array<{ id: string; label: string; status: string }>;
  tools: AgentActivityProjection[];
  files: Array<{ id: string; name: string; kind: string }>;
  artifacts: Array<{ id: string; name: string; kind: string }>;
  attachmentCount: number;
}

export function projectStatusPanel(projection?: AgentProjectionState): StatusPanelProjection {
  if (!projection) return { tasks: [], tools: [], files: [], artifacts: [], attachmentCount: 0 };
  const turn = [...projection.turnOrder].reverse()
    .map((id) => projection.turnsById[id])
    .find((item) => item && (item.messageIds.length > 0 || item.activityIds.length > 0));
  if (!turn) return { tasks: [], tools: [], files: [], artifacts: [], attachmentCount: 0 };
  const messages = turn.messageIds.map((id) => projection.messagesById[id]).filter(Boolean);
  const tasks: StatusPanelProjection['tasks'] = [];
  const files: StatusPanelProjection['files'] = [];
  const artifacts: StatusPanelProjection['artifacts'] = [];
  const attachmentIds = new Set<string>();
  for (const message of messages) {
    message.attachments.forEach((id) => attachmentIds.add(id));
    for (const block of message.blocks) {
      if (block.type === 'task_plan') {
        const items = Array.isArray(block.data.items) ? block.data.items : Array.isArray(block.data.tasks) ? block.data.tasks : [];
        items.slice(0, 12).forEach((item, index) => {
          const value = record(item);
          tasks.push({
            id: `${block.id}:${index}`,
            label: publicText(value.title ?? value.label ?? item, `步骤 ${index + 1}`),
            status: taskStatus(text(value.status)),
          });
        });
      }
      if (block.type === 'file') {
        const name = publicFileName(block.data.name ?? block.data.fileName ?? block.data.title);
        if (name) files.push({ id: block.id, name, kind: publicText(block.data.mimeType, '文件') });
        if (name && text(block.data.receiptId ?? block.data.artifactId)) artifacts.push({ id: `artifact:${block.id}`, name, kind: '文件产物' });
      }
      if (block.type === 'diff') {
        const name = publicFileName(block.data.fileName ?? block.data.title);
        if (name) artifacts.push({ id: `diff:${block.id}`, name, kind: '变更产物' });
      }
    }
  }
  const tools = turn.activityIds
    .map((id) => projection.activitiesById[id])
    .filter((activity): activity is AgentActivityProjection => Boolean(activity && activity.kind.startsWith('tool_')));
  for (const activity of tools) {
    if (text(activity.payload.toolId ?? activity.payload.toolName) !== 'agent_plan') continue;
    planItemsFromActivity(activity).slice(0, 12).forEach((item, index) => {
      const value = record(item);
      tasks.push({
        id: `agent-plan:${text(value.id ?? value.itemId) || index}`,
        label: publicText(value.title ?? value.label, `步骤 ${index + 1}`),
        status: taskStatus(text(value.status)),
      });
    });
  }
  return {
    turn,
    tasks: uniqueBy(tasks, (item) => item.id),
    tools,
    files: uniqueBy(files, (item) => item.name),
    artifacts: uniqueBy(artifacts, (item) => item.name),
    attachmentCount: attachmentIds.size,
  };
}

function planItemsFromActivity(activity: AgentActivityProjection): unknown[] {
  const payload = record(activity.payload);
  const result = record(payload.result ?? payload.partialResult);
  const details = record(result.details);
  const detailResult = record(details.result);
  const directResult = record(result.result);
  const layers = [detailResult, directResult, details, result, payload];
  for (const layer of layers) {
    if (Array.isArray(layer.items)) return layer.items;
    const plan = record(layer.plan);
    if (Array.isArray(plan.items)) return plan.items;
  }
  return [];
}

function subagentRuns(value: unknown): AgentSubagentRunV1[] {
  const source = Array.isArray(record(value).items) ? record(value).items as unknown[] : [];
  const runs = source.flatMap((batch) => Array.isArray(record(batch).runs) ? record(batch).runs as unknown[] : []);
  return runs.filter(isSubagentRun);
}

function isActiveSubagentRun(run: AgentSubagentRunV1): boolean {
  return run.state === 'queued' || run.state === 'running';
}

function hasActiveSubagentRuns(runs: AgentSubagentRunV1[]): boolean {
  return runs.some(isActiveSubagentRun);
}

function findSubagentRun(value: unknown, runId: string): AgentSubagentRunV1 | undefined {
  const batch = record(record(value).batch);
  const runs = Array.isArray(batch.runs) ? batch.runs : [];
  return runs.find((item) => isSubagentRun(item) && item.id === runId) as AgentSubagentRunV1 | undefined;
}

function isSubagentRun(value: unknown): value is AgentSubagentRunV1 {
  const item = record(value);
  const usage = record(item.usage);
  const templates: AgentSubagentRunV1['templateId'][] = ['researcher', 'planner', 'worker', 'reviewer', 'delegate'];
  return item.schemaVersion === 'rag-ime.agent-subagent-run.v1'
    && typeof item.id === 'string'
    && typeof item.task === 'string'
    && templates.includes(item.templateId as AgentSubagentRunV1['templateId'])
    && ['queued', 'running', 'completed', 'failed', 'aborted', 'timed_out'].includes(text(item.state))
    && Number.isFinite(usage.turnCount)
    && Number.isFinite(usage.toolCount)
    && Number.isFinite(usage.totalTokens);
}

function turnProgressLabel(view: StatusPanelProjection): string {
  if (!view.turn) return '';
  if (view.tasks.length) {
    const completed = view.tasks.filter((task) => task.status === 'completed').length;
    return `${completed} / ${view.tasks.length} 项待办已完成`;
  }
  if (view.tools.length) {
    const completed = view.tools.filter((tool) => tool.status === 'completed').length;
    return `${completed} / ${view.tools.length} 个关键步骤已完成`;
  }
  return view.turn.status === 'queued' || view.turn.status === 'running' ? '正在等待下一条可公开进度' : '本轮没有结构化待办';
}

function turnStatusLabel(status: AgentTurnStatus): string {
  return ({ queued: '排队中', running: '正在生成', waiting: '等待确认', completed: '已完成', failed: '未完成', aborted: '已停止' })[status];
}

function taskStatus(value: string): string {
  if (['completed', 'done', 'success'].includes(value)) return 'completed';
  if (['running', 'in_progress', 'active'].includes(value)) return 'running';
  if (['failed', 'error'].includes(value)) return 'failed';
  return 'queued';
}

function activityStatusLabel(status: AgentActivityProjection['status']): string {
  return ({ running: '进行中', waiting: '待确认', completed: '完成', failed: '失败' })[status];
}

function templateLabel(value: AgentSubagentRunV1['templateId']): string {
  return ({ researcher: '研究员', planner: '规划员', worker: '执行者', reviewer: '审阅者', delegate: '协作者' })[value];
}

function stateLabel(value: AgentSubagentRunV1['state']): string {
  return ({ queued: '排队中', running: '进行中', completed: '已完成', failed: '失败', aborted: '已停止', timed_out: '已超时' })[value];
}

function terminalResultFallback(state: AgentSubagentRunV1['state']): string {
  if (state === 'queued') return '任务正在等待执行。';
  if (state === 'running') return '任务仍在执行，结果会持续更新。';
  if (state === 'completed') return '任务已完成，最终结论已回到主对话。';
  return '任务没有生成可公开的结果摘要。';
}

function publicResultSummary(value: Record<string, unknown>): string {
  return publicText(value.summary ?? value.title ?? value.message, '');
}

function publicText(value: unknown, fallback: string): string {
  const normalized = text(value).replace(/\s+/gu, ' ').trim().slice(0, 280);
  if (!normalized) return fallback;
  if (/(?:chain.of.thought|reasoning|api.?key|authorization|cookie|password|secret|bearer\s)/iu.test(normalized)) return fallback;
  return normalized.replace(/\/(?:Users|Volumes|private|tmp)\/[^\s,;，。]+/gu, '[本地路径]');
}

function publicFileName(value: unknown): string {
  const normalized = text(value).replace(/\s+/gu, ' ').trim().slice(0, 180);
  if (!normalized || /[\\/]/u.test(normalized)) return '';
  if (/(?:api.?key|authorization|cookie|password|secret)/iu.test(normalized)) return '';
  return normalized;
}

function uniqueBy<T>(items: T[], key: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const value = key(item);
    if (seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
