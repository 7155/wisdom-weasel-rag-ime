import {
  Bot,
  BookOpenText,
  Check,
  ChevronRight,
  CircleDashed,
  FileText,
  FolderKanban,
  Gauge,
  ExternalLink,
  ListChecks,
  LoaderCircle,
  MessagesSquare,
  Paperclip,
  PanelRightClose,
  Radar,
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
  IconButton,
} from '@/components/primitives';
import type { AgentActivityProjection, AgentProjectionState, AgentTurnStatus } from '@/contracts/agent-reducer';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import { useAgentLiveStore } from '../state/live-store';
import { publicToolResultView } from '../timeline/public-tool-result';
import { ContextRuntimeSections } from './ContextRuntimePanel';
import { AgentWorkflowPanel } from './AgentWorkflowPanel';
import { ContextXraySections } from './ContextXrayPanel';
import { SubagentConsoleDialog } from './SubagentConsole';

type IdleWindow = Window & typeof globalThis & {
  requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
  cancelIdleCallback?: (handle: number) => void;
};

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
  const contentReady = useDeferredStatusContent(open);
  const projection = useAgentLiveStore((state) => state.projections[sessionId]);
  const view = useMemo(() => projectStatusPanel(projection), [projection]);
  const panelStatus = statusPanelLabel(projection, view);
  const subagents = useQuery({
    queryKey: ['agent', 'status-panel', 'subagents', sessionId],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.subagents.list',
      query: { sessionId, limit: 50 },
      signal,
    }),
    enabled: open && contentReady && Boolean(sessionId),
    refetchInterval: open && contentReady
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
        <span><strong>状态</strong><small>{panelStatus}</small></span>
        <IconButton icon={<PanelRightClose size={17} />} label="收起状态面板" onClick={onClose} tooltip />
      </header>
      {contentReady ? <div className="agent-status-panel__body">
        <AgentWorkflowPanel
          sessionId={sessionId}
          fallbackPlan={projection?.plan}
          fallbackGoal={projection?.goal}
          fallbackActGate={projection?.actGate}
        />
        {view.turn ? (
          <div className="agent-status-turn agent-plan-turn-summary" data-state={view.turn.status}>
            <TurnStateIcon status={view.turn.status} />
            <span><strong>当前回合 · {turnStatusLabel(view.turn.status)}</strong><small>{turnProgressLabel(view)}</small></span>
          </div>
        ) : !projection ? (
          <StatusSection icon={ListChecks} title="执行进度" count={view.tasks.length}>
            <EmptyLine>还没有可展示的回合状态</EmptyLine>
          </StatusSection>
        ) : null}

        <StatusSection icon={MessagesSquare} title="消息队列" count={(projection?.messageQueue.steering.length ?? 0) + (projection?.messageQueue.followUp.length ?? 0)}>
          <MessageQueueView projection={projection} />
        </StatusSection>

        <StatusSection icon={Gauge} title="上下文与用量" count={projection?.telemetry?.compactionCount ?? 0}>
          <SessionTelemetryView projection={projection} />
        </StatusSection>
        <ContextXraySections sessionId={sessionId} open={open} />

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
        <ContextRuntimeSections sessionId={sessionId} open={open} />

        <a
          className="agent-status-observation-link"
          href={`#/observability?sessionId=${encodeURIComponent(sessionId)}`}
        >
          <Radar size={16} />
          <span><strong>运行观察</strong><small>查看本会话的工具、检索与记忆轨迹</small></span>
          <ChevronRight size={15} />
        </a>
      </div> : <div aria-hidden="true" className="agent-status-panel__body agent-status-panel__body--pending" />}
    </aside>
  );
});

function useDeferredStatusContent(open: boolean): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!open) {
      setReady(false);
      return;
    }
    const idleWindow = window as IdleWindow;
    let secondFrame = 0;
    let idleHandle = 0;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        if (idleWindow.requestIdleCallback) {
          idleHandle = idleWindow.requestIdleCallback(() => setReady(true), { timeout: 120 });
        } else {
          idleHandle = window.setTimeout(() => setReady(true), 0);
        }
      });
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame) window.cancelAnimationFrame(secondFrame);
      if (idleHandle) {
        if (idleWindow.cancelIdleCallback) idleWindow.cancelIdleCallback(idleHandle);
        else window.clearTimeout(idleHandle);
      }
    };
  }, [open]);
  return ready;
}

