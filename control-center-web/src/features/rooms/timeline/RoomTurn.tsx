import {
  CheckCircle2,
  Braces,
  CircleAlert,
  ChevronRight,
  CircleStop,
  Clock3,
  ExternalLink,
  LoaderCircle,
  Route,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  X,
} from 'lucide-react';
import { Fragment, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/primitives';
import {
  approvalDecisionView,
  approvalDecisionReasonLabel,
  approvalNeedsHumanDecision,
} from '@/contracts/approval-decision';
import {
  roomActivityHasPublicInformation,
  type RoomActivityProjection,
  type RoomMessageProjection,
  type RoomProjectionState,
  type RoomTurnProjection,
} from '@/contracts/room-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { AgentBlocks, MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import {
  PublicToolError,
  PublicToolFields,
  PublicToolOutput,
  PublicToolRequest,
} from '@/features/agent/timeline/ActivitySummary';
import {
  toggleDisclosureOnKeyPreservingAnchor,
  toggleDisclosurePreservingAnchor,
} from '@/features/agent/timeline/disclosure-anchor';
import { publicToolResultView } from '@/features/agent/timeline/public-tool-result';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { publicToolName } from '@/features/agent/tool-presentation';
import {
  roomActivityNeedsSessionAction,
  selectRoomTurnExecution,
  type RoomExecutionLane,
} from '../runtime/room-execution-lanes';
import { useRoomUpdateClock } from '../runtime/use-room-update-clock';
import type { PendingRoomQuestion } from '../room-question';
import { RoomQuestionDialog } from '../RoomQuestionDialog';
import { roomProjection, useRoomLiveStore } from '../state/live-store';
import {
  roomPublicActivityText,
  roomPublicToolResultView,
} from './room-tool-presentation';

interface TimelineParticipant {
  id: string;
  sessionId: string;
  roleId: string;
  roleVersion: string;
  displayName: string;
}

interface TimelineRoom {
  participants: TimelineParticipant[];
}

interface RoomTurnProps {
  turnId: string;
  roomId?: string;
  room?: TimelineRoom;
  projection?: RoomProjectionState;
  personas: AgentPersonaV1[];
  abortingTurnIds?: ReadonlySet<string>;
  roomSyncState?: 'recovering' | 'failed' | 'synced';
  onAbortTurn?: (rootId: string) => void;
  retryingTurn?: boolean;
  onRetryTurn?: (message: string) => void;
  onAnswerQuestion?: (
    question: PendingRoomQuestion,
    value: string,
  ) => Promise<boolean>;
}

const roomTerminalPostLabels: Readonly<Record<string, string>> = {
  alignment: '已确认',
  result: '已完成',
  work_result: '已交付',
  review_result: '复核完成',
  handoff: '已转交',
  wait: '等待继续',
  blocked: '已阻塞',
};

function roomVisibleConversationMessages(
  messages: RoomMessageProjection[],
): RoomMessageProjection[] {
  const latestByEventIdentity = new Map<string, RoomMessageProjection>();
  for (const message of messages) {
    latestByEventIdentity.set(
      message.sourceEventId
        || message.sourceMessageId
        || message.message?.id
        || message.id,
      message,
    );
  }
  return messages.filter((message) => (
    latestByEventIdentity.get(
      message.sourceEventId
        || message.sourceMessageId
        || message.message?.id
        || message.id,
    ) === message
  ));
}

const roomActiveEventFreshnessMs = 15_000;
const emptyExpandedLaneKeys: ReadonlySet<string> = new Set();

function roomPostReportLabel(message: RoomMessageProjection): string {
  if (message.projectionKind === 'execution') return '';
  if (message.postKind === 'result') return '最终答复';
  if (message.postKind === 'work_result') return '工作交付';
  if (message.postKind === 'review_result') return '独立复核';
  if (message.postKind === 'alignment') return '需求理解确认';
  if (message.postKind === 'handoff') return '交接说明';
  if (message.postKind === 'wait') return '等待说明';
  if (message.postKind === 'blocked') return '遇到的问题';
  return '进度更新';
}


