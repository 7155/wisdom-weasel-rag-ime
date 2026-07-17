import {
  BookOpenText,
  Bot,
  Brain,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Database,
  ExternalLink,
  GitBranch,
  Search,
  ShieldAlert,
  TerminalSquare,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/primitives';
import {
  agentToolProgressHistory,
  type AgentActivityProjection,
  type AgentToolProgressEntry,
} from '@/contracts/agent-reducer';
import { SafeFieldList } from './BlockRenderer';
import { publicToolResultView, safeSourceLabels, type PublicToolResultView } from './public-tool-result';
import { publicAgentErrorText } from '../public-error';

export function ActivitySummary({
  activities,
  inline = false,
  onApprovalDecision,
  onOpenApproval,
  onRequestPermission,
}: {
  activities: AgentActivityProjection[];
  inline?: boolean;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  onOpenApproval?: (activity: AgentActivityProjection) => void;
  onRequestPermission?: () => void;
}) {
  const running = activities.some((activity) => activity.status === 'running');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [running]);
  if (activities.length === 0) return null;
  const waiting = activities.some((activity) => activity.status === 'waiting');
  const failed = activities.some((activity) => activity.status === 'failed');
  const summary = aggregateSummary(activities);
  const title = running ? '正在处理' : waiting ? '等待你的确认' : failed ? '活动中有失败项' : '活动已完成';
  const inlineTools = compactToolSummary(activities);
  const inlineTitle = inlineTools.count
    ? failed
      ? `${inlineTools.count} 项操作中有失败项`
      : waiting
        ? `${inlineTools.count} 项操作等待确认`
        : running
          ? `正在处理 ${inlineTools.count} 项操作`
          : `已完成 ${inlineTools.count} 项操作`
    : title;
  const inlineSummary = inlineTools.names || summary;
  const inlineStatus = failed ? '失败' : waiting ? '等待确认' : running ? '进行中' : '完成';
  const pendingApprovals = activities.flatMap((activity) => {
    const approvalId = text(activity.payload.approvalId);
    const hash = text(activity.payload.payloadSha256);
    if (activity.status !== 'waiting' || !approvalId || !hash || !onApprovalDecision) return [];
    const presentation = activityPresentation(activity);
    return [{
      approvalId,
      hash,
      title: presentation.title,
      summary: publicActivitySummary(activity.summary, presentation.title),
    }];
  });
  const liveActivities = running || waiting ? activities.slice(-3) : [];
  const state = failed ? 'failed' : waiting ? 'waiting' : running ? 'running' : 'done';
  const summaryContent = (
    <>
      <span className="agent-activity__status" aria-hidden="true">
        {failed ? <TriangleAlert size={15} /> : waiting ? <ShieldAlert size={15} /> : running ? <CircleDashed size={15} /> : <CheckCircle2 size={15} />}
      </span>
      <span className="agent-activity__copy">
        <strong>{title}</strong>
        <small>{summary}</small>
      </span>
      <ChevronRight aria-hidden="true" size={16} />
    </>
  );
  const approvals = pendingApprovals.map((approval) => (
    <div className="agent-activity-approval" key={approval.approvalId}>
      <ShieldAlert aria-hidden="true" size={16} />
      <span><strong>{approval.title}</strong><small>{approval.summary}</small></span>
      <div>
        <Button size="small" variant="quiet" onClick={() => onApprovalDecision?.(approval.approvalId, 'rejected', approval.hash)}>拒绝</Button>
        <Button size="small" variant="primary" onClick={() => onApprovalDecision?.(approval.approvalId, 'approved', approval.hash)}>批准</Button>
      </div>
    </div>
  ));
  if (inline) {
    const InlineIcon = failed
      ? TriangleAlert
      : waiting
        ? ShieldAlert
        : inlineTools.count
          ? Wrench
          : activityPresentation(activities[activities.length - 1]!).icon;
    return (
      <div className="agent-activity-group" data-layout="interleaved">
        <details className="agent-activity agent-activity--inline" open={running || waiting || failed || undefined} data-state={state}>
          <summary aria-label={`${inlineTitle}，${inlineSummary}，${inlineStatus}`}>
            <InlineIcon aria-hidden="true" className="agent-activity__inline-icon" size={15} />
            <strong>{inlineTitle}</strong>
            <span className="agent-activity__inline-tools">{inlineSummary}</span>
            <span className="agent-activity__inline-status" data-status={state}>{inlineStatus}</span>
            <ChevronRight aria-hidden="true" size={15} />
          </summary>
          <div className="agent-activity__inline-timeline">
            {activities.map((activity) => (
              <ActivityRow
                key={activity.id}
                activity={activity}
                nowMs={nowMs}
                onApprovalDecision={onApprovalDecision}
                onOpenApproval={onOpenApproval}
                onRequestPermission={onRequestPermission}
              />
            ))}
          </div>
        </details>
        {approvals}
      </div>
    );
  }
  return (
    <div className="agent-activity-group">
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogTrigger asChild>
          <button
            className="agent-activity"
            data-state={state}
            type="button"
            aria-label={`查看活动详情：${title}，${summary}`}
          >
            {summaryContent}
          </button>
        </DialogTrigger>
        <DialogContent className="agent-activity-dialog">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{summary}。这里显示本轮真实活动与可公开的工具结果。</DialogDescription>
          </DialogHeader>
          <div className="agent-activity__timeline">
            {activities.map((activity) => (
              <ActivityRow
                key={activity.id}
                activity={activity}
                nowMs={nowMs}
                onApprovalDecision={onApprovalDecision}
                onOpenApproval={(selected) => {
                  setDetailsOpen(false);
                  onOpenApproval?.(selected);
                }}
                onRequestPermission={() => {
                  setDetailsOpen(false);
                  onRequestPermission?.();
                }}
              />
            ))}
          </div>
        </DialogContent>
      </Dialog>
      {liveActivities.length ? (
        <div className="agent-activity-live" aria-label="当前活动">
          {liveActivities.map((activity) => (
            <ActivityRow
              key={activity.id}
              activity={activity}
              nowMs={nowMs}
              onApprovalDecision={onApprovalDecision}
              onOpenApproval={onOpenApproval}
              onRequestPermission={onRequestPermission}
            />
          ))}
        </div>
      ) : null}
      {approvals}
    </div>
  );
}

