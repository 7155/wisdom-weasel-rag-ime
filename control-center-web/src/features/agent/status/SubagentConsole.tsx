import {
  Bot,
  Check,
  CircleDashed,
  Clock3,
  ListChecks,
  LoaderCircle,
  MessageSquareText,
  OctagonX,
  Play,
  RefreshCw,
  Send,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/primitives';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import './SubagentConsole.css';
import {
  INVALID_SUBAGENT_CONTRACT_NOTICE,
  isContractInvalid,
  isUnverifiedReturn,
  subagentPresentationState,
  subagentStateLabel,
  UNVERIFIED_SUBAGENT_NOTICE,
} from './subagent-presentation';

type ConsoleTab = 'overview' | 'conversation' | 'activity' | 'inbox';
type ControlAction = 'steer' | 'retry' | 'resume' | 'abort' | 'reply';

interface ConsoleCapability {
  available: boolean;
  reason: string;
}

interface ConsoleInboxItem {
  id: string;
  kind: 'need_decision' | 'interview' | 'progress';
  title: string;
  message: string;
  status: 'pending' | 'replied' | 'observed';
  createdAtMs: number;
}

interface ConsoleActivity {
  id: string;
  eventType: string;
  createdAtMs: number;
  payload: Record<string, unknown>;
}

interface ConsoleSnapshot {
  run: AgentSubagentRunV1;
  capabilities: Record<ControlAction, ConsoleCapability>;
  conversation: {
    availability: 'available' | 'partial' | 'temporarily_unavailable' | 'unavailable';
    source: string;
    items: Array<Record<string, unknown>>;
  };
  activity: ConsoleActivity[];
  inbox: ConsoleInboxItem[];
  controls: Array<Record<string, unknown>>;
}

export function SubagentConsoleDialog({
  run,
  sessionId,
  triggerLabel,
}: {
  run: AgentSubagentRunV1;
  sessionId: string;
  triggerLabel: string;
}) {
  const transport = useControlTransport();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<ConsoleTab>('overview');
  const [message, setMessage] = useState('');
  const [replyByInbox, setReplyByInbox] = useState<Record<string, string>>({});
  const [pendingAction, setPendingAction] = useState('');
  const [actionError, setActionError] = useState('');
  const queryKey = ['agent', 'subagent-console', sessionId, run.id] as const;
  const consoleQuery = useQuery({
    queryKey,
    queryFn: async ({ signal }) => parseConsole(await transport.request({
      pathId: 'agent.subagent.console',
      params: { runId: run.id },
      query: { sessionId },
      signal,
    }), run),
    enabled: open,
    refetchInterval: (query) => {
      const current = parseConsole(query.state.data, run).run;
      return current.state === 'queued' || current.state === 'running' ? 1_000 : 5_000;
    },
    retry: false,
  });
  const snapshot = parseConsole(consoleQuery.data, run);
  const current = snapshot.run;
  const pendingInbox = snapshot.inbox.filter((item) => item.status === 'pending');
  const activity = useMemo(
    () => snapshot.activity.slice().reverse(),
    [snapshot.activity],
  );

  async function control(action: ControlAction, options: { message?: string; inboxId?: string } = {}) {
    if (pendingAction) return;
    const actionMessage = options.message?.trim() ?? '';
    setPendingAction(options.inboxId ? `${action}:${options.inboxId}` : action);
    setActionError('');
    try {
      await transport.request({
        pathId: 'agent.subagent.control',
        params: { runId: current.id },
        body: {
          sessionId,
          action,
          clientActionId: newActionId(),
          ...(actionMessage ? { message: actionMessage } : {}),
          ...(options.inboxId ? { inboxId: options.inboxId } : {}),
        },
      });
      if (action === 'steer' || action === 'resume') setMessage('');
      if (action === 'reply' && options.inboxId) {
        setReplyByInbox((value) => ({ ...value, [options.inboxId as string]: '' }));
      }
      await Promise.all([
        consoleQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: ['agent', 'status-panel', 'subagents', sessionId] }),
      ]);
    } catch (error) {
      setActionError(publicError(error));
    } finally {
      setPendingAction('');
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="small" variant="quiet">{triggerLabel}</Button>
      </DialogTrigger>
      <DialogContent className="subagent-console">
        <DialogHeader className="subagent-console__header">
          <span className="subagent-console__agent"><Bot size={18} /></span>
          <span>
            <DialogTitle>
              {templateLabel(current.templateId)}控制台 · 尝试 {current.attemptNumber}
            </DialogTitle>
            <DialogDescription>{current.task}</DialogDescription>
          </span>
          <RunState run={current} />
        </DialogHeader>

        <div className="subagent-console__summary">
          <Metric label="回合" value={current.usage.turnCount} />
          <Metric label="工具" value={current.usage.toolCount} />
          <Metric label="Token" value={formatCount(current.usage.totalTokens)} />
          <Metric label="等待回复" value={pendingInbox.length} emphasis={pendingInbox.length > 0} />
        </div>

        <div className="subagent-console__tabs" role="tablist" aria-label="子 Agent 控制台">
          <TabButton active={tab === 'overview'} icon={<ListChecks size={14} />} onClick={() => setTab('overview')}>概览</TabButton>
          <TabButton active={tab === 'conversation'} icon={<MessageSquareText size={14} />} onClick={() => setTab('conversation')}>对话</TabButton>
          <TabButton active={tab === 'activity'} icon={<Wrench size={14} />} onClick={() => setTab('activity')}>活动</TabButton>
          <TabButton active={tab === 'inbox'} icon={<CircleDashed size={14} />} count={pendingInbox.length} onClick={() => setTab('inbox')}>收件箱</TabButton>
        </div>

        <div className="subagent-console__content">
          {consoleQuery.isPending ? <ConsoleEmpty icon={<LoaderCircle size={18} />} text="正在读取真实运行状态" spinning /> : null}
          {consoleQuery.error ? <ConsoleEmpty icon={<TriangleAlert size={18} />} text="暂时无法读取子 Agent 控制台" /> : null}
          {!consoleQuery.isPending && !consoleQuery.error && tab === 'overview' ? (
            <Overview
              snapshot={snapshot}
              message={message}
              setMessage={setMessage}
              pendingAction={pendingAction}
              onControl={control}
            />
          ) : null}
          {!consoleQuery.isPending && !consoleQuery.error && tab === 'conversation' ? (
            <Conversation snapshot={snapshot} />
          ) : null}
          {!consoleQuery.isPending && !consoleQuery.error && tab === 'activity' ? (
            <Activity items={activity} />
          ) : null}
          {!consoleQuery.isPending && !consoleQuery.error && tab === 'inbox' ? (
            <Inbox
              items={snapshot.inbox}
              replies={replyByInbox}
              setReplies={setReplyByInbox}
              pendingAction={pendingAction}
              onReply={(item, value) => control('reply', { inboxId: item.id, message: value })}
            />
          ) : null}
        </div>
        {actionError ? <p className="subagent-console__error" role="alert">{actionError}</p> : null}
      </DialogContent>
    </Dialog>
  );
}