/** Render one Root as independent participant/dispatch execution lanes. */
export function RoomTurn({
  turnId,
  roomId = '',
  room,
  projection: providedProjection,
  personas,
  roomSyncState,
  abortingTurnIds = new Set(),
  onAbortTurn,
  retryingTurn = false,
  onRetryTurn,
  onAnswerQuestion,
}: RoomTurnProps) {
  useRoomLiveStore((state) => (
    providedProjection ? 0 : state.turnRevisions[roomId]?.[turnId] ?? 0
  ));
  const projection = providedProjection ?? roomProjection(roomId);
  const laneDisclosureScope = `${projection.roomId}\u001f${turnId}`;
  const [laneDisclosure, setLaneDisclosure] = useState<{
    expandedLaneKeys: ReadonlySet<string>;
    scope: string;
  }>(() => ({ expandedLaneKeys: new Set(), scope: laneDisclosureScope }));
  const expandedLaneKeys = laneDisclosure.scope === laneDisclosureScope
    ? laneDisclosure.expandedLaneKeys
    : emptyExpandedLaneKeys;
  const turn = projection.turnsById[turnId];
  const previousTurnStatus = usePrevious(turn?.status);
  const nowMs = useRoomUpdateClock(Boolean(
    turn && ['queued', 'running'].includes(turn.status),
  ));
  const { activities, lanes, messageIds, userMessageIds } = selectRoomTurnExecution(
    projection,
    turnId,
  );
  const conversationMessages = roomVisibleConversationMessages(
    messageIds
      .map((messageId) => projection.messagesById[messageId])
      .filter((message): message is RoomMessageProjection => Boolean(message)),
  );
  type TimelineEntry =
    | { key: string; kind: 'user'; message: RoomMessageProjection }
    | { key: string; kind: 'lane'; lane: RoomExecutionLane; includeDetails: boolean };
  const timelineEntries: TimelineEntry[] = [];
  const laneSegmentCounts = new Map<string, number>();
  for (const message of conversationMessages) {
    if (message.role === 'user') {
      timelineEntries.push({ key: `message:${message.id}`, kind: 'user', message });
      continue;
    }
    const sourceLane = lanes.find((lane) => lane.messageIds.includes(message.id));
    if (!sourceLane) continue;
    const previous = timelineEntries.at(-1);
    if (previous?.kind === 'lane' && previous.lane.key === sourceLane.key) {
      previous.lane = {
        ...previous.lane,
        messageIds: [...previous.lane.messageIds, message.id],
      };
      continue;
    }
    const segment = (laneSegmentCounts.get(sourceLane.key) ?? 0) + 1;
    laneSegmentCounts.set(sourceLane.key, segment);
    timelineEntries.push({
      key: `lane:${sourceLane.key}:${segment}`,
      kind: 'lane',
      lane: { ...sourceLane, messageIds: [message.id] },
      includeDetails: false,
    });
  }
  for (const lane of lanes) {
    const laneEntries = timelineEntries.filter((entry): entry is Extract<TimelineEntry, { kind: 'lane' }> => (
      entry.kind === 'lane' && entry.lane.key === lane.key
    ));
    const finalEntry = laneEntries.at(-1);
    if (finalEntry) {
      finalEntry.includeDetails = true;
    } else {
      timelineEntries.push({
        key: `lane:${lane.key}:activity`,
        kind: 'lane',
        lane,
        includeDetails: true,
      });
    }
  }
  const streamingLaneEntryKeys = timelineEntries.flatMap((entry) => (
    entry.kind === 'lane'
    && entry.lane.messageIds.some((messageId) => (
      projection.messagesById[messageId]?.status === 'streaming'
    ))
      ? [entry.key]
      : []
  ));
  const streamingLaneEntryKeySignature = streamingLaneEntryKeys.join('\u001e');
  useEffect(() => {
    if (!streamingLaneEntryKeySignature) return;
    const entryKeys = streamingLaneEntryKeySignature.split('\u001e');
    setLaneDisclosure((current) => {
      const next = new Set(
        current.scope === laneDisclosureScope
          ? current.expandedLaneKeys
          : emptyExpandedLaneKeys,
      );
      let changed = current.scope !== laneDisclosureScope;
      for (const key of entryKeys) {
        if (next.has(key)) continue;
        next.add(key);
        changed = true;
      }
      return changed
        ? { expandedLaneKeys: next, scope: laneDisclosureScope }
        : current;
    });
  }, [laneDisclosureScope, streamingLaneEntryKeySignature]);
  // Room/session lifecycle events may legitimately have no public Root. They
  // belong in the execution ledger, never as a synthetic Post in the chat.
  if (!turnId || turnId === 'unscoped' || !turn) return null;
  const responseUsageActivities = turn.activityIds
    .map((activityId) => projection.activitiesById[activityId])
    .filter((activity): activity is RoomActivityProjection => Boolean(activity));
  const rootTerminal = ['completed', 'failed', 'aborted'].includes(turn.status);
  const pendingAction = rootTerminal
    ? undefined
    : pendingRoomSessionAction(activities, projection, lanes, room);
  const rootId = turn.rootId || turnId;
  const rootHasActiveLane = lanes.length === 0
    ? ['queued', 'running'].includes(turn.status)
    : lanes.some((lane) => {
        const participantId = lane.participantId ?? '';
        const terminal = lane.dispatchId
          ? (turn.terminalDispatchIds ?? []).includes(lane.dispatchId)
          : participantId
            ? (turn.terminalParticipantIds ?? []).includes(participantId)
            : ['completed', 'failed', 'aborted'].includes(turn.status);
        return !terminal && !lane.activities.some(roomActivityNeedsSessionAction);
      });
  const pendingQuestion = projection.pendingUserQuestion?.rootId === rootId
    ? projection.pendingUserQuestion
    : undefined;
  const rootActive = ['queued', 'running'].includes(turn.status)
    && rootHasActiveLane
    && !pendingAction;
  const rootStopping = abortingTurnIds.has(rootId);
  const terminalIssue = turn.status === 'failed' || turn.status === 'aborted'
    ? turn.status
    : '';
  const publicFailure = publicAgentErrorText(
    turn.failure,
    '伙伴未能完成这轮任务，你可以调整原消息后再试。',
  );
  const outcome = roomTurnOutcome(
    projection,
    lanes,
    turn,
    publicFailure,
  );
  const outcomeArriving = Boolean(
    outcome && ['queued', 'running'].includes(previousTurnStatus ?? ''),
  );
  const retrySource = outcome && outcome.state !== 'completed'
    ? userMessageIds
        .map((messageId) => projection.messagesById[messageId])
        .find((message) => (
          Boolean(message?.text.trim())
          && (message?.message?.attachments.length ?? 0) === 0
        ))
    : undefined;
  const retryMessage = retrySource?.text ?? '';
  return <article className="room-turn" data-turn-status={turn.status}>
    {timelineEntries.map((entry) => {
      if (entry.kind === 'user') {
        return <RoomUserPost
          key={entry.key}
          message={entry.message}
          roomId={projection.roomId}
        />;
      }
      const { includeDetails, lane } = entry;
      const participant = room?.participants.find((item) => item.id === lane.participantId);
      const persona = personas.find((item) => (
        item.roleId === participant?.roleId && item.version === participant.roleVersion
      ));
      const messages = lane.messageIds
        .map((id) => projection.messagesById[id])
        .filter((message): message is RoomMessageProjection => Boolean(message));
      const visibleMessages = roomVisibleConversationMessages(messages);
      const participantId = lane.participantId ?? '';
      const explicitlyTerminal = lane.dispatchId
        ? (turn.terminalDispatchIds ?? []).includes(lane.dispatchId)
        : participantId
          ? (turn.terminalParticipantIds ?? []).includes(participantId)
          : false;
      const laneFailed = (
        lane.dispatchId
          ? (turn.failedDispatchIds ?? []).includes(lane.dispatchId)
          : participantId
            ? (turn.failedParticipantIds ?? []).includes(participantId)
            : false
      ) || (!explicitlyTerminal && turn.status === 'failed');
      const laneAborted = (
        lane.dispatchId
          ? (turn.abortedDispatchIds ?? []).includes(lane.dispatchId)
          : participantId
            ? (turn.abortedParticipantIds ?? []).includes(participantId)
            : false
      ) || (!explicitlyTerminal && turn.status === 'aborted');
      // A terminal Root is authoritative even when a transient resume Dispatch
      // never appeared in the terminal-id lists.
      const laneTerminal = rootTerminal || explicitlyTerminal;
      const laneActive = !laneTerminal && !laneFailed && !laneAborted;
      const laneAction = rootTerminal
        ? undefined
        : lane.activities.find(roomActivityNeedsSessionAction);
      const laneFreshness = roomLaneFreshness(
        lane,
        projection,
        turn,
        nowMs,
        roomSyncState,
      );
      const laneOutcome = visibleMessages.reduce((outcome, message) => (
        roomTerminalPostLabels[message.postKind ?? '']
          ? message.postKind ?? outcome
          : outcome
      ), '');
      const laneComplete = (laneTerminal || Boolean(laneOutcome)) && !laneFailed && !laneAborted;
      const laneStillActive = laneActive && !laneComplete;
      const laneMotionActive = laneStillActive
        && !laneAction
        && laneFreshness.state === 'fresh';
      const authoritativeStatusLabel = laneAction
        ? roomInteractionStatusLabel(laneAction)
        : laneOutcome === 'blocked'
          ? '已阻塞'
          : laneFailed
            ? '未完成'
            : laneAborted
              ? '已停止'
              : laneComplete
                ? roomTerminalPostLabels[laneOutcome] ?? '已完成'
                : laneStillActive
                  ? '执行中'
                  : '等待后续';
      const statusLabel = laneStillActive && !laneAction && laneFreshness.state === 'disconnected'
        ? '状态可能过期'
        : laneStillActive && !laneAction && laneFreshness.state === 'stale'
          ? '等待新进展'
          : authoritativeStatusLabel;
      const laneState = laneFailed
        ? 'failed'
        : laneAborted
          ? 'aborted'
          : laneAction
            ? 'waiting'
            : laneOutcome === 'wait'
              ? 'waiting'
              : laneOutcome === 'blocked'
                ? 'failed'
                : laneComplete
                  ? 'completed'
                  : laneStillActive
                    ? 'running'
                    : 'waiting';
      const laneWork = roomLaneWorkSummary(
        lane.activities,
        participant?.displayName,
        laneState,
      );
      const latestPublicResult = [...visibleMessages].reverse().find((message) => (
        message.projectionKind === 'post' && Boolean(message.text.trim())
      ));
      const laneHeadline = latestPublicResult
        ? `${roomPostReportLabel(latestPublicResult) || '公开结果'}：${roomReportPreview(latestPublicResult.text)}`
        : laneWork.title;
      const laneDetail = latestPublicResult
        ? `${roomPostReportLabel(latestPublicResult) || '公开结果'} · ${laneWork.detail}`
        : laneWork.detail;
      return <Fragment key={entry.key}><details
        className="room-agent-lane"
        data-dispatch-id={lane.dispatchId || undefined}
        data-has-result={latestPublicResult ? true : undefined}
        data-motion={laneStillActive && !laneAction ? laneFreshness.state : 'settled'}
        data-outcome={laneOutcome || undefined}
        data-root-id={rootId}
        data-state={laneState}
        data-lane-entry-key={entry.key}
        onToggle={(event) => {
          const expanded = event.currentTarget.open;
          setLaneDisclosure((current) => {
            const next = new Set(
              current.scope === laneDisclosureScope
                ? current.expandedLaneKeys
                : emptyExpandedLaneKeys,
            );
            if (expanded === next.has(entry.key)) {
              return current.scope === laneDisclosureScope
                ? current
                : { expandedLaneKeys: next, scope: laneDisclosureScope };
            }
            if (expanded) next.add(entry.key);
            else next.delete(entry.key);
            return { expandedLaneKeys: next, scope: laneDisclosureScope };
          });
        }}
        open={expandedLaneKeys.has(entry.key)}
      >
        <summary>
          {participant
            ? <PersonaAvatar
                persona={persona}
                presence={laneState === 'running' && laneMotionActive
                  ? 'thinking'
                  : laneState === 'waiting' || laneState === 'running'
                    ? 'listening'
                    : laneState === 'completed'
                      ? 'done'
                      : 'warning'}
              />
            : <span className="room-agent-lane__route"><Route size={15} /></span>}
          <span className="room-agent-lane__work">
            <span className="room-agent-lane__identity">
              <strong>{participant?.displayName ?? '正在选择伙伴'}</strong>
              <small>{statusLabel}</small>
            </span>
            <strong className="room-agent-lane__task">{laneHeadline}</strong>
            <small className="room-agent-lane__progress">{laneDetail}</small>
            <RoomLaneProgress
              active={laneStillActive && !laneAction && laneFreshness.state !== 'disconnected'}
              activities={lane.activities}
            />
          </span>
          <RoomLaneTiming
            freshness={laneFreshness}
            nowMs={nowMs}
            startedAtMs={turn.createdAtMs}
            endedAtMs={laneStillActive && !laneAction ? undefined : turn.updatedAtMs}
          />
        </summary>
        {visibleMessages.length ? <div className="room-agent-lane__posts">
          {visibleMessages.map((message) => <Fragment key={message.id}>
            <RoomLanePost
              activeWait={
                message.postKind === 'wait'
                && !rootTerminal
                && (!message.question || pendingQuestion?.postId === message.id)
              }
              evidence={roomResponseEvidenceForPost(message, responseUsageActivities)}
              message={message}
              onAnswerQuestion={onAnswerQuestion}
              participants={room?.participants ?? []}
              pendingQuestion={pendingQuestion?.postId === message.id ? pendingQuestion : undefined}
              showEvidence={Boolean(roomTerminalPostLabels[message.postKind ?? ''])}
              streamingMotion={laneFreshness.state === 'fresh'}
              turnStartedAtMs={turn.createdAtMs}
            />
          </Fragment>)}
        </div> : null}
        {includeDetails && lane.activities.length ? <ActivityLog
          activities={lane.activities}
          active={laneStillActive && !laneAction}
          motionActive={laneMotionActive}
          participantName={participant?.displayName}
          attention={laneState === 'failed' || laneState === 'aborted'}
        /> : null}
        {includeDetails && !lane.activities.length && laneStillActive && !messages.length ? <div className="room-agent-lane__waiting">
          {laneMotionActive ? <LoaderCircle size={14} /> : <Clock3 size={14} />}
          <span>{laneMotionActive
            ? participant
              ? `${participant.displayName} 已接手，正在准备`
              : '消息已经送达，正在请合适的伙伴回应'
            : laneFreshness.detail}
          </span>
        </div> : null}
        {includeDetails && !terminalIssue && (laneFailed || laneAborted) && !visibleMessages.length ? (
          <p className="room-agent-lane__failure">
            {laneFailed
              ? publicFailure
              : '这位伙伴的任务已经停止。'}
          </p>
        ) : null}
      </details></Fragment>;
    })}
    {rootActive && onAbortTurn ? <div className="room-turn__root-control" role="status">
      <span><CircleStop size={14} /><small>{rootStopping ? '正在停止本轮的伙伴、工具和后续任务' : '会一起停止本轮的所有伙伴、工具和后续任务'}</small></span>
      <Button
        variant="danger"
        size="small"
        leadingIcon={rootStopping ? <LoaderCircle className="ui-spin" size={14} /> : <CircleStop size={14} />}
        disabled={rootStopping}
        onClick={() => onAbortTurn(rootId)}
      >{rootStopping ? '正在停止' : '停止本轮任务'}</Button>
    </div> : null}
    {outcome ? <section
      className="room-turn__terminal"
      data-arriving={outcomeArriving || undefined}
      data-state={outcome.state}
      role="status"
    >
      <span className="room-turn__terminal-icon" aria-hidden="true">
        {outcome.state === 'completed'
          ? <CheckCircle2 size={16} />
          : outcome.state === 'blocked'
            ? <CircleAlert size={16} />
            : outcome.state === 'failed'
              ? <X size={16} />
              : <CircleStop size={16} />}
      </span>
      <span>
        <small className="room-turn__terminal-label">运行结论</small>
        <strong>{outcome.title}</strong>
        <small>{outcome.detail}</small>
      </span>
      {retryMessage && onRetryTurn ? <Button
        variant="secondary"
        size="small"
        leadingIcon={retryingTurn
          ? <LoaderCircle className="ui-spin" size={14} />
          : <RotateCcw size={14} />}
        disabled={retryingTurn}
        onClick={() => onRetryTurn(retryMessage)}
      >{retryingTurn ? '正在重试' : '再试一次'}</Button> : null}
    </section> : null}
    {pendingAction ? <SessionActionLink action={pendingAction} /> : null}
  </article>;
}