function ActivityRow({
  activity,
  nowMs,
  onApprovalDecision,
  onOpenApproval,
  onRequestPermission,
}: {
  activity: AgentActivityProjection;
  nowMs: number;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  onOpenApproval?: (activity: AgentActivityProjection) => void;
  onRequestPermission?: () => void;
}) {
  const presentation = activityPresentation(activity);
  const Icon = presentation.icon;
  const payload = activity.payload;
  const isToolActivity = activity.kind === 'tool_started' || activity.kind === 'tool_progress' || activity.kind === 'tool_finished';
  const toolView = isToolActivity ? publicToolResultView(activity) : null;
  const visibleSummary = activity.kind === 'turn_failed'
    ? publicAgentErrorText(activity.summary, '模型服务请求失败，请重试或切换模型。')
    : publicActivitySummary(activity.summary, presentation.title);
  const approvalId = text(payload.approvalId);
  const hash = text(payload.payloadSha256);
  const canDecide = activity.status === 'waiting' && approvalId && hash && onApprovalDecision;
  const progressHistory = isToolActivity ? agentToolProgressHistory(payload.progressHistory) : [];
  const duration = activityDuration(activity, nowMs);
  return (
    <details className="agent-activity-row" data-kind={presentation.kind} open={activity.status === 'failed' || activity.status === 'waiting' || undefined}>
      <summary>
        <span className="agent-activity-row__icon" data-kind={presentation.kind}><Icon size={15} /></span>
        <span>
          <strong>{presentation.title}</strong>
          <small>{activity.kind === 'reasoning_summary' ? '正在整理信息与下一步' : toolView?.summary ?? visibleSummary}</small>
        </span>
        <i data-status={activity.status}>{toolView?.sources.length ? `来源 ${toolView.sources.length} · ` : ''}{statusLabel(activity.status)}{duration ? ` · ${duration}` : ''}</i>
      </summary>
      <div className="agent-activity-row__details">
        {presentation.detail ? <p>{presentation.detail}</p> : null}
        <ToolProgressTimeline activity={activity} entries={progressHistory} />
        {toolView?.preview ? <SemanticToolPreview preview={toolView.preview} /> : null}
        {toolView ? <PublicToolFields view={toolView} /> : <SafeFieldList data={payload} />}
        {toolView?.error ? <PublicToolError reason={toolView.error} /> : null}
        <SourceList items={toolView?.sources ?? safeSourceLabels(payload.sources ?? payload.documents ?? payload.books)} />
        {toolView?.destination ? (
          <a className="agent-tool-destination" href={toolView.destination.href}>
            {toolView.destination.label}<ExternalLink size={13} aria-hidden="true" />
          </a>
        ) : null}
        {canDecide ? (
          <div className="agent-activity-row__approval-actions">
            <Button size="small" variant="quiet" onClick={() => onApprovalDecision(approvalId, 'rejected', hash)}>拒绝</Button>
            <Button size="small" variant="primary" onClick={() => onApprovalDecision(approvalId, 'approved', hash)}>批准</Button>
          </div>
        ) : null}
        {toolView?.recovery === 'approval' && onOpenApproval ? (
          <div className="agent-tool-recovery">
            <Button size="small" variant="primary" leadingIcon={<ShieldAlert size={14} />} onClick={() => onOpenApproval(activity)}>去审批</Button>
          </div>
        ) : toolView?.recovery === 'permission' && onRequestPermission ? (
          <div className="agent-tool-recovery">
            <Button size="small" variant="primary" leadingIcon={<ShieldAlert size={14} />} onClick={onRequestPermission}>请求权限</Button>
          </div>
        ) : null}
      </div>
    </details>
  );
}