function SessionTelemetryView({ projection }: { projection?: AgentProjectionState }) {
  const telemetry = projection?.telemetry;
  if (!telemetry) return <EmptyLine>发送一轮消息后显示上下文与缓存数据</EmptyLine>;
  const context = telemetry.context;
  const cumulative = telemetry.cumulativeUsage;
  const promptTokens = cumulative.input + cumulative.cacheRead + cumulative.cacheWrite;
  const cachePercent = promptTokens > 0 ? Math.round((cumulative.cacheRead / promptTokens) * 100) : 0;
  const percent = context.percent === null ? null : Math.min(100, Math.max(0, context.percent));
  return (
    <div className="agent-session-telemetry" data-compacting={telemetry.isCompacting || undefined}>
      <div className="agent-session-telemetry__model">
        <span><strong>{telemetry.model.name || telemetry.model.id}</strong><small>{telemetry.model.provider}</small></span>
        {telemetry.isCompacting ? <i><LoaderCircle size={13} />压缩中</i> : null}
      </div>
      <div className="agent-session-telemetry__usage" aria-label="会话累计 Token 用量">
        <span><small>输入</small><strong>{formatTokenCount(promptTokens)}</strong></span>
        <span><small>输出</small><strong>{formatTokenCount(cumulative.output)}</strong></span>
        <span><small>缓存</small><strong data-cache={cachePercent > 0 || undefined}>{cachePercent}%</strong></span>
      </div>
      <div className="agent-session-telemetry__context">
        <div>
          <span><strong>上下文</strong><small>{percent === null ? '待下一轮校准' : `${formatTokenCount(context.tokens ?? 0)} / ${formatTokenCount(context.contextWindow)}`}</small></span>
          <b>{percent === null ? '—' : `${Math.round(percent)}%`}</b>
        </div>
        <div className="agent-session-telemetry__track" aria-hidden="true">
          <span style={{ width: `${percent ?? 0}%` }} />
          {context.contextWindow > 0 ? <i style={{ left: `${Math.min(100, (context.compactAtTokens / context.contextWindow) * 100)}%` }} /> : null}
        </div>
        <p>
          {context.tokensUntilCompact === null
            ? '刚完成压缩，下一轮模型响应后恢复精确计量'
            : context.autoCompactEnabled
              ? `距自动压缩约 ${formatTokenCount(context.tokensUntilCompact)}`
              : `剩余上下文 ${formatTokenCount(context.remainingTokens ?? 0)} · 自动压缩已关闭`}
        </p>
      </div>
      {telemetry.latestCompaction ? (
        <div className="agent-session-telemetry__compaction" data-state={telemetry.latestCompaction.status}>
          <LoaderCircle size={14} data-running={telemetry.latestCompaction.status === 'running' || undefined} />
          <span><strong>{telemetry.latestCompaction.status === 'running' ? '正在压缩' : `已压缩 ${telemetry.compactionCount} 次`}</strong><small>{compactionSummary(telemetry.latestCompaction)}</small></span>
        </div>
      ) : null}
    </div>
  );
}

function MessageQueueView({ projection }: { projection?: AgentProjectionState }) {
  const steering = projection?.messageQueue.steering ?? [];
  const followUp = projection?.messageQueue.followUp ?? [];
  if (!steering.length && !followUp.length) return <EmptyLine>当前没有待处理消息</EmptyLine>;
  return (
    <ol className="agent-status-message-queue">
      {steering.map((message, index) => <li key={`steer:${index}:${message}`}><b>干预</b><span>{message}</span></li>)}
      {followUp.map((message, index) => <li key={`follow:${index}:${message}`}><b>接续</b><span>{message}</span></li>)}
    </ol>
  );
}

function compactionSummary(value: NonNullable<NonNullable<AgentProjectionState['telemetry']>['latestCompaction']>): string {
  if (value.status === 'running') return '正在生成精简摘要';
  if (value.tokensBefore && value.estimatedTokensAfter) {
    return `${formatTokenCount(value.tokensBefore)} → 约 ${formatTokenCount(value.estimatedTokensAfter)}`;
  }
  return value.status === 'failed' ? '压缩未完成' : '下一轮响应后校准占用';
}

function formatTokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(Math.max(0, Math.round(value)));
}

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
  const argumentFieldCount = Object.keys(record(activity.payload.args)).length;
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
        <p className="agent-status-tool__interface"><span>接口</span><code>{view.toolId || 'unknown'}</code></p>
        {view.operation ? <p><span>操作</span><code>{view.operation}</code></p> : null}
        <p><span>参数</span><strong>{argumentFieldCount} 个字段</strong></p>
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
      <SubagentConsoleDialog run={run} sessionId={sessionId} triggerLabel={active ? '查看进度' : '查看结果'} />
    </div>
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
  const durableTasks: StatusPanelProjection['tasks'] = projection.plan.items.slice(0, 100).map((item) => ({
    id: `agent-plan:${item.id}`,
    label: item.title,
    status: taskStatus(item.status),
  }));
  if (!turn) return { tasks: durableTasks, tools: [], files: [], artifacts: [], attachmentCount: 0 };
  const messages = turn.messageIds.map((id) => projection.messagesById[id]).filter(Boolean);
  const tasks: StatusPanelProjection['tasks'] = [...durableTasks];
  const files: StatusPanelProjection['files'] = [];
  const artifacts: StatusPanelProjection['artifacts'] = [];
  const attachmentIds = new Set<string>();
  for (const message of messages) {
    message.attachments.forEach((id) => attachmentIds.add(id));
    for (const block of message.blocks) {
      if (block.type === 'task_plan' && tasks.length === 0) {
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
    .filter((activity): activity is AgentActivityProjection => Boolean(
      activity
      && activity.kind.startsWith('tool_')
      && text(activity.payload.toolId ?? activity.payload.toolName) !== 'agent_plan',
    ));
  return {
    turn,
    tasks: uniqueBy(tasks, (item) => item.id),
    tools,
    files: uniqueBy(files, (item) => item.name),
    artifacts: uniqueBy(artifacts, (item) => item.name),
    attachmentCount: attachmentIds.size,
  };
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

function statusPanelLabel(
  projection: AgentProjectionState | undefined,
  view: StatusPanelProjection,
): string {
  const plan = projection?.plan;
  if (plan?.items.length) {
    if (plan.counts.completed === plan.counts.total) return '计划已完成';
    if (plan.counts.inProgress > 0) return `执行中 · ${plan.counts.completed}/${plan.counts.total}`;
    return `待执行 · ${plan.counts.completed}/${plan.counts.total}`;
  }
  return view.turn ? turnStatusLabel(view.turn.status) : '等待新回合';
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