function RoomUserPost({
  message,
  roomId,
}: {
  message: RoomMessageProjection;
  roomId: string;
}) {
  const visibleBlocks = roomVisibleBlocks(message.message?.blocks ?? []);
  return <div
    className="room-user-message"
    data-room-message-id={message.id}
    data-status={message.status}
  >
    {visibleBlocks.length ? (
      <AgentBlocks
        blocks={visibleBlocks}
        sessionId={message.message?.sessionId || message.sourceSessionId || `room:${roomId}`}
      />
    ) : <MarkdownBody text={message.text} />}
    {message.status === 'queued' ? <small>正在发送</small> : null}
  </div>;
}

interface RoomSessionAction {
  sessionId: string;
  kind: 'review' | 'select' | 'clarify';
}

function SessionActionLink({ action }: { action: RoomSessionAction }) {
  const copy = action.kind === 'review'
    ? {
        title: '这轮协作正在等待审阅',
        detail: '伙伴已暂停；打开对应对话审阅计划或请求后会自动继续。',
        action: '立即审阅',
      }
    : action.kind === 'select'
      ? {
          title: '这轮协作正在等待选择',
          detail: '打开对应伙伴对话，选择一个明确选项后继续。',
          action: '立即选择',
        }
      : {
          title: '这轮协作正在等待补充信息',
          detail: '打开对应伙伴对话回答问题后继续。',
          action: '立即回答',
        };
  return <a
    className="room-review-link room-review-link--turn"
    href={agentSessionHref(action.sessionId)}
  >
    <span><strong>{copy.title}</strong><small>{copy.detail}</small></span>
    <span>{copy.action} <ExternalLink size={13} /></span>
  </a>;
}

function roomLaneWorkSummary(
  activities: RoomActivityProjection[],
  participantName = '协作成员',
  laneState: string,
): { title: string; detail: string } {
  const informativeActivities = roomVisibleIncrementalActivities(activities);
  const digest = roomActivityDigest(informativeActivities);
  const attentionRequired = laneState === 'failed' || laneState === 'aborted';
  const focus = [...informativeActivities].reverse().find((candidate) => {
    const status = roomActivityDisplayStatus(candidate);
    return attentionRequired
      ? ['failed', 'aborted'].includes(status)
      : !['failed', 'aborted'].includes(status);
  });
  if (focus) {
    return {
      title: describeRoomActivity(focus, participantName).title,
      detail: `${digest.detail} · ${digest.title}`,
    };
  }
  const title = laneState === 'completed'
    ? `${participantName} 已完成任务`
    : laneState === 'failed'
      ? `${participantName} 的任务未完成`
      : laneState === 'aborted'
        ? `${participantName} 的任务已停止`
        : laneState === 'waiting'
          ? `${participantName} 正在等待后续`
          : `${participantName} 正在准备任务`;
  return { title, detail: '尚未收到公开工作进度' };
}