function ToolProgressTimeline({
  activity,
  entries,
}: {
  activity: AgentActivityProjection;
  entries: AgentToolProgressEntry[];
}) {
  if (entries.length === 0) return null;
  return (
    <div className="agent-activity-row__source-panel" aria-label="工具过程记录">
      <strong><CircleDashed size={13} />过程记录</strong>
      <ol className="agent-activity-row__sources">
        {entries.map((entry) => (
          <li key={entry.eventId}>
            {checkpointOffset(entry.createdAtMs, activity.createdAtMs)} · {entry.summary} · {statusLabel(entry.status)}
          </li>
        ))}
      </ol>
    </div>
  );
}

function PublicToolFields({ view }: { view: PublicToolResultView }) {
  if (view.preview) return null;
  if (view.fields.length === 0) {
    return view.error
      ? null
      : <p>工具没有返回可公开展示的结构化明细。</p>;
  }
  return (
    <dl className="agent-safe-fields">
      {view.fields.map((field) => (
        <div key={field.id}><dt>{field.label}</dt><dd>{field.value}</dd></div>
      ))}
    </dl>
  );
}

function SemanticToolPreview({ preview }: { preview: NonNullable<PublicToolResultView['preview']> }) {
  return (
    <section className="agent-tool-preview" data-kind={preview.kind} aria-label={`${preview.title}内容`}>
      <header>
        <span><BookOpenText size={17} /></span>
        <div>
          <strong>{preview.title}</strong>
          {preview.description ? <p>{preview.description}</p> : null}
        </div>
      </header>
      {preview.badges.length ? <ul className="agent-tool-preview__badges">{preview.badges.map((badge) => <li key={badge}>{badge}</li>)}</ul> : null}
      {preview.items.length ? (
        <ol className="agent-tool-preview__items">
          {preview.items.map((item) => (
            <li key={item.id}>
              {item.label ? <span>{item.label}</span> : null}
              <p>{item.text}</p>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function PublicToolError({ reason }: { reason: string }) {
  return (
    <section className="agent-tool-result-panel" data-tone="error" aria-label="工具错误">
      <strong><TriangleAlert size={13} />失败原因</strong>
      <p>{reason}</p>
    </section>
  );
}

function SourceList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return <div className="agent-activity-row__source-panel"><strong><BookOpenText size={13} />信息来源</strong><ul className="agent-activity-row__sources">{items.map((item) => <li key={item}>{item}</li>)}</ul></div>;
}

interface ActivityPresentation {
  title: string;
  kind: 'thinking' | 'tool' | 'rag' | 'memory' | 'subagent' | 'approval' | 'runtime';
  icon: LucideIcon;
  detail?: string;
}

function activityPresentation(activity: AgentActivityProjection): ActivityPresentation {
  const payload = activity.payload;
  const toolId = text(payload.toolId ?? payload.toolName).toLowerCase();
  const toolView = activity.kind.startsWith('tool_') ? publicToolResultView(activity) : null;
  const operation = toolView?.operation ?? text(payload.operation);
  if (activity.kind === 'reasoning_summary') {
    return { title: '处理说明', kind: 'thinking', icon: Brain };
  }
  if (activity.kind === 'turn_failed') {
    return { title: '模型服务请求失败', kind: 'runtime', icon: TriangleAlert, detail: '模型请求没有完成；可返回对话重试或切换模型。' };
  }
  if (activity.kind.includes('approval') || activity.kind === 'user_input_required') {
    const memoryReview = activity.kind === 'user_input_required' && payload.requestKind === 'memory_review';
    return {
      title: memoryReview ? '记忆草案审阅' : '权限确认',
      kind: 'approval',
      icon: ShieldAlert,
      detail: memoryReview ? 'Agent 已暂停，等待你在审阅弹窗中处理草案。' : '是否执行以你的本机确认结果为准。',
    };
  }
  if (activity.kind.includes('memory') || toolId.includes('memory')) {
    const title = ({
      catalog: '浏览记忆目录',
      read: '读取工具书',
      recent: '读取近期输入',
      trace: '查看记忆追溯',
      curation_prepare: '生成记忆整理草案',
      maintenance_preview: '生成记忆整理草案',
      maintenance_review: '查看记忆整理草案',
      maintenance_apply: '应用记忆整理',
      maintenance_rollback: '回滚记忆整理',
      list: '浏览记忆',
      search: '检索记忆',
    } as Record<string, string>)[operation] ?? '记忆操作';
    return { title, kind: 'memory', icon: BookOpenText };
  }
  if (toolId.includes('knowledge') || toolId.includes('rag') || text(payload.operation) === 'search') {
    const title = toolId === 'ime_knowledge'
      ? ({ list_bases: '浏览知识库', search: '检索文档', find: '定位文档证据', open: '读取文档片段', status: '检查知识库' } as Record<string, string>)[operation] ?? '文档知识库'
      : '知识检索';
    return { title, kind: 'rag', icon: Search };
  }
  if (toolId.includes('subagent') || activity.kind.includes('subagent')) {
    return { title: '协作 Agent', kind: 'subagent', icon: GitBranch };
  }
  if (toolId.includes('runtime') || toolId.includes('workspace')) {
    return { title: '运行环境', kind: 'runtime', icon: toolId.includes('workspace') ? TerminalSquare : Database };
  }
  if (toolId.includes('planning') || toolId === 'agent_plan') return { title: toolId === 'agent_plan' ? '当前回合计划' : '规划', kind: 'tool', icon: Bot };
  return { title: toolView?.toolLabel ?? '工具操作', kind: 'tool', icon: Wrench };
}

function publicActivitySummary(value: string, fallback: string): string {
  const summary = value.trim();
  if (!summary) return `${fallback}已更新`;
  if (/^[a-z][a-z0-9_.:/-]*$/i.test(summary) || /(?:session|participant|activity|event|tool_call|tool_result)/i.test(summary)) {
    return `${fallback}已更新`;
  }
  return summary;
}

function aggregateSummary(activities: AgentActivityProjection[]): string {
  const counts = new Map<string, number>();
  for (const activity of activities) {
    const label = activityPresentation(activity).title;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, count]) => `${label} ${count}`)
    .join(' · ');
}

function compactToolSummary(activities: AgentActivityProjection[]) {
  const calls = new Set<string>();
  const names = new Set<string>();
  for (const activity of activities) {
    if (!['tool_started', 'tool_progress', 'tool_finished'].includes(activity.kind)) continue;
    calls.add(text(activity.payload.toolCallId) || activity.id);
    names.add(activityPresentation(activity).title);
  }
  return {
    count: calls.size,
    names: [...names].slice(0, 3).join(' · '),
  };
}

function statusLabel(status: AgentActivityProjection['status']): string {
  switch (status) {
    case 'running': return '进行中';
    case 'waiting': return '待确认';
    case 'failed': return '失败';
    case 'completed': return '完成';
  }
}

function activityDuration(activity: AgentActivityProjection, nowMs: number): string {
  const endMs = activity.status === 'running' ? nowMs : activity.updatedAtMs;
  const elapsedMs = Math.max(0, endMs - activity.createdAtMs);
  // A restored activity with an invalid epoch should not display a fantastical timer.
  if (!Number.isFinite(elapsedMs) || (activity.status === 'running' && elapsedMs > 7 * 24 * 60 * 60 * 1_000)) return '';
  return elapsedLabel(elapsedMs);
}

function checkpointOffset(createdAtMs: number, startedAtMs: number): string {
  return `+${elapsedLabel(Math.max(0, createdAtMs - startedAtMs))}`;
}

function elapsedLabel(elapsedMs: number): string {
  return `${Math.max(0, Math.round(elapsedMs))} ms`;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
