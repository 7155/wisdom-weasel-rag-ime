import { ArrowUpRight, BrainCircuit, CircleDashed, GitBranch, PencilLine, RefreshCcw, Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  Virtuoso,
  type ScrollSeekConfiguration,
  type ScrollSeekPlaceholderProps,
  type VirtuosoHandle,
} from 'react-virtuoso';
import { useShallow } from 'zustand/react/shallow';
import { Button, IconButton } from '@/components/primitives';
import type { AgentActivityProjection, AgentMessageProjection } from '@/contracts/agent-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { ActivitySummary } from './ActivitySummary';
import { AgentBlocks } from './BlockRenderer';
import { PersonaAvatar, type PersonaPresence } from './PersonaAvatar';
import { useAgentLiveStore } from '../state/live-store';
import { publicAgentErrorText } from '../public-error';

export function AgentTimeline({
  assistantName = '澄',
  sessionId,
  persona,
  modelSelectionAvailable,
  turnRecoveryDisabled = false,
  onSuggestion,
  onRetryTurn,
  onSwitchModel,
  onApprovalDecision,
  onOpenApproval,
  onRequestPermission,
  forkAvailable = false,
  rewriteAvailable = false,
  jumpRequest,
  scrollToLatestRequest = 0,
  onAtBottomChange,
  onForkFromMessage,
  onEditMessage,
}: {
  assistantName?: string;
  sessionId: string;
  persona?: AgentPersonaV1;
  modelSelectionAvailable: boolean;
  turnRecoveryDisabled?: boolean;
  onSuggestion: (value: string) => void;
  onRetryTurn: (turnId: string) => boolean;
  onSwitchModel: () => void;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  onOpenApproval?: (activity: AgentActivityProjection) => void;
  onRequestPermission?: () => void;
  forkAvailable?: boolean;
  rewriteAvailable?: boolean;
  jumpRequest?: { messageId: string; requestId: number };
  scrollToLatestRequest?: number;
  onAtBottomChange?: (atBottom: boolean) => void;
  onForkFromMessage?: (entryId: string) => void;
  onEditMessage?: (messageId: string) => void;
}) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [activeTargetId, setActiveTargetId] = useState('');
  const [visibleRange, setVisibleRange] = useState({ startIndex: 0, endIndex: 0 });
  /* -1 means "follow the active marker"; a real value pins the roving stop
     to wherever the keyboard user last was. */
  const [navFocusIndex, setNavFocusIndex] = useState(-1);
  const turnOrder = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    if (!projection) return emptyIds;
    return projection.turnOrder.filter((turnId) => {
      const turn = projection.turnsById[turnId];
      return Boolean(turn && (turn.messageIds.length > 0 || turn.activityIds.length > 0));
    });
  }));
  const markerKinds = useAgentLiveStore(useShallow((state) => turnOrder.map((turnId) => {
    const projection = state.projections[sessionId];
    const turn = projection?.turnsById[turnId];
    if (!turn) return 'complete';
    if (turn.status === 'failed') return 'failed';
    if (turn.status === 'queued' || turn.status === 'running' || turn.status === 'waiting') return 'active';
    const hasAssistant = turn.messageIds.some((messageId) => projection?.messagesById[messageId]?.role === 'assistant');
    return hasAssistant ? 'complete' : 'user';
  })));
  const markerUserPreviews = useAgentLiveStore(useShallow((state) => turnOrder.map((turnId) => {
    const projection = state.projections[sessionId];
    const turn = projection?.turnsById[turnId];
    const message = turn?.messageIds
      .map((messageId) => projection?.messagesById[messageId])
      .find((item) => item?.role === 'user');
    return messagePreview(message);
  })));
  const markerAssistantPreviews = useAgentLiveStore(useShallow((state) => turnOrder.map((turnId) => {
    const projection = state.projections[sessionId];
    const turn = projection?.turnsById[turnId];
    const messages = turn?.messageIds
      .map((messageId) => projection?.messagesById[messageId])
      .filter((item): item is AgentMessageProjection => (
        item?.role === 'assistant' && item.status !== 'streaming'
      )) ?? [];
    return messagePreview(messages.at(-1));
  })));
  const timelineComponents = useMemo(() => ({
    ScrollSeekPlaceholder: AgentTurnTombstone,
    Header: AgentTimelineScrollHeader,
    Footer: AgentTimelineScrollFooter,
  }), []);
  useEffect(() => {
    const lastIndex = Math.max(0, turnOrder.length - 1);
    setVisibleRange({ startIndex: lastIndex, endIndex: lastIndex });
  }, [sessionId]);
  useEffect(() => {
    if (scrollToLatestRequest <= 0 || turnOrder.length === 0) return;
    virtuosoRef.current?.scrollToIndex({
      index: turnOrder.length - 1,
      align: 'end',
      behavior: 'smooth',
    });
  }, [scrollToLatestRequest, turnOrder.length]);
  useEffect(() => {
    if (!jumpRequest?.messageId) return;
    const projection = useAgentLiveStore.getState().projections[sessionId];
    const index = projection?.turnOrder.findIndex(
      (turnId) => projection.turnsById[turnId]?.messageIds.includes(jumpRequest.messageId),
    ) ?? -1;
    if (index < 0) return;
    setActiveTargetId(jumpRequest.messageId);
    virtuosoRef.current?.scrollToIndex({ index, align: 'center', behavior: 'smooth' });
    let attempts = 0;
    let focusTimer = 0;
    let clearTimer = 0;
    const focusWhenMounted = () => {
      const target = document.querySelector<HTMLElement>(`[data-agent-message-id="${cssEscape(jumpRequest.messageId)}"]`);
      if (target) {
        target.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
        target.focus({ preventScroll: true });
        clearTimer = window.setTimeout(() => setActiveTargetId(''), 2_400);
        return;
      }
      attempts += 1;
      if (attempts < 30) focusTimer = window.setTimeout(focusWhenMounted, 50);
      else setActiveTargetId('');
    };
    focusWhenMounted();
    return () => {
      window.clearTimeout(focusTimer);
      window.clearTimeout(clearTimer);
    };
  }, [jumpRequest?.messageId, jumpRequest?.requestId, sessionId]);
  if (turnOrder.length === 0) {
    return <AgentWelcome assistantName={assistantName} persona={persona} onSuggestion={onSuggestion} />;
  }
  return (
    <div className="agent-timeline" aria-label="对话时间线" role="log">
      <Virtuoso
        ref={virtuosoRef}
        key={sessionId}
        data={turnOrder}
        computeItemKey={(_index, turnId) => turnId}
        // Open the latest turn below the workspace header, not against the
        // composer. While the viewport still fits, `followOutput` naturally
        // moves the transcript upward as output grows; once a user scrolls
        // away from the bottom, their reading position remains authoritative.
        followOutput={(isAtBottom) => isAtBottom ? 'auto' : false}
        initialTopMostItemIndex={{ index: 'LAST', align: 'start' }}
        increaseViewportBy={{ top: 320, bottom: 520 }}
        components={timelineComponents}
        rangeChanged={setVisibleRange}
        atBottomStateChange={onAtBottomChange}
        atBottomThreshold={120}
        scrollSeekConfiguration={agentScrollSeekConfiguration}
        itemContent={(_index, turnId) => (
          <AgentTurn
            key={turnId}
            assistantName={assistantName}
            sessionId={sessionId}
            turnId={turnId}
            persona={persona}
            modelSelectionAvailable={modelSelectionAvailable}
            turnRecoveryDisabled={turnRecoveryDisabled}
            onRetryTurn={onRetryTurn}
            onSwitchModel={onSwitchModel}
            onApprovalDecision={onApprovalDecision}
            onOpenApproval={onOpenApproval}
            onRequestPermission={onRequestPermission}
            forkAvailable={forkAvailable}
            rewriteAvailable={rewriteAvailable}
            activeTargetId={activeTargetId}
            onForkFromMessage={onForkFromMessage}
            onEditMessage={onEditMessage}
          />
        )}
      />
      {turnOrder.length > 1 ? (
        <nav
          className="agent-conversation-nav"
          aria-label="快速跳转对话"
          data-density={turnOrder.length > 40 ? 'dense' : turnOrder.length > 18 ? 'tight' : undefined}
          onKeyDown={(event) => {
            /* Roving tabindex: only the current marker is a Tab stop, so a
               60-turn conversation costs one Tab rather than sixty. Arrow
               keys move between markers, Home/End jump to the ends. */
            const keys = ['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft', 'Home', 'End'];
            if (!keys.includes(event.key)) return;
            const markers = Array.from(
              event.currentTarget.querySelectorAll<HTMLButtonElement>('button[data-marker="true"]'),
            );
            if (markers.length === 0) return;
            event.preventDefault();
            const current = markers.findIndex((marker) => marker === document.activeElement);
            const from = current === -1 ? navFocusIndex : current;
            const next = event.key === 'Home'
              ? 0
              : event.key === 'End'
                ? markers.length - 1
                : event.key === 'ArrowUp' || event.key === 'ArrowLeft'
                  ? Math.max(0, from - 1)
                  : Math.min(markers.length - 1, from + 1);
            setNavFocusIndex(next);
            markers[next]?.focus();
          }}
        >
          <span aria-hidden="true" />
          {turnOrder.map((turnId, index) => {
            const activeIndex = Math.floor((visibleRange.startIndex + visibleRange.endIndex) / 2);
            const position = turnOrder.length === 1 ? 50 : (index / (turnOrder.length - 1)) * 100;
            const userPreview = markerUserPreviews[index];
            const assistantPreview = markerAssistantPreviews[index];
            const markerKind = markerKinds[index];
            return (
              <button
                aria-current={index === activeIndex ? 'location' : undefined}
                aria-label={`跳到第 ${index + 1} 轮`}
                data-marker="true"
                tabIndex={index === (navFocusIndex >= 0 ? navFocusIndex : activeIndex) ? 0 : -1}
                onFocus={() => setNavFocusIndex(index)}
                data-edge={index === 0 ? 'start' : index === turnOrder.length - 1 ? 'end' : undefined}
                data-kind={markerKind}
                data-visible={index >= visibleRange.startIndex && index <= visibleRange.endIndex || undefined}
                key={turnId}
                onClick={() => virtuosoRef.current?.scrollToIndex({ index, align: 'center', behavior: 'smooth' })}
                style={{ '--agent-nav-position': `${position}%` } as CSSProperties}
                title={userPreview || assistantPreview || `第 ${index + 1} 轮`}
                type="button"
              >
                <span aria-hidden="true" className="agent-conversation-nav__preview">
                  <span className="agent-conversation-nav__preview-head">
                    <strong>第 {index + 1} 轮</strong>
                    <em data-kind={markerKind}>{turnMarkerLabel(markerKind)}</em>
                  </span>
                  {userPreview ? <small><b>你</b><span>{userPreview}</span></small> : null}
                  <small>
                    <b>{persona?.displayName ?? assistantName}</b>
                    <span>{assistantPreview || turnMarkerLabel(markerKind)}</span>
                  </small>
                </span>
              </button>
            );
          })}
        </nav>
      ) : null}
    </div>
  );
}