function Overview({
  snapshot,
  message,
  setMessage,
  pendingAction,
  onControl,
}: {
  snapshot: ConsoleSnapshot;
  message: string;
  setMessage: (value: string) => void;
  pendingAction: string;
  onControl: (action: ControlAction, options?: { message?: string }) => Promise<void>;
}) {
  const { run, capabilities } = snapshot;
  const launch = record(run.launchDigest);
  const outputContract = record(launch.outputContract);
  const contract = record(run.contract);
  const tools = Array.isArray(launch.tools)
    ? launch.tools.filter((item): item is string => typeof item === 'string')
    : [];
  return (
    <div className="subagent-console__overview">
      <section>
        <header><strong>当前任务</strong><RunState run={run} /></header>
        <p>{run.task}</p>
        {isUnverifiedReturn(run) ? (
          <p className="subagent-console__verification" role="note">
            {UNVERIFIED_SUBAGENT_NOTICE}
          </p>
        ) : null}
        {isContractInvalid(run) ? (
          <p className="subagent-console__verification" data-contract-invalid role="alert">
            {INVALID_SUBAGENT_CONTRACT_NOTICE}
            {text(contract.error) ? <small>{text(contract.error)}</small> : null}
          </p>
        ) : null}
        {run.error ? <small className="subagent-console__failure">{run.error}</small> : null}
        {resultSummary(run.result) ? <blockquote>{resultSummary(run.result)}</blockquote> : null}
      </section>
      <section>
        <header><strong>运行中干预</strong><small>真实发送到当前 Pi 子会话</small></header>
        <textarea
          aria-label="给子 Agent 的干预消息"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="补充约束、纠正方向，或说明下一步..."
          rows={3}
        />
        <div className="subagent-console__actions">
          <Button
            disabled={!capabilities.steer.available || !message.trim()}
            loading={pendingAction === 'steer'}
            onClick={() => void onControl('steer', { message })}
          >
            <Send size={14} />发送干预
          </Button>
          <Button
            variant="quiet"
            disabled={!capabilities.resume.available}
            loading={pendingAction === 'resume'}
            onClick={() => void onControl('resume', { message })}
            title={capabilities.resume.reason}
          >
            <Play size={14} />继续
          </Button>
          <Button
            variant="quiet"
            disabled={!capabilities.retry.available}
            loading={pendingAction === 'retry'}
            onClick={() => void onControl('retry')}
            title={capabilities.retry.reason}
          >
            <RefreshCw size={14} />重试
          </Button>
          <Button
            variant="danger"
            disabled={!capabilities.abort.available}
            loading={pendingAction === 'abort'}
            onClick={() => {
              if (!confirmDestructive('确定停止这个子 Agent 吗？当前运行会被中止。')) return;
              void onControl('abort');
            }}
            title={capabilities.abort.reason}
          >
            <OctagonX size={14} />停止
          </Button>
        </div>
        {!capabilities.steer.available ? <small>{capabilities.steer.reason}</small> : null}
      </section>
      <section className="subagent-console__launch-digest">
        <header>
          <strong>Launch Digest</strong>
          <small>本次尝试的实际启动合同</small>
        </header>
        <dl>
          <div><dt>节点 / 尝试</dt><dd>{shortIdentity(run.nodeId)} · #{run.attemptNumber}</dd></div>
          <div><dt>上下文</dt><dd>{text(launch.contextMode) === 'fork' ? 'Fork' : 'Fresh'}</dd></div>
          <div><dt>模型 / 思考</dt><dd>{text(launch.modelProfile) || '默认'} · {text(launch.thinkingLevel) || '默认'}</dd></div>
          <div><dt>工具策略</dt><dd>{text(launch.toolProfileVersion) || '未记录'} · {tools.length} 项</dd></div>
          <div><dt>工作区</dt><dd>{workspaceAccessLabel(text(launch.workspaceAccess))} · {Number(launch.workspaceRootCount) || 0} 个根目录</dd></div>
          <div><dt>输出合同</dt><dd>{outputContract.required === true ? contractStatusLabel(text(contract.status)) : '未要求'}</dd></div>
        </dl>
        {tools.length ? (
          <div className="subagent-console__tool-chips" aria-label="本次尝试可用工具">
            {tools.map((tool) => <code key={tool}>{tool}</code>)}
          </div>
        ) : <small>本次启动没有披露产品工具。</small>}
      </section>
    </div>
  );
}