function ActivityLog({
  activities,
  active,
  motionActive,
  attention,
  participantName,
}: {
  activities: RoomActivityProjection[];
  active: boolean;
  motionActive: boolean;
  attention: boolean;
  participantName?: string;
}) {
  const [arrivingActivityIds, setArrivingActivityIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const previousActivityIds = useRef<ReadonlySet<string> | null>(null);
  const publicActivities = roomVisibleIncrementalActivities(activities);
  const latestReasoning = [...publicActivities].reverse().find((activity) => (
    textValue(activity.payload.sourceEventType) === 'reasoning_summary'
  ));
  const chronologicalActivities = publicActivities.filter((activity) => (
    textValue(activity.payload.sourceEventType) !== 'reasoning_summary'
  ));
  const activityIdentityKey = publicActivities.map((activity) => activity.id).join('\u001f');
  useEffect(() => {
    const nextIds = new Set(publicActivities.map((activity) => activity.id));
    const previousIds = previousActivityIds.current;
    previousActivityIds.current = nextIds;
    if (!previousIds) return;
    const arrivingIds = new Set([...nextIds].filter((activityId) => !previousIds.has(activityId)));
    if (!arrivingIds.size) return;
    setArrivingActivityIds(arrivingIds);
    const timer = window.setTimeout(() => setArrivingActivityIds(new Set()), 220);
    return () => window.clearTimeout(timer);
  }, [activityIdentityKey]);
  if (!publicActivities.length) return null;
  return <div
    className="room-agent-lane__activity"
    data-motion={motionActive ? 'fresh' : 'paused'}
    data-state={attention ? 'attention' : active ? 'running' : 'settled'}
  >
    <div
      aria-label={`工作进展与运行记录：${participantName ?? '协作成员'}`}
      aria-live={motionActive ? 'polite' : 'off'}
      className="room-agent-lane__activity-feed"
      role="log"
    >{latestReasoning ? <RoomReasoningActivity
      activity={latestReasoning}
      arriving={motionActive && arrivingActivityIds.has(latestReasoning.id)}
      pinned
    /> : null}
    {chronologicalActivities.map((activity, activityIndex) => {
      const displayStatus = roomActivityDisplayStatus(activity);
      const sourceEventType = textValue(activity.payload.sourceEventType);
      const arriving = motionActive && arrivingActivityIds.has(activity.id);
      if (['tool_started', 'tool_progress', 'tool_finished'].includes(sourceEventType)) {
        const toolName = textValue(activity.payload.toolName);
        const recovered = displayStatus === 'failed' && chronologicalActivities
          .slice(activityIndex + 1)
          .some((candidate) => (
            textValue(candidate.payload.sourceEventType) === 'tool_finished'
            && textValue(candidate.payload.toolName) === toolName
            && roomActivityDisplayStatus(candidate) === 'completed'
          ));
        return <RoomToolActivity
          activity={activity}
          arriving={arriving}
          key={activity.id}
          recovered={recovered}
        />;
      }
      const description = describeRoomActivity(activity, participantName);
      const waitDetails = displayStatus === 'waiting'
        ? roomActivityWaitDetails(activity, description.detail)
        : null;
      return <div
        className="room-agent-activity"
        data-arriving={arriving || undefined}
        data-state={displayStatus}
        key={activity.id}
      >
        {displayStatus === 'running'
          ? <LoaderCircle size={14} />
          : displayStatus === 'failed'
            ? <X size={14} />
            : displayStatus === 'waiting'
              ? <Clock3 size={14} />
              : displayStatus === 'aborted'
                ? <CircleStop size={14} />
                : <CheckCircle2 size={14} />}
        <span>
          <strong>{description.title}</strong>
          <small><span className="room-activity-provenance">{roomActivityProvenanceLabel(activity)}</span> · {description.detail} · <RoomActivityTimestamp activity={activity} /></small>
          {waitDetails ? <small className="room-agent-activity__wait-details">
            <b>等待原因：</b>{waitDetails.reason}<br />
            <b>恢复条件：</b>{waitDetails.recovery}
          </small> : null}
        </span>
      </div>;
    })}</div>
  </div>;
}

function RoomReasoningActivity({
  activity,
  arriving,
  pinned,
}: {
  activity: RoomActivityProjection;
  arriving: boolean;
  pinned?: boolean;
}) {
  const displayStatus = roomActivityDisplayStatus(activity);
  const rawReasoningItems = Array.isArray(activity.payload.items)
    ? activity.payload.items
        .filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
        .slice(0, 12)
    : [];
  const summary = publicReasoningSummary(
    publicActivitySummary(activity.summary, activity.kind)
      || rawReasoningItems.at(-1)
      || '',
    displayStatus,
  );
  if (!summary) return null;
  const reasoningItems = [...new Set(rawReasoningItems
    .map((item) => publicReasoningSummary(item, displayStatus))
    .filter((item) => Boolean(item) && item !== summary))];
  return <div
    className="room-agent-activity room-agent-activity--reasoning"
    data-arriving={arriving || undefined}
    data-pinned={pinned || undefined}
    data-state={displayStatus}
  >
    <Sparkles aria-hidden="true" size={14} />
    <span>
      <small className="room-agent-activity__reasoning-label">
        {pinned ? '最新思考摘要' : '工作摘要'} · <RoomActivityTimestamp activity={activity} />
      </small>
      <strong>{summary}</strong>
      {reasoningItems.length ? <details className="room-agent-activity__reasoning-details">
        <summary>查看工作要点</summary>
        <ol>
          {reasoningItems.map((item, index) => (
            <li key={`${activity.id}:reasoning:${index}`}>{item}</li>
          ))}
        </ol>
      </details> : null}
    </span>
  </div>;
}

function roomVisibleIncrementalActivities(
  activities: RoomActivityProjection[],
): RoomActivityProjection[] {
  const seen = new Set<string>();
  const visible: RoomActivityProjection[] = [];
  for (let index = activities.length - 1; index >= 0; index -= 1) {
    const activity = activities[index];
    if (!activity || !roomActivityHasPublicInformation(activity)) continue;
    const sourceEventType = textValue(activity.payload.sourceEventType);
    if (sourceEventType === 'reasoning_summary') {
      if (textValue(activity.payload.source) !== 'provider_reasoning_summary') continue;
      const rawItems = Array.isArray(activity.payload.items)
        ? activity.payload.items.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
        : [];
      const summary = publicReasoningSummary(
        publicActivitySummary(activity.summary, activity.kind) || rawItems.at(-1) || '',
        roomActivityDisplayStatus(activity),
      );
      if (!summary) continue;
    } else if (
      ['current_progress', 'progress'].includes(sourceEventType)
      || textValue(activity.payload.activityKind) === 'work'
    ) {
      const summary = publicActivitySummary(activity.summary, activity.kind);
      if (!summary) continue;
    }
    const identity = activity.id;
    if (seen.has(identity)) continue;
    seen.add(identity);
    visible.push(activity);
  }
  return visible.reverse();
}

const roomActivityTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

function RoomActivityTimestamp({ activity }: { activity: RoomActivityProjection }) {
  const atMs = activity.updatedAtMs ?? activity.createdAtMs;
  return <time dateTime={new Date(atMs).toISOString()}>
    {roomActivityTimeFormatter.format(new Date(atMs))}
  </time>;
}

function roomActivityWaitDetails(
  activity: RoomActivityProjection,
  publicDetail: string,
): { reason: string; recovery: string } {
  const payload = activity.payload;
  const reason = textValue(
    payload.reason
    || payload.blocker
    || payload.message
    || payload.prompt
    || activity.summary
    || publicDetail,
  ) || '伙伴还没有公开更具体的等待原因';
  const retryAtMs = typeof payload.retryAtMs === 'number' && Number.isFinite(payload.retryAtMs)
    ? payload.retryAtMs
    : 0;
  const retryDelayMs = typeof payload.retryDelayMs === 'number' && Number.isFinite(payload.retryDelayMs)
    ? payload.retryDelayMs
    : 0;
  if (retryAtMs > 0) {
    return {
      reason,
      recovery: `到 ${roomActivityTimeFormatter.format(new Date(retryAtMs))} 自动重试`,
    };
  }
  if (retryDelayMs > 0) {
    return { reason, recovery: `${formatElapsed(retryDelayMs)} 后自动重试` };
  }
  if (roomActivityNeedsSessionAction(activity)) {
    return { reason, recovery: '完成上面的确认或补充后继续' };
  }
  return { reason, recovery: '恢复条件尚未公开' };
}

type RoomResponseUsage = NonNullable<
  NonNullable<RoomMessageProjection['message']>['usage']
>;

function RoomLanePost({
  message,
  evidence,
  showEvidence,
  participants,
  turnStartedAtMs,
  activeWait,
  pendingQuestion,
  onAnswerQuestion,
  streamingMotion,
}: {
  message: RoomMessageProjection;
  evidence?: RoomResponseEvidence;
  showEvidence: boolean;
  participants: readonly TimelineParticipant[];
  turnStartedAtMs: number;
  activeWait: boolean;
  pendingQuestion?: PendingRoomQuestion;
  streamingMotion: boolean;
  onAnswerQuestion?: (
    question: PendingRoomQuestion,
    value: string,
  ) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const visibleBlocks = roomVisibleBlocks(message.message?.blocks ?? []);
  const reportLabel = roomPostReportLabel(message);
  const collapsible = roomPostShouldCollapse(message, visibleBlocks);
  const questionIsAuthoritative = Boolean(
    message.question?.status === 'pending'
    && pendingQuestion
    && message.id === pendingQuestion.postId
    && message.rootId === pendingQuestion.rootId
  );
  const content = message.question
    ? <div className="room-question-post">
        {message.text.trim() && message.text.trim() !== message.question.prompt.trim()
          ? <MarkdownBody text={message.text} />
          : null}
        <RoomQuestionDialog
          active={questionIsAuthoritative}
          question={message.question}
          onSubmit={questionIsAuthoritative && pendingQuestion && onAnswerQuestion
            ? (value) => onAnswerQuestion(pendingQuestion, value)
            : undefined}
        />
      </div>
    : visibleBlocks.length
      ? <AgentBlocks blocks={visibleBlocks} sessionId={message.message?.sessionId ?? message.sourceSessionId} />
      : message.text
        ? <MarkdownBody text={message.text} />
        : null;
  return <div
    className="room-agent-lane__post"
    data-room-message-id={message.id}
    data-projection={message.projectionKind ?? 'post'}
    data-status={message.status}
    data-kind={reportLabel ? message.postKind ?? 'progress' : undefined}
  >
    {message.projectionKind === 'execution'
      ? <small className="room-agent-lane__projection-label">实时进展 · 完成后会在这里留下公开结果</small>
      : null}
    {collapsible ? (
      <details className="room-agent-lane__report" open={open}>
        <summary
          aria-expanded={open}
          onClick={(event) => toggleDisclosurePreservingAnchor(event, setOpen)}
          onKeyDown={(event) => toggleDisclosureOnKeyPreservingAnchor(event, setOpen)}
        >
          <span>
            <strong>{reportLabel}</strong>
            <small>{roomReportPreview(message.text)}</small>
          </span>
          <span>{open ? '收起' : '查看完整汇报'}<ChevronRight aria-hidden="true" size={14} /></span>
        </summary>
        {open ? <div className="room-agent-lane__report-body">{content}</div> : null}
      </details>
    ) : (
      <>
        {reportLabel ? <small className="room-agent-lane__post-kind">{reportLabel}</small> : null}
        {content}
      </>
    )}
    <RoomPostLifecycle
      activeWait={activeWait}
      message={message}
      participants={participants}
      turnStartedAtMs={turnStartedAtMs}
    />
    {showEvidence && message.status !== 'streaming'
      ? <RoomResponseEvidenceFooter evidence={evidence} />
      : null}
    {message.status === 'streaming' && streamingMotion
      ? <span className="room-stream-caret" aria-label="仍在生成" />
      : message.status === 'streaming'
        ? <small className="room-agent-lane__stream-stale">这条实时内容暂时没有新的权威更新</small>
        : null}
  </div>;
}

function RoomPostLifecycle({
  message,
  participants,
  turnStartedAtMs,
  activeWait,
}: {
  message: RoomMessageProjection;
  participants: readonly TimelineParticipant[];
  turnStartedAtMs: number;
  activeWait: boolean;
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!activeWait) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [activeWait]);
  if (!['handoff', 'wait', 'blocked'].includes(message.postKind ?? '')) return null;
  const targetNames = (message.mentionedParticipantIds ?? [])
    .map((participantId) => (
      participants.find((participant) => participant.id === participantId)?.displayName
    ))
    .filter((value): value is string => Boolean(value));
  const target = targetNames.join('、');
  const title = message.postKind === 'handoff'
    ? target
      ? `已交接给 ${target}`
      : '已进入下一段协作'
    : message.postKind === 'wait'
      ? target
        ? `正在等待 ${target}`
        : message.question?.status === 'answered'
          ? '已收到你的回复'
          : message.question?.status === 'superseded'
            ? '等待问题已更新'
            : message.question
              ? '正在等待你的回复'
              : '正在等待继续条件'
      : '已记录阻塞';
  const elapsedMs = activeWait
    ? Math.max(0, nowMs - message.createdAtMs)
    : Math.max(0, message.createdAtMs - turnStartedAtMs);
  const timing = activeWait
    ? `已等待 ${formatElapsed(elapsedMs)}`
    : `本轮开始 ${formatElapsed(elapsedMs)} 后记录`;
  const waitReason = message.question?.prompt.trim()
    || message.text.trim()
    || (message.postKind === 'blocked'
      ? '伙伴没有公开更具体的阻塞原因'
      : '伙伴没有公开更具体的等待原因');
  const recoveryCondition = !activeWait && message.postKind === 'wait'
    ? message.question?.status === 'answered'
      ? '你的回答已收到，这段等待已经结束'
      : '这段等待已经结束'
    : message.question?.status === 'pending'
      ? '收到你的回答后继续'
      : message.question?.status === 'answered'
        ? '你的回答已收到，伙伴正在恢复工作'
        : message.question?.status === 'superseded'
          ? '请回应当前显示的最新问题'
          : target
            ? `收到 ${target} 的公开结果后继续`
            : message.postKind === 'blocked'
              ? '处理上面的阻塞原因后才能继续'
              : '恢复条件尚未公开';
  return <div className="room-agent-lane__transition" data-kind={message.postKind}>
    {message.postKind === 'handoff'
      ? <Route aria-hidden="true" size={14} />
      : message.postKind === 'blocked'
        ? <CircleAlert aria-hidden="true" size={14} />
        : <Clock3 aria-hidden="true" size={14} />}
    <span>
      <strong>{title}</strong>
      <time dateTime={new Date(message.createdAtMs).toISOString()}>{timing}</time>
      {message.postKind !== 'handoff' ? <small className="room-agent-lane__wait-details">
        <b>等待原因：</b>{waitReason}<br />
        <b>恢复条件：</b>{recoveryCondition}
      </small> : null}
    </span>
  </div>;
}

interface RoomResponseEvidence {
  usage?: RoomResponseUsage;
  usageReported: boolean;
  cacheUsageReported: boolean;
  provider: string;
  model: string;
  runtimeTurnId: string;
  sourceSessionId: string;
}

function roomResponseEvidenceForPost(
  message: RoomMessageProjection,
  activities: RoomActivityProjection[],
): RoomResponseEvidence | undefined {
  let usage: RoomResponseUsage | undefined;
  let usageReported = false;
  let cacheUsageReported = false;
  let provider = '';
  let model = '';
  let runtimeTurnId = '';
  let sourceSessionId = message.sourceSessionId;
  const messageDispatchId = textValue(message.dispatchId);
  for (let index = activities.length - 1; index >= 0; index -= 1) {
    const activity = activities[index];
    if (!activity) continue;
    const responsePostId = textValue(activity.payload.responsePostId);
    if (
      textValue(activity.payload.sourceEventType) !== 'message_completed'
      || !messageDispatchId
      || textValue(activity.payload.dispatchId) !== messageDispatchId
      || responsePostId !== message.id
    ) continue;
    usageReported = activity.payload.usageReported === true;
    cacheUsageReported = (
      usageReported
      && activity.payload.cacheUsageReported === true
    );
    usage = usageReported
      ? normalizeRoomResponseUsage(activity.payload.usage)
      : undefined;
    provider = textValue(activity.payload.provider);
    model = textValue(activity.payload.model);
    runtimeTurnId = textValue(activity.payload.runtimeTurnId);
    sourceSessionId = activity.sourceSessionId || sourceSessionId;
    break;
  }
  if (!usage && !provider && !model && !runtimeTurnId) return undefined;
  return {
    usage,
    usageReported,
    cacheUsageReported,
    provider,
    model,
    runtimeTurnId,
    sourceSessionId,
  };
}

function normalizeRoomResponseUsage(value: unknown): RoomResponseUsage | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const source = value as Record<string, unknown>;
  const input = source.input;
  const output = source.output;
  const cacheRead = source.cacheRead;
  const cacheWrite = source.cacheWrite;
  const totalTokens = source.totalTokens;
  if (![input, output, cacheRead, cacheWrite, totalTokens].every((field) => (
    typeof field === 'number' && Number.isFinite(field) && field >= 0
  ))) return undefined;
  return {
    input: Math.floor(input as number),
    output: Math.floor(output as number),
    cacheRead: Math.floor(cacheRead as number),
    cacheWrite: Math.floor(cacheWrite as number),
    totalTokens: Math.floor(totalTokens as number),
  };
}

