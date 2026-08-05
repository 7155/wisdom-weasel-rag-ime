import {
  BookOpenText,
  Bot,
  Brain,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Copy,
  Database,
  ExternalLink,
  GitBranch,
  MessageSquareText,
  Search,
  ShieldAlert,
  ShieldCheck,
  TerminalSquare,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
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
import {
  approvalDecisionView,
  approvalDecisionReasonLabel,
  approvalNeedsHumanDecision,
  type ApprovalDecisionView,
} from '@/contracts/approval-decision';
import { writeClipboardText } from '@/platform/clipboard';
import { SafeFieldList } from './BlockRenderer';
import {
  toggleDisclosureOnKeyPreservingAnchor,
  toggleDisclosurePreservingAnchor,
  useAutoFollowScroll,
} from './disclosure-anchor';
import { publicToolResultView, safeSourceLabels, type PublicToolResultView } from './public-tool-result';
import { publicAgentErrorText } from '../public-error';
import { DiffPreview } from '../file-preview/DiffPreview';
import { CodeContentBlock } from './CodeDiffRenderers';
import { canonicalToolId } from '../tool-presentation';
import { hasToolArtifacts, ToolArtifactOutput } from './ToolArtifactOutput';

const codeMutationToolIds = new Set([
  'write',
  'edit',
]);

export type CanonicalBasicToolId = 'read' | 'edit' | 'write' | 'bash';

const canonicalBasicToolIds = new Set<CanonicalBasicToolId>([
  'read',
  'edit',
  'write',
  'bash',
]);

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
  const automatedWaiting = activities.some((activity) => (
    activity.status === 'waiting'
    && Boolean(text(activity.payload.approvalId))
    && !approvalNeedsHumanDecision(activity.payload)
  ));
  const running = automatedWaiting || activities.some((activity) => activity.status === 'running');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const waiting = activities.some((activity) => (
    activity.status === 'waiting'
    && (
      !text(activity.payload.approvalId)
      || approvalNeedsHumanDecision(activity.payload)
    )
  ));
  const failed = activities.some((activity) => activity.status === 'failed');
  const terminalFailure = activities.some((activity) => (
    activity.kind === 'turn_failed' && activity.status === 'failed'
  ));
  const pendingApproval = activities.find((activity) => (
    activity.status === 'waiting'
    && Boolean(text(activity.payload.approvalId))
    && Boolean(text(activity.payload.toolCallId))
  ));
  const pendingApprovalId = text(pendingApproval?.payload.approvalId);
  const [inlineOpen, setInlineOpen] = useState(Boolean(pendingApprovalId));
  const presentedApprovalRef = useRef(pendingApprovalId);
  useEffect(() => {
    if (!pendingApprovalId || pendingApprovalId === presentedApprovalRef.current) return;
    presentedApprovalRef.current = pendingApprovalId;
    setInlineOpen(true);
  }, [pendingApprovalId]);

  if (activities.length === 0) return null;
  const summary = aggregateSummary(activities);
  const title = running
    ? '正在处理'
    : waiting
      ? '等待你的确认'
      : terminalFailure
        ? '本轮未完成'
        : '操作记录';
  const inlineTools = compactToolSummary(activities);
  const inlineTitle = inlineTools.count
    ? running
      ? `正在处理 ${inlineTools.count} 项操作`
      : waiting
        ? `${inlineTools.count} 项操作等待确认`
        : `${inlineTools.count} 项操作`
    : title;
  // A long Agent loop can legitimately contain failed probes. Keep the group
  // neutral and reserve terminal red for a turn/provider failure. The inline
  // detail list still identifies every unfinished call and its recovery reason.
  const inlineSummary = inlineTools.count
    ? inlineTools.count === 1
      ? inlineTools.highlight || inlineTools.outcome || inlineTools.names
      : inlineTools.outcome || inlineTools.names
    : summary;
  const inlineStatus = terminalFailure
    ? '未完成'
    : waiting
      ? '等待确认'
      : running
        ? '进行中'
        : failed && inlineTools.count > 1
          ? '查看'
          : failed
            ? '未完成'
            : '完成';
  const liveActivities = running || waiting ? activities.slice(-3) : [];
  const state = terminalFailure ? 'failed' : waiting ? 'waiting' : running ? 'running' : failed ? 'mixed' : 'done';
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
  if (inline) {
    const InlineIcon = terminalFailure
      ? TriangleAlert
      : waiting
        ? ShieldAlert
        : running
          ? CircleDashed
          : inlineTools.count
            ? Wrench
            : activityPresentation(activities[activities.length - 1]!).icon;
    return (
      <div className="agent-activity-group" data-layout="interleaved">
        <details
          className="agent-activity agent-activity--inline"
          data-state={state}
          open={inlineOpen}
        >
          <summary
            aria-expanded={inlineOpen}
            aria-label={`${inlineTitle}，${inlineSummary}，${inlineStatus}`}
            onClick={(event) => toggleDisclosurePreservingAnchor(event, setInlineOpen)}
            onKeyDown={(event) => toggleDisclosureOnKeyPreservingAnchor(event, setInlineOpen)}
          >
            <InlineIcon aria-hidden="true" className="agent-activity__inline-icon" size={15} />
            <strong>{inlineTitle}</strong>
            <span className="agent-activity__inline-tools">{inlineSummary}</span>
            <span className="agent-activity__inline-status" data-status={state}>{inlineStatus}</span>
            <ChevronRight aria-hidden="true" size={15} />
          </summary>
          {inlineOpen ? (
            <div
              aria-label={`${title}详情`}
              className="agent-activity__inline-timeline"
            >
              {activities.map((activity) => (
                <ActivityRow
                  key={activity.id}
                  activity={activity}
                  onApprovalDecision={onApprovalDecision}
                  onOpenApproval={(selected) => {
                    setInlineOpen(false);
                    onOpenApproval?.(selected);
                  }}
                  onRequestPermission={() => {
                    setInlineOpen(false);
                    onRequestPermission?.();
                  }}
                />
              ))}
            </div>
          ) : null}
        </details>
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
              onApprovalDecision={onApprovalDecision}
              onOpenApproval={onOpenApproval}
              onRequestPermission={onRequestPermission}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ActivityRow({
  activity,
  onApprovalDecision,
  onOpenApproval,
  onRequestPermission,
}: {
  activity: AgentActivityProjection;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  onOpenApproval?: (activity: AgentActivityProjection) => void;
  onRequestPermission?: () => void;
}) {
  const payload = activity.payload;
  const approvalId = text(payload.approvalId);
  const hash = text(payload.payloadSha256);
  const boundToTool = Boolean(approvalId && text(payload.toolCallId));
  const displayActivity: AgentActivityProjection = boundToTool && activity.kind.includes('approval')
    ? { ...activity, kind: 'tool_progress' }
    : activity;
  const presentation = activityPresentation(displayActivity);
  const approvalPresentation = approvalId
    ? activityPresentation({
        ...activity,
        kind: activity.status === 'waiting' ? 'approval_required' : 'approval_resolved',
      })
    : null;
  const Icon = presentation.icon;
  const isToolActivity = ['tool_started', 'tool_progress', 'tool_finished'].includes(displayActivity.kind);
  const toolView = isToolActivity ? publicToolResultView(displayActivity) : null;
  const basicToolId = toolView ? canonicalBasicToolId(toolView.toolId) : null;
  const mutating = Boolean(toolView && codeMutationToolIds.has(toolView.toolId));
  const progressHistory = isToolActivity ? agentToolProgressHistory(payload.progressHistory) : [];
  const editStarted = displayActivity.kind === 'tool_started'
    || progressHistory.some((entry) => entry.kind === 'tool_started');
  const editActive = mutating
    && activity.status === 'running'
    && editStarted
    && ['tool_started', 'tool_progress'].includes(displayActivity.kind);
  const toolStreaming = Boolean(
    basicToolId
    && activity.status === 'running'
    && ['tool_started', 'tool_progress'].includes(displayActivity.kind),
  );
  const mutationAwaitingDiff = Boolean(toolStreaming && mutating);
  const showArtifacts = Boolean(
    toolView
    && hasToolArtifacts(toolView.artifacts)
    && !mutationAwaitingDiff,
  );
  const showRunningPreview = Boolean(
    basicToolId
    && toolView
    && toolStreaming
    && (!toolView.output || mutationAwaitingDiff || basicToolId === 'bash'),
  );
  const visibleSummary = activity.kind === 'turn_failed'
    ? publicAgentErrorText(activity.summary, '模型服务请求失败，请重试或切换模型。')
    : publicActivitySummary(activity.summary, presentation.title);
  const canDecide = activity.status === 'waiting' && approvalNeedsHumanDecision(payload) && approvalId && hash && onApprovalDecision;
  const [rowOpen, setRowOpen] = useState(Boolean(boundToTool && activity.status === 'waiting'));
  const autoOpenedRunningRef = useRef(false);
  useEffect(() => {
    if (!basicToolId || activity.status !== 'running' || autoOpenedRunningRef.current) return;
    autoOpenedRunningRef.current = true;
    setRowOpen(true);
  }, [activity.status, basicToolId]);
  const nowMs = useActivityClock(activity.status === 'running');
  const duration = activityDuration(activity, nowMs);
  return (
    <details
      className="agent-activity-row"
      data-kind={presentation.kind}
      data-edit-active={editActive || undefined}
      data-state={activity.status}
      data-tool-kind={basicToolId ?? 'standard'}
      open={rowOpen}
    >
      <summary
        aria-expanded={rowOpen}
        onClick={(event) => toggleDisclosurePreservingAnchor(event, setRowOpen)}
        onKeyDown={(event) => toggleDisclosureOnKeyPreservingAnchor(event, setRowOpen)}
      >
        <span className="agent-activity-row__icon" data-kind={presentation.kind}><Icon size={15} /></span>
        <span>
          <strong>{presentation.title}</strong>
          <small>
            {toolView?.error ?? toolView?.summary ?? visibleSummary}
          </small>
          {editActive ? <span
            aria-label={basicToolId === 'write' ? '正在接收文件写入进度' : '正在接收文件编辑进度'}
            className="agent-activity-row__edit-progress"
            role="status"
          ><i /><i /><i /></span> : null}
        </span>
        <i data-status={activity.status}>
          {toolView?.sources.length ? `来源 ${toolView.sources.length} · ` : ''}
          {isToolActivity && activity.status === 'failed' ? '未完成' : statusLabel(activity.status)}
          {duration ? ` · ${duration}` : ''}
        </i>
      </summary>
      {rowOpen ? (
        <div className="agent-activity-row__details">
          {presentation.detail ? <p>{presentation.detail}</p> : null}
          <ToolProgressTimeline activity={activity} entries={progressHistory} />
          {showArtifacts && toolView ? (
            <ToolArtifactOutput artifacts={toolView.artifacts} autoExpandDiff={activity.status === 'completed'} />
          ) : null}
          {!showArtifacts && toolView?.request.length ? <PublicToolRequest view={toolView} /> : null}
          {showRunningPreview && basicToolId && toolView ? (
            <ToolRunningPreview
              target={publicToolTarget(toolView)}
              toolId={basicToolId}
            />
          ) : null}
          {!showArtifacts && !mutationAwaitingDiff && toolView?.output ? (
            <PublicToolOutput streaming={toolStreaming} view={toolView} />
          ) : null}
          {!showArtifacts && toolView?.preview ? <SemanticToolPreview preview={toolView.preview} /> : null}
          {!showArtifacts && !showRunningPreview && toolView && toolView.fields.every((field) => field.id === 'status') && !toolView.request.length && !toolView.output && !toolView.preview && !toolView.error ? (
            <p className="agent-tool-unavailable">这条历史回执未包含可公开的调用参数或返回内容。</p>
          ) : null}
          {activity.kind === 'reasoning_summary'
            ? <ReasoningSummaryDetails items={reasoningItemsFromPayload(payload, visibleSummary)} />
            : toolView && !showArtifacts
              ? <PublicToolFields view={toolView} />
              : !toolView
                ? <SafeFieldList data={payload} />
                : null}
          {toolView?.error ? <PublicToolError reason={toolView.error} /> : null}
          <SourceList items={toolView?.sources ?? safeSourceLabels(payload.sources ?? payload.documents ?? payload.books)} />
          {toolView?.destination ? (
            <a className="agent-tool-destination" href={toolView.destination.href}>
              {toolView.destination.label}<ExternalLink size={13} aria-hidden="true" />
            </a>
          ) : null}
          {approvalPresentation ? (
            <section className="agent-activity-row__approval" aria-label={`审批状态：${approvalPresentation.title}`}>
              <ShieldAlert aria-hidden="true" size={15} />
              <span>
                <strong>{approvalPresentation.title}</strong>
                <small>{approvalPresentation.detail ?? '审批状态与这次 Tool 调用使用同一 toolCallId。'}</small>
              </span>
              {canDecide ? (
                <div className="agent-activity-row__approval-actions">
                  <Button size="small" variant="quiet" onClick={() => onApprovalDecision?.(approvalId, 'rejected', hash)}>拒绝</Button>
                  <Button size="small" variant="primary" onClick={() => onApprovalDecision?.(approvalId, 'approved', hash)}>批准</Button>
                </div>
              ) : null}
            </section>
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
      ) : null}
    </details>
  );
}

interface PublicActivityFeedEntry {
  id: string;
  kind: 'reasoning' | 'tool';
  label: string;
  status: AgentActivityProjection['status'];
  summary: string;
  timestamp: number;
}

/** A live-only, bounded projection. Historical detail remains in the adjacent
 * disclosures, while this log follows new public updates until the reader
 * deliberately scrolls away from its end. */
export function PublicActivityFeed({
  activities,
}: {
  activities: AgentActivityProjection[];
}) {
  const entries = publicActivityFeedEntries(activities);
  const active = activities.some((activity) => (
    activity.status === 'running' || activity.status === 'waiting'
  ));
  const contentKey = entries.map((entry) => (
    `${entry.id}:${entry.status}:${entry.summary}`
  )).join('\u001f');
  const { onScroll, scrollRef } = useAutoFollowScroll<HTMLDivElement>(contentKey, active);
  if (!active || entries.length === 0) return null;
  return (
    <section className="agent-public-activity" aria-label="最新公开思考与工具活动">
      <header>
        <span>
          <strong>最新活动</strong>
          <small>Provider 公开摘要与 Tool 回执</small>
        </span>
        <b>{entries.length} 条</b>
      </header>
      <div
        aria-label="最新公开思考与工具活动"
        aria-live="polite"
        aria-relevant="additions text"
        className="agent-public-activity__feed"
        onScroll={onScroll}
        ref={scrollRef}
        role="log"
        tabIndex={0}
      >
        {entries.map((entry) => (
          <article data-kind={entry.kind} data-state={entry.status} key={entry.id}>
            <span aria-hidden="true">
              {entry.kind === 'reasoning' ? <Brain size={14} /> : <Wrench size={14} />}
            </span>
            <span>
              <strong>{entry.label}</strong>
              <small>{entry.summary}</small>
            </span>
            <i>{statusLabel(entry.status)}</i>
          </article>
        ))}
      </div>
    </section>
  );
}

function publicActivityFeedEntries(
  activities: AgentActivityProjection[],
): PublicActivityFeedEntry[] {
  const entries: Array<PublicActivityFeedEntry & { order: number }> = [];
  let order = 0;
  for (const activity of activities) {
    if (
      activity.kind === 'reasoning_summary'
      && text(activity.payload.source) === 'provider_reasoning_summary'
    ) {
      for (const [index, item] of reasoningItemsFromPayload(activity.payload, activity.summary).entries()) {
        entries.push({
          id: `${activity.id}:reasoning:${index}`,
          kind: 'reasoning',
          label: '公开思考摘要',
          status: activity.status,
          summary: boundedInlineSummary(item),
          timestamp: activity.updatedAtMs,
          order: order++,
        });
      }
      continue;
    }
    if (!['tool_started', 'tool_progress', 'tool_finished'].includes(activity.kind)) continue;
    const history = agentToolProgressHistory(activity.payload.progressHistory);
    const view = publicToolResultView(activity);
    if (history.length) {
      for (const entry of history) {
        entries.push({
          id: `${activity.id}:${entry.eventId}`,
          kind: 'tool',
          label: view.toolLabel,
          status: entry.status,
          summary: boundedInlineSummary(entry.summary, 180),
          timestamp: entry.createdAtMs,
          order: order++,
        });
      }
      continue;
    }
    entries.push({
      id: `${activity.id}:${activity.kind}`,
      kind: 'tool',
      label: view.toolLabel,
      status: activity.status,
      summary: boundedInlineSummary(
        view.error ?? view.summary ?? publicActivitySummary(activity.summary, view.toolLabel),
        180,
      ),
      timestamp: activity.updatedAtMs,
      order: order++,
    });
  }
  return entries
    .sort((left, right) => left.timestamp - right.timestamp || left.order - right.order)
    .slice(-24)
    .map(({ order: _order, ...entry }) => entry);
}

export function ReasoningActivitySummary({
  activities,
}: {
  activities: AgentActivityProjection[];
}) {
  const reasoning = reasoningSummaryItems(activities);
  if (reasoning.items.length === 0) return null;
  return (
    <ReasoningSummaryStrip
      items={reasoning.items}
      running={reasoning.running}
    />
  );
}

function ReasoningSummaryStrip({
  items,
  running,
}: {
  items: string[];
  running: boolean;
}) {
  const latest = items.at(-1) ?? '';
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          aria-label={`查看 Agent 思考摘要：${latest}`}
          className="agent-reasoning-feed"
          data-state={running ? 'running' : 'completed'}
          type="button"
        >
          <Brain aria-hidden="true" size={15} />
          <strong>{running ? '正在思考' : '思考摘要'}</strong>
          <span>{latest}</span>
          <small>{running ? '实时' : `${items.length} 项`}</small>
          <ChevronRight aria-hidden="true" size={15} />
        </button>
      </DialogTrigger>
      <DialogContent className="agent-activity-dialog agent-reasoning-dialog">
        <DialogHeader>
          <DialogTitle>{running ? '正在思考' : '思考摘要'}</DialogTitle>
          <DialogDescription>仅显示 Provider 允许公开的限长摘要；时间线保持单行，避免流式更新引起跳动。</DialogDescription>
        </DialogHeader>
        <ReasoningSummaryDetails items={items} />
      </DialogContent>
    </Dialog>
  );
}

function ReasoningSummaryDetails({ items }: { items: string[] }) {
  return (
    <section className="agent-reasoning-details" aria-label="可公开的思考摘要">
      <strong>可公开的思考摘要</strong>
      <ol>{items.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ol>
    </section>
  );
}

function reasoningSummaryItems(activities: AgentActivityProjection[]): { items: string[]; running: boolean } {
  const reasoning = activities.filter((activity) => (
    activity.kind === 'reasoning_summary'
    && text(activity.payload.source) === 'provider_reasoning_summary'
  ));
  const items = reasoning.flatMap((activity) => reasoningItemsFromPayload(activity.payload, activity.summary));
  return {
    items: [...new Set(items)].slice(-12),
    running: reasoning.some((activity) => activity.status === 'running'),
  };
}

function reasoningItemsFromPayload(payload: Record<string, unknown>, fallback: string): string[] {
  const values = Array.isArray(payload.items) ? payload.items : [];
  const items = values
    .filter((value): value is string => typeof value === 'string')
    .map((value) => value.replace(/\s+/gu, ' ').trim())
    .filter(Boolean);
  const summary = fallback.replace(/\s+/gu, ' ').trim();
  return items.length ? items.slice(0, 12) : summary ? [summary] : [];
}

function useActivityClock(running: boolean): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    setNowMs(Date.now());
    // The UI displays whole seconds once a call crosses one second. Updating
    // four times per second only rerendered every row in long tool histories.
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [running]);
  return nowMs;
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

export function PublicToolFields({ view }: { view: PublicToolResultView }) {
  const fieldsText = JSON.stringify(
    Object.fromEntries(view.fields.map((field) => [field.id, field.value])),
    null,
    2,
  );
  const { copy, state } = useCopyableText(fieldsText);
  if (view.preview) return null;
  if (view.fields.length === 0) {
    return view.error
      ? null
      : <p>工具没有返回可公开展示的结构化明细。</p>;
  }
  return (
    <section className="agent-tool-result-panel" aria-label="工具结果明细">
      <header className="agent-tool-result-panel__header">
        <strong><TerminalSquare size={13} />结果明细</strong>
        <Button
          aria-live="polite"
          leadingIcon={state === 'copied' ? <Check size={13} /> : <Copy size={13} />}
          onClick={() => void copy()}
          size="small"
          variant="quiet"
        >
          {state === 'copied' ? '已复制明细' : '复制明细'}
        </Button>
      </header>
      <dl className="agent-safe-fields">
        {view.fields.map((field) => (
          <div key={field.id}><dt>{field.label}</dt><dd>{field.value}</dd></div>
        ))}
      </dl>
      {state === 'failed' ? <small role="alert">无法复制明细，请手动选择内容。</small> : null}
    </section>
  );
}

export function PublicToolRequest({ view }: { view: PublicToolResultView }) {
  const requestText = JSON.stringify(
    Object.fromEntries(view.request.map((field) => [field.id, field.value])),
    null,
    2,
  );
  const { copy, state } = useCopyableText(requestText);
  return (
    <section className="agent-tool-result-panel" aria-label="工具调用参数">
      <header className="agent-tool-result-panel__header">
        <strong><TerminalSquare size={13} />调用参数</strong>
        <Button
          aria-live="polite"
          leadingIcon={state === 'copied' ? <Check size={13} /> : <Copy size={13} />}
          onClick={() => void copy()}
          size="small"
          variant="quiet"
        >
          {state === 'copied' ? '已复制参数' : '复制参数'}
        </Button>
      </header>
      <dl className="agent-tool-request">
        {view.request.map((field) => (
          <div key={field.id}>
            <dt>{field.label}</dt>
            <dd>{field.code ? <code>{field.value}</code> : field.value}</dd>
          </div>
        ))}
      </dl>
      {state === 'failed' ? <small role="alert">无法复制参数，请手动选择内容。</small> : null}
    </section>
  );
}

export function PublicToolOutput({
  view,
  streaming = false,
}: {
  view: PublicToolResultView;
  streaming?: boolean;
}) {
  const outputText = view.output?.text ?? '';
  const { copy, state } = useCopyableText(outputText);
  if (!view.output) return null;
  if (view.output.kind === 'diff') {
    return (
      <section className="agent-tool-specialized-output" aria-label="文件变更" data-streaming={streaming || undefined}>
        <DiffPreview content={outputText} fileName={view.output.title} />
        {view.output.truncated ? <small>这里只显示安全截断片段；完整 Diff 仍由本机工具回执保留。</small> : null}
      </section>
    );
  }
  if (['code', 'search', 'terminal'].includes(view.output.kind)) {
    const channels = view.output.kind === 'terminal' ? view.output.channels ?? [] : [];
    return (
      <section
        className="agent-tool-specialized-output"
        aria-label="工具返回片段"
        data-output-kind={view.output.kind}
        data-streaming={streaming || undefined}
      >
        {channels.length ? channels.map((channel, index) => (
          <div className="agent-tool-terminal-channel" data-channel={channel.id} key={channel.id}>
            <CodeContentBlock
              code={channel.text}
              fileName={channel.label}
              language="shell"
              streamingTail={streaming && index === channels.length - 1}
            />
            {channel.truncated ? <small>{channel.label}已安全截断；完整结果仍由本机工具回执保留。</small> : null}
          </div>
        )) : (
          <CodeContentBlock
            code={outputText}
            fileName={view.output.title}
            language={view.output.kind === 'terminal' ? 'shell' : 'text'}
            streamingTail={streaming}
          />
        )}
        {view.output.truncated ? <small>此处显示安全截断片段；完整结果仍由本机工具回执保留。</small> : null}
      </section>
    );
  }
  return (
    <section
      className="agent-tool-result-panel"
      data-output-kind="text"
      aria-label="工具返回片段"
    >
      <header className="agent-tool-result-panel__header">
        <strong><TerminalSquare size={13} />返回片段</strong>
        <Button
          aria-live="polite"
          leadingIcon={state === 'copied' ? <Check size={13} /> : <Copy size={13} />}
          onClick={() => void copy()}
          size="small"
          variant="quiet"
        >
          {state === 'copied' ? '已复制结果' : '复制结果'}
        </Button>
      </header>
      <pre aria-label="工具返回内容" tabIndex={0}>{outputText}</pre>
      {view.output.truncated ? (
        <small>此处显示安全截断片段；完整结果仍由本机工具回执保留。</small>
      ) : null}
      {state === 'failed' ? <small role="alert">无法复制结果，请选择内容后手动复制。</small> : null}
    </section>
  );
}

export function ToolRunningPreview({
  toolId,
  target = '',
}: {
  toolId: CanonicalBasicToolId | string;
  target?: string;
}) {
  const canonicalId = canonicalBasicToolId(toolId);
  if (!canonicalId) return null;
  const safeTarget = target.trim();
  const copy: Record<CanonicalBasicToolId, { title: string; detail: string }> = {
    read: {
      title: safeTarget ? `正在读取 ${safeTarget}` : '正在读取文件',
      detail: '内容到达后会持续追加在下方。',
    },
    edit: {
      title: safeTarget ? `正在编辑 ${safeTarget}` : '正在编辑文件',
      detail: '正在生成并校验变更，完成后会在这里展示真实 Diff。',
    },
    write: {
      title: safeTarget ? `正在写入 ${safeTarget}` : '正在写入文件',
      detail: '正在保存并核对产物，完成后会展示实际文件与 Diff。',
    },
    bash: {
      title: '命令正在运行',
      detail: '标准输出与标准错误会按到达顺序持续更新。',
    },
  };
  return (
    <section
      aria-live="polite"
      aria-label={copy[canonicalId].title}
      className="agent-tool-running-preview"
      data-tool={canonicalId}
      role="status"
    >
      <span aria-hidden="true" className="agent-tool-running-preview__pulse"><i /><i /><i /></span>
      <span>
        <strong>{copy[canonicalId].title}</strong>
        <small>{copy[canonicalId].detail}</small>
      </span>
    </section>
  );
}

function canonicalBasicToolId(value: string): CanonicalBasicToolId | null {
  const canonicalId = canonicalToolId(value) as CanonicalBasicToolId;
  return canonicalBasicToolIds.has(canonicalId) ? canonicalId : null;
}

function publicToolTarget(view: PublicToolResultView): string {
  return view.request.find((field) => field.id === 'path')?.value ?? '';
}

export function SemanticToolPreview({ preview }: { preview: NonNullable<PublicToolResultView['preview']> }) {
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
              {item.href ? <a href={item.href}>{item.text}</a> : <p>{item.text}</p>}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

export function PublicToolError({ reason }: { reason: string }) {
  const { copy, state } = useCopyableText(reason);
  return (
    <section className="agent-tool-result-panel" data-tone="error" aria-label="工具未完成">
      <header className="agent-tool-result-panel__header">
        <strong><TriangleAlert size={13} />未完成原因</strong>
        <Button
          aria-live="polite"
          leadingIcon={state === 'copied' ? <Check size={13} /> : <Copy size={13} />}
          onClick={() => void copy()}
          size="small"
          variant="quiet"
        >
          {state === 'copied' ? '已复制错误' : '复制错误'}
        </Button>
      </header>
      <p>{reason}</p>
      {state === 'failed' ? <small role="alert">无法复制错误，请手动选择内容。</small> : null}
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
    const decision = approvalDecisionView(payload);
    if (decision.mode === 'model') {
      const model = approvalModelLabel(decision.model);
      const arbiter = `独立审批 Agent（${model}）`;
      const settledTitle = decision.status === 'failed_closed'
        ? `${arbiter}无法形成可验证裁决，已拒绝这次操作`
        : decision.decision === 'approve'
          ? `${arbiter}已批准这次操作`
          : decision.decision === 'deny'
            ? `${arbiter}已拒绝这次操作`
            : '';
      return {
        title: settledTitle || `${arbiter}正在评估这次操作`,
        kind: 'approval',
        icon: Brain,
        detail: approvalDecisionDetail(decision),
      };
    }
    if (decision.mode === 'policy') {
      return {
        title: '安全策略已自动处理这次操作',
        kind: 'approval',
        icon: ShieldCheck,
        detail: '只有已授权范围内的常规受控操作会直接执行；权限、哈希与沙箱边界仍会再次校验。',
      };
    }
    const memoryReview = activity.kind === 'user_input_required' && payload.requestKind === 'memory_review';
    const genericInput = activity.kind === 'user_input_required' && !memoryReview;
    return {
      title: memoryReview ? '记忆草案审阅' : genericInput ? text(payload.title) || '等待你的回答' : '权限确认',
      kind: 'approval',
      icon: genericInput ? MessageSquareText : ShieldAlert,
      detail: memoryReview
        ? 'Agent 已暂停，等待你在审阅弹窗中处理草案。'
        : genericInput
          ? 'Agent 已暂停；回答、取消或超时后会继续当前回合。'
          : '是否执行以你的本机确认结果为准。',
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
    const title = toolId === 'knowledge'
      ? ({ list_bases: '浏览知识库', search: '检索文档', find: '定位文档证据', open: '读取文档片段', status: '检查知识库' } as Record<string, string>)[operation] ?? '文档知识库'
      : '知识检索';
    return { title, kind: 'rag', icon: Search };
  }
  if (toolId.includes('subagent') || activity.kind.includes('subagent')) {
    return { title: '协作 Agent', kind: 'subagent', icon: GitBranch };
  }
  if (toolId.includes('runtime')) {
    return { title: '运行环境', kind: 'runtime', icon: Database };
  }
  if (toolId.includes('workspace')) {
    return { title: toolView?.toolLabel ?? '运行环境', kind: 'runtime', icon: TerminalSquare };
  }
  if (toolId.includes('planning') || toolId === 'todo') return { title: toolId === 'todo' ? 'Todo' : '规划', kind: 'tool', icon: Bot };
  return { title: toolView?.toolLabel ?? '工具操作', kind: 'tool', icon: Wrench };
}

function approvalModelLabel(model: string): string {
  if (!model || /(?:^|[./_-])luna(?:$|[./_-])/i.test(model)) return 'Luna Max';
  return model.split('/').at(-1)?.slice(0, 80) || '审批模型';
}

function approvalDecisionDetail(
  decision: ApprovalDecisionView,
): string {
  const outcome = decision.status === 'failed_closed'
    ? '审批模型未形成可验证裁决，系统已按拒绝处理；原操作没有执行。'
    : decision.decision === 'approve'
      ? '审批 Agent 认为已绑定的操作预览可执行。'
      : decision.decision === 'deny'
        ? '审批 Agent 认为这次操作不应执行；原操作没有获得执行权限。'
        : '审批 Agent 只读取用户请求、当前任务、结构化预览和既有裁决，不读取当前 Agent 的输出或推理；无需人工操作。';
  const rationale = decision.rationaleSummary
    ? ` 裁决说明：${decision.rationaleSummary}`
    : '';
  const reasons = decision.reasonCodes.length
    ? ` 判定依据：${decision.reasonCodes.map(approvalDecisionReasonLabel).join('、')}。`
    : '';
  const history = decision.historyEntryCount !== null
    ? ` 已参考 ${decision.historyEntryCount} 条同一${decision.contextKind === 'room' ? ' Room' : ' Session'} 审批历史。`
    : '';
  const receipt = decision.receiptId ? ` 决策回执：${decision.receiptId}。` : '';
  return `${outcome}${rationale}${reasons}${history}${receipt}`;
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
  const calls = new Map<string, AgentActivityProjection['status']>();
  const names = new Set<string>();
  let latestResult = '';
  let latestError = '';
  for (const activity of activities) {
    if (!['tool_started', 'tool_progress', 'tool_finished'].includes(activity.kind)) continue;
    calls.set(text(activity.payload.toolCallId) || activity.id, activity.status);
    names.add(activityPresentation(activity).title);
    const view = publicToolResultView(activity);
    if (view.summary) latestResult = boundedInlineSummary(view.summary);
    if (view.error) latestError = boundedInlineSummary(view.error);
  }
  const statuses = [...calls.values()];
  const completed = statuses.filter((status) => status === 'completed').length;
  const failed = statuses.filter((status) => status === 'failed').length;
  const waiting = statuses.filter((status) => status === 'waiting').length;
  const running = statuses.filter((status) => status === 'running').length;
  const outcome = [
    completed ? `${completed} 已完成` : '',
    failed ? `${failed} 未完成` : '',
    waiting ? `${waiting} 待确认` : '',
    running ? `${running} 进行中` : '',
  ].filter(Boolean).join(' · ');
  return {
    count: calls.size,
    names: [...names].slice(0, 3).join(' · '),
    outcome,
    highlight: latestError || latestResult,
  };
}

function boundedInlineSummary(value: string, limit = 180): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
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

function useCopyableText(value: string): {
  copy: () => Promise<void>;
  state: 'idle' | 'copied' | 'failed';
} {
  const [receipt, setReceipt] = useState<{
    state: 'copied' | 'failed';
    value: string;
  } | null>(null);
  const state = receipt?.value === value ? receipt.state : 'idle';
  return {
    state,
    copy: async () => {
      try {
        await writeClipboardText(value);
        setReceipt({ state: 'copied', value });
      } catch {
        setReceipt({ state: 'failed', value });
      }
    },
  };
}


/**
 * Raw milliseconds stop being information almost immediately: a tool that has
 * been running for two minutes rendered as "98530095 ms", which a reader has to
 * decode before learning anything, and which looks like a bug even when the
 * number is correct. Milliseconds are kept only where they are the honest unit
 * — sub-second work, where "0.1 s" would round away the detail being reported.
 */
function elapsedLabel(elapsedMs: number): string {
  const ms = Math.max(0, Math.round(elapsedMs));
  if (ms < 1_000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(ms < 10_000 ? 1 : 0)} 秒`;
  if (ms < 3_600_000) {
    const minutes = Math.floor(ms / 60_000);
    const seconds = Math.round((ms % 60_000) / 1_000);
    return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`;
  }
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.round((ms % 3_600_000) / 60_000);
  return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
}


function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