function Conversation({ snapshot }: { snapshot: ConsoleSnapshot }) {
  const messages = snapshot.conversation.items;
  if (!messages.length) {
    return (
      <ConsoleEmpty
        icon={<MessageSquareText size={18} />}
        text={snapshot.conversation.availability === 'temporarily_unavailable'
          ? '运行时正忙，对话快照暂时不可读取'
          : '当前运行没有可确认的公开对话快照'}
      />
    );
  }
  return (
    <div className="subagent-console__conversation">
      {snapshot.conversation.availability === 'partial' ? (
        <p className="subagent-console__notice">旧任务仅保留最终回复；新任务会保存完整公开对话快照。</p>
      ) : null}
      {messages.map((message, index) => (
        <article key={text(message.id) || `message:${index}`} data-role={text(message.role) || 'assistant'}>
          <header>
            <strong>{messageRole(text(message.role))}</strong>
            <small>{formatTime(Number(message.createdAtMs))}</small>
          </header>
          <div>{messageText(message) || '该消息没有可公开展示的正文'}</div>
        </article>
      ))}
    </div>
  );
}

function Activity({ items }: { items: ConsoleActivity[] }) {
  if (!items.length) return <ConsoleEmpty icon={<Clock3 size={18} />} text="还没有运行活动" />;
  return (
    <ol className="subagent-console__activity">
      {items.map((item) => (
        <li key={item.id}>
          <span><ActivityIcon eventType={item.eventType} /></span>
          <div>
            <strong>{activityLabel(item.eventType)}</strong>
            <small>{activityDetail(item)}</small>
          </div>
          <time>{formatTime(item.createdAtMs)}</time>
        </li>
      ))}
    </ol>
  );
}