export const agentScrollSeekConfiguration = {
  enter: (velocity) => Math.abs(velocity) > 900,
  exit: (velocity) => Math.abs(velocity) < 120,
} satisfies ScrollSeekConfiguration;

function AgentTimelineScrollFooter() {
  return <div className="agent-timeline__footer-space" aria-hidden="true" />;
}

function AgentTimelineScrollHeader() {
  return <div className="agent-timeline__header-space" aria-hidden="true" />;
}

function AgentTurnTombstone({
  height,
}: ScrollSeekPlaceholderProps) {
  return (
    <div
      aria-hidden="true"
      className="agent-turn-tombstone"
      style={{ height }}
    />
  );
}

export function AgentTurn({
  assistantName = '澄',
  sessionId,
  turnId,
  persona,
  modelSelectionAvailable = false,
  turnRecoveryDisabled = false,
  onRetryTurn,
  onSwitchModel,
  onApprovalDecision,
  onOpenApproval,
  onRequestPermission,
  forkAvailable = false,
  rewriteAvailable = false,
  activeTargetId = '',
  onForkFromMessage,
  onEditMessage,
}: {
  assistantName?: string;
  sessionId: string;
  turnId: string;
  persona?: AgentPersonaV1;
  modelSelectionAvailable?: boolean;
  turnRecoveryDisabled?: boolean;
  onRetryTurn?: (turnId: string) => boolean;
  onSwitchModel?: () => void;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  onOpenApproval?: (activity: AgentActivityProjection) => void;
  onRequestPermission?: () => void;
  forkAvailable?: boolean;
  rewriteAvailable?: boolean;
  activeTargetId?: string;
  onForkFromMessage?: (entryId: string) => void;
  onEditMessage?: (messageId: string) => void;
}) {
  const turn = useAgentLiveStore((state) => state.projections[sessionId]?.turnsById[turnId]);
  const userIds = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    return (projection?.turnsById[turnId]?.messageIds ?? []).filter((id) => projection?.messagesById[id]?.role === 'user');
  }));
  const assistantMessages = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    return (projection?.turnsById[turnId]?.messageIds ?? [])
      .map((id) => projection?.messagesById[id])
      .filter((message): message is AgentMessageProjection => message?.role === 'assistant');
  }));
  const activities = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    return (projection?.turnsById[turnId]?.activityIds ?? []).map((id) => projection?.activitiesById[id]).filter(Boolean);
  }));
  /* Retrying creates a new optimistic turn, not a successful outcome. The
     control acknowledges only that local admission happened and stops a second
     identical submission; the new turn owns its eventual success or failure. */
  const [retryRequestedFor, setRetryRequestedFor] = useState('');
  const blockFailure = useAgentLiveStore((state) => {
    const projection = state.projections[sessionId];
    const messageIds = projection?.turnsById[turnId]?.messageIds ?? [];
    for (const messageId of messageIds) {
      const message = projection?.messagesById[messageId];
      if (message?.role !== 'assistant') continue;
      const errorBlock = message.blocks.find((block) => block.type === 'error');
      const messageText = text(errorBlock?.data.message ?? errorBlock?.data.summary);
      if (messageText) return messageText;
    }
    return '';
  });
  if (!turn) return null;
  const rawFailure = turn.failure || blockFailure;
  const failure = turn.status === 'failed' ? publicAgentErrorText(rawFailure) : '';
  const retryRequested = retryRequestedFor === `${turnId}:${turn.status}`;
  const showWorking = turn.status === 'queued' || turn.status === 'running';
  const presence: PersonaPresence = turn.status === 'failed' ? 'warning' : turn.status === 'running' || turn.status === 'waiting' ? 'thinking' : 'done';
  const timelineEntries = interleavedTurnEntries(assistantMessages, activities);
  const streamingMessageId = activeStreamingMessageId(turn.status, assistantMessages);
  return (
    <article className="agent-turn" data-turn-status={turn.status}>
      {userIds.map((messageId) => <MessageView key={messageId} sessionId={sessionId} messageId={messageId} user forkAvailable={forkAvailable} rewriteAvailable={rewriteAvailable} historyTarget={activeTargetId === messageId} onForkFromMessage={onForkFromMessage} onEditMessage={onEditMessage} />)}
      {assistantMessages.length > 0 || activities.length > 0 || failure || showWorking ? (
        <div className="agent-assistant-turn">
          <PersonaAvatar fallbackName={assistantName} persona={persona} presence={showWorking ? 'thinking' : presence} />
          <div className="agent-assistant-turn__body">
            <header><strong>{persona?.displayName ?? assistantName}</strong><span>{showWorking ? '正在处理' : turnStatusLabel(turn.status)}</span></header>
            {showWorking ? <AssistantWorkingState activities={activities} startedAtMs={turn.createdAtMs} /> : null}
            <div className="agent-turn-sequence" aria-label="本轮响应过程">
              {timelineEntries.map((entry) => entry.kind === 'message' ? (
                <div data-timeline-kind="message" key={entry.message.id}>
                  <MessageView
                    sessionId={sessionId}
                    messageId={entry.message.id}
                    forkAvailable={forkAvailable}
                    historyTarget={activeTargetId === entry.message.id}
                    streaming={entry.message.id === streamingMessageId}
                    onApprovalDecision={onApprovalDecision}
                    onForkFromMessage={onForkFromMessage}
                  />
                </div>
              ) : (
                <div data-timeline-kind="activity" key={entry.key}>
                  <ActivityGroupView
                    activities={entry.activities}
                    onApprovalDecision={onApprovalDecision}
                    onOpenApproval={onOpenApproval}
                    onRequestPermission={onRequestPermission}
                  />
                </div>
              ))}
            </div>
            {failure ? (
              <div className="agent-turn__failure" role="alert">
                <TriangleAlert size={17} />
                <span><strong>本轮未完成</strong><small>{failure}</small></span>
                {onRetryTurn && onSwitchModel ? (
                  <div className="agent-turn__failure-actions">
                    <Button
                      size="small"
                      variant="primary"
                      leadingIcon={<RefreshCcw size={14} />}
                      disabled={turnRecoveryDisabled || retryRequested}
                      onClick={() => {
                        if (onRetryTurn(turnId)) {
                          setRetryRequestedFor(`${turnId}:${turn.status}`);
                        }
                      }}
                    >
                      {retryRequested ? '已创建重试轮次' : '重试本轮'}
                    </Button>
                    <Button size="small" variant="quiet" leadingIcon={<BrainCircuit size={14} />} disabled={turnRecoveryDisabled || !modelSelectionAvailable} onClick={onSwitchModel}>切换模型</Button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </article>
  );
}

type TurnTimelineItem = {
  kind: 'message';
  message: AgentMessageProjection;
  createdAtMs: number;
  sequence?: number;
  fallbackOrder: number;
} | {
  kind: 'activity';
  activity: AgentActivityProjection;
  createdAtMs: number;
  sequence?: number;
  fallbackOrder: number;
};

export type InterleavedTurnEntry =
  | { kind: 'message'; message: AgentMessageProjection }
  | { kind: 'activity-group'; key: string; activities: AgentActivityProjection[] };

export function interleavedTurnEntries(
  messages: AgentMessageProjection[],
  activities: AgentActivityProjection[],
): InterleavedTurnEntry[] {
  const items: TurnTimelineItem[] = [
    ...messages.map((message, index): TurnTimelineItem => ({
      kind: 'message',
      message,
      createdAtMs: message.createdAtMs,
      sequence: message.timelineSequence,
      fallbackOrder: index,
    })),
    ...activities.map((activity, index): TurnTimelineItem => ({
      kind: 'activity',
      activity,
      createdAtMs: activity.createdAtMs,
      sequence: activity.timelineSequence,
      fallbackOrder: messages.length + index,
    })),
  ];
  items.sort(compareTimelineItems);

  return items.reduce<InterleavedTurnEntry[]>((entries, item) => {
    if (item.kind === 'message') {
      entries.push({ kind: 'message', message: item.message });
      return entries;
    }
    const previous = entries[entries.length - 1];
    if (previous?.kind === 'activity-group') {
      previous.activities.push(item.activity);
      return entries;
    }
    entries.push({
      kind: 'activity-group',
      key: `activity:${item.activity.id}`,
      activities: [item.activity],
    });
    return entries;
  }, []);
}

function activeStreamingMessageId(
  turnStatus: string,
  messages: AgentMessageProjection[],
): string {
  if (turnStatus !== 'running') return '';
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.status === 'streaming') return message.id;
  }
  return '';
}

function compareTimelineItems(left: TurnTimelineItem, right: TurnTimelineItem): number {
  if (left.sequence !== undefined && right.sequence !== undefined && left.sequence !== right.sequence) {
    return left.sequence - right.sequence;
  }
  const byTime = left.createdAtMs - right.createdAtMs;
  if (byTime !== 0) return byTime;
  return left.fallbackOrder - right.fallbackOrder;
}

function AssistantWorkingState({
  activities,
  startedAtMs,
}: {
  activities: AgentActivityProjection[];
  startedAtMs: number;
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const detail = useMemo(() => workingDetail(activities), [activities]);
  return (
    <div className="agent-assistant-pending" role="status" aria-live="polite">
      <CircleDashed aria-hidden="true" size={17} />
      <span><strong>思考中 <time>{formatElapsed(nowMs - startedAtMs)}</time></strong><small>{detail}</small></span>
      <i className="agent-working-dots" aria-hidden="true"><b /><b /><b /></i>
    </div>
  );
}

function MessageView({
  sessionId,
  messageId,
  user = false,
  forkAvailable = false,
  rewriteAvailable = false,
  historyTarget = false,
  streaming,
  onApprovalDecision,
  onForkFromMessage,
  onEditMessage,
}: {
  sessionId: string;
  messageId: string;
  user?: boolean;
  forkAvailable?: boolean;
  rewriteAvailable?: boolean;
  historyTarget?: boolean;
  streaming?: boolean;
  /* Approval blocks can arrive inside an ordinary assistant message, not only
     inside an activity group. Without this the renderer has no decision
     handler and silently drops its Reject/Approve controls. */
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  onForkFromMessage?: (entryId: string) => void;
  onEditMessage?: (messageId: string) => void;
}) {
  const message = useAgentLiveStore((state) => state.projections[sessionId]?.messagesById[messageId]);
  if (!message) return null;
  const visibleBlocks = user ? message.blocks : message.blocks.filter((block) => block.type !== 'error');
  const delivery = user
    ? text(message.blocks.find((block) => block.type === 'text')?.data.delivery)
    : '';
  const branchText = message.blocks.map((block) => (
    text(block.data.text ?? block.data.markdown ?? block.data.message ?? block.data.summary)
  )).filter(Boolean).join('\n').trim();
  const canFork = forkAvailable
    && (message.status === 'completed' || message.status === 'failed')
    && !messageId.startsWith('local:')
    && Boolean(branchText)
    && Boolean(onForkFromMessage);
  const canEdit = user
    && rewriteAvailable
    && (message.status === 'completed' || message.status === 'failed')
    && !messageId.startsWith('local:')
    && Boolean(branchText)
    && Boolean(onEditMessage);
  const showStreaming = !user && (streaming ?? message.status === 'streaming');
  const visibleStatus = showStreaming ? 'streaming' : message.status === 'streaming' ? 'completed' : message.status;
  return user ? (
    <div className="agent-user-message-shell" data-actions={canFork || canEdit || undefined} data-agent-message-id={messageId} data-history-target={historyTarget || undefined} tabIndex={-1}>
      <div className="agent-user-message" data-status={message.status}>
        <AgentBlocks blocks={visibleBlocks} sessionId={sessionId} onApprovalDecision={onApprovalDecision} />
        {delivery === 'steer' || delivery === 'followUp' ? (
          <small className="agent-user-message__delivery" data-delivery={delivery}>
            {delivery === 'steer' ? '干预当前执行' : '完成后接续'}
          </small>
        ) : null}
        {message.attachments.length ? <small>{message.attachments.length} 个附件</small> : null}
      </div>
      {canFork || canEdit ? (
        <div className="agent-message-actions">
          {canEdit ? (
            <IconButton
              label="修改这条消息"
              icon={<PencilLine size={14} />}
              size="small"
              onClick={() => onEditMessage?.(messageId)}
              tooltip
              tooltipSide="left"
            />
          ) : null}
          {canFork ? (
          <IconButton
            label="从这条消息创建分支"
            icon={<GitBranch size={14} />}
            size="small"
            onClick={() => onForkFromMessage?.(messageId)}
            tooltip
            tooltipSide="left"
          />
          ) : null}
        </div>
      ) : null}
    </div>
  ) : (
    <div className="agent-assistant-message-shell" data-actions={canFork || undefined}>
      <div className="agent-assistant-message" data-status={visibleStatus} data-agent-message-id={messageId} data-history-target={historyTarget || undefined} tabIndex={-1}>
        <AgentBlocks blocks={visibleBlocks} sessionId={sessionId} streaming={showStreaming} onApprovalDecision={onApprovalDecision} />
        {showStreaming ? <span className="agent-streaming-cursor" aria-label="正在生成" /> : null}
      </div>
      {!showStreaming ? <AgentMessageUsage message={message} /> : null}
      {canFork ? (
        <div className="agent-message-actions">
          <IconButton
            label="从这条消息创建分支"
            icon={<GitBranch size={14} />}
            size="small"
            onClick={() => onForkFromMessage?.(messageId)}
            tooltip
            tooltipSide="left"
          />
        </div>
      ) : null}
    </div>
  );
}

function AgentMessageUsage({ message }: { message: AgentMessageProjection }) {
  const usage = message.usage;
  if (!usage || usage.totalTokens <= 0) return null;
  const promptTokens = usage.input + usage.cacheRead + usage.cacheWrite;
  const cachePercent = promptTokens > 0 ? Math.round((usage.cacheRead / promptTokens) * 100) : 0;
  return (
    <div className="agent-message-usage" aria-label="本轮模型与 Token 用量">
      {message.model ? <span className="agent-message-usage__model" title="本轮模型">{message.model}</span> : null}
      {message.provider ? <span title="模型提供方">{message.provider}</span> : null}
      <span title="输入 Token">输入 {formatTokens(promptTokens)}</span>
      <span title="输出 Token">输出 {formatTokens(usage.output)}</span>
      <strong title="本轮缓存读取占提示 Token 的比例">缓存 {cachePercent}%</strong>
    </div>
  );
}

function ActivityGroupView({
  activities,
  onApprovalDecision,
  onOpenApproval,
  onRequestPermission,
}: {
  activities: AgentActivityProjection[];
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  onOpenApproval?: (activity: AgentActivityProjection) => void;
  onRequestPermission?: () => void;
}) {
  const compactions = activities.filter((activity) => activity.kind === 'context_compaction');
  const ordinary = activities.filter((activity) => (
    activity.kind !== 'context_compaction'
    && (!isAgentPlanActivity(activity) || activity.status === 'failed')
  ));
  return (
    <>
      {compactions.map((activity) => <ContextCompactionNotice key={activity.id} activity={activity} />)}
      {ordinary.length ? (
        <ActivitySummary
          activities={ordinary}
          inline
          onApprovalDecision={onApprovalDecision}
          onOpenApproval={onOpenApproval}
          onRequestPermission={onRequestPermission}
        />
      ) : null}
    </>
  );
}

function isAgentPlanActivity(activity: AgentActivityProjection): boolean {
  return text(activity.payload.toolId ?? activity.payload.toolName) === 'agent_plan';
}

function ContextCompactionNotice({ activity }: { activity: AgentActivityProjection }) {
  const running = activity.status === 'running';
  const failed = activity.status === 'failed';
  const before = numberValue(activity.payload.tokensBefore);
  const after = numberValue(activity.payload.estimatedTokensAfter);
  const reason = text(activity.payload.reason);
  const reasonLabel = reason === 'manual' ? '手动触发' : reason === 'overflow' ? '溢出恢复' : '达到自动阈值';
  return (
    <div className="agent-compaction-notice" data-state={activity.status} role="status" aria-live="polite">
      <span className="agent-compaction-notice__mark" aria-hidden="true"><RefreshCcw size={15} /></span>
      <span>
        <strong>{running ? '正在压缩上下文' : failed ? '上下文压缩失败' : '上下文已压缩'}</strong>
        <small>
          {running
            ? `${reasonLabel}，正在生成可继续对话的摘要`
            : before > 0 && after > 0
              ? `${formatTokens(before)} → 约 ${formatTokens(after)}，下一轮响应后校准实际占用`
              : `${reasonLabel}，下一轮响应后校准实际占用`}
        </small>
      </span>
      {running ? <i className="agent-compaction-notice__pulse" aria-hidden="true" /> : null}
    </div>
  );
}

function AgentWelcome({
  assistantName,
  persona,
  onSuggestion,
}: {
  assistantName: string;
  persona?: AgentPersonaV1;
  onSuggestion: (value: string) => void;
}) {
  const suggestions = [
    ['回顾今天', '结合近期对话，帮我回顾今天的进展。'],
    ['检查运行状态', '检查输入法、模型、RAG 与 Memory 的当前状态。'],
    ['整理下一步', '根据当前项目上下文，整理三个可以立刻推进的下一步。'],
  ];
  return (
    <div className="agent-welcome">
      <PersonaAvatar fallbackName={assistantName} persona={persona} size="hero" />
      <div><h2>今天想先从哪里开始？</h2><p>{persona?.tagline ?? '连续对话、检索和整理都从这里开始。'}</p></div>
      <div className="agent-welcome__suggestions">
        {suggestions.map(([title, prompt]) => (
          <Button key={title} variant="quiet" leadingIcon={<Sparkles size={15} />} trailingIcon={<ArrowUpRight size={14} />} onClick={() => onSuggestion(prompt)}>{title}</Button>
        ))}
      </div>
    </div>
  );
}

function turnStatusLabel(status: string): string {
  if (status === 'running') return '正在响应';
  if (status === 'waiting') return '等待确认';
  if (status === 'failed') return '本轮失败';
  if (status === 'queued') return '排队中';
  if (status === 'aborted') return '已停止';
  return '已完成';
}

function turnMarkerLabel(kind: string): string {
  if (kind === 'active') return '进行中';
  if (kind === 'failed') return '未完成';
  if (kind === 'user') return '待回复';
  return '已完成';
}

function messagePreview(message?: AgentMessageProjection): string {
  if (!message) return '';
  const value = message.blocks.map((block) => (
    text(block.data.text ?? block.data.markdown ?? block.data.code ?? block.data.message ?? block.data.summary)
  )).filter(Boolean).join(' ').replace(/\s+/gu, ' ').trim();
  return value.slice(0, 140);
}

const emptyIds: string[] = [];

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function cssEscape(value: string): string {
  return typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
    ? CSS.escape(value)
    : value.replace(/["\\]/gu, '\\$&');
}

function workingDetail(activities: AgentActivityProjection[]): string {
  const latest = [...activities].reverse().find((activity) => activity.status === 'running');
  if (text(latest?.payload.phase) === 'provider_retry') {
    return latest?.summary || '模型连接暂时不可用，正在自动重试。';
  }
  const tool = text(latest?.payload.toolName ?? latest?.payload.toolId).toLowerCase();
  if (tool.includes('memory')) return '正在读取并整理相关记忆，工具明细会实时显示在下方。';
  if (tool.includes('knowledge') || tool.includes('rag')) return '正在检索知识库，工具明细会实时显示在下方。';
  if (tool.includes('planning')) return '正在整理计划与下一步。';
  if (latest) return '正在执行工具，进度和结果会实时显示在下方。';
  return '消息已收到，正在组织本轮响应。';
}

function formatElapsed(durationMs: number): string {
  const seconds = Math.max(0, Math.floor(durationMs / 1_000));
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return minutes > 0 ? `${minutes}分 ${remaining}秒` : `${remaining}秒`;
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(Math.max(0, Math.round(value)));
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 0;
}