function RoomResponseEvidenceFooter({
  evidence,
}: {
  evidence?: RoomResponseEvidence;
}) {
  const modelLabel = roomResponseModelLabel(evidence?.provider, evidence?.model);
  const contextHref = evidence?.sourceSessionId && evidence.runtimeTurnId
    ? `#/context-debug?sessionId=${encodeURIComponent(evidence.sourceSessionId)}&turnId=${encodeURIComponent(evidence.runtimeTurnId)}`
    : '';
  return <footer aria-label="回复运行记录" className="room-response-evidence">
    <small className="room-response-evidence__source">运行记录</small>
    <small
      className="room-response-model"
      data-state={evidence?.provider || evidence?.model ? 'reported' : 'unavailable'}
      title={evidence?.provider || evidence?.model
        ? `provider=${evidence.provider || 'unreported'}, model=${evidence.model || 'unreported'}`
        : undefined}
    >
      {modelLabel}
    </small>
    <RoomResponseUsageFooter
      cacheUsageReported={evidence?.cacheUsageReported === true}
      usage={evidence?.usage}
    />
    {contextHref ? <a href={contextHref}>
      <Braces aria-hidden="true" size={12} />
      查看本轮上下文
    </a> : null}
  </footer>;
}

function roomResponseModelLabel(provider = '', model = ''): string {
  if (provider && model) return `${provider} · ${model}`;
  if (model) return `Provider 未上报 · ${model}`;
  if (provider) return `${provider} · 模型未上报`;
  return '模型 / Provider 未上报';
}

function RoomResponseUsageFooter({
  usage,
  cacheUsageReported,
}: {
  usage?: RoomResponseUsage;
  cacheUsageReported: boolean;
}) {
  if (!usage) {
    return <small className="room-response-usage" data-state="unavailable">
      本条回复未上报 Token / 缓存用量
    </small>;
  }
  const cacheLabel = cacheUsageReported
    ? `缓存读取 ${usage.cacheRead} tokens，缓存写入 ${usage.cacheWrite} tokens`
    : '缓存用量未上报';
  return <small
    aria-label={`输入 ${usage.input} tokens，输出 ${usage.output} tokens，${cacheLabel}`}
    className="room-response-usage"
    data-cache-hit={cacheUsageReported ? usage.cacheRead > 0 : undefined}
    data-cache-reported={cacheUsageReported}
    title={cacheUsageReported
      ? `input=${usage.input}, output=${usage.output}, cacheRead=${usage.cacheRead}, cacheWrite=${usage.cacheWrite}`
      : `input=${usage.input}, output=${usage.output}, cache=unreported`}
  >
    <span>输入 {formatTokenCount(usage.input)}</span>
    <span>输出 {formatTokenCount(usage.output)}</span>
    {cacheUsageReported ? <>
      <span>{usage.cacheRead > 0 ? '缓存命中' : '缓存读'} {formatTokenCount(usage.cacheRead)}</span>
      <span>写 {formatTokenCount(usage.cacheWrite)}</span>
    </> : <span>缓存未上报</span>}
  </small>;
}

function formatTokenCount(value: number): string {
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: 0,
  }).format(Math.max(0, value));
}


function roomPostShouldCollapse(
  message: RoomMessageProjection,
  blocks: NonNullable<RoomMessageProjection['message']>['blocks'],
): boolean {
  if (message.projectionKind === 'execution' || message.status === 'streaming') return false;
  if (message.question) return false;
  if (blocks.some((block) => !['text', 'progress', 'status'].includes(block.type))) return false;
  const normalized = message.text.replace(/\s+/g, ' ').trim();
  return normalized.length > 360 || message.text.split('\n').length > 8;
}