function Inbox({
  items,
  replies,
  setReplies,
  pendingAction,
  onReply,
}: {
  items: ConsoleInboxItem[];
  replies: Record<string, string>;
  setReplies: (value: Record<string, string>) => void;
  pendingAction: string;
  onReply: (item: ConsoleInboxItem, value: string) => Promise<void>;
}) {
  if (!items.length) return <ConsoleEmpty icon={<CircleDashed size={18} />} text="子 Agent 还没有发来问题或进度" />;
  return (
    <div className="subagent-console__inbox">
      {items.map((item) => {
        const reply = replies[item.id] ?? '';
        return (
          <article key={item.id} data-kind={item.kind} data-status={item.status}>
            <header>
              <span>{inboxKindLabel(item.kind)}</span>
              <time>{formatTime(item.createdAtMs)}</time>
            </header>
            <strong>{item.title || inboxKindLabel(item.kind)}</strong>
            <p>{item.message || '没有附加说明'}</p>
            {item.status === 'pending' ? (
              <div>
                <textarea
                  aria-label={`回复 ${item.title || '子 Agent'}`}
                  value={reply}
                  onChange={(event) => setReplies({ ...replies, [item.id]: event.target.value })}
                  placeholder="给出决定或补充信息..."
                  rows={2}
                />
                <Button
                  size="small"
                  disabled={!reply.trim()}
                  loading={pendingAction === `reply:${item.id}`}
                  onClick={() => void onReply(item, reply)}
                >
                  <Send size={13} />发送给子 Agent
                </Button>
              </div>
            ) : <small>{item.status === 'replied' ? '已发送回复' : '已记录进度'}</small>}
          </article>
        );
      })}
    </div>
  );
}

function TabButton({
  active,
  icon,
  count = 0,
  children,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  count?: number;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-label={typeof children === 'string' ? children : undefined}
      aria-selected={active}
      onClick={onClick}
    >
      {icon}<span>{children}</span>{count > 0 ? <i>{count}</i> : null}
    </button>
  );
}

function confirmDestructive(message: string): boolean {
  return typeof window === 'undefined' || window.confirm(message);
}

function RunState({ run }: { run: AgentSubagentRunV1 }) {
  const state = subagentPresentationState(run);
  const icon = state === 'running'
    ? <LoaderCircle size={13} />
    : state === 'completed'
      ? <Check size={13} />
      : state === 'queued' || state === 'returned'
        ? <CircleDashed size={13} />
        : <TriangleAlert size={13} />;
  return <span className="subagent-console__state" data-state={state}>{icon}{subagentStateLabel(run, 'console')}</span>;
}

function shortIdentity(value: string): string {
  const suffix = value.split(':').at(-1) || value;
  return suffix.length > 10 ? suffix.slice(0, 8) : suffix;
}

function workspaceAccessLabel(value: string): string {
  return ({ none: '无工作区', read_only: '只读', write: '可写' } as Record<string, string>)[value] ?? '无工作区';
}

function contractStatusLabel(value: string): string {
  return ({ pending: '等待结构化交付', valid: 'Schema 已通过', invalid: '合同无效' } as Record<string, string>)[value] ?? '未提交';
}

function Metric({ label, value, emphasis = false }: { label: string; value: string | number; emphasis?: boolean }) {
  return <span data-emphasis={emphasis || undefined}><small>{label}</small><strong>{value}</strong></span>;
}

function ConsoleEmpty({ icon, text: value, spinning = false }: { icon: React.ReactNode; text: string; spinning?: boolean }) {
  return <div className="subagent-console__empty" data-spinning={spinning || undefined}>{icon}<span>{value}</span></div>;
}

function ActivityIcon({ eventType }: { eventType: string }) {
  if (eventType === 'tool_started') return <Wrench size={14} />;
  if (eventType === 'completed') return <Check size={14} />;
  if (eventType === 'failed' || eventType === 'aborted' || eventType === 'timed_out') return <TriangleAlert size={14} />;
  return <Clock3 size={14} />;
}

function parseConsole(value: unknown, fallback: AgentSubagentRunV1): ConsoleSnapshot {
  const source = record(value);
  const capabilities = record(source.capabilities);
  const conversation = record(source.conversation);
  const run = isSubagentRun(source.run) ? source.run : fallback;
  return {
    run,
    capabilities: {
      steer: capability(capabilities.steer),
      retry: capability(capabilities.retry),
      resume: capability(capabilities.resume),
      abort: capability(capabilities.abort),
      reply: capability(capabilities.reply),
    },
    conversation: {
      availability: conversationAvailability(conversation.availability),
      source: text(conversation.source),
      items: Array.isArray(conversation.items)
        ? conversation.items.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object').map(record)
        : [],
    },
    activity: Array.isArray(source.activity)
      ? source.activity.map(parseActivity).filter((item): item is ConsoleActivity => item !== null)
      : [],
    inbox: Array.isArray(source.inbox)
      ? source.inbox.map(parseInbox).filter((item): item is ConsoleInboxItem => item !== null)
      : [],
    controls: Array.isArray(source.controls) ? source.controls.map(record) : [],
  };
}

