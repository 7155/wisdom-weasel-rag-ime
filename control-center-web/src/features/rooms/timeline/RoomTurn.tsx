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
  Wrench,
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
  type RoomActivityProjection,
  type RoomMessageProjection,
  type RoomProjectionState,
  type RoomTurnProjection,
} from '@/contracts/room-reducer';
import type { RoomKernelProjection } from '@/contracts/room-kernel-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
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
  useAutoFollowScroll,
} from '@/features/agent/timeline/disclosure-anchor';
import { publicToolResultView } from '@/features/agent/timeline/public-tool-result';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { publicToolName } from '@/features/agent/tool-presentation';
import {
  roomActivityNeedsSessionAction,
  selectRoomTurnExecution,
  type RoomExecutionLane,
} from '../runtime/room-execution-lanes';
import {
  roomTaskWorkspaceLifecycleView,
  RoomTaskSubagentRuns,
  type RoomTaskSubagentRun,
} from '../kernel/RoomTaskFlowGraph';
import { RoomTaskUpdatedAt, useRoomTaskUpdateClock } from '../kernel/RoomTaskUpdatedAt';
import type { PendingRoomQuestion } from '../room-question';
import { RoomQuestionDialog } from '../RoomQuestionDialog';
import {
  roomProjection,
  useRoomLiveStore,
  type RoomKernelSyncProjection,
} from '../state/live-store';
import { RoomStartActionGate, roomRootRequiresStartAction } from './RoomStartActionGate';
import { roomPublicToolResultView } from './room-tool-presentation';

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
  kernelRootsById?: RoomKernelProjection['rootsById'];
  kernelDispatchesById?: RoomKernelProjection['dispatchesById'];
  kernelTasksById?: RoomKernelProjection['tasksById'];
  kernelTaskUpdatedAtMsById?: RoomKernelProjection['taskUpdatedAtMsById'];
  kernelReceiptsById?: RoomKernelProjection['receiptsById'];
  kernelSync?: RoomKernelSyncProjection;
  roomSyncState?: 'recovering' | 'failed' | 'synced';
  subagentsByTaskId?: Record<string, RoomTaskSubagentRun[]>;
  startingRootIds?: ReadonlySet<string>;
  onStartExecution?: (rootId: string) => void;
  onAbortTurn?: (rootId: string) => void;
  retryingRootIds?: ReadonlySet<string>;
  retryingTurn?: boolean;
  onRetryTurn?: (message: string) => void;
  onRetryRoot?: (rootId: string) => void;
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
  kernelRootsById,
  kernelDispatchesById,
  kernelTasksById,
  kernelTaskUpdatedAtMsById,
  kernelReceiptsById,
  kernelSync,
  roomSyncState,
  subagentsByTaskId = {},
  startingRootIds = new Set(),
  onStartExecution,
  abortingTurnIds = new Set(),
  retryingRootIds = new Set(),
  onAbortTurn,
  retryingTurn = false,
  onRetryTurn,
  onRetryRoot,
  onAnswerQuestion,
}: RoomTurnProps) {
  useRoomLiveStore((state) => (
    providedProjection ? 0 : state.turnRevisions[roomId]?.[turnId] ?? 0
  ));
  const projection = providedProjection ?? roomProjection(roomId);
  const turn = projection.turnsById[turnId];
  const previousTurnStatus = usePrevious(turn?.status);
  const nowMs = useRoomTaskUpdateClock(Boolean(
    turn && ['queued', 'running'].includes(turn.status),
  ));
  // Room/session lifecycle events may legitimately have no public Root. They
  // belong in the execution ledger, never as a synthetic Post in the chat.
  if (!turnId || turnId === 'unscoped' || !turn) return null;
  const { activities, lanes, messageIds, userMessageIds } = selectRoomTurnExecution(
    projection,
    turnId,
  );
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
  const kernelRoot = kernelRootsById?.[rootId];
  const requiresStartAction = roomRootRequiresStartAction(
    kernelRoot,
    Object.values(kernelReceiptsById ?? {}),
  );
  const pendingQuestion = projection.pendingUserQuestion?.rootId === rootId
    ? projection.pendingUserQuestion
    : undefined;
  const kernelRootState = kernelRoot?.state;
  const reporterSummaryRequired = Boolean(
    rootTerminal && kernelRoot?.reporterParticipantId,
  );
  const reporterSummaryId = reporterSummaryRequired
    ? turn.messageIds
        .map((messageId) => projection.messagesById[messageId])
        .filter((message) => (
          message?.projectionKind !== 'execution'
          && message?.postKind === 'result'
          && message.participantId === kernelRoot?.reporterParticipantId
        ))
        .sort((left, right) => right!.createdAtMs - left!.createdAtMs)[0]?.id ?? ''
    : '';
  const conversationMessages = roomVisibleConversationMessages(
    messageIds
      .map((messageId) => projection.messagesById[messageId])
      .filter((message): message is RoomMessageProjection => Boolean(message)),
  ).filter((message) => (
    !reporterSummaryRequired
    || message.postKind !== 'result'
    || message.id === reporterSummaryId
  ));
  const finalAlignmentId = [...conversationMessages].reverse().find((message) => (
    message.role === 'assistant' && message.postKind === 'alignment'
  ))?.id ?? '';
  const rootBlocked = kernelRootState === 'blocked';
  const rootActive = !rootBlocked
    && (kernelRootState
      ? ['pending', 'running', 'waiting'].includes(kernelRootState)
      : ['queued', 'running'].includes(turn.status) && rootHasActiveLane)
    && !pendingAction
    && !requiresStartAction;
  const rootStopping = abortingTurnIds.has(rootId);
  const rootRetrying = retryingRootIds.has(rootId);
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
    reporterSummaryRequired,
    reporterSummaryId,
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
  const startActionGate = requiresStartAction && onStartExecution
    ? <RoomStartActionGate
        onStart={() => onStartExecution(rootId)}
        starting={startingRootIds.has(rootId)}
      />
    : null;
  return <article className="room-turn" data-turn-status={turn.status}>
    {conversationMessages.map((message) => {
      if (message.role === 'user') {
        return <RoomUserPost key={message.id} message={message} roomId={projection.roomId} />;
      }
      const lane = lanes.find((candidate) => candidate.messageIds.includes(message.id));
      const participant = room?.participants.find((item) => item.id === message.participantId);
      const persona = personas.find((item) => (
        item.roleId === participant?.roleId && item.version === participant.roleVersion
      ));
      const taskId = lane?.dispatchId
        ? kernelDispatchesById?.[lane.dispatchId]?.taskId ?? ''
        : '';
      const freshness = lane
        ? roomLaneFreshness(
            lane,
            projection,
            turn,
            nowMs,
            kernelSync,
            roomSyncState,
            taskId ? kernelTaskUpdatedAtMsById?.[taskId] : undefined,
          )
        : roomFallbackFreshness(message.createdAtMs, nowMs, kernelSync, roomSyncState);
      return <Fragment key={message.id}>
        <RoomParticipantPost
          activeWait={
            message.postKind === 'wait'
            && !rootTerminal
            && (!message.question || pendingQuestion?.postId === message.id)
          }
          evidence={roomResponseEvidenceForPost(message, responseUsageActivities)}
          message={message}
          motionFresh={freshness.state === 'fresh'}
          onAnswerQuestion={onAnswerQuestion}
          participant={participant}
          participants={room?.participants ?? []}
          pendingQuestion={pendingQuestion?.postId === message.id ? pendingQuestion : undefined}
          persona={persona}
          showEvidence={Boolean(roomTerminalPostLabels[message.postKind ?? ''])}
          turnStartedAtMs={turn.createdAtMs}
        />
        {message.id === finalAlignmentId ? startActionGate : null}
      </Fragment>;
    })}
    {rootBlocked ? <div className="room-turn__root-control" data-state="blocked" role="alert">
      <span><CircleAlert size={14} /><small>这轮协作因伙伴运行失败而暂停；继续会只重做失败的部分，并保留已完成的工作。</small></span>
      <div className="room-turn__root-actions">
        {onRetryRoot ? <Button
          variant="secondary"
          size="small"
          leadingIcon={rootRetrying ? <LoaderCircle className="ui-spin" size={14} /> : <RotateCcw size={14} />}
          disabled={rootRetrying || rootStopping}
          onClick={() => onRetryRoot(rootId)}
        >{rootRetrying ? '正在继续' : '继续任务'}</Button> : null}
        {onAbortTurn ? <Button
          variant="danger"
          size="small"
          leadingIcon={rootStopping ? <LoaderCircle className="ui-spin" size={14} /> : <CircleStop size={14} />}
          disabled={rootRetrying || rootStopping}
          onClick={() => onAbortTurn(rootId)}
        >{rootStopping ? '正在停止' : '停止任务'}</Button> : null}
      </div>
    </div> : null}
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
    {lanes.map((lane) => {
      const participant = room?.participants.find((item) => item.id === lane.participantId);
      const persona = personas.find((item) => (
        item.roleId === participant?.roleId && item.version === participant.roleVersion
      ));
      const messages = lane.messageIds
        .map((id) => projection.messagesById[id])
        .filter((message): message is RoomMessageProjection => Boolean(message));
      const visibleMessages = roomVisibleConversationMessages(messages).filter((message) => (
        !reporterSummaryRequired
        || message.postKind !== 'result'
        || message.id === reporterSummaryId
      ));
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
      const laneTaskId = lane.dispatchId
        ? kernelDispatchesById?.[lane.dispatchId]?.taskId ?? ''
        : '';
      const laneFreshness = roomLaneFreshness(
        lane,
        projection,
        turn,
        nowMs,
        kernelSync,
        roomSyncState,
        laneTaskId ? kernelTaskUpdatedAtMsById?.[laneTaskId] : undefined,
      );
      const laneMotionActive = laneActive
        && !laneAction
        && laneFreshness.state === 'fresh';
      const laneOutcome = visibleMessages.reduce((outcome, message) => (
        roomTerminalPostLabels[message.postKind ?? '']
          ? message.postKind ?? outcome
          : outcome
      ), '');
      const laneComplete = (laneTerminal || Boolean(laneOutcome)) && !laneFailed && !laneAborted;
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
                : laneActive
                  ? '执行中'
                  : '等待后续';
      const statusLabel = laneActive && !laneAction && laneFreshness.state === 'disconnected'
        ? '状态可能过期'
        : laneActive && !laneAction && laneFreshness.state === 'stale'
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
                : laneActive
                  ? 'running'
                  : laneComplete
                    ? 'completed'
                    : 'waiting';
      const laneWork = roomLaneWorkSummary(
        lane.activities,
        participant?.displayName,
        laneState,
      );
      const laneTask = laneTaskId ? kernelTasksById?.[laneTaskId] : undefined;
      const laneSubagents = laneTaskId ? subagentsByTaskId[laneTaskId] ?? [] : [];
      return <section
        className="room-agent-lane"
        data-motion={laneActive && !laneAction ? laneFreshness.state : 'settled'}
        data-outcome={laneOutcome || undefined}
        data-state={laneState}
        key={lane.key}
      >
        <header>
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
            <strong className="room-agent-lane__task">{laneWork.title}</strong>
            <small className="room-agent-lane__progress">{laneWork.detail}</small>
          </span>
          <RoomLaneTiming
            freshness={laneFreshness}
            nowMs={nowMs}
            startedAtMs={turn.createdAtMs}
            endedAtMs={laneActive && !laneAction ? undefined : turn.updatedAtMs}
          />
        </header>
        {lane.activities.length || (laneTask && roomTaskWorkspaceLifecycleView(laneTask)) ? <ActivityLog
          activities={lane.activities}
          active={laneActive && !laneAction}
          motionActive={laneMotionActive}
          participantName={participant?.displayName}
          attention={laneState === 'failed' || laneState === 'aborted'}
          workspaceTask={laneTask}
          workspaceUpdatedAtMs={laneTaskId
            ? kernelTaskUpdatedAtMsById?.[laneTaskId]
            : undefined}
        /> : null}
        {laneSubagents.length ? <RoomTaskSubagentRuns
          heading={laneTask?.objective || `${participant?.displayName ?? '这位伙伴'}的临时协作者`}
          runs={laneSubagents}
        /> : null}
        {!lane.activities.length && laneActive && !messages.length ? <div className="room-agent-lane__waiting">
          {laneMotionActive ? <LoaderCircle size={14} /> : <Clock3 size={14} />}
          <span>{laneMotionActive
            ? participant
              ? `${participant.displayName} 已接手，正在准备`
              : '消息已经送达，正在请合适的伙伴回应'
            : laneFreshness.detail}
          </span>
        </div> : null}
        {!terminalIssue && (laneFailed || laneAborted) && !visibleMessages.length ? (
          <p className="room-agent-lane__failure">
            {laneFailed
              ? publicFailure
              : '这位伙伴的任务已经停止。'}
          </p>
        ) : null}
      </section>;
    })}
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

function RoomParticipantPost({
  message,
  participant,
  persona,
  motionFresh,
  ...postProps
}: {
  message: RoomMessageProjection;
  participant?: TimelineParticipant;
  persona?: AgentPersonaV1;
  motionFresh: boolean;
  evidence?: RoomResponseEvidence;
  showEvidence: boolean;
  participants: readonly TimelineParticipant[];
  turnStartedAtMs: number;
  activeWait: boolean;
  pendingQuestion?: PendingRoomQuestion;
  onAnswerQuestion?: (
    question: PendingRoomQuestion,
    value: string,
  ) => Promise<boolean>;
}) {
  const displayName = participant?.displayName ?? persona?.displayName ?? '协作伙伴';
  const presence = message.status === 'streaming'
    ? motionFresh ? 'thinking' : 'listening'
    : message.status === 'failed' || message.status === 'aborted'
      ? 'warning'
      : 'done';
  return <article
    className="room-participant-message room-conversation-post"
    data-motion={motionFresh ? 'fresh' : 'paused'}
    data-room-message-id={message.id}
    data-status={message.status}
  >
    <PersonaAvatar
      fallbackName={displayName}
      persona={persona}
      presence={presence}
      size="small"
    />
    <div>
      <header>
        <strong>{displayName}</strong>
        {message.status === 'streaming'
          ? <small>{motionFresh ? '正在回复' : '状态可能过期'}</small>
          : null}
      </header>
      <RoomLanePost
        {...postProps}
        message={message}
        streamingMotion={motionFresh}
      />
    </div>
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
  const digest = roomActivityDigest(activities);
  let focus = activities.at(-1);
  for (let index = activities.length - 1; index >= 0; index -= 1) {
    const candidate = activities[index];
    if (candidate && ['running', 'waiting', 'failed', 'aborted'].includes(
      roomActivityDisplayStatus(candidate),
    )) {
      focus = candidate;
      break;
    }
  }
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
  workspaceTask,
  workspaceUpdatedAtMs,
}: {
  activities: RoomActivityProjection[];
  active: boolean;
  motionActive: boolean;
  attention: boolean;
  participantName?: string;
  workspaceTask?: RoomTaskV3;
  workspaceUpdatedAtMs?: number;
}) {
  const workspaceView = workspaceTask
    ? roomTaskWorkspaceLifecycleView(workspaceTask)
    : undefined;
  const effectiveAttention = attention || workspaceView?.attention === true;
  const [open, setOpen] = useState(active || effectiveAttention);
  const [arrivingActivityIds, setArrivingActivityIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const previousActive = useRef(active);
  const previousActivitySignatures = useRef<Map<string, string> | null>(null);
  const publicActivities = activities.filter((activity) => {
    if (textValue(activity.payload.sourceEventType) !== 'reasoning_summary') return true;
    return textValue(activity.payload.source) === 'provider_reasoning_summary';
  });
  const activityContentKey = publicActivities.map((activity) => (
    `${activity.id}:${activity.status}:${activity.updatedAtMs ?? activity.createdAtMs}:${activity.summary}`
  )).join('\u001f');
  const workspaceContentKey = workspaceTask && workspaceView
    ? `workspace:${workspaceTask.taskId}:${workspaceTask.revision}:${workspaceTask.workspaceLifecycleState}:${workspaceTask.workspaceAttentionRequired ?? ''}`
    : '';
  const contentKey = `${activityContentKey}\u001f${workspaceContentKey}`;
  const { onScroll, scrollRef } = useAutoFollowScroll<HTMLDivElement>(
    contentKey,
    motionActive && open,
  );
  useEffect(() => {
    const nextSignatures = new Map(publicActivities.map((activity) => [
      activity.id,
      `${activity.status}:${activity.updatedAtMs ?? activity.createdAtMs}:${activity.summary}`,
    ]));
    if (workspaceTask && workspaceView) {
      nextSignatures.set(
        `workspace:${workspaceTask.taskId}`,
        `${workspaceTask.revision}:${workspaceTask.workspaceLifecycleState}:${workspaceTask.workspaceAttentionRequired ?? ''}`,
      );
    }
    const previousSignatures = previousActivitySignatures.current;
    previousActivitySignatures.current = nextSignatures;
    if (!previousSignatures) return;
    const arrivingIds = new Set(
      [...nextSignatures].flatMap(([activityId, signature]) => (
        previousSignatures.get(activityId) === signature ? [] : [activityId]
      )),
    );
    if (!arrivingIds.size) return;
    setArrivingActivityIds(arrivingIds);
    const timer = window.setTimeout(() => setArrivingActivityIds(new Set()), 280);
    return () => window.clearTimeout(timer);
  }, [contentKey]);
  useEffect(() => {
    const wasActive = previousActive.current;
    previousActive.current = active;
    if (active && !wasActive) {
      setOpen(true);
    } else if (!active && wasActive) {
      setOpen(effectiveAttention);
    } else if (effectiveAttention) {
      setOpen(true);
    }
  }, [active, effectiveAttention]);
  if (!publicActivities.length && !workspaceView) return null;
  const digest = publicActivities.length
    ? roomActivityDigest(publicActivities)
    : {
        title: workspaceView?.title ?? '工作区进展',
        detail: '1 条权威任务更新',
      };
  return <details
    className="room-agent-lane__activity"
    data-motion={motionActive ? 'fresh' : 'paused'}
    data-state={effectiveAttention ? 'attention' : active ? 'running' : 'settled'}
    open={open}
  >
    <summary
      aria-expanded={open}
      onClick={(event) => toggleDisclosurePreservingAnchor(event, setOpen)}
      onKeyDown={(event) => toggleDisclosureOnKeyPreservingAnchor(event, setOpen)}
    >
      <Wrench size={14} />
      <span>
        <strong>{digest.title}</strong>
        <small>{digest.detail}</small>
      </span>
      <ChevronRight aria-hidden="true" size={14} />
    </summary>
    <div
      aria-label={`伙伴自述与运行记录：${participantName ?? '协作成员'}`}
      aria-live={motionActive ? 'polite' : 'off'}
      className="room-agent-lane__activity-feed"
      onScroll={onScroll}
      ref={scrollRef}
      role="log"
      tabIndex={0}
    >{publicActivities.map((activity) => {
      const displayStatus = roomActivityDisplayStatus(activity);
      const sourceEventType = textValue(activity.payload.sourceEventType);
      const arriving = motionActive && arrivingActivityIds.has(activity.id);
      if (['tool_started', 'tool_progress', 'tool_finished'].includes(sourceEventType)) {
        return <RoomToolActivity activity={activity} arriving={arriving} key={activity.id} />;
      }
      if (sourceEventType === 'reasoning_summary') {
        const reasoningItems = Array.isArray(activity.payload.items)
          ? activity.payload.items
              .filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
              .slice(0, 12)
          : [];
        const summary = publicActivitySummary(activity.summary, activity.kind)
          || reasoningItems.at(-1)
          || '';
        if (!summary) return null;
        return <article
          className="room-reasoning-summary"
          data-arriving={arriving || undefined}
          data-state={displayStatus}
          key={activity.id}
        >
          <Sparkles aria-hidden="true" size={14} />
          <span>
            <small><span className="room-activity-provenance">伙伴自述</span> · 工作摘要 · <RoomActivityTimestamp activity={activity} /></small>
            <strong>{summary}</strong>
            {reasoningItems.length ? <details className="room-reasoning-summary__details">
              <summary>查看工作要点</summary>
              <ol>
                {reasoningItems.map((item, index) => (
                  <li key={`${activity.id}:reasoning:${index}`}>{item}</li>
                ))}
              </ol>
            </details> : null}
          </span>
        </article>;
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
    })}
    {workspaceTask && workspaceView ? <RoomTaskWorkspaceActivity
      arriving={arrivingActivityIds.has(`workspace:${workspaceTask.taskId}`)}
      task={workspaceTask}
      updatedAtMs={workspaceUpdatedAtMs}
      view={workspaceView}
    /> : null}</div>
  </details>;
}

function RoomTaskWorkspaceActivity({
  arriving,
  task,
  updatedAtMs,
  view,
}: {
  arriving: boolean;
  task: RoomTaskV3;
  updatedAtMs?: number;
  view: NonNullable<ReturnType<typeof roomTaskWorkspaceLifecycleView>>;
}) {
  return <div
    className="room-agent-activity room-agent-activity--workspace"
    data-arriving={arriving || undefined}
    data-state={view.state}
    data-workspace-lifecycle={task.workspaceLifecycleState}
  >
    {view.state === 'running'
      ? <LoaderCircle aria-hidden="true" size={14} />
      : view.state === 'failed'
        ? <CircleAlert aria-hidden="true" size={14} />
        : view.state === 'waiting'
          ? <Clock3 aria-hidden="true" size={14} />
          : view.state === 'aborted'
            ? <CircleStop aria-hidden="true" size={14} />
            : <CheckCircle2 aria-hidden="true" size={14} />}
    <span>
      <strong>{view.title}</strong>
      <small>
        <span className="room-activity-provenance">任务记录</span>
        {' · '}{view.attention ? '需要处理 · ' : ''}{view.detail} · {' '}
        <RoomTaskUpdatedAt updatedAtMs={updatedAtMs} />
      </small>
    </span>
  </div>;
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
  reporterSummaryRequired = false,
  reporterSummaryId = '',
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
      && (
        !reporterSummaryRequired
        || message.postKind !== 'result'
        || message.id === reporterSummaryId
      )
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

function roomActivityProvenanceLabel(activity: RoomActivityProjection): '伙伴自述' | '运行记录' {
  const sourceEventType = textValue(activity.payload.sourceEventType);
  const activityKind = textValue(activity.payload.activityKind);
  if (
    ['reasoning_summary', 'current_progress', 'progress'].includes(sourceEventType)
    || ['intercom', 'work'].includes(activityKind)
  ) return '伙伴自述';
  return '运行记录';
}

function roomActivityDigest(
  activities: RoomActivityProjection[],
): { title: string; detail: string } {
  const labels = activities.flatMap((activity) => {
    const sourceEventType = textValue(activity.payload.sourceEventType);
    if (sourceEventType.startsWith('tool_')) {
      const toolId = textValue(activity.payload.toolName);
      return [publicToolName(toolId, textValue(activity.payload.displayName))];
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
}: {
  activity: RoomActivityProjection;
  arriving: boolean;
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
            ? `${detailView.toolLabel}执行失败`
            : activity.status === 'aborted'
              ? `${detailView.toolLabel}已停止`
              : detailView.summary}</strong>
          <small><span className="room-activity-provenance">运行记录</span> · {detailView.toolLabel} · {roomToolStatusLabel(activity.status)}{roomToolProgressCount(payload) > 1 ? ` · ${roomToolProgressCount(payload)} 次更新` : ''} · <RoomActivityTimestamp activity={activity} /></small>
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
  kernelSync?: RoomKernelSyncProjection,
  roomSyncState?: 'recovering' | 'failed' | 'synced',
  workspaceUpdatedAtMs?: number,
): RoomLaneFreshness {
  const updateTimes = [
    ...lane.activities.map((activity) => activity.updatedAtMs ?? activity.createdAtMs),
    ...lane.messageIds.flatMap((messageId) => {
      const message = projection.messagesById[messageId];
      return message ? [message.completedAtMs ?? message.createdAtMs] : [];
    }),
    ...(workspaceUpdatedAtMs === undefined ? [] : [workspaceUpdatedAtMs]),
  ];
  return roomFallbackFreshness(
    updateTimes.length ? Math.max(...updateTimes) : turn.updatedAtMs,
    nowMs,
    kernelSync,
    roomSyncState,
  );
}

function roomFallbackFreshness(
  updatedAtMs: number,
  nowMs: number,
  kernelSync?: RoomKernelSyncProjection,
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
  if (kernelSync && kernelSync.state !== 'synced') {
    return {
      state: 'disconnected',
      updatedAtMs,
      detail: kernelSync.detail.trim() || '实时更新暂时中断，状态可能过期',
    };
  }
  if (Math.max(0, nowMs - updatedAtMs) > roomActiveEventFreshnessMs) {
    return {
      state: 'stale',
      updatedAtMs,
      detail: '最近没有新的权威进展，状态可能过期',
    };
  }
  return { state: 'fresh', updatedAtMs, detail: '实时进展已同步' };
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
  const toolName = textValue(payload.displayName) || textValue(payload.toolName) || '工具';
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

function textValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function agentSessionHref(sessionId: string): string {
  return `#/agent?${new URLSearchParams({ session: sessionId })}`;
}