function roomReportPreview(value: string): string {
  const normalized = value
    .replace(/```[\s\S]*?```/g, '（含代码或命令结果）')
    .replace(/^\s{0,3}(?:#{1,6}|[-*+]>?)\s+/gm, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
  if (normalized.length <= 180) return normalized;
  const candidate = normalized.slice(0, 181);
  const sentenceEnd = Math.max(candidate.lastIndexOf('。'), candidate.lastIndexOf('；'));
  const end = sentenceEnd >= 90 ? sentenceEnd + 1 : 180;
  return `${normalized.slice(0, end).trimEnd()}…`;
}

type RoomTurnOutcomeState = 'completed' | 'blocked' | 'failed' | 'aborted';

interface RoomTurnOutcome {
  state: RoomTurnOutcomeState;
  title: string;
  detail: string;
}

function roomTurnOutcome(
  projection: RoomProjectionState,
  lanes: RoomExecutionLane[],
  turn: RoomTurnProjection,
  publicFailure: string,
): RoomTurnOutcome | null {
  if (
    turn.status !== 'completed'
    && turn.status !== 'failed'
    && turn.status !== 'aborted'
  ) return null;
  let publicReportCount = 0;
  let blockedLaneCount = 0;
  for (const lane of lanes) {
    const visibleMessages = roomVisibleConversationMessages(
      lane.messageIds
        .map((id) => projection.messagesById[id])
        .filter(Boolean),
    );
    const terminalPosts = visibleMessages.filter((message) => (
      message.projectionKind !== 'execution'
      && message.postKind !== 'alignment'
      && Boolean(roomTerminalPostLabels[message.postKind ?? ''])
    ));
    publicReportCount += terminalPosts.length;
    if (terminalPosts.some((message) => message.postKind === 'blocked')) {
      blockedLaneCount += 1;
    }
  }
  const state: RoomTurnOutcomeState = turn.status === 'aborted'
    ? 'aborted'
    : blockedLaneCount > 0
      ? 'blocked'
      : turn.status;
  const reportDetail = publicReportCount > 0
    ? `已保留 ${publicReportCount} 条伙伴公开汇报，可在上方查看。`
    : state === 'completed'
      ? '本轮没有产生伙伴公开汇报。'
      : '';
  if (state === 'completed') {
    const workDetail = lanes.length > 0 ? `${lanes.length} 项分工已经收束。` : '';
    return {
      state,
      title: '这轮协作已完成',
      detail: `${workDetail}${reportDetail}`,
    };
  }
  if (state === 'blocked') {
    return {
      state,
      title: '这轮协作受阻',
      detail: `${blockedLaneCount} 项分工报告阻塞。${reportDetail || '可调整原任务后再试。'}`,
    };
  }
  if (state === 'failed') {
    return {
      state,
      title: '这轮协作没有完成',
      detail: `${publicFailure}${reportDetail ? ` ${reportDetail}` : ''}`,
    };
  }
  return {
    state,
    title: '这轮协作已停止',
    detail: `未完成的伙伴、工具和后续任务不会继续。${reportDetail}`,
  };
}

function usePrevious<T>(value: T): T | undefined {
  const current = useRef<T | undefined>(undefined);
  useEffect(() => {
    current.current = value;
  }, [value]);
  return current.current;
}

function roomActivityProvenanceLabel(activity: RoomActivityProjection): '进度更新' | '伙伴沟通' | '运行记录' {
  const sourceEventType = textValue(activity.payload.sourceEventType);
  const activityKind = textValue(activity.payload.activityKind);
  if (activityKind === 'intercom') return '伙伴沟通';
  if (['current_progress', 'progress'].includes(sourceEventType) || activityKind === 'work') {
    return '进度更新';
  }
  return '运行记录';
}

function roomActivityDigest(
  activities: RoomActivityProjection[],
): { title: string; detail: string } {
  const labels = activities.flatMap((activity) => {
    const sourceEventType = textValue(activity.payload.sourceEventType);
    if (sourceEventType.startsWith('tool_')) {
      const toolId = textValue(activity.payload.toolName);
      return [roomPublicToolName(toolId, textValue(activity.payload.displayName))];
    }
    if (sourceEventType === 'reasoning_summary') return ['工作摘要'];
    if (['current_progress', 'progress'].includes(sourceEventType)) return ['任务进度'];
    if (activity.kind === 'route_decision') return ['任务分派'];
    if (textValue(activity.payload.activityKind) === 'intercom') return ['伙伴沟通'];
    if (textValue(activity.payload.approvalId)) return ['安全审批'];
    if (activity.kind === 'participant_status') return ['状态同步'];
    return [];
  });
  const uniqueLabels = [...new Set(labels)];
  const title = uniqueLabels.length
    ? `${uniqueLabels.slice(0, 3).join('、')}${uniqueLabels.length > 3 ? '等' : ''}`
    : '协作过程';
  const counts = activities.reduce((result, activity) => {
    const status = roomActivityDisplayStatus(activity);
    result[status] += 1;
    return result;
  }, { running: 0, waiting: 0, failed: 0, aborted: 0, completed: 0 });
  const states = [
    counts.running ? `${counts.running} 个进行中` : '',
    counts.waiting ? `${counts.waiting} 个等待处理` : '',
    counts.failed ? `${counts.failed} 个未完成` : '',
    counts.aborted ? `${counts.aborted} 个已停止` : '',
    !counts.running && !counts.waiting && !counts.failed && !counts.aborted
      ? '所有步骤已返回'
      : counts.completed
        ? `${counts.completed} 个步骤已返回`
        : '',
  ].filter(Boolean);
  return {
    title,
    detail: `${activities.length} 个步骤 · ${states.join(' · ')}`,
  };
}


function RoomToolActivity({
  activity,
  arriving,
  recovered,
}: {
  activity: RoomActivityProjection;
  arriving: boolean;
  recovered?: boolean;
}) {
  const payload = activity.payload;
  const approvalId = textValue(payload.approvalId);
  const [open, setOpen] = useState(Boolean(
    approvalId && ['running', 'waiting'].includes(activity.status),
  ));
  useEffect(() => {
    if (approvalId) setOpen(true);
  }, [approvalId]);
  const sourceEventType = textValue(payload.sourceEventType);
  const toolLabel = roomPublicToolName(
    textValue(payload.toolName),
    textValue(payload.displayName),
  );
  const safeResult = payload.result;
  const publicResult = safeResult && typeof safeResult === 'object' && !Array.isArray(safeResult)
    ? safeResult as Record<string, unknown>
    : {};
  const error = textValue(payload.error);
  const projectedArguments = payload.arguments && typeof payload.arguments === 'object' && !Array.isArray(payload.arguments)
    ? payload.arguments as Record<string, unknown>
    : {};
  const view = publicToolResultView({
    kind: sourceEventType || activity.kind,
    status: activity.status,
    payload: {
      ...payload,
      displayName: toolLabel,
      args: projectedArguments,
      publicResult: error && !publicResult.error
        ? { ...publicResult, error }
        : publicResult,
    },
  });
  const requestFields = roomToolDetailFields(projectedArguments);
  const resultFields = view.output ? [] : roomToolDetailFields(safeResult);
  const detailView = roomPublicToolResultView({
    ...view,
    request: view.request.length ? view.request : requestFields,
    fields: [
      ...view.fields,
      ...resultFields.filter((field) => (
        !view.fields.some((existingField) => existingField.id === field.id)
      )),
    ],
  });
  const approvalDescription = approvalId ? describeRoomActivity(activity) : null;
  return (
    <details
      className="room-agent-activity room-agent-activity--tool"
      data-arriving={arriving || undefined}
      data-recovered={recovered || undefined}
      data-state={activity.status}
      open={open}
    >
      <summary
        aria-expanded={open}
        onClick={(event) => toggleDisclosurePreservingAnchor(event, setOpen)}
        onKeyDown={(event) => toggleDisclosureOnKeyPreservingAnchor(event, setOpen)}
      >
        <span className="room-agent-activity__state" aria-hidden="true">
          {activity.status === 'running'
            ? <LoaderCircle size={14} />
            : activity.status === 'failed'
              ? <X size={14} />
              : activity.status === 'waiting'
                ? <Clock3 size={14} />
                : activity.status === 'aborted'
                  ? <CircleStop size={14} />
                  : <CheckCircle2 size={14} />}
        </span>
        <span>
          <strong>{activity.status === 'failed'
            ? recovered
              ? `${detailView.toolLabel}这次没有完成`
              : `${detailView.toolLabel}执行失败`
            : activity.status === 'aborted'
              ? `${detailView.toolLabel}已停止`
              : detailView.summary}</strong>
          <small><span className="room-activity-provenance">运行记录</span> · {detailView.toolLabel} · {roomToolStatusLabel(activity.status)}{recovered ? ` · 后续${detailView.toolLabel.replace(/文件$/, '')}已经成功` : ''}{roomToolProgressCount(payload) > 1 ? ` · ${roomToolProgressCount(payload)} 次更新` : ''} · <RoomActivityTimestamp activity={activity} /></small>
        </span>
        <ChevronRight aria-hidden="true" size={14} />
      </summary>
      {open ? (
        <div className="room-agent-activity__details">
          {!detailView.request.length ? (
            <p className="room-agent-activity__unavailable">这个步骤没有需要展示的公开参数。</p>
          ) : null}
          {detailView.request.length ? <PublicToolRequest view={detailView} /> : null}
          {detailView.output ? <PublicToolOutput view={detailView} /> : null}
          <PublicToolFields view={detailView} />
          {detailView.error ? <PublicToolError reason={detailView.error} /> : null}
          {approvalDescription ? (
            <section className="room-agent-activity__approval" aria-label="Tool 审批状态">
              <ShieldAlert aria-hidden="true" size={14} />
              <span>
                <strong>{approvalDescription.title}</strong>
                <small>{approvalDescription.detail}</small>
              </span>
            </section>
          ) : null}
          {activity.status === 'running' && safeResult === undefined ? (
            <p className="room-agent-activity__unavailable">工具尚未返回结果。</p>
          ) : activity.status === 'aborted' && safeResult === undefined ? (
            <p className="room-agent-activity__unavailable">这个步骤已随本轮任务停止，没有返回公开结果。</p>
          ) : activity.status !== 'running' && safeResult === undefined && !detailView.output && !detailView.fields.length && !detailView.error ? (
            <p className="room-agent-activity__unavailable">这个步骤没有可展示的公开返回内容。</p>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

const roomToolFieldLabels: Record<string, string> = {
  operation: '操作',
  action: '动作',
  intent: '协作意图',
  objective: '任务目标',
  expectedOutput: '预期交付',
  acceptance: '验收条件',
  kind: '消息类型',
  mentions: '提醒伙伴',
  waitingFor: '等待对象',
  blocker: '阻塞原因',
  responsibility: '协作职责',
  content: '公开内容',
  status: '状态',
  state: '状态',
  summary: '摘要',
  unchanged: '变更状态',
  stateRevision: '状态版本',
  evidenceRef: '验证依据',
  accepted: '接收状态',
  enqueued: '入队状态',
  deduplicated: '去重状态',
  targetParticipantRef: '下一位伙伴',
  currentResponsibilityContinues: '当前职责',
  currentResponsibility: '当前职责',
  published: '发布状态',
  postRef: '公开记录',
  settlementStaged: '结算状态',
  terminalForModelTurn: '模型轮次',
  canonicalTool: '规范工具',
  ok: '执行结果',
  created: '创建状态',
  executionPerformed: '实际执行',
  id: '编号',
  ref: '引用',
  revision: '版本',
  displayName: '名称',
};
const roomToolBooleanLabels: Record<string, readonly [string, string]> = {
  unchanged: ['已有变更', '无变更'],
  accepted: ['未接收', '已接收'],
  enqueued: ['未入队', '已入队'],
  deduplicated: ['新记录', '已去重'],
  currentResponsibilityContinues: ['职责已移交', '继续当前职责'],
  ok: ['未成功', '成功'],
  created: ['已有记录', '新记录'],
  executionPerformed: ['未执行', '已执行'],
  published: ['未发布', '已发布'],
  settlementStaged: ['未暂存', '已暂存'],
  terminalForModelTurn: ['模型轮次继续', '模型轮次已结束'],
};

function roomToolDetailFields(value: unknown): Array<{ id: string; label: string; value: string }> {
  if (value === undefined) return [];
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).flatMap(([id, fieldValue]) => {
    if (roomToolFieldLabels[id] === undefined) return [];
    const detail = roomToolFieldValue(id, fieldValue);
    return detail ? [{ id, label: roomToolFieldLabels[id], value: detail }] : [];
  });
}

function roomToolFieldValue(id: string, value: unknown): string {
  if (typeof value === 'boolean') {
    return roomToolBooleanLabels[id]?.[value ? 1 : 0] ?? (value ? '是' : '否');
  }
  if (typeof value === 'string') {
    if (id === 'status' || id === 'state') {
      return ({
        running: '进行中',
        completed: '已完成',
        failed: '失败',
        waiting: '等待中',
        pending: '待处理',
        queued: '排队中',
        ready: '就绪',
        idle: '空闲',
        aborted: '已中止',
        cancelled: '已取消',
        succeeded: '成功',
      } as Record<string, string>)[value] ?? value;
    }
    return value;
  }
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) {
    return value.map((item) => roomToolFieldValue(id, item)).filter(Boolean).join('、');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .flatMap(([nestedId, nestedValue]) => {
        if (roomToolFieldLabels[nestedId] === undefined) return [];
        const detail = roomToolFieldValue(nestedId, nestedValue);
        return detail ? [`${roomToolFieldLabels[nestedId]}：${detail}`] : [];
      })
      .join(' · ');
  }
  return '';
}

function roomToolStatusLabel(status: RoomActivityProjection['status']): string {
  if (status === 'running') return '进行中';
  if (status === 'waiting') return '待确认';
  if (status === 'failed') return '未完成';
  if (status === 'aborted') return '已停止';
  return '已返回';
}

function roomToolProgressCount(payload: Record<string, unknown>): number {
  return Array.isArray(payload.progressHistory) ? payload.progressHistory.length : 0;
}

type RoomLaneFreshnessState = 'fresh' | 'stale' | 'disconnected';

interface RoomLaneFreshness {
  state: RoomLaneFreshnessState;
  updatedAtMs: number;
  detail: string;
}

function roomLaneFreshness(
  lane: RoomExecutionLane,
  projection: RoomProjectionState,
  turn: RoomTurnProjection,
  nowMs: number,
  roomSyncState?: 'recovering' | 'failed' | 'synced',
): RoomLaneFreshness {
  const updateTimes = [
    ...lane.activities.map((activity) => activity.updatedAtMs ?? activity.createdAtMs),
    ...lane.messageIds.flatMap((messageId) => {
      const message = projection.messagesById[messageId];
      return message ? [message.completedAtMs ?? message.createdAtMs] : [];
    }),
  ];
  return roomFallbackFreshness(
    updateTimes.length ? Math.max(...updateTimes) : turn.updatedAtMs,
    nowMs,
    roomSyncState,
  );
}

function roomFallbackFreshness(
  updatedAtMs: number,
  nowMs: number,
  roomSyncState?: 'recovering' | 'failed' | 'synced',
): RoomLaneFreshness {
  if (roomSyncState && roomSyncState !== 'synced') {
    return {
      state: 'disconnected',
      updatedAtMs,
      detail: roomSyncState === 'recovering'
        ? '正在恢复 Room 对话实时更新，状态暂时静止'
        : 'Room 对话实时更新暂时中断，状态可能过期',
    };
  }
  if (Math.max(0, nowMs - updatedAtMs) > roomActiveEventFreshnessMs) {
    return {
      state: 'stale',
      updatedAtMs,
      detail: '正在等待下一条进展',
    };
  }
  return { state: 'fresh', updatedAtMs, detail: '实时进展已同步' };
}

function RoomLaneProgress({
  active,
  activities,
}: {
  active: boolean;
  activities: RoomActivityProjection[];
}) {
  const visible = roomVisibleIncrementalActivities(activities);
  const total = visible.length;
  if (!total && !active) return null;
  const returned = visible.filter((activity) => (
    ['completed', 'failed', 'aborted'].includes(roomActivityDisplayStatus(activity))
  )).length;
  const ratio = total ? returned / total : 0;
  const label = total
    ? `运行记录已返回 ${returned} / ${total}`
    : '伙伴仍在工作';
  return <span
    aria-label={label}
    aria-valuemax={total || undefined}
    aria-valuemin={total ? 0 : undefined}
    aria-valuenow={total ? returned : undefined}
    className="room-agent-lane__meter"
    data-active={active || undefined}
    data-indeterminate={!total || undefined}
    role="progressbar"
  >
    <span aria-hidden="true" className="room-agent-lane__meter-track">
      <i style={{ transform: `scaleX(${ratio})` }} />
    </span>
    <small>{total ? `${returned} / ${total}` : '进行中'}</small>
  </span>;
}

function RoomLaneTiming({
  freshness,
  nowMs,
  startedAtMs,
  endedAtMs,
}: {
  freshness: RoomLaneFreshness;
  nowMs: number;
  startedAtMs: number;
  endedAtMs?: number;
}) {
  const updatedAt = new Date(freshness.updatedAtMs);
  const elapsedSeconds = Math.max(
    0,
    Math.floor((nowMs - freshness.updatedAtMs) / 1_000),
  );
  return <span className="room-agent-lane__timing">
    <span className="room-agent-lane__updated-at">
      最近更新 <time dateTime={updatedAt.toISOString()}>
        {roomActivityTimeFormatter.format(updatedAt)}
      </time>
      <span aria-hidden="true"> · {elapsedSeconds} 秒前</span>
    </span>
    {freshness.state === 'fresh' ? null : <small data-state={freshness.state}>
      {freshness.detail}
    </small>}
    <RoomElapsed
      endedAtMs={endedAtMs}
      nowMs={nowMs}
      startedAtMs={startedAtMs}
    />
  </span>;
}

function RoomElapsed({
  startedAtMs,
  endedAtMs,
  nowMs,
}: {
  startedAtMs: number;
  endedAtMs?: number;
  nowMs: number;
}) {
  const elapsedMs = Math.max(0, (endedAtMs ?? nowMs) - startedAtMs);
  return <time
    className="room-agent-lane__elapsed"
    dateTime={`PT${Math.round(elapsedMs / 1_000)}S`}
  ><Clock3 size={12} />{formatElapsed(elapsedMs)}</time>;
}

function formatElapsed(elapsedMs: number): string {
  const seconds = Math.floor(elapsedMs / 1_000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function roomActivityDisplayStatus(
  activity: RoomActivityProjection,
): RoomActivityProjection['status'] {
  if (['completed', 'failed', 'aborted'].includes(activity.status)) {
    return activity.status;
  }
  const status = textValue(activity.payload.status);
  const approvalDecision = approvalDecisionView(activity.payload);
  const approvalState = textValue(
    activity.payload.resolutionState || activity.payload.state,
  );
  if (
    approvalDecision.automatic
    && !approvalDecision.decision
    && !['approved', 'rejected', 'applied', 'resolved', 'cancelled'].includes(approvalState)
  ) return 'running';
  if (
    activity.kind === 'participant_status'
    && ['room_created', 'room_archived', 'room_restored'].includes(status)
  ) return 'completed';
  if (textValue(activity.payload.activityKind) === 'intercom') {
    const phase = textValue(activity.payload.phase);
    if (phase === 'delivered') return 'completed';
    if (phase === 'failed' || phase === 'stale') return 'failed';
  }
  return activity.status;
}

function describeRoomActivity(
  activity: RoomActivityProjection,
  participantName = '协作成员',
): { title: string; detail: string } {
  const payload = activity.payload;
  const status = textValue(payload.status);
  const sourceEventType = textValue(payload.sourceEventType);
  const toolName = roomPublicToolName(
    textValue(payload.toolName),
    textValue(payload.displayName),
  );
  const approvalDecision = approvalDecisionView(payload);
  if (activity.status === 'aborted') {
    return sourceEventType.startsWith('tool_')
      ? { title: `${toolName} 已停止`, detail: '本轮已经停止，这个步骤不会继续执行' }
      : { title: `${participantName} 的这一步已停止`, detail: '本轮已经停止，不会再等待后续进度' };
  }
  if (textValue(payload.approvalId) && approvalDecision.mode === 'model') {
    const model = roomApprovalModelLabel(approvalDecision.model);
    const arbiter = `独立审批助手（${model}）`;
    const title = approvalDecision.decision === 'approve'
      ? `${arbiter}已批准这次操作`
      : approvalDecision.decision === 'deny'
        ? `${arbiter}已拒绝这次操作`
        : `${arbiter}正在评估这次操作`;
    const outcome = approvalDecision.status === 'failed_closed'
      ? '审批模型未形成可验证裁决，已按拒绝处理；原操作没有执行。'
      : approvalDecision.decision === 'approve'
        ? '已绑定的操作预览可以进入原有权限与沙箱复验。'
        : approvalDecision.decision === 'deny'
          ? '原操作不会执行；伙伴会尝试更安全的替代方案。'
          : '它读取整个协作空间的用户请求、当前任务与结构化审批记录，但不读取任何伙伴的输出或推理；无需人工操作。';
    const rationale = approvalDecision.rationaleSummary
      ? ` 裁决说明：${approvalDecision.rationaleSummary}`
      : '';
    const reasons = approvalDecision.reasonCodes.length
      ? ` 判定依据：${approvalDecision.reasonCodes.map(approvalDecisionReasonLabel).join('、')}。`
      : '';
    const history = approvalDecision.historyEntryCount !== null
      ? ` 已参考 ${approvalDecision.historyEntryCount} 条整个协作空间的审批记录。`
      : '';
    return { title, detail: `${outcome}${rationale}${reasons}${history}` };
  }
  if (textValue(payload.approvalId) && approvalDecision.mode === 'policy') {
    return {
      title: '安全策略已自动处理这次操作',
      detail: '只有已授权范围内的常规受控操作会直接执行；权限、哈希与沙箱边界仍会再次校验。',
    };
  }
  if (sourceEventType === 'tool_started') {
    return {
      title: `${participantName} 正在使用 ${toolName}`,
      detail: publicActivitySummary(activity.summary, activity.kind) || '工具已开始执行',
    };
  }
  if (sourceEventType === 'tool_progress') {
    return {
      title: `${toolName} 正在执行`,
      detail: publicActivitySummary(activity.summary, activity.kind) || '正在等待新的工具进度',
    };
  }
  if (sourceEventType === 'tool_finished') {
    return {
      title: activity.status === 'failed' ? `${toolName} 执行失败` : `${toolName} 已返回`,
      detail: publicActivitySummary(activity.summary, activity.kind)
        || (activity.status === 'failed' ? '工具没有完成' : '工具结果已交给伙伴'),
    };
  }
  if (sourceEventType === 'reasoning_summary') {
    const summary = publicActivitySummary(activity.summary, activity.kind);
    return {
      title: summary || `${participantName} 正在整理下一步`,
      detail: activity.status === 'running' ? '工作摘要仍在更新' : '工作摘要已同步',
    };
  }
  if (['current_progress', 'progress'].includes(sourceEventType)) {
    const summary = publicActivitySummary(activity.summary, activity.kind);
    return {
      title: summary || `${participantName} 正在推进任务`,
      detail: activity.status === 'running' ? '当前工作进度' : '工作进度已同步',
    };
  }
  if (status === 'retry_wait') {
    const attempt = (
      typeof payload.retryAttempt === 'number'
      && Number.isInteger(payload.retryAttempt)
      && payload.retryAttempt > 0
    ) ? payload.retryAttempt : 0;
    const delayMs = (
      typeof payload.retryDelayMs === 'number'
      && Number.isFinite(payload.retryDelayMs)
      && payload.retryDelayMs >= 0
    ) ? payload.retryDelayMs : 0;
    const summary = publicActivitySummary(activity.summary, activity.kind)
      || '系统已安排一次有限重试';
    return {
      title: attempt
        ? `${participantName} 正在等待第 ${attempt} 次尝试`
        : `${participantName} 正在等待重试`,
      detail: delayMs > 0
        ? `${summary} · ${formatElapsed(delayMs)} 后重试`
        : summary,
    };
  }
  if (activity.kind === 'route_decision') {
    const target = textValue(payload.targetDisplayName) || participantName;
    const reason = textValue(payload.reason);
    const detailByReason: Record<string, string> = {
      explicit_invite: '由用户直接邀请发言',
      mention: '根据明确提及开始处理',
      moderator: '协作调度已确定本轮负责角色',
      sequential: '该角色已接续上一步工作',
      descriptor_match: '根据角色标签与消息内容匹配',
      natural_fallback: '当前没有强匹配，由保底角色承接',
      configured_fallback: '由群组配置的保底角色承接',
    };
    return {
      title: `${target} 已接手`,
      detail: detailByReason[reason] ?? '已确定本轮负责角色',
    };
  }
  if (activity.kind === 'participant_status') {
    if (status === 'room_created') return { title: '协作空间已就绪', detail: '参与角色已经加入，可以开始对话' };
    if (status === 'room_archived') return { title: '协作空间已收起', detail: '历史对话已保留' };
    if (status === 'room_restored') return { title: '协作空间已恢复', detail: '参与角色可以继续协作' };
    return {
      title: `${participantName} 状态已更新`,
      detail: activity.status === 'running' ? '正在准备处理任务' : '当前步骤已经同步',
    };
  }
  if (activity.kind === 'turn_failed') {
    return { title: '这轮协作未完成', detail: '可以调整消息后重新发送' };
  }
  if (textValue(payload.activityKind) === 'intercom') {
    const phaseCopy: Record<string, string> = {
      queued: '协作消息正在等待接收',
      delivered: '协作消息已经送达',
      stale: '协作消息已过期',
      failed: '协作消息未能送达',
    };
    return {
      title: `${participantName} 正在与其他伙伴协作`,
      detail: phaseCopy[textValue(payload.phase)] ?? '协作消息状态已更新',
    };
  }
  const summary = publicActivitySummary(activity.summary, activity.kind);
  if (summary) return { title: `${participantName} 更新了进展`, detail: summary };
  if (activity.status === 'failed') return { title: `${participantName} 未完成这一步`, detail: '可以稍后重试' };
  if (activity.status === 'waiting') return { title: `${participantName} 正在等待你的决定`, detail: '打开伙伴对话处理后会继续' };
  if (activity.status === 'running') return { title: `${participantName} 正在处理`, detail: '有新进展时会在这里更新' };
  return { title: `${participantName} 完成了一步`, detail: '协作进度已经同步' };
}

function roomPublicToolName(toolId: string, displayName = ''): string {
  const normalizedId = toolId.trim().toLowerCase();
  if (normalizedId === 'tool_search') return '查找可用工具';
  const normalizedDisplayName = displayName.trim();
  return publicToolName(
    normalizedId,
    normalizedDisplayName && normalizedDisplayName !== normalizedId
      ? normalizedDisplayName
      : '',
  );
}

function roomApprovalModelLabel(model: string): string {
  if (!model || /(?:^|[./_-])luna(?:$|[./_-])/i.test(model)) return 'Luna Max';
  return model.split('/').at(-1)?.slice(0, 80) || '审批模型';
}

function roomInteractionKind(
  activity: RoomActivityProjection,
): RoomSessionAction['kind'] {
  const requestKind = textValue(activity.payload.requestKind);
  if (
    requestKind === 'plan_review'
    || requestKind === 'memory_review'
    || Boolean(textValue(activity.payload.approvalId))
  ) return 'review';
  return textValue(activity.payload.method) === 'select'
    || Array.isArray(activity.payload.options)
    ? 'select'
    : 'clarify';
}

function roomInteractionStatusLabel(activity: RoomActivityProjection): string {
  const kind = roomInteractionKind(activity);
  if (kind === 'review') return '等待审阅';
  if (kind === 'select') return '等待选择';
  return '等待回答';
}

function pendingRoomSessionAction(
  activities: RoomActivityProjection[],
  projection: RoomProjectionState,
  lanes: ReturnType<typeof selectRoomTurnExecution>['lanes'],
  room?: TimelineRoom,
): RoomSessionAction | undefined {
  const activity = [...activities].reverse().find(roomActivityNeedsSessionAction);
  if (activity) {
    const sessionId = activity.sourceSessionId
      || room?.participants.find((item) => item.id === activity.participantId)?.sessionId
      || '';
    if (sessionId) return { sessionId, kind: roomInteractionKind(activity) };
  }
  for (const lane of [...lanes].reverse()) {
    for (const messageId of [...lane.messageIds].reverse()) {
      const message = projection.messagesById[messageId];
      const pendingApproval = message?.message?.blocks.some((block) => (
        block.type === 'approval'
        && approvalNeedsHumanDecision(block.data)
        && !['approved', 'rejected', 'applied'].includes(textValue(block.data.state))
      ));
      if (!pendingApproval) continue;
      const participantSessionId = room?.participants.find(
        (item) => item.id === lane.participantId,
      )?.sessionId;
      const sessionId = message?.sourceSessionId || lane.sourceSessionId || participantSessionId || '';
      if (sessionId) return { sessionId, kind: 'review' };
    }
  }
  return undefined;
}

function roomVisibleBlocks(
  blocks: NonNullable<RoomMessageProjection['message']>['blocks'],
) {
  const visible = blocks.filter((block) => (
    block.type !== 'reasoning_summary'
    && block.type !== 'tool_call'
    && block.type !== 'tool_result'
    && block.visibility !== 'private_session'
  ));
  let retainedStatusIndex = -1;
  for (let index = visible.length - 1; index >= 0; index -= 1) {
    const type = visible[index]?.type;
    if (type === 'progress' || type === 'status') {
      retainedStatusIndex = index;
      break;
    }
  }
  return visible.filter((block, index) => (
    (block.type !== 'progress' && block.type !== 'status')
    || index === retainedStatusIndex
  ));
}

function publicActivitySummary(summary: string, kind: string): string {
  const value = summary.trim();
  if (!value || value === kind) return '';
  if (/\b(?:participant|route|tool|turn)_[a-z_]+\b/i.test(value)) return '';
  if (/control-center-(?:safe-)?v\d/i.test(value)) return '';
  if (value.includes('内部工具步骤')) return '准备工作已经完成';
  return value;
}

function publicReasoningSummary(
  value: string,
  status: RoomActivityProjection['status'],
): string {
  const safe = roomPublicActivityText(value);
  if (!safe) return status === 'running' ? '正在推进当前工作' : '';
  const normalized = safe.toLocaleLowerCase('en-US');
  if (/\b(?:plan|planning|design|designing|coordinate|coordinating|assign|assigning|define|defining|phase|phases|wave|workwave)\b/u.test(normalized)) {
    return '正在整理分工和下一步';
  }
  if (/\b(?:assess|assessing|search|searching|locate|locating|identify|identifying|inspect|inspecting|check|checking|review|reviewing)\b/u.test(normalized)) {
    return '正在检查相关代码和信息';
  }
  if (/\b(?:test|testing|verify|verifying|validate|validating)\b/u.test(normalized)) {
    return '正在验证当前结果';
  }
  if (/\b(?:fix|fixing|implement|implementing|update|updating|edit|editing)\b/u.test(normalized)) {
    return '正在修改并核对结果';
  }
  if (/\b(?:finalize|finalizing|summarize|summarizing|prepare|preparing)\b/u.test(normalized)) {
    return '正在整理本轮结果';
  }
  if (/\b(?:request|requesting|load|loading|read|reading)\b/u.test(normalized)) {
    return '正在读取所需信息';
  }
  if (/\b(?:continue|continuing|resume|resuming|proceed|proceeding)\b/u.test(normalized)) {
    return '正在推进当前工作';
  }
  const latinWords = safe.match(/[A-Za-z][A-Za-z0-9_-]*/g) ?? [];
  if (/\p{Script=Han}/u.test(safe) && latinWords.length <= 1) return safe;
  return status === 'running' ? '正在推进当前工作' : '';
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function agentSessionHref(sessionId: string): string {
  return `#/agent?${new URLSearchParams({ session: sessionId })}`;
}