function capability(value: unknown): ConsoleCapability {
  const item = record(value);
  return { available: item.available === true, reason: text(item.reason) };
}

function parseActivity(value: unknown): ConsoleActivity | null {
  const item = record(value);
  if (!text(item.id)) return null;
  return {
    id: text(item.id),
    eventType: text(item.eventType),
    createdAtMs: Number(item.createdAtMs) || 0,
    payload: record(item.payload),
  };
}

function parseInbox(value: unknown): ConsoleInboxItem | null {
  const item = record(value);
  const kind = text(item.kind);
  const status = text(item.status);
  if (!text(item.id) || !['need_decision', 'interview', 'progress'].includes(kind)) return null;
  if (!['pending', 'replied', 'observed'].includes(status)) return null;
  return {
    id: text(item.id),
    kind: kind as ConsoleInboxItem['kind'],
    title: text(item.title),
    message: text(item.message),
    status: status as ConsoleInboxItem['status'],
    createdAtMs: Number(item.createdAtMs) || 0,
  };
}

function isSubagentRun(value: unknown): value is AgentSubagentRunV1 {
  const item = record(value);
  return item.schemaVersion === 'rag-ime.agent-subagent-run.v1'
    && typeof item.id === 'string'
    && typeof item.state === 'string'
    && typeof item.usage === 'object';
}

function conversationAvailability(value: unknown): ConsoleSnapshot['conversation']['availability'] {
  const normalized = text(value);
  if (normalized === 'available' || normalized === 'partial' || normalized === 'temporarily_unavailable') return normalized;
  return 'unavailable';
}

function messageText(message: Record<string, unknown>): string {
  if (!Array.isArray(message.blocks)) return '';
  return message.blocks.map((block) => {
    const item = record(block);
    const data = record(item.data);
    if (item.type === 'text') return text(data.text);
    if (item.type === 'code') return text(data.code);
    if (item.type === 'tool_call') return `调用工具：${text(data.toolName ?? data.name) || '未命名工具'}`;
    if (item.type === 'tool_result') return text(data.summary) || '工具已返回';
    return '';
  }).filter(Boolean).join('\n\n');
}

function resultSummary(value: unknown): string {
  return text(record(value).summary);
}

function activityDetail(item: ConsoleActivity): string {
  return text(item.payload.summary)
    || text(item.payload.toolName)
    || text(item.payload.reason)
    || text(item.payload.error)
    || '状态已写入审计记录';
}

function activityLabel(value: string): string {
  return ({
    queued: '进入队列',
    started: '开始执行',
    progress: '进度更新',
    tool_started: '调用工具',
    message_completed: '完成回复',
    budget_exceeded: '预算保护',
    completed: '执行完成',
    failed: '执行失败',
    aborted: '用户停止',
    timed_out: '执行超时',
    runtime_retained: '保留运行会话',
    runtime_retired: '清理运行会话',
  } as Record<string, string>)[value] ?? '运行事件';
}

function inboxKindLabel(value: ConsoleInboxItem['kind']): string {
  return value === 'need_decision' ? '需要决定' : value === 'interview' ? '需要补充信息' : '进度';
}

function messageRole(value: string): string {
  return value === 'user' ? '任务输入' : value === 'tool' ? '工具' : value === 'system' ? '系统' : '子 Agent';
}

function templateLabel(value: AgentSubagentRunV1['templateId']): string {
  return ({
    researcher: '研究 Agent',
    planner: '规划 Agent',
    worker: '执行 Agent',
    reviewer: '审查 Agent',
    delegate: '协作 Agent',
  })[value];
}

function newActionId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `action-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function publicError(value: unknown): string {
  const message = value instanceof Error ? value.message : '';
  if (message.includes('currently active')) return '子 Agent 已结束，无法接收这条消息。';
  if (message.includes('no longer pending')) return '这个问题已经处理，请刷新后查看。';
  return '操作没有完成，运行状态未被前端提前修改。请刷新后重试。';
}

function formatCount(value: number): string {
  return value >= 1_000 ? `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K` : String(value);
}

function formatTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '--:--';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(value);
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
